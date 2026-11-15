import unittest
from contextlib import contextmanager
from unittest.mock import patch
import realized_statistics as statistics

class Diagnostics(unittest.TestCase):
    @contextmanager
    def connect(self):
        class DB:
            def execute(self, *args): return []
        yield DB()

    def test_connection_failure_is_classified_without_exposing_exception(self):
        with patch('oauth.access_token', side_effect=ValueError('secret')):
            with self.assertRaises(statistics.StatisticsUnavailable) as failure:
                statistics.read(self.connect, 1, lambda token: None)
        self.assertEqual(str(failure.exception), 'CONNECTION')
        self.assertNotIn('secret', str(failure.exception))

    def test_catalog_failure_is_distinct(self):
        class Client:
            def tools(self): raise ValueError('private detail')
        with patch('oauth.access_token', return_value='token'):
            with self.assertRaises(statistics.StatisticsUnavailable) as failure:
                statistics.read(self.connect, 1, lambda token: Client())
        self.assertEqual(str(failure.exception), 'CATALOG_RESPONSE')

    def test_catalog_errors_remain_distinct_and_private(self):
        import sqlite3
        from urllib.error import HTTPError, URLError
        budget = RuntimeError('private secret'); budget.code = 'PROVIDER_RATE_BUDGET'
        cases = [(budget,'CATALOG_BUDGET'), (sqlite3.OperationalError('private secret'),'CATALOG_DATABASE'),
                 (HTTPError('https://private',403,'secret',None,None),'CATALOG_DENIED'),
                 (HTTPError('https://private',429,'secret',None,None),'CATALOG_RATE_LIMIT'),
                 (HTTPError('https://private',500,'secret',None,None),'CATALOG_HTTP'),
                 (URLError(TimeoutError('secret')),'CATALOG_TIMEOUT'),
                 (URLError('secret'),'CATALOG_NETWORK'), (ValueError('secret'),'CATALOG_RESPONSE'),
                 (RuntimeError('secret'),'BROKER_CATALOG')]
        for error, category in cases:
            with self.subTest(category=category):
                self.assertEqual(statistics.catalog_error_code(error), category)
                self.assertNotIn('secret', statistics.catalog_error_code(error))

    def test_depot_permission_and_budget_are_distinct_and_sanitized(self):
        class DB:
            def execute(self, *args): return [{'id':1,'name':'Private','external_id':'portfolios:private','kind':'portfolio','parent_external_id':None}]
        @contextmanager
        def connect(): yield DB()
        class Client:
            def __init__(self, allowed): self.allowed=allowed
            def tools(self):
                return [{'name':'list_orders','annotations':{'readOnlyHint':True},'inputSchema':{'type':'object','properties':{'portfolioId':{'type':'string'}}}}] if self.allowed else []
            def request(self, *args):
                error=RuntimeError('private secret'); error.code='PROVIDER_RATE_BUDGET'; raise error
        with patch('oauth.access_token', return_value='token'):
            for allowed, expected in [(False,'DIRECT_PERMISSION'),(True,'PROVIDER_RATE_BUDGET')]:
                with self.subTest(expected=expected):
                    result=statistics.read(connect,1,lambda token:Client(allowed))
                    self.assertEqual(result['error_codes'],[expected])
                    self.assertNotIn('private secret',str(result))

    def test_request_error_types_have_fixed_categories(self):
        from urllib.error import HTTPError, URLError
        from mcp_client import PortfolioFormatError
        guard=RuntimeError('secret'); guard.code='PLUTO_WRITE_OR_UNKNOWN_TOOL_BLOCKED'
        for error, suffix in [(guard,'LOCAL_GUARD'),(HTTPError('https://secret',403,'secret',None,None),'DENIED'),(TimeoutError('secret'),'TIMEOUT'),(URLError('secret'),'NETWORK'),(PortfolioFormatError('secret'),'RESPONSE')]:
            with self.subTest(suffix=suffix):
                result=statistics.depot_error_code('DIRECT_REQUEST',error)
                self.assertEqual(result,'DIRECT_REQUEST_'+suffix)
                self.assertNotIn('secret',result.lower())

    def test_authenticated_http_errors_are_categorized_without_private_text(self):
        import io, json, tempfile
        import app, passenger_wsgi
        with tempfile.TemporaryDirectory() as directory, patch.object(app, 'DB', directory+'/test.sqlite'):
            app.init(); app.create_user('statistics-test-password')
            def request(path, data=None, cookie=''):
                body=json.dumps(data).encode() if data else b''; headers=[]
                result=b''.join(passenger_wsgi.application({'PATH_INFO':path,'REQUEST_METHOD':'POST' if data else 'GET','REMOTE_ADDR':'test','CONTENT_LENGTH':str(len(body)),'wsgi.input':io.BytesIO(body),'HTTP_COOKIE':cookie},lambda status,h:headers.extend([status,h])))
                return headers,json.loads(result)
            headers,_=request('/api/login',{'password':'statistics-test-password'})
            cookie=next(v for k,v in headers[1] if k=='Set-Cookie').split(';')[0]
            for exception, status, category in [(statistics.StatisticsUnavailable('BROKER_CATALOG'),'503','BROKER_CATALOG'), (RuntimeError('private secret'),'500','UNEXPECTED')]:
                with self.subTest(category=category), patch.object(statistics,'read',side_effect=exception):
                    headers,body=request('/api/realized-statistics',cookie=cookie)
                    self.assertTrue(headers[0].startswith(status))
                    self.assertEqual(body['diagnostic'],category)
                    self.assertNotIn('private secret',json.dumps(body))

if __name__ == '__main__': unittest.main()
