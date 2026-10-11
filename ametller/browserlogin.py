"""Conexión interactiva en un navegador aislado, sin exportar un HAR."""

import sys
import time
from urllib.parse import urlparse

from .account import AccountClient, extract_har, token_identity, trusted_url
from .client import Client
from .storage import Error


class LoginCapture:
    """Retener sólo autenticación; nunca cuerpos de peticiones ni contraseñas."""

    def __init__(self, config):
        self.config = config
        self.tokens = {}

    def request(self, url, headers):
        if not trusted_url(url, self.config):
            return
        if "/organizations/" + self.config["organizationId"] + "/" not in urlparse(url).path:
            return
        value = headers.get("authorization", "")
        if value.startswith("Bearer "):
            token = value[7:]
            try:
                identity = token_identity(token)
            except Error:
                return
            if not identity["guest"] and identity["site_id"] == self.config["siteId"]:
                self.tokens[token] = identity

    def account(self, cookies):
        cookie_list = [{"name": item["name"], "value": item["value"]} for item in cookies
                       if item.get("secure") and item.get("domain", "").lstrip(".") in
                       ("ametllerorigen.com", "www.ametllerorigen.com")]
        resource = "https://ametllerorigen.com/mobify/proxy/api/customer/shopper-customers/v1/organizations/" + self.config["organizationId"] + "/customers"
        entries = [{"request": {"url": resource, "headers": [{"name": "Authorization", "value": "Bearer " + token}],
                                "cookies": cookie_list}, "response": {}} for token in self.tokens]
        result = extract_har({"log": {"entries": entries}}, self.config)
        result["config"] = {key: self.config[key] for key in ("clientId", "organizationId", "siteId")}
        return result


def browser_login(storage, lang="es", channel="chromium", timeout=900):
    if not 30 <= timeout <= 1800:
        raise Error("El tiempo de login debe estar entre 30 y 1800 segundos.")
    try:
        from playwright.sync_api import sync_playwright, Error as BrowserError
    except ImportError:
        raise Error("Activa el entorno con Playwright o instala desde el repositorio: python -m pip install -e '.[browser]' y python -m playwright install chromium.") from None
    client = Client(lang=lang, storage=storage)
    client.discover()
    capture = LoginCapture(client.config)
    print("Abriendo Ametller. Inicia sesión en esa ventana; la CLI no lee tu contraseña. Cierra la ventana para cancelar.", file=sys.stderr, flush=True)
    try:
        with sync_playwright() as runtime:
            options = {"headless": False}
            if channel != "chromium":
                options["channel"] = channel
            browser = runtime.chromium.launch(**options)
            try:
                context = browser.new_context(locale="es-ES" if lang == "es" else "ca-ES")
                context.on("request", lambda request: capture.request(request.url, request.all_headers()))
                page = context.new_page()
                page.goto("https://www.ametllerorigen.com/" + lang + "/client-area/profile", wait_until="domcontentloaded")
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    if not browser.is_connected() or page.is_closed():
                        raise Error("Conexión cancelada; se conserva la cuenta anterior.")
                    page.wait_for_timeout(1000)
                    if not capture.tokens:
                        continue
                    # El SDK acaba de entrar: esperar a su cookie de renovación.
                    cookies = context.cookies()
                    if not any(item["name"] == "cc-nx_" + client.config["siteId"] for item in cookies):
                        continue
                    account = capture.account(cookies)
                    probe = AccountClient(lang=lang, storage=storage, account=account)
                    profile = probe.whoami()
                    # Visitar el carrito obtiene la sesión SFRA sin avanzar al checkout.
                    page.goto("https://www.ametllerorigen.com/" + lang + "/cart", wait_until="domcontentloaded")
                    page.wait_for_timeout(1000)
                    account = capture.account(context.cookies())
                    probe = AccountClient(lang=lang, storage=storage, account=account)
                    profile = probe.whoami()
                    if not probe.session.get("cookies", {}).get("dwsid"):
                        raise Error("La cuenta entró, pero falta la sesión de entrega. Vuelve a conectar.")
                    with storage.lock("account"):
                        storage.write("account.json", probe.session)
                    profile.update({"login_method": "browser", "checkout_session_available": True})
                    return profile
                raise Error("Se agotó el tiempo para entrar; se conserva la cuenta anterior.")
            finally:
                if browser.is_connected():
                    browser.close()
    except BrowserError:
        raise Error("No se pudo completar el acceso por navegador. Instala Chromium con python -m playwright install chromium y vuelve a ejecutar login.") from None
