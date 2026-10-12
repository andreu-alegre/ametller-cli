import argparse
import json
import os
from pathlib import Path
import sys

from . import __version__
from .account import AccountClient, import_har, login
from .browserlogin import browser_login
from .catalog import decimal, normalize, parse_basket, price_basket, timestamp, validate_id
from .client import Client, ORIGIN
from .storage import Error, Storage
from .remote import RemoteCart, postal_code, summary
from .webcheckout import delivery_slots, WebCheckout
from .stores import find_stores, get_store
from .details import collect_details, read_details
from .promotions import promotion_result
from .club import MobileClub, SESSION_FILE as CLUB_SESSION_FILE, interactive_login


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise Error(message)

    def parse_args(self, args=None, namespace=None):
        result = super().parse_args(args, namespace)
        for key, value in {"json": False, "raw": False, "lang": "es", "state_dir": None, "max_eur": None, "account": False}.items():
            if not hasattr(result, key):
                setattr(result, key, value)
        return result


def parser():
    common = Parser(add_help=False)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Salida estructurada")
    common.add_argument("--raw", action="store_true", default=argparse.SUPPRESS, help="Datos de catálogo sin normalizar")
    common.add_argument("--lang", choices=("es", "ca"), default=argparse.SUPPRESS, help="Idioma del catálogo")
    common.add_argument("--state-dir", default=argparse.SUPPRESS, help="Directorio de estado (también AMETLLER_HOME)")
    common.add_argument("--max", dest="max_eur", default=argparse.SUPPRESS, help="Presupuesto máximo de productos en EUR")
    common.add_argument("--account", action="store_true", default=argparse.SUPPRESS, help="Consultar catálogo y presupuestar con la cuenta conectada")
    root = Parser(prog="ametller", description="Ametller Origen: catálogo, cuenta y cestas; CLI no oficial.", parents=[common])
    root.add_argument("--version", action="version", version=__version__)
    commands = root.add_subparsers(dest="command", required=True)

    def command(name, help_text, parent=commands):
        return parent.add_parser(name, help=help_text, parents=[common])

    search = command("search", "Buscar productos sin cuenta")
    search.add_argument("query", nargs="+")
    search.add_argument("--limit", type=int, default=10)
    search.add_argument("--offset", type=int, default=0)
    promotions = command("promotions", "Ver promociones, Precio Club y lotes ahorro publicados")
    promotions.add_argument("--query", help="Buscar dentro de las promociones")
    promotions.add_argument("--club", action="store_true", help="Sólo productos con una etiqueta explícita Club")
    promotions.add_argument("--lots", action="store_true", help="Consultar la colección Lotes Ahorro")
    promotions.add_argument("--all", dest="all_results", action="store_true", help="Leer todas las páginas (máximo 5000 productos)")
    promotions.add_argument("--limit", type=int, default=20)
    promotions.add_argument("--offset", type=int, default=0)
    coupons = command("coupons", "Consultar cupones personales o preparar una activación; --apply escribe")
    coupons.add_argument("action", nargs="?", choices=("list", "activate"), default="list")
    coupons.add_argument("coupon_id", nargs="?", help="Cupón concreto para activate")
    coupons.add_argument("--apply", action="store_true", help="Activar el cupón indicado después de revisar su vista previa")
    coupons.add_argument("--id", help="Seleccionar un cupón de la lista de esta cuenta")
    coupons.add_argument("--status", choices=("active", "inactive"), help="Estado exacto devuelto por la app")
    club = command("club", "Conectar o consultar la sesión del Club móvil, independiente del login web")
    club_commands = club.add_subparsers(dest="action", required=True)
    mobile_import = command("import-capture", "Importar una consulta privada de cupones de tu app", club_commands)
    mobile_import.add_argument("--file", required=True)
    mobile_login = command("login", "Conectar el Club con contraseña oculta; sin proxy ni HAR", club_commands)
    mobile_login.add_argument("--form", action="store_true", help="Formulario local aislado en lugar del terminal")
    mobile_login.add_argument("--timeout", type=int, default=900)
    command("status", "Verificar la sesión del Club leyendo los cupones", club_commands)
    command("logout", "Eliminar sólo la sesión móvil local; no cierra la app", club_commands)
    product = command("product", "Ficha, precio, ingredientes y datos disponibles")
    product.add_argument("id")
    categories = command("categories", "Árbol de categorías o productos de una categoría")
    categories.add_argument("--id")
    categories.add_argument("--limit", type=int, default=20)
    categories.add_argument("--offset", type=int, default=0)
    batch = command("batch", "Buscar una lista de términos (una consulta por término)")
    batch.add_argument("-f", "--file", required=True, help="Un término por línea; - para stdin")
    total = command("total", "Presupuestar un archivo <id> <cantidad>")
    total.add_argument("-f", "--file", required=True)
    cart = command("cart", "Gestionar una cesta LOCAL")
    cart_commands = cart.add_subparsers(dest="action", required=True)
    command("get", "Leer y actualizar los precios", cart_commands)
    command("clear", "Vaciar la cesta local", cart_commands)
    for name in ("add", "set"):
        change = command(name, "Añadir unidades" if name == "add" else "Fijar cantidad (0 elimina)", cart_commands)
        change.add_argument("id")
        change.add_argument("quantity", nargs="?", default="1")
    remove = command("remove", "Eliminar un producto", cart_commands)
    remove.add_argument("id")
    many = command("set-many", "Aplicar un archivo <id> <cantidad> de forma atómica", cart_commands)
    many.add_argument("-f", "--file", required=True)
    checkout = command("checkout", "Preparar una lista para completar la compra en la web")
    checkout_commands = checkout.add_subparsers(dest="action", required=True)
    command("prepare", "Revalidar cesta y devolver enlaces; no sincroniza ni compra", checkout_commands)
    remote_checkout = command("account", "Leer la cesta de cuenta y preparar la continuación en la web", checkout_commands)
    remote_checkout.add_argument("--basket-id")
    rehearsal = command("test", "Validar el checkout real hasta antes del pago; pagos y pedidos bloqueados", checkout_commands)
    rehearsal.add_argument("--refresh", action="store_true", help="Autorizar cálculo web de entrega; puede cambiar su propuesta por defecto")
    details = command("details", "Completar contacto y domicilio mediante un borrador privado", checkout_commands)
    input_details = details.add_mutually_exclusive_group(required=True)
    input_details.add_argument("--form", action="store_true", help="Abrir formulario local; guarda borrador sin enviarlo a la tienda")
    input_details.add_argument("--file", help="JSON privado fuera del repositorio (permisos 600)")
    details.add_argument("--apply", action="store_true", help="Enviar contacto y dirección a la tienda; nunca pago ni pedido")
    details.add_argument("--timeout", type=int, default=900)
    details.add_argument("--review-address", action="store_true", help="Si Ametller pide corregir la dirección, mostrarla y esperar tu elección privada")
    connect = command("login", "Conectar en un navegador, sin exportar archivos")
    connect.add_argument("--email")
    connect.add_argument("--terminal", action="store_true", help="Acceso SLAS con contraseña oculta en terminal; pendiente de validar")
    connect.add_argument("--browser", choices=("chromium", "chrome", "msedge"), default="chromium")
    connect.add_argument("--timeout", type=int, default=900)
    imported = command("import-har", "Importar una sesión propia exportada desde el navegador")
    imported.add_argument("-f", "--file", required=True)
    command("whoami", "Comprobar la cuenta conectada con el servidor")
    command("logout", "Eliminar la sesión local de cuenta; no cierra el navegador")
    command("addresses", "Leer direcciones guardadas de la cuenta")
    orders = command("orders", "Leer pedidos anteriores de la cuenta")
    orders.add_argument("--limit", type=int, default=10)
    orders.add_argument("--offset", type=int, default=0)
    stores = command("stores", "Buscar tiendas por código postal o consultar una tienda")
    location = stores.add_mutually_exclusive_group(required=True)
    location.add_argument("--postcode")
    location.add_argument("--id")
    stores.add_argument("--limit", type=int, default=20)
    stores.add_argument("--distance", type=int, default=20, help="Radio de búsqueda en km")
    stores.add_argument("--pickup-only", action="store_true")
    remote = command("remote-cart", "Leer y modificar la cesta REAL de la cuenta")
    remote_commands = remote.add_subparsers(dest="action", required=True)
    for action in ("list", "get", "add", "set", "remove", "sync", "clear"):
        item = command(action, "Sincronizar cesta local (vista previa; --apply escribe)" if action == "sync" else action, remote_commands)
        item.add_argument("--basket-id")
        if action in ("add", "set", "remove"):
            item.add_argument("id")
        if action in ("add", "set"):
            item.add_argument("quantity", nargs="?", default="1")
        if action in ("sync", "clear"):
            item.add_argument("--apply", action="store_true")
    delivery = command("delivery", "Código postal, métodos y dirección de envío de la cesta")
    delivery_commands = delivery.add_subparsers(dest="action", required=True)
    postcode = command("postcode", "Consultar cobertura declarada por la tienda", delivery_commands)
    postcode.add_argument("code")
    slots = command("slots", "Consultar franjas reales en el checkout web (requiere cesta y sesión de navegador)", delivery_commands)
    slots.add_argument("--postcode")
    slots.add_argument("--pickup-store")
    slots.add_argument("--refresh", action="store_true", help="Calcular franjas; la web puede actualizar su propuesta de entrega en la cesta")
    pickup = command("pickup", "Elegir tienda de recogida (vista previa; --apply escribe)", delivery_commands)
    pickup.add_argument("store_id")
    pickup.add_argument("--apply", action="store_true")
    home = command("home", "Elegir domicilio y código postal (vista previa; --apply escribe)", delivery_commands)
    home.add_argument("--postcode", required=True)
    home.add_argument("--apply", action="store_true")
    selected_slot = command("select-slot", "Elegir una franja disponible (vista previa; --apply escribe)", delivery_commands)
    selected_slot.add_argument("slot_id")
    selected_slot.add_argument("--date", required=True, help="Fecha exacta devuelta por delivery slots")
    selected_slot.add_argument("--apply", action="store_true")
    for action in ("methods", "address", "method", "status"):
        shipping = command(action, "Leer métodos" if action == "methods" else "Aplicar a la cesta", delivery_commands)
        shipping.add_argument("--basket-id")
        shipping.add_argument("--shipment-id")
        if action not in ("methods", "status"):
            shipping.add_argument("id")
    command("doctor", "Comprobar conexión, sesión de invitado y catálogo")
    command("capabilities", "Describir funciones y límites para agentes, sin conexión de red")
    return root


def read_file(path):
    if path == "-":
        return sys.stdin.read()
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError:
        raise Error(f"No se pudo leer el archivo {path}.") from None


def search_result(client, args, query=None, category=None):
    if not 1 <= args.limit <= 200 or args.offset < 0:
        raise Error("--limit debe estar entre 1 y 200 y --offset no puede ser negativo.")
    raw = client.search(query=query, category=category, limit=args.limit, offset=args.offset)
    if args.raw:
        return raw
    return {
        "query": query, "category_id": category, "total": raw.get("total"),
        "offset": raw.get("offset", args.offset), "limit": args.limit,
        "products": [normalize(hit) for hit in raw.get("hits", [])],
        "fetched_at": timestamp(), "source": ORIGIN,
    }


def run(args, client, storage):
    if args.command == "capabilities":
        return {"schema_version": 1, "version": __version__, "unofficial": True,
                "interfaces": ["cli", "mcp_stdio_optional"],
                "output": {"success": "stdout_json", "error": "stderr_json", "exit_codes": {"success": 0, "error": 1, "interrupted": 130}},
                "catalog": ["search", "product", "categories", "promotions", "stores"],
                "account": ["browser_login", "whoami", "addresses", "orders", "remote_cart", "delivery"],
                "cart_scopes": ["local", "account"], "account_session_storage": "local_private",
                "human_login_required": True, "personal_coupons_supported": True,
                "personal_coupon_activation_supported": True, "mobile_club_session_required": True,
                "mobile_club_login_supported": True, "mobile_club_automatic_refresh_supported": False,
                "checkout_test_supported": True, "home_address_fully_verified": False,
                "payments_blocked": True, "orders_blocked": True,
                "notice": "Las promociones del catálogo y los cupones personales se consultan por separado. La lectura no confirma descuentos de cesta. La selección de franja no certifica una reserva."}
    if args.command == "coupons":
        if args.account:
            raise Error("Los cupones usan la sesión móvil del Club, no --account. Conecta con club import-capture.")
        if args.action == "activate":
            if not args.coupon_id or args.id or args.status or args.raw:
                raise Error("Usa coupons activate <id> [--apply], sin --id, --status ni --raw.")
            return MobileClub(storage, args.lang).activate(args.coupon_id, args.apply)
        if args.coupon_id or args.apply:
            raise Error("--apply y el ID posicional sólo se usan con coupons activate <id>.")
        return MobileClub(storage, args.lang).coupons(args.id, args.status, args.raw)
    if args.command == "club":
        mobile = MobileClub(storage, args.lang)
        if args.action == "login":
            return interactive_login(storage, args.lang, args.form, args.timeout)
        if args.action == "import-capture":
            return mobile.import_capture(args.file)
        if args.action == "status":
            return mobile.status()
        with storage.lock("club"):
            storage.delete(CLUB_SESSION_FILE)
        return {"scope": "club_mobile", "connected": False, "app_session_closed": False}
    maximum = args.max_eur if args.max_eur is not None else os.environ.get("AMETLLER_MAX_EUR")
    if maximum is not None and decimal(maximum, "presupuesto") < 0:
        raise Error("El presupuesto no puede ser negativo.")
    if args.command == "login":
        if args.terminal:
            return login(storage, args.lang, args.email)
        if args.email:
            raise Error("--email se utiliza con --terminal. En el login por navegador, escribe tus datos en la web.")
        return browser_login(storage, args.lang, args.browser, args.timeout)
    if args.command == "import-har":
        return import_har(args.file, storage, args.lang)
    if args.command == "stores":
        return get_store(client, args.id) if args.id else find_stores(client, args.postcode, args.limit, args.distance, args.pickup_only)
    if args.command == "logout":
        with storage.lock("account"):
            storage.delete("account.json")
        return {"connected": False, "browser_session_closed": False}
    if args.command == "checkout" and args.action == "details":
        if args.review_address and not args.apply:
            raise Error("--review-address necesita --file y --apply.")
        if args.form:
            if args.apply:
                raise Error("Guarda y revisa primero el borrador con --form; después usa --file y --apply.")
            account = AccountClient(lang=args.lang, storage=storage)
            return collect_details(storage, account.customer().get("email", ""), args.timeout)
        details = read_details(args.file)
        if not args.apply:
            return {"scope": "account", "details_valid_locally": True, "applied": False,
                    "payment_submitted": False, "order_submitted": False,
                    "next_step": "Selecciona domicilio y franja; usa --apply para enviar contacto y dirección."}
        account = AccountClient(lang=args.lang, storage=storage)
        with storage.lock("remote-cart"), storage.lock("web-session"):
            web = WebCheckout(account).prepare()
            web.contact(details)
            return web.shipping_details(details, args.review_address)
    if args.command in ("whoami", "addresses", "orders", "remote-cart", "delivery") or (args.command == "checkout" and args.action in ("account", "test")):
        if args.command == "delivery" and args.action == "postcode":
            return {"postal_code": args.code, "coverage": postal_code(client, args.code), "delivery_slot_reserved": False}
        account = AccountClient(lang=args.lang, storage=storage)
        if args.command == "checkout" and args.action == "test":
            if not args.refresh:
                raise Error("Usa --refresh para autorizar la consulta web del checkout; puede actualizar la propuesta de entrega.")
            with storage.lock("remote-cart"), storage.lock("web-session"):
                return WebCheckout(account).prepare().test(maximum)
        if args.command == "delivery" and args.action in ("pickup", "select-slot", "home"):
            if not args.apply:
                if args.action == "home":
                    return {"scope": "account", "applied": False, "postal_code": args.postcode,
                            "coverage": postal_code(client, args.postcode), "order_submitted": False,
                            "next_step": "Usa --apply para elegir domicilio en la cesta; no envía dirección ni pedido."}
                return {"scope": "account", "applied": False, "order_submitted": False,
                        "pickup_store": get_store(client, args.store_id) if args.action == "pickup" else None,
                        "slot_id": args.slot_id if args.action == "select-slot" else None,
                        "date": args.date if args.action == "select-slot" else None,
                        "next_step": "Usa --apply para configurar la entrega de la cesta."}
            with storage.lock("remote-cart"), storage.lock("web-session"):
                web = WebCheckout(account).prepare()
                if args.action == "home":
                    return web.home(args.postcode)
                return web.pickup(args.store_id) if args.action == "pickup" else web.select_slot(args.slot_id, args.date)
        if args.command == "delivery" and args.action == "slots":
            return delivery_slots(account, args.postcode, args.pickup_store, args.refresh)
        if args.command == "whoami":
            return account.whoami()
        if args.command == "addresses":
            return account.addresses()
        if args.command == "orders":
            if not 1 <= args.limit <= 50 or args.offset < 0:
                raise Error("--limit debe estar entre 1 y 50 y --offset no puede ser negativo.")
            return account.orders(args.limit, args.offset)
        remote = RemoteCart(account, storage, getattr(args, "basket_id", None))
        with storage.lock("remote-cart"):
            if args.command == "delivery":
                if args.action == "status":
                    basket = remote.get()
                    return {**summary(basket or {}), "delivery_slot_reserved": None,
                            "notice": "Estado actual de la cesta; elegir franja no implica que se haya enviado un pedido."}
                if args.action == "methods":
                    return remote.shipping_methods(args.shipment_id)
                return remote.set_shipping(address_id=args.id if args.action == "address" else None,
                                           method_id=args.id if args.action == "method" else None, shipment_id=args.shipment_id)
            if args.command == "checkout":
                basket = remote.get()
                result = summary(basket or {})
                result.update({"checkout_url": "https://www.ametllerorigen.com/" + args.lang + "/cart",
                               "delivery_slot_reserved": None, "payment_submitted": False,
                               "checkout_ready": False,
                               "next_step": "Abre la web con la misma cuenta y confirma cesta, franja de entrega y pago allí."})
                result["pending_steps"] = ["Seleccionar franja y confirmar entrega en la web", "Confirmar pago y pedido en la web"]
                if not (basket or {}).get("productItems"):
                    result["pending_steps"].insert(0, "Añadir productos a la cesta")
                if not any(shipment.get("shippingAddress") for shipment in (basket or {}).get("shipments", [])):
                    result["pending_steps"].insert(0, "Completar dirección de entrega")
                if maximum is not None:
                    total = result["order_total_cents"]
                    if total is None or total > int(decimal(maximum) * 100):
                        raise Error("El total de la cuenta es desconocido o supera el presupuesto.")
                return result
            if args.action == "list":
                response = account.baskets()
                return {"scope": "account", "total": response.get("total"), "baskets": [summary(basket) for basket in response.get("baskets", [])]}
            if args.action == "get":
                return remote.confirmed_get()
            if args.action == "clear":
                return remote.clear(args.apply)
            if args.action == "sync":
                with storage.lock():
                    local = storage.read("cart.json", {})
                return remote.sync(local, maximum, args.apply)
            return remote.change("set" if args.action == "remove" else args.action, args.id,
                                 "0" if args.action == "remove" else args.quantity, maximum)
    if args.command == "search":
        return search_result(client, args, query=" ".join(args.query))
    if args.command == "promotions":
        return promotion_result(client, query=args.query, club=args.club, lots=args.lots,
                                all_results=args.all_results, limit=args.limit, offset=args.offset, raw=args.raw)
    if args.command == "product":
        raw = client.product(validate_id(args.id))
        return raw if args.raw else {**normalize(raw), "fetched_at": timestamp(), "source": ORIGIN}
    if args.command == "categories":
        if args.id:
            return search_result(client, args, category=validate_id(args.id))
        return {"categories": client.categories(), "fetched_at": timestamp(), "source": ORIGIN}
    if args.command == "batch":
        terms = [line.split("#", 1)[0].strip() for line in read_file(args.file).splitlines()]
        terms = [term for term in terms if term]
        if len(terms) > 100:
            raise Error("Máximo 100 términos por batch.")
        lines = []
        for term in terms:
            result = client.search(query=term, limit=1)
            hits = result.get("hits", [])
            lines.append({"query": term, "product": normalize(hits[0]) if hits else None})
        return {"lines": lines, "complete": all(line["product"] is not None for line in lines),
                "notice": "El primer resultado es una sugerencia; revisa producto y formato antes de añadirlo.", "fetched_at": timestamp()}
    if args.command == "total":
        return price_basket(client, parse_basket(read_file(args.file)), maximum)
    if args.command in ("cart", "checkout"):
        with storage.lock():
            basket = storage.read("cart.json", {})
            if not isinstance(basket, dict):
                raise Error("Cesta local inválida.")
            if args.command == "checkout":
                result = price_basket(client, basket, maximum)
                return {**result, "checkout_url": ORIGIN + f"/{args.lang}/online",
                        "synced_to_store": False, "order_submitted": False,
                        "next_step": "Abre las fichas, añade los productos en la web y confirma dirección, entrega y pago allí."}
            if args.action == "get":
                return price_basket(client, basket, maximum)
            if args.action == "clear":
                basket = {}
            elif args.action == "set-many":
                basket.update(parse_basket(read_file(args.file)))
            else:
                product_id = validate_id(args.id)
                quantity = decimal("0" if args.action == "remove" else args.quantity)
                if quantity < 0 or quantity > 10000 or (args.action == "add" and quantity == 0):
                    raise Error("Cantidad fuera de rango; add requiere una cantidad positiva.")
                if args.action == "add":
                    quantity += decimal(basket.get(product_id, "0"))
                basket[product_id] = str(quantity)
            basket = {key: value for key, value in basket.items() if decimal(value) > 0}
            # Revalidar toda la cesta antes de guardar: un fallo no deja cambios parciales.
            result = price_basket(client, basket, maximum)
            storage.write("cart.json", basket)
            return result
    if args.command == "doctor":
        result = client.search(query="yogur", limit=1)
        if not result.get("hits"):
            raise Error("La tienda respondió pero no devolvió el producto de prueba.")
        return {"ok": True, "version": __version__, "platform": "Salesforce Commerce Cloud",
                "session_type": "guest", "catalog_available": True, "cart_scope": "local",
                "account_login_supported": True, "account_connected_locally": bool(storage.read("account.json")),
                "checkout_submit_supported": False,
                "checkout_test_supported": True, "payments_blocked": True, "orders_blocked": True,
                "fetched_at": timestamp()}
    raise Error("Comando desconocido.")


def display_product(product):
    price = "sin precio" if product.get("price") is None else f"{product['price']:.2f} €"
    reference = ""
    if product.get("price_per_unit") is not None and product.get("reference_unit"):
        reference = f" ({product['price_per_unit']:.2f} €/{product['reference_unit'].lower()})"
    print(f"[{product['id']}] {product['name']} — {price}{reference}")
    for promotion in product.get("promotions") or []:
        parts = [promotion["label"]] if promotion.get("label") else []
        if promotion.get("promotional_price") is not None:
            parts.append(f"precio promocional: {promotion['promotional_price']:.2f} €")
        if parts:
            print("  Oferta: " + " · ".join(parts))


def display(result):
    if "coupons" in result:
        for coupon in result["coupons"]:
            print(f"[{coupon['id']}] {coupon['title'].strip()} — estado: {coupon['status']}")
            if coupon.get("badge_text"):
                print(f"  {coupon['badge_text']} · hasta: {coupon.get('date_to') or 'desconocido'}")
        print(f"{result['returned']} cupones mostrados de {result['total']} en la cuenta móvil.")
        print(result["notice"])
    elif result.get("scope") == "account":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif "products" in result:
        for product in result["products"]:
            display_product(product)
        print(f"{result['total']} resultados; mostrando {len(result['products'])} desde {result['offset']}.")
        if result.get("collection_scope") == "store_collection":
            print(result["notice"])
    elif "subtotal_cents" in result:
        for line in result["lines"]:
            product = line["product"]
            print(f"[{product['id']}] {product['name']} — {line['quantity']} × {product['price']:.2f} € = {line['line_total']:.2f} €")
        print(f"Subtotal estimado: {result['subtotal']:.2f} € · {result['count']} productos · cesta local")
        print(result["notice"])
        if "checkout_url" in result:
            print(result["next_step"])
            for line in result["lines"]:
                print(line["product"]["url"] or f"Buscar ID {line['product']['id']} en la tienda")
            print(result["checkout_url"])
    elif "categories" in result:
        def tree(categories, depth=0):
            for category in categories:
                print(f"{'  ' * depth}[{category['id']}] {category['name']}")
                tree(category.get("categories", []), depth + 1)
        tree(result["categories"])
    elif "id" in result and "ingredients" in result:
        display_product(result)
        for key, label in (("brand", "Marca"), ("ingredients", "Ingredientes"), ("nutrition_text", "Nutrición (texto de la tienda)"),
                           ("allergen_codes", "Códigos de alérgenos de la tienda"), ("conservation", "Conservación"), ("origin", "Origen"), ("url", "URL")):
            if result.get(key) is not None:
                print(f"{label}: {result[key]}")
    elif "lines" in result:
        for line in result["lines"]:
            print(f"{line['query']}:", end=" ")
            if line["product"]:
                display_product(line["product"])
            else:
                print("sin resultados")
        print(result["notice"])
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))


def execute(args, storage=None):
    """Operación estructurada compartida por CLI y MCP; no imprime el resultado."""
    storage = storage if storage is not None else Storage(args.state_dir)
    catalog_commands = ("search", "promotions", "product", "categories", "batch", "total", "cart", "checkout")
    selected_client = AccountClient if args.account and args.command in catalog_commands else Client
    return run(args, selected_client(lang=args.lang, storage=storage), storage)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        args = parser().parse_args(argv)
        result = execute(args)
        if args.json or args.raw:
            print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        else:
            display(result)
        return 0
    except Error as error:
        # Los errores van a stderr; stdout sólo contiene datos de una operación exitosa.
        if "--json" in argv:
            print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        else:
            print(f"error: {error}", file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError, TypeError) as error:
        message = f"No se pudo completar la operación ({type(error).__name__}). Revisa el estado local o la integración."
        print(json.dumps({"error": message}, ensure_ascii=False) if "--json" in argv else f"error: {message}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrumpido.", file=sys.stderr)
        return 130
