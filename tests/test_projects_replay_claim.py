import importlib.util
from pathlib import Path
import io
import json
import unittest
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

spec = importlib.util.spec_from_file_location('claim', Path(__file__).resolve().parents[1] / 'development' / 'projects_replay_claim.py')
claim = importlib.util.module_from_spec(spec)
spec.loader.exec_module(claim)

ARGS = ('a' * 32, 123, 'PVT_abc', 'PVTI_abc', 'Backlog', 'In progress')


class Response:
    status = 201
    def __enter__(self): return self
    def __exit__(self, *args): pass

class History(io.BytesIO):
    status = 200
    def __init__(self, data=b'[]'): super().__init__(data)


class ReplayClaim(unittest.TestCase):
    def test_same_id_maps_to_same_path_even_if_other_fields_change(self):
        first, payload = claim.prepare_claim(*ARGS)
        second, other = claim.prepare_claim(ARGS[0], 456, *ARGS[2:])
        self.assertEqual(first, second)
        self.assertNotEqual(payload, other)
        self.assertIn('binding_sha256', json.loads(payload))
        self.assertNotIn('PVTI_abc', payload.decode())

    def test_success_uses_create_only_and_binds_fields(self):
        opener = Mock(); opener.open.side_effect = [History(), Response()]
        with patch('urllib.request.build_opener', return_value=opener):
            self.assertEqual(claim.claim('fake-secret', *ARGS), 'CLAIMED')
        request = opener.open.call_args.args[0]
        body = json.loads(request.data)
        self.assertEqual(request.get_method(), 'PUT')
        self.assertNotIn('sha', body)
        self.assertNotIn('fake-secret', request.data.decode())
        self.assertEqual(body['branch'], 'escape-projects-journal')

    def test_conflicts_and_uncertain_fail_closed(self):
        for error in (HTTPError('https://example.test', 409, '', {}, io.BytesIO()), HTTPError('https://example.test', 422, '', {}, io.BytesIO()), HTTPError('https://example.test', 503, '', {}, io.BytesIO()), URLError('connection failed')):
            opener = Mock(); opener.open.side_effect = error
            with self.subTest(error=error), patch('urllib.request.build_opener', return_value=opener), self.assertRaises(claim.ClaimBlocked):
                claim.claim('fake-secret', *ARGS)
            self.assertEqual(opener.open.call_count, 1)

    def test_invalid_inputs_do_not_call_network(self):
        opener = Mock()
        for args in [('bad', *ARGS[1:]), (ARGS[0], True, *ARGS[2:]), (*ARGS[:2], 'PVT_a', 'wrong', *ARGS[4:]), (*ARGS[:4], 'same', 'same')]:
            with self.subTest(args=args), patch('urllib.request.build_opener', return_value=opener), self.assertRaises(claim.ClaimBlocked):
                claim.claim('fake-secret', *args)
        opener.open.assert_not_called()

    def test_historical_or_invalid_journal_blocks_before_create(self):
        for data in (b'[{"sha":"abc"}]', b'{}', b'not json'):
            opener = Mock(); opener.open.return_value = History(data)
            with self.subTest(data=data), patch('urllib.request.build_opener', return_value=opener), self.assertRaises(claim.ClaimBlocked):
                claim.claim('fake-secret', *ARGS)
            self.assertEqual(opener.open.call_count, 1)

    def test_simulated_atomic_create_allows_only_one_claim(self):
        lock = threading.Lock(); paths = set()
        def fake_open(request, timeout):
            if request.get_method() == 'GET': return History()
            with lock:
                if request.full_url in paths:
                    raise HTTPError(request.full_url, 409, '', {}, io.BytesIO())
                paths.add(request.full_url)
            return Response()
        opener = Mock(); opener.open.side_effect = fake_open
        def attempt():
            try: return claim.claim('fake-secret', *ARGS)
            except claim.ClaimBlocked: return 'BLOCKED'
        with patch('urllib.request.build_opener', return_value=opener), ThreadPoolExecutor(max_workers=2) as pool:
            self.assertCountEqual(list(pool.map(lambda _: attempt(), range(2))), ['CLAIMED', 'BLOCKED'])


if __name__ == '__main__': unittest.main()
