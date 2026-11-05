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
 def test_key_whitespace_is_removed_before_request(self):
  from urllib.parse import urlsplit,parse_qs
  class Capture:
   def open(self,request,**kw):
    self.token=parse_qs(urlsplit(request.full_url).query)['api_token'][0]
    return Response()
  opener=Capture()
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'  TEST-SECRET\n'}),patch('market_data.candidate',return_value={'ticker':'AMD'}),patch.object(adapter,'reserve'):
   result=adapter.search_eodhd_symbols(None,1,{'candidate_id':'c'},opener)
  self.assertEqual(opener.token,'TEST-SECRET');self.assertNotIn('TEST-SECRET',str(result))
 def test_share_class_suffix_search_does_not_offer_a_different_class(self):
  from urllib.parse import urlsplit,unquote
  class Reply:
   def __init__(self,rows):self.rows=rows
   def __enter__(self):return self
   def __exit__(self,*args):return False
   def read(self,size):return json.dumps(self.rows).encode()
  class ClassAlias:
   def __init__(self):self.paths=[]
   def open(self,request,**kw):
    self.paths.append(unquote(urlsplit(request.full_url).path))
    return Reply([] if len(self.paths)==1 else [{'Code':'TEST-B','Exchange':'CO','Name':'Synthetic B','Currency':'DKK'},{'Code':'TEST-A','Exchange':'CO','Name':'Synthetic A','Currency':'DKK'}])
  client=ClassAlias()
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'TEST-SECRET'}),patch('market_data.candidate',return_value={'ticker':'TESTB','company_name':'A.P. Synthetic A/S B'}),patch.object(adapter,'reserve'):
   result=adapter.search_eodhd_symbols(None,1,{'candidate_id':'c','quote_currency':'DKK'},client)
  self.assertEqual(client.paths,['/api/search/TESTB','/api/search/TEST-B']);self.assertEqual([v['symbol'] for v in result['choices']],['TEST-B.CO'])
 def test_alias_lookup_requires_exact_issuer_name(self):
  class Reply:
   def __init__(self,body):self.body=body
   def __enter__(self):return self
   def __exit__(self,*args):return False
   def read(self,size):return json.dumps(self.body).encode()
  class AliasOpener:
   def __init__(self):self.calls=0
   def open(self,*a,**kw):
    self.calls+=1
    return Reply([] if self.calls==1 else [{'Code':'NOVO-B','Exchange':'CO','Name':'Novo Nordisk A/S','Currency':'DKK'},{'Code':'OTHER','Exchange':'CO','Name':'Other Co','Currency':'DKK'}])
  opener=AliasOpener()
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'TEST-SECRET'}),patch('market_data.candidate',return_value={'ticker':'NOVOB','company_name':'Novo Nordisk A/S'}),patch.object(adapter,'reserve') as budget:
   result=adapter.search_eodhd_symbols(None,1,{'candidate_id':'c'},opener)
  self.assertEqual([x['symbol'] for x in result['choices']],['NOVO-B.CO']);self.assertEqual(budget.call_count,2)
 def test_observed_novob_ticker_and_issuer_search_shape(self):
  from urllib.parse import unquote,urlsplit
  class Reply:
   def __init__(self,body):self.body=body
   def __enter__(self):return self
   def __exit__(self,*args):return False
   def read(self,size):return json.dumps(self.body).encode()
  class Observed:
   def __init__(self):self.paths=[]
   def open(self,request,**kwargs):
    self.paths.append(unquote(urlsplit(request.full_url).path))
    if len(self.paths)==1:return Reply([{'Code':'NOVOB80','Exchange':'BK','Name':'Novo Nordisk A/S','Currency':'THB'}])
    return Reply([{'Code':'NVO','Exchange':'US','Name':'Novo Nordisk A/S','Currency':'USD'},{'Code':'NOVO-B','Exchange':'CO','Name':'Novo Nordisk A/S','Currency':'DKK'},{'Code':'OTHER','Exchange':'CO','Name':'Different company','Currency':'DKK'}])
  opener=Observed()
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'TEST-ONLY'}),patch('market_data.candidate',return_value={'ticker':'NOVOB','company_name':'Novo Nordisk A/S'}),patch.object(adapter,'reserve'):
   result=adapter.search_eodhd_symbols(None,1,{'candidate_id':'synthetic','quote_currency':'DKK'},opener)
  self.assertEqual(opener.paths,['/api/search/NOVOB','/api/search/Novo Nordisk']);self.assertEqual([v['symbol'] for v in result['choices']],['NVO.US','NOVO-B.CO']);self.assertEqual(result['choices'][1]['currency'],'DKK')
 def test_company_fallback_when_ticker_only_matches_wrong_currency(self):
  from urllib.parse import urlsplit,unquote
  class Reply:
   def __init__(self,body):self.body=body
   def __enter__(self):return self
   def __exit__(self,*args):return False
   def read(self,size):return json.dumps(self.body).encode()
  class DifferentCurrency:
   def __init__(self):self.paths=[]
   def open(self,request,**kw):
    self.paths.append(urlsplit(request.full_url).path)
    if len(self.paths)==1:return Reply([{'Code':'NOVOB','Exchange':'ST','Name':'Novo Nordisk A/S','Currency':'SEK'}])
    return Reply([{'Code':'NOVO-B','Exchange':'CO','Name':'Novo Nordisk A/S','Currency':'DKK'}])
  opener=DifferentCurrency()
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'TEST-SECRET'}),patch('market_data.candidate',return_value={'ticker':'NOVOB','company_name':'Novo Nordisk A/S'}),patch.object(adapter,'reserve') as budget:
   result=adapter.search_eodhd_symbols(None,1,{'candidate_id':'c','quote_currency':'DKK'},opener)
  self.assertEqual([x['symbol'] for x in result['choices']],['NOVOB.ST','NOVO-B.CO']);self.assertEqual(budget.call_count,2)
  self.assertEqual(unquote(opener.paths[1]),'/api/search/Novo Nordisk');self.assertNotIn('%2F',opener.paths[1])
 def test_404_ticker_search_retries_exact_issuer_name(self):
  class Reply:
   def __enter__(self):return self
   def __exit__(self,*args):return False
   def read(self,size):return json.dumps([{'Code':'NOVO-B','Exchange':'CO','Name':'Novo Nordisk A/S','Currency':'DKK'}]).encode()
  class NotFoundThenMatch:
   def __init__(self):self.calls=0
   def open(self,*a,**kw):
    self.calls+=1
    if self.calls==1:raise urllib.error.HTTPError('https://example.invalid/TEST-SECRET',404,'not found',{},None)
    return Reply()
  opener=NotFoundThenMatch()
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'TEST-SECRET'}),patch('market_data.candidate',return_value={'ticker':'NOVOB','company_name':'Novo Nordisk A/S'}),patch.object(adapter,'reserve') as budget:
   result=adapter.search_eodhd_symbols(None,1,{'candidate_id':'c'},opener)
  self.assertEqual([x['symbol'] for x in result['choices']],['NOVO-B.CO']);self.assertEqual(budget.call_count,2)
 def test_missing_search_endpoint_reports_404_without_secret(self):
  class Missing:
   def open(self,*a,**kw):raise urllib.error.HTTPError('https://example.invalid/TEST-SECRET',404,'not found',{},None)
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'TEST-SECRET'}),patch('market_data.candidate',return_value={'ticker':'AMD','company_name':'AMD Inc'}),patch.object(adapter,'reserve') as budget:
   with self.assertRaises(adapter.DataUnavailable) as error:adapter.search_eodhd_symbols(None,1,{'candidate_id':'c'},Missing())
  self.assertEqual(error.exception.code,'EODHD_SEARCH_HTTP_404');self.assertEqual(budget.call_count,2);self.assertNotIn('TEST-SECRET',str(error.exception))
 def test_other_http_error_shows_only_status_not_key(self):
  class Bad:
   def open(self,*a,**kw):raise urllib.error.HTTPError('https://example.invalid/TEST-SECRET',503,'failure',{},None)
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'TEST-SECRET'}),patch('market_data.candidate',return_value={'ticker':'AMD'}),patch.object(adapter,'reserve'):
   with self.assertRaises(adapter.DataUnavailable) as e:adapter.search_eodhd_symbols(None,1,{'candidate_id':'c'},Bad())
  self.assertEqual(e.exception.code,'EODHD_SEARCH_HTTP_503');self.assertNotIn('TEST-SECRET',str(e.exception))
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
  self.assertEqual(e.exception.code,'EODHD_SEARCH_HTTP_403');self.assertNotIn('TEST-SECRET',str(e.exception))
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
