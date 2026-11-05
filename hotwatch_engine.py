"""Persistent HOT WATCH v1 session/signal engine. No trading capabilities."""
import json,os,secrets,time
from datetime import datetime,timezone
from decimal import Decimal
from hotwatch_contract import SESSION,SAMPLE,CONTEXT,ACTIVATION_BATCH,EngineError,require,canonical,checksum,stamp,OPEN_STATES,PROFILES,GLOBAL_RISK,provider_floor
from hotwatch_features import features,observation_status,verified_bar_samples
from hotwatch_strategy import BASELINE,validate_strategy,calculate

def utc():return datetime.now(timezone.utc)
def capacity():return max(1,min(20,int(os.environ.get('ESCAPE_HW_CAPACITY','20'))))
def init(c):
 c.execute('CREATE TABLE IF NOT EXISTS hw_strategies(owner_id INTEGER NOT NULL,strategy_id TEXT NOT NULL,version TEXT NOT NULL,payload TEXT NOT NULL,checksum TEXT NOT NULL,created TEXT NOT NULL,author TEXT NOT NULL,validation_status TEXT NOT NULL,PRIMARY KEY(owner_id,strategy_id,version))')
 c.execute('INSERT OR IGNORE INTO hw_strategies VALUES(0,?,?,?,?,?,?,?)',(BASELINE['strategy_id'],BASELINE['version'],canonical(BASELINE),checksum(BASELINE),utc().isoformat(),'ESCAPE builtin','baseline_tested'))
 c.execute('CREATE TABLE IF NOT EXISTS hw_sessions(id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),watch_id TEXT NOT NULL,is_test INTEGER NOT NULL,candidate_id TEXT NOT NULL,purpose TEXT NOT NULL,status TEXT NOT NULL,request TEXT NOT NULL,digest TEXT NOT NULL,strategy TEXT NOT NULL,state TEXT NOT NULL,created TEXT NOT NULL,updated TEXT NOT NULL,last_data TEXT,last_calculation TEXT,next_due REAL NOT NULL,lease_owner TEXT,lease_until REAL NOT NULL DEFAULT 0,revision INTEGER NOT NULL DEFAULT 0,failures INTEGER NOT NULL DEFAULT 0,last_error TEXT,UNIQUE(user_id,watch_id))')
 c.execute("CREATE UNIQUE INDEX IF NOT EXISTS hw_active_identity ON hw_sessions(user_id,is_test,candidate_id,purpose) WHERE status IN ('CREATED','VALIDATING','ACTIVE','PAUSED','DEGRADED')")
 c.execute('CREATE INDEX IF NOT EXISTS hw_due ON hw_sessions(status,next_due,lease_until)')
 c.execute('CREATE TABLE IF NOT EXISTS hw_samples(id INTEGER PRIMARY KEY,watch_row_id INTEGER NOT NULL REFERENCES hw_sessions(id),source TEXT NOT NULL,sample_id TEXT NOT NULL,event_epoch REAL NOT NULL,received TEXT NOT NULL,payload TEXT NOT NULL,digest TEXT NOT NULL,UNIQUE(watch_row_id,source,sample_id))')
 c.execute('CREATE TABLE IF NOT EXISTS hw_context_events(id INTEGER PRIMARY KEY,watch_row_id INTEGER NOT NULL REFERENCES hw_sessions(id),sample_row_id INTEGER REFERENCES hw_samples(id),observed TEXT NOT NULL,payload TEXT NOT NULL)')
 # Preserve unpublished checkpoint journals while allowing broker evidence before any quote.
 if any(r['name']=='sample_row_id' and r['notnull'] for r in c.execute('PRAGMA table_info(hw_context_events)')):
  c.execute('ALTER TABLE hw_context_events RENAME TO hw_context_events_legacy')
  c.execute('CREATE TABLE hw_context_events(id INTEGER PRIMARY KEY,watch_row_id INTEGER NOT NULL REFERENCES hw_sessions(id),sample_row_id INTEGER REFERENCES hw_samples(id),observed TEXT NOT NULL,payload TEXT NOT NULL)')
  c.execute('INSERT INTO hw_context_events SELECT * FROM hw_context_events_legacy')
  c.execute('DROP TABLE hw_context_events_legacy')
 c.execute('CREATE INDEX IF NOT EXISTS hw_samples_time ON hw_samples(watch_row_id,event_epoch,id)')
 c.execute('CREATE TABLE IF NOT EXISTS hw_calculations(id INTEGER PRIMARY KEY,watch_row_id INTEGER NOT NULL REFERENCES hw_sessions(id),sample_row_id INTEGER REFERENCES hw_samples(id),calculated TEXT NOT NULL,payload TEXT NOT NULL,strategy_checksum TEXT NOT NULL)')
 c.execute('CREATE TABLE IF NOT EXISTS hw_events(id INTEGER PRIMARY KEY,event_id TEXT NOT NULL UNIQUE,watch_row_id INTEGER NOT NULL REFERENCES hw_sessions(id),event_type TEXT NOT NULL,severity TEXT NOT NULL,created TEXT NOT NULL,data_timestamp TEXT,payload TEXT NOT NULL)')
 c.execute('CREATE INDEX IF NOT EXISTS hw_event_history ON hw_events(watch_row_id,id)')
 c.execute('CREATE TABLE IF NOT EXISTS hw_admin_events(id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),kind TEXT NOT NULL,created TEXT NOT NULL,payload TEXT NOT NULL)')
 c.execute('CREATE TABLE IF NOT EXISTS hw_operator_events(id INTEGER PRIMARY KEY,created TEXT NOT NULL,killed INTEGER NOT NULL,reason TEXT NOT NULL)')
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

def _create_in_transaction(c,uid,data,now):
 if len(set(data['portfolio_ids']))!=len(data['portfolio_ids']):raise EngineError('duplicate_portfolio_reference')
 if data['provider']=='synthetic' and not data['is_test']:raise EngineError('synthetic_requires_test_mode')
 if data['end_at'] and stamp(data['end_at'])<=now:raise EngineError('watch_deadline_already_passed')
 for key,maximum in GLOBAL_RISK.items():
  v=data['risk'][key]
  if Decimal(str(v))<=0 or Decimal(str(v))>Decimal(str(maximum)):raise EngineError('risk_limit_exceeds_global',400,[{'path':'risk.'+key,'code':'risk_limit','message':'Must be positive and no greater than '+str(maximum)}])
 if c.execute('SELECT killed FROM hw_system_control WHERE id=1').fetchone()[0]:raise EngineError('operator_kill_switch',409)
 old=c.execute('SELECT * FROM hw_sessions WHERE user_id=? AND watch_id=?',(uid,data['watch_id'])).fetchone()
 if old:
  if old['digest']!=checksum(data):raise EngineError('watch_id_conflict',409)
  return {'ok':True,'duplicate':True,'session':view(c,old,now)}
 if c.execute("SELECT count(*) FROM hw_sessions WHERE status IN ('CREATED','VALIDATING','ACTIVE','PAUSED','DEGRADED')").fetchone()[0]>=capacity():raise EngineError('global_capacity_limit',409)
 if c.execute("SELECT count(*) FROM hw_sessions WHERE user_id=? AND status IN ('CREATED','VALIDATING','ACTIVE','PAUSED','DEGRADED')",(uid,)).fetchone()[0]>=capacity():raise EngineError('capacity_limit',409)
 if c.execute("SELECT 1 FROM hw_sessions WHERE user_id=? AND is_test=? AND candidate_id=? AND purpose=? AND status IN ('CREATED','VALIDATING','ACTIVE','PAUSED','DEGRADED')",(uid,int(data['is_test']),data['candidate_id'],data['purpose'].strip().casefold())).fetchone():raise EngineError('active_watch_exists',409)
 report=c.execute('SELECT payload FROM ingested_reports WHERE user_id=? AND report_id=? AND is_test=?',(uid,data['report_id'],int(data['is_test']))).fetchone()
 if not report:raise EngineError('report_reference_not_found',404)
 candidate=next((x for x in json.loads(report['payload']).get('candidates',[]) if x.get('candidate_id')==data['candidate_id']),None)
 if not candidate:raise EngineError('candidate_reference_not_found',404)
 if candidate.get('ticker','').casefold()!=data['ticker'].casefold():raise EngineError('candidate_ticker_mismatch',409)
 for pid in data['portfolio_ids']:
  if not c.execute("SELECT 1 FROM portfolios WHERE id=? AND user_id=? AND active=1 AND source='pluto'",(pid,uid)).fetchone():raise EngineError('portfolio_reference_not_found')
 import candidate_lifecycle
 previous_lifecycle=candidate_lifecycle.latest(c,uid,data['is_test'],data['candidate_id'])
 if previous_lifecycle and previous_lifecycle['status'] in ['CLOSED','ARCHIVED'] and data.get('watch_mode','both')!='exit' and not data.get('reactivation_reason'):raise EngineError('reactivation_evidence_required')
 version=strategy(c,uid,data['strategy_id'],data['strategy_version'])
 if version['validation_status']!='baseline_tested':raise EngineError('strategy_qualification_required',409)
 cur=c.execute('INSERT INTO hw_sessions(user_id,watch_id,is_test,candidate_id,purpose,status,request,digest,strategy,state,created,updated,next_due) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(uid,data['watch_id'],int(data['is_test']),data['candidate_id'],data['purpose'].strip().casefold(),'CREATED',canonical(data),checksum(data),version['payload'],canonical({'signal':'NO_DATA','alert_codes':[]}),now.isoformat(),now.isoformat(),now.timestamp()))
 row=c.execute('SELECT * FROM hw_sessions WHERE id=?',(cur.lastrowid,)).fetchone();event(c,row,'WATCH_STARTED',now,data['activation_reason']);cycle=data.get('trade_cycle_id') or 'cycle:'+checksum({'watch_id':data['watch_id']})[:24];candidate_lifecycle.record(c,uid,data['is_test'],data['candidate_id'],'HOT_WATCH',now.isoformat(),data.get('reactivation_reason') or data['activation_reason'],data['watch_id'],cycle);return {'ok':True,'duplicate':False,'session':view(c,row,now)}

def create(connect,uid,data,now=None):
 now=now or utc();require(data,SESSION)
 with connect() as c:
  c.execute('BEGIN IMMEDIATE')
  return _create_in_transaction(c,uid,data,now)

def create_batch(connect,uid,data,now=None):
 """Explicit, idempotent activation request; report lifecycle alone never calls this."""
 now=now or utc()
 if not isinstance(data,dict):raise EngineError('invalid_input')
 sessions=data.get('sessions')
 if not isinstance(sessions,list) or not 1<=len(sessions)<=20:raise EngineError('activation_batch_limit_exceeded')
 outer={k:v for k,v in ACTIVATION_BATCH['properties'].items() if k!='sessions'}
 require({k:v for k,v in data.items() if k!='sessions'}, {'type':'object','properties':outer,'required':['request_id','is_test'],'additionalProperties':False})
 for item in sessions:require(item,SESSION)
 if any(item['is_test'] is not data['is_test'] for item in data['sessions']):raise EngineError('activation_category_mismatch')
 if len({item['candidate_id'] for item in data['sessions']})!=len(data['sessions']):raise EngineError('duplicate_candidate_in_activation')
 digest_value=checksum(data)
 with connect() as c:
  old=c.execute('SELECT * FROM hw_activation_requests WHERE user_id=? AND request_id=?',(uid,data['request_id'])).fetchone() if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='hw_activation_requests'").fetchone() else None
 if old:
  if old['digest']!=digest_value:raise EngineError('activation_request_conflict',409)
  return {**json.loads(old['response']),'duplicate':True}
 with connect() as c:
  c.execute('BEGIN IMMEDIATE')
  c.execute('CREATE TABLE IF NOT EXISTS hw_activation_requests(user_id INTEGER NOT NULL,request_id TEXT NOT NULL,is_test INTEGER NOT NULL,digest TEXT NOT NULL,response TEXT NOT NULL,created TEXT NOT NULL,PRIMARY KEY(user_id,request_id))')
  old=c.execute('SELECT * FROM hw_activation_requests WHERE user_id=? AND request_id=?',(uid,data['request_id'])).fetchone()
  if old:
   if old['digest']!=digest_value:raise EngineError('activation_request_conflict',409)
   return {**json.loads(old['response']),'duplicate':True}
  # Validate all items before creating any, and reserve capacity atomically.
  batch_candidates=set()
  for item in data['sessions']:
   if item['provider']=='synthetic' and not item['is_test']:raise EngineError('synthetic_requires_test_mode')
   if item['end_at'] and stamp(item['end_at'])<=now:raise EngineError('watch_deadline_already_passed')
   if item['candidate_id'] in batch_candidates:raise EngineError('duplicate_candidate_in_activation')
   batch_candidates.add(item['candidate_id'])
   if len(item['portfolio_ids'])!=len(set(item['portfolio_ids'])):raise EngineError('duplicate_portfolio_reference')
   for key,maximum in GLOBAL_RISK.items():
    value=Decimal(str(item['risk'][key]))
    if value<=0 or value>Decimal(str(maximum)):raise EngineError('risk_limit_exceeds_global',400,[{'path':'risk.'+key,'code':'risk_limit','message':'Must be positive and no greater than '+str(maximum)}])
   report=c.execute('SELECT payload FROM ingested_reports WHERE user_id=? AND report_id=? AND is_test=?',(uid,item['report_id'],int(item['is_test']))).fetchone()
   if not report:raise EngineError('report_reference_not_found',404)
   candidate=next((x for x in json.loads(report['payload']).get('candidates',[]) if x.get('candidate_id')==item['candidate_id']),None)
   if not candidate:raise EngineError('candidate_reference_not_found',404)
   if candidate.get('ticker','').casefold()!=item['ticker'].casefold():raise EngineError('candidate_ticker_mismatch',409)
   if c.execute('SELECT 1 FROM hw_sessions WHERE user_id=? AND watch_id=?',(uid,item['watch_id'])).fetchone():raise EngineError('watch_id_conflict',409)
   if c.execute("SELECT 1 FROM hw_sessions WHERE user_id=? AND is_test=? AND candidate_id=? AND purpose=? AND status IN ('CREATED','VALIDATING','ACTIVE','PAUSED','DEGRADED')",(uid,int(item['is_test']),item['candidate_id'],item['purpose'].strip().casefold())).fetchone():raise EngineError('active_watch_exists',409)
  open_count=c.execute("SELECT count(*) FROM hw_sessions WHERE status IN ('CREATED','VALIDATING','ACTIVE','PAUSED','DEGRADED')").fetchone()[0]
  own_count=c.execute("SELECT count(*) FROM hw_sessions WHERE user_id=? AND status IN ('CREATED','VALIDATING','ACTIVE','PAUSED','DEGRADED')",(uid,)).fetchone()[0]
  if open_count+len(data['sessions'])>capacity() or own_count+len(data['sessions'])>capacity():raise EngineError('activation_capacity_exceeded',409)
  batch_started=time.perf_counter();results=[]
  for item in data['sessions']:
   result=_create_in_transaction(c,uid,item,now);results.append({'candidate_id':item['candidate_id'],'watch_id':item['watch_id'],'outcome':'duplicate' if result['duplicate'] else 'created','session':result['session']})
  response={'ok':True,'request_id':data['request_id'],'duplicate':False,'results':results,'created_count':sum(x['outcome']=='created' for x in results),'batch_elapsed_ms':round((time.perf_counter()-batch_started)*1000,3)}
  c.execute('INSERT INTO hw_activation_requests VALUES(?,?,?,?,?,?)',(uid,data['request_id'],int(data['is_test']),digest_value,canonical(response),now.isoformat()))
  return response

def reported_daily_from_history(history,request,price):
 """Use only a same-instrument EODHD reference on the verified exchange day."""
 if request.get('provider')!='eodhd' or not history or history[-1].get('source')!='eodhd' or not history[-1].get('bar_evidence') or price is None:return None
 try:
  from zoneinfo import ZoneInfo
  latest=history[-1];zone=ZoneInfo(latest['bar_evidence']['timezone']);at=stamp(latest['event_time']);day=at.astimezone(zone).date()
  for prior in reversed(history[:-1]):
   if prior.get('source')!='eodhd' or prior.get('asset_id')!=latest.get('asset_id') or prior.get('currency')!=latest.get('currency') or not str(prior.get('feed_type','')).startswith('EODHD REST real-time endpoint') or not prior.get('previous_close'):continue
   reference=stamp(prior['event_time']);previous=Decimal(prior['previous_close']);current=Decimal(price)
   if reference<=at and reference.astimezone(zone).date()==day and previous>0 and current>0:return format((current/previous-1)*100,'f')
 except (KeyError,ValueError,TypeError,ArithmeticError):pass
 return None

def view(c,row,now=None):
 now=now or utc()
 request=json.loads(row['request']);state=json.loads(row['state']);sample=c.execute('SELECT payload FROM hw_samples WHERE watch_row_id=? ORDER BY id DESC LIMIT 1',(row['id'],)).fetchone();currency=json.loads(sample['payload'])['currency'] if sample else None;context=json.loads(sample['payload'])['context'] if sample else None;extra=c.execute('SELECT payload FROM hw_context_events WHERE watch_row_id=? ORDER BY id DESC LIMIT 1',(row['id'],)).fetchone()
 if extra:
  newer=json.loads(extra['payload'])
  if context is None or newer['as_of'] and (not context['as_of'] or stamp(newer['as_of'])>=stamp(context['as_of'])):context=newer
 last=c.execute('SELECT payload FROM hw_calculations WHERE watch_row_id=? ORDER BY id DESC LIMIT 1',(row['id'],)).fetchone()
 stale=not row['last_data'] or (now-stamp(row['last_data'])).total_seconds()>request['risk']['max_quote_age_s']
 display_reasons=[]
 if row['last_error']:display_reasons.append(row['last_error'])
 if stale and row['last_data']:display_reasons.append('DATA_STALE')
 effective='NO_DATA' if stale and state.get('signal') not in ['PAUSE','NO_DATA'] else state.get('signal','NO_DATA')
 if effective not in ('NO_DATA','PAUSE') and (not context or context.get('status')!='verified' or not context.get('as_of') or not 0<=(now-stamp(context['as_of'])).total_seconds()<=300):effective='NO_DATA';display_reasons.append('POSITION_CONTEXT_UNKNOWN')
 if sample and effective not in ('NO_DATA','PAUSE'):
  latest_sample=json.loads(sample['payload']);max_age=request['risk']['max_quote_age_s']
  if latest_sample['source']=='eodhd' and latest_sample['market_status']!='UNKNOWN':
   fields=['status_at']+(['bid_at','ask_at'] if effective=='BUY' else [])
   if any(not latest_sample.get(k) or not 0<=(now-stamp(latest_sample[k])).total_seconds()<=max_age for k in fields):effective='NO_DATA';display_reasons.append('MARKET_EVIDENCE_STALE')
   if latest_sample.get('bar_history'):
    from datetime import timedelta
    try:
     bar_end=stamp(latest_sample['bar_history'][-1]['bar_open_at'])+timedelta(seconds=60)
     if not 0<=(now-bar_end).total_seconds()<=max_age or not 0<=(now-stamp(latest_sample['bar_evidence']['schedule_received_at'])).total_seconds()<=max_age:effective='NO_DATA';display_reasons.append('BAR_EVIDENCE_STALE')
    except (KeyError,TypeError,ValueError,IndexError):effective='NO_DATA';display_reasons.append('BAR_EVIDENCE_STALE')
 profile=state.get('adaptive_profile',request['profile'])
 minimum=state.get('provider_floor_s',provider_floor(request['provider']))
 latest_payload=json.loads(sample['payload']) if sample else None
 if latest_payload and latest_payload.get('bar_history'):
  # Older bar arrays are not needed for quote-to-quote comparisons; omit them
  # so each dashboard refresh does not deserialize thousands of old bars.
  previous=c.execute("SELECT json_remove(payload,'$.bar_history','$.bar_evidence') AS payload FROM hw_samples WHERE watch_row_id=? AND event_epoch<? ORDER BY event_epoch DESC,id DESC LIMIT 119",(row['id'],stamp(latest_payload['event_time']).timestamp())).fetchall()
  history=[json.loads(x['payload']) for x in reversed(previous)]+[latest_payload]
 else:history=[json.loads(x['payload']) for x in reversed(c.execute('SELECT payload FROM hw_samples WHERE watch_row_id=? ORDER BY event_epoch DESC,id DESC LIMIT 120',(row['id'],)).fetchall())]
 data_status=observation_status(history,now,request['risk']['max_quote_age_s'],effective,row['status'])
 # A previous-close value from an earlier EODHD snapshot for this same watch
 # can accompany a later trade only on the same verified exchange-local date.
 # It remains a provider-reported reference, never an official-close claim.
 if data_status['daily_change_pct'] is None:
  reported_daily=reported_daily_from_history(history,request,data_status['price'])
  if reported_daily is not None:data_status.update(daily_change_pct=reported_daily,daily_change_source='EODHD reported previousClose')
 display_status={'BUY':'KØBSSIGNAL','SELL':'SÆLGSSIGNAL','REDUCE':'EXIT WATCH','WAIT':'AFVENT','NO_DATA':'DATA MANGLER','PAUSE':'DATA MANGLER'}.get(effective,'HOT WATCH')
 if effective=='NO_DATA' and data_status['price'] is not None:display_status='AFVENTER SIGNALDATA'
 return {'watch_id':row['watch_id'],'latest_currency':currency,'latest_context':context,'is_test':bool(row['is_test']),'status':row['status'],'request':request,'strategy_checksum':checksum(json.loads(row['strategy'])),'signal':effective,'display_status':display_status,'display_reason_codes':list(dict.fromkeys(display_reasons)),'data_status':data_status,'last_computed_signal':json.loads(last['payload'])['signal'] if last else 'NO_DATA','data_stale':stale,'latest_calculation':json.loads(last['payload']) if last else None,'last_data_at':row['last_data'],'last_calculation_at':row['last_calculation'],'updated_at':row['updated'],'last_error':row['last_error'],'adaptive_profile':profile,'target_interval_s':PROFILES[profile],'effective_min_interval_s':max(minimum,PROFILES[profile]),'next_due_at':datetime.fromtimestamp(row['next_due'],timezone.utc).isoformat(),'failures':row['failures']}

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
 for field in ('bid_at','ask_at','status_at'):
  if sample.get(field) and stamp(sample[field])>now:raise EngineError('future_market_data')
 if sample['source']=='eodhd' and not (request['is_test'] and sample['feed_type']=='synthetic interval bars'):
  if sample['bid'] is not None or sample['ask'] is not None:
   if not sample.get('bid_at') or not sample.get('ask_at') or not sample.get('quote_feed'):raise EngineError('quote_evidence_missing')
   if any(not 0<=(now-stamp(sample[k])).total_seconds()<=request['risk']['max_quote_age_s'] for k in ('bid_at','ask_at')):raise EngineError('quote_evidence_stale')
  if sample['market_status']!='UNKNOWN':
   if not sample.get('status_at') or not sample.get('status_feed'):raise EngineError('market_status_evidence_missing')
   if not 0<=(now-stamp(sample['status_at'])).total_seconds()<=request['risk']['max_quote_age_s']:raise EngineError('market_status_evidence_stale')
 if 'bar_history' in sample or 'bar_evidence' in sample:
  if verified_bar_samples(sample,request,now) is None:raise EngineError('bar_evidence_invalid')
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
  samples=[sample] if sample.get('bar_history') else [json.loads(r['payload']) for r in reversed(c.execute('SELECT payload FROM hw_samples WHERE watch_row_id=? ORDER BY event_epoch DESC,id DESC LIMIT 120',(row['id'],)).fetchall())]
  strategy_data=json.loads(row['strategy']);state=json.loads(row['state']);bar_samples=verified_bar_samples(sample,request,now) if sample.get('bar_history') else None
  metrics=features(bar_samples if bar_samples is not None else samples,strategy_data['parameters'])
  if bar_samples is not None:
   live_metrics=features([sample],strategy_data['parameters']);metrics.update(price=sample['price'],spread=live_metrics.get('spread'),spread_pct=live_metrics.get('spread_pct'),bar_history_count=len(bar_samples))
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
  nextstate['provider_floor_s']=provider_floor(request['provider'])
  interval=max(PROFILES[adaptive],nextstate['provider_floor_s'])
  if sample['market_status'] in ['CLOSED','HALTED']:interval=max(interval,300)
  c.execute('UPDATE hw_sessions SET status=?,state=?,updated=?,last_data=?,last_calculation=?,next_due=?,failures=0,last_error=NULL,lease_owner=NULL,lease_until=0 WHERE id=?',(new_status,canonical(nextstate),now.isoformat(),sample['event_time'],now.isoformat(),now.timestamp()+interval,row['id']))
  return {'ok':True,'duplicate':False,'calculation':result,'session':view(c,row_for(c,uid,wid,mode),now)}

def observe_context(connect,uid,wid,mode,context,now=None,lease=None):
 """Trusted adapter evidence only. Never invent a quote or advance signal confirmation."""
 now=now or utc();require(context,CONTEXT)
 if not context['as_of'] or not 0<=now.timestamp()-stamp(context['as_of']).timestamp()<=300:raise EngineError('invalid_position_context_time')
 if context['position']=='held' and (context['quantity'] is None or Decimal(context['quantity'])<=0):raise EngineError('invalid_position_quantity')
 if context['position']=='none' and context['quantity'] not in [None,'0'] and Decimal(context['quantity'])!=0:raise EngineError('invalid_position_quantity')
 with connect() as c:
  c.execute('BEGIN IMMEDIATE');row=row_for(c,uid,wid,mode);request=json.loads(row['request'])
  if lease and (row['lease_owner']!=lease or row['lease_until']<now.timestamp()):raise EngineError('lease_lost',409)
  if row['status'] not in ['CREATED','VALIDATING','ACTIVE','DEGRADED']:raise EngineError('watch_not_running',409)
  if c.execute('SELECT killed FROM hw_system_control WHERE id=1').fetchone()[0]:raise EngineError('operator_kill_switch',409)
  killed=c.execute('SELECT killed FROM hw_control WHERE user_id=?',(uid,)).fetchone()
  if killed and killed['killed']:raise EngineError('kill_switch_active',409)
  if request['provider'] not in ['pluto','synthetic']:raise EngineError('broker_context_source_required')
  if request['provider']=='synthetic' and not mode:raise EngineError('synthetic_requires_test_mode')
  if request['end_at'] and stamp(request['end_at'])<=now:raise EngineError('watch_not_running',409)
  previous=c.execute('SELECT payload FROM hw_context_events WHERE watch_row_id=? ORDER BY id DESC LIMIT 1',(row['id'],)).fetchone()
  if previous:
   old=json.loads(previous['payload'])
   if stamp(context['as_of'])<stamp(old['as_of']):raise EngineError('out_of_order_position_context',409)
   if old==context:return {'ok':True,'duplicate':True}
  c.execute('INSERT INTO hw_context_events(watch_row_id,sample_row_id,observed,payload) VALUES(?,NULL,?,?)',(row['id'],now.isoformat(),canonical(context)))
  import candidate_lifecycle
  cycle=request.get('trade_cycle_id') or 'cycle:'+checksum({'watch_id':wid})[:24]
  candidate_lifecycle.observe_pluto(c,uid,mode,request['candidate_id'],context,now.isoformat(),wid,cycle,'NO_DATA',synthetic=request['provider']=='synthetic')
  material=lambda value:{k:v for k,v in value.items() if k!='as_of'}
  if not previous or material(old)!=material(context):event(c,row,'BROKER_CONTEXT_UPDATED',now,'Verified broker context without usable market timestamp; no market signal calculated',data_time=context['as_of'])
  return {'ok':True,'duplicate':False}


def fault(connect,uid,wid,mode,code,now=None,lease=None,retry_after_s=None):
 now=now or utc()
 with connect() as c:
  c.execute('BEGIN IMMEDIATE');row=row_for(c,uid,wid,mode)
  if row['status'] not in ['CREATED','VALIDATING','ACTIVE','DEGRADED'] or lease and (row['lease_owner']!=lease or row['lease_until']<now.timestamp()):return
  request=json.loads(row['request']);state=json.loads(row['state'])
  if request['end_at'] and stamp(request['end_at'])<=now:
   c.execute("UPDATE hw_sessions SET status='EXPIRED',updated=?,lease_owner=NULL,lease_until=0 WHERE id=?",(now.isoformat(),row['id']));event(c,row,'WATCH_EXPIRED',now,'Session deadline reached');return
  if row['last_error']!=code:event(c,row,'DATA_STALE' if code=='DATA_STALE' else 'DATA_ERROR',now,code,severity='warning',data_time=row['last_data'])
  failures=min(row['failures']+1,10);floor=provider_floor(request['provider']);interval=min(1800,max(floor,PROFILES[request['profile']])*2**min(failures-1,5));state.update(signal='NO_DATA',pending=None,confirmations=0)
  if code=='PROVIDER_RATE_BUDGET':interval=60
  if retry_after_s is not None:interval=max(interval,max(0,retry_after_s))
  if row['last_error']!=code:
   previous=json.loads(row['strategy']);result={'signal':'NO_DATA','reason_codes':[code],'human_readable_explanation':code,'supporting_metrics':{'quote_age_s':(now-stamp(row['last_data'])).total_seconds() if row['last_data'] else None},'calculation_timestamp':now.isoformat(),'data_timestamp':row['last_data'],'strategy_id':previous['strategy_id'],'strategy_version':previous['version'],'strategy_checksum':checksum(previous),'confidence_score':0,'risk_level':'critical' if set(state.get('alert_codes',[]))&{'STOP_BREACHED','EXIT_DEADLINE'} else 'high','rules_score_note':'No valid current market input','critical_override':False}
   c.execute('INSERT INTO hw_calculations(watch_row_id,sample_row_id,calculated,payload,strategy_checksum) VALUES(?,NULL,?,?,?)',(row['id'],now.isoformat(),canonical(result),result['strategy_checksum']))
  state['alert_codes']=sorted(set(state.get('alert_codes',[]))|{code})
  status='ERROR' if code in ['quote_currency_mismatch','sample_identity_mismatch','PLUTO_ASSET_NOT_CONFIRMED','EODHD_RATE_LIMIT_MANUAL_REVIEW'] else 'DEGRADED'
  if status=='ERROR' and row['status']!='ERROR':event(c,row,'WATCH_ERROR',now,'Manual review required: '+code,severity='critical')
  c.execute("UPDATE hw_sessions SET status=?,state=?,last_error=?,failures=?,updated=?,next_due=?,lease_owner=NULL,lease_until=0 WHERE id=?",(status,canonical(state),code,failures,now.isoformat(),now.timestamp()+interval,row['id']))

def claim(connect,now=None,watch_id=None):
 now=now or utc();owner=secrets.token_hex(16)
 with connect() as c:
  c.execute('BEGIN IMMEDIATE')
  if c.execute('SELECT killed FROM hw_system_control WHERE id=1').fetchone()[0]:return None
  concurrency=max(1,min(10,int(os.environ.get('ESCAPE_HW_CONCURRENCY','2'))))
  if c.execute('SELECT count(*) FROM hw_sessions WHERE lease_until>?',(now.timestamp(),)).fetchone()[0]>=concurrency:return None
  row=c.execute("SELECT s.* FROM hw_sessions s JOIN users u ON u.id=s.user_id AND u.active=1 LEFT JOIN hw_control k ON k.user_id=s.user_id WHERE s.status IN ('CREATED','VALIDATING','ACTIVE','DEGRADED') AND s.next_due<=? AND s.lease_until<=? AND COALESCE(k.killed,0)=0 AND (? IS NULL OR s.watch_id=?) ORDER BY CASE json_extract(s.state,'$.adaptive_profile') WHEN 'CRITICAL' THEN 0 ELSE 1 END,CASE json_extract(s.request,'$.priority') WHEN 'CRITICAL' THEN 0 WHEN 'HIGH' THEN 1 ELSE 2 END,s.next_due,s.created,s.id LIMIT 1",(now.timestamp(),now.timestamp(),watch_id,watch_id)).fetchone()
  if not row:return None
  # Provider adapters charge the shared budget immediately before each actual
  # upstream request. Claiming a job is not itself a provider request.
  request=json.loads(row['request'])
  c.execute("UPDATE hw_sessions SET status=CASE WHEN status='CREATED' THEN 'VALIDATING' ELSE status END,lease_owner=?,lease_until=? WHERE id=?",(owner,now.timestamp()+120,row['id']))
  return dict(row,lease_owner=owner,request_data=request)

def release(connect,job,now=None):
 now=now or utc();request=job['request_data'];interval=max(PROFILES[request['profile']],provider_floor(request['provider']))
 with connect() as c:c.execute('UPDATE hw_sessions SET next_due=?,lease_owner=NULL,lease_until=0 WHERE id=? AND lease_owner=?',(now.timestamp()+interval,job['id'],job['lease_owner']))


def system_kill(connect,enabled,reason,now=None):
 """Local server-operator control only; no remote/user token endpoint."""
 now=now or utc()
 if type(enabled) is not bool or not isinstance(reason,str) or not 1<=len(reason)<=1000:raise EngineError('invalid_kill_switch')
 with connect() as c:
  c.execute('BEGIN IMMEDIATE');c.execute('UPDATE hw_system_control SET killed=?,changed=?,reason=? WHERE id=1',(int(enabled),now.isoformat(),reason))
  c.execute('INSERT INTO hw_operator_events(created,killed,reason) VALUES(?,?,?)',(now.isoformat(),int(enabled),reason))
  if enabled:
   for row in c.execute("SELECT * FROM hw_sessions WHERE status IN ('CREATED','VALIDATING','ACTIVE','DEGRADED')").fetchall():
    state=json.loads(row['state']);state.update(signal='PAUSE',pending=None,confirmations=0)
    c.execute("UPDATE hw_sessions SET status='PAUSED',state=?,updated=?,revision=revision+1,lease_owner=NULL,lease_until=0 WHERE id=?",(canonical(state),now.isoformat(),row['id']));event(c,row,'OPERATOR_KILL_SWITCH',now,reason,severity='critical')
 return {'ok':True,'killed':enabled,'auto_resumed':False}
