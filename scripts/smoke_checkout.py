"""Prueba registrada sin compra: cesta temporal, domicilio, franja y preflight.

Usar sólo con permiso para una cesta de prueba. --details envía los datos privados
de contacto/domicilio a Ametller, que puede guardarlos en la cuenta. No acepta
condiciones, no envía datos de tarjeta y no llama a pagos ni creación de pedidos.
Si existe una cesta, se detiene antes de modificarla. Limpieza por ID y cantidades.
"""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ametller import __version__
from ametller.account import AccountClient
from ametller.catalog import timestamp
from ametller.cli import parser, run
from ametller.client import Client
from ametller.details import read_details
from ametller.remote import RemoteCart, SERVICE, identifier
from ametller.storage import Error, Storage


def main():
    options = argparse.ArgumentParser(description=__doc__)
    options.add_argument("--details", help="Borrador privado del formulario (opcional)")
    options.add_argument("--postcode", default="08021")
    options.add_argument("--review-address", action="store_true", help="Mostrar revisión privada de dirección si la tienda la pide")
    args = options.parse_args()
    details = read_details(args.details) if args.details else None
    postcode = details["shipping"]["postal_code"] if details else args.postcode
    storage = Storage(); account = AccountClient(storage=storage); remote = RemoteCart(account, storage)
    client = Client(storage=storage)
    checks = []
    basket_id = None
    report = None

    def command(argv):
        return run(parser().parse_args(argv), client, storage)

    def order_state():
        result = account.orders(limit=50)
        return result.get("total"), {item.get("orderNo") for item in result.get("data", [])}

    before = order_state()
    with storage.lock("remote-cart"):
        remote.pending()
        if remote.get():
            raise Error("La cuenta ya tiene una cesta; no se modificará ni eliminará.")
        if details and details["contact"]["email"] != account.customer().get("email"):
            raise Error("El email del borrador no coincide con la cuenta.")
        result = remote.change("add", "2351", "8", "30")
        basket_id = result["basket_id"]
        checks.append("temporary_basket_created_with_budget")
    try:
        preview = command(["delivery", "home", "--postcode", postcode])
        if preview["applied"] is not False:
            raise Error("La vista previa modificó la entrega.")
        checks.append("home_preview")
        home = command(["delivery", "home", "--postcode", postcode, "--apply"])
        if home["home_postcode_confirmed"] is not True:
            raise Error("Domicilio no confirmado.")
        checks.append("home_method_and_postcode_readback")
        slots = command(["delivery", "slots", "--refresh"])["slots"]
        if not slots:
            raise Error("No hay franjas disponibles.")
        checks.append("live_home_slots")
        slot = slots[0]
        selection = command(["delivery", "select-slot", str(slot["id"]), "--date", slot["date"], "--apply"])
        if not selection["delivery_selection_confirmed"]:
            raise Error("La franja no quedó confirmada.")
        checks.append("home_slot_id_and_date_readback")
        if details:
            argv = ["checkout", "details", "--file", args.details, "--apply"]
            if args.review_address:
                argv.append("--review-address")
            result = command(argv)
            if not result["shipping_confirmed"] or not result["contact_confirmed"]:
                raise Error("Datos de envío/contacto sin confirmar.")
            checks.append("contact_and_home_address_confirmed")
        report = command(["checkout", "test", "--refresh", "--max", "30"])
        if report["order_submitted"] or report["payment_submitted"] or not report["orders_blocked"] or not report["payments_blocked"]:
            raise Error("Se incumplió el límite del modo de prueba.")
        if details and not report["prepayment_ready"]:
            raise Error("La tienda aún no acepta toda la preparación previa al pago.")
        checks.append("checkout_test_no_purchase")
        if order_state() != before:
            raise Error("El historial de pedidos cambió durante la prueba; revisa la cuenta.")
        checks.append("order_history_unchanged")
    finally:
        if basket_id:
            with storage.lock("remote-cart"):
                basket = remote.read_id(basket_id)
                if remote.quantities(basket) != {"2351": "8"}:
                    raise Error("La cesta temporal cambió fuera de la prueba; se conserva para revisión.")
                storage.write("remote-pending.json", {"customer_id": account.session["customer_id"],
                              "basket_id": basket_id, "operation": "checkout-test-delete"})
                account.account_api(SERVICE, "baskets/" + identifier(basket_id), method="DELETE")
                if any(item.get("basketId") == basket_id for item in account.baskets().get("baskets", [])):
                    raise Error("No se confirmó la limpieza de la cesta temporal.")
                pending = storage.read("remote-pending.json")
                if pending and pending.get("basket_id") == basket_id and pending.get("customer_id") == account.session["customer_id"]:
                    storage.delete("remote-pending.json")
                checks.append("temporary_basket_deleted")
    evidence = {"version": __version__, "verified_at": timestamp(), "scope": "registered_account",
                "checks": checks, "passed": len(checks), "prepayment_checks": report["checks"],
                "home_address_verified": bool(details), "prepayment_ready": report["prepayment_ready"],
                "order_submitted": False, "payment_submitted": False, "payment_processing_verified": False,
                "payment_sandbox_available": None, "delivery_slot_reserved": None}
    target = Path(__file__).resolve().parents[1] / "docs" / "checkout-test-verification.json"
    target.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(evidence, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Error as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
