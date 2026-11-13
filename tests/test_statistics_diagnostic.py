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

if __name__ == '__main__': unittest.main()
