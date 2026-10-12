# Cambios

## 0.7.0 — en desarrollo

- Lectura de cupones personales de la app: estado, vigencia, condiciones y filtros
  por estado o ID. No activa ni aplica descuentos al carrito.
- Sesión móvil separada de la web, importada desde una captura privada y validada
  antes de guardarla. No almacena cookies ni contraseña, ni expone autenticación.
- Herramientas MCP de lectura `list_personal_coupons` y `get_mobile_club_status`.
- Salida normal sin códigos de canje, bloqueos de redirecciones y validación del
  esquema remoto. Pruebas con datos ficticios y consulta real de sólo lectura.
- Activación y renovación móvil automática pendientes; pagos y pedidos bloqueados.

## 0.6.0 — 2026-10-11

- Distribución como paquete Python con licencia MIT, instrucciones de instalación
  desde GitHub y builds de wheel y sdist.
- Skill portable para agentes y `ametller capabilities --json`, disponible sin red.
- MCP local por stdio con catálogo, promociones, tiendas y consultas de cestas.
  Las escrituras requieren habilitar `--allow-writes` y confirmar cada llamada.
- CI para tests, formularios con datos ficticios, revisión de archivos y prueba de
  instalación desde el wheel fuera del repositorio. Sin compras ni cuentas en CI.
- Conserva los bloqueos de pagos y pedidos. Los cupones personales siguen pendientes.

## 0.5.0

- Promociones del catálogo, etiquetas Precio Club y lotes ahorro.

## 0.4.0

- Borrador privado de contacto/domicilio y validación anterior al pago.

## 0.3.0

- Login por navegador sin HAR, recogida y franjas de entrega.
