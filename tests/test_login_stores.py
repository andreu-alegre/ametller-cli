import unittest

from ametller.browserlogin import LoginCapture
from ametller.cli import parser
from ametller.storage import Error
from ametller.stores import find_stores, get_store
from test_account import CONFIG, jwt


class LoginTests(unittest.TestCase):
    url = "https://www.ametllerorigen.com/mobify/proxy/api/customer/shopper-customers/v1/organizations/org/customers/customer"

    def test_browser_capture_ignores_guests_foreign_hosts_and_wrong_organization(self):
        capture = LoginCapture(CONFIG)
        capture.request(self.url, {"authorization": "Bearer " + jwt(guest=True)})
        capture.request(self.url.replace("www.ametllerorigen.com", "other.example"), {"authorization": "Bearer " + jwt()})
        capture.request(self.url.replace("/org/", "/other/"), {"authorization": "Bearer " + jwt()})
        self.assertEqual(capture.tokens, {})

    def test_browser_capture_saves_only_allowed_cookies_and_authentication(self):
        capture = LoginCapture(CONFIG)
        capture.request(self.url, {"authorization": "Bearer " + jwt()})
        cookies = [{"name": name, "value": value, "domain": domain, "secure": secure}
                   for name, value, domain, secure in [
                       ("cc-nx_ametller", "refresh", ".ametllerorigen.com", True),
                       ("dwsid", "session", "www.ametllerorigen.com", True),
                       ("analytics", "tracking", "www.ametllerorigen.com", True),
                       ("dwsecuretoken_other", "foreign", "other.example", True),
                       ("cc-at_ametller", jwt(guest=True), "ametllerorigen.com", False)]]
        account = capture.account(cookies)
        self.assertEqual(account["refresh_token"], "refresh")
        self.assertEqual(account["cookies"], {"cc-nx_ametller": "refresh", "dwsid": "session"})
        self.assertEqual(account["config"], CONFIG)

    def test_browser_capture_rejects_account_switching(self):
        capture = LoginCapture(CONFIG)
        for customer in ["one", "two"]:
            capture.request(self.url, {"authorization": "Bearer " + jwt(customer=customer)})
        with self.assertRaises(Error):
            capture.account([])

    def test_login_defaults_to_browser_and_accepts_terminal_explicitly(self):
        self.assertFalse(parser().parse_args(["login"]).terminal)
        self.assertTrue(parser().parse_args(["login", "--terminal"]).terminal)


class StoreClient:
    lang = "es"

    def __init__(self):
        self.calls = []

    def api(self, service, resource, params=None):
        self.calls.append((service, resource, params))
        if service == "custom/postal-codes":
            return {"latitude": "41.397", "longitude": "2.141"}
        return {"total": 2, "data": [{"id": "I220", "name": "Tienda", "c_info_click_collect_standar": True},
                                     {"id": "I221", "name": "Otra"}]}


class StoreTests(unittest.TestCase):
    def test_postcode_search_uses_store_coverage_coordinates(self):
        client = StoreClient()
        result = find_stores(client, "08021", pickup_only=True)
        self.assertEqual([store["id"] for store in result["stores"]], ["I220"])
        self.assertEqual(client.calls[1][2]["latitude"], "41.397")
        self.assertEqual(result["total_in_radius"], 2)

    def test_invalid_search_is_rejected_before_requests(self):
        for postcode, limit, distance in [("invalid", 20, 20), ("08021", 0, 20), ("08021", 20, 501)]:
            client = StoreClient()
            with self.assertRaises(Error):
                find_stores(client, postcode, limit, distance)
            self.assertEqual(client.calls, [])

    def test_store_id_response_must_match_requested_store(self):
        with self.assertRaises(Error):
            get_store(StoreClient(), "foreign")
