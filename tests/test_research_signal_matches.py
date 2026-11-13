"""Offline, synthetic observations; never connects to ESCAPE or a broker."""
import copy
import unittest
from decimal import Decimal
from tools.research_signal_matches import screen


class ResearchMatches(unittest.TestCase):
    def setUp(self):
        common = {'asset_id': 'asset-a', 'portfolio_id': 'p1', 'scope': 'direct',
                  'side': 'SELL', 'currency': 'USD', 'identity_verified': True}
        self.order = {**common, 'id': 'o1', 'execution_verified': True,
                      'filled_at': '2026-11-11T20:21:00Z', 'filled_price': '10.01'}
        self.signal = {**common, 'id': 's1', 'signal_verified': True,
                       'signaled_at': '2026-11-11T20:20:17Z', 'valid_until': '2026-11-11T20:25:00Z',
                       'signal_price': '10.00'}

    def run_screen(self, orders=None, signals=None):
        return screen(orders if orders is not None else [self.order],
                      signals if signals is not None else [self.signal], 900, '0.5')['results']

    def test_unique_qualified_candidate_is_not_attributed_as_fact(self):
        row = self.run_screen()[0]
        self.assertEqual(row['status'], 'research_candidate')
        self.assertEqual(row['delay_seconds'], 43)
        self.assertEqual(Decimal(row['price_difference_percent']), Decimal('0.1'))

    def test_same_time_and_direction_is_not_enough_for_different_asset(self):
        # Mirrors the observed CRWV/RSKD mismatch, with synthetic prices/IDs.
        self.signal['asset_id'] = 'asset-b'
        self.assertEqual(self.run_screen()[0]['status'], 'unknown')

    def test_missing_or_unverified_evidence_is_unknown(self):
        for key in ('filled_at', 'filled_price', 'asset_id', 'portfolio_id', 'scope', 'currency'):
            with self.subTest(order_field=key):
                order = dict(self.order); order.pop(key)
                self.assertEqual(self.run_screen([order])[0]['status'], 'unknown')
        for key in ('signaled_at', 'signal_price', 'valid_until'):
            with self.subTest(signal_field=key):
                signal = dict(self.signal); signal.pop(key)
                self.assertEqual(self.run_screen(signals=[signal])[0]['status'], 'unknown')
        for key in ('identity_verified', 'execution_verified'):
            order = dict(self.order, **{key: False})
            self.assertEqual(self.run_screen([order])[0]['status'], 'unknown')

    def test_created_at_does_not_stand_in_for_fill_time(self):
        order = dict(self.order, created_at=self.order['filled_at']); order.pop('filled_at')
        self.assertEqual(self.run_screen([order])[0]['status'], 'unknown')

    def test_wrong_scope_side_time_price_or_expired_signal_is_unknown(self):
        cases = [dict(self.order, portfolio_id='p2'), dict(self.order, side='BUY'),
                 dict(self.order, scope='collection'), dict(self.order, filled_price='10.06'),
                 dict(self.order, filled_at='2026-11-11T20:19:00Z'),
                 dict(self.order, filled_at='2026-11-11T20:25:00Z')]
        for order in cases:
            self.assertEqual(self.run_screen([order])[0]['status'], 'unknown')

    def test_multiple_or_ambiguous_links_are_unknown(self):
        signal2 = dict(self.signal, id='s2')
        self.assertEqual(self.run_screen(signals=[self.signal, signal2])[0]['status'], 'unknown')
        order2 = dict(self.order, id='o2')
        self.assertTrue(all(x['status'] == 'unknown' for x in self.run_screen([self.order, order2])))
        incomplete = dict(signal2); incomplete.pop('signal_price')
        self.assertEqual(self.run_screen(signals=[self.signal, incomplete])[0]['status'], 'unknown')
        order2 = dict(self.order, id='o2'); order2.pop('filled_at')
        self.assertTrue(all(x['status'] == 'unknown' for x in self.run_screen([self.order, order2])))

    def test_unknown_identity_cannot_exclude_a_competing_event(self):
        other = dict(self.signal, id='s2', asset_id='unverified', identity_verified=False)
        self.assertEqual(self.run_screen(signals=[self.signal, other])[0]['status'], 'unknown')

    def test_thresholds_are_explicit_and_input_is_not_mutated(self):
        order, signal = copy.deepcopy(self.order), copy.deepcopy(self.signal)
        with self.assertRaises(ValueError): screen([order], [signal], 0, '0.5')
        screen([order], [signal], 900, '0.5')
        self.assertEqual(order, self.order); self.assertEqual(signal, self.signal)


if __name__ == '__main__':
    unittest.main()
