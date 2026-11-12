"""Consistent, explicitly synthetic portfolio data for desktop browser checks."""
from datetime import timedelta
from decimal import Decimal
import json
import math

import app
import dashboard_projection
import portfolio_data
import portfolios


def seed(case):
    # Synthetic snapshots, not instrument quotes: a varied 15-minute history
    # whose portfolio result stays consistent with the fixed 50,000 DKK cost.
    anchors = [(0, 48040.12), (96, 48963.26), (192, 48532.17),
               (280, 49818.42), (288, 50127.36)]
    for index in range(289):
        left, right = next((a, b) for a, b in zip(anchors, anchors[1:]) if a[0] <= index <= b[0])
        fraction = (index - left[0]) / (right[0] - left[0])
        wave = 4 * fraction * (1 - fraction) * (32 * math.sin(index * .77) + 18 * math.sin(index * .21))
        amount = Decimal(str(left[1] + (right[1] - left[1]) * fraction + wave)).quantize(Decimal('.01'))
        case.save(case.root, str(amount), case.now - timedelta(minutes=15 * (288 - index)),
                  result=str(amount - Decimal('50000')))
    observed = case.now.isoformat()
    specs = [('ALFA', '13', '1000', '13000', '200'),
             ('BETA', '25', '500', '12500', '-340'),
             ('GAMMA', '40', '400', '16000', '100'),
             ('DELTA', '8', '1078.42', '8627.36', '167.36')]
    assert sum(Decimal(r[3]) for r in specs) == Decimal('50127.36')
    assert sum(Decimal(r[4]) for r in specs) == Decimal('127.36')
    rows = [{'assetId': 'synthetic-' + ticker, 'ticker': ticker,
             'name': 'Fiktiv ' + ticker, 'quantity': qty, 'price': price,
             'currency': 'DKK', 'value': value, 'unrealisedPnL': pnl,
             'costBasis': str(Decimal(value) - Decimal(pnl)),
             'averageEntryPrice': str((Decimal(value) - Decimal(pnl)) / Decimal(qty)),
             'dailyChange': '1.25', 'dailyChangePercent': str((Decimal('1.25') / (Decimal(price) - Decimal('1.25')) * 100).quantize(Decimal('.01'))),
             'priceAsOf': observed} for ticker, qty, price, value, pnl in specs]
    with app.connect() as c:
        row = c.execute('SELECT payload FROM portfolio_snapshots WHERE portfolio_id=?', (case.root,)).fetchone()
        payload = json.loads(row['payload'])
        payload.update(positions=portfolio_data.normalize_positions(rows), positions_complete=True,
                       accounts=[], pending_orders=[], errors=[], complete=True)
        portfolio_data.save(c, 1, case.root, payload)
        owned = portfolios.list_owned(c, 1)
        snapshots = portfolio_data.snapshots(c, 1)
    projected = dashboard_projection.build(app.connect, 1, owned, snapshots)
    assert len(projected['positions']) == len(specs), projected['positions']
    assert {row['ticker'] for row in projected['positions']} == {row[0] for row in specs}
