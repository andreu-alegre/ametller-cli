from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
import tempfile
import unittest
from unittest.mock import patch

from ametller.catalog import normalize, price_basket
from ametller.cli import main
from ametller.promotions import promotion_result
from ametller.storage import Error


def product(product_id, label=None, promotional_price=None, is_sale=True):
    promo = {"promotionId": "offer-" + product_id}
    if label is not None:
        promo["calloutMsg"] = label
    if promotional_price is not None:
        promo["promotionalPrice"] = promotional_price
    return {"id": product_id, "name": "Producto " + product_id, "price": 2,
            "currency": "EUR", "minOrderQuantity": 1, "stepQuantity": 1,
            "inventory": {"orderable": True}, "c_isSale": is_sale, "productPromotions": [promo]}


class Catalog:
    def __init__(self, products):
        self.data = products
        self.calls = []

    def search(self, *, query, category, limit, offset):
        self.calls.append((query, category, limit, offset))
        return {"total": len(self.data), "offset": offset, "selectedRefinements": {"cgid": category},
                "hits": [{"productId": p["id"]} for p in self.data[offset:offset + limit]]}

    def products(self, ids):
        return [p for p in reversed(self.data) if p["id"] in ids]


class PromotionTests(unittest.TestCase):
    def test_callout_html_is_text_and_prices_keep_distinct_roles(self):
        p = product("a", '<p style="color:red">PRECIO&nbsp;CLUB</p><script>secret()</script>', 1.09)
        result = normalize(p)
        self.assertEqual(result["price"], 2)
        self.assertEqual(result["price_cents"], 200)
        self.assertEqual(result["promotions"][0], {
            "id": "offer-a", "label": "PRECIO CLUB", "promotional_price": 1.09,
            "promotional_price_cents": 109, "club_only": True})

    def test_multibuy_and_absent_promotion_do_not_infer_a_unit_price(self):
        result = normalize(product("a", "<p>2x3€</p>"))["promotions"][0]
        self.assertEqual(result["label"], "2x3€")
        self.assertIsNone(result["promotional_price"])
        self.assertIsNone(result["club_only"])
        self.assertIsNone(normalize({"id": "absent"})["promotions"])
        self.assertEqual(normalize({"id": "empty", "productPromotions": []})["promotions"], [])

    def test_sale_flag_is_not_a_requirement_and_zero_price_is_preserved(self):
        result = promotion_result(Catalog([product("lot", promotional_price=0, is_sale=False)]), lots=True)
        self.assertEqual(result["products"][0]["promotions"][0]["promotional_price_cents"], 0)
        self.assertEqual(result["category_id"], "LOTSESTALVI")

    def test_club_filter_scans_every_page_then_applies_filtered_offset(self):
        products = [product(str(i), "2x3€") for i in range(199)]
        products += [product("199", "PRECIO CLUB", 1), product("200", "PREU CLUB", 1)]
        catalog = Catalog(products)
        result = promotion_result(catalog, club=True, offset=1, limit=1, query="yogur")
        self.assertEqual(result["total"], 2)
        self.assertEqual([p["id"] for p in result["products"]], ["200"])
        self.assertEqual(catalog.calls, [("yogur", "PROMOCIONS", 200, 0), ("yogur", "PROMOCIONS", 200, 200)])

    def test_all_pages_preserve_search_order_and_empty_result(self):
        catalog = Catalog([product(str(i)) for i in range(202)])
        result = promotion_result(catalog, all_results=True, offset=1)
        self.assertEqual([p["id"] for p in result["products"]], [str(i) for i in range(1, 202)])
        self.assertEqual(promotion_result(Catalog([]), club=True)["total"], 0)
        self.assertEqual(promotion_result(catalog, offset=999)["products"], [])

    def test_ignored_filter_missing_detail_and_truncated_pages_fail(self):
        for failure in ("filter", "details", "page"):
            with self.subTest(failure=failure):
                catalog = Catalog([product("a")])
                if failure == "filter":
                    catalog.search = lambda **kwargs: {"total": 1, "hits": [{"productId": "a"}]}
                elif failure == "page":
                    catalog.search = lambda **kwargs: {"total": 1, "hits": [], "selectedRefinements": {"cgid": "PROMOCIONS"}}
                else:
                    catalog.products = lambda ids: []
                with self.assertRaises(Error):
                    promotion_result(catalog)

    def test_catalog_budget_does_not_apply_conditional_discount(self):
        catalog = Catalog([product("a", "PRECIO CLUB", 1)])
        self.assertEqual(price_basket(catalog, {"a": "2"})["subtotal_cents"], 400)

    def test_account_flag_selects_account_and_failures_never_fall_back(self):
        with tempfile.TemporaryDirectory() as directory:
            stdout, stderr = StringIO(), StringIO()
            catalog = Catalog([product("a", "PRECIO CLUB", 1)])
            catalog.catalog_context = "account"
            with patch("ametller.cli.AccountClient", return_value=catalog), patch("ametller.cli.Client") as guest, redirect_stdout(stdout):
                self.assertEqual(main(["promotions", "--account", "--club", "--json", "--state-dir", directory]), 0)
                guest.assert_not_called()
            result = json.loads(stdout.getvalue())
            self.assertEqual(result["catalog_context"], "account")
            self.assertFalse(result["basket_discount_verified"])
            with patch("ametller.cli.AccountClient", side_effect=Error("Cuenta caducada")), patch("ametller.cli.Client") as guest, redirect_stdout(StringIO()), redirect_stderr(stderr):
                self.assertEqual(main(["--account", "promotions", "--json", "--state-dir", directory]), 1)
                guest.assert_not_called()
            self.assertIn("Cuenta caducada", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
