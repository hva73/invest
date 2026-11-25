"""Read-only chronological comparison of recorded HOT WATCH observations.

This is a bounded replay of saved inputs, not a trade simulation or a full
historical backtest. It never changes sessions or communicates with brokers.
"""
import copy,json
from collections import Counter
from functools import lru_cache
from hotwatch_contract import EngineError, RISK, checksum, require, stamp
import trading_engine_v2 as v2
from hotwatch_features import features,verified_bar_samples
from hotwatch_strategy import calculate,validate_strategy,early_watch

MAX_CALCULATIONS=240
MAX_FEATURE_INPUTS = 120
FEATURE_PARAMETERS = {
    'short_period': {'sma_short', 'ema_short', 'trend_up'},
    'long_period': {'sma_long', 'ema_long', 'trend_up'},
    'rsi_period': {'rsi'},
    'atr_period': {'atr'},
    'breakout_window': {'breakout', 'breakdown', 'relative_volume', 'new_breakout'},
    'momentum_window_minutes': {'return_window_pct'},
}


def available(connect,uid):
    with connect() as c:
        rows=c.execute('''SELECT s.watch_id,s.is_test,s.request,s.created,count(x.id) AS calculations
            FROM hw_sessions s JOIN hw_calculations x ON x.watch_row_id=s.id
            WHERE s.user_id=? GROUP BY s.id ORDER BY s.updated DESC LIMIT 100''',(uid,)).fetchall()
    return {'sessions':[{'watch_id':r['watch_id'],'is_test':bool(r['is_test']),'ticker':json.loads(r['request'])['ticker'],'created':r['created'],'calculations':r['calculations']} for r in rows], 'limit':MAX_CALCULATIONS}


def required(rule):
    if 'all' in rule:return set().union(*(required(x) for x in rule['all']))
    if 'any' in rule:return set().union(*(required(x) for x in rule['any']))
    return {rule['metric']}


def _recorded_inputs(connect,uid,data,*, resolve_original=False):
    if not isinstance(data,dict) or set(data)!={'watch_id','is_test','strategies'} or not isinstance(data['watch_id'],str) or not 1<=len(data['watch_id'])<=100 or type(data['is_test']) is not bool:raise ValueError('Vælg en gyldig overvågning.')
    choices=data['strategies']
    if not isinstance(choices,list) or not 1<=len(choices)<=3:raise ValueError('Vælg én til tre strategier.')
    if any(not isinstance(x,dict) or set(x)!={'strategy_id','version'} or not isinstance(x['strategy_id'],str) or not isinstance(x['version'],str) or len(x['strategy_id'])>100 or len(x['version'])>30 for x in choices):raise ValueError('Vælg gyldige strategiversioner.')
    if len({(x['strategy_id'],x['version']) for x in choices})!=len(choices):raise ValueError('Vælg forskellige strategier til sammenligningen.')
    with connect() as c:
        row=c.execute('SELECT * FROM hw_sessions WHERE user_id=? AND watch_id=? AND is_test=?',(uid,data['watch_id'],int(data['is_test']))).fetchone()
        if not row:raise ValueError('Overvågningen blev ikke fundet på din konto.')
        specs=[]
        for choice in choices:
            item=c.execute('SELECT payload,checksum FROM hw_strategies WHERE owner_id IN (0,?) AND strategy_id=? AND version=? ORDER BY owner_id DESC LIMIT 1',(uid,choice['strategy_id'],choice['version'])).fetchone()
            if not item:raise ValueError('En strategiversion blev ikke fundet på din konto.')
            spec=json.loads(item['payload'])
            if validate_strategy(spec) or checksum(spec)!=item['checksum']:raise ValueError('Strategiversionen kunne ikke verificeres.')
            specs.append((spec, item['checksum']))
        original = ''', (SELECT k.payload FROM hw_strategies k
            WHERE k.owner_id IN (0,?) AND k.checksum=c.strategy_checksum
            AND k.strategy_id=json_extract(CASE WHEN json_valid(c.payload) THEN c.payload END,'$.strategy_id')
            AND k.version=json_extract(CASE WHEN json_valid(c.payload) THEN c.payload END,'$.strategy_version')
            ORDER BY k.owner_id DESC LIMIT 1) AS original_spec''' if resolve_original else ''
        params = (uid,) if resolve_original else ()
        rows=c.execute(f'''SELECT c.id,c.calculated,c.payload AS calculation,c.strategy_checksum,
                   s.id AS sample_row_id,s.source,s.sample_id,s.received,
                   s.event_epoch,s.digest AS sample_digest,s.payload AS sample {original}
            FROM hw_calculations c LEFT JOIN hw_samples s ON s.id=c.sample_row_id AND s.watch_row_id=c.watch_row_id
            WHERE c.watch_row_id=? ORDER BY c.id LIMIT ?''',(*params,row['id'],MAX_CALCULATIONS+1)).fetchall()
        request=json.loads(row['request'])
    if not rows:raise ValueError('Der er endnu ingen gemte observationer at sammenligne.')
    return row, request, specs, rows[:MAX_CALCULATIONS], len(rows)>MAX_CALCULATIONS


def compare(connect,uid,data):
    _, request, versions, rows, truncated = _recorded_inputs(connect,uid,data)
    specs = [spec for spec, _ in versions]
    outcomes=[{'strategy_id':s['strategy_id'],'version':s['version'],'checksum':checksum(s),'counts':{'BUY':0,'SELL':0,'REDUCE':0,'WAIT':0,'NO_DATA':0,'PAUSE':0},'missing_indicators':set(),'timeline':[],'early_watch':{'met':0,'not_met':0,'unknown':0,'first_met_at':None} if s['schema_version']==2 else None,'first_buy_at':None} for s in specs]
    states=[{} for _ in specs];window=[];previous_id=None;previous_time=None;skipped=0
    from hotwatch_engine import sample_errors
    for r in rows:
        try:
            calc=json.loads(r['calculation']);sample=json.loads(r['sample']);at=stamp(r['calculated'])
            if checksum(sample)!=r['sample_digest']:raise ValueError('Observation checksum mismatch')
            if not r['received'] or stamp(r['received'])>at or previous_time and at<previous_time:raise ValueError('Chronology unavailable')
            if not isinstance(calc.get('risk_parameters'),dict) or not isinstance(calc.get('position_context'),dict) or type(calc.get('new_market_observation')) is not bool:raise ValueError('Historical context unavailable')
            sample['context']=copy.deepcopy(calc['position_context']);sample_errors(sample,request,at)
            new=bool(calc['new_market_observation'])
            if not new and r['sample_row_id']!=previous_id:raise ValueError('Missing original market observation')
            if new:
                if previous_id==r['sample_row_id']:raise ValueError('Duplicate market observation')
                window.append(sample);window=window[-120:]
            previous_id=r['sample_row_id'];previous_time=at
            bars=verified_bar_samples(sample,request,at) if sample.get('bar_history') else None
            evaluated=[]
            for i,spec in enumerate(specs):
                metrics=features(bars if bars is not None else window,spec['parameters'])
                if bars is not None:
                    live=features([sample],spec['parameters']);metrics.update(price=sample['price'],spread=live.get('spread'),spread_pct=live.get('spread_pct'),bar_history_count=len(bars))
                # Only evidence actually persisted with this historical
                # calculation is reused; never consult later report state.
                if spec['schema_version']==2 and isinstance(calc.get('early_catalyst'),dict):
                    captured=calc.get('supporting_metrics') or {}
                    keys=('ordinary_share','pluto_tradable','catalyst_verified','catalyst_age_minutes','earnings_previous_session','no_verified_news','reference_gain_pct','news_reaction_pct','consolidating','new_breakout','new_setup')
                    metrics.update({key:captured.get(key) for key in keys})
                necessary=required(spec['exit_rules'] if sample['context']['position']=='held' else spec['entry_rules'])
                if spec['schema_version']==2:necessary|=required(spec['watch_rules'])
                if spec['schema_version']==2 and spec['parameters']['use_macd_confirmation']:necessary.add('macd_histogram')
                missing={key for key in necessary if metrics.get(key) is None}
                watch_met=early_watch(spec,metrics) if spec['schema_version']==2 else None
                watch_missing=any(metrics.get(key) is None for key in required(spec['watch_rules'])) if spec['schema_version']==2 else False
                result,new_state=calculate(sample,metrics,spec,calc['risk_parameters'],states[i],at,new_market_event=new)
                evaluated.append((result,new_state,missing,watch_met,watch_missing))
            for i,(result,new_state,missing,watch_met,watch_missing) in enumerate(evaluated):
                states[i]=new_state;out=outcomes[i];out['counts'][result['signal']]+=1;out['missing_indicators'].update(missing)
                watch_status=('met' if watch_met else 'unknown' if watch_missing else 'not_met') if watch_met is not None else None
                if watch_status:
                    out['early_watch'][watch_status]+=1
                    if watch_status=='met' and out['early_watch']['first_met_at'] is None:out['early_watch']['first_met_at']=r['calculated']
                if result['signal']=='BUY' and out['first_buy_at'] is None:out['first_buy_at']=r['calculated']
                out['timeline'].append({'at':r['calculated'],'signal':result['signal'],'reason_codes':result['reason_codes'],'missing':sorted(missing),'early_watch':watch_status})
        except (ValueError,TypeError,KeyError,ArithmeticError,AttributeError,IndexError):
            skipped+=1;states=[{} for _ in specs];window=[];previous_id=None;previous_time=None
    for out in outcomes:out['missing_indicators']=sorted(out['missing_indicators']);out['timeline']=out['timeline'][-12:]
    return {'watch_id':data['watch_id'],'ticker':request['ticker'],'is_test':data['is_test'],'evaluated':len(rows)-skipped,'skipped':skipped,'truncated':truncated,'limit':MAX_CALCULATIONS,'from':rows[0]['calculated'],'to':rows[-1]['calculated'],'strategies':outcomes,'limitations':['Kun gemte observationer og tidligere risikokontekst er anvendt.','Historisk warmup, nyhedsdata og alle hændelser er ikke fuldt rekonstrueret.','Ingen handler, afkast, omkostninger eller faktisk eksekvering er simuleret.']}


def _immutable_sample(row):
    if row['sample_row_id'] is None:
        raise EngineError('SAMPLE_MISSING')
    sample = json.loads(row['sample'])
    if checksum(sample) != row['sample_digest']:
        raise EngineError('SAMPLE_CHECKSUM_MISMATCH')
    if sample['source'] != row['source'] or sample['sample_id'] != row['sample_id']:
        raise EngineError('SAMPLE_IDENTITY_MISMATCH')
    if sample['source'] == 'eodhd' and sample.get('price_time_kind') == 'trade':
        # Ingest can overwrite quote/status evidence without changing received.
        # The calculation does not pin the sample revision it used.
        raise EngineError('SAMPLE_REVISION_UNVERIFIED')

    received = stamp(row['received'])
    event_time = stamp(sample['event_time'])
    market_times = [stamp(sample[key]) for key in ('bid_at', 'ask_at', 'status_at')
                    if sample.get(key)]
    if (event_time.timestamp() != row['event_epoch'] or event_time > received
            or any(value > received for value in market_times)):
        raise EngineError('SAMPLE_CHRONOLOGY_UNVERIFIED')
    return sample, event_time, received


def _v2_snapshot(session, request, row, at, calc):
    """Build the common evidence from this journal pair."""
    from hotwatch_engine import sample_errors

    sample, event_time, received = _immutable_sample(row)
    if received > at:
        raise EngineError('SAMPLE_CHRONOLOGY_UNVERIFIED')
    input_ids = calc.get('input_sample_ids')
    if (stamp(calc['calculation_timestamp']) != at
            or stamp(calc['data_timestamp']) != event_time
            or not isinstance(input_ids, list) or sample['sample_id'] not in input_ids):
        raise EngineError('CALCULATION_LINK_UNVERIFIED')

    context = calc.get('position_context')
    if not isinstance(context, dict) or not context.get('as_of'):
        raise EngineError('POSITION_CONTEXT_UNVERIFIED')
    if context.get('position') == 'held':
        raise EngineError('POSITION_ID_UNAVAILABLE')
    if context.get('position') != 'none' or context.get('status') != 'verified':
        raise EngineError('POSITION_CONTEXT_UNVERIFIED')
    risk = calc.get('risk_parameters')
    metrics = calc.get('supporting_metrics')
    if not isinstance(risk, dict) or type(risk.get('entry_allowed')) is not bool:
        raise EngineError('RISK_CAPTURE_UNAVAILABLE')
    require({key: risk[key] for key in RISK['properties'] if key in risk}, RISK)
    if not isinstance(metrics, dict) or not any(value is not None for value in metrics.values()):
        raise EngineError('METRICS_CAPTURE_UNAVAILABLE')

    portfolios = request.get('portfolio_ids', [])
    if len(portfolios) != 1 or type(portfolios[0]) is not int or portfolios[0] <= 0:
        raise EngineError('PORTFOLIO_SCOPE_UNVERIFIED')
    position_scope = {
        'asset_id': request['asset_id'], 'portfolio_id': portfolios[0],
        'watch_id': session['watch_id'], 'trade_cycle_id': request.get('trade_cycle_id'),
    }
    if (risk.get('_position_scope') != checksum(position_scope)
            or request['watch_id'] != session['watch_id']
            or request['candidate_id'] != session['candidate_id']
            or request['is_test'] is not bool(session['is_test'])
            or not request['exchange']):
        raise EngineError('HISTORICAL_SCOPE_UNVERIFIED')
    scope = v2.Scope(
        user_id=session['user_id'], is_test=bool(session['is_test']),
        exchange=request['exchange'], candidate_id=session['candidate_id'], **position_scope,
    )

    sample.pop('bar_history', None)
    sample.pop('bar_evidence', None)
    sample['context'] = context
    sample_errors(sample, {**request, 'risk': risk}, at)
    if any(order.get('status_time') and stamp(order['status_time']) > at
           for order in context['orders']):
        raise EngineError('POSITION_CONTEXT_UNVERIFIED')

    calc_id = f"hw_calculations:{row['id']}"
    sample_id = f"hw_samples:{row['sample_row_id']}"
    # Local journal references identify the actual capture. The full sample
    # includes the calculation's context and is proven available at calculation time.
    observation = v2.Evidence(sample, event_time, at, (sample_id, calc_id))
    risks = v2.Evidence(risk, at, at, (calc_id,))
    facts = {key: v2.Evidence(value, at, at, (calc_id,))
             for key, value in metrics.items() if value is not None}
    recorded = {
        'signal': calc['signal'], 'reason_codes': calc['reason_codes'],
        'strategy_id': calc['strategy_id'], 'version': calc['strategy_version'],
        'checksum': row['strategy_checksum'],
    }
    if (recorded['signal'] not in ('BUY', 'SELL', 'REDUCE', 'WAIT', 'NO_DATA', 'PAUSE')
            or not isinstance(recorded['reason_codes'], list)):
        raise EngineError('RECORDED_DECISION_UNVERIFIED')
    latency = {
        'event_to_received_ms': (received - event_time).total_seconds() * 1000,
        'received_to_calculated_ms': (at - received).total_seconds() * 1000,
    }
    return scope, calc_id, observation, facts, risks, recorded, latency


def _original_strategy(row, calc):
    try:
        original = json.loads(row['original_spec'])
        if (not validate_strategy(original)
                and checksum(original) == row['strategy_checksum'] == calc.get('strategy_checksum')
                and original['strategy_id'] == calc['strategy_id']
                and original['version'] == calc['strategy_version']):
            return original
    except (ValueError, TypeError):
        pass
    return None


def _feature_history(row, calc, request, at, samples, verified):
    from hotwatch_engine import sample_errors

    # Embedded verified bars belong to mutable trades. Separately cached
    # warmup bars also lack a revision link in these calculations.
    if calc.get('analysis_uses_bars') is not False or 'bar_history_count' in calc['supporting_metrics']:
        raise EngineError('FEATURE_BAR_REVISION_UNVERIFIED')
    if calc.get('feature_version') != '1.3.0':
        raise EngineError('FEATURE_VERSION_UNVERIFIED')
    ids = calc['input_sample_ids']
    if (not 1 <= len(ids) <= MAX_FEATURE_INPUTS or ids[-1] != row['sample_id']
            or any(not isinstance(item, str) for item in ids) or len(set(ids)) != len(ids)):
        raise EngineError('FEATURE_HISTORY_UNVERIFIED')
    history, refs = [], []
    previous_event = None
    for sample_id in ids:
        prior = samples.get((row['source'], sample_id))
        if prior is None:
            raise EngineError('FEATURE_HISTORY_MISSING')
        key = prior['sample_row_id']
        if key not in verified:
            try:
                sample, event, received = _immutable_sample(prior)
                sample_errors(sample, request, received)
                if sample['verification'] != 'verified':
                    raise EngineError('SAMPLE_UNVERIFIED')
                verified[key] = (sample, event, received)
            except (ValueError, TypeError, KeyError, ArithmeticError, AttributeError) as exc:
                verified[key] = exc.code if isinstance(exc, EngineError) else 'FEATURE_HISTORY_UNVERIFIED'
        evidence = verified[key]
        if isinstance(evidence, str):
            raise EngineError(evidence)
        sample, event, received = evidence
        if (received > at or key > row['sample_row_id']
                or previous_event is not None and event <= previous_event):
            raise EngineError('FEATURE_HISTORY_CHRONOLOGY_UNVERIFIED')
        previous_event = event
        history.append(sample)
        refs.append(f'hw_samples:{key}')
    return history, tuple(refs)


def _strategy_facts(spec, original, metrics, history, at, snapshot_id):
    if original is None:
        raise EngineError('ORIGINAL_STRATEGY_UNVERIFIED')
    parameters, recorded = spec['parameters'], original['parameters']
    # Validated specs always have the period parameters. Schema 1 uses the
    # feature function's three-minute default for momentum_window_minutes.
    changed = set().union(*(names for key, names in FEATURE_PARAMETERS.items()
                           if parameters.get(key, 3) != recorded.get(key, 3)))
    facts = dict(metrics)
    if parameters.get('news_max_age_minutes', 120) != recorded.get('news_max_age_minutes', 120):
        for name in ('catalyst_verified', 'earnings_previous_session', 'no_verified_news'):
            facts.pop(name, None)
    if not changed:
        return facts

    samples, refs = history()
    try:
        computed = features(samples, parameters)
    except (ValueError, ArithmeticError) as exc:
        raise EngineError('FEATURE_HISTORY_UNVERIFIED') from exc
    count = metrics.get('sample_count')
    if count is None or type(count.value) is not int or computed['sample_count'] != count.value:
        raise EngineError('FEATURE_HISTORY_UNVERIFIED')
    computed['new_breakout'] = computed.get('breakout') if 'new_breakout' in metrics else None
    needed = required(spec['entry_rules']) | {'relative_volume'}
    if spec['schema_version'] == 2:
        needed |= required(spec['watch_rules']) | {'return_window_pct'}
    if any(computed.get(name) is None for name in changed & needed):
        raise EngineError('FEATURE_HISTORY_INSUFFICIENT')
    for name in changed:
        facts.pop(name, None)
        if computed.get(name) is not None:
            facts[name] = v2.Evidence(computed[name], at, at, (*refs, snapshot_id))
    return facts


def compare_v2(connect, uid, data):
    """Compare recorded decisions with v2 decisions on shared, bounded snapshots."""
    session, request, versions, rows, truncated = _recorded_inputs(connect, uid, data, resolve_original=True)
    strategies = [
        {'strategy_id': spec['strategy_id'], 'version': spec['version'], 'checksum': digest,
         'counts': dict.fromkeys(('decision', 'observation', 'blocked'), 0),
         'first_blocking_reason': None}
        for spec, digest in versions
    ]
    timeline = []
    skips = Counter()
    recorded_counts = Counter()
    first_skip = None
    previous_at = None
    samples, verified = {}, {}
    for row in rows:
        if row['sample_row_id'] is not None:
            samples[(row['source'], row['sample_id'])] = row
        try:
            at = stamp(row['calculated'])
            if previous_at is not None and at < previous_at:
                raise EngineError('CALCULATION_OUT_OF_ORDER')
            previous_at = at
            calc = json.loads(row['calculation'])
            scope, snapshot_id, sample, metrics, risk, recorded, latency = _v2_snapshot(
                session, request, row, at, calc,
            )
        except (ValueError, KeyError, TypeError, AttributeError, ArithmeticError) as exc:
            reason = exc.code if isinstance(exc, EngineError) else 'INVALID_HISTORICAL_CAPTURE'
            skips[reason] += 1
            if first_skip is None:
                first_skip = {'calculation_id': row['id'], 'at': row['calculated'], 'reason': reason}
            continue
        recorded_counts[recorded['signal']] += 1
        original = _original_strategy(row, calc)
        simulated = []
        # Share verified history across alternatives with different windows.
        @lru_cache(maxsize=1)
        def history():
            return _feature_history(row, calc, request, at, samples, verified)

        for (spec, digest), summary in zip(versions, strategies):
            try:
                facts = _strategy_facts(spec, original, metrics, history, at, snapshot_id)
                result = v2.evaluate(scope, snapshot_id, at, 'entry', spec, digest, sample, facts, risk)
            except EngineError as exc:
                origin = v2.DecisionOrigin(scope.digest, snapshot_id, at.isoformat(), 'entry',
                                           spec['strategy_id'], spec['version'], digest)
                result = v2.Decision(origin, 'blocked', (exc.code,))
            summary['counts'][result.outcome] += 1
            if result.outcome == 'blocked' and summary['first_blocking_reason'] is None:
                summary['first_blocking_reason'] = {'at': row['calculated'], 'reason': result.reasons[0]}
            simulated.append({
                'strategy_id': spec['strategy_id'], 'version': spec['version'],
                'outcome': result.outcome, 'action': result.action, 'reason_codes': list(result.reasons),
                'decision_digest': result.origin.digest, 'snapshot_checksum': result.origin.snapshot_checksum,
            })
        timeline.append({
            'snapshot_id': snapshot_id, 'at': row['calculated'], 'latency': latency,
            'recorded': recorded, 'simulated': simulated,
        })

    return {
        'watch_id': session['watch_id'], 'ticker': request['ticker'], 'is_test': bool(session['is_test']),
        'limit': MAX_CALCULATIONS, 'truncated': truncated,
        'coverage': {'considered': len(rows), 'evaluated': len(timeline), 'skipped': sum(skips.values()),
                     'skip_reasons': dict(skips), 'first_skip': first_skip},
        'recorded_counts': dict(recorded_counts), 'strategies': strategies, 'timeline': timeline,
    }
