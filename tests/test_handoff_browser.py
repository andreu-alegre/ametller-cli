"""Checkout ficticio en Chromium; ninguna petición llega a Ametller."""

from contextlib import contextmanager
import os
import tempfile
import unittest
from unittest.mock import Mock, patch

from ametller.checkoutbrowser import open_checkout
from ametller.storage import Storage
from ametller.webcheckout import CheckoutPage


@unittest.skipUnless(os.environ.get('AMETLLER_BROWSER_TESTS')=='1','Activa AMETLLER_BROWSER_TESTS=1')
class HandoffBrowserTests(unittest.TestCase):
    def setup_fake(self):
        web=Mock(); web.client=Mock()
        web.prepare.return_value=web
        web.client.config={'siteId':'ametller'}
        web.client.session={'cookies':{'dwsid':'synthetic-session','cc-nx_ametller':'synthetic-refresh'}}
        web.page=CheckoutPage(); web.page.urls['data-checkout-get-url']='/on/demandware.store/Sites-ametller-Site/es/CheckoutServices-Get'
        web.remote.get.return_value={'basketId':'synthetic-basket','productItems':[{'productId':'synthetic-product','quantity':1}]}
        web.remote.quantities.return_value={'synthetic-product':'1'}
        web.test.return_value={'web_total_cents':2000,'currency':'EUR','prepayment_ready':False,'checks':{'address_present':False}}
        return web

    def run_fake(self,review):
        from playwright.sync_api import sync_playwright, Error as BrowserError, Page
        web=self.setup_fake(); reached=[]; real_wait=Page.wait_for_timeout
        test=self
        @contextmanager
        def factory():
            with sync_playwright() as runtime:
                class Chromium:
                    def launch(self,**kwargs):
                        browser=runtime.chromium.launch(headless=True)
                        original=browser.new_context
                        def context(**options):
                            value=original(**options)
                            def fixture(route):
                                reached.append((route.request.method,route.request.url))
                                if route.request.method=='GET':
                                    test.assertIn('synthetic-session',route.request.headers.get('cookie',''))
                                    route.fulfill(status=200,content_type='text/html',body="<html><h1>Checkout ficticio</h1><script>fetch('/on/demandware.store/Sites-ametller-Site/es/CheckoutServices-PlaceOrder',{method:'POST'}).catch(()=>{});</script></html>")
                                else:
                                    route.fulfill(status=200,content_type='application/json',body='{}')
                            value.route('**/*',fixture)
                            return value
                        browser.new_context=context
                        return browser
                yield type('Runtime',(),{'chromium':Chromium()})()
        def wait(page,ms):
            real_wait(page,150)
            page.close()
        def validate(context,*args):
            cookies=context.cookies()
            self.assertEqual({item['name'] for item in cookies},{'dwsid','cc-nx_ametller'})
        client=web.client
        with tempfile.TemporaryDirectory() as directory,patch('ametller.checkoutbrowser._playwright',return_value=(factory,BrowserError)),patch('ametller.checkoutbrowser.AccountClient',return_value=client),patch('ametller.checkoutbrowser.WebCheckout',return_value=web),patch('ametller.checkoutbrowser.verify_browser_session',side_effect=validate),patch('ametller.checkoutbrowser.persist_browser_auth') as auth,patch.object(Page,'wait_for_timeout',wait):
            result=open_checkout(Storage(directory),maximum='30',review_only=review,timeout=30)
            auth.assert_called_once()
            self.assertFalse(result['automated_payment_submitted'])
            self.assertFalse(result['automated_order_submitted'])
            return result,reached

    def test_review_mode_blocks_real_browser_post_without_reaching_fixture(self):
        result,reached=self.run_fake(True)
        self.assertTrue(result['review_only']); self.assertFalse(result['manual_purchase_possible'])
        self.assertFalse(result['order_submitted'])
        self.assertGreaterEqual(result['review_requests_blocked'],1)
        self.assertFalse(any(method=='POST' for method,_ in reached))

    def test_manual_handoff_reports_unknown_order_and_does_not_claim_no_purchase(self):
        result,reached=self.run_fake(False)
        self.assertTrue(result['manual_purchase_possible'])
        self.assertIsNone(result['order_submitted']); self.assertIsNone(result['payment_submitted'])
        self.assertEqual(result['manual_order_status'],'unverified')
        self.assertFalse(result['budget_enforced_after_handoff'])
        self.assertTrue(any(method=='POST' for method,_ in reached))
