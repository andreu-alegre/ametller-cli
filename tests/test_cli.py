from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from ametller.catalog import normalize, parse_basket, price_basket
from ametller.cli import main, parser
from ametller.client import Client, NoRedirect, parse_site_data
from ametller.storage import Error, Storage


def product(product_id="2351", price=2.89, **changes):
    return {"id": product_id, "name": "Producto", "price": price, "currency": "EUR",
            "pricePerUnit": 2.89, "unitMeasure": "KG", "unitQuantity": 1,
            "minOrderQuantity": 1, "stepQuantity": 1, "inventory": {"orderable": True}, **changes}


class Catalog:
    def __init__(self, products):
        self.data = products

    def products(self, ids):
        return [item for item in self.data if item["id"] in ids]


class BasketTests(unittest.TestCase):
    def test_weighted_item_uses_selling_unit_instead_of_kilo_price(self):
        catalog = Catalog([product("16490", 0.90, pricePerUnit=5, unitQuantity=0.18)])
        result = price_basket(catalog, {"16490": "3"})
        self.assertEqual(result["subtotal_cents"], 270)
        self.assertFalse(result["shipping_included"])
        self.assertEqual(result["scope"], "local")

    def test_fractional_quantity_only_when_sku_accepts_it(self):
        catalog = Catalog([product(stepQuantity=0.5, minOrderQuantity=0.5)])
        self.assertEqual(price_basket(catalog, {"2351": "0.5"})["subtotal_cents"], 145)
        with self.assertRaises(Error):
            price_basket(Catalog([product()]), {"2351": "0.5"})

    def test_missing_price_or_availability_fails_closed(self):
        for data in ([], [product(price=None)], [product(inventory={})], [product(inventory={"orderable": False})]):
            with self.subTest(data=data), self.assertRaises(Error):
                price_basket(Catalog(data), {"2351": "1"})

    def test_bad_quantities_and_duplicate_ids_are_rejected(self):
        for text in ("2351 NaN", "2351 -1", "2351 1\n2351 2", "2351 Infinity", "2351 10001", "../../secret 1"):
            with self.subTest(text=text), self.assertRaises(Error):
                parse_basket(text)
        self.assertEqual(parse_basket("# compra\n2351 2 # yogur\n"), {"2351": "2"})

    def test_budget_failure_preserves_existing_cart(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = Storage(directory)
            storage.write("cart.json", {"2351": "1"})
            before = (Path(directory) / "cart.json").read_bytes()
            stdout, stderr = StringIO(), StringIO()
            with patch("ametller.cli.Client", return_value=Catalog([product()])), redirect_stdout(stdout), redirect_stderr(stderr):
                status = main(["--json", "cart", "add", "2351", "1", "--max", "5", "--state-dir", directory])
            self.assertEqual(status, 1)
            self.assertEqual(stdout.getvalue(), "")
            self.assertIn("Presupuesto superado", json.loads(stderr.getvalue())["error"])
            self.assertEqual((Path(directory) / "cart.json").read_bytes(), before)

    def test_set_many_failure_is_atomic_and_clear_is_offline(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = Storage(directory)
            storage.write("cart.json", {"2351": "1"})
            file = Path(directory) / "basket.txt"
            file.write_text("2351 2\nmissing 1\n")
            with patch("ametller.cli.Client", return_value=Catalog([product()])), redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                self.assertEqual(main(["cart", "set-many", "-f", str(file), "--state-dir", directory]), 1)
                self.assertEqual(storage.read("cart.json"), {"2351": "1"})
                self.assertEqual(main(["cart", "clear", "--state-dir", directory]), 0)
                self.assertEqual(storage.read("cart.json"), {})

    def test_checkout_prepare_never_submits_or_syncs(self):
        with tempfile.TemporaryDirectory() as directory:
            Storage(directory).write("cart.json", {"2351": "1"})
            output = StringIO()
            with patch("ametller.cli.Client", return_value=Catalog([product()])), redirect_stdout(output):
                self.assertEqual(main(["checkout", "prepare", "--state-dir", directory, "--json"]), 0)
            result = json.loads(output.getvalue())
            self.assertFalse(result["order_submitted"])
            self.assertFalse(result["synced_to_store"])

    def test_global_options_survive_every_command_position(self):
        for argv in (["--json", "--lang", "ca", "cart", "get"],
                     ["cart", "--json", "--lang", "ca", "get"],
                     ["cart", "get", "--json", "--lang", "ca"]):
            args = parser().parse_args(argv)
            self.assertTrue(args.json)
            self.assertEqual(args.lang, "ca")

    def test_allergens_remain_source_codes_and_absent_price_is_null(self):
        result = normalize(product(price=None, c_ao_allergens=["1"]))
        self.assertIsNone(result["price_cents"])
        self.assertEqual(result["allergen_codes"], ["1"])


class Response:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self):
        return self.body


class NetworkTests(unittest.TestCase):
    def test_no_redirect_follows_auth_code(self):
        self.assertIsNone(NoRedirect().redirect_request(None, None, 303, "See other", {}, "https://example.com"))

    def test_site_config_is_discovered_without_hardcoded_client_ids(self):
        content = {"__CONFIG__": {"app": {"commerceAPI": {"parameters": {
            "clientId": "public-client", "organizationId": "test-org", "siteId": "ametller"}}}}}
        html = '<script type="application/json" id="mobify-data">' + json.dumps(content) + '</script>'
        self.assertEqual(parse_site_data(html), content)
        with self.assertRaises(Error):
            parse_site_data("<html>cambio de plataforma</html>")

    def test_get_honors_retry_after_and_post_is_not_retried(self):
        error = HTTPError("https://example.com", 429, "limited", {"Retry-After": "2"}, None)
        with tempfile.TemporaryDirectory() as directory:
            client = Client(storage=Storage(directory))
            with patch.object(client.opener, "open", side_effect=[error, Response(b'{}')]) as request, patch("ametller.client.time.sleep") as sleep:
                self.assertEqual(client.request("https://example.com"), b'{}')
                sleep.assert_called_once_with(2)
                self.assertEqual(request.call_count, 2)
            with patch.object(client.opener, "open", side_effect=error) as request, self.assertRaises(Error):
                client.request("https://example.com", method="POST", body=b"code=secret")
            self.assertEqual(request.call_count, 1)

    def test_private_state_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state"
            Storage(path).write("session.json", {"access_token": "synthetic-test-value"})
            self.assertEqual(path.stat().st_mode & 0o777, 0o700)
            self.assertEqual((path / "session.json").stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
