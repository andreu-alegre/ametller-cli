# ametller-cli

Proyecto independiente, no oficial, en Python 3.10+ para macOS/Linux.

- Ejecutar desde el repo: `./bin/ametller` o `python3 -m ametller`.
- Tests: `python3 -m unittest discover -s tests -v`.
- Distribución: `python scripts/check_publication.py`, `python -m build`,
  `python -m twine check dist/*` y `python scripts/check_install.py <wheel>`.
- La skill distribuible vive en `skills/ametller/SKILL.md`. MCP utiliza
  `ametller.mcpserver` y la misma operación `cli.execute`, sin shell ni rutas HTTP
  arbitrarias. Mantener salida stdio MCP limpia y los extras opcionales.
- MCP no registra escrituras sin `--allow-writes`. Las llamadas de escritura
  requieren `confirmed=true`, con autorización del usuario, y presupuesto para
  cambios de producto. No añadir pagos, pedidos o activación de cupones sin
  implementar y verificar su protocolo y autorización específicos.
- Verificación de catálogo real: `python3 scripts/smoke.py`.
- Mantener las lecturas de catálogo separadas de cualquier futura operación de cuenta.
- `cart` gestiona una cesta local; `remote-cart` gestiona la cesta de cuenta. Conservar
  el alcance real en ayuda, README y JSON. Nunca convertir un fallo de cuenta en invitado.
- No introducir llamadas de compra, pago o modificación de una cuenta real sin
  autorización concreta de Andreu para probar esa operación.
- No guardar HAR, cookies ni credenciales en el repo. Sesiones fuera del repo, con
  permisos privados; no imprimir tokens, contraseñas ni cookies en logs o errores.
- No inferir alérgenos, unidades de venta, stock de una dirección o descuentos de
  cuenta. Conservar los campos desconocidos como `null`.
- Precio de venta y precio por kg/litro son campos distintos. El presupuesto usa
  el primero, aritmética decimal y validación de mínimo/incremento de cantidad.
- Las mutaciones locales deben bloquear, validar todo y guardar atómicamente.
- Las mutaciones remotas no se reintentan. Confirmar por GET; un resultado incierto
  conserva `remote-pending.json` y bloquea cambios hasta reconciliar leyendo la cesta.
- Las operaciones remotas de varios lotes no son atómicas. No afirmar lo contrario.
- No confundir los slots CMS con franjas de entrega. El checkout final usa SFRA y
  necesita verificación propia; no inferir un flujo de pago de los endpoints SCAPI.
- `login` usa un navegador aislado y Playwright opcional. Capturar sólo autenticación
  de Ametller, nunca cuerpos de peticiones de login, contraseñas o un perfil de navegador.
- Comprobar la identidad tanto en SCAPI como en SFRA antes de aplicar entrega.
  Conservar renovaciones de cookies. Algunas escrituras usan GET: no repetirlas.
- Seleccionar una franja en la cesta no certifica una reserva definitiva ni un pedido.
- No publicar en GitHub, PyPI ni npm sin autorización. Revisar sólo las rutas de
  este proyecto; no tocar los proyectos vecinos.
