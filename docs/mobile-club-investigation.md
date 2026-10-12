# Cupones personales del Club: investigación

Actualizado el 12 de octubre de 2026. Login móvil, lectura y activación implementados en 0.7;
renovación automática y desactivación pendientes.

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
  Se guardaron estructura de peticiones y tokens de respuesta, fuera del
  repositorio y con permisos privados. No se guardaron valores de la autenticación
  Basic ni cuerpos de login. Se activó un cupón expresamente elegido por el usuario
  y se confirmó su estado mediante una nueva consulta, sin comprar.

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

## Login y activación verificados

El acceso utiliza POST a https://app.ametllerorigen.cat/movil/api/v1/public/login,
con cuerpo vacío y autenticación HTTP Basic sobre HTTPS. La respuesta HTTP 200
contiene el campo token, cuyo valor es la autorización Bearer que después utiliza
el listado. No se conservó la contraseña ni el valor Basic capturado.
La CLI construye esa cabecera en memoria a partir de la entrada local, comprueba
el token mediante el listado y contrasta su sujeto con el email introducido antes
de guardarlo. El login directo desde el formulario local de la CLI funcionó sin
cookies, proxy, certificado temporal ni iPhone.

La activación observada utiliza:

```text
POST https://app.ametllerorigen.cat/api/mobile/v3/coupons/<id>/activate/
Authorization: Bearer <sesión móvil propia>
Accept: application/json
Accept-Language: es o ca
Content-Type: application/json
Cuerpo vacío
```

La app recibió HTTP 200; una lectura posterior confirmó activo el cupón elegido.
Ese protocolo se implementa en la CLI y se cubre con pruebas ficticias, incluyendo
respuesta perdida, resultado no confirmado y bloqueo de nuevas escrituras.
La evidencia distingue la activación desde la app de cualquier prueba posterior
de escritura desde CLI/MCP. No se enviaron pagos ni pedidos.

## Integración y límites

club login pide credenciales localmente; --form ofrece un formulario aislado.
No acepta contraseña por argumentos o stdin ni guarda credenciales para renovar
la sesión en segundo plano. Se guarda sólo el token y la fecha de conexión.
club import-capture se conserva como alternativa avanzada para una captura propia;
club status valida la conexión y coupons lista y filtra por ID o estado.
El filtro por ID utiliza el listado, aunque también se observó un GET de detalle.
club logout elimina la sesión móvil local, conservando un diario pendiente si existe.

coupons activate muestra la vista previa; --apply envía una única activación para
el cupón indicado y verifica el estado por GET. Si ya está activo no lo reenvía.
Ante resultado incierto, el diario privado conserva ID, estado solicitado y un hash
del sujeto de la cuenta, sin tokens. Bloquea nuevas escrituras hasta que una lectura
confirme activo ese cupón de esa misma cuenta. No se borra ni se reintenta en automático.
El MCP expone la vista previa como lectura y la activación sólo con --allow-writes,
confirmed=true y autorización del usuario para el cupón concreto.

Las peticiones no llevan cookies, no siguen redirecciones y no se reintentan.
El token observado no declara expiración: se devuelve null y no se promete duración.
El protocolo de renovación no está verificado; una sesión rechazada requiere login.
No se implementa desactivación. Activar no prueba la aplicación de un descuento a
una cesta; se mantienen los bloqueos de pagos y pedidos.

La captura temporal se detuvo al completar la observación y se indicó desactivar
el proxy y eliminar su perfil. Se observó un fallo TLS transitorio en la segunda
pasada, seguido de login y activación con HTTP 200. No se modificó la app ni se
eliminó su pinning; el resultado no demuestra que todas sus rutas sean capturables.
Las rutas de puntos y progreso del Club siguen sin protocolo verificado.
