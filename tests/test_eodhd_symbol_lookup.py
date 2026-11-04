"""Synthetic EODHD search: identity choices, ownership and secret hygiene."""
import json,os,unittest,urllib.error
from unittest.mock import patch
import hotwatch_adapters as adapter
class Response:
 def __enter__(self):return self
 def __exit__(self,*args):return False
 def read(self,size):return json.dumps([{'Code':'AMD','Exchange':'US','Name':'AMD Inc','Currency':'USD'},{'Code':'AMD','Exchange':'XETRA','Name':'AMD Inc','Currency':'EUR'},{'Code':'AMDX','Exchange':'US','Name':'Other','Currency':'USD'}]).encode()
class Opener:
 def open(self,*args,**kwargs):return Response()
class SymbolLookup(unittest.TestCase):
 def test_symbol_choices_exact_ticker_and_distinct_exchanges(self):
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'TEST-SECRET'}),patch('market_data.candidate',return_value={'ticker':'AMD'}),patch.object(adapter,'reserve'):
   result=adapter.search_eodhd_symbols(None,1,{'candidate_id':'c'},Opener())
  self.assertEqual([x['symbol'] for x in result['choices']],['AMD.US','AMD.XETRA']);self.assertNotIn('TEST-SECRET',str(result))
 def test_candidate_authorization_is_checked_before_network(self):
  class NoNetwork:
   def open(self,*a,**kw):raise AssertionError('Network must not run')
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'TEST-SECRET'}),patch('market_data.candidate',side_effect=ValueError('unauthorized')),patch.object(adapter,'reserve') as budget:
   with self.assertRaises(ValueError):adapter.search_eodhd_symbols(None,2,{'candidate_id':'wrong'},NoNetwork())
   budget.assert_not_called()
 def test_auth_error_does_not_expose_secret_or_url(self):
  class Bad:
   def open(self,*a,**kw):raise urllib.error.HTTPError('https://example.invalid/TEST-SECRET',403,'denied',{},None)
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'TEST-SECRET'}),patch('market_data.candidate',return_value={'ticker':'AMD'}),patch.object(adapter,'reserve'):
   with self.assertRaises(adapter.DataUnavailable) as e:adapter.search_eodhd_symbols(None,1,{'candidate_id':'c'},Bad())
  self.assertEqual(e.exception.code,'EODHD_ENTITLEMENT_REJECTED');self.assertNotIn('TEST-SECRET',str(e.exception))
class SymbolEndpoint(unittest.TestCase):
 def test_auth_and_csrf_required_before_search(self):
  import app,test_app
  old_db=app.DB;case=test_app.Workflow('test_protected_workflow');case.setUp()
  try:
   with patch.object(adapter,'search_eodhd_symbols',return_value={'ticker':'AMD','choices':[]}) as search:
    self.assertEqual(case.request('market/eodhd-symbols',{'candidate_id':'synthetic'})[0],401)
    case.login();self.assertEqual(case.request('market/eodhd-symbols',{'candidate_id':'synthetic'},False)[0],403)
    self.assertEqual(case.request('market/eodhd-symbols',{'candidate_id':'synthetic'})[0],200)
    self.assertEqual(search.call_count,1)
  finally:case.tearDown();app.DB=old_db

if __name__=='__main__':unittest.main()
