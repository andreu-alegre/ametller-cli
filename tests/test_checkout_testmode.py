import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from ametller.account import AccountClient
from ametller.checkoutguard import allow_account_request
from ametller.cli import parser, run
from ametller.details import read_details, validate_details
from ametller.storage import Error, Storage
from ametller.webcheckout import AddressReviewRequired, CheckoutPage, WebCheckout, web_total_cents


def details():
    return {"contact": {"first_name": "Persona", "last_name": "Prueba", "email": "user@example.test"},
            "shipping": {"first_name": "Persona", "last_name": "Prueba", "address1": "Calle de Prueba",
                         "street_number": "10", "floor": "Bajos", "postal_code": "08021", "city": "Barcelona",
                         "state_code": "barcelona", "country": "ES", "receiver": "Persona Prueba", "phone": "600000000",
                         "address_name": "Prueba"}}


class TestModeTests(unittest.TestCase):
    def test_payment_and_order_services_block_before_network_including_get(self):
        for controller in ("CheckoutServices-SubmitPayment", "CheckoutServices-PlaceOrder", "Adyen-PaymentFromComponent",
                           "Adyen-ShowConfirmation", "Checkout-SetBillingAddress", "NewController-Charge", "CheckoutServices-%50laceOrder"):
            for method in ("GET", "POST"):
                web = object.__new__(WebCheckout)
                web.opener = Mock()
                web.persist_cookies = Mock()
                with self.assertRaises(Error):
                    web.request("https://www.ametllerorigen.com/on/demandware.store/Sites-ametller-Site/es/" + controller,
                                method=method)
                web.opener.open.assert_not_called()
                web.persist_cookies.assert_not_called()

    def test_api_purchase_block_precedes_authentication(self):
        client = object.__new__(AccountClient)
        client.authenticate = Mock()
        for service, resource, method in (("checkout/shopper-orders", "orders", "POST"),
                                           ("checkout/shopper-baskets", "baskets/abc/payment-instruments", "POST"),
                                           ("checkout/shopper-baskets", "baskets/abc/%70ayment-instruments", "DELETE")):
            with self.assertRaises(Error):
                client.account_api(service, resource, method=method)
        client.authenticate.assert_not_called()
        allow_account_request("customer/shopper-customers", "customers/abc/orders", "GET")
        allow_account_request("checkout/shopper-baskets", "baskets/abc/items", "POST")

    def test_private_details_reject_cards_credentials_and_unknown_fields(self):
        self.assertEqual(validate_details(details()), details())
        for key in ("card_number", "password", "csrf_token", "latitude"):
            data = details(); data["shipping"][key] = "secret"
            with self.assertRaises(Error):
                validate_details(data)
        for key, value in (("phone", "invalid"), ("country", "US"), ("postal_code", "8021"), ("address1", "line\nother"), ("floor", "X" * 11)):
            data = details(); data["shipping"][key] = value
            with self.assertRaises(Error):
                validate_details(data)

    def test_details_file_requires_private_permissions_and_rejects_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "details.json"
            file.write_text(json.dumps(details())); file.chmod(0o600)
            self.assertEqual(read_details(file), details())
            file.chmod(0o644)
            with self.assertRaises(Error): read_details(file)
            file.chmod(0o600)
            link = Path(directory) / "link.json"; link.symlink_to(file)
            with self.assertRaises(Error): read_details(link)

    def test_contact_parser_ignores_consent_invoice_and_card_values(self):
        page = CheckoutPage()
        page.feed('<form class="contact-form" action="/submit"><input name="contactEmail" value="user@example.test">'
                  '<input name="acceptarContact" checked value="true"><input name="dwfrm_invoice_nif" value="private"></form>'
                  '<form id="dwfrm_billing"><input name="cardNumber" value="secret"></form>')
        self.assertEqual(page.contact_fields, {"contactEmail": "user@example.test"})
        self.assertEqual(page.fields, {})
        self.assertTrue(page.payment_form_present)

    def test_checkout_test_requires_refresh_without_web_request(self):
        args = parser().parse_args(["checkout", "test", "--json"])
        with tempfile.TemporaryDirectory() as directory, patch("ametller.cli.WebCheckout") as web:
            with self.assertRaises(Error): run(args, Mock(), Storage(directory))
            web.assert_not_called()

    def test_contact_email_mismatch_does_not_write(self):
        web = object.__new__(WebCheckout)
        web.customer = {"email": "other@example.test"}
        web.mutate = Mock()
        with self.assertRaises(Error): web.contact(details())
        web.mutate.assert_not_called()

    def test_review_marks_incomplete_delivery_and_never_submits_payment(self):
        web = object.__new__(WebCheckout)
        web.remote = Mock()
        web.remote.get.return_value = {"basketId": "test", "currency": "EUR", "orderTotal": 29,
                                       "productItems": [{"productId": "123", "quantity": 1}], "shipments": [{}]}
        web.customer = {"email": "user@example.test"}
        web.model = {"customer": {"profile": {"firstName": "Test", "lastName": "User", "email": "user@example.test"}},
                     "order": {"shipping": [{"selectedShippingMethod": {"storePickupEnabled": False}}],
                               "steps": {"shipping": {"iscompleted": False}}, "totals": {"grandTotal": "29,00€"}}}
        web.page = CheckoutPage(); web.page.payment_form_present = True
        web.json_request = Mock(); web.mutate = Mock()
        result = web.test("30")
        self.assertFalse(result["prepayment_ready"])
        self.assertFalse(result["checks"]["shipping_accepted_by_store"])
        self.assertFalse(result["payment_processing_verified"])
        self.assertTrue(result["orders_blocked"])
        self.assertNotIn("user@example.test", json.dumps(result))
        with self.assertRaises(Error): web.test("20")
        web.mutate.assert_not_called(); web.json_request.assert_not_called()

    def test_web_total_uses_currency_and_decimal_format_without_guessing(self):
        self.assertEqual(web_total_cents(" 1.234,56 €"), 123456)
        for value in ("29.00$", "1,234.56€", "gratis", None):
            self.assertIsNone(web_total_cents(value))

    def test_basket_change_during_human_address_review_prevents_second_post(self):
        web = object.__new__(WebCheckout)
        web.storage = Mock(); web.storage.read.return_value = {"basket_id": "test"}
        web.remote = Mock(); web.remote.read_id.return_value = {"basketId": "test", "quantity": 1}
        web.remote.get.return_value = {"basketId": "test", "quantity": 2}
        web.page = CheckoutPage()
        prefix = "dwfrm_shipping_shippingAddress_addressFields_"
        web.page.shipping_options = {prefix + "states_stateCode": ["barcelona"], prefix + "country": ["ES"]}
        web.page.delivery_url = "https://www.ametllerorigen.com/on/demandware.store/Sites-ametller-Site/es/TimeSlot-GetSlots?postalCode=08021"
        web.page.fields = {"csrf_token": "fake", "timeSlotID": "1"}
        web.model = {"order": {"shipping": [{"UUID": "test", "selectedShippingMethod": {"storePickupEnabled": False}}]}}
        web.mutate = Mock(side_effect=AddressReviewRequired({"originalAddress": {"formattedAddress": "Ficticia"}}))
        with patch("ametller.details.collect_address_review", return_value="original"):
            with self.assertRaises(Error): web.shipping_details(details(), review_address=True)
        self.assertEqual(web.mutate.call_count, 1)
        self.assertEqual(web.mutate.call_args.kwargs["data"][prefix + "addressValidated"], "false")
        web.remote.confirmed_get.assert_not_called()

    def test_address_suggestion_stock_and_slot_errors_cannot_confirm_shipping(self):
        for reply in ({"showAddressModal": True}, {"inventoryError": True}, {"slotError": True}, {"sushiError": True}):
            with tempfile.TemporaryDirectory() as directory:
                web = object.__new__(WebCheckout)
                web.storage = Storage(directory); web.client = Mock(); web.client.session = {"customer_id": "test"}
                web.remote = Mock(); web.remote.get.return_value = {"basketId": "test"}
                web.remote.read_id.return_value = {"basketId": "test"}
                web.page = CheckoutPage()
                web.page.urls["submit-shipping"] = "/on/demandware.store/Sites-ametller-Site/es/CheckoutShippingServices-SubmitShipping"
                web.json_request = Mock(return_value=reply); web.read_model = Mock()
                with self.assertRaises(Error): web.mutate("submit-shipping", "CheckoutShippingServices-SubmitShipping", "home-address")
                self.assertEqual(web.json_request.call_count, 1)
                self.assertTrue(web.storage.read("remote-pending.json"))
                web.read_model.assert_not_called()


if __name__ == "__main__":
    unittest.main()
