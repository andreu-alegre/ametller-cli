# Entorno propio de pruebas de pago

La fase actual abre el checkout oficial para confirmación humana. No ejecuta
pagos desde la CLI y no certifica procesamiento de pago. La prueba de cuenta usa
el modo de revisión; las pruebas de Chromium utilizan una página ficticia y
peticiones interceptadas, sin alcanzar Ametller.

## Opciones para la siguiente fase

| Entorno | Qué comprobaría | Qué quedaría sin demostrar |
| --- | --- | --- |
| Simulador propio local | Estado de cesta, presupuestos, confirmaciones, rechazos simulados, autenticación bancaria simulada, red interrumpida y prevención de duplicados | Compatibilidad real con la tienda y su proveedor de pago |
| Integración propia con cuenta Adyen de pruebas | Nuestro adaptador con autorizaciones y rechazos de Adyen, tarjetas de prueba y acciones adicionales | Checkout, pedidos y configuración de Ametller |
| Sandbox facilitado por Ametller | Su checkout completo, autenticación, entrega, pago y confirmación de pedidos de prueba | Comportamiento exacto y operaciones de producción |

Un sandbox Salesforce creado por nosotros empieza vacío y necesita permisos,
créditos y configuración del realm. No trae el código, configuración, datos ni
credenciales de Ametller. Recrear una tienda con datos ficticios serviría para
pruebas propias, pero no demostraría equivalencia con su implementación.
[Salesforce: On-Demand Sandboxes](https://developer.salesforce.com/docs/commerce/commerce-solutions/guide/b2c-developer-sandboxes.html).

Adyen ofrece integración de pruebas, pero sus tarjetas de prueba funcionan sólo
en esa plataforma. Una cuenta propia de desarrollo no cambia el entorno del
checkout de Ametller; no deben enviarse tarjetas de prueba a su tienda real.
[Adyen: tarjetas de prueba](https://docs.adyen.com/development-resources/test-cards-and-credentials/test-card-numbers),
[integración SFRA](https://docs.adyen.com/plugins/salesforce-commerce-cloud/sfra/).

## Propuesta para el simulador

Implementar un backend de pruebas independiente, con clientes y productos
ficticios, importes deterministas y ninguna credencial real. El transporte de
pruebas debe quedar separado del de producción y nunca reutilizar su sesión.

Casos mínimos: aprobación y rechazo, acción adicional del banco, cancelación,
caducidad de sesión, cambio de total, doble confirmación, respuesta perdida
después de un pedido aceptado y consulta posterior antes de decidir otro cambio.
El resultado tiene que indicar de forma explícita que es simulado y no acreditar
un pago ni un pedido real. No basta con un mock que siempre responde aprobado.

Esta siguiente fase todavía no está implementada. La habilitación de pagos reales
necesitará verificar el protocolo de Ametller y autorización propia para cada
operación; levantar los bloqueos actuales no constituye esa implementación.
