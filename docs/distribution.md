# Distribución

Repositorio público: https://github.com/andreu-alegre/ametller-cli.
La instalación desde GitHub no requiere cuenta. El paquete todavía no se publica
en PyPI.
La release pública es 0.6.0. Cupones (0.7) y checkout manual (0.8) están en ramas
de desarrollo; hasta su publicación requieren instalar el checkout correspondiente.

## Instalar una versión

Desde Git:

```bash
uv tool install 'ametller-cli[browser,mcp] @ git+https://github.com/andreu-alegre/ametller-cli@v0.6.0'
uv tool run --from 'ametller-cli[browser,mcp] @ git+https://github.com/andreu-alegre/ametller-cli@v0.6.0' playwright install chromium
ametller capabilities --json
ametller login
```

Para instalar sólo el catálogo y las cestas, omite `[browser,mcp]`. `uv tool run`
utiliza el entorno de la herramienta ya instalada si la petición coincide.
El login también admite Chrome o Edge instalados con `ametller login --browser chrome`.

Alternativa sin uv, después de clonar el repositorio:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install '.[browser,mcp]'
python -m playwright install chromium
ametller capabilities --json
```

Las releases contienen wheel y sdist, además de `SHA256SUMS`. Para usar el wheel
descargado, instala ese archivo en un entorno virtual. Cada instalación guarda
su sesión fuera del repositorio; no distribuyas tu `~/.ametller`.

## Datos y credenciales

El código distribuido no incluye una cuenta de Ametller compartida. Cada usuario
conecta la suya mediante `ametller login`. Tokens, cookies y borradores personales
se guardan en su máquina, fuera del repositorio, con permisos privados.
No se guarda la contraseña ni se envían sesiones a un servidor de este proyecto.
Los cupones usan otra sesión, conectada con `club login` en un terminal interactivo
o `club login --form` en un formulario local. No necesita proxy, certificado ni HAR.
Se guarda en `club-account.json`, fuera del repositorio, sin cookies ni contraseña;
no se distribuye con el paquete. No tiene renovación automática. La importación
de una captura propia sigue disponible como alternativa avanzada.

Antes de abrir el repositorio se revisaron todos los objetos del historial Git,
los paquetes de la release `v0.6.0` y sus sumas. No se encontraron credenciales ni
valores privados de la cuenta utilizada para las pruebas. Esta revisión de
publicación no certifica que el software esté libre de vulnerabilidades.

## Agentes

Agentes con terminal pueden utilizar `ametller ... --json` y cargar
[la skill](../skills/ametller/SKILL.md). Copia el directorio `skills/ametller`
al directorio de skills admitido por tu agente, conservando `SKILL.md`.

Para clientes MCP, instala el extra `mcp` y configura el proceso local:

```json
{
  "mcpServers": {
    "ametller": {
      "command": "ametller-mcp",
      "args": []
    }
  }
}
```

Si el cliente no hereda el PATH del terminal, utiliza la ruta absoluta al ejecutable
de tu instalación. CLI y MCP usan `~/.ametller` por defecto. `--state-dir` y
`--lang` permiten configurar el proceso; conecta la cuenta con el mismo directorio.
La estructura de configuración concreta depende del cliente MCP.

El MCP se inicia con herramientas de lectura. Para preparar también cambios de
cesta o activar un cupón autorizado, añade `--allow-writes` a `args`. Cada escritura exige `confirmed=true`
tras autorización del usuario y las operaciones de producto exigen `max_eur`.
Estos controles corresponden al MCP; la CLI conserva sus opciones originales.

Herramientas de lectura: `capabilities`, `search_products`, `get_product`,
`list_promotions`, `list_personal_coupons`, `get_mobile_club_status`, `preview_coupon_activation`,
`get_categories`, `get_account_status`, `get_local_cart`,
`prepare_local_checkout`, `get_remote_cart`, `list_remote_carts`,
`preview_cart_sync`, `get_stores`, `get_delivery_status`, `get_shipping_methods`.
Con escrituras: `set_local_cart_item`, `set_remote_cart_item`, `apply_cart_sync`,
`clear_local_cart`, `activate_personal_coupon`. Las herramientas de cuenta no exponen cookies ni tokens;
la cesta y la entrega pueden incluir datos privados. No hay login interactivo,
desactivación de cupones ni controladores de pago/pedido en MCP. Los cupones se
leen con la sesión móvil privada, sin devolver códigos de canje en la salida normal.

La preparación de domicilio y recogida sigue disponible desde la CLI. Se evita
exponer como lecturas MCP los cálculos web que pueden alterar la entrega.
`checkout open --max <importe>` también se usa sólo desde la CLI, por ser un flujo
interactivo que espera al cierre del navegador. El modo normal permite al usuario
pagar manualmente en Ametller; `--review-only` permite probar sin enviar escrituras.

## Versionar y publicar

Antes de subir una versión:

1. Actualiza la versión en `pyproject.toml`, `ametller/__init__.py` y el changelog.
2. Ejecuta los tests, `scripts/check_publication.py`, `python -m build`,
   `python -m twine check dist/*` y `scripts/check_install.py` sobre el wheel nuevo.
3. Revisa los archivos a subir, también las imágenes y evidencias, y crea un tag `vX.Y.Z`.
4. La CI valida macOS/Linux, Python 3.10/3.12/3.14 y formularios locales; después
   adjunta wheel, sdist y sumas a un prerelease de GitHub para el tag.

La CI no inicia sesión en Ametller ni ejecuta pruebas remotas con escrituras.
Las pruebas de integración con cuenta requieren autorización propia y no forman
parte de la publicación. La publicación en PyPI sigue pendiente y este workflow
no la ejecuta.
