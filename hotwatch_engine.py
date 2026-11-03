"""Persistent HOT WATCH v1 session/signal engine. No trading capabilities."""
import json,os,secrets,time
from datetime import datetime,timezone
from decimal import Decimal
from hotwatch_contract import SESSION,SAMPLE,EngineError,require,canonical,checksum,stamp,OPEN_STATES,PROFILES,GLOBAL_RISK
from hotwatch_features import features
from hotwatch_strategy import BASELINE,validate_strategy,calculate

def utc():return datetime.now(timezone.utc)
def capacity():return max(1,min(100,int(os.environ.get('ESCAPE_HW_CAPACITY','10'))))
def init(c):
 c.execute('CREATE TABLE IF NOT EXISTS hw_strategies(owner_id INTEGER NOT NULL,strategy_id TEXT NOT NULL,version TEXT NOT NULL,payload TEXT NOT NULL,checksum TEXT NOT NULL,created TEXT NOT NULL,author TEXT NOT NULL,validation_status TEXT NOT NULL,PRIMARY KEY(owner_id,strategy_id,version))')
 c.execute('INSERT OR IGNORE INTO hw_strategies VALUES(0,?,?,?,?,?,?,?)',(BASELINE['strategy_id'],BASELINE['version'],canonical(BASELINE),checksum(BASELINE),utc().isoformat(),'ESCAPE builtin','baseline_tested'))
 c.execute('CREATE TABLE IF NOT EXISTS hw_sessions(id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),watch_id TEXT NOT NULL,is_test INTEGER NOT NULL,candidate_id TEXT NOT NULL,purpose TEXT NOT NULL,status TEXT NOT NULL,request TEXT NOT NULL,digest TEXT NOT NULL,strategy TEXT NOT NULL,state TEXT NOT NULL,created TEXT NOT NULL,updated TEXT NOT NULL,last_data TEXT,last_calculation TEXT,next_due REAL NOT NULL,lease_owner TEXT,lease_until REAL NOT NULL DEFAULT 0,revision INTEGER NOT NULL DEFAULT 0,failures INTEGER NOT NULL DEFAULT 0,last_error TEXT,UNIQUE(user_id,watch_id))')
 c.execute("CREATE UNIQUE INDEX IF NOT EXISTS hw_active_identity ON hw_sessions(user_id,is_test,candidate_id,purpose) WHERE status IN ('CREATED','VALIDATING','ACTIVE','PAUSED','DEGRADED')")
 c.execute('CREATE INDEX IF NOT EXISTS hw_due ON hw_sessions(status,next_due,lease_until)')
 c.execute('CREATE TABLE IF NOT EXISTS hw_samples(id INTEGER PRIMARY KEY,watch_row_id INTEGER NOT NULL REFERENCES hw_sessions(id),source TEXT NOT NULL,sample_id TEXT NOT NULL,event_epoch REAL NOT NULL,received TEXT NOT NULL,payload TEXT NOT NULL,digest TEXT NOT NULL,UNIQUE(watch_row_id,source,sample_id))')
 c.execute('CREATE TABLE IF NOT EXISTS hw_context_events(id INTEGER PRIMARY KEY,watch_row_id INTEGER NOT NULL REFERENCES hw_sessions(id),sample_row_id INTEGER NOT NULL REFERENCES hw_samples(id),observed TEXT NOT NULL,payload TEXT NOT NULL)')
 c.execute('CREATE INDEX IF NOT EXISTS hw_samples_time ON hw_samples(watch_row_id,event_epoch,id)')
 c.execute('CREATE TABLE IF NOT EXISTS hw_calculations(id INTEGER PRIMARY KEY,watch_row_id INTEGER NOT NULL REFERENCES hw_sessions(id),sample_row_id INTEGER REFERENCES hw_samples(id),calculated TEXT NOT NULL,payload TEXT NOT NULL,strategy_checksum TEXT NOT NULL)')
 c.execute('CREATE TABLE IF NOT EXISTS hw_events(id INTEGER PRIMARY KEY,event_id TEXT NOT NULL UNIQUE,watch_row_id INTEGER NOT NULL REFERENCES hw_sessions(id),event_type TEXT NOT NULL,severity TEXT NOT NULL,created TEXT NOT NULL,data_timestamp TEXT,payload TEXT NOT NULL)')
 c.execute('CREATE INDEX IF NOT EXISTS hw_event_history ON hw_events(watch_row_id,id)')
 c.execute('CREATE TABLE IF NOT EXISTS hw_admin_events(id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),kind TEXT NOT NULL,created TEXT NOT NULL,payload TEXT NOT NULL)')
 c.execute('CREATE TABLE IF NOT EXISTS hw_system_control(id INTEGER PRIMARY KEY CHECK(id=1),killed INTEGER NOT NULL,changed TEXT NOT NULL,reason TEXT NOT NULL)')
 c.execute("INSERT OR IGNORE INTO hw_system_control VALUES(1,0,'','')")
 c.execute('CREATE TABLE IF NOT EXISTS hw_control(user_id INTEGER PRIMARY KEY REFERENCES users(id),killed INTEGER NOT NULL,changed TEXT NOT NULL,reason TEXT NOT NULL)')
 c.execute('CREATE TABLE IF NOT EXISTS hw_request_budget(user_id INTEGER NOT NULL,source TEXT NOT NULL,window INTEGER NOT NULL,used INTEGER NOT NULL,PRIMARY KEY(user_id,source,window))')
 c.execute('CREATE TABLE IF NOT EXISTS hw_provider_health(user_id INTEGER NOT NULL,is_test INTEGER NOT NULL,source TEXT NOT NULL,attempted TEXT NOT NULL,succeeded TEXT,code TEXT,payload TEXT NOT NULL,PRIMARY KEY(user_id,is_test,source))')
 c.execute('CREATE TABLE IF NOT EXISTS hw_heartbeat(id INTEGER PRIMARY KEY CHECK(id=1),updated TEXT NOT NULL,status TEXT NOT NULL)')

def event(c,row,kind,now,reason,metrics=None,severity='info',data_time=None):
 payload={'watch_id':row['watch_id'],'event_type':kind,'reason':reason,'supporting_metrics':metrics or {},'strategy_version':json.loads(row['strategy'])['version']}
 c.execute('INSERT INTO hw_events(event_id,watch_row_id,event_type,severity,created,data_timestamp,payload) VALUES(?,?,?,?,?,?,?)',('hw-'+secrets.token_hex(12),row['id'],kind,severity,now.isoformat(),data_time,canonical(payload)))

def strategy(c,uid,sid,version):
 row=c.execute('SELECT * FROM hw_strategies WHERE owner_id IN (0,?) AND strategy_id=? AND version=? ORDER BY owner_id DESC LIMIT 1',(uid,sid,version)).fetchone()
 if not row:raise EngineError('strategy_not_found',404)
 return row

def upload_strategy(connect,uid,author,data):
 errors=validate_strategy(data)
 if errors:raise EngineError('invalid_strategy',400,errors)
 with connect() as c:
  c.execute('BEGIN IMMEDIATE');old=c.execute('SELECT * FROM hw_strategies WHERE owner_id IN (0,?) AND strategy_id=? AND version=?',(uid,data['strategy_id'],data['version'])).fetchone()
  if old:
   if old['checksum']!=checksum(data):raise EngineError('strategy_version_conflict',409)
   return {'ok':True,'duplicate':True,'checksum':old['checksum']}
  c.execute('INSERT INTO hw_admin_events(user_id,kind,created,payload) VALUES(?,?,?,?)',(uid,'STRATEGY_UPLOADED',utc().isoformat(),canonical({'strategy_id':data['strategy_id'],'version':data['version'],'checksum':checksum(data),'author':author})))
  c.execute('INSERT INTO hw_strategies VALUES(?,?,?,?,?,?,?,?)',(uid,data['strategy_id'],data['version'],canonical(data),checksum(data),utc().isoformat(),author,'schema_validated'))
 return {'ok':True,'duplicate':False,'checksum':checksum(data),'validation_status':'schema_validated','deployment_status':'inactive','qualification_required':True}

def strategies(connect,uid):
 with connect() as c:rows=c.execute('SELECT owner_id,strategy_id,version,checksum,created,author,validation_status FROM hw_strategies WHERE owner_id IN (0,?) ORDER BY strategy_id,version',(uid,)).fetchall()
 return {'strategies':[dict(r,deployment_status='available_for_explicit_session_start' if r['validation_status']=='baseline_tested' else 'inactive_requires_phase3_qualification') for r in rows],'capabilities':{'declarative_upload':True,'validation':True,'version_pinning':True,'backtest':False,'shadow':False,'activation_of_uploaded_strategies':False,'rollback':False}}

def row_for(c,uid,wid,mode):
 row=c.execute('SELECT * FROM hw_sessions WHERE user_id=? AND watch_id=? AND is_test=?',(uid,wid,int(mode))).fetchone()
 if not row:raise EngineError('watch_not_found',404)
 return row

def create(connect,uid,data,now=None):
 now=now or utc();require(data,SESSION)
 if len(set(data['portfolio_ids']))!=len(data['portfolio_ids']):raise EngineError('duplicate_portfolio_reference')
 if data['provider']=='synthetic' and not data['is_test']:raise EngineError('synthetic_requires_test_mode')
 if data['end_at'] and stamp(data['end_at'])<=now:raise EngineError('watch_deadline_already_passed')
 for key,maximum in GLOBAL_RISK.items():
  v=data['risk'][key]
  if Decimal(str(v))<=0 or Decimal(str(v))>Decimal(str(maximum)):raise EngineError('risk_limit_exceeds_global',400,[{'path':'risk.'+key,'code':'risk_limit','message':'Must be positive and no greater than '+str(maximum)}])
 with connect() as c:
  c.execute('BEGIN IMMEDIATE')
  if c.execute('SELECT killed FROM hw_system_control WHERE id=1').fetchone()[0]:raise EngineError('operator_kill_switch',409)
  old=c.execute('SELECT * FROM hw_sessions WHERE user_id=? AND watch_id=?',(uid,data['watch_id'])).fetchone()
  if old:
   if old['digest']!=checksum(data):raise EngineError('watch_id_conflict',409)
   return {'ok':True,'duplicate':True,'session':view(c,old)}
  if c.execute("SELECT count(*) FROM hw_sessions WHERE status IN ('CREATED','VALIDATING','ACTIVE','PAUSED','DEGRADED')").fetchone()[0]>=capacity():raise EngineError('global_capacity_limit',409)
  if c.execute('SELECT count(*) FROM hw_sessions WHERE user_id=? AND status IN (\'CREATED\',\'VALIDATING\',\'ACTIVE\',\'PAUSED\',\'DEGRADED\')',(uid,)).fetchone()[0]>=capacity():raise EngineError('capacity_limit',409)
  if c.execute("SELECT 1 FROM hw_sessions WHERE user_id=? AND is_test=? AND candidate_id=? AND purpose=? AND status IN ('CREATED','VALIDATING','ACTIVE','PAUSED','DEGRADED')",(uid,int(data['is_test']),data['candidate_id'],data['purpose'].strip().casefold())).fetchone():raise EngineError('active_watch_exists',409)
  report=c.execute('SELECT payload FROM ingested_reports WHERE user_id=? AND report_id=? AND is_test=?',(uid,data['report_id'],int(data['is_test']))).fetchone()
  if not report:raise EngineError('report_reference_not_found',404)
  candidate=next((x for x in json.loads(report['payload']).get('candidates',[]) if x.get('candidate_id')==data['candidate_id']),None)
  if not candidate or candidate.get('ticker','').casefold()!=data['ticker'].casefold():raise EngineError('candidate_identity_mismatch')
  for pid in data['portfolio_ids']:
   if not c.execute("SELECT 1 FROM portfolios WHERE id=? AND user_id=? AND active=1 AND source='pluto'",(pid,uid)).fetchone():raise EngineError('portfolio_reference_not_found')
  import candidate_lifecycle
  previous_lifecycle=candidate_lifecycle.latest(c,uid,data['is_test'],data['candidate_id'])
  if previous_lifecycle and previous_lifecycle['status'] in ['CLOSED','ARCHIVED'] and data.get('watch_mode','both')!='exit' and not data.get('reactivation_reason'):raise EngineError('reactivation_evidence_required')
  version=strategy(c,uid,data['strategy_id'],data['strategy_version'])
  if version['validation_status']!='baseline_tested':raise EngineError('strategy_qualification_required',409)
  killed=c.execute('SELECT killed FROM hw_control WHERE user_id=?',(uid,)).fetchone()
  if killed and killed['killed']:raise EngineError('kill_switch_active',409)
  cur=c.execute('INSERT INTO hw_sessions(user_id,watch_id,is_test,candidate_id,purpose,status,request,digest,strategy,state,created,updated,next_due) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(uid,data['watch_id'],int(data['is_test']),data['candidate_id'],data['purpose'].strip().casefold(),'CREATED',canonical(data),checksum(data),version['payload'],canonical({'signal':'NO_DATA','alert_codes':[]}),now.isoformat(),now.isoformat(),now.timestamp()))
  row=c.execute('SELECT * FROM hw_sessions WHERE id=?',(cur.lastrowid,)).fetchone();event(c,row,'WATCH_STARTED',now,data['activation_reason']);cycle=data.get('trade_cycle_id') or 'cycle:'+checksum({'watch_id':data['watch_id']})[:24];candidate_lifecycle.record(c,uid,data['is_test'],data['candidate_id'],'HOT_WATCH',now.isoformat(),data.get('reactivation_reason') or data['activation_reason'],data['watch_id'],cycle);return {'ok':True,'duplicate':False,'session':view(c,row,now)}

def view(c,row,now=None):
 now=now or utc()
 request=json.loads(row['request']);state=json.loads(row['state']);sample=c.execute('SELECT payload FROM hw_samples WHERE watch_row_id=? ORDER BY id DESC LIMIT 1',(row['id'],)).fetchone();currency=json.loads(sample['payload'])['currency'] if sample else None;context=json.loads(sample['payload'])['context'] if sample else None;extra=c.execute('SELECT payload FROM hw_context_events WHERE watch_row_id=? ORDER BY id DESC LIMIT 1',(row['id'],)).fetchone()
 if extra:
  newer=json.loads(extra['payload'])
  if context is None or newer['as_of'] and (not context['as_of'] or stamp(newer['as_of'])>=stamp(context['as_of'])):context=newer
 last=c.execute('SELECT payload FROM hw_calculations WHERE watch_row_id=? ORDER BY id DESC LIMIT 1',(row['id'],)).fetchone()
 stale=not row['last_data'] or (now-stamp(row['last_data'])).total_seconds()>request['risk']['max_quote_age_s']
 effective='NO_DATA' if stale and state.get('signal') not in ['PAUSE','NO_DATA'] else state.get('signal','NO_DATA')
 profile=state.get('adaptive_profile',request['profile'])
 minimum={'pluto':300,'eodhd':300,'report_inbox':60,'synthetic':5}[request['provider']]
 return {'watch_id':row['watch_id'],'latest_currency':currency,'latest_context':context,'is_test':bool(row['is_test']),'status':row['status'],'request':request,'strategy_checksum':checksum(json.loads(row['strategy'])),'signal':effective,'last_computed_signal':json.loads(last['payload'])['signal'] if last else 'NO_DATA','data_stale':stale,'latest_calculation':json.loads(last['payload']) if last else None,'last_data_at':row['last_data'],'last_calculation_at':row['last_calculation'],'updated_at':row['updated'],'last_error':row['last_error'],'adaptive_profile':profile,'target_interval_s':PROFILES[profile],'effective_min_interval_s':max(minimum,PROFILES[profile]),'next_due_at':datetime.fromtimestamp(row['next_due'],timezone.utc).isoformat(),'failures':row['failures']}

def sessions(connect,uid,mode=False,after=0,limit=50):
 with connect() as c:
  rows=c.execute('SELECT * FROM hw_sessions WHERE user_id=? AND is_test=? AND id>? ORDER BY id LIMIT ?',(uid,int(mode),after,limit+1)).fetchall();control=c.execute('SELECT killed,reason,changed FROM hw_control WHERE user_id=?',(uid,)).fetchone();beat=c.execute('SELECT updated,status FROM hw_heartbeat WHERE id=1').fetchone()
  return {'sessions':[view(c,r) for r in rows[:limit]],'next_cursor':rows[limit-1]['id'] if len(rows)>limit else None,'is_test':mode,'operator_kill_switch':bool(c.execute('SELECT killed FROM hw_system_control WHERE id=1').fetchone()[0]),'kill_switch':dict(control) if control else {'killed':0,'reason':'','changed':None},'worker':dict(beat) if beat else None,'capacity':capacity(),'phase':'1-2','deferred':['backtest','shadow','qualified strategy activation/rollback']}

def item(connect,uid,wid,mode=False):
 with connect() as c:return {'session':view(c,row_for(c,uid,wid,mode))}

def control(connect,uid,wid,mode,action,now=None):
 now=now or utc()
 with connect() as c:
  c.execute('BEGIN IMMEDIATE');row=row_for(c,uid,wid,mode);status=row['status']
  if action=='pause':new='PAUSED'
  elif action=='resume':
   if c.execute('SELECT killed FROM hw_system_control WHERE id=1').fetchone()[0]:raise EngineError('operator_kill_switch',409)
   killed=c.execute('SELECT killed FROM hw_control WHERE user_id=?',(uid,)).fetchone()
   if killed and killed['killed']:raise EngineError('kill_switch_active',409)
   request=json.loads(row['request'])
   if request['end_at'] and stamp(request['end_at'])<=now:raise EngineError('watch_expired',409)
   new='VALIDATING'
  elif action=='stop':new='COMPLETED'
  else:raise EngineError('unknown_action')
  if status==new or action=='resume' and status in ['VALIDATING','ACTIVE']:return {'ok':True,'duplicate':True,'session':view(c,row,now)}
  if status in ['EXPIRED','COMPLETED','ERROR']:raise EngineError('watch_is_terminal',409)
  c.execute('UPDATE hw_sessions SET status=?,updated=?,revision=revision+1,lease_owner=NULL,lease_until=0,next_due=?,state=? WHERE id=?',(new,now.isoformat(),now.timestamp(),canonical({**json.loads(row['state']),'signal':'PAUSE' if action=='pause' else 'NO_DATA','pending':None,'confirmations':0}),row['id']))
  event(c,row,{'pause':'WATCH_PAUSED','resume':'WATCH_RESUMED','stop':'WATCH_COMPLETED'}[action],now,action)
  return {'ok':True,'duplicate':False,'session':view(c,row_for(c,uid,wid,mode),now)}

def kill(connect,uid,enabled,reason,now=None):
 now=now or utc()
 if type(enabled) is not bool or not isinstance(reason,str) or not 1<=len(reason)<=1000:raise EngineError('invalid_kill_switch')
 with connect() as c:
  c.execute('BEGIN IMMEDIATE');old=c.execute('SELECT killed,reason FROM hw_control WHERE user_id=?',(uid,)).fetchone()
  if old and old['killed']==int(enabled) and old['reason']==reason:return {'ok':True,'duplicate':True}
  c.execute('INSERT INTO hw_admin_events(user_id,kind,created,payload) VALUES(?,?,?,?)',(uid,'KILL_SWITCH_ENABLED' if enabled else 'KILL_SWITCH_DISABLED',now.isoformat(),canonical({'reason':reason})))
  c.execute('INSERT INTO hw_control VALUES(?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET killed=excluded.killed,changed=excluded.changed,reason=excluded.reason',(uid,int(enabled),now.isoformat(),reason))
  if enabled:
   rows=c.execute("SELECT * FROM hw_sessions WHERE user_id=? AND status IN ('CREATED','VALIDATING','ACTIVE','DEGRADED')",(uid,)).fetchall()
   for row in rows:
    state=json.loads(row['state']);state.update(signal='PAUSE',pending=None,confirmations=0)
    c.execute("UPDATE hw_sessions SET status='PAUSED',state=?,updated=?,revision=revision+1,lease_owner=NULL,lease_until=0 WHERE id=?",(canonical(state),now.isoformat(),row['id']));event(c,row,'KILL_SWITCH',now,reason,severity='critical')
 return {'ok':True,'duplicate':False,'killed':enabled,'note':'Disabling the switch does not resume sessions automatically.'}

def history(connect,uid,wid,mode=False,kind='events',after=0,limit=50,order='asc'):
 if kind not in ['events','signals','metrics','history','samples']:raise EngineError('unknown_history')
 with connect() as c:
  row=row_for(c,uid,wid,mode)
  table='hw_events' if kind in ['events','history'] else 'hw_samples' if kind=='samples' else 'hw_calculations'
  if order not in ['asc','desc']:raise EngineError('invalid_order')
  bound=' AND id'+('>' if order=='asc' else '<')+'?' if after or order=='asc' else ''
  args=[row['id']]+([after] if bound else [])+[limit+1]
  rows=c.execute('SELECT * FROM '+table+' WHERE watch_row_id=?'+bound+' ORDER BY id '+order+' LIMIT ?',args).fetchall()
  result=[]
  for r in rows[:limit]:
   data=dict(r);data['data']=json.loads(data.pop('payload'));result.append(data)
  return {'items':result,'next_cursor':rows[limit-1]['id'] if len(rows)>limit else None,'watch_id':wid,'is_test':mode,'kind':kind}

def sample_errors(sample,request,now):
 require(sample,SAMPLE)
 if sample['source']!=request['provider'] or sample['asset_id']!=request['asset_id'] or sample['ticker'].casefold()!=request['ticker'].casefold():raise EngineError('sample_identity_mismatch')
 if sample['source']=='synthetic' and not request['is_test']:raise EngineError('synthetic_requires_test_mode')
 if sample['currency']!=request['quote_currency']:raise EngineError('quote_currency_mismatch')
 if sample['price'] is not None and Decimal(sample['price'])<=0:raise EngineError('invalid_price')
 if sample['bid'] is not None and sample['ask'] is not None and Decimal(sample['bid'])>Decimal(sample['ask']):raise EngineError('crossed_market')
 if sample['price'] is not None and sample['close'] is not None and Decimal(sample['price'])!=Decimal(sample['close']):raise EngineError('price_close_basis_mismatch')
 if all(sample[k] is not None for k in ['open','high','low','close']):
  if Decimal(sample['low'])>min(Decimal(sample['open']),Decimal(sample['close'])) or Decimal(sample['high'])<max(Decimal(sample['open']),Decimal(sample['close'])) or Decimal(sample['low'])>Decimal(sample['high']):raise EngineError('invalid_ohlc')
 if stamp(sample['event_time'])>now:raise EngineError('future_market_data')
 context=sample['context']
 if context['as_of'] and stamp(context['as_of'])>now:raise EngineError('future_position_context')
 if context['position']=='held' and (context['quantity'] is None or Decimal(context['quantity'])<=0):raise EngineError('invalid_position_quantity')
 if context['position']=='none' and context['quantity'] is not None and Decimal(context['quantity'])!=0:raise EngineError('invalid_position_quantity')
 return sample

def ingest(connect,uid,wid,mode,sample,now=None,lease=None):
 now=now or utc()
 with connect() as c:
  c.execute('BEGIN IMMEDIATE');row=row_for(c,uid,wid,mode);request=json.loads(row['request'])
  if lease and (row['lease_owner']!=lease or row['lease_until']<now.timestamp()):raise EngineError('lease_lost',409)
  if row['status'] not in ['CREATED','VALIDATING','ACTIVE','DEGRADED']:raise EngineError('watch_not_running',409)
  killed=c.execute('SELECT killed FROM hw_control WHERE user_id=?',(uid,)).fetchone()
  if killed and killed['killed']:raise EngineError('kill_switch_active',409)
  if c.execute('SELECT killed FROM hw_system_control WHERE id=1').fetchone()[0]:raise EngineError('operator_kill_switch',409)
  if request['end_at'] and stamp(request['end_at'])<=now:
   c.execute("UPDATE hw_sessions SET status='EXPIRED',updated=?,lease_owner=NULL,lease_until=0 WHERE id=?",(now.isoformat(),row['id']));event(c,row,'WATCH_EXPIRED',now,'Session deadline reached');return {'ok':True,'expired':True}
  sample_errors(sample,request,now)
  old=c.execute('SELECT id,digest,payload FROM hw_samples WHERE watch_row_id=? AND source=? AND sample_id=?',(row['id'],sample['source'],sample['sample_id'])).fetchone()
  if old is None and row['last_data'] and stamp(sample['event_time'])==stamp(row['last_data']):old=c.execute('SELECT id,digest,payload FROM hw_samples WHERE watch_row_id=? AND source=? AND event_epoch=? ORDER BY id DESC LIMIT 1',(row['id'],sample['source'],stamp(sample['event_time']).timestamp())).fetchone()
  new_market_event=True
  if old:
   if row['last_data'] and stamp(json.loads(old['payload'])['event_time'])!=stamp(row['last_data']):raise EngineError('historical_sample_context_update',409)
   previous_sample=json.loads(old['payload'])
   previous_market={k:v for k,v in previous_sample.items() if k not in ['context','sample_id']};current_market={k:v for k,v in sample.items() if k not in ['context','sample_id']}
   if previous_market!=current_market:raise EngineError('sample_id_conflict',409)
   extra=c.execute('SELECT payload FROM hw_context_events WHERE watch_row_id=? ORDER BY id DESC LIMIT 1',(row['id'],)).fetchone()
   prior_context=json.loads(extra['payload']) if extra else previous_sample['context'];current_context=sample['context']
   material=lambda context:{k:v for k,v in context.items() if k!='as_of'}
   fresh=lambda context:bool(context['as_of'] and 0<=now.timestamp()-stamp(context['as_of']).timestamp()<=300)
   if material(prior_context)==material(current_context) and fresh(prior_context)==fresh(current_context):return {'ok':True,'duplicate':True,'session':view(c,row,now)}
   c.execute('INSERT INTO hw_context_events(watch_row_id,sample_row_id,observed,payload) VALUES(?,?,?,?)',(row['id'],old['id'],now.isoformat(),canonical(current_context)))
   event(c,row,'BROKER_CONTEXT_UPDATED',now,'Position/order context changed; no new market observation',data_time=current_context['as_of'])
   sample_row_id=old['id'];new_market_event=False
  else:
   if row['last_data'] and stamp(sample['event_time'])<=stamp(row['last_data']):raise EngineError('out_of_order_market_data',409)
   cur=c.execute('INSERT INTO hw_samples(watch_row_id,source,sample_id,event_epoch,received,payload,digest) VALUES(?,?,?,?,?,?,?)',(row['id'],sample['source'],sample['sample_id'],stamp(sample['event_time']).timestamp(),now.isoformat(),canonical(sample),checksum(sample)))
   sample_row_id=cur.lastrowid
  samples=[json.loads(r['payload']) for r in reversed(c.execute('SELECT payload FROM hw_samples WHERE watch_row_id=? ORDER BY event_epoch DESC,id DESC LIMIT 120',(row['id'],)).fetchall())]
  strategy_data=json.loads(row['strategy']);state=json.loads(row['state']);metrics=features(samples,strategy_data['parameters'])
  import intel_workflows,candidate_lifecycle
  decision=intel_workflows.prior_decision(c,uid,mode,request['candidate_id'])
  risk=dict(request['risk'],entry_allowed=request.get('watch_mode','both')!='exit' and (not decision or decision[1]['status']!='FRAVÆLG'),exit_allowed=request.get('watch_mode','both')!='entry')
  result,nextstate=calculate(sample,metrics,strategy_data,risk,state,now,new_market_event=new_market_event)
  result['position_context']=sample['context'];result['new_market_observation']=new_market_event
  result.update(engine_version='1.0-phase1-2',feature_version='1.0.0',risk_version='1.0.0',global_risk_limits=GLOBAL_RISK,algorithm_constraints={'max_volatility_pct':'5','max_price_gap_pct':'5','max_action_signals_hour':20,'max_context_age_s':300},risk_parameters=risk,prior_signal_state=state,input_sample_ids=[s['sample_id'] for s in samples])
  metrics['quote_age_s']=format(Decimal(str(now.timestamp()-stamp(sample['event_time']).timestamp())),'f');result['supporting_metrics']=metrics
  c.execute('INSERT INTO hw_calculations(watch_row_id,sample_row_id,calculated,payload,strategy_checksum) VALUES(?,?,?,?,?)',(row['id'],sample_row_id,now.isoformat(),canonical(result),result['strategy_checksum']))
  cycle=request.get('trade_cycle_id') or 'cycle:'+checksum({'watch_id':wid})[:24]
  if result['signal']=='BUY' and state.get('signal')!='BUY':candidate_lifecycle.record(c,uid,mode,request['candidate_id'],'BUY_SIGNAL',now.isoformat(),'Deterministisk motor, ikke en udført handel',wid,cycle)
  if sample['source']!='report_inbox':candidate_lifecycle.observe_pluto(c,uid,mode,request['candidate_id'],sample['context'],now.isoformat(),wid,cycle,result['signal'],synthetic=sample['source']=='synthetic')
  new_status='DEGRADED' if result['signal'] in ['NO_DATA','PAUSE'] else 'ACTIVE'
  codes=set(result['reason_codes'])&{'DATA_UNVERIFIED','DATA_STALE','DATA_FUTURE','MARKET_HALTED','MARKET_CLOSED','MARKET_STATUS_UNKNOWN','POSITION_CONTEXT_UNKNOWN','SPREAD_TOO_WIDE','SPREAD_UNKNOWN','LOSS_BUDGET_LIMIT','POSITION_SIZE_LIMIT','EXPOSURE_LIMIT','STOP_BREACHED','EXIT_DEADLINE','RISK_INPUTS_UNKNOWN'}
  oldcodes=set(state.get('alert_codes',[]))
  for code in sorted(codes-oldcodes):event(c,row,'DATA_STALE' if code=='DATA_STALE' else 'RISK_REJECTION',now,code,metrics,'critical' if code in ['STOP_BREACHED','EXIT_DEADLINE'] else 'warning',sample['event_time'])
  if oldcodes-codes:event(c,row,'DATA_RECOVERED',now,';'.join(sorted(oldcodes-codes)),metrics,data_time=sample['event_time'])
  if result['signal']!=state.get('signal','NO_DATA'):event(c,row,{'BUY':'BUY_SIGNAL','SELL':'SELL_SIGNAL','REDUCE':'REDUCE_SIGNAL','WAIT':'WAIT_SIGNAL','NO_DATA':'NO_DATA','PAUSE':'WATCH_PAUSED'}[result['signal']],now,result['human_readable_explanation'],metrics,'critical' if result['critical_override'] else 'info',sample['event_time'])
  if result['critical_override'] and state.get('signal')!='SELL':event(c,row,'CRITICAL_OVERRIDE',now,'Critical exit bypassed confirmation/cooldown; no order created',metrics,'critical',sample['event_time'])
  for key,kind in [('breakout','BREAKOUT_DETECTED'),('rising_price_falling_volume','MOMENTUM_WEAKENING')]:
   if metrics.get(key) and not state.get('feature_'+key):event(c,row,kind,now,key,metrics,data_time=sample['event_time'])
   nextstate['feature_'+key]=bool(metrics.get(key))
  if metrics.get('relative_volume') is not None and Decimal(metrics['relative_volume'])>=Decimal('2') and not state.get('volume_spike'):event(c,row,'VOLUME_SPIKE',now,'Relative interval volume >= 2',metrics,data_time=sample['event_time'])
  nextstate['volume_spike']=metrics.get('relative_volume') is not None and Decimal(metrics['relative_volume'])>=2
  previous_orders=state.get('orders',{})
  for order in sample['context']['orders']:
   before=previous_orders.get(order['order_id']);filled=order['filled_quantity']
   if sample['context']['status']=='verified' and filled is not None and Decimal(filled)>0 and (before is None or Decimal(filled)>Decimal(before or '0')):event(c,row,'ORDER_FILLED',now,'Provider-reported quantity; signal is separate from order execution',{'order_id':order['order_id'],'filled_quantity':filled,'status':order['status']},data_time=sample['context']['as_of'])
  nextstate.update(alert_codes=sorted(codes),orders={o['order_id']:o['filled_quantity'] for o in sample['context']['orders']})
  adaptive='CRITICAL' if result['risk_level']=='critical' else 'ACTIVE' if metrics.get('breakout') or nextstate.get('volume_spike') else 'IDLE' if sample['market_status'] in ['CLOSED','HALTED'] else request['profile']
  nextstate['adaptive_profile']=adaptive
  interval=max(PROFILES[adaptive],{'pluto':300,'eodhd':300,'report_inbox':60,'synthetic':5}[request['provider']])
  if sample['market_status'] in ['CLOSED','HALTED']:interval=max(interval,300)
  c.execute('UPDATE hw_sessions SET status=?,state=?,updated=?,last_data=?,last_calculation=?,next_due=?,failures=0,last_error=NULL,lease_owner=NULL,lease_until=0 WHERE id=?',(new_status,canonical(nextstate),now.isoformat(),sample['event_time'],now.isoformat(),now.timestamp()+interval,row['id']))
  return {'ok':True,'duplicate':False,'calculation':result,'session':view(c,row_for(c,uid,wid,mode),now)}

def fault(connect,uid,wid,mode,code,now=None,lease=None,retry_after_s=None):
 now=now or utc()
 with connect() as c:
  c.execute('BEGIN IMMEDIATE');row=row_for(c,uid,wid,mode)
  if row['status'] not in ['CREATED','VALIDATING','ACTIVE','DEGRADED'] or lease and (row['lease_owner']!=lease or row['lease_until']<now.timestamp()):return
  request=json.loads(row['request']);state=json.loads(row['state'])
  if request['end_at'] and stamp(request['end_at'])<=now:
   c.execute("UPDATE hw_sessions SET status='EXPIRED',updated=?,lease_owner=NULL,lease_until=0 WHERE id=?",(now.isoformat(),row['id']));event(c,row,'WATCH_EXPIRED',now,'Session deadline reached');return
  if row['last_error']!=code:event(c,row,'DATA_STALE' if code=='DATA_STALE' else 'DATA_ERROR',now,code,severity='warning',data_time=row['last_data'])
  failures=min(row['failures']+1,10);floor={'pluto':300,'eodhd':300,'report_inbox':60,'synthetic':5}[request['provider']];interval=min(1800,max(floor,PROFILES[request['profile']])*2**min(failures-1,5));state.update(signal='NO_DATA',pending=None,confirmations=0)
  if retry_after_s is not None:interval=max(interval,max(0,retry_after_s))
  if row['last_error']!=code:
   previous=json.loads(row['strategy']);result={'signal':'NO_DATA','reason_codes':[code],'human_readable_explanation':code,'supporting_metrics':{'quote_age_s':(now-stamp(row['last_data'])).total_seconds() if row['last_data'] else None},'calculation_timestamp':now.isoformat(),'data_timestamp':row['last_data'],'strategy_id':previous['strategy_id'],'strategy_version':previous['version'],'strategy_checksum':checksum(previous),'confidence_score':0,'risk_level':'critical' if set(state.get('alert_codes',[]))&{'STOP_BREACHED','EXIT_DEADLINE'} else 'high','rules_score_note':'No valid current market input','critical_override':False}
   c.execute('INSERT INTO hw_calculations(watch_row_id,sample_row_id,calculated,payload,strategy_checksum) VALUES(?,NULL,?,?,?)',(row['id'],now.isoformat(),canonical(result),result['strategy_checksum']))
  state['alert_codes']=sorted(set(state.get('alert_codes',[]))|{code})
  status='ERROR' if code in ['quote_currency_mismatch','sample_identity_mismatch','PLUTO_ASSET_NOT_CONFIRMED','EODHD_RATE_LIMIT_MANUAL_REVIEW'] else 'DEGRADED'
  if status=='ERROR' and row['status']!='ERROR':event(c,row,'WATCH_ERROR',now,'Manual review required: '+code,severity='critical')
  c.execute("UPDATE hw_sessions SET status=?,state=?,last_error=?,failures=?,updated=?,next_due=?,lease_owner=NULL,lease_until=0 WHERE id=?",(status,canonical(state),code,failures,now.isoformat(),now.timestamp()+interval,row['id']))

def claim(connect,now=None):
 now=now or utc();owner=secrets.token_hex(16)
 with connect() as c:
  c.execute('BEGIN IMMEDIATE')
  if c.execute('SELECT killed FROM hw_system_control WHERE id=1').fetchone()[0]:return None
  concurrency=max(1,min(10,int(os.environ.get('ESCAPE_HW_CONCURRENCY','2'))))
  if c.execute('SELECT count(*) FROM hw_sessions WHERE lease_until>?',(now.timestamp(),)).fetchone()[0]>=concurrency:return None
  row=c.execute("SELECT s.* FROM hw_sessions s JOIN users u ON u.id=s.user_id AND u.active=1 LEFT JOIN hw_control k ON k.user_id=s.user_id WHERE s.status IN ('CREATED','VALIDATING','ACTIVE','DEGRADED') AND s.next_due<=? AND s.lease_until<=? AND COALESCE(k.killed,0)=0 ORDER BY CASE json_extract(s.request,'$.priority') WHEN 'CRITICAL' THEN 0 WHEN 'HIGH' THEN 1 ELSE 2 END,s.next_due,s.id LIMIT 1",(now.timestamp(),now.timestamp())).fetchone()
  if not row:return None
  request=json.loads(row['request']);window=int(now.timestamp()//60);budget=max(1,min(120,int(os.environ.get('ESCAPE_HW_REQUESTS_PER_MINUTE','12'))))
  c.execute('DELETE FROM hw_request_budget WHERE window<?',(window-2,))
  used=c.execute('SELECT used FROM hw_request_budget WHERE user_id=? AND source=? AND window=?',(row['user_id'],request['provider'],window)).fetchone()
  if used and used['used']>=budget:
   c.execute('UPDATE hw_sessions SET next_due=? WHERE id=?',((window+1)*60,row['id']));return None
  c.execute('INSERT INTO hw_request_budget VALUES(?,?,?,1) ON CONFLICT(user_id,source,window) DO UPDATE SET used=used+1',(row['user_id'],request['provider'],window))
  c.execute("UPDATE hw_sessions SET status=CASE WHEN status='CREATED' THEN 'VALIDATING' ELSE status END,lease_owner=?,lease_until=? WHERE id=?",(owner,now.timestamp()+120,row['id']))
  return dict(row,lease_owner=owner,request_data=request)

def release(connect,job,now=None):
 now=now or utc();request=job['request_data'];interval=max(PROFILES[request['profile']],{'pluto':300,'eodhd':300,'report_inbox':60,'synthetic':5}[request['provider']])
 with connect() as c:c.execute('UPDATE hw_sessions SET next_due=?,lease_owner=NULL,lease_until=0 WHERE id=? AND lease_owner=?',(now.timestamp()+interval,job['id'],job['lease_owner']))


def system_kill(connect,enabled,reason,now=None):
 """Local server-operator control only; no remote/user token endpoint."""
 now=now or utc()
 if type(enabled) is not bool or not isinstance(reason,str) or not 1<=len(reason)<=1000:raise EngineError('invalid_kill_switch')
 with connect() as c:
  c.execute('BEGIN IMMEDIATE');c.execute('UPDATE hw_system_control SET killed=?,changed=?,reason=? WHERE id=1',(int(enabled),now.isoformat(),reason))
  if enabled:
   for row in c.execute("SELECT * FROM hw_sessions WHERE status IN ('CREATED','VALIDATING','ACTIVE','DEGRADED')").fetchall():
    state=json.loads(row['state']);state.update(signal='PAUSE',pending=None,confirmations=0)
    c.execute("UPDATE hw_sessions SET status='PAUSED',state=?,updated=?,revision=revision+1,lease_owner=NULL,lease_until=0 WHERE id=?",(canonical(state),now.isoformat(),row['id']));event(c,row,'OPERATOR_KILL_SWITCH',now,reason,severity='critical')
 return {'ok':True,'killed':enabled,'auto_resumed':False}
