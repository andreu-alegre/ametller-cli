"""Cesta temporal registrada y navegador en revisión; ninguna compra o tarjeta.

Sólo con autorización para una cesta de prueba. Se detiene si existe otra cesta.
El navegador bloquea escrituras y el proveedor de pago. Cierra la ventana para
terminar; se comprueba el historial y se limpia únicamente la cesta creada aquí.
"""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ametller import __version__
from ametller.account import AccountClient
from ametller.catalog import timestamp
from ametller.checkoutbrowser import open_checkout
from ametller.remote import RemoteCart, SERVICE, identifier
from ametller.storage import Error, Storage


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--timeout',type=int,default=180)
    args=parser.parse_args()
    storage=Storage(); client=AccountClient(storage=storage); remote=RemoteCart(client,storage)
    def orders():
        result=client.orders(limit=50)
        return result.get('total'),{item.get('orderNo') for item in result.get('data',[])}
    before=orders()
    with storage.lock('remote-cart'):
        remote.pending()
        if remote.get(): raise Error('La cuenta ya tiene una cesta; no se modificará.')
        result=remote.change('add','2351','8','30')
        basket_id=result['basket_id']
    checks=['temporary_basket_created_with_budget']
    report=None
    try:
        report=open_checkout(storage,maximum='30',review_only=True,timeout=args.timeout)
        if not report['review_only'] or report['manual_purchase_possible'] or report['order_submitted'] or report['payment_submitted']:
            raise Error('La prueba dejó de ser de sólo revisión.')
        checks+=['official_browser_opened','browser_account_verified','initial_total_within_budget','review_network_guard_enabled']
        if orders()!=before: raise Error('El historial cambió durante la prueba; revisa Ametller.')
        checks.append('order_history_unchanged')
    finally:
        with storage.lock('remote-cart'):
            basket=remote.read_id(basket_id)
            if remote.quantities(basket)!={'2351':'8'}:
                raise Error('La cesta temporal cambió; se conserva para revisión.')
            storage.write('remote-pending.json',{'customer_id':client.session['customer_id'],
                'basket_id':basket_id,'operation':'browser-review-delete'})
            client.account_api(SERVICE,'baskets/'+identifier(basket_id),method='DELETE')
            if any(item.get('basketId')==basket_id for item in client.baskets().get('baskets',[])):
                raise Error('No se confirmó la limpieza de la cesta temporal.')
            pending=storage.read('remote-pending.json')
            if pending and pending.get('basket_id')==basket_id and pending.get('customer_id')==client.session['customer_id']:
                storage.delete('remote-pending.json')
            checks.append('temporary_basket_deleted')
    evidence={'version':__version__,'verified_at':timestamp(),'scope':'registered_account_review_browser',
              'checks':checks,'passed':len(checks),'prepayment_ready':report['prepayment_ready'],
              'pending_checks':report['pending_checks'],'review_requests_blocked':report['review_requests_blocked'],
              'payment_submitted':False,'order_submitted':False,'payment_processing_verified':False,
              'payment_sandbox_available':None,'sensitive_values_published':False}
    path=Path(__file__).resolve().parents[1]/'docs/checkout-browser-verification.json'
    path.write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(evidence,ensure_ascii=False,indent=2))


if __name__=='__main__':
    try: main()
    except Error as error:
        print(str(error),file=sys.stderr); raise SystemExit(1)
