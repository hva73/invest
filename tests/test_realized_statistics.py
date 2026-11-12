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
        self.assertIsNone(row['sell_time']);self.assertFalse(result['history_complete'])
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
