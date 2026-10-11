"""SCAPI de la tienda: configuración actual y OAuth de invitado con PKCE."""

import base64
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
from html.parser import HTMLParser
import json
import random
import re
import secrets
import time
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlencode, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .storage import Error, Storage
from . import __version__

ORIGIN = "https://ametllerorigen.com"
PROXY = ORIGIN + "/mobify/proxy/api"
USER_AGENT = f"ametller-cli/{__version__} (unofficial personal shopping client)"


class HTTPFailure(Error):
    def __init__(self, status):
        self.status = status
        super().__init__(f"La tienda respondió HTTP {status}.")


class ConnectionFailure(Error):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class SiteDataParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.active = False
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag == "script" and dict(attrs).get("id") == "mobify-data":
            self.active = True

    def handle_endtag(self, tag):
        if tag == "script":
            self.active = False

    def handle_data(self, data):
        if self.active:
            self.parts.append(data)


def parse_site_data(html):
    parser = SiteDataParser()
    parser.feed(html)
    try:
        data = json.loads("".join(parser.parts))
        params = data["__CONFIG__"]["app"]["commerceAPI"]["parameters"]
        if not all(isinstance(params[k], str) and re.fullmatch(r"[\w-]+", params[k])
                   for k in ("clientId", "organizationId", "siteId")):
            raise ValueError()
        return data
    except (ValueError, KeyError, TypeError):
        raise Error("La configuración de la tienda ha cambiado; revisa la integración.") from None


def retry_delay(value, attempt):
    if value:
        try:
            return min(30, max(0, float(value)))
        except ValueError:
            try:
                date = parsedate_to_datetime(value)
                return min(30, max(0, (date - datetime.now(timezone.utc)).total_seconds()))
            except (ValueError, TypeError):
                pass
    return min(10, 2 ** attempt + random.random())


class Client:
    def __init__(self, lang="es", storage=None):
        self.lang = lang
        self.storage = storage or Storage()
        self.opener = build_opener(NoRedirect)
        self.config = None
        self.site_data = None
        self.session = None

    def request(self, url, method="GET", body=None, headers=None, redirect=False):
        request = Request(url, data=body, method=method, headers={
            "User-Agent": USER_AGENT, "Accept": "application/json",
            "Accept-Language": self.lang, **(headers or {}),
        })
        attempts = 3 if method == "GET" else 1
        for attempt in range(attempts):
            try:
                with self.opener.open(request, timeout=25) as response:
                    return response.read()
            except HTTPError as error:
                if redirect and error.code in (302, 303):
                    location = error.headers.get("Location", "")
                    error.close()
                    return location
                if method == "GET" and error.code in (429, 502, 503, 504) and attempt + 1 < attempts:
                    delay = retry_delay(error.headers.get("Retry-After"), attempt)
                    error.close()
                    time.sleep(delay)
                    continue
                status = error.code
                error.close()
                raise HTTPFailure(status) from None
            except (URLError, TimeoutError, OSError):
                if attempt + 1 < attempts:
                    time.sleep(retry_delay(None, attempt))
                    continue
                raise ConnectionFailure("No se pudo conectar con la tienda. Comprueba la conexión.") from None

    def json_request(self, *args, **kwargs):
        try:
            return json.loads(self.request(*args, **kwargs))
        except (ValueError, TypeError):
            raise Error("La tienda devolvió una respuesta inesperada.") from None

    def discover(self):
        if self.config is not None:
            return
        cached = self.storage.read("site.json")
        if cached and time.time() - cached.get("fetched_at", 0) < 3600:
            self.config = cached["parameters"]
            return
        self.site_data = parse_site_data(self.request(ORIGIN + f"/{self.lang}/online").decode())
        self.config = self.site_data["__CONFIG__"]["app"]["commerceAPI"]["parameters"]
        self.storage.write("site.json", {"fetched_at": time.time(), "parameters": self.config})

    def authenticate(self, force=False):
        self.discover()
        fingerprint = {k: self.config[k] for k in ("clientId", "organizationId", "siteId")}
        with self.storage.lock("session"):
            cached = self.storage.read("session.json")
            if not force and cached and cached.get("config") == fingerprint and cached.get("expires_at", 0) > time.time() + 60:
                self.session = cached
                return
            auth = PROXY + "/shopper/auth/v1/organizations/" + self.config["organizationId"] + "/oauth2"
            verifier = secrets.token_urlsafe(48)
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
            redirect_uri = ORIGIN + "/callback"
            parameters = {
                "hint": "guest", "response_type": "code", "client_id": self.config["clientId"],
                "code_challenge": challenge, "redirect_uri": redirect_uri, "channel_id": self.config["siteId"],
            }
            location = self.request(auth + "/authorize?" + urlencode(parameters), redirect=True)
            if not isinstance(location, str):
                raise Error("La sesión de invitado no devolvió un código de autorización.")
            parsed = urlparse(location)
            expected = urlparse(redirect_uri)
            if (parsed.scheme, parsed.netloc, parsed.path) != (expected.scheme, expected.netloc, expected.path):
                raise Error("La tienda devolvió una redirección de autorización inesperada.")
            code = parse_qs(parsed.query).get("code", [None])[0]
            if not code:
                raise Error("No se pudo iniciar la sesión de invitado.")
            token = self.json_request(auth + "/token", method="POST", body=urlencode({
                "grant_type": "authorization_code_pkce", "code_verifier": verifier, "code": code,
                "client_id": self.config["clientId"], "redirect_uri": redirect_uri, "channel_id": self.config["siteId"],
            }).encode(), headers={"Content-Type": "application/x-www-form-urlencoded"})
            if not token.get("access_token"):
                raise Error("No se pudo obtener la sesión de invitado.")
            # Sólo el token de invitado; no contraseñas ni tokens de renovación.
            self.session = {"access_token": token["access_token"], "expires_at": time.time() + token["expires_in"], "config": fingerprint}
            self.storage.write("session.json", self.session)

    def api(self, service, resource, params=None):
        self.authenticate()
        url = PROXY + f"/{service}/v1/organizations/{self.config['organizationId']}/{resource}"
        query = {"siteId": self.config["siteId"], **(params or {})}
        if service.startswith(("product/", "search/")):
            query.setdefault("locale", self.lang)
        url += "?" + urlencode(query, doseq=True)
        try:
            return self.json_request(url, headers={"Authorization": "Bearer " + self.session["access_token"]})
        except HTTPFailure as error:
            if error.status != 401:
                raise
            self.authenticate(force=True)
            return self.json_request(url, headers={"Authorization": "Bearer " + self.session["access_token"]})

    def search(self, query=None, category=None, limit=10, offset=0):
        params = {"limit": limit, "offset": offset, "expand": "images,prices", "perPricebook": "true"}
        if query:
            params["q"] = query
        if category:
            params["refine"] = ["cgid=" + category]
        return self.api("search/shopper-search", "product-search", params)

    def product(self, product_id):
        return self.api("product/shopper-products", "products/" + quote(product_id, safe=""), {
            "expand": "images,prices,availability,promotions", "perPricebook": "true",
        })

    def products(self, product_ids):
        # SCAPI admite hasta 24 IDs por petición.
        output = []
        for offset in range(0, len(product_ids), 24):
            response = self.api("product/shopper-products", "products", {
                "ids": ",".join(product_ids[offset:offset + 24]),
                "expand": "images,prices,availability,promotions", "perPricebook": "true",
            })
            output.extend(response.get("data", []))
        return output

    def categories(self):
        # El árbol público viene completo en los datos estructurados del menú.
        data = self.site_data or parse_site_data(self.request(ORIGIN + f"/{self.lang}/online").decode())
        queries = data["__PRELOADED_STATE__"]["__reactQuery"]["queries"]
        for query in queries:
            if query.get("queryKey", [None])[0] == "site-shell":
                try:
                    return query["state"]["data"]["categories"]["categories"]
                except KeyError:
                    break
        raise Error("No se pudo leer el árbol de categorías.")
