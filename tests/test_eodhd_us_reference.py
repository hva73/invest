import io,json,os,unittest
import socket,ssl,urllib.error,http.client
from unittest.mock import patch
from eodhd_us_reference import get_reference,parse_reference,ReferenceUnavailable

class USReference(unittest.TestCase):
 def test_network_errors_are_classified_without_leaking_provider_details(self):
  from eodhd_us_reference import network_error_code
  cases=[(TimeoutError('secret-token'),'EODHD_US_REFERENCE_TIMEOUT'),(urllib.error.URLError(socket.gaierror('secret-token')),'EODHD_US_REFERENCE_DNS_ERROR'),(ssl.SSLError('secret-token'),'EODHD_US_REFERENCE_TLS_ERROR'),(http.client.IncompleteRead(b'secret-token'),'EODHD_US_REFERENCE_INCOMPLETE'),(urllib.error.URLError('secret-token'),'EODHD_US_REFERENCE_NETWORK_ERROR')]
  for error,expected in cases:
   with self.subTest(expected=expected):
    self.assertEqual(network_error_code(error),expected)
    self.assertNotIn('secret',network_error_code(error))

 def rows(self):
  return [{'Code':'TSM','Name':'Taiwan Semiconductor Manufacturing','Country':'USA','Exchange':'NYSE','Currency':'USD','Type':'Common Stock','Isin':'US8740391003'}, {'Code':'TSLA','Name':'Tesla Inc','Country':'USA','Exchange':'NASDAQ','Currency':'USD','Type':'Common Stock','Isin':'US88160R1014'}]
 def test_observed_us_catalog_rows_and_invalid_schema(self):
  result=parse_reference(json.dumps(self.rows()).encode(),'2026-11-06T18:35:00+00:00')
  self.assertEqual([(row['Code'],row['Exchange'],row['Isin']) for row in result['rows']],[('TSM','NYSE','US8740391003'),('TSLA','NASDAQ','US88160R1014')])
  with self.assertRaises(ReferenceUnavailable):parse_reference(b'{"error":"not entitled"}','2026-11-06T18:35:00+00:00')
 def test_provider_uses_budget_and_does_not_expose_api_key(self):
  class Response:
   def __init__(self):self.buf=io.BytesIO(json.dumps(USReference().rows()).encode())
   def __enter__(self):return self
   def __exit__(self,*args):return False
   def read(self,size):return self.buf.read(min(size,7))
  class Opener:
   def open(self,*args,**kwargs):return Response()
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'SYNTHETIC-SECRET'}),patch('hotwatch_adapters.reserve') as budget:
   result=get_reference(None,1,opener=Opener())
  self.assertEqual(budget.call_count,1);self.assertNotIn('SYNTHETIC-SECRET',str(result));self.assertEqual(len(result['rows']),2)
 def test_incomplete_and_malformed_catalogues_fail_closed(self):
  payload=json.dumps(self.rows()).encode()
  for raw in (payload[:-1],payload+b'garbage',payload[:-1]+b',]'):
   with self.subTest(raw=raw[-10:]):
    with self.assertRaises(ReferenceUnavailable):parse_reference(raw,'2026-11-06T18:35:00+00:00')
