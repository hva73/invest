"""Conservative read-only projection of Pluto execution observations.

The order list has no documented complete history or execution times. Consequently
only sales following a single observed direct purchase are compared as an
indicative gross price comparison, never as a verified cost basis or net profit.
"""
from decimal import Decimal, InvalidOperation, localcontext
from datetime import datetime, timezone
from collections import defaultdict, deque
from urllib.error import HTTPError, URLError
import sqlite3
import json
import re

def signal_order_sides(connect, user_id, portfolio_id):
    """Return explicit, unambiguous provider order references to HOT WATCH proposals.

    A proposal is not a fill. The consumer must independently verify an executed
    order in the same portfolio and direction. Missing or contradictory evidence
    leaves the source unknown.
    """
    try:
        with connect() as db:
            proposals = db.execute("SELECT p.signal_event_id,p.intent_id,p.payload,p.response,e.event_type,s.request FROM broker_proposals p JOIN hw_events e ON e.event_id=p.signal_event_id JOIN hw_sessions s ON s.id=e.watch_row_id "
                                   "WHERE p.user_id=? AND p.portfolio_id=? AND p.kind='direct' AND p.status='sent' AND p.report_id='@hotwatch' AND s.user_id=p.user_id AND s.watch_id=p.candidate_id AND s.is_test=0",
                                   (user_id, portfolio_id)).fetchall()
    except sqlite3.OperationalError:
        return {}
    seen = {}
    for event_id, intent_id, payload, response, event_type, request in proposals:
        if not isinstance(event_id,str) or not re.fullmatch(r'hw-[a-f0-9]{24}',event_id): continue
        try:
            args, result, watch = json.loads(payload), json.loads(response), json.loads(request)
        except (TypeError, ValueError): continue
        if not isinstance(args,dict) or not isinstance(result,dict) or not isinstance(watch,dict): continue
        orders = args.get('orders')
        if not isinstance(orders,list) or len(orders)!=1 or not isinstance(orders[0],dict): continue
        side=orders[0].get('side'); order_id=result.get('orderId'); asset_id=orders[0].get('assetId')
        if side not in ('BUY','SELL') or not isinstance(intent_id,str) or not intent_id: continue
        if not isinstance(asset_id,str) or not asset_id or watch.get('asset_id') != asset_id: continue
        if watch.get('portfolio_ids') != [portfolio_id]: continue
        if event_type not in ({'BUY_SIGNAL'} if side=='BUY' else {'SELL_SIGNAL','REDUCE_SIGNAL'}): continue
        if result.get('orderIntentId')!=intent_id or str(result.get('status','')).upper()!='ACCEPTED': continue
        if not isinstance(order_id,str) or not order_id or len(order_id)>200: continue
        if order_id in seen:
            seen[order_id]=None
        else:
            seen[order_id]=(side,asset_id)
    return {key: value for key,value in seen.items() if value is not None}


def documented_order_origins(connect, user_id, portfolio_id):
    """An explicit provider order reference, never price/time coincidence.

    Preserve decision origin independently of Pluto's AI-agent routing label.
    The stored, verified asset fills the identity gap in list_orders only when
    name, currency, side, portfolio and exact order ID also agree.
    """
    signals = signal_order_sides(connect, user_id, portfolio_id)
    try:
        with connect() as db:
            proposals = db.execute("SELECT report_id,payload,response,intent_id,asset FROM broker_proposals WHERE user_id=? AND portfolio_id=? AND kind='direct' AND status='sent'", (user_id, portfolio_id)).fetchall()
    except sqlite3.OperationalError: return {}
    matches = {}; ambiguous = set()
    for report, payload, response, intent, stored_asset in proposals:
        try:
            payload, response, asset = json.loads(payload), json.loads(response), json.loads(stored_asset)
            orders = payload.get('orders')
            if not isinstance(orders,list) or len(orders)!=1: continue
            order = orders[0]; oid = response.get('orderId'); side=order.get('side'); aid=order.get('assetId')
            if not isinstance(oid,str) or not oid or side not in ('BUY','SELL') or not isinstance(aid,str) or not aid: continue
            if response.get('orderIntentId') != intent or not intent or response.get('status') != 'ACCEPTED': continue
            if not isinstance(asset,dict) or asset.get('assetId',asset.get('id')) != aid: continue
            if not isinstance(asset.get('name'),str) or not asset['name'] or not isinstance(asset.get('currency'),str): continue
            if signals.get(oid)==(side,aid):
                origin='signal'; note='Bekræftet ordre-ID → forslag → valgt HOT WATCH-signal.'
            elif report in ('@manual-buy','@manual-sell') and side==('BUY' if report=='@manual-buy' else 'SELL'):
                origin='own'; note='Bekræftet ordre-ID → manuelt oprettet forslag i ESCAPE.'
            else: continue
            if oid in matches: ambiguous.add(oid)
            matches[oid]={'side':side,'asset_id':aid,'name':asset['name'],'currency':asset['currency'],'ticker':asset.get('ticker'),'origin':origin,'evidence':note}
        except (ValueError,TypeError,AttributeError,KeyError): continue
    return {oid:value for oid,value in matches.items() if oid not in ambiguous}


class StatisticsUnavailable(Exception):
    def __init__(self, category):
        self.category = category
        super().__init__(category)

def catalog_error_code(error):
    """Classify startup failures without returning provider or account details."""
    if getattr(error, 'code', None) == 'PROVIDER_RATE_BUDGET': return 'CATALOG_BUDGET'
    if isinstance(error, sqlite3.Error): return 'CATALOG_DATABASE'
    if isinstance(error, HTTPError):
        if error.code in (401, 403): return 'CATALOG_DENIED'
        if error.code == 429: return 'CATALOG_RATE_LIMIT'
        return 'CATALOG_HTTP'
    if isinstance(error, TimeoutError): return 'CATALOG_TIMEOUT'
    if isinstance(error, URLError):
        return 'CATALOG_TIMEOUT' if isinstance(error.reason, TimeoutError) else 'CATALOG_NETWORK'
    if isinstance(error, ConnectionError): return 'CATALOG_NETWORK'
    if isinstance(error, (ValueError, TypeError, KeyError)): return 'CATALOG_RESPONSE'
    return 'BROKER_CATALOG'

def depot_error_code(stage, error):
    """Return only fixed, non-sensitive categories for operational diagnosis."""
    if getattr(error, 'code', None) == 'PROVIDER_RATE_BUDGET': return 'PROVIDER_RATE_BUDGET'
    if stage not in ('DIRECT_REQUEST', 'COLLECTION_REQUEST'): return stage
    if getattr(error, 'code', None) == 'PLUTO_WRITE_OR_UNKNOWN_TOOL_BLOCKED': return stage + '_LOCAL_GUARD'
    if isinstance(error, HTTPError):
        return stage + ('_DENIED' if error.code in (401, 403) else '_HTTP')
    if isinstance(error, TimeoutError): return stage + '_TIMEOUT'
    if isinstance(error, (URLError, ConnectionError)): return stage + '_NETWORK'
    from mcp_client import PortfolioFormatError
    if isinstance(error, PortfolioFormatError): return stage + '_RESPONSE'
    return stage


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


def _ratio(numerator, denominator):
    # Ratios may repeat forever; keep their existing 28 significant digits.
    # Monetary totals are computed separately with sufficient exact precision.
    with localcontext() as ctx:
        ctx.prec = 28
        return numerator / denominator


def _percent(numerator, denominator):
    with localcontext() as ctx:
        ctx.prec = 28
        return numerator / denominator * 100


def _result(buy, sell, quantity, basis, provisional):
    proceeds = quantity * sell['price']
    profit = proceeds - basis
    return {'ticker': sell['ticker'], 'name': sell['name'], 'scope': sell['scope'], 'currency': sell['currency'],
            'quantity': format(quantity, 'f'), 'cost_basis': format(basis, 'f'), 'sale_proceeds': format(proceeds, 'f'),
            'gross': format(profit, 'f'), 'gross_percent': format(_percent(profit, basis), 'f'),
            'gross_dkk': format(profit, 'f') if sell['currency']=='DKK' else None,
            'net_dkk': None, 'fees_status': 'unknown',
            'buy_origin': buy.get('origin', 'unknown'), 'sell_origin': sell.get('origin', 'unknown'),
            'buy_order_id':buy['id'], 'sell_order_id':sell['id'],
            'buy_origin_evidence':buy.get('origin_evidence'), 'sell_origin_evidence':sell.get('origin_evidence'),
            'buy_price': format(buy['price'], 'f'), 'sell_price': format(sell['price'], 'f'),
            'sell_time': None if provisional else sell['time'].isoformat(),
            'order_created_at': sell['time'].isoformat() if provisional else None,
            'quality': 'indicative',
            'note': ('Foreløbig kursforskel: faktisk fyldtid og fuld købshistorik er ikke dokumenteret.' if provisional
                     else 'Foreløbigt brutto i handelsvaluta; gebyrer, valutaomregning og ældre historik er ikke dokumenteret.')}


def project(direct_orders, collection_orders=(), signal_order_sides=None, order_origins=None):
    """Project orders using enough precision for exact finite amount arithmetic."""
    direct_orders = list(direct_orders)
    collection_orders = list(collection_orders)
    values = []
    for row in direct_orders + [row for _, row in collection_orders]:
        if isinstance(row, dict):
            values.extend(value for value in (_decimal(row.get('filledQuantity')),
                                              _decimal(row.get('filledAveragePrice'))) if value is not None)
    # A quantity/price product can span twice the input's decimal range.
    # Allow extra digits for summing every observed order and avoid changing
    # the caller's Decimal context.
    if values:
        low = min(0, *(value.as_tuple().exponent for value in values))
        high = max(0, *(value.adjusted() for value in values))
        precision = max(28, 2 * (high - low + 2) + len(str(len(values))) + 10)
    else:
        precision = 28
    with localcontext() as ctx:
        ctx.prec = precision
        return _project(direct_orders, collection_orders, signal_order_sides or {}, order_origins or {})


def _project(direct_orders, collection_orders=(), signal_order_sides=None, order_origins=None):
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
        if (scope == 'direct' and isinstance(row.get('asset'), dict)
                and isinstance(row['asset'].get('id'), str) and row['asset']['id']
                and (signal_order_sides or {}).get(record['id']) == (record['side'], row['asset']['id'])):
            record['origin'] = 'signal'
        proof = (order_origins or {}).get(record['id'])
        if scope == 'direct' and isinstance(proof, dict):
            asset_id = row['asset'].get('id')
            same_identity = (asset_id == proof['asset_id'] if asset_id else
                             record['name'] == proof['name'] and record['currency'] == proof['currency']
                             and (not proof.get('ticker') or record['ticker'] == proof['ticker']))
            if same_identity and record['side'] == proof['side']:
                record['origin'] = proof['origin']
                record['origin_evidence'] = proof['evidence']
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
    unresolved_sales = []
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
            elif sells:
                omitted += 1
                for sell in sells:
                    unresolved_sales.append({'ticker': sell['ticker'], 'name': sell['name'],
                        'currency': sell['currency'], 'quantity': format(sell['quantity'], 'f'),
                        'sell_price': format(sell['price'], 'f'),
                        'sale_proceeds': format(sell['quantity'] * sell['price'], 'f'),
                        'buy_origin': 'unknown', 'sell_origin': sell.get('origin', 'unknown'),
                        'sell_order_id':sell['id'], 'sell_origin_evidence':sell.get('origin_evidence')})
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
            result['buy_price'] = format(_ratio(cost, row['quantity']), 'f')
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
                 win_rate_percent=format(_percent(Decimal(s['wins']), Decimal(s['sales'])),'f'))
    return {'items': results, 'unresolved_sales': unresolved_sales, 'summary_by_currency':summaries, 'omitted': omitted, 'history_complete': False,
            'count_note':'Én observeret salgsordre tælles én gang; delsalg tælles hver for sig. Vinderandel er antal positive salg divideret med alle viste salg, også nulresultater.',
            'note': 'Kun observerede handler. Historikkens dækning, gebyrer og historisk valutakurs er ikke bekræftet. Direkte handler er foreløbige kursforskelle; oprettelsestid er ikke fyldtid.'}


def display_currency(connect, output, now=None, user_id=None):
    """DKK display estimate from the same cached reference sources as sectors.

    Original executions stay untouched. This is not historical settlement FX.
    No provider calls, writes or fixed exchange-rate defaults.
    """
    now = now or datetime.now(timezone.utc)
    rates = {'DKK': {'rate':'1', 'source':'DKK', 'as_of':None}}
    needed = {row.get('currency') for p in output.get('portfolios', [])
              for row in p.get('items', []) + p.get('unresolved_sales', [])}
    if not needed:
        output['display_currency'] = 'DKK'
        output['display_fx'] = rates
        return output
    def positive(value):
        try:
            n = Decimal(str(value))
            return n if n.is_finite() and n > 0 else None
        except (InvalidOperation, ValueError, TypeError): return None
    with connect() as db:
        try:
            row = db.execute('SELECT source_date,payload FROM fx_snapshots ORDER BY source_date DESC,id DESC LIMIT 1').fetchone()
            if row:
                date, payload = row
                age = (now.date() - datetime.fromisoformat(date).date()).days
                values = json.loads(payload).get('rates', {})
                dkk = positive(values.get('DKK'))
                if 0 <= age <= 7 and dkk:
                    for code in needed:
                        foreign = Decimal(1) if code == 'EUR' else positive(values.get(code))
                        if code != 'DKK' and foreign:
                            rates[code] = {'rate':format(dkk / foreign,'f'), 'source':'ECB', 'as_of':date}
        except (sqlite3.OperationalError, ValueError, TypeError, AttributeError): pass
        try:
            quotes = db.execute('SELECT currency,rate,event_time,status FROM sector_fx').fetchall()
            for code, value, at, status in quotes:
                rate = positive(value)
                try: age = (now - datetime.fromisoformat(at.replace('Z','+00:00'))).total_seconds()
                except (ValueError, TypeError, AttributeError): continue
                if code not in rates and code in needed and status == 'OK' and rate and 0 <= age <= 7*86400:
                    rates[code] = {'rate':format(rate,'f'), 'source':'EODHD', 'as_of':at}
        except sqlite3.OperationalError: pass
        # Sector Intelligence also derives a display FX estimate from fresh
        # pairs of original/DKK position values in the owner's Pluto snapshot.
        if user_id is not None:
            candidates = defaultdict(list)
            try:
                snapshots = db.execute('SELECT observed,payload FROM portfolio_snapshots WHERE user_id=? AND last_error IS NULL',(user_id,)).fetchall()
                for at, payload in snapshots:
                    try:
                        age = (now - datetime.fromisoformat(at.replace('Z','+00:00'))).total_seconds()
                        snapshot = json.loads(payload)
                        if not 0 <= age <= 86400 or snapshot.get('positions_complete') is not True: continue
                        for position in snapshot.get('positions',[]):
                            foreign=position.get('value') or {}; local=position.get('value_in_portfolio_currency') or {}
                            code=foreign.get('currency'); a=positive(foreign.get('amount')); b=positive(local.get('amount'))
                            if code in needed and code not in rates and local.get('currency')=='DKK' and a and b:
                                candidates[code].append((b/a,at))
                    except (ValueError,TypeError,AttributeError): continue
                for code, values in candidates.items():
                    values.sort()
                    if values[-1][0]/values[0][0] > Decimal('1.05'): continue
                    mid=len(values)//2
                    rate=values[mid][0] if len(values)%2 else (values[mid-1][0]+values[mid][0])/2
                    rates[code]={'rate':format(rate,'f'),'source':'Pluto-estimat','as_of':max(at for _,at in values)}
            except sqlite3.OperationalError: pass
    for portfolio in output.get('portfolios', []):
        for item in portfolio.get('items', []) + portfolio.get('unresolved_sales', []):
            info = rates.get(item.get('currency'))
            item['display_fx'] = info
            for original, target in [('gross','display_gross_dkk'),('cost_basis','display_cost_dkk'),('sale_proceeds','display_proceeds_dkk')]:
                item[target] = None
                try:
                    value = Decimal(item[original])
                    if info and value.is_finite():
                        with localcontext() as ctx:
                            ctx.prec = 300
                            item[target] = format(value * Decimal(info['rate']),'f')
                except (KeyError, InvalidOperation, TypeError, ValueError): pass
    output['display_currency'] = 'DKK'
    output['display_fx'] = rates
    return output


def read(connect, user_id, client_factory=None):
    """Read only active portfolios owned by the session; no broker writes."""
    import oauth
    from mcp_client import decode_result
    from pending_orders import allowed
    from portfolio_data import list_data
    try:
        with connect() as db:
            portfolios = [dict(row) for row in db.execute(
                "SELECT id,name,external_id,kind,parent_external_id FROM portfolios WHERE user_id=? AND source='pluto' AND active=1", (user_id,))]
    except Exception as error:
        raise StatisticsUnavailable('DATABASE') from error
    if client_factory is None:
        from hotwatch_adapters import PlutoAdapter
        client_factory = PlutoAdapter(connect, user_id, purpose='statistics').factory
    try:
        token = oauth.access_token(connect, user_id)
    except Exception as error:
        raise StatisticsUnavailable('CONNECTION') from error
    try:
        client = client_factory(token)
        tools = client.tools()
    except Exception as error:
        raise StatisticsUnavailable(catalog_error_code(error)) from error
    output = []; errors = []; error_codes = []
    for portfolio in portfolios:
        external = portfolio['external_id'] or ''
        stage = 'IDENTITY'
        try:
            namespace, identifier = external.split(':', 1)
            if portfolio['kind'] == 'portfolio' and namespace == 'portfolios':
                stage = 'DIRECT_PERMISSION'
                if not allowed(tools, 'list_orders', 'portfolioId'): raise ValueError('Ordrehistorik er utilgængelig')
                stage = 'DIRECT_REQUEST'
                data = decode_result(client.request('tools/call', {'name':'list_orders', 'arguments':{
                    'portfolioId':identifier, 'scope':'DIRECT', 'statusGroup':'INACTIVE', 'limit':50}}), 'list_orders')
                rows = list_data(data, ['orders','items','data'])
                stage = 'DIRECT_PROJECTION'
                result = project(rows, signal_order_sides=signal_order_sides(connect, user_id, portfolio['id']), order_origins=documented_order_origins(connect,user_id,portfolio['id']))
            elif portfolio['kind'] == 'collection' and namespace == 'collections':
                stage = 'COLLECTION_PERMISSION'
                if not allowed(tools, 'get_collection_activity', 'collectionId'): raise ValueError('Collectionhistorik er utilgængelig')
                stage = 'COLLECTION_REQUEST'
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
                stage = 'COLLECTION_PROJECTION'
                result=project([],rows)
            else: continue
            output.append({'portfolio_id':portfolio['id'],'name':portfolio['name'],'kind':portfolio['kind'],**result})
        except Exception as error:
            stage = depot_error_code(stage, error)
            if stage not in error_codes: error_codes.append(stage)
            errors.append('En historik kunne ikke læses; eventuelle tal dækker ikke alle depoter.')
    return display_currency(connect, {'portfolios':output,'errors':errors,'error_codes':error_codes,'observed':datetime.now(timezone.utc).isoformat(),
            'history_complete':False}, user_id=user_id)

