"""Consistent, explicitly synthetic portfolio data for desktop browser checks."""
from datetime import timedelta
from decimal import Decimal
import json

import app
import dashboard_projection
import portfolio_data
import portfolios


def seed(case):
    for hours, value, result in [(72, '48040.12', '-1020.55'), (48, '48963.26', '-620.18'),
                                 (24, '48532.17', '-399.46'), (2, '49818.42', '-181.58'),
                                 (0, '50127.36', '127.36')]:
        case.save(case.root, value, case.now - timedelta(hours=hours), result=result)
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
