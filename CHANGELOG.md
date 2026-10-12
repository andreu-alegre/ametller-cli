# Cambios

## 0.7.0 — en desarrollo

- Login móvil directo por email y contraseña oculta, o formulario local aislado,
  sin proxy/HAR. Valida la sesión y la identidad antes de guardarlas.
- Lectura de cupones personales de la app: estado, vigencia, condiciones y filtros
  por estado o ID. Sesión separada de la web, sin cookies ni contraseña persistida.
- Activación de un cupón concreto con vista previa, `--apply`, comprobación por
  lectura y diario privado que bloquea nuevas escrituras ante resultado incierto.
- MCP con listado, estado, vista previa y activación sólo con `--allow-writes`
  y `confirmed=true` tras autorización específica del usuario.
- Salida normal sin códigos de canje, bloqueos de redirecciones y validación del
  esquema remoto. Pruebas con datos ficticios y consulta real de sólo lectura.
- Renovación móvil automática y desactivación pendientes; pagos y pedidos bloqueados.

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
