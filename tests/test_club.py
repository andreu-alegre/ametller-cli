from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import base64
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

from ametller.cli import main
from ametller.club import COUPONS_URL, LOGIN_URL, SESSION_FILE, PENDING_FILE, MobileClub, normalize_coupon, interactive_login, subject_hash
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
                self.assertTrue(result["activation_supported"])
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


def synthetic_authorization(email="member@example.test"):
    part = base64.urlsafe_b64encode(json.dumps({"sub":email}).encode()).decode().rstrip("=")
    return "Bearer synthetic-header." + part + ".synthetic-signature"


class MobileLoginActivationTests(unittest.TestCase):
    def setup_mobile(self, directory):
        storage=Storage(directory)
        storage.write(SESSION_FILE,{"schema_version":1,"authorization":synthetic_authorization()})
        mobile=MobileClub(storage); mobile.opener=Mock()
        return mobile,storage

    def test_login_matches_captured_basic_post_and_saves_only_verified_session(self):
        with tempfile.TemporaryDirectory() as directory:
            mobile,storage=self.setup_mobile(directory)
            password="synthetic-private-password"
            mobile.opener.open.side_effect=[Response({"token":synthetic_authorization(),"profile":"private-response"}),Response()]
            result=mobile.login("member@example.test",password)
            first,second=[call.args[0] for call in mobile.opener.open.call_args_list]
            self.assertEqual((first.full_url,first.get_method(),first.data),(LOGIN_URL,"POST",b""))
            expected="Basic "+base64.b64encode(("member@example.test:"+password).encode()).decode()
            self.assertEqual(first.get_header("Authorization"),expected)
            self.assertIsNone(first.get_header("Cookie"))
            self.assertEqual(second.full_url,COUPONS_URL)
            self.assertEqual(set(storage.read(SESSION_FILE)),{"schema_version","authorization","connected_at"})
            self.assertNotIn(password,json.dumps(result))
            self.assertNotIn(expected,(storage.root/SESSION_FILE).read_text())
            self.assertNotIn("private-response",(storage.root/SESSION_FILE).read_text())

    def test_rejected_or_wrong_identity_login_preserves_prior_session_without_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            mobile,storage=self.setup_mobile(directory); prior=storage.read(SESSION_FILE)
            mobile.opener.open.side_effect=HTTPError(LOGIN_URL,401,"private-password",{},StringIO("private-password"))
            with self.assertRaises(Error) as error: mobile.login("member@example.test","private-password")
            self.assertNotIn("private-password",str(error.exception))
            self.assertEqual(mobile.opener.open.call_count,1)
            self.assertEqual(storage.read(SESSION_FILE),prior)
            mobile.opener.open.side_effect=[Response({"token":synthetic_authorization("other@example.test")}),Response()]
            with self.assertRaises(Error): mobile.login("member@example.test","private-password")
            self.assertEqual(storage.read(SESSION_FILE),prior)

    def test_noninteractive_login_refuses_stdin_credentials(self):
        with patch("ametller.club.sys.stdin.isatty",return_value=False),patch("ametller.club.getpass.getpass") as prompt:
            with self.assertRaises(Error): interactive_login(Storage())
            prompt.assert_not_called()

    def test_terminal_without_secure_password_echo_aborts_before_login(self):
        import getpass
        import warnings
        def insecure_prompt(*args):
            warnings.warn("no secure echo", getpass.GetPassWarning)
            self.fail("No debe continuar con una contraseña visible")
        with patch("ametller.club.sys.stdin.isatty",return_value=True),patch("builtins.input",return_value="member@example.test"),patch("ametller.club.getpass.getpass",side_effect=insecure_prompt),patch("ametller.club.MobileClub.login") as login:
            with self.assertRaises(Error): interactive_login(Storage())
            login.assert_not_called()

    def test_source_repository_destination_rejects_login_before_network(self):
        from ametller.club import PROJECT
        mobile=MobileClub(Storage(PROJECT/".state"/"forbidden-login-test")); mobile.opener=Mock()
        with self.assertRaises(Error): mobile.login("member@example.test","private-password")
        mobile.opener.open.assert_not_called()
        self.assertFalse(mobile.storage.root.exists())

    def test_other_git_repository_rejects_login_before_network(self):
        with tempfile.TemporaryDirectory() as directory:
            repo=Path(directory)/"other-checkout"; repo.mkdir(); (repo/".git").write_text("gitdir: /synthetic/worktree")
            mobile=MobileClub(Storage(repo/"state")); mobile.opener=Mock()
            with self.assertRaises(Error): mobile.login("member@example.test","private-password")
            mobile.opener.open.assert_not_called()
            self.assertFalse(mobile.storage.root.exists())

    def test_generic_session_writer_protects_any_git_checkout(self):
        with tempfile.TemporaryDirectory() as directory:
            repo=Path(directory)/"other-checkout"; repo.mkdir(); (repo/".git").mkdir()
            storage=Storage(repo/"state")
            for name in (SESSION_FILE,PENDING_FILE,"account.json"):
                with self.subTest(name=name),self.assertRaises(Error): storage.write(name,{"secret":"synthetic-private"})
            self.assertFalse(storage.root.exists())

    def test_malformed_pending_blocks_login_before_replacing_session(self):
        with tempfile.TemporaryDirectory() as directory:
            mobile,storage=self.setup_mobile(directory); prior=storage.read(SESSION_FILE)
            storage.write(PENDING_FILE,{"schema_version":2,"subject_hash":subject_hash("member@example.test")})
            with self.assertRaises(Error): mobile.login("member@example.test","private-password")
            mobile.opener.open.assert_not_called()
            self.assertEqual(storage.read(SESSION_FILE),prior)

    def test_login_form_masks_password_and_clears_submission_without_saving_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            def serve(content,submit,*args):
                self.assertIn(b"type='password'",content)
                self.assertIn(b"autocomplete='off'",content)
                fields={"email":["member@example.test"],"password":["private-password"]}
                result=submit(fields); self.assertEqual(fields,{})
                return result
            with patch("ametller.details._serve_form",side_effect=serve),patch("ametller.club.MobileClub.login",return_value={"connected":True}) as login:
                self.assertTrue(interactive_login(Storage(directory),form=True)["connected"])
                login.assert_called_once_with("member@example.test","private-password")
            self.assertEqual(list(Path(directory).iterdir()),[])

    def test_activation_preview_and_already_active_never_post(self):
        with tempfile.TemporaryDirectory() as directory:
            mobile,storage=self.setup_mobile(directory)
            mobile.opener.open.return_value=Response()
            preview=mobile.activate("test-coupon")
            self.assertFalse(preview["post_sent"])
            self.assertTrue(preview["activation_needed"])
            self.assertFalse((storage.root/PENDING_FILE).exists())
            mobile.opener.open.return_value=Response([{**COUPON,"status":"active"}])
            actual=mobile.activate("test-coupon",apply=True)
            self.assertTrue(actual["already_active"])
            self.assertFalse(actual["post_sent"])
            self.assertTrue(all(call.args[0].get_method()=="GET" for call in mobile.opener.open.call_args_list))

    def test_activation_matches_captured_empty_post_and_checks_get_state(self):
        with tempfile.TemporaryDirectory() as directory:
            mobile,storage=self.setup_mobile(directory)
            active={**COUPON,"status":"active"}
            def respond(request,timeout):
                if request.get_method()=="POST":
                    self.assertTrue((storage.root/PENDING_FILE).exists())
                    return Response(active)
                return Response([COUPON] if mobile.opener.open.call_count==1 else [active])
            mobile.opener.open.side_effect=respond
            result=mobile.activate("test-coupon",apply=True)
            self.assertTrue(result["applied"])
            self.assertEqual(result["coupon"]["status"],"active")
            post=mobile.opener.open.call_args_list[1].args[0]
            self.assertEqual((post.full_url,post.get_method(),post.data),(COUPONS_URL+"/test-coupon/activate/","POST",b""))
            self.assertEqual(post.get_header("Authorization"),synthetic_authorization())
            self.assertFalse((storage.root/PENDING_FILE).exists())
            self.assertEqual(mobile.opener.open.call_count,3)

    def test_uncertain_activation_keeps_private_journal_and_blocks_second_post(self):
        with tempfile.TemporaryDirectory() as directory:
            mobile,storage=self.setup_mobile(directory)
            mobile.opener.open.side_effect=[Response(),URLError("private-sensitive-error")]
            with self.assertRaises(Error) as error: mobile.activate("test-coupon",apply=True)
            self.assertNotIn("private-sensitive-error",str(error.exception))
            self.assertEqual((storage.root/PENDING_FILE).stat().st_mode&0o777,0o600)
            self.assertNotIn(synthetic_authorization(),(storage.root/PENDING_FILE).read_text())
            mobile.opener.open.side_effect=None; mobile.opener.open.return_value=Response()
            with self.assertRaises(Error): mobile.activate("test-coupon",apply=True)
            self.assertEqual(sum(call.args[0].get_method()=="POST" for call in mobile.opener.open.call_args_list),1)
            mobile.opener.open.return_value=Response([{**COUPON,"status":"active"}])
            self.assertFalse(mobile.coupons()["activation_pending"])
            self.assertFalse((storage.root/PENDING_FILE).exists())

    def test_post_success_without_confirming_get_remains_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            mobile,storage=self.setup_mobile(directory)
            mobile.opener.open.side_effect=[Response(),Response({**COUPON,"status":"active"}),Response()]
            with self.assertRaises(Error): mobile.activate("test-coupon",apply=True)
            self.assertTrue((storage.root/PENDING_FILE).exists())

    def test_unknown_coupon_status_and_path_injection_never_write(self):
        with tempfile.TemporaryDirectory() as directory:
            mobile,storage=self.setup_mobile(directory)
            mobile.opener.open.return_value=Response([{**COUPON,"status":"expired"}])
            for target in ("test-coupon","../payments","test-coupon?x=1","missing"):
                with self.subTest(target=target),self.assertRaises(Error): mobile.activate(target,apply=True)
            self.assertTrue(all(call.args[0].get_method()=="GET" for call in mobile.opener.open.call_args_list))
            self.assertFalse((storage.root/PENDING_FILE).exists())

    def test_other_account_cannot_reconcile_pending_or_login_over_it(self):
        with tempfile.TemporaryDirectory() as directory:
            mobile,storage=self.setup_mobile(directory)
            storage.write(PENDING_FILE,{"schema_version":1,"coupon_id":"test-coupon","subject_hash":subject_hash("other@example.test"),"requested_status":"active"})
            with self.assertRaises(Error): mobile.login("member@example.test","private-password")
            mobile.opener.open.assert_not_called()
            mobile.opener.open.return_value=Response([{**COUPON,"status":"active"}])
            self.assertTrue(mobile.coupons()["activation_pending"])
            self.assertTrue((storage.root/PENDING_FILE).exists())

    def test_transport_rejects_foreign_endpoints_and_payment_routes(self):
        mobile=MobileClub(); mobile.opener=Mock()
        for url,method in (("https://other.example/login","POST"),(COUPONS_URL+"/test-coupon/pay/","POST"),(LOGIN_URL,"GET")):
            with self.subTest(url=url),self.assertRaises(Error): mobile._json(url,synthetic_authorization(),method)
        mobile.opener.open.assert_not_called()


@unittest.skipUnless(importlib.util.find_spec("mcp"), "Instala el extra mcp")
class ActivationMCPTests(unittest.IsolatedAsyncioTestCase):
    async def test_write_requires_enabled_server_and_confirmation_before_any_call(self):
        from mcp import Client
        from ametller.mcpserver import create_server
        with tempfile.TemporaryDirectory() as directory,patch("ametller.club.MobileClub.activate",return_value={"applied":True}) as activate:
            async with Client(create_server(directory)) as client:
                names={tool.name for tool in (await client.list_tools()).tools}
                self.assertIn("preview_coupon_activation",names)
                self.assertNotIn("activate_personal_coupon",names)
            async with Client(create_server(directory,allow_writes=True)) as client:
                rejected=await client.call_tool("activate_personal_coupon",{"coupon_id":"test-coupon"})
                self.assertTrue(rejected.is_error); activate.assert_not_called()
                approved=await client.call_tool("activate_personal_coupon",{"coupon_id":"test-coupon","confirmed":True})
                self.assertFalse(approved.is_error); activate.assert_called_once_with("test-coupon",True)
