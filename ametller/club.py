"""Lectura de cupones con sesión propia de la app, independiente de la cuenta web."""

import base64
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import stat
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

from .client import NoRedirect, USER_AGENT
from .storage import Error, Storage

COUPONS_URL = "https://app.ametllerorigen.cat/api/mobile/v3/coupons"
SESSION_FILE = "club-account.json"
PROJECT = Path(__file__).resolve().parents[1]


def bearer(value):
    if not isinstance(value, str) or not re.fullmatch(r"Bearer [A-Za-z0-9_.~-]{20,12000}", value):
        raise Error("La captura no contiene una autorización móvil válida.")
    return value


def expires_at(authorization):
    # Metadato opcional; la identidad y validez de la sesión se verifican en la API.
    try:
        part = authorization.partition(" ")[2].split(".")[1]
        payload = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
        if not isinstance(payload, dict):
            return None
        expiry = payload.get("exp")
        if type(expiry) not in (int, float) or not math.isfinite(expiry):
            return None
        return datetime.fromtimestamp(expiry, timezone.utc).isoformat()
    except (ValueError, KeyError, IndexError, TypeError, OverflowError, OSError):
        return None


def validate_coupons(value):
    if not isinstance(value, list) or len(value) > 5000:
        raise Error("El formato de cupones de la app ha cambiado; revisa la integración.")
    ids = set()
    for item in value:
        if (not isinstance(item, dict) or not isinstance(item.get("id"), str)
                or not item["id"] or item["id"] in ids or not isinstance(item.get("title"), str)
                or not isinstance(item.get("status"), str)):
            raise Error("El formato de cupones de la app ha cambiado; revisa la integración.")
        ids.add(item["id"])
    return value


def normalize_coupon(item):
    fields = ("id", "title", "status", "badge_text", "date_from", "date_to", "description",
              "legal_conditions_link", "discount", "discount_type", "image_url", "partner_name",
              "partner_description")
    result = {field: item.get(field) for field in fields}
    for field in fields:
        value = result[field]
        if field == "discount":
            if value is not None and (type(value) not in (int, float) or not math.isfinite(value)):
                result[field] = None
        elif value is not None and not isinstance(value, str):
            result[field] = None
    result["title"] = item["title"].strip()
    result["active"] = {"active": True, "inactive": False}.get(item["status"])
    return result


class MobileClub:
    def __init__(self, storage=None, lang="es"):
        self.storage = storage if storage is not None else Storage()
        self.lang = lang
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def fetch(self, authorization):
        if self.lang not in ("es", "ca"):
            raise Error("Idioma móvil inválido.")
        request = Request(COUPONS_URL, method="GET", headers={
            "Authorization": bearer(authorization), "Accept": "application/json",
            "Accept-Language": self.lang, "Content-Type": "application/json", "User-Agent": USER_AGENT})
        try:
            with self.opener.open(request, timeout=30) as response:
                if response.status != 200:
                    raise Error(f"Respuesta de cupones inesperada (HTTP {response.status}).")
                raw = response.read(5_000_001)
                if len(raw) > 5_000_000:
                    raise Error("La respuesta de cupones supera el tamaño permitido.")
        except HTTPError as error:
            error.close()
            if error.code in (401, 403):
                raise Error("La app rechazó la sesión del Club. Importa una nueva captura propia; el login web no sustituye esta sesión.") from None
            raise Error(f"La API de cupones respondió HTTP {error.code}. No se activó ningún cupón.") from None
        except (URLError, TimeoutError, OSError):
            raise Error("No se pudo consultar la API de cupones. No se activó ningún cupón.") from None
        try:
            data = json.loads(raw)
        except (ValueError, UnicodeError):
            raise Error("La API de cupones no devolvió JSON válido.") from None
        return validate_coupons(data)

    def session(self):
        session = self.storage.read(SESSION_FILE)
        if not isinstance(session, dict) or session.get("schema_version") != 1:
            raise Error("Conecta el Club con ametller club import-capture --file <captura privada de la app>.")
        bearer(session.get("authorization"))
        return session

    def result(self, data, coupon_id=None, status=None, raw=False):
        selected = [item for item in data if (coupon_id is None or item["id"] == coupon_id)
                    and (status is None or item["status"] == status)]
        if coupon_id is not None and not selected:
            raise Error("El cupón solicitado no está en la lista de esta cuenta o no coincide con el filtro.")
        return {"scope": "club_mobile", "total": len(data), "returned": len(selected),
                "coupons": selected if raw else [normalize_coupon(item) for item in selected],
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "source": COUPONS_URL, "activation_supported": False,
                "basket_discount_verified": False, "payment_submitted": False, "order_submitted": False,
                "notice": "Cupones personales de la app. Consulta de sólo lectura; condiciones, activación y aplicación final se comprueban en Ametller."}

    def coupons(self, coupon_id=None, status=None, raw=False):
        if status is not None and status not in ("active", "inactive"):
            raise Error("Filtro de estado de cupón inválido.")
        with self.storage.lock("club"):
            session = self.session()
            data = self.fetch(session["authorization"])
        return self.result(data, coupon_id, status, raw)

    def status(self):
        with self.storage.lock("club"):
            session = self.session()
            data = self.fetch(session["authorization"])
        return {"scope": "club_mobile", "connected": True, "verified_by": "coupons_api",
                "coupon_count": len(data), "expires_at": expires_at(session["authorization"]),
                "automatic_refresh_supported": False, "activation_supported": False}

    def import_capture(self, filename):
        path = Path(filename).expanduser()
        if path.resolve().is_relative_to(PROJECT):
            raise Error("La captura de sesión debe estar fuera del repositorio.")
        try:
            info = path.stat()
            if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_size > 10_000_000:
                raise Error("La captura debe ser un archivo privado (permisos 600), de menos de 10 MB.")
            capture = json.loads(path.read_text())
        except (OSError, ValueError, UnicodeError):
            raise Error("No se pudo leer la captura privada de la app.") from None
        if (not isinstance(capture, dict) or capture.get("method") != "GET"
                or capture.get("url") != COUPONS_URL or capture.get("response_status") != 200
                or not isinstance(capture.get("request_headers"), dict)):
            raise Error("La captura debe corresponder al GET de cupones de la app de Ametller.")
        candidates = [value for key, value in capture["request_headers"].items()
                      if isinstance(key, str) and key.lower() == "authorization"]
        if len(candidates) != 1:
            raise Error("La captura no contiene una única autorización móvil.")
        authorization = bearer(candidates[0])
        with self.storage.lock("club"):
            data = self.fetch(authorization)
            self.storage.write(SESSION_FILE, {"schema_version": 1, "authorization": authorization,
                               "connected_at": datetime.now(timezone.utc).isoformat()})
        return {"scope": "club_mobile", "connected": True, "verified_by": "coupons_api",
                "coupon_count": len(data), "expires_at": expires_at(authorization),
                "automatic_refresh_supported": False, "activation_supported": False,
                "cookies_saved": False, "password_saved": False}
