# ametller-cli

CLI no oficial de **Ametller Origen**, inspirada en la experiencia de
[mercadona-cli](https://github.com/ivorpad/mercadona-cli). Implementación independiente
en Python. Catálogo y cestas sin dependencias de ejecución; el login por navegador
utiliza Playwright como dependencia opcional. Compatible con macOS y Linux, Python 3.10+.

Licencia MIT. [Repositorio](https://github.com/andreu-alegre/ametller-cli) ·
[Releases](https://github.com/andreu-alegre/ametller-cli/releases) ·
[Skill para agentes](skills/ametller/SKILL.md) · [Instalación y MCP](docs/distribution.md).
Repositorio público, instalable desde GitHub. No hay paquete publicado en PyPI
ni npm.

Busca productos reales, consulta sus fichas y prepara una cesta local con precios
actuales. Utiliza las mismas APIs de Salesforce Commerce Cloud que la tienda online.
No requiere una cuenta: obtiene una sesión de invitado mediante el flujo público PKCE.

**Versión 0.8 (en desarrollo):** abre el checkout oficial en un navegador aislado
para que el usuario termine la compra; incluye modo de revisión sin pago.
La versión 0.7 añadió login móvil por email/contraseña, lectura
y activación de cupones personales, con una sesión separada del login web.
La versión 0.6 incorporó distribución, skill para agentes, MCP local opcional y CI.
La versión 0.5 añadió promociones, filtro de Precio Club y lotes ahorro.
La versión 0.4 incorporó preparación de domicilio, borrador privado de contacto y
dirección, y `checkout test` para validar el checkout antes del pago. El login por
navegador, catálogo, cestas, recogida y franjas están probados con la tienda.
**Las peticiones automáticas de pago y creación de pedidos están bloqueadas.**
El usuario puede pagar manualmente en la ventana oficial abierta con `checkout open`.
El alcance comprobado de domicilio figura en `docs/checkout-test-verification.json`.

## Ejecutar

Con [uv](https://docs.astral.sh/uv/guides/tools/), sin cuenta de GitHub:

```bash
uv tool install 'ametller-cli[browser,mcp] @ git+https://github.com/andreu-alegre/ametller-cli@v0.6.0'
uv tool run --from 'ametller-cli[browser,mcp] @ git+https://github.com/andreu-alegre/ametller-cli@v0.6.0' playwright install chromium
ametller capabilities --json
ametller search yogur --limit 5 --json
ametller login
```

Omite los extras para instalar sólo la CLI sin navegador ni MCP. Cada usuario
conecta su propia cuenta; los archivos de sesión permanecen en su máquina.
El instalador anterior usa la release 0.6.0. Los cupones y la apertura del checkout
requieren las ramas de desarrollo 0.7 y 0.8, respectivamente, hasta publicar la nueva release.

Desde este directorio, sin instalación:

```bash
./bin/ametller search yogur --limit 5
./bin/ametller promotions --limit 10
./bin/ametller product 2351
./bin/ametller categories
./bin/ametller categories --id 127 --limit 10
./bin/ametller doctor --json
```

Para disponer del comando `ametller` en un entorno Python:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e '.[browser]'
python3 -m playwright install chromium
ametller search tomate
```

También puedes ejecutar `python3 -m ametller` desde este directorio. No se ha
publicado un paquete en PyPI ni en npm.

## Catálogo

```bash
ametller search "yogur griego natural" --limit 5 --json
ametller search tomate --limit 20 --offset 20
ametller product 2351 --json
ametller product 2351 --raw
ametller categories --lang ca
ametller categories --id 127 --json
ametller batch -f examples/busquedas.txt --json
```

`search` devuelve ID, nombre, precio, precio por kg/litro cuando existe, imagen y
datos del formato. `product` añade marca, EAN, ingredientes, nutrición, conservación,
origen, enlace y condiciones de venta cuando la tienda proporciona esos campos.
Los datos ausentes se devuelven como `null`.

Los alérgenos se exponen como **códigos originales de la tienda** (`allergen_codes`):
esta versión no interpreta su significado. La nutrición se conserva como texto
original (`nutrition_text`), sin inferir la base de medida.

`batch` lee un término por línea y hace una consulta por término, secuencialmente;
el primer resultado es una sugerencia que hay que revisar. No añade productos.

## Promociones

```bash
ametller promotions --limit 20
ametller promotions --all --json
ametller promotions --query yogur
ametller promotions --club --account
ametller promotions --club --query yogur --account --json
ametller promotions --lots
ametller promotions --limit 20 --offset 20 --lang ca
```

Consulta la colección **Promociones** publicada por la tienda y carga las fichas
para mostrar las condiciones: etiquetas como `2x4€`, `PRECIO CLUB` y el precio
promocional cuando la API lo proporciona. `--lots` consulta **Lotes Ahorro**.
`--query` busca dentro de la colección; `--all` lee todas sus páginas desde
`--offset` (máximo 5000 productos). La paginación normal admite `--limit` de 1 a 200.

`--club` filtra las etiquetas explícitas Club después de leer toda la colección:
`total` y `--offset` se refieren al resultado filtrado, incluso si las ofertas están
en páginas posteriores. No usa la categoría vacía «Precio Club» como prueba de que
no existen ofertas. `--account` consulta con la sesión conectada y nunca recurre
a una sesión de invitado si falla la cuenta.

El JSON conserva `price` como precio de catálogo y añade `promotions` con
`label`, `promotional_price`, `promotional_price_cents` y `club_only` (sólo `true`
si lo indica la etiqueta; desconocido es `null`). `--raw` conserva las fichas
originales dentro de `products`. La colección puede incluir productos sin una
condición de promoción devuelta por la API; no se inventa un descuento.

**Consultar una promoción no confirma su aplicación a una cesta.** No se calcula
un precio por unidad a partir de un `2x…`, ni se descuentan automáticamente ofertas
Club del presupuesto local. Las condiciones finales se comprueban en la cesta
remota. No se reciben fechas de vigencia en estos datos. Esta consulta no modifica
productos, entrega, pagos ni pedidos. Evidencia: `docs/promotions-verification.json`.

## Cupones personales del Club

La sesión móvil es independiente del login de la tienda web. `club login` conecta
directamente con el servicio de Ametller, sin proxy, certificado ni HAR. Pide email
y contraseña oculta en un terminal interactivo; `--form` abre un formulario local
aislado con el extra browser. Las credenciales se envían sólo al servicio por HTTPS.
No se guarda la contraseña ni se admiten argumentos de contraseña o lectura por stdin.

```bash
ametller club login
ametller club login --form
ametller club status --json
ametller coupons --json
ametller coupons --status inactive --lang ca --json
ametller coupons --id '<id devuelto por la consulta>' --json
ametller club logout
```

La CLI valida el token y la identidad mediante una consulta antes de sustituir
la conexión anterior. Guarda sólo la autorización y la fecha de conexión en
`~/.ametller/club-account.json`, sin contraseña ni cookies. Los agentes utilizan
esa sesión local; no necesitan recibir las credenciales del usuario.

Como alternativa avanzada, `club import-capture --file <ruta privada>` acepta
únicamente el JSON del capturador de esta investigación,
fuera del repositorio, con permisos privados: método `GET`, URL exacta
`https://app.ametllerorigen.cat/api/mobile/v3/coupons`, `response_status: 200`
y la cabecera `Authorization` en `request_headers`. No acepta un HAR genérico. Valida
la sesión con una lectura antes de guardarla. No usa el token web como alternativa.

La consulta devuelve título, estado, descuento, fechas y condiciones recibidas
de la API. `active` es `null` si el estado no se reconoce. Los códigos de canje
se excluyen de la salida normal; `--raw` devuelve los objetos originales y puede
incluirlos, por lo que su salida es privada. `--id` filtra el listado recibido:
no presupone otro endpoint de detalle. `club logout` elimina sólo la sesión
móvil local. Si el servidor rechaza la sesión, hace falta conectar de nuevo;
una fecha de expiración `null` significa que se desconoce. La renovación
automática sigue pendiente: no se guarda contraseña para volver a entrar en segundo plano.

```bash
ametller coupons activate '<id devuelto por la consulta>' --json
ametller coupons activate '<id autorizado>' --apply --json
```

La primera llamada muestra estado, vigencia y condiciones sin activar. Tras
revisarlas y autorizar ese cupón concreto, `--apply` envía una única activación
y comprueba el estado por lectura. Un cupón ya activo no genera otra escritura.
Si el resultado queda incierto, `club-pending.json` bloquea nuevas activaciones;
`coupons` o `club status` lo reconcilian sólo cuando el servidor confirma activo
el cupón de la misma cuenta. Si sigue pendiente, revisa en la app antes de actuar;
no repitas la escritura ni borres el diario automáticamente.

Leer o activar un cupón no confirma su aplicación al carrito. No se modifican
entrega, cesta, pagos ni pedidos. No se implementa desactivación.
La verificación está en [la investigación móvil](docs/mobile-club-investigation.md).
Si se utiliza un proxy para obtener la captura, requiere consentimiento informado
para el certificado temporal; al terminar, desactiva el proxy y elimina ese perfil.

## Presupuesto y cesta local

```bash
ametller total -f examples/cesta.txt --max 15
ametller cart add 2351 2 --max 15
ametller cart set 42171 1 --max 15
ametller cart get --json
ametller cart set-many -f examples/cesta.txt --max 15
ametller cart remove 2351
ametller cart set 42171 0
ametller cart clear
ametller checkout prepare --max 15 --json
```

Los archivos de cesta contienen `<id> <cantidad>` y aceptan comentarios con `#`.
`add` suma a la cantidad existente; `set` fija una cantidad absoluta; `set-many`
aplica todos los cambios juntos, conservando los productos no mencionados.
Las líneas con cantidad `0` eliminan un producto. Los IDs duplicados se rechazan.

**La cantidad cuenta unidades de venta, no kilos.** Por ejemplo, un manojo de
plátanos de aproximadamente 900 g tiene cantidad `1`; tres tomates vendidos por
pieza tienen cantidad `3`. Se comprueban la cantidad mínima y los incrementos que
indica la API. Las cantidades fraccionarias sólo se aceptan si el producto las permite.

Se calcula cada línea con aritmética decimal y redondeo a céntimos. Cada lectura o
cambio vuelve a consultar el precio de todos los productos de la cesta. Si falta
un producto, un precio, su unidad de venta o la disponibilidad de catálogo, se
rechaza la operación. Los cambios se guardan de forma atómica y con bloqueo entre
procesos; un error o un presupuesto superado deja la cesta anterior intacta.

`--max` limita el **subtotal de productos estimado**, con prioridad sobre
`AMETLLER_MAX_EUR`. No incluye entrega, peso definitivo, descuentos de cuenta ni
disponibilidad por dirección. `0` es un límite de cero euros; omitirlo significa
no establecer un límite. Por defecto se consulta el catálogo como invitado;
`--account` utiliza la cuenta conectada para las consultas y la cesta local.

`checkout prepare` devuelve la cesta revalidada y enlaces a las fichas y a la tienda.
Sus salidas incluyen `synced_to_store: false` y `order_submitted: false`. No reserva
entrega, sincroniza una cesta remota ni realiza un pedido.

## Conectar tu cuenta

`ametller login` abre una ventana aislada con la web de Ametller. Inicia sesión
allí normalmente; la CLI captura únicamente autenticación de Ametller, comprueba
el perfil en el servidor y obtiene la sesión del carrito/checkout. La ventana se
cierra al terminar. **No exporta HAR, no lee la contraseña ni guarda el perfil
del navegador.** Si cancelas, se conserva la conexión anterior.

```bash
ametller login
ametller whoami --json
ametller search yogur --account --json
ametller product 2351 --account --json
ametller addresses --json
ametller orders --limit 10 --json
ametller logout
```

El login requiere el extra `browser` y Chromium (comandos de instalación arriba).
También admite `--browser chrome` o `--browser msedge` si están instalados.
El acceso directo con contraseña oculta se conserva como `login --terminal`:
implementado según SLAS B2C, pendiente de validar con el login personalizado de
Ametller. No se acepta la contraseña como argumento ni se guarda.

La alternativa es importar tu sesión del navegador. Abre Ametller con tu cuenta,
abre DevTools → Network, permite exportar HAR con datos sensibles, recarga y
exporta el archivo fuera del repositorio:

```bash
ametller import-har --file ~/Downloads/ametller.har
ametller whoami
```

Un HAR exportado sin datos sensibles suele omitir las cookies y el token y no
permite conectar. El importador sólo extrae tokens y cookies de autenticación de
Ametller y del servidor Salesforce descubierto; ignora contraseñas y peticiones
a terceros. Antes de guardar la conexión, consulta el perfil en el servidor y
comprueba la identidad. Un rechazo conserva la sesión anterior.

El HAR puede contener secretos de sesión: mantenlo fuera de Git y bórralo desde
el navegador de archivos cuando ya no lo necesites. La CLI no guarda el HAR ni
lo elimina automáticamente. `logout` elimina la conexión local; la sesión del
navegador continúa abierta.

## Cesta de la cuenta y entrega

`remote-cart` opera la cesta real de la cuenta conectada. `cart` sigue siendo
local. No se inicia sesión como invitado si falla la cuenta.

```bash
ametller remote-cart list --json
ametller remote-cart get --json
ametller remote-cart add 2351 1 --max 20
ametller remote-cart set 2351 2 --max 20
ametller remote-cart remove 2351
ametller remote-cart sync --max 20           # sólo muestra el plan
ametller remote-cart sync --apply --max 20   # fija cantidades de la cesta local
ametller remote-cart clear                  # sólo muestra la cesta
ametller remote-cart clear --apply
ametller delivery postcode 08021 --json
ametller stores --postcode 08021 --pickup-only --json
ametller stores --id I220 --json
ametller delivery methods --json
ametller delivery pickup I220                 # vista previa
ametller delivery pickup I220 --apply         # elige modalidad y tienda
ametller delivery home --postcode 08021       # vista previa
ametller delivery home --postcode 08021 --apply
ametller delivery slots --refresh --json
ametller delivery slots --refresh --postcode 08021 --json
ametller delivery select-slot ID_FRANJA --date 'FECHA_DEVUELTA_POR_SLOTS'
ametller delivery select-slot ID_FRANJA --date 'FECHA_DEVUELTA_POR_SLOTS' --apply
ametller delivery status --json
ametller addresses --json
ametller delivery address ID_DIRECCION
ametller delivery method ID_METODO
ametller checkout account --max 30 --json
```

Si hay varias cestas, usa `--basket-id ID`; con varios envíos, `--shipment-id ID`.
La dirección debe existir en la cuenta y el método debe figurar entre los que
devuelve la tienda para ese envío. `postcode` consulta cobertura, no stock de
cada producto ni disponibilidad de una franja horaria.

`stores` busca por las coordenadas públicas del código postal y devuelve las
tiendas cercanas y sus servicios declarados. `--pickup-only` filtra los resultados
devueltos; no implica disponibilidad de productos o de una franja.

`delivery pickup ID --apply` configura recogida y confirma la tienda en la web.
`delivery select-slot ID --date FECHA --apply` vuelve a comprobar la franja,
la guarda y verifica el ID y la fecha en la cesta. Sin `--apply`, ambos comandos
devuelven una vista previa. Una selección confirmada **no garantiza una reserva
definitiva ni envía un pedido**; `delivery_slot_reserved` permanece `null`.

`delivery slots --refresh` consulta las franjas reales del checkout SFRA. Requiere
la sesión obtenida con `login` (o HAR) y una cesta que la web permita llevar al checkout (mínimo
20 € de productos en la prueba). **Abrir ese flujo puede actualizar la propuesta
de entrega por defecto de la cesta**; por eso exige `--refresh`. No envía un pedido
ni confirma una reserva. Usa la modalidad ya elegida; para consultar otra tienda
de recogida: `--pickup-store ID_TIENDA`. Cambiar la consulta no selecciona esa tienda.
La CLI comprueba que API y checkout reconocen la misma cuenta. Conserva las
cookies de sesión renovadas y no repite escrituras, incluso cuando Ametller las
expone mediante GET. `delivery status` lee el estado actual de la cesta.

`sync` conserva los productos remotos no mencionados en la cesta local y fija las
cantidades de los productos mencionados. Puede necesitar dos lotes de escritura;
`clear` elimina las líneas secuencialmente. Estas operaciones **no son atómicas**.
La CLI bloquea sus propios procesos, comprueba cambios entre lectura y escritura
y confirma cada operación por GET. La tienda o el navegador pueden cambiar la
cesta durante el proceso.

El presupuesto de una modificación remota se comprueba con el catálogo de la
cuenta **antes de escribir**. El resultado también devuelve el total calculado
por la tienda y `server_product_budget_exceeded` cuando se proporcionó `--max`.
Ese total puede diferir por promociones, peso o recalculaciones. No se hace una
reversión automática ni se promete un límite final garantizado. `checkout account
--max` comprueba el total remoto con entrega cuando existe; si es desconocido,
rechaza la preparación.

Si se pierde la respuesta de una escritura, **no repitas add**: ejecuta
`remote-cart get`, revisa cantidades y después decide el siguiente cambio. La CLI
mantiene un bloqueo en `remote-pending.json` hasta recuperar el estado por GET.

`checkout account` devuelve el enlace al carrito SFRA de Ametller. No autoriza
ni ejecuta una compra; `checkout_ready` permanece `false`. Para comprobar la
preparación real anterior al pago usa `checkout test`. Elegir una franja no
garantiza reserva.

## Probar domicilio y checkout sin comprar

```bash
ametller checkout details --form
ametller checkout details --file ~/.ametller/checkout-details.json  # valida el borrador local
ametller delivery home --postcode TU_CP --apply
ametller delivery slots --refresh --json
ametller delivery select-slot ID_FRANJA --date FECHA --apply
ametller checkout details --file ~/.ametller/checkout-details.json --apply
# Si la tienda pide revisar la dirección, añadir --review-address abre su propuesta:
ametller checkout details --file ~/.ametller/checkout-details.json --apply --review-address
ametller checkout test --refresh --max 35 --json
```

El formulario abre una ventana aislada servida desde `127.0.0.1`. Guarda contacto,
calle, número, piso/puerta, municipio, provincia, código postal, destinatario y
teléfono en un borrador local con permisos `0600`, fuera del repositorio. El email
debe coincidir con la cuenta. No pide tarjetas, contraseñas ni códigos. El archivo
no se imprime en las salidas de estos comandos. Puedes borrarlo cuando termine la
prueba; conserva datos personales mientras exista.

`delivery home --apply` elige domicilio y el código postal; no envía aún la dirección.
Después de elegir franja, `checkout details --file ... --apply` envía contacto y
dirección mediante los formularios oficiales. **Son cambios reales anteriores al
pago:** Ametller puede conservar esos datos en la cuenta. Piso y puerta tiene un
máximo de 10 caracteres, igual que el formulario de Ametller. Se omiten los controles
de publicidad y consentimiento; no se aceptan condiciones de compra. Contacto y
envío son dos escrituras distintas, sin atomicidad. Si la tienda propone corregir
la dirección, rechaza productos o franja, la CLI se detiene para revisión: no
acepta correcciones automáticamente ni finge una dirección geocodificada.
`--review-address` muestra la original y la propuesta en un formulario privado y
espera una elección explícita, sin opción preseleccionada. Sólo después de esa
elección y de leer la misma cesta se envía la confirmación de dirección de Ametller.
Mantener la original puede dejarla pendiente de revisión de la tienda; no equivale
a geocodificarla. Si cambia el código postal propuesto o la cesta, se detiene para
elegir otra franja o revisar el cambio.

`checkout test --refresh` comprueba identidad, datos presentes, dirección, facturación, franja,
aceptación del envío y disponibilidad del formulario de pago. Devuelve comprobaciones
individuales y `prepayment_ready`. `--max` contrasta el total remoto conocido con
el presupuesto, y `web_totals` conserva los importes mostrados por el checkout.
El cálculo web puede actualizar la propuesta de entrega, por eso requiere `--refresh`.

No envía `SubmitPayment`, `PlaceOrder` ni los servicios de pago de Adyen. Una lista
cerrada de servicios permitidos bloquea cualquier controlador web nuevo antes de
acceder a la red; SCAPI bloquea escrituras de pagos/pedidos. No existe una opción
para quitar el bloqueo. `payment_processing_verified` sigue siendo `false`: esta
prueba **no verifica cobros, rechazos de tarjeta, 3DS, confirmación de pedido ni
reserva definitiva**. Las pruebas locales simulan errores de contacto/envío y
comprueban el bloqueo de compra, no un pago aceptado por Ametller.

No se ha encontrado ni conectado un sandbox de Ametller. Las tarjetas de prueba
de Adyen requieren una integración configurada para pruebas: no deben usarse en
el checkout real. Para validar de verdad el procesamiento de pago sin comprar se
necesita un entorno de pruebas facilitado por Ametller/Adyen.

## Abrir el checkout para confirmación manual

```bash
ametller checkout open --max 50
ametller checkout open --max 50 --browser chrome --timeout 1800
ametller checkout open --max 50 --review-only --json
```

Necesita el extra browser, la cuenta web conectada con `ametller login` y una única
cesta remota con productos. No sincroniza la cesta local ni elige dirección o franja
por iniciativa propia. Usa `remote-cart sync` y las operaciones de entrega para
prepararlas con la autorización correspondiente. Si todavía faltan datos, el
checkout oficial permite completarlos manualmente. La apertura puede recalcular
la propuesta de entrega mediante las consultas web ya utilizadas por `checkout test`.

Antes de mostrar la tienda, la CLI comprueba identidad, cesta e importe conocido
y valida de nuevo la cuenta dentro del contexto del navegador. `--max` es obligatorio
y limita el importe inicial; las modificaciones posteriores y el total final se
revisan en la web. Se transfieren sólo las cookies de autenticación necesarias,
sin copiarlas a argumentos, URLs, perfiles persistentes, HAR o logs.

En modo normal, **puedes realizar una compra real manualmente**. La CLI no rellena
tarjetas, pulsa pagar, captura respuestas de pago ni controla una validación bancaria.
La ventana permanece abierta hasta que la cierras o se agota el tiempo; el resultado
se imprime entonces. `payment_submitted` y `order_submitted` son `null` porque la
CLI no certifica lo que hayas hecho manualmente. Comprueba el pedido en Ametller
antes de repetir un pago. La cuenta puede necesitar reconexión si la web rota su sesión.

`--review-only` bloquea escrituras del navegador, el proveedor de pago y controladores
SFRA no permitidos, incluyendo algunos que escriben mediante GET. Sirve para probar
la apertura sin comprar; los formularios de entrega y pago pueden quedar limitados.
No introduzcas tarjetas en este modo. Las API de la CLI conservan sus bloqueos de
pago/pedido en ambos modos. El comando es interactivo y se usa desde la CLI; no se
expone como herramienta MCP. [Evidencia](docs/checkout-browser-verification.json).

Con autorización para crear y eliminar una cesta de cuenta temporal:

```bash
python scripts/smoke_checkout_browser.py
```

La prueba se detiene si ya existe una cesta y comprueba el historial antes y después.
Usa sólo revisión y no acepta condiciones de compra. Para preparar una futura
automatización de pagos, consulta [las opciones de pruebas](docs/payment-testing.md).

## Uso desde scripts y agentes

Consulta `ametller capabilities --json` para descubrir funciones y límites
sin acceder a la red. La [skill portable](skills/ametller/SKILL.md) describe el
flujo de búsqueda, presupuesto, conexión y sincronización de cestas.

El extra `mcp` añade `ametller-mcp`, un servidor **local por stdio** que comparte
operaciones y sesión con la CLI. Arranca con herramientas de lectura; para
exponer cambios de cesta o activaciones necesita `--allow-writes` y cada escritura requiere
`confirmed=true` tras autorización del usuario. Configuración y listado de
herramientas: [docs/distribution.md](docs/distribution.md). No abre un servicio
remoto ni recoge las sesiones de otros usuarios.

`--json` produce JSON en stdout. Los errores van a stderr, con código de salida 1;
en modo JSON también son estructurados. Los flags comunes (`--json`, `--lang`,
`--max`, `--state-dir`, `--raw`, `--account`) pueden ir antes o después de los subcomandos.
`--raw` devuelve los datos originales del catálogo en formato JSON.

Ejemplo para comparar precio por kilo entre los resultados devueltos:

```bash
ametller search yogur --limit 50 --json |
  jq '.products | map(select(.reference_unit == "KG" and .price_per_unit != null)) | sort_by(.price_per_unit)'
```

No confundir `price`, precio de la unidad de venta, con `price_per_unit`, precio
de referencia por kg o litro. El agente debe revisar que el ID y el formato
correspondan al producto solicitado.

## Estado y conexión

- Estado local: `~/.ametller/`, configurable con `AMETLLER_HOME` o `--state-dir`.
- `club-account.json` contiene la sesión móvil privada para cupones, separada de
  `account.json`. No se copia al repositorio ni a los paquetes publicados.
- `club-pending.json` protege activaciones inciertas; no contiene credenciales.
- `cart.json` contiene únicamente IDs y cantidades de la cesta local.
- `site.json` cachea durante una hora la configuración pública descubierta en la web.
- `session.json` cachea el token de invitado hasta su caducidad. No se guardan
  contraseñas ni tokens de renovación **de invitado**. Los archivos nuevos tienen permisos `0600`
  y el directorio nuevo `0700`.
- `account.json` guarda la sesión de cuenta y su token de renovación cuando se
  proporciona. Se renueva bajo bloqueo, sin cambiar a invitado. No contiene contraseña.
- `remote-pending.json` guarda la operación y los IDs de cuenta/cesta cuando una
  escritura necesita reconciliación; no contiene el perfil ni el HAR.
- `checkout-details.json` guarda el borrador personal del formulario, con permisos
  privados. Su ubicación dentro del repositorio se rechaza, igual que las sesiones.
- El token se obtiene con PKCE; la redirección se inspecciona sin navegar a ella.
- Un 401 en el catálogo de invitado provoca una nueva sesión de invitado y un
  único reintento. Con cuenta, se intenta renovar esa misma cuenta sin pasar a invitado.
- Las lecturas reintentan de forma limitada ante 429/502/503/504, respetando
  `Retry-After` hasta 30 segundos. Los POST de autorización no se reintentan.
- Si la tienda cambia de plataforma o su API, la integración puede necesitar cambios.

## Equivalencia con la CLI de referencia

| Función | Estado en esta versión |
| --- | --- |
| Búsqueda, ficha, precios, categorías | Implementado y probado con la tienda |
| Español/catalán, JSON, consultas por lista | Implementado y probado |
| Presupuesto de cesta por IDs | Implementado y probado |
| Añadir, fijar, eliminar, vaciar, cambios por archivo | Local probado; API remota probada con invitado |
| Login sin HAR, importar cuenta, renovar y comprobar identidad | Login por navegador probado con cuenta registrada; renovación real probada |
| Login directo por email/contraseña | Implementado según SLAS B2C; pendiente de validación frente al login personalizado |
| Acceso a pedidos anteriores y direcciones | Lecturas probadas con cuenta registrada |
| Promociones, filtro de etiquetas Club y lotes ahorro | Implementado y probado con invitado y cuenta; no confirma descuento final de cesta |
| Cupones personales de la app | Login directo, listado, filtros y activación implementados; renovación automática y desactivación pendientes. Ver [investigación](docs/mobile-club-investigation.md) |
| Cesta de la cuenta | Añadir, actualizar y eliminar probados con cuenta y web; lotes probados con invitado |
| Código postal y métodos de envío | API probada con invitado y métodos también con cuenta |
| Tiendas y recogida | Búsqueda por código postal y selección de tienda/método probadas |
| Franjas reales de entrega | Consulta SFRA y selección confirmada en cesta probadas para recogida |
| Aplicar dirección guardada/método a cesta | Implementado; no probado con dirección guardada (cuenta de prueba sin direcciones) |
| Domicilio, contacto y dirección nueva | Formularios SFRA implementados; ver evidencia actual de prueba registrada |
| Preparación de compra | Lista local, cuenta y validación anterior al pago con `checkout test` |
| Enviar pedido y pago | Automatización bloqueada; `checkout open` permite confirmación humana en la web. Procesamiento real no validado |
| CLI para agentes, skill y MCP local | JSON, descubrimiento sin red y MCP opcional; escrituras MCP desactivadas por defecto |
| Distribución | Repositorio público; paquete Python instalable desde Git y releases |

Para igualar el flujo completo quedan pago/pedido SFRA y validar el login directo
de terminal. El estado real de dirección/contacto se documenta por separado de
las pruebas locales. Los slots CMS de SCAPI no
son horarios de entrega: se consulta el controlador SFRA TimeSlot de la tienda.

## Verificación

```bash
python3 -m unittest discover -s tests -v
AMETLLER_BROWSER_TESTS=1 python -m unittest discover -s tests -v
python3 scripts/smoke.py
python3 scripts/smoke_promotions.py
python3 scripts/smoke_promotions.py --account  # lecturas con la cuenta conectada
```

El extra `mcp` activa los tests del protocolo, incluidos arranque por stdio,
validación de argumentos, permisos de escritura y presupuesto. La CI no usa
credenciales de Ametller ni modifica cestas remotas. Para validar la distribución:

```bash
python scripts/check_publication.py
python -m pip install build twine
python -m build
python -m twine check dist/*
python scripts/check_install.py dist/ametller_cli-0.8.0-py3-none-any.whl
```

Los tests son locales; la variante `AMETLLER_BROWSER_TESTS=1` requiere el extra
browser y Chromium y prueba los formularios con datos ficticios, sin una cuenta.
El smoke test consulta la tienda y usa una cesta local
aislada que elimina al terminar; no opera una cuenta ni una cesta remota.
La evidencia de la última ejecución está en [docs/verification.json](docs/verification.json).
La prueba de promociones verifica la colección completa, filtro Club, paginación,
búsqueda, lotes en catalán y fichas originales. Sólo consulta; `--account` añade
una lectura autenticada sin modificar la cesta. Evidencia en
[docs/promotions-verification.json](docs/promotions-verification.json).

Con autorización para crear y eliminar una cesta de invitado aislada:

```bash
python3 scripts/smoke_remote.py
```

La prueba remota comprueba creación con líneas, actualización, sincronización de
lotes, cobertura postal, métodos, eliminación de líneas y limpieza final. No
carga la cuenta del usuario ni envía pedidos. Su evidencia está en
[docs/remote-verification.json](docs/remote-verification.json). Si falla la limpieza,
conserva el estado privado temporal para poder recuperar esa cesta.

La prueba registrada y la comprobación visual API/web están documentadas sin
identificadores, credenciales ni perfil en
[docs/registered-verification.json](docs/registered-verification.json).

La ampliación de login sin HAR y recogida se documenta en
[docs/login-delivery-verification.json](docs/login-delivery-verification.json).
La prueba confirmó tienda y franja en la cesta, renovó la sesión y comprobó que
el checkout seguía reconociendo la misma cuenta. La cesta temporal se eliminó;
no se enviaron pedidos ni pagos. Los tests locales cubren, entre otros casos,
identidad cruzada, franjas desaparecidas y escrituras con respuesta perdida.

Con permiso para una cesta temporal de cuenta (se detiene si ya existe una):

```bash
python scripts/smoke_checkout.py
python scripts/smoke_checkout.py --details ~/.ametller/checkout-details.json
python scripts/smoke_checkout.py --details ~/.ametller/checkout-details.json --review-address
```

La segunda variante envía contacto/domicilio reales; ambas eligen una franja de
prueba, validan el checkout anterior al pago, comprueban que el historial de pedidos
no cambia y eliminan la cesta temporal por ID. No se usan tarjetas ni se compra.
La evidencia no contiene dirección, email, teléfono ni identificadores de cuenta.
Si cambian las cantidades durante la prueba, se conserva la cesta para revisión.
Consulta [docs/checkout-test-verification.json](docs/checkout-test-verification.json).

Fuentes técnicas: [tienda de Ametller](https://ametllerorigen.com/es/online),
sus datos públicos `mobify-data` y bundles JavaScript, y
[flujo de invitado PKCE de Salesforce](https://developer.salesforce.com/docs/commerce/b2c-commerce/guide/slas-public-client.html).
La sincronización de sesiones se apoya en el comportamiento de Hybrid Auth de
la tienda y la [guía de Salesforce](https://developer.salesforce.com/docs/commerce/commerce-api/guide/slas-session-bridge-overview.html).
El navegador opcional utiliza [Playwright](https://playwright.dev/python/docs/library).
La distinción entre entorno de prueba y cobro real sigue la
[documentación de pruebas de Adyen](https://docs.adyen.com/development-resources/test-cards-and-credentials/).
Verificado inicialmente el 11 de octubre de 2026.
