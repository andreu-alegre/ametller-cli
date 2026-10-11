"""Prueba explícita de API remota con invitado aislado; elimina su cesta al acabar.

NO usa la cuenta del usuario. No llama a pedidos, pagos o reservas de entrega.
Ejecutar sólo con autorización para crear y eliminar una cesta de prueba.
"""

import json
from pathlib import Path
import shutil
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ametller.account import AccountClient, token_identity
from ametller.client import Client
from ametller.catalog import timestamp
from ametller.remote import RemoteCart, SERVICE, identifier, postal_code
from ametller.storage import Storage


class GuestProbe(AccountClient):
    def authenticate(self, force=False):
        Client.authenticate(self, force)
        self.session.update(token_identity(self.session["access_token"]))


def main():
    checks = []
    directory = tempfile.mkdtemp(prefix="ametller-remote-test-")
    try:
        storage = Storage(directory)
        client = GuestProbe(storage=storage)
        remote = RemoteCart(client, storage)
        basket_id = None
        try:
            assert not remote.get()
            checks.append("isolated_guest_has_no_basket")
            result = remote.change("add", "2351", "1", "10")
            basket_id = result["basket_id"]
            assert result["quantity_confirmed"] and result["order_total_cents"] == 289
            checks.append("create_with_item_and_readback")
            result = remote.change("set", "2351", "2", "10")
            assert result["quantity_confirmed"] and result["order_total_cents"] == 578
            checks.append("patch_quantity_and_readback")
            preview = remote.sync({"2351": "1", "42171": "1"}, "10")
            assert not preview["applied"]
            checks.append("sync_preview")
            result = remote.sync({"2351": "1", "42171": "1"}, "10", True)
            assert result["quantities_confirmed"] and len(result["lines"]) == 2
            checks.append("sync_patch_and_add_batches")
            methods = remote.shipping_methods()
            assert isinstance(methods.get("applicableShippingMethods"), list)
            checks.append("shipping_methods_api")
            coverage = postal_code(client, "08021")
            assert str(coverage["cp"]) == "08021"
            checks.append("postal_coverage_api")
            result = remote.change("set", "42171", "0")
            assert result["quantity_confirmed"] and len(result["lines"]) == 1
            checks.append("delete_item_and_readback")
            result = remote.clear(True)
            assert result["empty_confirmed"]
            checks.append("clear_items_and_readback")
        finally:
            # Recuperar también una creación cuya respuesta no llegara al cliente.
            response = client.baskets()
            for basket in response.get("baskets", []):
                client.account_api(SERVICE, "baskets/" + identifier(basket["basketId"]), method="DELETE")
            assert client.baskets().get("total") == 0
            checks.append("all_test_baskets_deleted")
            shutil.rmtree(directory)
    except Exception:
        if Path(directory).exists():
            print("Conservado estado privado para limpiar la cesta de prueba: " + directory, file=sys.stderr)
        raise
    evidence = {"verified_at": timestamp(), "scope": "isolated_guest", "registered_account_verified": False,
                "order_submitted": False, "payment_submitted": False, "checks": checks, "passed": len(checks)}
    target = Path(__file__).resolve().parents[1] / "docs" / "remote-verification.json"
    target.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(evidence, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
