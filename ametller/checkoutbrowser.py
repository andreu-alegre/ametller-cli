"""Abrir el checkout oficial para el usuario, sin automatizar pagos."""

from http.cookiejar import Cookie
import re
import sys
import time
from urllib.parse import unquote, urlparse

from .account import AccountClient
from .catalog import cents, decimal
from .storage import Error
from .webcheckout import ORIGIN, WebCheckout, controller_url, web_total_cents

COOKIE_NAMES = re.compile(r"dwsid|dwsecuretoken[\w-]*|dwanonymous[\w-]*|usid_[\w-]+|(?:__Secure-)?cc-(?:at|nx|cid)[\w-]*")


def browser_cookies(values, site_id):
    if not isinstance(values, dict) or not isinstance(site_id, str) or not re.fullmatch(r"[\w-]{1,150}", site_id):
        raise Error("Sesión web inválida; vuelve a conectar con login.")
    if "cc-nx-g_" + site_id in values or not values.get("dwsid"):
        raise Error("Falta una sesión web registrada; conecta con ametller login.")
    result = []
    for name, value in values.items():
        if not COOKIE_NAMES.fullmatch(name):
            continue
        if not isinstance(value, str) or not value or len(value) > 16000 or re.search(r"[\r\n;]", value):
            raise Error("Cookie de cuenta inválida; vuelve a conectar con login.")
        result.append({"name": name, "value": value, "domain": ".ametllerorigen.com", "path": "/",
                       "secure": True, "httpOnly": not name.startswith(("cc-", "__Secure-cc-")), "sameSite": "Lax"})
    return result


def review_request_allowed(url, method):
    """Revisión: sin escrituras, proveedor de pago ni controladores SFRA desconocidos."""
    if method not in ("GET", "HEAD"):
        return False
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    path = unquote(parsed.path).lower()
    query = unquote(parsed.query).lower()
    if host == "adyen.com" or host.endswith(".adyen.com"):
        return False
    if any(word in path + "?" + query for word in ("payment", "placeorder", "submitorder", "adyen")):
        return False
    if host in ("www.ametllerorigen.com", "ametllerorigen.com") and "/on/demandware.store/" in path:
        return path.rsplit("/", 1)[-1] in ("checkoutservices-get", "timeslot-getslots")
    return True


def verify_browser_session(context, web, maximum):
    url = controller_url(web.page.urls.get("data-checkout-get-url"), "CheckoutServices-Get")
    response = context.request.get(url, headers={"X-Requested-With": "XMLHttpRequest"},
                                   max_redirects=0, timeout=30000)
    try:
        if response.status != 200:
            raise Error("El navegador no pudo validar la sesión del checkout. Vuelve a conectar con login.")
        web.verify_model(response.json())
        total = web_total_cents(web.model["order"].get("totals", {}).get("grandTotal"))
        if total is None or total > cents(decimal(maximum)):
            raise Error("El importe del navegador es desconocido o supera --max; no se abrirá el checkout.")
    finally:
        response.dispose()


def persist_browser_auth(context, web):
    # Sólo antes de entregar el control. Nunca leer cookies bancarias ni campos de tarjeta.
    items = context.cookies([ORIGIN, "https://ametllerorigen.com"])
    current = {item["name"]: item["value"] for item in items if item.get("secure") and
               item.get("domain", "").lstrip(".") in ("ametllerorigen.com", "www.ametllerorigen.com")}
    browser_cookies(current, web.client.config["siteId"])
    for name, value in current.items():
        if COOKIE_NAMES.fullmatch(name):
            web.jar.set_cookie(Cookie(0, name, value, None, False, "www.ametllerorigen.com", False, False,
                                     "/", True, True, None, True, None, None, {}, False))
    web.persist_cookies()


def _playwright():
    try:
        from playwright.sync_api import sync_playwright, Error as BrowserError
    except ImportError:
        raise Error("checkout open necesita el extra browser y Chromium, igual que login.") from None
    return sync_playwright, BrowserError


def open_checkout(storage, lang="es", maximum=None, review_only=False, channel="chromium", timeout=900):
    if lang not in ("es", "ca") or channel not in ("chromium", "chrome", "msedge") or not 30 <= timeout <= 1800:
        raise Error("Idioma, navegador o tiempo de checkout inválidos.")
    if maximum is None or decimal(maximum) <= 0:
        raise Error("checkout open requiere --max con un importe positivo para revisar el total inicial.")
    storage.require_private_root()
    factory, BrowserError = _playwright()
    with storage.lock("remote-cart"), storage.lock("web-session"):
        client = AccountClient(lang=lang, storage=storage)
        web = WebCheckout(client).prepare()
        report = web.test(maximum)
        basket = web.remote.get()
        expected_id, quantities = basket["basketId"], web.remote.quantities(basket)
        cookies = browser_cookies(client.session.get("cookies", {}), client.config["siteId"])
    target = ORIGIN + "/" + lang + "/checkout"
    blocked = [0]
    handed_off = False
    print("Abriendo checkout oficial en ventana aislada. " +
          ("Sólo revisión: pagos y escrituras del navegador bloqueados. " if review_only else
           "El pago y la confirmación quedan en tus manos; puedes realizar una compra real. ") +
          "Revisa el total final en Ametller y cierra la ventana al terminar. La CLI no lee tarjetas ni hace clic en pagar.",
          file=sys.stderr, flush=True)
    try:
        with factory() as runtime:
            options = {"headless": False}
            if channel != "chromium":
                options["channel"] = channel
            browser = runtime.chromium.launch(**options)
            try:
                context = browser.new_context(locale="es-ES" if lang == "es" else "ca-ES", service_workers="block")
                context.add_cookies(cookies)
                if review_only:
                    def guard(route):
                        if review_request_allowed(route.request.url, route.request.method):
                            route.fallback()
                        else:
                            blocked[0] += 1
                            route.abort("blockedbyclient")
                    context.route("**/*", guard)
                # Validar la identidad dentro del contexto antes de mostrar la tienda.
                with storage.lock("remote-cart"), storage.lock("web-session"):
                    verify_browser_session(context, web, maximum)
                    persist_browser_auth(context, web)
                    current = web.remote.get()
                    if not current or current["basketId"] != expected_id or web.remote.quantities(current) != quantities:
                        raise Error("La cesta cambió antes de abrir el navegador. Revisa remote-cart get.")
                    report = web.test(maximum)
                page = context.new_page()
                page.goto(target, wait_until="domcontentloaded", timeout=45000)
                location = urlparse(page.url)
                if location.scheme != "https" or location.hostname != "www.ametllerorigen.com" or location.path != "/" + lang + "/checkout":
                    raise Error("La tienda no abrió el checkout esperado. Revisa el mínimo y la sesión en Ametller.")
                handed_off = True
                deadline = time.monotonic() + timeout
                while browser.is_connected() and not page.is_closed() and time.monotonic() < deadline:
                    # No inspeccionar URL, cookies, respuestas o campos después de entregar el control.
                    try:
                        page.wait_for_timeout(1000)
                    except BrowserError:
                        if not browser.is_connected() or page.is_closed():
                            break
                        raise
                timed_out = browser.is_connected() and not page.is_closed()
            finally:
                if browser.is_connected():
                    browser.close()
    except BrowserError:
        if not handed_off or review_only:
            raise Error("No se pudo abrir o mantener el checkout. Comprueba sesión y navegador; instala Chromium como indica login.") from None
        raise Error("La ventana del checkout se interrumpió. Comprueba tus pedidos en Ametller antes de volver a intentar un pago manual.") from None
    return {"scope": "manual_checkout_browser", "browser_opened": True, "checkout_url": target,
            "review_only": review_only, "browser_timed_out": timed_out, "initial_total_cents": report["web_total_cents"],
            "currency": report["currency"], "prepayment_ready": report["prepayment_ready"],
            "pending_checks": [key for key, passed in report["checks"].items() if not passed],
            "cli_payments_blocked": True, "cli_orders_blocked": True, "automated_payment_submitted": False,
            "automated_order_submitted": False, "manual_purchase_possible": not review_only,
            "payment_submitted": False if review_only else None, "order_submitted": False if review_only else None,
            "manual_order_status": "unverified", "budget_enforced_after_handoff": False,
            "review_requests_blocked": blocked[0], "payment_processing_verified": False,
            "notice": "Importe revisado al abrir. Revisa cambios y total final en la web; la CLI no confirma pagos ni pedidos manuales."}
