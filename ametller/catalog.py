from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re

from .client import ORIGIN
from .storage import Error
from .promotions import normalize_promotions


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def decimal(value, label="cantidad"):
    try:
        result = Decimal(str(value))
        if not result.is_finite():
            raise InvalidOperation()
        return result
    except (InvalidOperation, ValueError):
        raise Error(f"{label.capitalize()} inválida: {value!r}.") from None


def cents(value):
    return int((decimal(value, "precio") * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def normalize(raw):
    product_id = str(raw.get("id") or raw.get("productId") or "")
    if not product_id:
        raise Error("La tienda devolvió un producto sin ID.")
    instaleap = raw.get("c_instaleapHit") or {}
    image = raw.get("image", {}).get("link")
    if not image:
        for group in raw.get("imageGroups", []):
            if group.get("images"):
                image = group["images"][0].get("link")
                break
    price = raw.get("price")
    inventory = raw.get("inventory") or {}
    return {
        "id": product_id,
        "name": raw.get("name") or raw.get("productName"),
        "price": price,
        "price_cents": cents(price) if price is not None else None,
        "currency": raw.get("currency"),
        "price_per_unit": raw.get("pricePerUnit"),
        "reference_unit": raw.get("unitMeasure") or instaleap.get("unit"),
        "unit_quantity": raw.get("unitQuantity") if "unitQuantity" in raw else instaleap.get("quantity"),
        "min_order_quantity": raw.get("minOrderQuantity"),
        "step_quantity": raw.get("stepQuantity"),
        # La disponibilidad de catálogo no confirma reparto o stock de una dirección.
        "orderable": inventory.get("orderable"),
        "availability_scope": "catalog",
        "brand": raw.get("brand"),
        "ean": raw.get("ean") or next(iter(instaleap.get("barcodes", [])), None),
        "url": raw.get("slugUrl"),
        "image": image,
        "category_id": raw.get("primaryCategoryId") or instaleap.get("attributes", {}).get("category"),
        "ingredients": raw.get("c_ao_ingredientes"),
        "allergen_codes": raw.get("c_ao_allergens"),
        "nutrition_text": raw.get("c_ao_nutrients"),
        "conservation": raw.get("c_ao_conservation"),
        "origin": raw.get("c_ao_origen"),
        "approximate_weight": raw.get("c_ao_pesoAproximado"),
        "is_sale": raw.get("c_isSale"),
        "promotions": normalize_promotions(raw),
    }


def validate_id(value):
    if not re.fullmatch(r"[\w-]{1,100}", value):
        raise Error("ID de producto o categoría inválido.")
    return value


def parse_basket(text):
    result = {}
    for index, line in enumerate(text.splitlines(), 1):
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 2:
            raise Error(f"Línea {index}: se espera <id> <cantidad>.")
        product_id = validate_id(parts[0])
        if product_id in result:
            raise Error(f"Línea {index}: ID duplicado {product_id}.")
        quantity = decimal(parts[1])
        if quantity < 0 or quantity > 10000:
            raise Error(f"Línea {index}: cantidad fuera del rango 0–10000.")
        result[product_id] = str(quantity)
    return result


def price_basket(client, basket, max_eur=None):
    for product_id, value in basket.items():
        validate_id(product_id)
        if not 0 <= decimal(value) <= 10000:
            raise Error(f"{product_id}: cantidad fuera del rango 0–10000.")
    active = {product_id: quantity for product_id, quantity in basket.items() if decimal(quantity) > 0}
    raw = client.products(list(active)) if active else []
    products = {str(product["id"]): normalize(product) for product in raw}
    lines, total_cents = [], 0
    for product_id, value in active.items():
        quantity = decimal(value)
        product = products.get(product_id)
        if product is None or product["price"] is None:
            raise Error(f"No hay precio confirmado para {product_id}; cesta sin modificar.")
        if product["currency"] != "EUR" or product["price_cents"] < 0:
            raise Error(f"Precio o moneda no admitidos para {product_id}.")
        if product["orderable"] is not True:
            raise Error(f"El catálogo no confirma disponibilidad de {product_id}; cesta sin modificar.")
        minimum, step = product["min_order_quantity"], product["step_quantity"]
        if minimum is None or step is None or decimal(step) <= 0:
            raise Error(f"No se puede verificar la unidad de venta de {product_id}.")
        minimum, step = decimal(minimum), decimal(step)
        if quantity < minimum or (quantity - minimum) % step != 0:
            raise Error(f"{product_id}: cantidad mínima {minimum}, incrementos de {step} unidades de venta.")
        # price es el precio de la unidad de venta, no el precio por kg/litro.
        line_cents = cents(decimal(product["price"]) * quantity)
        total_cents += line_cents
        lines.append({"product": product, "quantity": str(quantity), "line_total_cents": line_cents, "line_total": line_cents / 100})
    if max_eur is not None:
        maximum = decimal(max_eur, "presupuesto")
        if maximum < 0:
            raise Error("El presupuesto no puede ser negativo.")
        if Decimal(total_cents) > maximum * 100:
            raise Error(f"Presupuesto superado: {total_cents / 100:.2f} € > {maximum} €. Cesta sin modificar.")
    return {
        "scope": "local", "currency": "EUR", "lines": lines,
        "subtotal_cents": total_cents, "subtotal": total_cents / 100,
        "count": len(lines), "complete": True, "shipping_included": False,
        "price_scope": getattr(client, "catalog_context", "guest") + "_catalog_estimate", "fetched_at": timestamp(),
        "source": ORIGIN,
        "notice": "Estimación de catálogo: peso final, promociones de cuenta, stock por dirección y entrega se confirman en la tienda.",
    }
