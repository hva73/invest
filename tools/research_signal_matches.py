"""Offline screening only; no app, broker, network, or database access.

Inputs are independently verified execution and signal observations. This
tool does not infer fills from order creation, or causation from proximity.
The output is a research candidate, never a production origin classification.
"""
import argparse
import json
from datetime import datetime
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from pathlib import Path


def _date(value):
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return result if result.utcoffset() is not None else None
    except (AttributeError, TypeError, ValueError, OverflowError):
        return None


def _positive(value):
    try:
        if isinstance(value, bool) or value is None:
            return None
        number = Decimal(str(value))
        return number if number.is_finite() and number > 0 else None
    except (InvalidOperation, ValueError):
        return None


def _pair(order, signal, seconds, percent):
    # A known mismatch rules out this pair even when other fields are missing.
    if order.get('identity_verified') is not True or signal.get('identity_verified') is not True:
        return 'unknown', None
    for key in ('asset_id', 'portfolio_id', 'scope', 'side', 'currency'):
        left, right = order.get(key), signal.get(key)
        if left and right and left != right:
            return 'no', None
    if (order.get('execution_verified') is not True or signal.get('signal_verified') is not True
            or any(not order.get(k) or not signal.get(k) for k in ('asset_id', 'portfolio_id', 'scope', 'side', 'currency'))
            or order.get('side') not in ('BUY', 'SELL')):
        return 'unknown', None
    executed, started, ended = _date(order.get('filled_at')), _date(signal.get('signaled_at')), _date(signal.get('valid_until'))
    fill_price, signal_price = _positive(order.get('filled_price')), _positive(signal.get('signal_price'))
    if not all((executed, started, ended, fill_price, signal_price)) or ended < started:
        return 'unknown', None
    delta = (executed - started).total_seconds()
    if delta < 0 or delta > seconds or executed >= ended:
        return 'no', None
    change = abs(Fraction(fill_price) - Fraction(signal_price)) / Fraction(signal_price) * 100
    if change > Fraction(percent):
        return 'no', None
    return 'candidate', {'delay_seconds': delta,
                         'price_difference_percent': str(Decimal(change.numerator) / Decimal(change.denominator))}


def screen(orders, signals, max_seconds, max_price_percent):
    """Return uncalibrated candidates and unknowns; require unambiguous pairs."""
    window, percent = _positive(max_seconds), _positive(max_price_percent)
    if window is None or percent is None:
        raise ValueError('Supply positive experimental time and price thresholds')
    if (not isinstance(orders, list) or not isinstance(signals, list)
            or any(not isinstance(x, dict) or not isinstance(x.get('id'), str) or not x['id'] for x in orders + signals)
            or len({x['id'] for x in orders}) != len(orders)
            or len({x['id'] for x in signals}) != len(signals)):
        raise ValueError('Expected observations with unique IDs')
    matrix = [[_pair(order, signal, float(window), percent) for signal in signals] for order in orders]
    results = []
    for i, order in enumerate(orders):
        candidates = [j for j, (state, _) in enumerate(matrix[i]) if state == 'candidate']
        uncertain = any(state == 'unknown' for state, _ in matrix[i])
        if len(candidates) == 1 and not uncertain:
            j = candidates[0]
            if all(k == i or matrix[k][j][0] == 'no' for k in range(len(orders))):
                results.append({'order_id': order['id'], 'status': 'research_candidate',
                                'signal_id': signals[j]['id'], **matrix[i][j][1]})
                continue
        results.append({'order_id': order['id'], 'status': 'unknown'})
    return {'classification': 'experimental_only_not_proof_of_cause', 'results': results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path, help='Local JSON file containing orders and signals')
    parser.add_argument('--max-seconds', required=True)
    parser.add_argument('--max-price-percent', required=True)
    args = parser.parse_args()
    data = json.loads(args.input.read_text(encoding='utf-8'))
    print(json.dumps(screen(data['orders'], data['signals'], args.max_seconds, args.max_price_percent), ensure_ascii=False))


if __name__ == '__main__':
    main()
