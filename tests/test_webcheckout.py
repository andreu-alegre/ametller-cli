from datetime import datetime
import tempfile
import unittest
from unittest.mock import Mock
from urllib.error import HTTPError
from email.message import Message
from io import BytesIO

from ametller.remote import RemoteCart
from ametller.storage import Error, Storage
from ametller.webcheckout import CheckoutPage, WebCheckout, controller_url, delivery_day, flatten_slots
from test_account import FakeAccount


class CheckoutTests(unittest.TestCase):
    def test_session_redirect_saves_rotation_and_never_repeats_post(self):
        url = "https://www.ametllerorigen.com/es/checkout"
        for method, allow_redirect, expected_calls in [("GET", True, 2), ("POST", True, 1), ("GET", False, 1)]:
            request_url = ("https://www.ametllerorigen.com/on/demandware.store/Sites-ametller-Site/es/TimeSlot-SaveTimeSlot"
                           if method == "POST" else url)
            web = object.__new__(WebCheckout)
            web.persist_cookies = Mock()
            headers = Message(); headers["Location"] = request_url
            error = HTTPError(request_url, 302, "renewed", headers, BytesIO(b""))
            response = Mock()
            response.__enter__ = Mock(return_value=response)
            response.__exit__ = Mock(return_value=False)
            response.read.return_value = b"checkout"
            web.opener = Mock()
            web.opener.open.side_effect = [error, response]
            if method == "GET" and allow_redirect:
                self.assertEqual(web.request(url), b"checkout")
            else:
                with self.assertRaises(Error):
                    web.request(request_url, method=method, data={"slotId": "1"} if method == "POST" else None,
                                allow_session_redirect=allow_redirect)
            self.assertEqual(web.opener.open.call_count, expected_calls)
            self.assertGreaterEqual(web.persist_cookies.call_count, 1)
    def test_controllers_must_match_site_origin_and_expected_action(self):
        route = "/on/demandware.store/Sites-ametller-Site/es/TimeSlot-SaveTimeSlot"
        self.assertEqual(controller_url(route, "TimeSlot-SaveTimeSlot"), "https://www.ametllerorigen.com" + route)
        for value in ["https://other.example" + route, "https://www.ametllerorigen.com/TimeSlot-SaveTimeSlot",
                      "https://www.ametllerorigen.com:8443" + route, "/on/demandware.store/Sites-other-Site/es/TimeSlot-SaveTimeSlot"]:
            with self.assertRaises(Error):
                controller_url(value, "TimeSlot-SaveTimeSlot")

    def test_shipping_parser_does_not_collect_payment_or_contact_fields(self):
        page = CheckoutPage()
        page.feed('<form id="dwfrm_shipping"><input name="shipmentUUID" value="shipment">'
                  '<input type="radio" name="method" value="01"><input type="radio" name="method" value="02" checked>'
                  '</form><form id="dwfrm_billing"><input name="cardNumber" value="sensitive"></form>')
        self.assertEqual(page.fields, {"shipmentUUID": "shipment", "method": "02"})

    def test_delivery_dates_match_store_timestamps_and_local_days(self):
        self.assertEqual(delivery_day("14/10/2026"), delivery_day("2026-10-14T16:11:16.591Z"))
        self.assertEqual(delivery_day("2026-10-14T23:00:00Z"), "2026-10-15")
        self.assertIsNone(delivery_day("invalid"))

    def test_web_model_rejects_guest_other_account_or_missing_identity(self):
        web = object.__new__(WebCheckout)
        web.customer = {"email": "account@example.test"}
        model = {"customer": {"registeredUser": True, "profile": {"email": "account@example.test"}},
                 "order": {"shipping": [{}]}}
        self.assertEqual(web.verify_model(model), model)
        for customer in [{"registeredUser": False, "profile": {"email": "account@example.test"}},
                         {"registeredUser": True, "profile": {"email": "other@example.test"}},
                         {"registeredUser": True, "profile": {}}]:
            with self.assertRaises(Error):
                web.verify_model({**model, "customer": customer})

    def test_empty_day_lists_do_not_claim_slot_availability(self):
        self.assertEqual(flatten_slots({"success": True, "data": [{"sections": [{"slots": []}]}]}), [])
        with self.assertRaises(Error):
            flatten_slots({"success": False, "data": []})

    def test_unavailable_slot_does_not_submit(self):
        web = object.__new__(WebCheckout)
        web.model = {"order": {"shipping": [{"selectedShippingMethod": {"storePickupEnabled": True}}]}}
        web.page = CheckoutPage()
        web.page.pickup_url = "https://www.ametllerorigen.com/on/demandware.store/Sites-ametller-Site/es/TimeSlot-GetSlots"
        web.json_request = Mock(return_value={"success": True, "data": []})
        web.mutate = Mock()
        with self.assertRaises(Error):
            web.select_slot("unknown", "14/10/2026")
        web.mutate.assert_not_called()

    def test_lost_web_write_is_journalled_and_never_repeated(self):
        with tempfile.TemporaryDirectory() as directory:
            web = object.__new__(WebCheckout)
            web.storage = Storage(directory)
            web.client = FakeAccount()
            web.remote = RemoteCart(web.client, web.storage)
            web.page = CheckoutPage()
            web.page.urls["data-save-time-slot-url"] = "/on/demandware.store/Sites-ametller-Site/es/TimeSlot-SaveTimeSlot"
            web.json_request = Mock(side_effect=Error("response lost"))
            for attempt in range(2):
                with self.assertRaises(Error):
                    web.mutate("data-save-time-slot-url", "TimeSlot-SaveTimeSlot", "delivery-slot", data={"slotId": "1"})
            self.assertEqual(web.json_request.call_count, 1)
            self.assertEqual(web.storage.read("remote-pending.json")["operation"], "delivery-slot")
