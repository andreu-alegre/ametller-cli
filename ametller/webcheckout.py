"""Lecturas del checkout SFRA: descubrir enlaces y franjas reales desde su HTML."""

from html.parser import HTMLParser
from datetime import datetime
from zoneinfo import ZoneInfo
from http.cookiejar import Cookie, CookieJar
import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, Request, build_opener
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse, urljoin, quote, unquote

from .catalog import timestamp
from .client import HTTPFailure, NoRedirect, USER_AGENT
from .account import AccountClient, token_identity
from .remote import RemoteCart, fingerprint, summary
from .stores import get_store
from .storage import Error
from .checkoutguard import allow_web_request

ORIGIN = "https://www.ametllerorigen.com"


class AddressReviewRequired(Error):
    def __init__(self, result):
        super().__init__("Ametller requiere revisión explícita de la dirección.")
        self.result = result


def delivery_day(value):
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, "%d/%m/%Y").date().isoformat()
    except ValueError:
        try:
            date = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if date.tzinfo:
                date = date.astimezone(ZoneInfo("Europe/Madrid"))
            return date.date().isoformat()
        except ValueError:
            return None


def web_total_cents(value):
    """Formato EUR es/ca del checkout; no adivinar otro formato de moneda."""
    from .catalog import cents, decimal
    if not isinstance(value, str):
        return None
    value = re.sub(r"\s", "", value)
    if not re.fullmatch(r"(?:\d{1,3}(?:\.\d{3})+|\d+),\d{2}€", value):
        return None
    return cents(decimal(value[:-1].replace(".", "").replace(",", ".")))


class CheckoutPage(HTMLParser):
    def __init__(self):
        super().__init__()
        self.delivery_url = self.pickup_url = None
        self.urls = {}
        self.fields = {}
        self.contact_fields = {}
        self.shipping_options = {}
        self.payment_form_present = False
        self.shipping_form = False
        self.contact_form = False
        self.select = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get("data-time-slots-get-url-delivery"):
            self.delivery_url = attrs["data-time-slots-get-url-delivery"]
        if attrs.get("data-time-slots-get-url-store"):
            self.pickup_url = attrs["data-time-slots-get-url-store"]
        for key in ("data-checkout-get-url", "data-select-shipping-method-url", "data-change-store-url", "data-save-time-slot-url",
                    "data-change-postal-code-url", "data-validate-street-number-url"):
            if attrs.get(key):
                self.urls[key] = attrs[key]
        if tag == "form":
            self.shipping_form = attrs.get("id") == "dwfrm_shipping"
            self.contact_form = "contact-form" in attrs.get("class", "").split()
            if self.shipping_form:
                self.urls["submit-shipping"] = attrs.get("action")
            if self.contact_form:
                self.urls["submit-contact"] = attrs.get("action")
            if attrs.get("id") == "dwfrm_billing":
                self.payment_form_present = True
        if self.shipping_form and tag == "input" and attrs.get("name"):
            if attrs.get("type") not in ("radio", "checkbox") or "checked" in attrs:
                self.fields[attrs["name"]] = attrs.get("value", "")
        if self.contact_form and tag == "input" and attrs.get("name") in (
                "dwfrm_contact_contactFirstName", "dwfrm_contact_contactLastName", "contactEmail", "csrf_token"):
            self.contact_fields[attrs["name"]] = attrs.get("value", "")
        if self.shipping_form and tag == "select":
            self.select = attrs.get("name")
        if self.select and tag == "option":
            value = attrs.get("value", "")
            self.shipping_options.setdefault(self.select, []).append(value)
            if "selected" in attrs:
                self.fields[self.select] = value

    def handle_endtag(self, tag):
        if tag == "form":
            self.shipping_form = False
            self.contact_form = False
        if tag == "select":
            self.select = None


def controller_url(value, expected):
    parsed = urlparse(urljoin(ORIGIN, value or ""))
    if (parsed.scheme != "https" or parsed.hostname != "www.ametllerorigen.com" or parsed.port not in (None, 443)
            or parsed.username or parsed.password or not parsed.path.startswith("/on/demandware.store/Sites-ametller-Site/")
            or parsed.path.rsplit("/", 1)[-1] != expected):
        raise Error("La web devolvió un servicio de entrega inesperado.")
    return parsed._replace(fragment="").geturl()


class WebCheckout:
    """Una cesta y envío, identidad verificada y escrituras sin reintentos."""

    def __init__(self, client):
        self.client = client
        self.storage = client.storage
        self.remote = RemoteCart(client, self.storage)
        self.page = self.model = None
        self.jar = CookieJar()
        self.opener = build_opener(NoRedirect, HTTPCookieProcessor(self.jar))
        self.customer = client.customer()
        self.original = dict(client.session)
        for name, value in self.original.get("cookies", {}).items():
            self.jar.set_cookie(Cookie(0, name, value, None, False, "www.ametllerorigen.com", False, False,
                                       "/", True, True, None, True, None, None, {}, False))
        if not any(cookie.name == "dwsid" for cookie in self.jar):
            raise Error("Falta la sesión web. Ejecuta ametller login para conectar cuenta y checkout.")

    def persist_cookies(self):
        cookies = {item.name: item.value for item in self.jar if item.domain.lstrip(".") in
                   ("www.ametllerorigen.com", "ametllerorigen.com") and
                   re.fullmatch(r"dwsid|dwsecuretoken[\w-]*|dwanonymous[\w-]*|usid_[\w-]+|cc-(?:at|nx|cid)[\w-]*", item.name)}
        if "cc-nx-g_" + self.client.config["siteId"] in cookies:
            raise Error("La sesión web ha pasado a invitado. Conecta de nuevo con ametller login.")
        candidate = {**self.client.session, "cookies": cookies}
        refresh = cookies.get("cc-nx_" + self.client.config["siteId"])
        token = cookies.get("cc-at_" + self.client.config["siteId"])
        if refresh and unquote(refresh) != candidate.get("refresh_token"):
            if not token:
                raise Error("La web renovó la sesión sin devolver su identidad; vuelve a conectar.")
            identity = token_identity(unquote(token))
            if identity["guest"] or identity["customer_id"] != self.original["customer_id"]:
                raise Error("La web devolvió otra cuenta; conexión detenida.")
            candidate.update({**identity, "access_token": unquote(token), "refresh_token": unquote(refresh)})
            probe = AccountClient(lang=self.client.lang, storage=self.storage, account=candidate)
            probe.whoami()
            candidate = probe.session
        with self.storage.lock("account"):
            stored = self.storage.read("account.json")
            if stored and any(stored.get(key) != self.client.session.get(key) for key in ("customer_id", "access_token", "refresh_token")):
                raise Error("La sesión cambió en otro proceso; vuelve a conectar antes de usar entrega.")
            self.storage.write("account.json", candidate)
        self.client.session = candidate

    def request(self, url, method="GET", data=None, allow_session_redirect=True):
        # La tienda usa GET para algunas escrituras: no repetir ninguna petición.
        allow_web_request(url, method)
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname != "www.ametllerorigen.com" or parsed.port not in (None, 443) or parsed.username:
            raise Error("Destino de checkout inesperado.")
        headers = {"User-Agent": USER_AGENT, "X-Requested-With": "XMLHttpRequest"}
        body = None
        if data is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            body = urlencode(data).encode()
        for redirect_count in range(4):
            try:
                with self.opener.open(Request(url, data=body, method=method, headers=headers), timeout=25) as response:
                    value = response.read()
            except HTTPError as error:
                # Hybrid Auth puede renovar y redirigir al mismo recurso. Guardar
                # los tokens rotados incluso si el checkout aún no puede abrirse.
                next_url = urljoin(url, error.headers.get("Location", ""))
                status = error.code
                error.close()
                self.persist_cookies()
                next_path = urlparse(next_url)
                if (allow_session_redirect and method == "GET" and status in (301, 302, 303) and redirect_count < 3
                        and next_path.scheme == "https" and next_path.hostname == "www.ametllerorigen.com"
                        and next_path.netloc == parsed.netloc and next_path.path == parsed.path):
                    url = next_url
                    continue
                if status in (301, 302, 303, 401):
                    raise Error("La web no permite continuar: conecta con login y comprueba el mínimo de cesta.") from None
                raise HTTPFailure(status) from None
            except (URLError, TimeoutError, OSError):
                raise Error("No se recibió el resultado del checkout. No repitas cambios sin leer la cesta.") from None
            self.persist_cookies()
            return value

    def json_request(self, url, method="GET", data=None, allow_session_redirect=True):
        try:
            return json.loads(self.request(url, method, data, allow_session_redirect))
        except (ValueError, TypeError):
            raise Error("Respuesta inesperada del checkout.") from None

    def verify_model(self, model):
        customer = model.get("customer") or {}
        email = self.customer.get("email")
        if not email or customer.get("registeredUser") is not True or (customer.get("profile") or {}).get("email") != email:
            raise Error("El checkout no corresponde a la cuenta conectada. Ejecuta ametller login.")
        if len((model.get("order") or {}).get("shipping", [])) != 1:
            raise Error("El checkout requiere un único envío para configurar entrega desde esta versión.")
        self.model = model
        return model

    def read_model(self):
        url = controller_url(self.page.urls.get("data-checkout-get-url"), "CheckoutServices-Get")
        return self.verify_model(self.json_request(url))

    def prepare(self):
        self.remote.pending()
        basket = self.remote.get()
        if not basket or not basket.get("productItems"):
            raise Error("Añade productos a la cesta de cuenta antes de configurar entrega.")
        self.remote.shipment(basket)
        self.page = CheckoutPage()
        self.page.feed(self.request(ORIGIN + "/" + self.client.lang + "/checkout").decode())
        self.read_model()
        return self

    def reload_page(self):
        self.page = CheckoutPage()
        self.page.feed(self.request(ORIGIN + "/" + self.client.lang + "/checkout").decode())
        self.read_model()

    def home(self, postcode):
        if not re.fullmatch(r"\d{5}", postcode):
            raise Error("El código postal debe tener cinco dígitos.")
        shipment = self.model["order"]["shipping"][0]
        methods = [method for method in shipment.get("applicableShippingMethods", []) if method.get("storePickupEnabled") is False]
        if len(methods) != 1:
            raise Error("No hay un único método de domicilio disponible.")
        method_id = methods[0]["ID"]
        self.mutate("data-select-shipping-method-url", "CheckoutShippingServices-SelectShippingMethod", "home-method",
                    data={"shipmentUUID": shipment["UUID"], "methodID": method_id, "isGift": "false", "giftMessage": ""},
                    check=lambda model, basket: model["order"]["shipping"][0]["selectedShippingMethod"]["ID"] == method_id)
        _, basket = self.mutate("data-change-postal-code-url", "TimeSlot-ChangeCodePostal", "home-postcode",
                                method="GET", data={"postalCode": postcode})
        self.reload_page()
        if parse_qs(urlparse(self.page.delivery_url or "").query).get("postalCode") != [postcode]:
            self.storage.write("remote-pending.json", {"customer_id": self.client.session["customer_id"],
                               "basket_id": basket["basketId"], "operation": "home-postcode"})
            raise Error("La web no confirmó el código postal; revisa remote-cart get.")
        return {"scope": "account", "home_postcode_confirmed": True, "postal_code": postcode,
                "payment_submitted": False, "order_submitted": False,
                "next_step": "Consulta franjas, selecciona una y completa checkout details."}

    def contact(self, details):
        contact = details["contact"]
        if contact["email"] != self.customer["email"]:
            raise Error("El email de contacto debe coincidir con la cuenta conectada.")
        fields = {**self.page.contact_fields,
                  "dwfrm_contact_contactFirstName": contact["first_name"],
                  "dwfrm_contact_contactLastName": contact["last_name"], "contactEmail": contact["email"]}
        if not fields.get("csrf_token"):
            raise Error("El checkout no devolvió el formulario de contacto vigente.")
        self.mutate("submit-contact", "CheckoutShippingServices-SubmitContact", "checkout-contact", data=fields,
                    check=lambda model, basket: all((model["customer"].get("profile") or {}).get(key) == contact[value]
                                                    for key, value in (("firstName", "first_name"), ("lastName", "last_name"))))
        # Obtener el CSRF y los campos de envío vigentes tras enviar contacto.
        self.reload_page()

    def shipping_details(self, details, review_address=False):
        address = details["shipping"]
        shipment = self.model["order"]["shipping"][0]
        if shipment.get("selectedShippingMethod", {}).get("storePickupEnabled") is not False:
            raise Error("Selecciona domicilio con delivery home antes de enviar la dirección.")
        prefix = "dwfrm_shipping_shippingAddress_addressFields_"
        mapping = {"firstName": "first_name", "lastName": "last_name", "address1": "address1", "streetNumber": "street_number",
                   "floor": "floor", "postalCode": "postal_code", "city": "city", "states_stateCode": "state_code",
                   "country": "country", "nameReceiver": "receiver", "phone": "phone"}
        for field, value in (("states_stateCode", "state_code"), ("country", "country")):
            if address[value] not in self.page.shipping_options.get(prefix + field, []):
                raise Error("Provincia o país no admitido por el formulario de la tienda.")
        if parse_qs(urlparse(self.page.delivery_url or "").query).get("postalCode") != [address["postal_code"]]:
            raise Error("Configura primero delivery home con el código postal de la dirección.")
        fields = {key: value for key, value in self.page.fields.items()
                  if key.startswith("dwfrm_shipping_") or key in ("csrf_token", "shipmentUUID", "originalShipmentUUID",
                                                                "timeSlotID", "idcustomObject", "address_shipping_modify")}
        if not fields.get("csrf_token") or not fields.get("timeSlotID"):
            raise Error("Falta el formulario vigente o la franja. Selecciona una con delivery select-slot.")
        fields.update({prefix + key: address[value] for key, value in mapping.items()})
        # El servidor valida y puede proponer una corrección: nunca fingir geocodificación.
        fields.update({prefix + "addressValidated": "false", prefix + "latitude": "", prefix + "longitude": "",
                       "shipmentUUID": shipment["UUID"], "shippingAddressName": address["address_name"]})
        check = lambda model, basket: (model["order"].get("steps", {}).get("shipping", {}).get("iscompleted") is True
                         and all((model["order"]["shipping"][0].get("shippingAddress") or {}).get(key) == address[value]
                                 for key, value in (("postalCode", "postal_code"), ("city", "city"), ("phone", "phone"))))
        reviewed = False
        try:
            self.mutate("submit-shipping", "CheckoutShippingServices-SubmitShipping", "checkout-home-address", data=fields, check=check)
        except AddressReviewRequired as error:
            if not review_address:
                raise Error("Ametller pide revisar la dirección. Lee remote-cart get; luego usa --review-address para verla y elegirla en un formulario privado.") from None
            from .details import collect_address_review, validate_details
            pending = self.storage.read("remote-pending.json")
            before = self.remote.read_id(pending["basket_id"])
            choice = collect_address_review(error.result)
            if fingerprint(self.remote.get()) != fingerprint(before):
                raise Error("La cesta cambió durante la revisión de dirección; se conserva el bloqueo y no se envía la elección.")
            if choice == "suggested":
                address = dict(address)
                components = error.result["suggestedAddress"]["components"]
                for field, component in (("address1", "route"), ("street_number", "street_number"),
                                         ("postal_code", "postal_code"), ("city", "locality")):
                    if components.get(component):
                        address[field] = components[component]
                validate_details({"contact": details["contact"], "shipping": address})
                if address["postal_code"] != details["shipping"]["postal_code"]:
                    raise Error("La propuesta cambia el código postal: actualiza el borrador y elige una nueva franja antes de enviarla.")
            # Confirmar el estado leído antes de una nueva escritura decidida por el usuario.
            self.remote.confirmed_get()
            self.reload_page()
            fields.update({prefix + key: address[value] for key, value in mapping.items()})
            fields["csrf_token"] = self.page.fields.get("csrf_token", "")
            fields[prefix + "addressValidated"] = "confirmed"
            self.mutate("submit-shipping", "CheckoutShippingServices-SubmitShipping", "checkout-home-address-confirmed", data=fields, check=check)
            reviewed = True
        return {"scope": "account", "contact_confirmed": True, "shipping_confirmed": True,
                "address_reviewed_by_user": reviewed,
                "payment_submitted": False, "order_submitted": False,
                "notice": "Datos confirmados por la tienda. Pago y pedido permanecen bloqueados."}

    def test(self, maximum=None):
        """Leer preparación real, sin enviar formularios de pago ni aceptar condiciones."""
        from .catalog import cents, decimal
        basket = self.remote.get()
        if not basket:
            raise Error("La cesta ya no existe.")
        state = summary(basket)
        total = state["order_total_cents"]
        if maximum is not None and (total is None or total > cents(decimal(maximum))):
            raise Error("El total de la cesta es desconocido o supera --max.")
        order = self.model["order"]
        web_total = web_total_cents(order.get("totals", {}).get("grandTotal"))
        if maximum is not None and (web_total is None or web_total > cents(decimal(maximum))):
            raise Error("El total del checkout web es desconocido o supera --max.")
        shipment = order["shipping"][0]
        billing = (order.get("billing", {}).get("billingAddress") or {}).get("address") or {}
        profile = self.model["customer"].get("profile") or {}
        pickup = (shipment.get("selectedShippingMethod") or {}).get("storePickupEnabled")
        prefix = "c_storeDelivery" if pickup is True else "c_homeDelivery"
        checks = {"same_registered_account": True, "products_present": bool(basket.get("productItems")),
                  "contact_present": all(profile.get(key) for key in ("firstName", "lastName", "email")),
                  "address_present": bool(shipment.get("shippingAddress")),
                  "billing_address_present": all(billing.get(key) for key in ("firstName", "lastName", "address1", "postalCode", "city", "phone")),
                  "delivery_slot_selected": any(item.get(prefix + "SlotID") and item.get(prefix + "Date") for item in basket.get("shipments", [])),
                  "shipping_accepted_by_store": ((order.get("steps") or {}).get("shipping") or {}).get("iscompleted") is True,
                  "payment_form_available": self.page.payment_form_present}
        return {"scope": "account", "mode": "test", "checks": {key: bool(value) for key, value in checks.items()},
                "prepayment_ready": all(checks.values()),
                "web_total_cents": web_total,
                "currency": state["currency"], "basket_total_cents": total, "web_totals": {
                    key: order.get("totals", {}).get(key) for key in ("subTotal", "totalShippingCost", "grandTotal")},
                "payments_blocked": True, "orders_blocked": True, "payment_submitted": False, "order_submitted": False,
                "payment_processing_verified": False, "delivery_slot_reserved": None,
                "notice": "Validación hasta antes del pago. Sin cargo ni pedido; no acredita procesamiento de pago, 3DS ni reserva definitiva."}

    def mutate(self, key, controller, operation, method="POST", data=None, check=None):
        self.remote.pending()
        basket = self.remote.get()
        if not basket:
            raise Error("La cesta de cuenta ya no existe.")
        url = controller_url(self.page.urls.get(key), controller)
        if method == "GET" and data:
            url += ("&" if "?" in url else "?") + urlencode(data)
            data = None
        if fingerprint(self.remote.read_id(basket["basketId"])) != fingerprint(basket):
            raise Error("La cesta cambió mientras se preparaba la entrega. Vuelve a leerla.")
        self.storage.write("remote-pending.json", {"customer_id": self.client.session["customer_id"],
                                                  "basket_id": basket["basketId"], "operation": operation})
        issue = "respuesta o lectura sin confirmar"
        try:
            result = self.json_request(url, method, data, allow_session_redirect=False)
            if result.get("showAddressModal"):
                raise AddressReviewRequired(result)
            if (result.get("success") is False or result.get("error") is True or result.get("inventoryError")
                    or result.get("showAddressModal") or result.get("slotError") or result.get("sushiError")):
                issue = ("corrección de dirección pendiente" if result.get("showAddressModal") else
                         "inventario rechazado" if result.get("inventoryError") else
                         "franja rechazada" if result.get("slotError") else "formulario rechazado")
                raise Error("La tienda rechazó la configuración de entrega.")
            model = self.read_model()
            updated = self.remote.read_id(basket["basketId"])
            if check is not None and not check(model, updated):
                issue = "lectura no coincide con los datos solicitados"
                raise Error("El estado leído no confirma la entrega solicitada.")
        except AddressReviewRequired:
            raise
        except Error:
            raise Error("La entrega no quedó confirmada (" + operation + ": " + issue +
                        "). Ejecuta remote-cart get, revisa el estado y no repitas automáticamente.") from None
        self.storage.delete("remote-pending.json")
        return result, updated

    def pickup(self, store_id):
        store = get_store(self.client, store_id)
        if store["pickup_standard"] is not True and store["pickup_express"] is not True:
            raise Error("La tienda no declara servicio de recogida.")
        shipment = self.model["order"]["shipping"][0]
        methods = [method for method in shipment.get("applicableShippingMethods", []) if method.get("storePickupEnabled") is True]
        if len(methods) != 1:
            raise Error("La tienda no ofrece un único método de recogida aplicable.")
        method_id = methods[0]["ID"]
        self.mutate("data-select-shipping-method-url", "CheckoutShippingServices-SelectShippingMethod", "pickup-method",
                    data={"shipmentUUID": shipment["UUID"], "methodID": method_id, "isGift": "false", "giftMessage": ""},
                    check=lambda model, basket: model["order"]["shipping"][0]["selectedShippingMethod"]["ID"] == method_id)
        _, basket = self.mutate("data-change-store-url", "TimeSlot-ChangeStore", "pickup-store", method="GET", data={"storeID": store_id})
        # El controlador actualiza la selección que devuelve la siguiente página.
        self.page = CheckoutPage()
        self.page.feed(self.request(ORIGIN + "/" + self.client.lang + "/checkout").decode())
        if self.page.fields.get("selectedStore") != store_id:
            self.storage.write("remote-pending.json", {"customer_id": self.client.session["customer_id"], "basket_id": basket["basketId"], "operation": "pickup-store"})
            raise Error("La web no confirmó la tienda elegida. Revisa remote-cart get antes de otro cambio.")
        return {**summary(basket), "pickup_store": store, "pickup_store_confirmed": True,
                "notice": "Tienda y modalidad elegidas. Falta seleccionar y confirmar una franja."}

    def select_slot(self, slot_id, date):
        shipment = self.model["order"]["shipping"][0]
        pickup = shipment.get("selectedShippingMethod", {}).get("storePickupEnabled") is True
        url = slots_url(self.page.pickup_url if pickup else self.page.delivery_url)
        slots = flatten_slots(self.json_request(url))
        slot = next((slot for slot in slots if str(slot["id"]) == slot_id and slot["date"] == date), None)
        if not slot:
            raise Error("La franja ya no está disponible para esta cesta, tienda y fecha. Vuelve a consultar slots.")
        prefix = "c_storeDelivery" if pickup else "c_homeDelivery"
        _, basket = self.mutate("data-save-time-slot-url", "TimeSlot-SaveTimeSlot", "delivery-slot",
                                data={"slotId": slot_id, "deliveryDate": date},
                                check=lambda model, basket: any(str(item.get(prefix + "SlotID")) == slot_id and
                                                               delivery_day(item.get(prefix + "Date")) == delivery_day(date)
                                                               for item in basket.get("shipments", [])))
        return {**summary(basket), "selected_slot": slot, "delivery_selection_confirmed": True,
                "delivery_slot_reserved": None, "notice": "Franja seleccionada y confirmada en la cesta. La reserva definitiva depende de Ametller al completar el pedido."}


def flatten_slots(result):
    if result.get("success") is not True or not isinstance(result.get("data"), list):
        raise Error("La tienda no confirmó disponibilidad de franjas para esta consulta.")
    return [{"id": slot.get("id"), "date": slot.get("deliveryDate"), "time": slot.get("timeSlot"),
             "price": slot.get("price"), "type": slot.get("type"), "origin": slot.get("origin"),
             "day_label": day.get("day"), "section": section.get("title")}
            for day in result["data"] for section in day.get("sections", []) for slot in section.get("slots", [])]


def slots_url(value, postcode=None, store=None):
    if not value:
        raise Error("La web no devolvió el servicio de franjas; revisa el checkout de Ametller.")
    parsed = urlparse(controller_url(value, "TimeSlot-GetSlots"))
    query = parse_qs(parsed.query)
    if postcode is not None:
        if not re.fullmatch(r"\d{5}", postcode):
            raise Error("El código postal debe tener cinco dígitos.")
        query["postalCode"] = [postcode]
    if store is not None:
        if not re.fullmatch(r"[\w-]{1,100}", store):
            raise Error("ID de tienda inválido.")
        query["storePickupEnabled"] = ["true"]
        query["storeIDPickup"] = [store]
    return urlunparse(parsed._replace(query=urlencode(query, doseq=True), fragment=""))


def delivery_slots(client, postcode=None, store=None, refresh=False):
    if not refresh:
        raise Error("Ametller puede actualizar la propuesta de entrega de la cesta al calcular franjas. Usa --refresh para autorizar ese cálculo.")
    with client.storage.lock("remote-cart"), client.storage.lock("web-session"):
        web = WebCheckout(client).prepare()
        pickup = bool(store) or web.model["order"]["shipping"][0].get("selectedShippingMethod", {}).get("storePickupEnabled") is True
        if store and postcode is None:
            postcode = get_store(client, store)["postal_code"]
        url = slots_url(web.page.pickup_url if pickup else web.page.delivery_url, postcode, store)
        slots = flatten_slots(web.json_request(url))
    query = parse_qs(urlparse(url).query)
    return {"scope": "account", "postal_code": query.get("postalCode", [None])[0],
            "pickup_store": query.get("storeIDPickup", [None])[0] if pickup else None, "slots": slots, "total": len(slots),
            "delivery_slot_reserved": None, "order_submitted": False,
            "store_delivery_defaults_may_change": True,
            "notice": "Franjas de la web. Ametller puede actualizar la propuesta de entrega de la cesta; no se ha confirmado una reserva ni enviado un pedido.",
            "fetched_at": timestamp()}
