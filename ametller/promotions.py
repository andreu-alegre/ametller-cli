"""Promociones publicadas por la tienda; no certifica descuentos de una cesta."""

from html.parser import HTMLParser
import re

from .storage import Error


class CalloutText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.hidden += 1
        elif tag in ("br", "p", "div"):
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.hidden = max(0, self.hidden - 1)
        elif tag in ("p", "div"):
            self.parts.append(" ")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def callout_text(value):
    if value is None:
        return None
    parser = CalloutText()
    parser.feed(str(value))
    # El HTML de la tienda no se ejecuta ni puede enviar secuencias al terminal.
    text = re.sub(r"[\x00-\x1f\x7f-\x9f]", " ", "".join(parser.parts))
    return " ".join(text.split()) or None


def normalize_promotions(raw):
    if raw.get("productPromotions") is None:
        return None
    # Importación local: catalog.normalize incorpora estos datos y sus precios.
    from .catalog import cents
    output = []
    for promotion in raw["productPromotions"]:
        label = callout_text(promotion.get("calloutMsg"))
        price = promotion.get("promotionalPrice")
        output.append({
            "id": promotion.get("promotionId"), "label": label,
            "promotional_price": price,
            "promotional_price_cents": cents(price) if price is not None else None,
            # La ausencia de la palabra Club no certifica acceso universal.
            "club_only": True if label and re.search(r"\bclub\b", label, re.I) else None,
        })
    return output


def promotion_result(client, *, query=None, club=False, lots=False, all_results=False,
                     limit=20, offset=0, raw=False):
    from .catalog import normalize, timestamp
    from .client import ORIGIN

    if not 1 <= limit <= 200 or offset < 0:
        raise Error("--limit debe estar entre 1 y 200 y --offset no puede ser negativo.")
    category = "LOTSESTALVI" if lots else "PROMOCIONS"
    # Precio Club (930) está vacío en SCAPI. Filtrar etiquetas de la colección
    # real evita anunciar que no existen ofertas Club o filtrar sólo una página.
    scan_all = club or all_results
    start = 0 if club else offset
    page_size = 200 if scan_all else limit
    hits = []
    total = None
    while True:
        response = client.search(query=query, category=category, limit=page_size, offset=start)
        page = response.get("hits") or []
        if (response.get("selectedRefinements") or {}).get("cgid") != category:
            raise Error("La tienda no confirmó el filtro de promociones; no se muestran resultados generales.")
        current_total = response.get("total")
        if not isinstance(current_total, int) or current_total < 0:
            raise Error("La tienda no confirmó el número de productos de la colección.")
        if total is not None and current_total != total:
            raise Error("La colección cambió durante la consulta. Vuelve a consultar las promociones.")
        total = current_total
        if scan_all and total - (0 if club else offset) > 5000:
            raise Error("Demasiados productos para esta consulta; limita con --query.")
        hits.extend(page)
        if not page and start < total:
            raise Error("La tienda devolvió una página incompleta de promociones. Vuelve a intentarlo.")
        start += len(page)
        if not scan_all or start >= total:
            break
        if not page:
            raise Error("La tienda devolvió una página incompleta de promociones. Vuelve a intentarlo.")

    ids = [str(hit["productId"]) for hit in hits]
    if len(set(ids)) != len(ids):
        raise Error("La colección devolvió productos duplicados entre páginas. Vuelve a consultar.")
    detailed = {str(product["id"]): product for product in client.products(ids)} if ids else {}
    if any(product_id not in detailed for product_id in ids):
        raise Error("No se pudieron comprobar todas las fichas y condiciones de promoción.")
    products = [detailed[product_id] for product_id in ids]
    if club:
        products = [product for product in products
                    if any(promotion["club_only"] is True for promotion in normalize_promotions(product) or [])]
        total = len(products)
        products = products[offset:] if all_results else products[offset:offset + limit]
    return {
        "collection": "lots" if lots else "promotions", "category_id": category,
        "query": query, "club_filter": club, "total": total, "offset": offset,
        "limit": None if all_results else limit,
        "products": products if raw else [normalize(product) for product in products],
        "catalog_context": getattr(client, "catalog_context", "guest"),
        "price_scope": "catalog", "collection_scope": "store_collection",
        "basket_discount_verified": False,
        "fetched_at": timestamp(), "source": ORIGIN,
        "notice": "Colección de la tienda: los precios promocionales y etiquetas no confirman el descuento final de una cesta. Club y cantidades pueden tener condiciones; las fechas no se publican en esta API.",
    }
