"""Datos privados de checkout: borrador local, sin tarjetas ni contraseñas."""

import html
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import stat
import sys
import threading
import time
from urllib.parse import parse_qs

from .storage import Error

FIELDS = {
    "contact": {"first_name": "Nombre", "last_name": "Apellidos", "email": "Email de la cuenta"},
    "shipping": {"first_name": "Nombre de envío", "last_name": "Apellidos de envío", "address1": "Calle (sin número)",
                 "street_number": "Número", "floor": "Piso y puerta (o bajos)", "postal_code": "Código postal",
                 "city": "Municipio", "state_code": "Provincia", "country": "País", "receiver": "Persona que recibe",
                 "phone": "Teléfono de entrega", "address_name": "Nombre de la dirección"},
}
STATES = ("barcelona", "gerona", "lerida", "tarragona")


def validate_details(value):
    if not isinstance(value, dict) or set(value) != set(FIELDS):
        raise Error("El borrador debe contener sólo contact y shipping, sin credenciales ni datos de pago.")
    result = {}
    for section, fields in FIELDS.items():
        data = value[section]
        if not isinstance(data, dict) or set(data) != set(fields):
            raise Error("Campos incompletos o inesperados en " + section + ".")
        result[section] = {}
        for key in fields:
            text = data[key]
            if not isinstance(text, str) or not text.strip() or len(text) > 150 or any(ord(char) < 32 for char in text):
                raise Error("Campo inválido en " + section + ": " + key + ".")
            result[section][key] = text.strip()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", result["contact"]["email"]):
        raise Error("Email inválido en el borrador.")
    address = result["shipping"]
    if len(address["floor"]) > 10:
        raise Error("Piso y puerta admite como máximo 10 caracteres en Ametller.")
    if not re.fullmatch(r"\d{5}", address["postal_code"]) or address["country"] != "ES" or address["state_code"] not in STATES:
        raise Error("Código postal, país o provincia no admitidos.")
    if not re.fullmatch(r"[+\d ().-]{9,25}", address["phone"]) or len(re.sub(r"\D", "", address["phone"])) < 9:
        raise Error("Teléfono de entrega inválido.")
    if not re.fullmatch(r"[A-Za-zÀ-ÖØ-öø-ÿ0-9\s,._'-]+", address["address_name"]):
        raise Error("Nombre de dirección no admitido por la tienda.")
    return result


def read_details(path):
    source = Path(path).expanduser()
    if source.resolve().is_relative_to(Path(__file__).resolve().parents[1]):
        raise Error("Guarda los datos de checkout fuera del repositorio.")
    try:
        descriptor = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor) as file:
            info = os.fstat(file.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_size > 32768:
                raise Error("El borrador debe ser un archivo privado (chmod 600) de hasta 32 KiB.")
            value = json.load(file)
    except (OSError, ValueError):
        raise Error("No se pudo leer el borrador privado de checkout.") from None
    return validate_details(value)


def collect_details(storage, email="", timeout=900):
    if not 30 <= timeout <= 1800:
        raise Error("El tiempo del formulario debe estar entre 30 y 1800 segundos.")
    # Rechazar antes de abrir la ventana si el destino no es privado.
    if storage.root.resolve().is_relative_to(Path(__file__).resolve().parents[1]):
        raise Error("El borrador debe guardarse fuera del repositorio; usa ~/.ametller.")
    controls = []
    previous = storage.read("checkout-details.json", {})
    for section, fields in FIELDS.items():
        controls.append("<fieldset><legend>" + ("Contacto" if section == "contact" else "Domicilio") + "</legend>")
        for key, label in fields.items():
            name = section + "." + key
            saved = previous.get(section, {}).get(key, "") if isinstance(previous, dict) and isinstance(previous.get(section, {}), dict) else ""
            default = saved if isinstance(saved, str) and len(saved) <= 150 else ""
            if key == "email":
                default = email or default
            if key == "state_code":
                control = '<select name="' + name + '" required><option value="">Selecciona</option>' + ''.join(
                    '<option value="' + state + '"' + (' selected' if state == default else '') + '>' + state.title() + '</option>' for state in STATES) + '</select>'
            elif key == "country":
                control = '<select name="' + name + '"><option value="ES">España</option></select>'
            else:
                kind = "email" if key == "email" else "tel" if key == "phone" else "text"
                limit = "10" if key == "floor" else "150"
                if key == "floor":
                    label += " · máximo 10 caracteres"
                control = '<input required maxlength="' + limit + '" type="' + kind + '" name="' + name + '" value="' + html.escape(default, quote=True) + '">'
            controls.append('<label>' + label + control + '</label>')
        controls.append('</fieldset>')
    content = ('<!doctype html><html lang="es"><meta charset="utf-8"><title>Ametller CLI · Datos privados</title>'
               '<style>body{font:16px system-ui;max-width:760px;margin:40px auto;padding:20px;background:#faf8f2;color:#233629}'
               'fieldset{border:1px solid #b9c7ba;margin:20px 0;padding:20px;display:grid;grid-template-columns:1fr 1fr;gap:16px}'
               'label{display:block}input,select{display:block;width:90%;padding:10px;margin-top:6px}button{padding:14px;background:#245c37;color:white;border:0;border-radius:6px}</style>'
               '<h1>Preparar entrega a domicilio</h1><p>Este formulario se sirve desde tu ordenador. Guarda un borrador en ~/.ametller con permisos privados.'
               ' No envía los datos a Ametller, no acepta condiciones de compra y no realiza pagos ni pedidos. No introduzcas datos de tarjeta.</p>'
               '<form method="post">' + ''.join(controls) + '<button>Guardar borrador local</button></form></html>').encode()

    def submit(pairs):
        expected = {section + "." + key for section, fields in FIELDS.items() for key in fields}
        if set(pairs) != expected or any(len(values) != 1 for values in pairs.values()):
            raise Error("Formulario incompleto.")
        details = validate_details({section: {key: pairs[section + "." + key][0] for key in fields} for section, fields in FIELDS.items()})
        storage.write("checkout-details.json", details)
        return {"details_saved_locally": True, "details_file": str((storage.root / "checkout-details.json").resolve()),
                "applied": False, "payment_submitted": False, "order_submitted": False}

    return _serve_form(content, submit, timeout, "Borrador guardado", "No se ha enviado a Ametller.")


def collect_address_review(result, timeout=900):
    original = result.get("originalAddress") or {}
    suggested = result.get("suggestedAddress") or {}
    if not isinstance(original.get("formattedAddress"), str) or not original["formattedAddress"]:
        raise Error("La tienda no devolvió una dirección que puedas revisar. Se conserva el bloqueo.")
    choices = '<label><input type="radio" name="choice" value="original" required> Mantener la dirección introducida</label><p>' + html.escape(original["formattedAddress"]) + '</p>'
    has_suggestion = isinstance(suggested.get("formattedAddress"), str) and isinstance(suggested.get("components"), dict)
    if has_suggestion:
        choices += '<label><input type="radio" name="choice" value="suggested" required> Usar la propuesta de Ametller</label><p>' + html.escape(suggested["formattedAddress"]) + '</p>'
    else:
        choices += '<p>Ametller no devolvió una alternativa. Puedes mantener la original para revisión de la tienda, o cerrar para cancelar.</p>'
    content = ('<!doctype html><html lang="es"><meta charset="utf-8"><title>Revisar dirección · Ametller CLI</title>'
               '<style>body{font:18px system-ui;max-width:760px;margin:60px auto;padding:20px;background:#faf8f2;color:#233629}'
               'label{display:block;margin-top:30px}button{padding:16px;background:#245c37;color:white;border:0;margin-top:25px}</style>'
               '<h1>Ametller pide revisar la dirección</h1><p>Elige la dirección de esta cesta temporal. Al confirmar se enviará esa elección a Ametller.'
               ' Mantener la original puede dejarla pendiente de revisión de la tienda. No acepta condiciones de compra ni envía pagos o pedidos.</p>'
               '<form method="post">' + choices + '<button>Confirmar sólo la dirección</button></form></html>').encode()

    def submit(pairs):
        if set(pairs) != {"choice"} or pairs["choice"] not in (["original"], ["suggested"]):
            raise Error("Elección de dirección inválida.")
        choice = pairs["choice"][0]
        if choice == "suggested" and not has_suggestion:
            raise Error("No existe una propuesta de dirección.")
        return choice

    return _serve_form(content, submit, timeout, "Dirección revisada", "La CLI continuará sólo con la dirección. Pago y pedido bloqueados.")


def _serve_form(content, submit, timeout, success_title, success_text):
    try:
        from playwright.sync_api import sync_playwright, Error as BrowserError
    except ImportError:
        raise Error("El formulario necesita el extra browser y Chromium, igual que login.") from None
    token = secrets.token_urlsafe(32)
    received = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, status, body):
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            # Chromium envía Origin: null en formularios con no-referrer.
            # Mantener el origen local para CSRF, sin enviarlo a otros sitios.
            self.send_header("Referrer-Policy", "same-origin")
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def valid(self):
            return self.path == "/" + token and self.headers.get("Host") == host

        def do_GET(self):
            self.reply(200 if self.valid() and not received else 404, content if self.valid() and not received else b"Cerrado")

        def do_POST(self):
            if not self.valid() or received or self.headers.get("Origin") != "http://" + host:
                self.reply(403, b"Solicitud no permitida"); return
            try:
                self.connection.settimeout(5)
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 32768:
                    raise Error("Formulario demasiado grande.")
                pairs = parse_qs(self.rfile.read(size).decode(), keep_blank_values=True, max_num_fields=20)
                received.append(submit(pairs))
                self.reply(200, ('<meta charset=utf-8><h1>' + success_title + '</h1><p>' + success_text + '</p>').encode())
            except (Error, ValueError, OSError):
                self.reply(400, b"<meta charset=utf-8>Revisa los campos, vuelve atras y corrige el formulario.")

    server = HTTPServer(("127.0.0.1", 0), Handler)
    server.timeout = 1
    host = "127.0.0.1:" + str(server.server_port)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    print("Abriendo formulario privado. Completa la acción indicada en la ventana; cierra para cancelar.", file=sys.stderr, flush=True)
    try:
        with sync_playwright() as runtime:
            browser = runtime.chromium.launch(headless=False)
            try:
                page = browser.new_page()
                page.goto("http://" + host + "/" + token)
                deadline = time.monotonic() + timeout
                while not received and time.monotonic() < deadline:
                    if page.is_closed() or not browser.is_connected():
                        raise Error("Formulario cancelado; se conserva el borrador anterior.")
                    page.wait_for_timeout(250)
                if not received:
                    raise Error("Formulario agotado; se conserva el borrador anterior.")
                return received[0]
            finally:
                if browser.is_connected():
                    browser.close()
    except BrowserError:
        if received:
            return received[0]
        raise Error("El formulario se interrumpió sin guardar; vuelve a abrirlo. Si no se abre, instala Chromium como indica login.") from None
    finally:
        server.shutdown(); server.server_close(); worker.join(timeout=2)
