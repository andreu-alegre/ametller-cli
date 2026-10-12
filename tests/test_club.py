from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

from ametller.cli import main
from ametller.club import COUPONS_URL, SESSION_FILE, MobileClub, normalize_coupon
from ametller.client import NoRedirect
from ametller.storage import Error, Storage

AUTH = "Bearer " + "synthetic-token-for-tests-only"
COUPON = {"id": "test-coupon", "title": " Oferta ficticia ", "status": "inactive",
          "discount": 5.0, "discount_type": "PERCENT", "date_to": "2030-01-01T00:00:00+0000",
          "ean_code": "synthetic-redeem-code"}


class Response:
    status = 200
    def __init__(self, body=None): self.body = [COUPON] if body is None else body
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self, limit): return json.dumps(self.body).encode()


def capture(directory, **updates):
    data = {"method": "GET", "url": COUPONS_URL, "response_status": 200,
            "request_headers": {"Authorization": AUTH, "Cookie": "synthetic-cookie"}}
    data.update(updates)
    path = Path(directory) / "private-capture.json"
    path.write_text(json.dumps(data)); path.chmod(0o600)
    return path


class ClubTests(unittest.TestCase):
    def test_import_verifies_before_save_and_keeps_only_minimum_auth(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = Storage(Path(directory)/"state")
            mobile = MobileClub(storage)
            mobile.opener = Mock(); mobile.opener.open.return_value = Response()
            result = mobile.import_capture(capture(directory))
            self.assertTrue(result["connected"])
            stored = storage.read(SESSION_FILE)
            self.assertEqual(set(stored), {"schema_version", "authorization", "connected_at"})
            self.assertEqual((storage.root/SESSION_FILE).stat().st_mode & 0o777, 0o600)
            self.assertEqual(storage.root.stat().st_mode & 0o777, 0o700)
            self.assertNotIn(AUTH, json.dumps(result))
            self.assertFalse(result["cookies_saved"])

    def test_failed_import_preserves_connection_and_error_does_not_echo_token(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = Storage(Path(directory)/"state"); storage.write(SESSION_FILE, {"previous": True})
            mobile = MobileClub(storage); mobile.opener = Mock()
            mobile.opener.open.side_effect = HTTPError(COUPONS_URL, 401, AUTH, {}, StringIO(AUTH))
            with self.assertRaises(Error) as error: mobile.import_capture(capture(directory))
            self.assertNotIn(AUTH, str(error.exception))
            self.assertEqual(storage.read(SESSION_FILE), {"previous": True})
            self.assertEqual(mobile.opener.open.call_count, 1)

    def test_foreign_url_method_and_unprivate_file_fail_before_network(self):
        with tempfile.TemporaryDirectory() as directory:
            mobile = MobileClub(Storage(Path(directory)/"state")); mobile.opener = Mock()
            for updates in ({"url": "https://other.example/api/mobile/v3/coupons"},
                            {"url": COUPONS_URL + "?user=test"}, {"method": "POST"},
                            {"request_headers": {"Authorization": AUTH+"\r\nx: injected"}}):
                with self.subTest(updates=updates), self.assertRaises(Error):
                    mobile.import_capture(capture(directory, **updates))
            file = capture(directory); file.chmod(0o644)
            with self.assertRaises(Error): mobile.import_capture(file)
            mobile.opener.open.assert_not_called()
            self.assertFalse((Path(directory)/"state"/SESSION_FILE).exists())

    def test_session_cannot_be_written_under_source_repository(self):
        from ametller.club import PROJECT
        storage = Storage(PROJECT/".state"/"forbidden-club-test")
        with self.assertRaises(Error): storage.write(SESSION_FILE, {"authorization": AUTH})
        self.assertFalse((storage.root/SESSION_FILE).exists())

    def test_only_fixed_get_and_required_locale_are_sent_without_cookie(self):
        mobile = MobileClub(lang="ca")
        redirect = next(handler for handler in mobile.opener.handlers if isinstance(handler, NoRedirect))
        mobile.opener = Mock()
        mobile.opener.open.return_value = Response()
        mobile.fetch(AUTH)
        request = mobile.opener.open.call_args.args[0]
        self.assertEqual(request.full_url, COUPONS_URL)
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(request.get_header("Accept-language"), "ca")
        self.assertEqual(request.get_header("Authorization"), AUTH)
        self.assertIsNone(request.get_header("Cookie"))
        self.assertIsNone(request.data)
        self.assertIsNone(redirect.redirect_request(None,None,302,"",{},"https://other.example"))

    def test_unknown_status_fields_and_redeem_code_are_not_invented_or_exposed(self):
        coupon = normalize_coupon({**COUPON, "status": "future-state", "discount": float('nan')})
        self.assertIsNone(coupon["active"])
        self.assertIsNone(coupon["discount"])
        self.assertIsNone(coupon["date_from"])
        self.assertNotIn("ean_code", coupon)
        self.assertEqual(coupon["title"], "Oferta ficticia")

    def test_shape_change_and_duplicate_coupons_are_rejected(self):
        mobile = MobileClub(); mobile.opener = Mock()
        for body in ({"coupons": [COUPON]}, [COUPON, COUPON], [{"id":"x","title":"test"}]):
            with self.subTest(body=body), self.assertRaises(Error):
                mobile.opener.open.return_value = Response(body)
                mobile.fetch(AUTH)

    def test_missing_mobile_account_never_reads_web_account_or_network(self):
        with tempfile.TemporaryDirectory() as directory:
            Storage(directory).write("account.json", {"access_token": "synthetic-web-token"})
            mobile = MobileClub(Storage(directory))
            with patch.object(mobile,"fetch") as fetch, self.assertRaises(Error): mobile.coupons()
            fetch.assert_not_called()
            self.assertFalse((Path(directory)/SESSION_FILE).exists())

    def test_selection_uses_verified_list_not_an_unobserved_detail_endpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = Storage(directory); storage.write(SESSION_FILE,{"schema_version":1,"authorization":AUTH})
            mobile = MobileClub(storage)
            with patch.object(mobile,"fetch",return_value=[COUPON]) as fetch:
                result = mobile.coupons(coupon_id="test-coupon",status="inactive")
                self.assertEqual(result["returned"],1)
                self.assertFalse(result["activation_supported"])
                self.assertFalse(result["basket_discount_verified"])
                self.assertFalse(result["order_submitted"])
                fetch.assert_called_once_with(AUTH)
                with self.assertRaises(Error): mobile.coupons(coupon_id="unknown")

    def test_cli_json_and_mobile_logout_preserve_web_account(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = Storage(directory)
            storage.write("account.json", {"access_token":"synthetic-web-token"})
            storage.write(SESSION_FILE, {"schema_version":1,"authorization":AUTH})
            output,error = StringIO(),StringIO()
            with patch("ametller.club.MobileClub.fetch",return_value=[COUPON]),redirect_stdout(output),redirect_stderr(error):
                self.assertEqual(main(["coupons","--json","--state-dir",directory]),0)
                self.assertEqual(json.loads(output.getvalue())["returned"],1)
                self.assertEqual(main(["club","logout","--state-dir",directory]),0)
            self.assertFalse((Path(directory)/SESSION_FILE).exists())
            self.assertEqual(storage.read("account.json"), {"access_token":"synthetic-web-token"})


@unittest.skipUnless(importlib.util.find_spec("mcp"), "Instala el extra mcp")
class ClubMCPTests(unittest.IsolatedAsyncioTestCase):
    async def test_personal_coupon_tool_reads_mobile_session_without_activation(self):
        from mcp import Client
        from ametller.mcpserver import create_server
        with tempfile.TemporaryDirectory() as directory:
            Storage(directory).write(SESSION_FILE, {"schema_version":1,"authorization":AUTH})
            with patch("ametller.club.MobileClub.fetch",return_value=[COUPON]):
                async with Client(create_server(directory)) as client:
                    tools = (await client.list_tools()).tools
                    coupon_tool=next(tool for tool in tools if tool.name=="list_personal_coupons")
                    self.assertTrue(coupon_tool.annotations.read_only_hint)
                    self.assertFalse(any("activate" in tool.name for tool in tools))
                    result=await client.call_tool('list_personal_coupons',{"status":"inactive"})
                    self.assertFalse(result.is_error)
                    self.assertEqual(result.structured_content["returned"],1)
                    self.assertNotIn(AUTH,json.dumps(result.structured_content))
