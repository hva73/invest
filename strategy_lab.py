"""Read-only chronological comparison of recorded HOT WATCH observations.

This is a bounded replay of saved inputs, not a trade simulation or a full
historical backtest. It never changes sessions or communicates with brokers.
"""
import copy,json
from hotwatch_contract import checksum,stamp
from hotwatch_features import features,verified_bar_samples
from hotwatch_strategy import calculate,validate_strategy,early_watch

MAX_CALCULATIONS=240


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


def compare(connect,uid,data):
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
            specs.append(spec)
        rows=c.execute('''SELECT c.id,c.calculated,c.payload AS calculation,s.id AS sample_row_id,s.received,s.digest AS sample_digest,s.payload AS sample
            FROM hw_calculations c LEFT JOIN hw_samples s ON s.id=c.sample_row_id AND s.watch_row_id=c.watch_row_id
            WHERE c.watch_row_id=? ORDER BY c.id LIMIT ?''',(row['id'],MAX_CALCULATIONS+1)).fetchall()
        request=json.loads(row['request'])
    if not rows:raise ValueError('Der er endnu ingen gemte observationer at sammenligne.')
    truncated=len(rows)>MAX_CALCULATIONS;rows=rows[:MAX_CALCULATIONS]
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
