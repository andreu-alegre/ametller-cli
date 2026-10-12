import tempfile
import unittest
from unittest.mock import Mock, patch

from ametller.checkoutbrowser import browser_cookies, open_checkout, review_request_allowed, verify_browser_session
from ametller.storage import Error, Storage
from ametller.webcheckout import CheckoutPage, WebCheckout


class CheckoutBrowserTests(unittest.TestCase):
    def test_cookie_bridge_excludes_other_data_and_requires_registered_session(self):
        result=browser_cookies({"dwsid":"synthetic-session","cc-nx_ametller":"synthetic-refresh",
                                "other-cookie":"synthetic-private"},"ametller")
        self.assertEqual({item['name'] for item in result},{"dwsid","cc-nx_ametller"})
        self.assertTrue(all(item['secure'] and item['domain']=='.ametllerorigen.com' for item in result))
        with self.assertRaises(Error): browser_cookies({"cc-nx_ametller":"refresh"},"ametller")
        with self.assertRaises(Error): browser_cookies({"dwsid":"session","cc-nx-g_ametller":"guest"},"ametller")
        with self.assertRaises(Error): browser_cookies({"dwsid":"session\r\ninjection"},"ametller")

    def test_review_mode_blocks_writes_payment_provider_and_encoded_controllers(self):
        for url,method in (("https://www.ametllerorigen.com/es/checkout","POST"),
                           ("https://checkoutshopper-live.adyen.com/assets/checkout.js","GET"),
                           ("https://www.ametllerorigen.com/on/demandware.store/Sites-ametller-Site/es/CheckoutServices-%50laceOrder","GET"),
                           ("https://www.ametllerorigen.com/on/demandware.store/Sites-ametller-Site/es/TimeSlot-ChangeStore","GET"),
                           ("https://www.ametllerorigen.com/es/checkout?action=SubmitPayment","GET")):
            with self.subTest(url=url): self.assertFalse(review_request_allowed(url,method))
        self.assertTrue(review_request_allowed("https://www.ametllerorigen.com/es/checkout","GET"))
        self.assertTrue(review_request_allowed("https://www.ametllerorigen.com/on/demandware.static/assets.js","GET"))
        self.assertTrue(review_request_allowed("https://www.ametllerorigen.com/on/demandware.store/Sites-ametller-Site/es/CheckoutServices-Get","GET"))

    def test_redirect_or_unknown_amount_closes_browser_bootstrap_before_handoff(self):
        context=Mock(); web=Mock(); web.page=CheckoutPage()
        web.page.urls['data-checkout-get-url']='/on/demandware.store/Sites-ametller-Site/es/CheckoutServices-Get'
        response=context.request.get.return_value; response.status=302
        with self.assertRaises(Error): verify_browser_session(context,web,'30')
        web.verify_model.assert_not_called(); response.dispose.assert_called_once()
        response.status=200; web.model={'order':{'totals':{'grandTotal':'unknown'}}}
        with self.assertRaises(Error): verify_browser_session(context,web,'30')
        web.model={'order':{'totals':{'grandTotal':'31,00 €'}}}
        with self.assertRaises(Error): verify_browser_session(context,web,'30')

    def test_browser_model_must_match_registered_account(self):
        context=Mock(); web=object.__new__(WebCheckout)
        web.page=CheckoutPage(); web.page.urls['data-checkout-get-url']='/on/demandware.store/Sites-ametller-Site/es/CheckoutServices-Get'
        web.customer={'email':'member@example.test'}
        context.request.get.return_value.status=200
        context.request.get.return_value.json.return_value={'customer':{'registeredUser':True,'profile':{'email':'other@example.test'}},'order':{'shipping':[{}]}}
        with self.assertRaises(Error): verify_browser_session(context,web,'30')

    def test_invalid_budget_and_timeout_reject_before_network_or_browser(self):
        with tempfile.TemporaryDirectory() as directory,patch('ametller.checkoutbrowser.AccountClient') as client,patch('ametller.checkoutbrowser._playwright') as runtime:
            for options in ({'maximum':None},{'maximum':'0'},{'maximum':'-1'},{'maximum':'30','timeout':2}):
                with self.subTest(options=options),self.assertRaises(Error): open_checkout(Storage(directory),**options)
            client.assert_not_called(); runtime.assert_not_called()

    def test_foreign_model_endpoint_never_receives_cookies(self):
        context=Mock(); web=Mock(); web.page=CheckoutPage()
        web.page.urls['data-checkout-get-url']='https://other.example/CheckoutServices-Get'
        with self.assertRaises(Error): verify_browser_session(context,web,'30')
        context.request.get.assert_not_called()

    def test_missing_delivery_method_is_pending_and_not_assumed_ready(self):
        web=object.__new__(WebCheckout)
        web.remote=Mock(); web.remote.get.return_value={'basketId':'test','currency':'EUR','orderTotal':20,'productItems':[{}],'shipments':[{}]}
        web.page=CheckoutPage(); web.page.payment_form_present=True
        web.model={'customer':{'profile':{}},'order':{'shipping':[{'selectedShippingMethod':None}],
                   'steps':{'shipping':None},'totals':{'grandTotal':'20,00 €'}}}
        report=web.test('30')
        self.assertFalse(report['prepayment_ready'])
        self.assertFalse(report['checks']['shipping_accepted_by_store'])
        self.assertFalse(report['checks']['delivery_slot_selected'])
