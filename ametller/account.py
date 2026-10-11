"""Sesión de cuenta: importar sólo autenticación de Ametller y validar en servidor."""

import base64
import json
import getpass
import hashlib
import math
import re
import secrets
import sys
import time
from http.cookies import SimpleCookie, CookieError
from urllib.parse import parse_qs, quote, unquote, urlencode, urlparse

from .client import Client, HTTPFailure, ORIGIN, PROXY
from .storage import Error

HOSTS = {"ametllerorigen.com", "www.ametllerorigen.com"}


def token_identity(token):
    """Leer metadatos para enrutar. El GET al servidor valida el token de verdad."""
    try:
        payload = json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "=="))
        segments = payload["isb"].split("::")
        guest = "upn:Guest" in segments
        customer = next(part.split(":", 1)[1] for part in segments if part.startswith("gcid:" if guest else "rcid:"))
        site = next(part.split(":", 1)[1] for part in segments if part.startswith("chid:"))
        if not re.fullmatch(r"[\w-]{1,150}", customer):
            raise ValueError()
        expiry = float(payload["exp"])
        if not math.isfinite(expiry):
            raise ValueError()
        return {"customer_id": customer, "site_id": site, "guest": guest, "expires_at": expiry}
    except (ValueError, KeyError, TypeError, IndexError, StopIteration):
        raise Error("El archivo no contiene un token de sesión de Ametller válido.") from None


def trusted_url(value, config):
    parsed = urlparse(value)
    if parsed.scheme != "https":
        return False
    return parsed.hostname in HOSTS or parsed.hostname == config.get("shortCode", "") + ".api.commercecloud.salesforce.com"


def extract_har(har, config):
    """No leer contraseñas de postData ni guardar el HAR completo."""
    candidates, cookies = {}, {}
    try:
        entries = har["log"]["entries"]
    except (KeyError, TypeError):
        raise Error("Formato HAR inválido.") from None
    for entry in entries:
        request = entry.get("request", {})
        url = request.get("url", "")
        if not trusted_url(url, config):
            continue
        parsed = urlparse(url)
        response = entry.get("response", {})
        # Evitar importar sesiones de otra organización SCAPI.
        path = parsed.path
        scapi = "/organizations/" + config["organizationId"] + "/" in path
        if scapi:
            for header in request.get("headers", []):
                if header.get("name", "").lower() == "authorization":
                    value = header.get("value", "")
                    if value.startswith("Bearer "):
                        candidates.setdefault(value[7:], {})
            if "/shopper/auth/" in path and (path.endswith("/token") or path.endswith("/session-bridge/token")):
                content = response.get("content", {})
                try:
                    text = content.get("text", "")
                    if content.get("encoding") == "base64":
                        text = base64.b64decode(text).decode()
                    data = json.loads(text)
                    if data.get("access_token"):
                        candidates[data["access_token"]] = {"refresh_token": data.get("refresh_token")}
                except (ValueError, TypeError, UnicodeError):
                    pass
        if parsed.hostname in HOSTS:
            cookie_list = request.get("cookies", []) + response.get("cookies", [])
            for header in request.get("headers", []):
                if header.get("name", "").lower() == "cookie":
                    try:
                        raw_cookies = SimpleCookie(header.get("value", ""))
                        cookie_list += [{"name": name, "value": morsel.value} for name, morsel in raw_cookies.items()]
                    except CookieError:
                        pass
            for cookie in cookie_list:
                name, value = cookie.get("name", ""), cookie.get("value", "")
                if re.fullmatch(r"dwsid|dwsecuretoken[\w-]*|dwanonymous[\w-]*|usid_[\w-]+|(?:__Secure-)?cc-(?:at|rt|nx|cid)[\w-]*", name):
                    if not re.search(r"[\r\n;]", value):
                        cookies[name] = value
                        if re.fullmatch(r"(?:__Secure-)?cc-at[\w-]*", name):
                            candidates.setdefault(unquote(value).removeprefix("Bearer "), {})
    sessions = []
    for token, metadata in candidates.items():
        try:
            identity = token_identity(token)
        except Error:
            continue
        if not identity["guest"] and identity["site_id"] == config["siteId"]:
            sessions.append({**identity, **metadata, "access_token": token})
    if not sessions:
        raise Error("El HAR no contiene una sesión de cuenta. Recarga estando conectado y exporta incluyendo datos sensibles.")
    if len({session["customer_id"] for session in sessions}) != 1:
        raise Error("El HAR contiene varias cuentas; exporta una captura nueva de la cuenta que quieres conectar.")
    selected = max(sessions, key=lambda session: session["expires_at"])
    # Recuperar renovación sólo si la cookie identifica de forma inequívoca este sitio.
    for name, value in cookies.items():
        # PWA Kit guarda refresh_token_registered como cc-nx_<sitio>.
        if re.fullmatch(r"(?:__Secure-)?cc-(?:rt|nx)_?" + re.escape(config["siteId"]), name):
            if not selected.get("refresh_token"):
                selected["refresh_token"] = unquote(value)
    selected["cookies"] = cookies
    return selected


class AccountClient(Client):
    catalog_context = "account"

    def __init__(self, *args, account=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.account_override = account

    def authenticate(self, force=False):
        self.discover()
        with self.storage.lock("account"):
            account = self.account_override or self.storage.read("account.json")
            if not account:
                raise Error("Conecta tu cuenta con ametller import-har --file <archivo>.")
            if account.get("config") != {key: self.config[key] for key in ("clientId", "organizationId", "siteId")}:
                raise Error("La configuración de la cuenta ha cambiado. Vuelve a importar la sesión.")
            identity = token_identity(account.get("access_token", ""))
            if identity["guest"] or identity["customer_id"] != account.get("customer_id") or identity["site_id"] != self.config["siteId"]:
                raise Error("La sesión guardada no corresponde a la cuenta conectada.")
            if force or account.get("expires_at", 0) <= time.time() + 60:
                if not account.get("refresh_token"):
                    raise Error("La sesión de cuenta ha caducado y no incluye renovación. Importa un HAR nuevo.")
                token = self.json_request(PROXY + "/shopper/auth/v1/organizations/" + self.config["organizationId"] + "/oauth2/token",
                                          method="POST", body=urlencode({
                                              "grant_type": "refresh_token", "refresh_token": account["refresh_token"],
                                              "client_id": self.config["clientId"], "channel_id": self.config["siteId"],
                                          }).encode(), headers={"Content-Type": "application/x-www-form-urlencoded"})
                identity = token_identity(token.get("access_token", ""))
                if identity["guest"] or identity["customer_id"] != account["customer_id"] or identity["site_id"] != self.config["siteId"]:
                    raise Error("La renovación no corresponde a la cuenta conectada; operación detenida.")
                account = {**account, **identity, "access_token": token["access_token"], "refresh_token": token.get("refresh_token") or account["refresh_token"]}
                # Mantener el checkout con la renovación vigente. PWA Kit
                # elimina cc-at al cambiar el token para que SFRA lo regenere.
                cookies = {name: value for name, value in account.get("cookies", {}).items()
                           if not re.fullmatch(r"(?:__Secure-)?cc-at[\w-]*", name)}
                cookie_name = "cc-nx_" + self.config["siteId"]
                if cookies:
                    cookies[cookie_name] = quote(account["refresh_token"], safe="")
                account["cookies"] = cookies
                if self.account_override is None:
                    self.storage.write("account.json", account)
                else:
                    self.account_override = account
            self.session = account

    def account_api(self, service, resource, params=None, method="GET", body=None):
        from .checkoutguard import allow_account_request
        allow_account_request(service, resource, method)
        self.authenticate()
        url = PROXY + f"/{service}/v1/organizations/{self.config['organizationId']}/{resource}"
        query = {"siteId": self.config["siteId"], **(params or {})}
        if service.startswith(("product/", "search/")):
            query.setdefault("locale", self.lang)
        url += "?" + urlencode(query, doseq=True)
        options = {"method": method, "headers": {"Authorization": "Bearer " + self.session["access_token"]}}
        if body is not None:
            options["body"] = json.dumps(body, allow_nan=False).encode()
            options["headers"]["Content-Type"] = "application/json"
        try:
            if method == "DELETE":
                result = self.request(url, **options)
                return json.loads(result) if result else None
            return self.json_request(url, **options)
        except HTTPFailure as error:
            # Sólo reintentar lecturas. Nunca repetir una mutación cuyo resultado sea incierto.
            if error.status != 401 or method != "GET":
                raise
            self.authenticate(force=True)
            options["headers"]["Authorization"] = "Bearer " + self.session["access_token"]
            return self.json_request(url, **options)

    def api(self, service, resource, params=None):
        return self.account_api(service, resource, params)

    def customer(self):
        self.authenticate()
        return self.account_api("customer/shopper-customers", "customers/" + quote(self.session["customer_id"], safe=""))

    def whoami(self):
        customer = self.customer()
        if customer.get("customerId") != self.session["customer_id"] or customer.get("authType") == "guest":
            raise Error("El servidor no confirmó la cuenta importada.")
        return {"connected": True, "session_type": "registered", "customer_id": customer["customerId"],
                "first_name": customer.get("firstName"), "last_name": customer.get("lastName"),
                "email": customer.get("email"), "refresh_available": bool(self.session.get("refresh_token")),
                "expires_at": self.session["expires_at"], "session_mode": self.session.get("session_mode", "slas_token")}

    def baskets(self):
        self.authenticate()
        return self.account_api("customer/shopper-customers", "customers/" + self.session["customer_id"] + "/baskets")

    def orders(self, limit=10, offset=0):
        self.authenticate()
        return self.account_api("customer/shopper-customers", "customers/" + self.session["customer_id"] + "/orders", {"limit": limit, "offset": offset})

    def addresses(self):
        return {"addresses": self.customer().get("addresses", [])}


def save_account(token, client, storage):
    identity = token_identity(token.get("access_token", ""))
    if identity["guest"] or identity["site_id"] != client.config["siteId"]:
        raise Error("El servidor no devolvió una sesión de cuenta de Ametller.")
    account = {**identity, "access_token": token["access_token"], "refresh_token": token.get("refresh_token"),
               "config": {key: client.config[key] for key in ("clientId", "organizationId", "siteId")}}
    probe = AccountClient(lang=client.lang, storage=storage, account=account)
    profile = probe.whoami()
    with storage.lock("account"):
        storage.write("account.json", probe.session)
    return profile


def login(storage, lang="es", email=None):
    """SLAS B2C PKCE. Contraseña sólo desde terminal, nunca argumentos o disco."""
    if not sys.stdin.isatty():
        raise Error("login requiere un terminal interactivo para ocultar la contraseña. También puedes usar import-har.")
    if not email:
        print("Email de Ametller: ", end="", file=sys.stderr, flush=True)
        email = sys.stdin.readline().strip()
    if not email or ":" in email or any(char in email for char in "\r\n"):
        raise Error("Email inválido.")
    client = Client(lang=lang, storage=storage)
    client.discover()
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    redirect_uri = ORIGIN + "/callback"
    auth = PROXY + "/shopper/auth/v1/organizations/" + client.config["organizationId"] + "/oauth2"
    password = getpass.getpass("Contraseña (no se guarda): ")
    if not password:
        raise Error("La contraseña no puede estar vacía.")
    authorization = "Basic " + base64.b64encode((email + ":" + password).encode()).decode()
    del password
    try:
        location = client.request(auth + "/login", method="POST", body=urlencode({
            "code_challenge": challenge, "usid": secrets.token_hex(16), "channel_id": client.config["siteId"],
            "client_id": client.config["clientId"], "redirect_uri": redirect_uri,
        }).encode(), headers={"Authorization": authorization, "Content-Type": "application/x-www-form-urlencoded"}, redirect=True)
    except HTTPFailure as error:
        if error.status in (400, 401, 403):
            raise Error("No se pudo conectar por SLAS B2C. Comprueba el acceso en la web; puedes importar su sesión con import-har.") from None
        raise
    finally:
        del authorization
    if not isinstance(location, str):
        raise Error("La tienda no devolvió la redirección de acceso esperada. Usa import-har.")
    parsed, expected = urlparse(location), urlparse(redirect_uri)
    if (parsed.scheme, parsed.netloc, parsed.path) != (expected.scheme, expected.netloc, expected.path):
        raise Error("Redirección de acceso inesperada; operación detenida.")
    code = parse_qs(parsed.query).get("code", [None])[0]
    if not code:
        raise Error("No se recibió un código de acceso. Usa import-har.")
    token = client.json_request(auth + "/token", method="POST", body=urlencode({
        "grant_type": "authorization_code_pkce", "code_verifier": verifier, "code": code,
        "client_id": client.config["clientId"], "redirect_uri": redirect_uri, "channel_id": client.config["siteId"],
    }).encode(), headers={"Content-Type": "application/x-www-form-urlencoded"})
    return save_account(token, client, storage)


def import_har(path, storage, lang="es"):
    try:
        with open(path, encoding="utf-8") as file:
            har = json.load(file)
    except (OSError, ValueError):
        raise Error("No se pudo leer el HAR; revisa el archivo local.") from None
    guest = Client(lang=lang, storage=storage)
    guest.discover()
    account = extract_har(har, guest.config)
    account["config"] = {key: guest.config[key] for key in ("clientId", "organizationId", "siteId")}
    probe = AccountClient(lang=lang, storage=storage, account=account)
    profile = probe.whoami()
    # El servidor valida el token antes de sustituir una sesión existente.
    with storage.lock("account"):
        storage.write("account.json", probe.session)
    return profile
