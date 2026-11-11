import io
import json
import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from unittest.mock import Mock
import nordicway_uapi_probe as p


class Response(io.BytesIO):
    status = 200
    def __enter__(self): return self
    def __exit__(self, *args): self.close()


class ProbeTests(unittest.TestCase):
    def test_valid_shape_only_returns_field_types(self):
        payload = {'result': {'status': 1, 'data': [{'name':'diskusage', 'count':'12.1',
                   'max':'10 GB', '_count': '12', '_max':'100', 'units':'MB', 'normalized':1}]}}
        opener = Mock()
        opener.open.return_value = Response(json.dumps(payload).encode())
        result = p.probe('a' * 40, opener)
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['fields']['units'], 'str')
        self.assertNotIn('12.1', str(result))
        self.assertNotIn('a' * 40, str(result))
        self.assertEqual(opener.open.call_args.args[0].full_url, p.URL)

    def test_error_and_invalid_token_never_expose_response(self):
        opener = Mock()
        opener.open.return_value = Response(b'{"result":{"status":0,"errors":["sensitive"]}}')
        self.assertEqual(p.probe('a' * 40, opener), {'status':'api_rejected'})
        self.assertEqual(p.probe('bad\n', opener), {'status':'invalid_credential'})

    def test_untrusted_values_are_classified_not_exposed(self):
        payload = {'status':1, 'data':[{'id':'diskusage', 'units':'private-value',
                   '_count':'secret-value', '_max':'1024', 'count':'7.5 GB', 'max':'10 GB'}]}
        opener = Mock(); opener.open.return_value = Response(json.dumps(payload).encode())
        result = p.probe('a' * 40, opener)
        self.assertEqual(result['shapes']['_count'], 'other')
        self.assertEqual(result['shapes']['_max'], 'number')
        self.assertEqual(result['shapes']['count'], 'number_with_unit')
        self.assertEqual(result['unit'], 'other')
        self.assertNotIn('secret-value', str(result))
        self.assertNotIn('private-value', str(result))

    def test_previous_display_comparison_does_not_print_amounts(self):
        payload = {'status':1, 'data':[{'id':'diskusage', 'units':'MB', 'normalized':1,
                   '_count':'8022.09', '_max':'10240'}]}
        opener = Mock(); opener.open.return_value = Response(json.dumps(payload).encode())
        result = p.probe('a' * 40, opener)
        self.assertTrue(result['prior_display_compatible'])
        self.assertNotIn('8022.09', str(result))
        self.assertNotIn('10240', str(result))

    def test_direct_envelope_and_id_are_supported(self):
        payload = {'status':1, 'data':[{'id':'diskusage', 'units':'MB'}]}
        opener = Mock(); opener.open.return_value = Response(json.dumps(payload).encode())
        self.assertEqual(p.probe('a' * 40, opener)['status'], 'ok')

    def test_non_json_does_not_print_response(self):
        opener = Mock(); opener.open.return_value = Response(b'<html>secret</html>')
        self.assertEqual(p.probe('a' * 40, opener), {'status':'non_json_response'})

    def test_http_error_is_categorised_without_body(self):
        import urllib.error
        opener = Mock()
        opener.open.side_effect = urllib.error.HTTPError(p.URL, 401, 'private', {}, None)
        self.assertEqual(p.probe('a' * 40, opener), {'status':'http_error', 'code':401})

    def test_redirect_is_rejected(self):
        with self.assertRaises(ValueError):
            p.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://evil.example/')

if __name__ == '__main__': unittest.main()
