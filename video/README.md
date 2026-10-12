# Vídeo de ametller-cli

Promo de 12 segundos, 1920 × 1080, 30 fps y sin audio, implementada con Remotion.
Mantiene la portada crema y oliva, con escritura de comandos, aparición progresiva
de resultados y cierre con el enlace al repo. El aviso «CLI no oficial · Demo
ilustrativa» permanece visible.

```bash
cd video
npm ci
npm run studio
npm run typecheck
npm run render
```

El render se guarda en `out/ametller-cli-promo.mp4`. `npm run poster` exporta un
fotograma de la búsqueda. `out/` y `node_modules/` no se versionan.

La terminal es una recreación editorial, no una grabación de una cuenta. La búsqueda
usa los nombres, precios e IDs del catálogo público devueltos por la CLI el
12 de octubre de 2026; los precios no son una oferta actual ni confirman stock.
Los dos cupones e identificadores `demo-01` y `demo-02` son ficticios. No se captura
autenticación, no se activa ningún cupón ni se modifica una cesta. El vídeo no
presenta un pago ni un pedido.

El logo se obtuvo del
[recurso público de Ametller Origen](https://www.ametllerorigen.com/wp-content/uploads/2026/09/ao-organization-logo-512.png).
La marca pertenece a sus titulares; el proyecto es independiente y no oficial.
La licencia MIT del código no concede derechos sobre la marca ni sustituye la
[licencia de Remotion](https://www.remotion.dev/docs/license).

Los componentes dependen únicamente del fotograma de Remotion: sin temporizadores,
red, perfiles de navegador ni archivos de cuenta durante el render. Las fuentes
Inter e IBM Plex Mono se cargan desde los paquetes fijados por el lockfile.
