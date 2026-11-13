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
        self.assertEqual(str(failure.exception), 'BROKER_CATALOG')

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
