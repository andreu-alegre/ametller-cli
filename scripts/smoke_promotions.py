"""Verificación real de promociones; sólo lecturas, cuenta opcional."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account", action="store_true", help="Comprobar también la cuenta conectada")
    args = parser.parse_args()
    evidence = {"verified_at": datetime.now(timezone.utc).isoformat(),
                "source": "https://ametllerorigen.com/es/promociones", "checks": []}

    def invoke(*arguments, state_dir=None):
        env = {**os.environ}
        env.pop("AMETLLER_MAX_EUR", None)
        if state_dir:
            env["AMETLLER_HOME"] = state_dir
        process = subprocess.run([sys.executable, "-m", "ametller", "promotions", *arguments, "--json"],
                                 cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
        if process.returncode:
            raise RuntimeError(process.stderr)
        return json.loads(process.stdout)

    with tempfile.TemporaryDirectory(prefix="ametller-promotions-") as directory:
        all_offers = invoke("--all", state_dir=directory)
        assert all_offers["catalog_context"] == "guest"
        assert len(all_offers["products"]) == all_offers["total"] > 0
        assert any(p["promotions"] for p in all_offers["products"])
        assert not all_offers["basket_discount_verified"]
        evidence["checks"].append({"check": "guest_all_pages_and_product_conditions", "ok": True,
                                   "total": all_offers["total"],
                                   "products_with_promotion_data": sum(bool(p["promotions"]) for p in all_offers["products"]),
                                   "examples": [{k: p[k] for k in ("id", "name", "price", "promotions")}
                                                for p in all_offers["products"][:3]]})
        expected_club = [p for p in all_offers["products"]
                         if any(offer["club_only"] for offer in p["promotions"] or [])]
        club = invoke("--club", "--all", state_dir=directory)
        assert [p["id"] for p in club["products"]] == [p["id"] for p in expected_club]
        evidence["checks"].append({"check": "club_filter_across_all_pages", "ok": True, "total": club["total"]})
        page = invoke("--limit", "2", "--offset", "2", state_dir=directory)
        assert [p["id"] for p in page["products"]] == [p["id"] for p in all_offers["products"][2:4]]
        evidence["checks"].append({"check": "pagination", "ok": True})
        yogur = invoke("--club", "--query", "yogur", state_dir=directory)
        assert yogur["products"]
        evidence["checks"].append({"check": "query_within_club_offers", "ok": True,
                                   "total": yogur["total"],
                                   "examples": [{k: p[k] for k in ("id", "name", "price", "promotions")}
                                                for p in yogur["products"][:1]]})
        lots = invoke("--lots", "--limit", "2", "--lang", "ca", state_dir=directory)
        assert lots["category_id"] == "LOTSESTALVI" and len(lots["products"]) == 2
        assert any(p["promotions"] for p in lots["products"])
        evidence["checks"].append({"check": "lots_ca", "ok": True, "total": lots["total"]})
        raw = invoke("--raw", "--limit", "1", state_dir=directory)
        assert "productPromotions" in raw["products"][0]
        assert raw["products"][0]["id"] == all_offers["products"][0]["id"]
        evidence["checks"].append({"check": "raw_product_conditions", "ok": True})
    if args.account:
        account = invoke("--club", "--query", "yogur", "--account", "--limit", "2")
        assert account["catalog_context"] == "account" and account["products"]
        assert not account["basket_discount_verified"]
        evidence["checks"].append({"check": "authenticated_catalog_read", "ok": True})
    evidence.update({"account_used": args.account, "remote_cart_modified": False,
                     "payment_submitted": False, "order_submitted": False})
    path = ROOT / "docs" / "promotions-verification.json"
    path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n")
    print(f"{len(evidence['checks'])} comprobaciones reales OK. Evidencia: {path}")


if __name__ == "__main__":
    main()
