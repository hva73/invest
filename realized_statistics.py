"""Conservative read-only projection of Pluto execution observations.

The order list has no documented complete history or execution times. Consequently
only sales following a single observed direct purchase are compared as an
indicative gross price comparison, never as a verified cost basis or net profit.
"""
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone
from collections import defaultdict, deque


def _decimal(value):
    if value is None or isinstance(value, bool): return None
    try:
        value = Decimal(str(value))
        return value if value.is_finite() and 0 < value < Decimal('1e30') and value.adjusted() >= -90 else None
    except (InvalidOperation, ValueError): return None


def _stamp(value):
    if not isinstance(value, str): return None
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return result.astimezone(timezone.utc) if result.tzinfo else None
    except ValueError: return None


def _record(row, scope, event_time):
    if not isinstance(row, dict) or row.get('side') not in ('BUY', 'SELL'): return None
    # Final cancelled orders can contain a real partial execution; never accept
    # a zero-filled or unpriced observation as a transaction.
    if row.get('status') not in ('FILLED', 'COMPLETED', 'CANCELED', 'CANCELLED', 'EXPIRED'): return None
    asset = row.get('asset') if isinstance(row.get('asset'), dict) else {}
    ticker, name, currency = asset.get('ticker'), asset.get('name'), asset.get('currency')
    if not all(isinstance(x, str) and x.strip() for x in (ticker, name, currency)): return None
    if len(currency) != 3 or not currency.isascii() or not currency.isalpha(): return None
    quantity, price = _decimal(row.get('filledQuantity')), _decimal(row.get('filledAveragePrice'))
    stamp = _stamp(row.get(event_time))
    order_id = row.get('id')
    if not quantity or not price or not stamp or not isinstance(order_id, str) or not order_id: return None
    return dict(id=order_id, side=row['side'], ticker=ticker, name=name, currency=currency.upper(), quantity=quantity, price=price, time=stamp, scope=scope)


def _result(buy, sell, quantity, basis, provisional):
    proceeds = quantity * sell['price']
    profit = proceeds - basis
    return {'ticker': sell['ticker'], 'name': sell['name'], 'scope': sell['scope'], 'currency': sell['currency'],
            'quantity': format(quantity, 'f'), 'cost_basis': format(basis, 'f'), 'sale_proceeds': format(proceeds, 'f'),
            'gross': format(profit, 'f'), 'gross_percent': format(profit / basis * 100, 'f'),
            'gross_dkk': format(profit, 'f') if sell['currency']=='DKK' else None,
            'net_dkk': None, 'fees_status': 'unknown',
            'buy_origin': 'unknown', 'sell_origin': 'unknown',
            'buy_price': format(buy['price'], 'f'), 'sell_price': format(sell['price'], 'f'),
            'sell_time': None if provisional else sell['time'].isoformat(),
            'order_created_at': sell['time'].isoformat() if provisional else None,
            'quality': 'indicative',
            'note': ('Foreløbig kursforskel: faktisk fyldtid og fuld købshistorik er ikke dokumenteret.' if provisional
                     else 'Foreløbigt brutto i handelsvaluta; gebyrer, valutaomregning og ældre historik er ikke dokumenteret.')}


def project(direct_orders, collection_orders=()):
    """Return results per sale; inputs must already be isolated to one portfolio.

    Each collection tuple is (collection_id, nested order). Separate scopes are
    intentionally never merged. Stable order IDs are required and duplicates are
    discarded entirely when their observations differ.
    """
    groups = defaultdict(list); ambiguous = set(); seen = {}; omitted = 0
    unsafe_instruments = set(); unsafe_scopes = set()
    def taint(row, scope):
        asset = row.get('asset') if isinstance(row, dict) and isinstance(row.get('asset'), dict) else {}
        ticker = asset.get('ticker')
        if isinstance(ticker, str) and ticker.strip(): unsafe_instruments.add((scope, ticker.strip().casefold()))
        else: unsafe_scopes.add(scope)
    def add(row, scope, timestamp):
        nonlocal omitted
        record = _record(row, scope, timestamp)
        if record is None:
            omitted += 1
            # Only an explicitly zero-filled final order proves it cannot alter
            # the cost basis. Any other incomplete observation poisons the
            # relevant instrument (or the entire scope if identity is missing).
            quantity = row.get('filledQuantity') if isinstance(row, dict) else None
            try:
                zero = not isinstance(quantity, bool) and quantity is not None and Decimal(str(quantity)).is_finite() and Decimal(str(quantity)) == 0
            except (InvalidOperation, ValueError): zero = False
            if not (zero and row.get('status') in ('CANCELED','CANCELLED','EXPIRED','REJECTED')): taint(row, scope)
            return
        key = (scope, record['id'])
        if key in seen:
            if seen[key] != record:
                ambiguous.add(key)
                taint(row, scope)
                unsafe_instruments.add((scope, seen[key]['ticker'].strip().casefold()))
            return
        seen[key] = record
    for row in direct_orders:
        if isinstance(row, dict) and row.get('scope') in ('ROOT', 'DIRECT') and not row.get('collectionId'):
            add(row, 'direct', 'createdAt')
        elif isinstance(row, dict) and (row.get('scope') == 'COLLECTION' or row.get('collectionId')):
            omitted += 1
        else:
            omitted += 1
            taint(row, 'direct')
    for collection_id, row in collection_orders:
        if isinstance(collection_id, str) and collection_id: add(row, 'collection:' + collection_id, 'filledAt')
        else: omitted += 1
    for key, row in seen.items():
        if key in ambiguous:
            omitted += 1
            continue
        groups[(row['scope'], row['ticker'], row['name'], row['currency'])].append(row)
    results = []
    identities = defaultdict(set)
    for scope, ticker, name, currency in groups:
        identities[(scope, ticker.strip().casefold())].add((name, currency))
    for key, names in identities.items():
        if len(names) > 1: unsafe_instruments.add(key)
    for (scope, _, _, _), rows in groups.items():
        if scope in unsafe_scopes or (scope, rows[0]['ticker'].strip().casefold()) in unsafe_instruments:
            omitted += 1
            continue
        rows.sort(key=lambda x: x['time'])
        if len({row['time'] for row in rows}) != len(rows):
            omitted += 1
            continue
        if scope == 'direct':
            # createdAt is NOT fill time. One observed purchase can provide one
            # indicative unit price for partial sales, without assuming an order
            # among multiple buys or sales. No claim of complete opening history.
            buys=[row for row in rows if row['side']=='BUY']
            sells=[row for row in rows if row['side']=='SELL']
            if (len(buys)==1 and sells and all(sell['time']>buys[0]['time'] for sell in sells)
                    and sum((sell['quantity'] for sell in sells),Decimal(0))<=buys[0]['quantity']):
                buy=buys[0]
                for sell in sells:
                    results.append(_result(buy,sell,sell['quantity'],sell['quantity']*buy['price'],True))
            elif sells: omitted += 1
            continue
        lots = deque(); unsafe = False
        for row in rows:
            if row['side'] == 'BUY': lots.append([row, row['quantity']]); continue
            if sum((lot[1] for lot in lots), Decimal(0)) < row['quantity']:
                omitted += 1; unsafe = True; lots.clear(); continue
            if unsafe:
                omitted += 1; continue
            remaining = row['quantity']; cost = Decimal(0); first = lots[0][0]
            while remaining:
                buy, available = lots[0]; taken = min(available, remaining)
                cost += taken * buy['price']; remaining -= taken; lots[0][1] -= taken
                if not lots[0][1]: lots.popleft()
            result = _result(first, row, row['quantity'], cost, False)
            result['buy_price'] = format(cost / row['quantity'], 'f')
            results.append(result)
    summaries={}
    for row in results:
        currency=row['currency']; gross=Decimal(row['gross'])
        s=summaries.setdefault(currency,{'sales':0,'wins':0,'losses':0,'flat':0,'gains':Decimal(0),'losses_total':Decimal(0)})
        s['sales']+=1
        if gross>0: s['wins']+=1;s['gains']+=gross
        elif gross<0: s['losses']+=1;s['losses_total']+=gross
        else: s['flat']+=1
    for s in summaries.values():
        gains=s['gains'];losses=s['losses_total']
        s.update(gains=format(gains,'f'),losses_total=format(losses,'f'),gross_total=format(gains+losses,'f'),
                 win_rate_percent=format(Decimal(s['wins'])/Decimal(s['sales'])*100,'f'))
    return {'items': results, 'summary_by_currency':summaries, 'omitted': omitted, 'history_complete': False,
            'count_note':'Én observeret salgsordre tælles én gang; delsalg tælles hver for sig. Vinderandel er antal positive salg divideret med alle viste salg, også nulresultater.',
            'note': 'Kun observerede handler. Historikkens dækning, gebyrer og historisk valutakurs er ikke bekræftet. Direkte handler er foreløbige kursforskelle; oprettelsestid er ikke fyldtid.'}


def read(connect, user_id, client_factory=None):
    """Read only active portfolios owned by the session; no broker writes."""
    import oauth
    from mcp_client import decode_result
    from pending_orders import allowed
    from portfolio_data import list_data
    with connect() as db:
        portfolios = [dict(row) for row in db.execute(
            "SELECT id,name,external_id,kind,parent_external_id FROM portfolios WHERE user_id=? AND source='pluto' AND active=1", (user_id,))]
    if client_factory is None:
        from hotwatch_adapters import PlutoAdapter
        client_factory = PlutoAdapter(connect, user_id, purpose='statistics').factory
    client = client_factory(oauth.access_token(connect, user_id))
    tools = client.tools(); output = []; errors = []
    for portfolio in portfolios:
        external = portfolio['external_id'] or ''
        try:
            namespace, identifier = external.split(':', 1)
            if portfolio['kind'] == 'portfolio' and namespace == 'portfolios':
                if not allowed(tools, 'list_orders', 'portfolioId'): raise ValueError('Ordrehistorik er utilgængelig')
                data = decode_result(client.request('tools/call', {'name':'list_orders', 'arguments':{
                    'portfolioId':identifier, 'scope':'DIRECT', 'statusGroup':'INACTIVE', 'limit':50}}), 'list_orders')
                rows = list_data(data, ['orders','items','data'])
                result = project(rows)
            elif portfolio['kind'] == 'collection' and namespace == 'collections':
                if not allowed(tools, 'get_collection_activity', 'collectionId'): raise ValueError('Collectionhistorik er utilgængelig')
                rows=[]; cursor=None; seen=set()
                for _ in range(20):
                    args={'collectionId':identifier,'limit':50}
                    if cursor: args['nextToken']=cursor
                    data=decode_result(client.request('tools/call', {'name':'get_collection_activity','arguments':args}), 'get_collection_activity')
                    for activity in list_data(data,['activities','activity','items','data']):
                        if not isinstance(activity,dict) or activity.get('collectionId') != identifier: raise ValueError('Collectiontilknytning mangler')
                        wrappers=activity.get('orders',[])
                        if not isinstance(wrappers,list): raise ValueError('Ugyldige Collectionordrer')
                        for wrapper in wrappers:
                            if not isinstance(wrapper,dict) or not isinstance(wrapper.get('type'),str): raise ValueError('Ukendt Collectionordre')
                            if wrapper['type']=='ORDER':
                                if not isinstance(wrapper.get('data'),dict): raise ValueError('Ufuldstændig Collectionordre')
                                rows.append((identifier,wrapper['data']))
                    cursor=data.get('nextToken') if isinstance(data,dict) else None
                    if isinstance(data,dict) and (data.get('nextCursor') or (data.get('hasMore') is True and not cursor)): raise ValueError('Collectionhistorik er ufuldstændig')
                    if not cursor: break
                    if not isinstance(cursor,str) or cursor in seen: raise ValueError('Collectionhistorik er ufuldstændig')
                    seen.add(cursor)
                else: raise ValueError('Collectionhistorik er ufuldstændig')
                result=project([],rows)
            else: continue
            output.append({'portfolio_id':portfolio['id'],'name':portfolio['name'],'kind':portfolio['kind'],**result})
        except Exception:
            errors.append('En historik kunne ikke læses; eventuelle tal dækker ikke alle depoter.')
    return {'portfolios':output,'errors':errors,'observed':datetime.now(timezone.utc).isoformat(),
            'history_complete':False}

