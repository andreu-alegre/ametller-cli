# Cupones personales del Club: investigación

Comprobado el 11 de octubre de 2026. Integración todavía no implementada.

## Fuentes comprobadas

- [Información oficial del Club](https://corp.ametllerorigen.com/es/unete-al-club/):
  los cupones se activan en «Tus cupones» de la app y pueden aplicarse después
  en tienda física o en la tienda online, si se cumplen sus condiciones.
- App oficial instalada desde la App Store en el Mac: versión **26.0.10**,
  identificador **com.casaametller.clubca**. Se abre, pero no se ha podido
  avanzar con los controles de automatización desde «SEGÜENT» en la presentación
  de notificaciones, incluso tras reiniciar y cambiar la disposición de la ventana.
  No se llegó al formulario de acceso ni se consultaron cupones autenticados.
  La app queda abierta para probar manualmente al volver al Mac.
  [Captura del punto de bloqueo](mobile-app-onboarding.png).
- Configuración y cadenas de rutas del paquete instalado, sin modificarlo ni
  copiar credenciales de configuración o datos privados al repositorio.

## Hallazgos de la app

La configuración de producción declara
`https://app.ametllerorigen.cat/movil/api` como URL base y activa certificate
pinning. El paquete contiene estas rutas y tipos relacionados:

- `/api/mobile/v3/coupons`
- `/api/mobile/v3/coupons/`
- `CouponsAPIRouter` y `CouponDetailScreen`
- `trace_coupon_activate` y `couponActivationChanged`
- `/api/mobile/v3/club`, `/api/mobile/v3/club/points`,
  `/api/mobile/v3/club/progress`
- `/movil/api/v1/public/login`

Son rutas observadas en el paquete: aún no certifican la URL final, método,
cabeceras, esquema de respuesta o protocolo de activación en el servidor.
No se han hecho llamadas de activación ni intentos de login con contraseña.

## Pruebas de acceso de sólo lectura

Una petición GET a
`https://app.ametllerorigen.cat/api/mobile/v3/coupons` responde HTTP **403**
con un error JSON, tanto sin autenticación como con el token de la sesión web
registrada. Esto confirma que el servidor es accesible, pero no permite
certificar todavía una lectura autenticada ni que esa sea la URL final correcta.
No se guardaron ni imprimieron tokens.

La captura HAR existente tampoco contiene peticiones al host del servicio móvil.
Sólo se comprobó ese dato; no se imprimieron sus peticiones ni cuerpos privados.
La CLI guarda sesiones, no contraseñas. La reutilización directa de la sesión web
probada no ha permitido completar esta lectura.

El perfil SCAPI tiene un campo `c_clubCardId`, pero no devuelve la lista de
cupones. Su presencia no prueba que los tokens web y de la app sean intercambiables.

## Próximo paso

Completar el acceso en la app oficial y comprobar el protocolo de su sesión.
Después, verificar listado y detalle con identidad confirmada y estado privado
fuera del repositorio. Una futura activación debe mostrar primero el cupón y
sus condiciones y comprobar por lectura el estado posterior, sin reintentar
una escritura incierta.

`promotions --club` sigue consultando las etiquetas Club del catálogo, no
cupones personales. Los bloqueos de pago y creación de pedidos siguen vigentes.
No se ha activado ningún cupón ni modificado la cesta.
