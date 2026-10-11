"""Esta versión prepara el checkout; nunca envía pagos ni crea pedidos."""

from urllib.parse import unquote, urlparse

from .storage import Error

CONTROLLERS = {
    "CheckoutServices-Get": "GET",
    "TimeSlot-GetSlots": "GET",
    "TimeSlot-ChangeStore": "GET",
    "TimeSlot-ChangeCodePostal": "GET",
    "TimeSlot-SaveTimeSlot": "POST",
    "CheckoutShippingServices-SelectShippingMethod": "POST",
    "CheckoutShippingServices-ValidateStreetNumber": "GET",
    "CheckoutShippingServices-SubmitContact": "POST",
    "CheckoutShippingServices-SubmitShipping": "POST",
}


def allow_web_request(url, method):
    path = unquote(urlparse(url).path)
    if path in ("/es/checkout", "/ca/checkout") and method == "GET":
        return
    action = path.rsplit("/", 1)[-1]
    if (path.startswith("/on/demandware.store/Sites-ametller-Site/")
            and CONTROLLERS.get(action) == method):
        return
    raise Error("Modo de prueba: servicio bloqueado. Esta versión no envía pagos ni pedidos.")


def allow_account_request(service, resource, method):
    path = unquote(resource).lower()
    if method.upper() != "GET" and any(word in service.lower() or word in path for word in ("order", "payment")):
        raise Error("Modo de prueba: la escritura de pagos y pedidos está bloqueada.")
