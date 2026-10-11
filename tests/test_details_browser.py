"""Regresión real del formulario local/Origin en Chromium; datos ficticios."""

import os
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from ametller.details import collect_address_review, collect_details, read_details
from ametller.storage import Storage
from test_checkout_testmode import details


@unittest.skipUnless(os.environ.get("AMETLLER_BROWSER_TESTS") == "1", "Activa AMETLLER_BROWSER_TESTS=1 con Playwright/Chromium")
class DetailsBrowserTests(unittest.TestCase):
    def test_address_review_has_no_default_choice_and_requires_explicit_selection(self):
        from playwright.sync_api import Page, BrowserType
        original_goto, original_launch = Page.goto, BrowserType.launch
        test = self

        def launch(browser_type, *args, **kwargs):
            kwargs["headless"] = True
            return original_launch(browser_type, *args, **kwargs)

        def goto(page, url, **kwargs):
            result = original_goto(page, url, **kwargs)
            test.assertEqual(page.locator('input[type="radio"]:checked').count(), 0)
            test.assertEqual(page.locator('input[type="radio"]').count(), 2)
            page.locator('[value="suggested"]').check()
            page.locator("button").click()
            test.assertIn("Dirección revisada", page.locator("body").inner_text())
            return result

        with patch.object(Page, "goto", goto), patch.object(BrowserType, "launch", launch):
            self.assertEqual(collect_address_review({"originalAddress": {"formattedAddress": "Dirección ficticia"},
                           "suggestedAddress": {"formattedAddress": "Corrección ficticia", "components": {"route": "Prueba"}}}, timeout=30), "suggested")

    def test_real_chromium_form_saves_private_file_and_rejects_foreign_origin(self):
        from playwright.sync_api import Page, BrowserType
        original_goto, original_launch = Page.goto, BrowserType.launch
        sample = details()
        test = self

        def launch(browser_type, *args, **kwargs):
            kwargs["headless"] = True
            return original_launch(browser_type, *args, **kwargs)

        def goto(page, url, **kwargs):
            result = original_goto(page, url, **kwargs)
            with test.assertRaises(HTTPError) as rejected:
                urlopen(Request(url, data=b"contact.email=attacker", headers={"Origin": "https://other.example"}), timeout=5)
            test.assertEqual(rejected.exception.code, 403)
            rejected.exception.close()
            for section, fields in sample.items():
                for name, value in fields.items():
                    locator = page.locator('[name="' + section + '.' + name + '"]')
                    if name in ("state_code", "country"):
                        locator.select_option(value)
                    else:
                        locator.fill(value)
            page.locator("button").click()
            test.assertIn("Borrador guardado", page.locator("body").inner_text())
            return result

        with tempfile.TemporaryDirectory() as directory, patch.object(Page, "goto", goto), patch.object(BrowserType, "launch", launch):
            result = collect_details(Storage(directory), timeout=30)
            self.assertEqual(read_details(result["details_file"]), sample)
            self.assertFalse(result["applied"])
            self.assertFalse(result["payment_submitted"])
            self.assertEqual(os.stat(result["details_file"]).st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
