import unittest
from realized_statistics import project

def order(side, qty, price, at, ident, **extra):
    return {'id':ident, 'side':side, 'status':'FILLED', 'filledQuantity':qty, 'filledAveragePrice':price,
            'createdAt':at, 'filledAt':at, 'scope':'ROOT', 'collectionId':None,
            'asset':{'ticker':'ABC','name':'Company ABC','currency':'USD'}, **extra}

class StatisticsTest(unittest.TestCase):
    def setUp(self):
        self.buy=order('BUY','2','10','2026-01-01T00:00:00Z','b')
        self.sell=order('SELL','2','12','2026-01-02T00:00:00Z','s')
    def test_direct_pair_is_indicative_not_a_dated_fill(self):
        result=project([self.buy,self.sell]);row=result['items'][0]
        self.assertEqual(row['gross'],'4');self.assertEqual(row['quality'],'indicative')
        self.assertEqual((row['buy_origin'],row['sell_origin']),('unknown','unknown'))
        self.assertIsNone(row['sell_time']);self.assertFalse(result['history_complete'])
    def test_direct_partial_sales_count_only_sold_quantity(self):
        first=order('SELL','0.5','12','2026-01-02T00:00:00Z','s1')
        second=order('SELL','1','8','2026-01-03T00:00:00Z','s2')
        result=project([self.buy,first,second]);self.assertEqual([row['gross'] for row in result['items']],['1.0','-2'])
        summary=result['summary_by_currency']['USD']
        self.assertEqual((summary['sales'],summary['wins'],summary['losses'],summary['flat']),(2,1,1,0))
        self.assertEqual(summary['gains'],'1.0');self.assertEqual(summary['losses_total'],'-2');self.assertEqual(summary['gross_total'],'-1.0');self.assertEqual(summary['win_rate_percent'],'50.0')
        self.assertTrue(all(row['sell_time'] is None for row in result['items']))
    def test_sales_exceeding_one_buy_are_not_falsely_matched(self):
        extra=order('SELL','1','8','2026-01-03T00:00:00Z','s2')
        self.assertEqual(project([self.buy,self.sell,extra])['items'],[])
    def test_two_partial_sales_leave_remaining_holding_out_of_totals(self):
        buy=order('BUY','10','10','2026-01-01T00:00:00Z','b')
        first=order('SELL','4','12','2026-01-02T00:00:00Z','s1')
        second=order('SELL','2','8','2026-01-03T00:00:00Z','s2')
        result=project([buy,first,second]);rows=result['items'];summary=result['summary_by_currency']['USD']
        self.assertEqual([(r['quantity'],r['gross']) for r in rows],[('4','8'),('2','-4')])
        self.assertEqual((summary['sales'],summary['gains'],summary['losses_total'],summary['gross_total']),(2,'8','-4','4'))
    def test_zero_result_is_in_winner_denominator(self):
        flat=order('SELL','1','10','2026-01-02T00:00:00Z','s1')
        gain=order('SELL','1','12','2026-01-03T00:00:00Z','s2')
        summary=project([self.buy,flat,gain])['summary_by_currency']['USD']
        self.assertEqual((summary['sales'],summary['wins'],summary['flat']),(2,1,1));self.assertEqual(summary['win_rate_percent'],'50.0')
    def test_currencies_never_combined_into_dkk(self):
        euro_buy=order('BUY','1','10','2026-01-01T00:00:00Z','eb',asset={'ticker':'EUR','name':'Euro','currency':'EUR'})
        euro_sell=order('SELL','1','12','2026-01-02T00:00:00Z','es',asset={'ticker':'EUR','name':'Euro','currency':'EUR'})
        result=project([self.buy,self.sell,euro_buy,euro_sell]);self.assertEqual(set(result['summary_by_currency']),{'USD','EUR'});self.assertNotIn('DKK',result['summary_by_currency'])
        self.assertTrue(all(row['gross_dkk'] is None and row['net_dkk'] is None and row['fees_status']=='unknown' for row in result['items']))
    def test_dkk_trade_shows_gross_but_not_guessed_net(self):
        asset={'ticker':'DK','name':'Danish company','currency':'DKK'}
        buy=order('BUY','1','10','2026-01-01T00:00:00Z','b',asset=asset)
        sell=order('SELL','1','12','2026-01-02T00:00:00Z','s',asset=asset)
        row=project([buy,sell])['items'][0]
        self.assertEqual(row['gross_dkk'],'2');self.assertIsNone(row['net_dkk']);self.assertEqual(row['fees_status'],'unknown')
    def test_small_values_use_fixed_decimal_notation(self):
        for buy_price,sell_price,expected in [('0.1','0.2','0.000000001'),('0.2','0.1','-0.000000001'),('0.1','0.1','0.000000000')]:
            buy=order('BUY','0.00000001',buy_price,'2026-01-01T00:00:00Z','b')
            sell=order('SELL','0.00000001',sell_price,'2026-01-02T00:00:00Z','s')
            row=project([buy,sell])['items'][0]
            self.assertEqual(row['gross'],expected)
            for key in ['quantity','gross','gross_percent','buy_price','sell_price']:
                self.assertNotIn('E',row[key].upper())
    def test_partial_lots_fifo_collection(self):
        b2=order('BUY','2','14','2026-01-02T00:00:00Z','b2')
        sale=order('SELL','3','15','2026-01-03T00:00:00Z','s')
        result=project([], [('c',self.buy),('c',b2),('c',sale)])['items'][0]
        self.assertEqual(result['gross'],'11');self.assertEqual(result['buy_price'],str(__import__('decimal').Decimal(34)/3))
    def test_popup_amounts_use_sold_quantity_for_partial_sales(self):
        buy=order('BUY','10','10','2026-01-01T00:00:00Z','b')
        first=order('SELL','4','12','2026-01-02T00:00:00Z','s1')
        second=order('SELL','2','8','2026-01-03T00:00:00Z','s2')
        rows=project([buy,first,second])['items']
        self.assertEqual([(r['cost_basis'],r['sale_proceeds'],r['buy_price'],r['gross']) for r in rows],
                         [('40','48','10','8'),('20','16','10','-4')])
    def test_popup_collection_weighted_price_and_actual_lot_totals(self):
        b2=order('BUY','2','14','2026-01-02T00:00:00Z','b2')
        sale=order('SELL','3','15','2026-01-03T00:00:00Z','s')
        row=project([], [('c',self.buy),('c',b2),('c',sale)])['items'][0]
        self.assertEqual((row['cost_basis'],row['sale_proceeds'],row['gross']),('34','45','11'))
        self.assertEqual(row['buy_price'],str(__import__('decimal').Decimal(34)/3))
    def test_high_precision_fractional_direct_amounts_and_summary(self):
        from decimal import Decimal, localcontext
        qty='123456789.123456789'
        buy=order('BUY',qty,'0.000012345678912345','2026-01-01T00:00:00Z','b')
        sell=order('SELL',qty,'0.000012345678912346','2026-01-02T00:00:00Z','s')
        result=project([buy,sell]); row=result['items'][0]
        with localcontext() as ctx:
            ctx.prec=150
            basis=Decimal(qty)*Decimal(buy['filledAveragePrice'])
            proceeds=Decimal(qty)*Decimal(sell['filledAveragePrice'])
            self.assertEqual(Decimal(row['cost_basis']),basis)
            self.assertEqual(Decimal(row['sale_proceeds']),proceeds)
            self.assertEqual(Decimal(row['gross']),proceeds-basis)
            self.assertEqual(Decimal(result['summary_by_currency']['USD']['gross_total']),proceeds-basis)
        self.assertEqual(row['gross'],'0.000000000123456789123456789')
    def test_high_precision_collection_fifo_and_summary(self):
        from decimal import Decimal, localcontext
        b1=order('BUY','123456789.123456789','0.000012345678912345','2026-01-01T00:00:00Z','b1')
        b2=order('BUY','0.123456789123456789','0.000012345678912344','2026-01-02T00:00:00Z','b2')
        s=order('SELL','123456789.223456789','0.000012345678912346','2026-01-03T00:00:00Z','s')
        result=project([], [('c',b1),('c',b2),('c',s)])
        with localcontext() as ctx:
            ctx.prec=150
            basis=Decimal(b1['filledQuantity'])*Decimal(b1['filledAveragePrice'])+Decimal('0.1')*Decimal(b2['filledAveragePrice'])
            proceeds=Decimal(s['filledQuantity'])*Decimal(s['filledAveragePrice'])
            row=result['items'][0]
            self.assertEqual(Decimal(row['cost_basis']),basis)
            self.assertEqual(Decimal(row['sale_proceeds']),proceeds)
            self.assertEqual(Decimal(row['gross']),proceeds-basis)
            self.assertEqual(Decimal(result['summary_by_currency']['USD']['gross_total']),proceeds-basis)
    def test_projection_keeps_callers_decimal_context(self):
        from decimal import getcontext, localcontext
        with localcontext() as ctx:
            ctx.prec=9
            project([self.buy,self.sell])
            self.assertEqual(getcontext().prec,9)
    def test_summary_preserves_small_profit_beside_large_profit(self):
        from decimal import Decimal, localcontext
        big_buy=order('BUY','1','1','2026-01-01T00:00:00Z','b1')
        big_sell=order('SELL','1','100000000000000000000000000001','2026-01-02T00:00:00Z','s1')
        asset={'ticker':'SMALL','name':'Small','currency':'USD'}
        small_buy=order('BUY','0.000000000000000000000000000001','1','2026-01-01T00:00:00Z','b2',asset=asset)
        small_sell=order('SELL','0.000000000000000000000000000001','2','2026-01-02T00:00:00Z','s2',asset=asset)
        result=project([big_buy,big_sell,small_buy,small_sell])
        with localcontext() as ctx:
            ctx.prec=150
            self.assertEqual(Decimal(result['summary_by_currency']['USD']['gross_total']),
                             Decimal('100000000000000000000000000000')+Decimal('0.000000000000000000000000000001'))
    def test_missing_buy_is_not_profit(self):
        self.assertEqual(project([self.sell])['items'],[])
        self.assertEqual(project([], [('c',self.sell)])['items'],[])
    def test_collection_never_matches_direct(self):
        self.assertEqual(project([self.buy], [('c',self.sell)])['items'],[])
    def test_cancelled_without_fill_ignored(self):
        canceled=dict(self.sell,status='CANCELED',filledQuantity='0')
        self.assertEqual(project([self.buy,canceled])['items'],[])
    def test_cancelled_with_positive_filled_quantity_can_be_compared(self):
        partial=dict(self.sell,status='CANCELED')
        self.assertEqual(project([self.buy,partial])['items'][0]['gross'],'4')
    def test_collection_same_timestamp_does_not_guess_order(self):
        simultaneous=dict(self.sell,filledAt=self.buy['filledAt'])
        self.assertEqual(project([], [('c',self.buy),('c',simultaneous)])['items'],[])
    def test_missing_price_does_not_create_result(self):
        self.assertEqual(project([self.buy,dict(self.sell,filledAveragePrice=None)])['items'],[])
    def test_missing_fill_price_taints_later_pair_in_both_scopes(self):
        incomplete=order('BUY','1','7','2025-12-31T00:00:00Z','missing',filledAveragePrice=None)
        self.assertEqual(project([incomplete,self.buy,self.sell])['items'],[])
        self.assertEqual(project([], [('c',incomplete),('c',self.buy),('c',self.sell)])['items'],[])
    def test_conflicting_earlier_duplicate_taints_later_pair(self):
        earlier=order('BUY','1','7','2025-12-31T00:00:00Z','old')
        conflict=dict(earlier,filledAveragePrice='8')
        self.assertEqual(project([earlier,conflict,self.buy,self.sell])['items'],[])
        self.assertEqual(project([], [('c',earlier),('c',conflict),('c',self.buy),('c',self.sell)])['items'],[])
    def test_taint_does_not_leak_between_scopes(self):
        incomplete=order('BUY','1','7','2025-12-31T00:00:00Z','old',filledAveragePrice=None)
        result=project([incomplete], [('c',self.buy),('c',self.sell)])
        self.assertEqual(len(result['items']),1)
    def test_unknown_scope_taints_only_its_instrument(self):
        unknown=dict(self.buy,id='unknown',scope=None)
        self.assertEqual(project([unknown,self.buy,self.sell])['items'],[])
    def test_identity_disagreement_cannot_leave_a_later_pair(self):
        old=dict(self.buy,id='old',asset={'ticker':'ABC','name':'Other company','currency':'USD'})
        self.assertEqual(project([old,self.buy,self.sell])['items'],[])
    def test_ambiguous_direct_does_not_invent_fill_order(self):
        extra=order('BUY','1','8','2026-01-01T01:00:00Z','x')
        self.assertEqual(project([self.buy,extra,self.sell])['items'],[])
    def test_duplicate_or_conflicting_orders(self):
        self.assertEqual(len(project([self.buy,self.buy,self.sell])['items']),1)
        conflict=dict(self.buy,filledAveragePrice='9')
        self.assertEqual(project([self.buy,conflict,self.sell])['items'],[])
    def test_currency_or_asset_mismatch(self):
        sale=dict(self.sell,asset={'ticker':'ABC','name':'Company ABC','currency':'EUR'})
        self.assertEqual(project([self.buy,sale])['items'],[])
    def test_missing_time_and_empty(self):
        self.assertEqual(project([dict(self.buy,createdAt=None),self.sell])['items'],[])
        self.assertEqual(project([])['items'],[])

if __name__=='__main__': unittest.main()

class ReaderTest(unittest.TestCase):
    def test_read_is_scoped_and_only_calls_read_tools(self):
        import sqlite3
        from contextlib import contextmanager
        from unittest.mock import patch
        from realized_statistics import read
        db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row
        db.execute('CREATE TABLE portfolios(user_id INTEGER,external_id TEXT,kind TEXT,parent_external_id TEXT,source TEXT,active INTEGER,id INTEGER,name TEXT)')
        db.executemany('INSERT INTO portfolios VALUES(?,?,?,?,?,?,?,?)', [(1,'portfolios:mine','portfolio',None,'pluto',1,10,'Mine'),(2,'portfolios:other','portfolio',None,'pluto',1,20,'Other'),(1,'collections:col','collection','portfolios:mine','pluto',1,30,'Col')])
        @contextmanager
        def connect(): yield db
        class Client:
            def __init__(self, token): self.calls=[]; clients.append(self)
            def tools(self):
                return [{'name':name,'annotations':{'readOnlyHint':True},'inputSchema':{'type':'object','properties':{key:{'type':'string'}},'required':[key]}} for name,key in [('list_orders','portfolioId'),('get_collection_activity','collectionId')]]
            def request(self,method,params):
                self.calls.append(params)
                if params['name']=='list_orders': return {'structuredContent':{'orders':[order('BUY','1','10','2026-01-01T00:00:00Z','b'),order('SELL','1','11','2026-01-02T00:00:00Z','s')]}}
                return {'structuredContent':{'activities':[],'nextToken':None}}
        clients=[]
        with patch('oauth.access_token',return_value='test'):
            result=read(connect,1,Client)
        self.assertEqual(len(result['portfolios']),2)
        self.assertEqual(result['portfolios'][0]['portfolio_id'],10)
        self.assertEqual(result['portfolios'][0]['items'][0]['gross'],'1')
        self.assertEqual({x['name'] for x in clients[0].calls},{'list_orders','get_collection_activity'})
        self.assertEqual(clients[0].calls[0]['arguments']['portfolioId'],'mine')
        self.assertFalse(result['history_complete'])
    def test_bad_collection_pagination_is_not_silently_accepted(self):
        import sqlite3
        from contextlib import contextmanager
        from unittest.mock import patch
        from realized_statistics import read
        db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row
        db.execute('CREATE TABLE portfolios(user_id INTEGER,external_id TEXT,kind TEXT,parent_external_id TEXT,source TEXT,active INTEGER,id INTEGER,name TEXT)')
        db.execute("INSERT INTO portfolios VALUES(1,'collections:c','collection',NULL,'pluto',1,30,'Col')")
        @contextmanager
        def connect(): yield db
        class Client:
            def __init__(self, token): pass
            def tools(self): return [{'name':'get_collection_activity','annotations':{'readOnlyHint':True},'inputSchema':{'type':'object','properties':{'collectionId':{'type':'string'}},'required':['collectionId']}}]
            def request(self,method,params): return {'structuredContent':{'activities':[],'nextToken':'same'}}
        with patch('oauth.access_token',return_value='test'):
            result=read(connect,1,Client)
        self.assertEqual(result['portfolios'],[]);self.assertTrue(result['errors'])

class HttpTest(unittest.TestCase):
    def test_endpoint_requires_session_and_uses_authenticated_user(self):
        import io, json, tempfile
        from unittest.mock import patch
        import app, passenger_wsgi, realized_statistics
        with tempfile.TemporaryDirectory() as directory, patch.object(app,'DB',directory+'/test.sqlite'):
            app.init();app.create_user('statistics-test-password')
            def request(path,data=None,cookie=''):
                body=json.dumps(data).encode() if data else b'';headers=[]
                response=b''.join(passenger_wsgi.application({'PATH_INFO':path,'REQUEST_METHOD':'POST' if data else 'GET','REMOTE_ADDR':'test','CONTENT_LENGTH':str(len(body)),'wsgi.input':io.BytesIO(body),'HTTP_COOKIE':cookie},lambda status,h:headers.extend([status,h])))
                return headers,json.loads(response)
            self.assertTrue(request('/api/realized-statistics')[0][0].startswith('401'))
            headers,_=request('/api/login',{'password':'statistics-test-password'})
            cookie=next(v for k,v in headers[1] if k=='Set-Cookie').split(';')[0]
            with patch.object(realized_statistics,'read',return_value={'portfolios':[],'history_complete':False}) as reader:
                response,body=request('/api/realized-statistics',cookie=cookie)
            self.assertTrue(response[0].startswith('200'));self.assertFalse(body['history_complete'])
            self.assertEqual(reader.call_args.args[1],1)

