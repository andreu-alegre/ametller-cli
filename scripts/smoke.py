"""Verificación de catálogo real; sin cuenta, cesta remota ni pedidos."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    evidence = {"verified_at": datetime.now(timezone.utc).isoformat(), "source": "https://ametllerorigen.com/es/online", "checks": []}
    with tempfile.TemporaryDirectory(prefix="ametller-smoke-") as directory:
        env = {**os.environ, "AMETLLER_HOME": directory}
        env.pop("AMETLLER_MAX_EUR", None)

        def invoke(*args, expect=0):
            process = subprocess.run([sys.executable, "-m", "ametller", *args, "--json"],
                                     cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
            if process.returncode != expect:
                raise RuntimeError(f"Falló {args}: {process.stderr}")
            if expect != 0:
                assert not process.stdout
                return json.loads(process.stderr)
            return json.loads(process.stdout)

        doctor = invoke("doctor")
        assert doctor["ok"] and doctor["session_type"] == "guest"
        evidence["checks"].append({"check": "guest_catalog_connection", "ok": True})
        search = invoke("search", "yogur", "--limit", "3")
        assert len(search["products"]) == 3
        evidence["checks"].append({"check": "search_es", "ok": True, "total": search["total"],
                                    "examples": [{key: product[key] for key in ("id", "name", "price", "currency")} for product in search["products"]]})
        ca = invoke("search", "iogurt", "--limit", "1", "--lang", "ca")
        assert ca["products"]
        evidence["checks"].append({"check": "search_ca", "ok": True})
        product = invoke("product", "2351")
        assert product["ingredients"] and product["nutrition_text"] and product["url"]
        evidence["checks"].append({"check": "product_details", "ok": True, "id": product["id"]})
        categories = invoke("categories")["categories"]
        assert categories
        category = invoke("categories", "--id", "127", "--limit", "2")
        assert len(category["products"]) == 2
        evidence["checks"].append({"check": "categories_and_category_search", "ok": True})
        batch = invoke("batch", "-f", "examples/busquedas.txt")
        assert len(batch["lines"]) == 3 and batch["complete"]
        evidence["checks"].append({"check": "batch", "ok": True})
        total = invoke("total", "-f", "examples/cesta.txt", "--max", "50")
        cart = invoke("cart", "set-many", "-f", "examples/cesta.txt", "--max", "50")
        assert cart["subtotal_cents"] == total["subtotal_cents"]
        before = (Path(directory) / "cart.json").read_bytes()
        failure = invoke("cart", "add", "2351", "1", "--max", "0", expect=1)
        assert "Presupuesto superado" in failure["error"]
        assert (Path(directory) / "cart.json").read_bytes() == before
        evidence["checks"].append({"check": "local_cart_and_budget_rollback", "ok": True, "subtotal": cart["subtotal"]})
        prepared = invoke("checkout", "prepare", "--max", "50")
        assert not prepared["synced_to_store"] and not prepared["order_submitted"]
        evidence["checks"].append({"check": "local_checkout_preparation", "ok": True})
        invoke("cart", "remove", "2351")
        invoke("cart", "clear")
        assert invoke("cart", "get")["count"] == 0
        evidence["checks"].append({"check": "local_remove_clear", "ok": True})
    evidence.update({"account_used": False, "remote_cart_modified": False, "order_submitted": False})
    path = ROOT / "docs" / "verification.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n")
    print(f"{len(evidence['checks'])} comprobaciones reales OK. Evidencia: {path}")


if __name__ == "__main__":
    main()
