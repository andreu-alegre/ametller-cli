# Distribución

Repositorio: https://github.com/andreu-alegre/ametller-cli. La preparación inicial
es privada; requiere acceso a GitHub. El paquete todavía no se publica en PyPI.

## Instalar una versión

Desde Git, con la autenticación de Git configurada para acceder al repo privado:

```bash
uv tool install 'ametller-cli[browser,mcp] @ git+https://github.com/andreu-alegre/ametller-cli@v0.6.0'
uv tool run --from 'ametller-cli[browser,mcp] @ git+https://github.com/andreu-alegre/ametller-cli@v0.6.0' playwright install chromium
ametller capabilities --json
ametller login
```

Para instalar sólo el catálogo y las cestas, omite `[browser,mcp]`. `uv tool run`
utiliza el entorno de la herramienta ya instalada si la petición coincide.
El login también admite Chrome o Edge instalados con `ametller login --browser chrome`.

Alternativa sin uv, desde un checkout autorizado:

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
cesta, añade `--allow-writes` a `args`. Cada escritura exige `confirmed=true`
tras autorización del usuario y las operaciones de producto exigen `max_eur`.
Estos controles corresponden al MCP; la CLI conserva sus opciones originales.

Herramientas de lectura: `capabilities`, `search_products`, `get_product`,
`list_promotions`, `get_categories`, `get_account_status`, `get_local_cart`,
`prepare_local_checkout`, `get_remote_cart`, `list_remote_carts`,
`preview_cart_sync`, `get_stores`, `get_delivery_status`, `get_shipping_methods`.
Con escrituras: `set_local_cart_item`, `set_remote_cart_item`, `apply_cart_sync`,
`clear_local_cart`. Las herramientas de cuenta no exponen cookies ni tokens;
la cesta y la entrega pueden incluir datos privados. No hay login interactivo,
cupones personales ni controladores de pago/pedido en MCP.

La preparación de domicilio y recogida sigue disponible desde la CLI. Se evita
exponer como lecturas MCP los cálculos web que pueden alterar la entrega.

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
parte de la publicación. PyPI y el cambio de visibilidad a público son pasos
posteriores; este workflow no los ejecuta.
