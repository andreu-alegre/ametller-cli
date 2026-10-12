"""Lectura de cupones con sesión propia de la app, independiente de la cuenta web."""

import base64
import getpass
import hashlib
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import stat
import sys
import warnings
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

from .client import NoRedirect, USER_AGENT
from .storage import Error, Storage

COUPONS_URL = "https://app.ametllerorigen.cat/api/mobile/v3/coupons"
LOGIN_URL = "https://app.ametllerorigen.cat/movil/api/v1/public/login"
SESSION_FILE = "club-account.json"
PENDING_FILE = "club-pending.json"
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


def subject(authorization):
    try:
        part = authorization.partition(" ")[2].split(".")[1]
        value = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))).get("sub")
        return value if isinstance(value, str) and value else None
    except (ValueError, TypeError, AttributeError, IndexError):
        return None


def subject_hash(value):
    return hashlib.sha256(value.casefold().encode()).hexdigest()


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

    def _json(self, url, authorization, method="GET"):
        if self.lang not in ("es", "ca"):
            raise Error("Idioma móvil inválido.")
        login = method == "POST" and url == LOGIN_URL
        activation = method == "POST" and re.fullmatch(re.escape(COUPONS_URL) + r"/[A-Za-z0-9_-]{1,200}/activate/", url)
        if not (login or activation or (method == "GET" and url == COUPONS_URL)):
            raise Error("Operación móvil no permitida.")
        if login:
            if not re.fullmatch(r"Basic [A-Za-z0-9+/]{4,12000}={0,2}", authorization):
                raise Error("Autenticación de login inválida.")
        else:
            bearer(authorization)
        request = Request(url, data=b"" if method == "POST" else None, method=method, headers={
            "Authorization": authorization, "Accept": "application/json",
            "Accept-Language": self.lang, "Content-Type": "application/json", "User-Agent": USER_AGENT})
        try:
            with self.opener.open(request, timeout=30) as response:
                if response.status != 200:
                    raise Error(f"Respuesta móvil inesperada (HTTP {response.status}).")
                raw = response.read(5_000_001)
                if len(raw) > 5_000_000:
                    raise Error("La respuesta de cupones supera el tamaño permitido.")
        except HTTPError as error:
            error.close()
            if error.code in (401, 403):
                message = "El Club rechazó el acceso. Comprueba tus credenciales." if login else "La app rechazó la sesión del Club. Conecta con club login; el login web no sustituye esta sesión."
                raise Error(message) from None
            raise Error(f"La API móvil respondió HTTP {error.code}. No reintentes una activación incierta; consulta coupons.") from None
        except (URLError, TimeoutError, OSError):
            raise Error("No se pudo completar la petición móvil. Si era una activación, consulta coupons antes de otro cambio.") from None
        try:
            data = json.loads(raw)
        except (ValueError, UnicodeError):
            raise Error("La API móvil no devolvió JSON válido.") from None
        return data

    def fetch(self, authorization):
        return validate_coupons(self._json(COUPONS_URL, authorization))

    def login(self, email, password):
        self.storage.require_private_root()
        if (not isinstance(email, str) or not re.fullmatch(r"[^\s@:]+@[^\s@:]+\.[^\s@:]+", email)
                or len(email) > 320 or not isinstance(password, str) or not password or len(password) > 2000):
            raise Error("Email o contraseña de login inválidos.")
        with self.storage.lock("club"):
            pending = self._pending()
            if pending and pending["subject_hash"] != subject_hash(email):
                raise Error("Hay una activación pendiente de otra cuenta. Reconcilia con coupons antes de cambiar de cuenta.")
            basic = "Basic " + base64.b64encode((email + ":" + password).encode()).decode()
            response = self._json(LOGIN_URL, basic, "POST")
            if not isinstance(response, dict):
                raise Error("El formato de login móvil ha cambiado.")
            authorization = bearer(response.get("token"))
            data = self.fetch(authorization)
            identity = subject(authorization)
            if identity is None or identity.casefold() != email.casefold():
                raise Error("El login móvil no devolvió la identidad solicitada; se conserva la conexión anterior.")
            self.storage.write(SESSION_FILE, {"schema_version": 1, "authorization": authorization,
                               "connected_at": datetime.now(timezone.utc).isoformat()})
            unresolved = self._reconcile(data, authorization)
        return {"scope": "club_mobile", "connected": True, "verified_by": "coupons_api",
                "coupon_count": len(data), "expires_at": expires_at(authorization),
                "automatic_refresh_supported": False, "activation_supported": True,
                "activation_pending": unresolved, "password_saved": False, "cookies_saved": False}

    def _pending(self):
        pending = self.storage.read(PENDING_FILE)
        if pending is None:
            return None
        if (not isinstance(pending, dict) or pending.get("schema_version") != 1
                or pending.get("requested_status") != "active" or not isinstance(pending.get("coupon_id"), str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", pending["coupon_id"])
                or not isinstance(pending.get("subject_hash"), str)
                or not re.fullmatch(r"[a-f0-9]{64}", pending["subject_hash"])):
            raise Error("Diario de activación inválido. Revisa el estado privado antes de otro cambio.")
        return pending

    def _reconcile(self, data, authorization):
        pending = self._pending()
        if pending is None:
            return False
        identity = subject(authorization)
        if identity and pending["subject_hash"] == subject_hash(identity):
            if any(item["id"] == pending["coupon_id"] and item["status"] == "active" for item in data):
                self.storage.delete(PENDING_FILE)
                return False
        return True

    def activate(self, coupon_id, apply=False):
        if not isinstance(coupon_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", coupon_id):
            raise Error("Identificador de cupón inválido.")
        with self.storage.lock("club"):
            authorization = self.session()["authorization"]
            data = self.fetch(authorization)
            pending = self._reconcile(data, authorization)
            selected = next((item for item in data if item["id"] == coupon_id), None)
            if selected is None:
                raise Error("El cupón solicitado no está en la lista de esta cuenta.")
            if selected["status"] not in ("active", "inactive"):
                raise Error("El estado del cupón no permite una activación verificada.")
            result = {"scope": "club_mobile", "operation": "activate", "coupon": normalize_coupon(selected),
                      "activation_supported": True, "activation_pending": pending,
                      "activation_needed": selected["status"] == "inactive", "already_active": selected["status"] == "active",
                      "applied": False, "post_sent": False, "payment_submitted": False, "order_submitted": False,
                      "basket_discount_verified": False}
            if not apply:
                return result
            if pending:
                raise Error("Hay una activación incierta pendiente. Consulta coupons; no se enviará otra escritura.")
            if selected["status"] == "active":
                return result
            identity = subject(authorization)
            if identity is None:
                raise Error("No se pudo identificar la cuenta móvil para proteger la activación.")
            self.storage.write(PENDING_FILE, {"schema_version": 1, "coupon_id": coupon_id,
                "subject_hash": subject_hash(identity), "requested_status": "active",
                "started_at": datetime.now(timezone.utc).isoformat()})
            self._json(COUPONS_URL + "/" + coupon_id + "/activate/", authorization, "POST")
            updated = self.fetch(authorization)
            if self._reconcile(updated, authorization):
                raise Error("La activación no quedó confirmada. Se conserva el bloqueo; consulta coupons antes de otro cambio.")
            selected = next(item for item in updated if item["id"] == coupon_id)
            return {**result, "coupon": normalize_coupon(selected), "applied": True, "post_sent": True,
                    "activation_needed": False, "activation_pending": False, "verified_by": "coupons_api"}

    def session(self):
        session = self.storage.read(SESSION_FILE)
        if not isinstance(session, dict) or session.get("schema_version") != 1:
            raise Error("Conecta el Club con ametller club login o club login --form. Alternativa avanzada: club import-capture --file <captura privada de la app>.")
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
                "source": COUPONS_URL, "activation_supported": True,
                "basket_discount_verified": False, "payment_submitted": False, "order_submitted": False,
                "notice": "Cupones personales de la app. Consulta de sólo lectura; condiciones, activación y aplicación final se comprueban en Ametller."}

    def coupons(self, coupon_id=None, status=None, raw=False):
        if status is not None and status not in ("active", "inactive"):
            raise Error("Filtro de estado de cupón inválido.")
        with self.storage.lock("club"):
            session = self.session()
            data = self.fetch(session["authorization"])
            pending = self._reconcile(data, session["authorization"])
        return {**self.result(data, coupon_id, status, raw), "activation_pending": pending}

    def status(self):
        with self.storage.lock("club"):
            session = self.session()
            data = self.fetch(session["authorization"])
            pending = self._reconcile(data, session["authorization"])
        return {"scope": "club_mobile", "connected": True, "verified_by": "coupons_api",
                "coupon_count": len(data), "expires_at": expires_at(session["authorization"]),
                "automatic_refresh_supported": False, "activation_supported": True, "activation_pending": pending}

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
            pending = self._pending()
            identity = subject(authorization)
            if pending and (identity is None or pending["subject_hash"] != subject_hash(identity)):
                raise Error("Hay una activación pendiente de otra cuenta. Reconcilia antes de cambiar la sesión.")
            self.storage.write(SESSION_FILE, {"schema_version": 1, "authorization": authorization,
                               "connected_at": datetime.now(timezone.utc).isoformat()})
            unresolved = self._reconcile(data, authorization)
        return {"scope": "club_mobile", "connected": True, "verified_by": "coupons_api",
                "coupon_count": len(data), "expires_at": expires_at(authorization),
                "automatic_refresh_supported": False, "activation_supported": True,
                "activation_pending": unresolved,
                "cookies_saved": False, "password_saved": False}


def interactive_login(storage, lang="es", form=False, timeout=900):
    mobile = MobileClub(storage, lang)
    if not form:
        if not sys.stdin.isatty():
            raise Error("El login requiere un terminal interactivo o --form. No pases contraseñas por argumentos ni stdin.")
        try:
            email = input("Email del Club: ").strip()
            with warnings.catch_warnings():
                warnings.simplefilter("error", getpass.GetPassWarning)
                password = getpass.getpass("Contraseña del Club: ")
        except (EOFError, getpass.GetPassWarning):
            raise Error("No se pudo leer una contraseña oculta. Usa club login --form; se conserva la conexión anterior.") from None
        try:
            return mobile.login(email, password)
        finally:
            password = None
    if not 30 <= timeout <= 1800:
        raise Error("El tiempo del formulario debe estar entre 30 y 1800 segundos.")
    from .details import _serve_form
    content = ("<!doctype html><html lang='es'><meta charset='utf-8'><title>Ametller CLI · Login del Club</title>"
        "<style>body{font:18px system-ui;max-width:520px;margin:60px auto;padding:20px;background:#faf8f2;color:#233629}"
        "label{display:block;margin:20px 0}input{display:block;width:95%;padding:12px}button{padding:14px;background:#245c37;color:white;border:0}</style>"
        "<h1>Conectar el Club Ametller</h1><p>Formulario local. Envía tus credenciales sólo al servicio de Ametller mediante HTTPS. "
        "La contraseña no se guarda. Conserva únicamente la sesión validada, fuera del repositorio. No activa cupones ni compra.</p>"
        "<form method='post'><label>Email<input name='email' type='email' autocomplete='username' maxlength='320' required></label>"
        "<label>Contraseña<input name='password' type='password' autocomplete='off' maxlength='2000' required></label>"
        "<button>Conectar el Club</button></form></html>").encode()

    def submit(pairs):
        if set(pairs) != {"email", "password"} or any(len(values) != 1 for values in pairs.values()):
            raise Error("Formulario de login inválido.")
        try:
            return mobile.login(pairs["email"][0].strip(), pairs["password"][0])
        finally:
            pairs.clear()

    return _serve_form(content, submit, timeout, "Club conectado", "Sesión validada. No se guardó la contraseña ni se activaron cupones.")
