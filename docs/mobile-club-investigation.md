# Cupones personales del Club: investigación

Actualizado el 12 de octubre de 2026. Lectura autenticada implementada en 0.7;
activación y renovación automática pendientes.

## Fuentes y acceso

- [Información oficial del Club](https://corp.ametllerorigen.com/es/unete-al-club/):
  los cupones se activan en «Tus cupones» de la app y pueden aplicarse después
  en tienda física o en la tienda online, si se cumplen sus condiciones.
- App oficial instalada en el Mac: versión **26.0.10**, identificador
  **com.casaametller.clubca**. Ni los controles automáticos ni el clic manual
  permitieron avanzar desde «SEGÜENT». Se abandonó esa vía.
  [Captura del punto de bloqueo](mobile-app-onboarding.png).
- App oficial en el iPhone: el usuario accedió a su cuenta y autorizó la captura
  de la consulta de cupones mediante un proxy local y certificado temporal.
  Sólo se guardó la respuesta del listado, fuera del repositorio y con permisos
  privados. No se capturaron cuerpos de login ni se activaron cupones.

## Protocolo de lectura verificado

```text
GET https://app.ametllerorigen.cat/api/mobile/v3/coupons
Accept: application/json
Accept-Language: es o ca
Content-Type: application/json
Authorization: Bearer <sesión móvil propia>
```

Devuelve HTTP 200 y una lista de objetos. Se verificó con cuatro cupones mediante
captura, peticiones directas sin cookies y la CLI. Ambos idiomas funcionaron.
Sin Accept-Language, la prueba respondió HTTP 400. La sesión web no sustituye
la móvil; las pruebas anteriores sin sesión móvil devolvieron HTTP 403.
La identidad de la sesión utilizada se contrastó con la cuenta web validada,
sin publicar email, identificadores, tokens ni códigos de canje.

El esquema observado incluye id, title, status, badge_text, date_from,
date_to, description, legal_conditions_link, discount, discount_type,
image_url, campos de partner y ean_code. La salida normal usa una lista
explícita de campos que excluye el código de canje. --raw devuelve el objeto
original y debe tratarse como información privada. Los estados desconocidos no
se convierten en activos o inactivos.

La configuración del paquete declara certificate pinning. Este GET concreto
funcionó a través del proxy con el certificado confiado y sin modificar la app;
eso no demuestra que el resto de endpoints admita la misma captura.
Se detuvieron los servidores al terminar y se indicó desactivar el proxy y
eliminar el perfil temporal del iPhone. No se almacena certificado alguno en Git.

## Integración y límites

club import-capture valida la captura privada y consulta el endpoint fijo
antes de guardar una sesión móvil mínima. club status verifica esa conexión;
coupons lista y filtra por ID o estado. El filtro por ID utiliza el listado:
no se ha supuesto otro endpoint de detalle. club logout elimina la sesión
móvil local. El MCP expone sólo listado y estado de conexión.

Las peticiones no llevan cookies, no siguen redirecciones y no se reintentan.
El token observado no declara fecha de expiración: se devuelve null y no se
promete duración. El protocolo de renovación no está verificado; una sesión
rechazada requiere otra captura propia. La importación sigue siendo avanzada,
sin login móvil automático por email/contraseña.

Las cadenas de la app contienen /api/mobile/v3/club, /club/points,
/club/progress, /movil/api/v1/public/login y referencias a activación,
pero sus métodos y esquemas no están verificados. No se implementan ni invocan
operaciones a partir de esas cadenas.

Para añadir activación hará falta verificar una acción autorizada concreta,
sus condiciones y su resultado por lectura, sin reintentar escrituras inciertas.
La consulta actual no demuestra que un descuento se aplique al carrito.
promotions --club sigue consultando promociones del catálogo. Los bloqueos de
pagos y creación de pedidos permanecen vigentes.
