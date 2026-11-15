import unittest
from decimal import Decimal
from realized_statistics import project


def order(ticker, side, price, currency='USD'):
    return {'id': ticker + side, 'side': side, 'status': 'FILLED', 'filledQuantity': '2',
            'filledAveragePrice': price, 'createdAt': '2026-01-01T00:00:00Z' if side == 'BUY' else '2026-01-02T00:00:00Z',
            'scope': 'ROOT', 'collectionId': None, 'asset': {'ticker': ticker, 'name': ticker, 'currency': currency}}

class MissingCostTests(unittest.TestCase):
    def test_unmatched_sale_is_visible_but_excluded_from_results(self):
        orders = [order('MISSING','SELL','12')]
        for i in range(10):
            currency = 'EUR' if i == 0 else 'USD'
            orders.extend([order(str(i),'BUY','10',currency), order(str(i),'SELL','12' if i < 6 else '8',currency)])
        result = project(orders)
        self.assertEqual(len(result['items']), 10)
        self.assertEqual(result['summary_by_currency']['USD']['sales'], 9)
        self.assertEqual(result['summary_by_currency']['USD']['gross_total'], '4')
        self.assertEqual(result['summary_by_currency']['EUR']['gross_total'], '4')
        self.assertEqual(result['unresolved_sales'][0]['ticker'], 'MISSING')
        self.assertEqual(result['unresolved_sales'][0]['sale_proceeds'], '24')
        self.assertNotIn('gross', result['unresolved_sales'][0])
        self.assertEqual(result['unresolved_sales'][0]['sell_origin'], 'unknown')

    def test_lufthansa_percentage_and_amount(self):
        buy = order('LHA','BUY','7.714','EUR'); sell = order('LHA','SELL','8.75','EUR')
        buy['filledQuantity'] = sell['filledQuantity'] = '3.46253565'
        result = project([buy,sell])['items'][0]
        self.assertEqual(Decimal(result['gross']).quantize(Decimal('.01')), Decimal('3.59'))
        self.assertEqual(Decimal(result['gross_percent']).quantize(Decimal('.01')), Decimal('13.43'))

class DuplicatesAndScopes(unittest.TestCase):
    def test_duplicate_and_cancelled_orders(self):
        sale=order('UNKNOWN','SELL','12')
        self.assertEqual(len(project([sale,dict(sale)])['unresolved_sales']),1)
        conflict=dict(sale,filledAveragePrice='13')
        self.assertEqual(project([sale,conflict])['unresolved_sales'],[])
        cancelled=dict(sale,status='CANCELED',filledQuantity='0')
        self.assertEqual(project([cancelled])['unresolved_sales'],[])
        partial=dict(sale,status='CANCELED',filledQuantity='0.5')
        self.assertEqual(project([partial])['unresolved_sales'][0]['quantity'],'0.5')
    def test_separate_collection_and_direct(self):
        direct=order('A','SELL','12')
        buy=order('A','BUY','10'); sale=dict(order('A','SELL','12'),id='collection-sale')
        buy['filledAt']='2026-01-01T00:00:00Z';sale['filledAt']='2026-01-02T00:00:00Z'
        result=project([direct],[('c1',buy),('c1',sale)])
        self.assertEqual(result['unresolved_sales'][0]['ticker'],'A')
        self.assertEqual(result['items'][0]['scope'],'collection:c1')

class UnresolvedOrigin(unittest.TestCase):
    def test_verified_sale_source_survives_missing_cost(self):
        sale=order('KNOWN','SELL','12')
        sale['asset']['id']='asset-1'
        row=project([sale],signal_order_sides={sale['id']:('SELL','asset-1')})['unresolved_sales'][0]
        self.assertEqual(row['sell_origin'],'signal')
        self.assertEqual(row['buy_origin'],'unknown')
        self.assertNotIn('gross',row)
