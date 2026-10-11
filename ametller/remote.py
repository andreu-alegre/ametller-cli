"""Cesta de cuenta SCAPI. Mutaciones sin reintentos y lectura de confirmación."""

import hashlib
import json
import re
from urllib.parse import quote

from .catalog import cents, decimal, price_basket, validate_id
from .client import ConnectionFailure
from .storage import Error

SERVICE = "checkout/shopper-baskets"


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[\w-]{1,150}", value):
        raise Error("Identificador de cesta, línea o envío inválido.")
    return quote(value, safe="")


def summary(basket):
    def money(field):
        value = basket.get(field)
        return None if value is None else cents(decimal(value))
    return {"scope": "account", "basket_id": basket.get("basketId"), "currency": basket.get("currency"),
            "product_total_cents": money("productTotal"), "shipping_total_cents": money("shippingTotal"),
            "order_total_cents": money("orderTotal"), "tax_total_cents": money("taxTotal"),
            "lines": [{"item_id": item.get("itemId"), "product_id": item.get("productId"),
                       "name": item.get("productName"), "quantity": item.get("quantity"),
                       "line_total": item.get("priceAfterOrderDiscount", item.get("price"))}
                      for item in basket.get("productItems", [])],
            "shipments": basket.get("shipments", []), "order_submitted": False,
            "notice": "Importes calculados por la tienda; entrega y peso final pueden cambiar el total."}


def fingerprint(basket):
    # Detectar cambios de otra sesión entre planificación y escritura.
    return hashlib.sha256(json.dumps(basket, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class RemoteCart:
    def __init__(self, client, storage, basket_id=None):
        self.client, self.storage, self.basket_id = client, storage, basket_id

    def read_id(self, basket_id):
        return self.client.account_api(SERVICE, "baskets/" + identifier(basket_id))

    def get(self):
        response = self.client.baskets()
        baskets = response.get("baskets", [])
        if response.get("total", len(baskets)) != len(baskets):
            raise Error("La lista de cestas está incompleta; no se seleccionará una cesta automáticamente.")
        if self.basket_id:
            if self.basket_id not in {basket.get("basketId") for basket in baskets}:
                raise Error("La cesta solicitada no pertenece a las cestas de esta cuenta.")
            return self.read_id(self.basket_id)
        if len(baskets) > 1:
            raise Error("Hay varias cestas. Usa remote-cart list y --basket-id para elegir.")
        return self.read_id(baskets[0]["basketId"]) if baskets else None

    def pending(self):
        if self.storage.read("remote-pending.json"):
            raise Error("Hay una operación remota sin confirmar. Ejecuta remote-cart get y revisa su resultado antes de otro cambio.")

    def confirmed_get(self):
        basket = self.get()
        pending = self.storage.read("remote-pending.json")
        if pending:
            # No borrar un bloqueo consultando una cesta o cuenta diferente.
            self.client.authenticate()
            if pending.get("customer_id") != self.client.session["customer_id"]:
                raise Error("La operación pendiente corresponde a otra cuenta; conserva el estado y revisa la conexión.")
            if pending.get("basket_id") and (basket or {}).get("basketId") != pending["basket_id"]:
                raise Error("Consulta la cesta de la operación pendiente usando --basket-id.")
            self.storage.delete("remote-pending.json")
        result = summary(basket or {})
        result["exists"] = basket is not None
        if pending:
            result["reconciled_operation"] = pending["operation"]
            result["notice"] += " Se recuperó el estado actual; revisa las cantidades antes de repetir la operación."
        return result

    def mutate(self, basket, resource, method, body, operation):
        self.pending()
        self.client.authenticate()
        if basket and fingerprint(self.read_id(basket["basketId"])) != fingerprint(basket):
            raise Error("La cesta cambió en otra sesión. Vuelve a leerla antes de aplicar cambios.")
        pending = {"customer_id": self.client.session["customer_id"], "basket_id": (basket or {}).get("basketId"),
                   "operation": operation}
        self.storage.write("remote-pending.json", pending)
        try:
            response = self.client.account_api(SERVICE, resource, method=method, body=body)
            if not response or not response.get("basketId"):
                raise Error("La tienda no confirmó la cesta modificada.")
            pending["basket_id"] = response["basketId"]
            self.storage.write("remote-pending.json", pending)
            verified = self.read_id(response["basketId"])
        except (ConnectionFailure, Error):
            # Un error HTTP puede producirse después de un hook con efectos.
            # Conservar el bloqueo para recuperar por GET, sin repetir la mutación.
            raise Error("La operación remota no quedó confirmada. No la repitas: ejecuta remote-cart get y revisa la cesta.") from None
        self.storage.delete("remote-pending.json")
        return verified

    @staticmethod
    def quantities(basket):
        result = {}
        for line in (basket or {}).get("productItems", []):
            product_id = validate_id(line["productId"])
            if product_id in result:
                raise Error("El mismo producto ocupa varias líneas remotas; revisa esa cesta en la web.")
            result[product_id] = str(line["quantity"])
        return result

    def change(self, action, product_id, quantity, maximum=None):
        self.pending()
        product_id = validate_id(product_id)
        quantity = decimal(quantity)
        if quantity < 0 or quantity > 10000 or (action == "add" and quantity == 0):
            raise Error("Cantidad fuera de rango.")
        basket = self.get()
        quantities = self.quantities(basket)
        if action == "add":
            quantity += decimal(quantities.get(product_id, 0))
        quantities[product_id] = str(quantity)
        quantities = {key: value for key, value in quantities.items() if decimal(value) > 0}
        estimate = price_basket(self.client, quantities, maximum)
        item = next((item for item in (basket or {}).get("productItems", []) if item["productId"] == product_id), None)
        if basket is None:
            if quantity == 0:
                return summary({})
            body = {"productItems": [{"productId": product_id, "quantity": float(quantity)}]}
            updated = self.mutate(None, "baskets", "POST", body, action)
        elif quantity == 0 and item:
            updated = self.mutate(basket, "baskets/" + identifier(basket["basketId"]) + "/items/" + identifier(item["itemId"]), "DELETE", None, action)
        elif quantity == 0:
            updated = basket
        elif item:
            updated = self.mutate(basket, "baskets/" + identifier(basket["basketId"]) + "/items/" + identifier(item["itemId"]),
                                  "PATCH", {"quantity": float(quantity)}, action)
        else:
            updated = self.mutate(basket, "baskets/" + identifier(basket["basketId"]) + "/items", "POST",
                                  [{"productId": product_id, "quantity": float(quantity)}], action)
        expected = decimal(quantities.get(product_id, 0))
        actual = decimal(self.quantities(updated).get(product_id, 0))
        result = summary(updated)
        result["quantity_confirmed"] = actual == expected
        result["catalog_estimate_cents"] = estimate["subtotal_cents"]
        if maximum is not None:
            total = result["product_total_cents"]
            result["server_product_budget_exceeded"] = None if total is None else total > cents(decimal(maximum))
        if not result["quantity_confirmed"]:
            result["notice"] += " La tienda ajustó la cantidad solicitada; revisa el resultado."
        return result

    def sync(self, local, maximum=None, apply=False):
        """Upsert de cesta local. Conservar productos remotos no mencionados."""
        self.pending()
        basket = self.get()
        quantities = self.quantities(basket)
        quantities.update(local)
        estimate = price_basket(self.client, quantities, maximum)
        plan = {"scope": "account", "applied": False, "basket_id": (basket or {}).get("basketId"),
                "set_quantities": local, "preserves_other_products": True, "catalog_estimate_cents": estimate["subtotal_cents"],
                "order_submitted": False}
        if not apply or not local:
            return plan
        if not basket:
            body = {"productItems": [{"productId": key, "quantity": float(decimal(value))} for key, value in local.items()]}
            updated = self.mutate(None, "baskets", "POST", body, "sync")
        else:
            updated = basket
            items = {item["productId"]: item["itemId"] for item in basket.get("productItems", [])}
            changes = [{"itemId": items[key], "quantity": float(decimal(value))} for key, value in local.items() if key in items]
            additions = [{"productId": key, "quantity": float(decimal(value))} for key, value in local.items() if key not in items]
            # Confirmar cada lote. Dos lotes no constituyen una transacción remota.
            if changes:
                updated = self.mutate(updated, "baskets/" + identifier(updated["basketId"]) + "/items", "PATCH", changes, "sync-set")
            if additions:
                updated = self.mutate(updated, "baskets/" + identifier(updated["basketId"]) + "/items", "POST", additions, "sync-add")
        return {**summary(updated), "applied": True, "atomic": False,
                "quantities_confirmed": self.quantities(updated) == quantities}

    def clear(self, apply=False):
        self.pending()
        basket = self.get()
        if not apply:
            return {**summary(basket or {}), "applied": False, "next_step": "Usa --apply para eliminar todas las líneas de esta cesta."}
        if basket:
            for line in list(basket.get("productItems", [])):
                basket = self.mutate(basket, "baskets/" + identifier(basket["basketId"]) + "/items/" +
                                     identifier(line["itemId"]), "DELETE", None, "clear")
        return {**summary(basket or {}), "applied": True, "atomic": False,
                "empty_confirmed": not (basket or {}).get("productItems")}

    def shipment(self, basket, shipment_id=None):
        shipments = basket.get("shipments", [])
        if shipment_id:
            matching = [shipment for shipment in shipments if shipment.get("shipmentId") == shipment_id]
        else:
            matching = shipments if len(shipments) == 1 else []
        if len(matching) != 1:
            raise Error("Selecciona un envío existente con --shipment-id.")
        return matching[0]

    def shipping_methods(self, shipment_id=None):
        basket = self.get()
        if not basket:
            raise Error("La cuenta no tiene una cesta.")
        shipment = self.shipment(basket, shipment_id)
        return self.client.account_api(SERVICE, "baskets/" + identifier(basket["basketId"]) + "/shipments/" +
                                       identifier(shipment["shipmentId"]) + "/shipping-methods")

    def set_shipping(self, address_id=None, method_id=None, shipment_id=None):
        self.pending()
        basket = self.get()
        if not basket:
            raise Error("La cuenta no tiene una cesta.")
        shipment = self.shipment(basket, shipment_id)
        resource = "baskets/" + identifier(basket["basketId"]) + "/shipments/" + identifier(shipment["shipmentId"])
        if address_id:
            addresses = self.client.addresses()["addresses"]
            address = next((item for item in addresses if item.get("addressId") == address_id), None)
            if not address:
                raise Error("La dirección no está guardada en esta cuenta.")
            fields = ("address1", "address2", "city", "companyName", "countryCode", "firstName", "lastName", "phone", "postalCode", "stateCode")
            body = {key: address[key] for key in fields if key in address}
            updated = self.mutate(basket, resource + "/shipping-address", "PUT", body, "shipping-address")
        else:
            methods = self.shipping_methods(shipment["shipmentId"])
            if method_id not in {item.get("id") for item in methods.get("applicableShippingMethods", [])}:
                raise Error("El método no está disponible para este envío.")
            updated = self.mutate(basket, resource + "/shipping-method", "PUT", {"id": method_id}, "shipping-method")
        return summary(updated)


def postal_code(client, code):
    if not re.fullmatch(r"\d{5}", code):
        raise Error("El código postal debe tener cinco dígitos.")
    return client.api("custom/postal-codes", "postal-codes/" + code)
