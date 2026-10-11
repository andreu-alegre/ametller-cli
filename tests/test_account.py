import base64
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from ametller.account import AccountClient, extract_har, import_har, token_identity
from ametller.client import ConnectionFailure
from ametller.remote import RemoteCart
from ametller.storage import Error, Storage
from ametller.webcheckout import delivery_slots, slots_url
from test_cli import product

CONFIG = {"clientId": "public", "organizationId": "org", "siteId": "ametller"}


def jwt(customer="customer", guest=False, expiry=None):
    data = {"isb": "x::upn:" + ("Guest" if guest else "shopper") + "::chid:ametller::" + ("gcid:" if guest else "rcid:") + customer,
            "exp": expiry or time.time() + 3000}
    part = base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")
    return "eyJ0ZXN0Ijp0cnVlfQ." + part + ".synthetic"


def har(token, host="ametllerorigen.com"):
    return {"log": {"entries": [{"request": {"url": "https://" + host + "/mobify/proxy/api/customer/shopper-customers/v1/organizations/org/customers/customer",
                                                "headers": [{"name": "Authorization", "value": "Bearer " + token}],
                                                "postData": {"text": "password=never-save-this"}}, "response": {}}]}}


class AccountTests(unittest.TestCase):
    def test_import_rejects_guest_foreign_host_and_multiple_accounts(self):
        for data in (har(jwt(guest=True)), har(jwt(), host="untrusted.example"),
                     {"log": {"entries": har(jwt("one"))["log"]["entries"] + har(jwt("two"))["log"]["entries"]}}):
            with self.subTest(data=data), self.assertRaises(Error):
                extract_har(data, CONFIG)

    def test_har_extracts_only_auth_material(self):
        session = extract_har(har(jwt()), CONFIG)
        self.assertEqual(session["customer_id"], "customer")
        self.assertNotIn("never-save-this", json.dumps(session))
        self.assertFalse(session["guest"])

    def test_registered_refresh_cookie_is_imported_but_guest_cookie_is_not(self):
        data = har(jwt())
        data["log"]["entries"][0]["request"]["cookies"] = [
            {"name": "cc-nx-g_ametller", "value": "guest-refresh"},
            {"name": "cc-nx_ametller", "value": "registered-refresh"}]
        self.assertEqual(extract_har(data, CONFIG)["refresh_token"], "registered-refresh")

    def test_rejected_server_validation_preserves_existing_session(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = Storage(directory)
            old = {"access_token": "previous-session"}
            storage.write("account.json", old)
            path = Path(directory) / "capture.har"
            path.write_text(json.dumps(har(jwt())))
            with patch("ametller.account.Client.discover", lambda client: setattr(client, "config", CONFIG)), \
                 patch("ametller.account.AccountClient.whoami", side_effect=Error("invalid")), self.assertRaises(Error):
                import_har(path, storage)
            self.assertEqual(storage.read("account.json"), old)

    def test_expired_override_refresh_never_saves_until_profile_verified(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = Storage(directory)
            storage.write("account.json", {"access_token": "old"})
            account = {**token_identity(jwt(expiry=time.time() - 200)), "config": CONFIG,
                       "access_token": jwt(expiry=time.time() - 200), "refresh_token": "synthetic-refresh",
                       "cookies": {"dwsid": "web-session", "cc-nx_ametller": "stale-refresh", "cc-at_ametller": "stale-web-token"}}
            client = AccountClient(storage=storage, account=account)
            client.config = CONFIG
            with patch.object(client, "json_request", return_value={"access_token": jwt(), "refresh_token": "rotated"}):
                client.authenticate()
            self.assertEqual(storage.read("account.json"), {"access_token": "old"})
            self.assertEqual(client.session["refresh_token"], "rotated")
            self.assertEqual(client.session["cookies"], {"dwsid": "web-session", "cc-nx_ametller": "rotated"})

    def test_missing_account_never_falls_back_to_guest(self):
        with tempfile.TemporaryDirectory() as directory:
            client = AccountClient(storage=Storage(directory)); client.config = CONFIG
            with self.assertRaises(Error):
                client.authenticate()


class FakeAccount:
    def __init__(self):
        self.session = {"customer_id": "customer"}
        self.basket = {"basketId": "basket", "currency": "EUR", "productTotal": 2.89, "orderTotal": 2.89,
                       "productItems": [{"itemId": "item", "productId": "2351", "quantity": 1}]}
        self.mutations = []
        self.fail = False

    def authenticate(self):
        pass

    def baskets(self):
        return {"total": 1, "baskets": [self.basket]}

    def products(self, ids):
        return [product()]

    def account_api(self, service, resource, method="GET", body=None):
        if method != "GET":
            self.mutations.append((method, resource, body))
            if self.fail:
                raise ConnectionFailure("timeout")
            self.basket["productItems"][0]["quantity"] = body["quantity"]
            self.basket["productTotal"] = 2.89 * body["quantity"]
            self.basket["orderTotal"] = self.basket["productTotal"]
        return json.loads(json.dumps(self.basket))


class RemoteTests(unittest.TestCase):
    def test_slot_calculation_requires_explicit_refresh_before_any_request(self):
        with self.assertRaises(Error):
            delivery_slots(None)
        with self.assertRaises(Error):
            slots_url("https://other.example/TimeSlot-GetSlots")
        value = slots_url("https://www.ametllerorigen.com/on/demandware.store/Sites-ametller-Site/es/TimeSlot-GetSlots?postalCode=08021", "08001")
        self.assertIn("postalCode=08001", value)
    def test_budget_prevents_any_remote_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            client = FakeAccount(); remote = RemoteCart(client, Storage(directory))
            with self.assertRaises(Error):
                remote.change("add", "2351", "1", "5")
            self.assertEqual(client.mutations, [])
            self.assertEqual(client.basket["productItems"][0]["quantity"], 1)

    def test_change_confirms_actual_server_quantity_and_total(self):
        with tempfile.TemporaryDirectory() as directory:
            client = FakeAccount(); remote = RemoteCart(client, Storage(directory))
            result = remote.change("set", "2351", "2", "10")
            self.assertTrue(result["quantity_confirmed"])
            self.assertEqual(result["order_total_cents"], 578)
            self.assertFalse(result["order_submitted"])

    def test_uncertain_write_not_retried_and_requires_read_to_reconcile(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = Storage(directory); client = FakeAccount(); client.fail = True
            remote = RemoteCart(client, storage)
            with self.assertRaises(Error):
                remote.change("add", "2351", "1")
            with self.assertRaises(Error):
                remote.change("add", "2351", "1")
            self.assertEqual(len(client.mutations), 1)
            result = remote.confirmed_get()
            self.assertEqual(result["reconciled_operation"], "add")
            self.assertIsNone(storage.read("remote-pending.json"))

    def test_explicit_basket_must_belong_to_connected_account(self):
        with tempfile.TemporaryDirectory() as directory:
            client = FakeAccount(); remote = RemoteCart(client, Storage(directory), "other-account-basket")
            with self.assertRaises(Error):
                remote.get()
            self.assertEqual(client.mutations, [])

    def test_sync_preview_does_not_write(self):
        with tempfile.TemporaryDirectory() as directory:
            client = FakeAccount(); remote = RemoteCart(client, Storage(directory))
            result = remote.sync({"2351": "2"}, "10")
            self.assertFalse(result["applied"])
            self.assertEqual(client.mutations, [])


if __name__ == "__main__":
    unittest.main()
