"""Tiendas públicas y servicios declarados por Ametller."""

import re

from .remote import identifier, postal_code
from .storage import Error


def normalize_store(store):
    return {"id": store.get("id"), "name": store.get("name"), "address": store.get("address1"),
            "postal_code": store.get("postalCode"), "city": store.get("city"), "phone": store.get("phone"),
            "latitude": store.get("latitude"), "longitude": store.get("longitude"),
            "distance": store.get("distance"), "distance_unit": store.get("distanceUnit"),
            "hours": store.get("storeHours"), "pickup_standard": store.get("c_info_click_collect_standar"),
            "pickup_express": store.get("c_info_click_collect_express"),
            "home_standard": store.get("c_info_domicilio_standard"),
            "home_express": store.get("c_info_domicilio_express")}


def find_stores(client, postcode, limit=20, distance=20, pickup_only=False):
    if not re.fullmatch(r"\d{5}", postcode):
        raise Error("El código postal debe tener cinco dígitos.")
    if not 1 <= limit <= 200 or not 1 <= distance <= 500:
        raise Error("Usa un límite de 1 a 200 tiendas y una distancia de 1 a 500 km.")
    coverage = postal_code(client, postcode)
    lat, lon = coverage.get("latitude"), coverage.get("longitude")
    if lat is None or lon is None:
        raise Error("La tienda no proporciona coordenadas para ese código postal.")
    raw = client.api("store/shopper-stores", "store-search", {
        "latitude": lat, "longitude": lon, "distanceUnit": "km", "maxDistance": distance,
        "limit": limit, "locale": client.lang})
    stores = [normalize_store(store) for store in raw.get("data", [])]
    if pickup_only:
        stores = [store for store in stores if store["pickup_standard"] is True or store["pickup_express"] is True]
    return {"postal_code": postcode, "total_in_radius": raw.get("total"), "returned": len(stores),
            "stores": stores, "notice": "Servicios declarados por la tienda. La franja se comprueba con la cesta real."}


def get_store(client, store_id):
    raw = client.api("store/shopper-stores", "stores", {"ids": identifier(store_id), "locale": client.lang})
    stores = raw.get("data", [])
    if len(stores) != 1 or stores[0].get("id") != store_id:
        raise Error("La tienda solicitada no existe en el catálogo de Ametller.")
    return normalize_store(stores[0])
