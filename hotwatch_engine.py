"""Persistent HOT WATCH v1 session/signal engine. No trading capabilities."""
import json,os,secrets,time,hashlib,re
from contextlib import nullcontext
from datetime import datetime,timezone,timedelta
from decimal import Decimal
from hotwatch_contract import SESSION,SAMPLE,CONTEXT,ACTIVATION_BATCH,EngineError,require,canonical,checksum,stamp,OPEN_STATES,PROFILES,GLOBAL_RISK,provider_floor
from hotwatch_features import features,observation_status,verified_bar_samples
from hotwatch_strategy import BASELINE,EARLY_CATALYST,EARLY_CATALYST_V1,validate_strategy,calculate

def utc():return datetime.now(timezone.utc)

def trailing_notification_worsened(price,anchor,trailing_pct):
 """Escalate each further decline of one configured trailing distance."""
 return Decimal(str(price))<=Decimal(str(anchor))*(Decimal('1')-Decimal(str(trailing_pct))/Decimal('100'))

def capacity():
 try:return max(1,int(os.environ.get('ESCAPE_HW_CAPACITY','60')))
 except (TypeError,ValueError):return 40

def reported_catalyst_priority_until(candidate,now,max_age_minutes=None):
 """Short queue priority from attributed report evidence; never a trade gate."""
 try:
  proposal=candidate.get('strategy_proposal') or {};news=proposal.get('news_check') or {};catalyst=proposal.get('catalyst') or {}
  if proposal.get('strategy_id')!='escape_early_catalyst' or news.get('status')!='verified_news':return None
  if not set(news.get('source_ids') or []).intersection(catalyst.get('source_ids') or []):return None
  published=stamp(catalyst['published_at']);available=stamp(catalyst['available_at']);checked=stamp(news['checked_at']);proposed=stamp(proposal['proposed_at'])
  if not published<=available<=proposed<=now or not available<=checked<=proposed:return None
  minutes=EARLY_CATALYST_V1['parameters']['news_max_age_minutes'] if max_age_minutes is None else max_age_minutes
  if type(minutes) is not int or not 1<=minutes<=1440:return None
  expiry=published+timedelta(minutes=minutes)
  return expiry.timestamp() if published<=now<expiry else None
 except (KeyError,TypeError,ValueError,OverflowError):return None

def valid_cxe_evidence(c,uid,request,now):
 """None means no CXE proof; False means proof exists but cannot be used."""
 row=c.execute('SELECT * FROM hw_cxe_feed_evidence WHERE user_id=? AND asset_id=?',(uid,request.get('asset_id'))).fetchone()
 if not row:return None
 try:
  data=json.loads(row['payload']);pluto=data['pluto']
  link=c.execute('SELECT isin,currency,symbol FROM hw_verified_feed_links WHERE user_id=? AND asset_id=?',(uid,request.get('asset_id'))).fetchone()
  keys=(('asset_id','asset_id'),('ticker','ticker'),('exchange','exchange'),('currency','quote_currency'))
  common=bool(row['status']=='MATCHED' and row['symbol']==request.get('provider_symbol') and 0<=now.timestamp()-row['verified_epoch']<=7*86400 and data.get('symbol')==row['symbol'] and all(pluto.get(a) and str(pluto[a]).casefold()==str(request.get(b,'')).casefold() for a,b in keys) and link and link['symbol']==row['symbol'] and link['isin']==data.get('isin') and link['currency']==data.get('currency')==request.get('quote_currency'))
  if not common:return False
  if data.get('basis')=='user_authorized_btc_monitoring':
   from instrument_resolver import crypto_reference
   ref=crypto_reference(pluto)
   return bool(ref and ref['approved'] and ref['symbol']==row['symbol'] and request.get('watch_mode')=='exit' and request.get('purpose')=='automatic holding watch' and data.get('isin')=='' and data.get('currency')=='USD')
  if data.get('basis')=='pluto_asset_cxe_security_reference_eodhd_isin':
   source=stamp(data['reference_created_at'])
   if data.get('reference_source')!='https://accounteu.cboe.com/cxe/market_data/symbol_listing/csv/' or not -300<=(now-source).total_seconds()<=72*3600:return False
  if data.get('basis')=='pluto_asset_cxe_security_reference_eodhd_isin':return data.get('cxe_asset_class')=='EQTY' and pluto.get('type')=='CS'
  if data.get('basis') in ('pluto_asset_us_catalog_cxe_security_isin','pluto_asset_us_listing'):
   from instrument_resolver import same_us_class_ticker
   received=stamp(data['catalog_received_at'])
   return bool(-300<=(now-received).total_seconds()<=7*86400 and data.get('catalog_source')=='https://eodhd.com/api/exchange-symbol-list/US' and pluto.get('type') in ('CS','ADRC') and data.get('pluto_type')==pluto.get('type') and data.get('catalog_type')=='Common Stock' and data.get('catalog_exchange')==request.get('exchange') and same_us_class_ticker(data.get('catalog_ticker'),request.get('ticker')) and data.get('symbol')==data.get('catalog_ticker')+'.US' and (data.get('basis')=='pluto_asset_us_listing' or data.get('cxe_symbols')))
  return False
 except (KeyError,ValueError,TypeError,AttributeError):return False

def verified_automatic_feed(c,uid,request,now):
 """Require a current asset-bound mapping before automatic EODHD signals."""
 try:
  row=c.execute('SELECT * FROM hw_verified_feed_links WHERE user_id=? AND asset_id=?',(uid,request.get('asset_id'))).fetchone()
  if not row or row['symbol']!=request.get('provider_symbol') or str(row['ticker']).casefold()!=str(request.get('ticker','')).casefold() or row['currency']!=request.get('quote_currency') or str(row['exchange']).casefold()!=str(request.get('exchange','')).casefold() or not 0<=now.timestamp()-row['verified_epoch']<=7*86400:return False
  evidence=valid_cxe_evidence(c,uid,request,now)
  return bool(evidence is True or evidence is None and isinstance(row['isin'],str) and re.fullmatch('[A-Z]{2}[A-Z0-9]{9}[0-9]',row['isin']))
 except (KeyError,ValueError,TypeError,AttributeError):return False

def provider_request_limit(source):
 if source=='eodhd':
  from eodhd_capacity import configured_limit
  return configured_limit()
 try:return max(1,min(120,int(os.environ.get('ESCAPE_HW_REQUESTS_PER_MINUTE','12'))))
 except (TypeError,ValueError):return 12

def effective_poll_interval(c,request,profile=None):
 """Use existing profiles and actual HTTP capacity, not WebSocket call counts."""
 source=request['provider'];profile=profile or request['profile']
 floor=provider_floor(source)
 from instrument_resolver import BTC_PLUTO_ASSET_ID
 if source=='eodhd' and request.get('purpose')=='automatic holding watch' and request.get('asset_id')==BTC_PLUTO_ASSET_ID and request.get('provider_symbol')=='BTC-USD.CC' and os.environ.get('ESCAPE_HW_EODHD_FAST_POLL_ENABLED')!='1':floor=60
 minimum=max(PROFILES.get(profile,PROFILES[request['profile']]),floor)
 if source!='eodhd':return minimum
 from eodhd_capacity import http_limit
 limit=http_limit(c)
 ws=os.environ.get('ESCAPE_HW_EODHD_WS_TRADES_ENABLED')=='1' and os.environ.get('ESCAPE_HW_EODHD_FUSE_ENABLED')=='1'
 bars=os.environ.get('ESCAPE_HW_EODHD_BARS_ENABLED')=='1'
 eu={x.strip().upper() for x in os.environ.get('ESCAPE_HW_EODHD_WS_EU_EXCHANGES','CO,XETRA,AS').split(',') if re.fullmatch(r'[A-Za-z0-9_-]{1,16}',x.strip())}-{'CC'}
 rows=c.execute("SELECT s.is_test,s.request,p.symbol AS provisional_symbol FROM hw_sessions s LEFT JOIN hw_provisional_feed_links p ON p.watch_row_id=s.id WHERE s.status IN ('CREATED','VALIDATING','ACTIVE','DEGRADED') AND json_extract(s.request,'$.provider')='eodhd'").fetchall()
 histories=set();rest=set();calendars=set()
 for item in rows:
  req=json.loads(item['request']);symbol=req.get('provider_symbol') or '';exchange=symbol.rsplit('.',1)[-1]
  live=ws and not item['is_test'] and item['provisional_symbol']!=symbol and (exchange=='US' or exchange in eu)
  if live:
   if bars:histories.add(symbol);calendars.add(exchange)
  else:rest.add(symbol)
 # Successful history and REST observations are shared by credential/symbol.
 # Calendar is one HTTP request per exchange/minute. WebSockets cost zero
 # HTTP requests. Fallbacks still consume the shared limiter when performed.
 units=max(1,len(histories)+len(rest));available=max(1,limit-len(calendars))
 return max(minimum,(units*60+available-1)//available)

def quiet_market_interval(c,request,profile,now,interval,sample=None):
 """Conservative reduced polling, not proof of broker untradability."""
 if request.get('provider')!='eodhd' or profile=='CRITICAL':return interval
 if sample and sample.get('market_status') in ('PRE','AFTER','HALTED'):return interval
 if sample and sample.get('event_time'):
  try:
   if 0<=(now-stamp(sample['event_time'])).total_seconds()<=request['risk']['max_quote_age_s']:return interval
  except (ValueError,TypeError):return interval
 symbol=request.get('provider_symbol') or '';exchange=symbol.rsplit('.',1)[-1].upper() if '.' in symbol else ''
 if not exchange or not scheduled_regular_close(c,exchange,now):return interval
 opening=expected_regular_open(c,request,now)
 if not opening:return interval
 seconds=(stamp(opening['expected_at'])-now).total_seconds()
 if seconds<=300:return interval
 # US extended trading can occur 04:00–20:00 local. Do not slow it down.
 if exchange=='US':
  from zoneinfo import ZoneInfo
  local=now.astimezone(ZoneInfo('America/New_York'))
  if local.weekday()<5 and 4<=local.hour<20:return interval
  # Wake before 04:00 ET even if regular opening is later.
  if local.weekday()<5 and local.hour<4:
   pre=local.replace(hour=4,minute=0,second=0,microsecond=0)
   seconds=min(seconds,(pre-local).total_seconds())
 deadline=request.get('risk',{}).get('exit_deadline')
 if deadline:
  try:seconds=min(seconds,(stamp(deadline)-now).total_seconds())
  except (ValueError,TypeError):return interval
 if seconds<=300:return interval
 return max(interval,min(120,int(seconds-300)))

def observation_poll_interval(c,request,profile,now,sample,baseline=None):
 """Recheck aging live trades at the existing ACTIVE cadence, within budget."""
 interval=effective_poll_interval(c,request,profile) if baseline is None else baseline
 if sample and request['provider']=='eodhd' and sample.get('price_time_kind')=='trade' and sample.get('market_status') in ('REGULAR','PRE','AFTER'):
  age=min(request['risk']['max_quote_age_s'],GLOBAL_RISK['max_quote_age_s'])
  deadlines=[stamp(sample['event_time']).timestamp()+age]
  for key in ('status_at','bid_at','ask_at'):
   if sample.get(key):deadlines.append(stamp(sample[key]).timestamp()+age)
  context=sample.get('context') or {}
  if context.get('as_of'):deadlines.append(stamp(context['as_of']).timestamp()+300)
  if sample.get('bar_history') and verified_bar_samples(sample,request,now) is not None:
   deadlines.extend([stamp(sample['bar_history'][-1]['bar_open_at']).timestamp()+60+age,stamp(sample['bar_evidence']['schedule_received_at']).timestamp()+age])
  remaining=min(deadlines)-now.timestamp()
  if remaining<=interval:
   interval=min(interval,interval if profile=='ACTIVE' else effective_poll_interval(c,request,'ACTIVE'))
 return quiet_market_interval(c,request,profile,now,interval,sample)

def init(c):
 import hotwatch_warmup,web_push,hotwatch_buy_plan
 hotwatch_buy_plan.init(c)
 hotwatch_warmup.init(c)
 web_push.init(c)
 c.execute('CREATE TABLE IF NOT EXISTS hw_strategies(owner_id INTEGER NOT NULL,strategy_id TEXT NOT NULL,version TEXT NOT NULL,payload TEXT NOT NULL,checksum TEXT NOT NULL,created TEXT NOT NULL,author TEXT NOT NULL,validation_status TEXT NOT NULL,PRIMARY KEY(owner_id,strategy_id,version))')
 c.execute('INSERT OR IGNORE INTO hw_strategies VALUES(0,?,?,?,?,?,?,?)',(BASELINE['strategy_id'],BASELINE['version'],canonical(BASELINE),checksum(BASELINE),utc().isoformat(),'ESCAPE builtin','baseline_tested'))
 c.execute('INSERT OR IGNORE INTO hw_strategies VALUES(0,?,?,?,?,?,?,?)',(EARLY_CATALYST['strategy_id'],EARLY_CATALYST['version'],canonical(EARLY_CATALYST),checksum(EARLY_CATALYST),utc().isoformat(),'ESCAPE builtin','schema_validated'))
 c.execute('INSERT OR IGNORE INTO hw_strategies VALUES(0,?,?,?,?,?,?,?)',(EARLY_CATALYST_V1['strategy_id'],EARLY_CATALYST_V1['version'],canonical(EARLY_CATALYST_V1),checksum(EARLY_CATALYST_V1),utc().isoformat(),'ESCAPE builtin','schema_validated'))
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
 c.execute('CREATE INDEX IF NOT EXISTS hw_samples_latest ON hw_samples(watch_row_id,id)')
 c.execute('CREATE INDEX IF NOT EXISTS hw_context_latest ON hw_context_events(watch_row_id,id)')
 c.execute('CREATE TABLE IF NOT EXISTS hw_feed_recovery(watch_row_id INTEGER PRIMARY KEY REFERENCES hw_sessions(id),next_attempt REAL NOT NULL,status TEXT NOT NULL,updated TEXT NOT NULL)')
 c.execute('CREATE TABLE IF NOT EXISTS hw_reference_cache(id INTEGER PRIMARY KEY CHECK(id=1),raw BLOB NOT NULL)')
 c.execute('CREATE TABLE IF NOT EXISTS hw_verified_feed_links(user_id INTEGER NOT NULL,asset_id TEXT NOT NULL,ticker TEXT NOT NULL,currency TEXT NOT NULL,exchange TEXT NOT NULL,symbol TEXT NOT NULL,isin TEXT NOT NULL,verified_epoch REAL NOT NULL,PRIMARY KEY(user_id,asset_id))')
 c.execute('CREATE TABLE IF NOT EXISTS hw_cxe_feed_evidence(user_id INTEGER NOT NULL,asset_id TEXT NOT NULL,symbol TEXT NOT NULL,payload TEXT NOT NULL,verified_epoch REAL NOT NULL,next_attempt REAL NOT NULL,status TEXT NOT NULL,PRIMARY KEY(user_id,asset_id))')
 c.execute('CREATE TABLE IF NOT EXISTS hw_provisional_feed_links(watch_row_id INTEGER PRIMARY KEY REFERENCES hw_sessions(id),symbol TEXT NOT NULL,evidence TEXT NOT NULL,created TEXT NOT NULL)')
 c.execute('CREATE TABLE IF NOT EXISTS hw_calculations(id INTEGER PRIMARY KEY,watch_row_id INTEGER NOT NULL REFERENCES hw_sessions(id),sample_row_id INTEGER REFERENCES hw_samples(id),calculated TEXT NOT NULL,payload TEXT NOT NULL,strategy_checksum TEXT NOT NULL)')
 c.execute('CREATE INDEX IF NOT EXISTS hw_calculations_latest ON hw_calculations(watch_row_id,id)')
 c.execute('CREATE TABLE IF NOT EXISTS hw_events(id INTEGER PRIMARY KEY,event_id TEXT NOT NULL UNIQUE,watch_row_id INTEGER NOT NULL REFERENCES hw_sessions(id),event_type TEXT NOT NULL,severity TEXT NOT NULL,created TEXT NOT NULL,data_timestamp TEXT,payload TEXT NOT NULL)')
 c.execute('CREATE INDEX IF NOT EXISTS hw_event_history ON hw_events(watch_row_id,id)')
 c.execute('CREATE TABLE IF NOT EXISTS hw_discovery_control(id INTEGER PRIMARY KEY CHECK(id=1),started_at TEXT NOT NULL)')
 c.execute('INSERT OR IGNORE INTO hw_discovery_control VALUES(1,?)',(utc().isoformat(),))
 c.execute('CREATE TABLE IF NOT EXISTS hw_discovery_resets(user_id INTEGER PRIMARY KEY REFERENCES users(id),reset_at TEXT NOT NULL,generation TEXT NOT NULL)')
 c.execute('CREATE TABLE IF NOT EXISTS hw_discovery_attempts(user_id INTEGER NOT NULL,is_test INTEGER NOT NULL,candidate_id TEXT NOT NULL,report_id TEXT NOT NULL,status TEXT NOT NULL,updated TEXT NOT NULL,next_attempt REAL NOT NULL,watch_id TEXT,PRIMARY KEY(user_id,is_test,candidate_id))')
 c.execute('CREATE TABLE IF NOT EXISTS hw_admin_events(id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),kind TEXT NOT NULL,created TEXT NOT NULL,payload TEXT NOT NULL)')
 c.execute('CREATE TABLE IF NOT EXISTS hw_operator_events(id INTEGER PRIMARY KEY,created TEXT NOT NULL,killed INTEGER NOT NULL,reason TEXT NOT NULL)')
 c.execute('CREATE TABLE IF NOT EXISTS hw_system_control(id INTEGER PRIMARY KEY CHECK(id=1),killed INTEGER NOT NULL,changed TEXT NOT NULL,reason TEXT NOT NULL)')
 c.execute("INSERT OR IGNORE INTO hw_system_control VALUES(1,0,'','')")
 c.execute('CREATE TABLE IF NOT EXISTS hw_control(user_id INTEGER PRIMARY KEY REFERENCES users(id),killed INTEGER NOT NULL,changed TEXT NOT NULL,reason TEXT NOT NULL)')
 c.execute('CREATE TABLE IF NOT EXISTS hw_request_budget(user_id INTEGER NOT NULL,source TEXT NOT NULL,window INTEGER NOT NULL,used INTEGER NOT NULL,PRIMARY KEY(user_id,source,window))')
 c.execute('CREATE TABLE IF NOT EXISTS hw_pluto_budget_lane(user_id INTEGER NOT NULL,window INTEGER NOT NULL,lane TEXT NOT NULL,used INTEGER NOT NULL,PRIMARY KEY(user_id,window,lane))')
 c.execute('CREATE TABLE IF NOT EXISTS hw_provider_health(user_id INTEGER NOT NULL,is_test INTEGER NOT NULL,source TEXT NOT NULL,attempted TEXT NOT NULL,succeeded TEXT,code TEXT,payload TEXT NOT NULL,PRIMARY KEY(user_id,is_test,source))')
 c.execute('CREATE TABLE IF NOT EXISTS hw_heartbeat(id INTEGER PRIMARY KEY CHECK(id=1),updated TEXT NOT NULL,status TEXT NOT NULL)')
 c.execute('CREATE TABLE IF NOT EXISTS hw_supervisor_status(id INTEGER PRIMARY KEY CHECK(id=1),updated TEXT NOT NULL,status TEXT NOT NULL,reason TEXT,attempts INTEGER NOT NULL DEFAULT 0)')
 c.execute('CREATE TABLE IF NOT EXISTS hw_supervisor_events(id INTEGER PRIMARY KEY,created TEXT NOT NULL,event TEXT NOT NULL,code INTEGER)')
 c.execute('CREATE TABLE IF NOT EXISTS hw_exchange_status(exchange TEXT PRIMARY KEY,received TEXT,is_open INTEGER,next_attempt REAL NOT NULL DEFAULT 0)')
 c.execute('CREATE TABLE IF NOT EXISTS hw_exchange_calendar(exchange TEXT PRIMARY KEY,received TEXT NOT NULL,timezone TEXT NOT NULL,calendar TEXT NOT NULL)')
 c.execute('CREATE TABLE IF NOT EXISTS hw_holding_autowatch(user_id INTEGER NOT NULL,portfolio_id INTEGER NOT NULL,asset_id TEXT NOT NULL,status TEXT NOT NULL,watch_id TEXT,next_attempt REAL NOT NULL DEFAULT 0,updated TEXT NOT NULL,PRIMARY KEY(user_id,portfolio_id,asset_id))')
 # Existing local-budget failures can retry when the minute window resets.
 boundary=(int(utc().timestamp()//60)+1)*60+1
 c.execute("UPDATE hw_holding_autowatch SET next_attempt=? WHERE status='PROVIDER_RATE_BUDGET' AND next_attempt>?",(boundary,boundary))
 # Existing generic identity failures deserve an early retry after upgrading.
 retry=utc().timestamp()+10
 c.execute("UPDATE hw_holding_autowatch SET next_attempt=? WHERE status='IDENTITY_UNVERIFIED' AND next_attempt>?",(retry,retry))

def scheduled_regular_close(c,exchange,now):
 """Use same-day provider schedule only to identify regular-session closure."""
 from zoneinfo import ZoneInfo,ZoneInfoNotFoundError
 row=c.execute('SELECT received,timezone,calendar FROM hw_exchange_calendar WHERE exchange=?',(exchange,)).fetchone()
 if not row:return None
 try:
  received=stamp(row['received']);zone=ZoneInfo(row['timezone']);local=now.astimezone(zone);schedule=json.loads(row['calendar'])
  if received>now or received.astimezone(zone).date()!=local.date():return None
  opening=datetime.strptime(schedule['open'],'%H:%M:%S').time();closing=datetime.strptime(schedule['close'],'%H:%M:%S').time()
  days=schedule['working_days'];excluded=schedule['excluded_dates']
  if opening>=closing or not isinstance(days,list) or not days or not isinstance(excluded,list) or local.date().isoformat() in excluded:return None
  if local.strftime('%a') not in days or local.time()<opening or local.time()>=closing:
   return {'status':'CLOSED','received_at':row['received'],'exchange':exchange,'source':'EODHD tidsplan for ordinær handel'}
 except (KeyError,TypeError,ValueError,ZoneInfoNotFoundError):pass
 return None

def expected_regular_open(c,request,now):
 """Display-only next regular opening from a current provider calendar."""
 from datetime import time as local_time
 from zoneinfo import ZoneInfo,ZoneInfoNotFoundError
 symbol=request.get('provider_symbol') or ''
 exchange=symbol.rsplit('.',1)[-1].upper() if '.' in symbol else str(request.get('exchange','')).upper()
 if exchange in ('NASDAQ','NYSE','AMEX','NYSE ARCA'):exchange='US'
 if not re.fullmatch(r'[A-Z0-9_-]{1,16}',exchange) or exchange in ('CC','FOREX'):return None
 row=c.execute('SELECT received,timezone,calendar FROM hw_exchange_calendar WHERE exchange=?',(exchange,)).fetchone()
 if not row or not row['timezone']:return None
 try:
  zone=ZoneInfo(row['timezone']);local=now.astimezone(zone);received=stamp(row['received']);calendar=json.loads(row['calendar'])
  if received>now or received.astimezone(zone).date()!=local.date():return None
  opening=local_time.fromisoformat(calendar['open']);closing=local_time.fromisoformat(calendar['close']);days=calendar['working_days'];excluded=calendar['excluded_dates']
  if opening.tzinfo or closing.tzinfo or opening>=closing or not isinstance(days,list) or not days or not isinstance(excluded,list):return None
  day=local.date();weekday=lambda d:('Mon','Tue','Wed','Thu','Fri','Sat','Sun')[d.weekday()]
  if weekday(day) in days and day.isoformat() in excluded:return None
  if weekday(day) in days and opening<=local.time()<closing:return None
  if weekday(day) in days and local.time()>=opening:day+=timedelta(days=1)
  for _ in range(8):
   if weekday(day) in days:
    # The provider combines full holidays and early closes. Do not guess.
    if day.isoformat() in excluded:return None
    target=datetime.combine(day,opening,zone)
    if target>local:return {'kind':'REGULAR','expected_at':target.astimezone(timezone.utc).isoformat(),'same_day_copenhagen':target.astimezone(ZoneInfo('Europe/Copenhagen')).date()==now.astimezone(ZoneInfo('Europe/Copenhagen')).date(),'basis':'EODHD exchange calendar','execution_confirmed':False}
   day+=timedelta(days=1)
 except (KeyError,ValueError,TypeError,AttributeError,ZoneInfoNotFoundError):return None
 return None

def event(c,row,kind,now,reason,metrics=None,severity='info',data_time=None):
 payload={'watch_id':row['watch_id'],'event_type':kind,'reason':reason,'supporting_metrics':metrics or {},'strategy_version':json.loads(row['strategy'])['version']}
 event_id='hw-'+secrets.token_hex(12)
 c.execute('INSERT INTO hw_events(event_id,watch_row_id,event_type,severity,created,data_timestamp,payload) VALUES(?,?,?,?,?,?,?)',(event_id,row['id'],kind,severity,now.isoformat(),data_time,canonical(payload)))
 try:
  import web_push
  web_push.enqueue(c,row,kind,event_id,now,severity,reason)
 except Exception:
  import logging
  logging.getLogger('escape.hotwatch').error('push_queue_unavailable')

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
 with connect() as c:rows=c.execute('SELECT owner_id,strategy_id,version,checksum,created,author,validation_status,payload FROM hw_strategies WHERE owner_id IN (0,?) ORDER BY strategy_id,version',(uid,)).fetchall()
 from strategy_center import deployment
 return {'strategies':[dict({k:r[k] for k in r.keys() if k!='payload'},deployment_status={'QUALIFIED':'available_for_explicit_session_start','PILOT':'live_pilot','UNQUALIFIED':'inactive_requires_phase3_qualification'}[deployment(r)]) for r in rows],'capabilities':{'declarative_upload':True,'validation':True,'version_pinning':True,'backtest':False,'shadow':False,'activation_of_uploaded_strategies':False,'rollback':False}}

def row_for(c,uid,wid,mode):
 row=c.execute('SELECT * FROM hw_sessions WHERE user_id=? AND watch_id=? AND is_test=?',(uid,wid,int(mode))).fetchone()
 if not row:raise EngineError('watch_not_found',404)
 return row

def entry_for_holding(c,uid,now):
 """Find a confirmed unowned, idle automatic entry watch."""
 rows=c.execute("SELECT * FROM hw_sessions WHERE user_id=? AND is_test=0 AND purpose='automatic discovery' AND status IN ('CREATED','VALIDATING','ACTIVE','DEGRADED') AND lease_until<=? AND json_extract(request,'$.watch_mode')='entry' ORDER BY updated,id",(uid,now.timestamp())).fetchall()
 for row in rows:
  try:
   state=json.loads(row['state'])
   if state.get('signal') not in ('WAIT','NO_DATA') or state.get('pending') in ('BUY','SELL','REDUCE'):continue
   request=json.loads(row['request']);scope=request.get('portfolio_ids',[])
   active={p['id'] for p in c.execute("SELECT id FROM portfolios WHERE user_id=? AND source='pluto' AND active=1",(uid,))}
   if not active or scope and set(scope)!=active:continue
   extra=c.execute('SELECT payload FROM hw_context_events WHERE watch_row_id=? ORDER BY id DESC LIMIT 1',(row['id'],)).fetchone()
   sample=c.execute('SELECT payload FROM hw_samples WHERE watch_row_id=? ORDER BY id DESC LIMIT 1',(row['id'],)).fetchone()
   contexts=([json.loads(extra['payload'])] if extra else [])+([json.loads(sample['payload'])['context']] if sample else [])
   if not contexts or any(not item.get('as_of') for item in contexts):continue
   context=max(contexts,key=lambda item:stamp(item['as_of']))
   if any(stamp(item['as_of'])==stamp(context['as_of']) and (item.get('position')!=context.get('position') or item.get('status')!=context.get('status') or item.get('orders')!=context.get('orders')) for item in contexts):continue
   if not context or context.get('status')!='verified' or context.get('position')!='none' or context.get('orders') or not context.get('as_of') or not 0<=(now-stamp(context['as_of'])).total_seconds()<=300:continue
  except (ValueError,TypeError,KeyError):continue
  return row
 return None

def release_entry_for_holding(c,uid,now):
 row=entry_for_holding(c,uid,now)
 if not row:return False
 c.execute("UPDATE hw_sessions SET status='EXPIRED',updated=?,revision=revision+1,lease_owner=NULL,lease_until=0 WHERE id=?",(now.isoformat(),row['id']))
 event(c,row,'CAPACITY_RELEASED',now,'Plads frigivet til en verificeret beholdnings exit-overvågning')
 return True

def _create_in_transaction(c,uid,data,now,holding=False,manual=False):
 if len(set(data['portfolio_ids']))!=len(data['portfolio_ids']):raise EngineError('duplicate_portfolio_reference')
 if data['provider']=='synthetic' and not data['is_test']:raise EngineError('synthetic_requires_test_mode')
 if data['end_at'] and stamp(data['end_at'])<=now:raise EngineError('watch_deadline_already_passed')
 for key,maximum in GLOBAL_RISK.items():
  v=data['risk'][key]
  if Decimal(str(v))<=0 or Decimal(str(v))>Decimal(str(maximum)):raise EngineError('risk_limit_exceeds_global',400,[{'path':'risk.'+key,'code':'risk_limit','message':'Must be positive and no greater than '+str(maximum)}])
 if c.execute('SELECT killed FROM hw_system_control WHERE id=1').fetchone()[0]:raise EngineError('operator_kill_switch',409)
 if holding and c.execute('SELECT killed FROM hw_control WHERE user_id=?',(uid,)).fetchone() and c.execute('SELECT killed FROM hw_control WHERE user_id=?',(uid,)).fetchone()[0]:raise EngineError('kill_switch_active',409)
 old=c.execute('SELECT * FROM hw_sessions WHERE user_id=? AND watch_id=?',(uid,data['watch_id'])).fetchone()
 if old:
  if old['digest']!=checksum(data):raise EngineError('watch_id_conflict',409)
  return {'ok':True,'duplicate':True,'session':view(c,old,now)}
 if not holding and c.execute("SELECT count(*) FROM hw_sessions WHERE status IN ('CREATED','VALIDATING','ACTIVE','PAUSED','DEGRADED')").fetchone()[0]>=capacity():raise EngineError('global_capacity_limit',409)
 if not holding and c.execute("SELECT count(*) FROM hw_sessions WHERE user_id=? AND status IN ('CREATED','VALIDATING','ACTIVE','PAUSED','DEGRADED')",(uid,)).fetchone()[0]>=capacity():raise EngineError('capacity_limit',409)
 if c.execute("SELECT 1 FROM hw_sessions WHERE user_id=? AND is_test=? AND candidate_id=? AND purpose=? AND status IN ('CREATED','VALIDATING','ACTIVE','PAUSED','DEGRADED')",(uid,int(data['is_test']),data['candidate_id'],data['purpose'].strip().casefold())).fetchone():raise EngineError('active_watch_exists',409)
 if holding:
  if data['is_test'] or data['watch_mode']!='exit' or data['provider'] not in ('eodhd','pluto') or len(data['portfolio_ids'])!=1:raise EngineError('invalid_holding_watch')
  pid=data['portfolio_ids'][0]
  origin_keys=('origin_candidate_id','origin_trade_cycle_id','origin_watch_id')
  if any(data.get(k) for k in origin_keys):
   from hotwatch_service import holding_origin
   if {k:data.get(k) for k in origin_keys}!=holding_origin(c,uid,pid,data['asset_id']):raise EngineError('holding_origin_unverified',409)
  for existing in c.execute("SELECT request FROM hw_sessions WHERE user_id=? AND is_test=0 AND status IN ('CREATED','VALIDATING','ACTIVE','PAUSED','DEGRADED') AND json_extract(request,'$.asset_id')=?",(uid,data['asset_id'])):
   other=json.loads(existing['request']);scope=other.get('portfolio_ids',[])
   if other.get('watch_mode','both')!='entry' and (not scope or pid in scope):raise EngineError('holding_watch_already_exists',409)
  snap=c.execute("SELECT s.payload FROM portfolios p JOIN portfolio_snapshots s ON s.portfolio_id=p.id AND s.user_id=p.user_id WHERE p.id=? AND p.user_id=? AND p.source='pluto' AND p.active=1 AND s.last_error IS NULL",(pid,uid)).fetchone()
  payload=json.loads(snap['payload']) if snap else {}
  try:fresh=0<=(now-stamp(payload['observed'])).total_seconds()<=300
  except (KeyError,ValueError,TypeError):fresh=False
  if not fresh or not payload.get('positions_complete') or not any(x.get('kind')=='holding' and x.get('asset_id')==data['asset_id'] and x.get('quantity') is not None and Decimal(str(x['quantity']))>0 for x in payload.get('positions',[])):raise EngineError('holding_not_verified',409)
 elif any(data.get(k) for k in ('origin_candidate_id','origin_trade_cycle_id','origin_watch_id')):raise EngineError('invalid_holding_origin',409)
 elif manual:
  if data['is_test'] or data['report_id']!='manual-pluto' or not data['candidate_id'].startswith('manual-'):raise EngineError('invalid_manual_watch')
 else:
  report=c.execute('SELECT payload FROM ingested_reports WHERE user_id=? AND report_id=? AND is_test=?',(uid,data['report_id'],int(data['is_test']))).fetchone()
  if not report:raise EngineError('report_reference_not_found',404)
  candidate=next((x for x in json.loads(report['payload']).get('candidates',[]) if x.get('candidate_id')==data['candidate_id']),None)
  if not candidate:raise EngineError('candidate_reference_not_found',404)
  if candidate.get('ticker','').casefold()!=data['ticker'].casefold():raise EngineError('candidate_ticker_mismatch',409)
  if data.get('purpose')=='automatic discovery':
   latest=c.execute("SELECT r.report_id,r.payload FROM report_candidate_links l JOIN ingested_reports r ON r.id=l.report_row_id WHERE l.user_id=? AND l.is_test=? AND l.candidate_id=? AND r.report_type!='deep_analysis' ORDER BY l.generated DESC,r.id DESC LIMIT 1",(uid,int(data['is_test']),data['candidate_id'])).fetchone()
   if not latest or latest['report_id']!=data['report_id']:raise EngineError('candidate_report_superseded',409)
   proposed=candidate.get('strategy_proposal')
   if proposed and (proposed['strategy_id']!=data['strategy_id'] or proposed['version']!=data['strategy_version']):raise EngineError('strategy_proposal_mismatch',409)
  if data.get('watch_mode','both')!='exit':
   from intel_workflows import candidate_currentness
   currentness=candidate_currentness(c,uid,data['is_test'],data['candidate_id'],now,report_fallback=data.get('purpose')=='automatic discovery')
   if currentness['status']!='CURRENT' and not (data.get('purpose')=='automatic discovery' and currentness['status']=='REPORT_ONLY'):raise EngineError('candidate_not_current',409)
   if currentness['status']=='REPORT_ONLY' and (now-stamp(currentness['report_seen_at'])).total_seconds()>86400:raise EngineError('candidate_not_current',409)
   reset=c.execute('SELECT reset_at FROM hw_discovery_resets WHERE user_id=?',(uid,)).fetchone() if not data['is_test'] and data.get('purpose')=='automatic discovery' else None
   if reset:
    if not currentness.get('assessed_at') or stamp(currentness['assessed_at'])<=stamp(reset['reset_at']) or stamp(json.loads(report['payload'])['generated_at'])<=stamp(reset['reset_at']):raise EngineError('candidate_not_current',409)
    from hotwatch_service import pending_holding_slots
    pending=pending_holding_slots(c,uid,now)
    opened=c.execute("SELECT count(*) FROM hw_sessions WHERE status IN ('CREATED','VALIDATING','ACTIVE','PAUSED','DEGRADED')").fetchone()[0]
    if pending and opened>=max(0,capacity()-pending):raise EngineError('HOLDINGS_PRIORITY',409)
   stopped=c.execute("SELECT e.created FROM hw_sessions s JOIN hw_events e ON e.watch_row_id=s.id AND e.event_type IN ('WATCH_COMPLETED','CANDIDATE_WATCH_EXPIRED') WHERE s.user_id=? AND s.is_test=? AND s.candidate_id=? ORDER BY e.id DESC LIMIT 1",(uid,int(data['is_test']),data['candidate_id'])).fetchone()
   if stopped and (not data.get('reactivation_reason') or not currentness.get('assessed_at') or stamp(currentness['assessed_at'])<=stamp(stopped['created'])):raise EngineError('new_assessment_and_reactivation_reason_required',409)
 for pid in data['portfolio_ids']:
  if not c.execute("SELECT 1 FROM portfolios WHERE id=? AND user_id=? AND active=1 AND source='pluto'",(pid,uid)).fetchone():raise EngineError('portfolio_reference_not_found')
 import candidate_lifecycle
 previous_lifecycle=candidate_lifecycle.latest(c,uid,data['is_test'],data['candidate_id'])
 if previous_lifecycle and previous_lifecycle['status'] in ['CLOSED','ARCHIVED'] and data.get('watch_mode','both')!='exit' and not data.get('reactivation_reason'):raise EngineError('reactivation_evidence_required')
 version=strategy(c,uid,data['strategy_id'],data['strategy_version'])
 from strategy_center import deployment
 if deployment(version) not in ('QUALIFIED','PILOT'):raise EngineError('strategy_qualification_required',409)
 if holding and c.execute("SELECT count(*) FROM hw_sessions WHERE status IN ('CREATED','VALIDATING','ACTIVE','PAUSED','DEGRADED')").fetchone()[0]>=capacity():
  if not release_entry_for_holding(c,uid,now):raise EngineError('global_capacity_limit',409)
 initial_state={'signal':'NO_DATA','alert_codes':[]}
 if not holding and not manual and data.get('purpose')=='automatic discovery':
  configured=json.loads(version['payload']).get('parameters',{}).get('news_max_age_minutes')
  priority_until=reported_catalyst_priority_until(candidate,now,configured)
  if priority_until is not None:initial_state.update(catalyst_priority_until=priority_until,catalyst_priority_basis='sender_reported_news')
 cur=c.execute('INSERT INTO hw_sessions(user_id,watch_id,is_test,candidate_id,purpose,status,request,digest,strategy,state,created,updated,next_due) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(uid,data['watch_id'],int(data['is_test']),data['candidate_id'],data['purpose'].strip().casefold(),'CREATED',canonical(data),checksum(data),version['payload'],canonical(initial_state),now.isoformat(),now.isoformat(),now.timestamp()))
 row=c.execute('SELECT * FROM hw_sessions WHERE id=?',(cur.lastrowid,)).fetchone();event(c,row,'WATCH_STARTED',now,data['activation_reason']);cycle=data.get('trade_cycle_id') or 'cycle:'+checksum({'watch_id':data['watch_id']})[:24];candidate_lifecycle.record(c,uid,data['is_test'],data['candidate_id'],'HOT_WATCH',now.isoformat(),data.get('reactivation_reason') or data['activation_reason'],data['watch_id'],cycle);return {'ok':True,'duplicate':False,'session':view(c,row,now)}

def create(connect,uid,data,now=None):
 now=now or utc();require(data,SESSION)
 with connect() as c:
  c.execute('BEGIN IMMEDIATE')
  return _create_in_transaction(c,uid,data,now)

def create_holding(connect,uid,data,now=None):
 """Internal worker path; holding identity is checked again under the write lock."""
 now=now or utc();require(data,SESSION)
 with connect() as c:
  c.execute('BEGIN IMMEDIATE')
  return _create_in_transaction(c,uid,data,now,holding=True)

def create_manual(connect,uid,data,now=None):
 """Create an explicitly requested, Pluto-verified, non-report watch."""
 now=now or utc();require(data,SESSION)
 with connect() as c:
  c.execute('BEGIN IMMEDIATE')
  existing=c.execute("SELECT * FROM hw_sessions WHERE user_id=? AND is_test=0 AND candidate_id=? AND status IN ('CREATED','VALIDATING','ACTIVE','PAUSED','DEGRADED') ORDER BY id DESC LIMIT 1",(uid,data['candidate_id'])).fetchone()
  if not existing:
   for row in c.execute("SELECT * FROM hw_sessions WHERE user_id=? AND is_test=0 AND status IN ('CREATED','VALIDATING','ACTIVE','PAUSED','DEGRADED') AND json_extract(request,'$.asset_id')=? ORDER BY id DESC",(uid,data['asset_id'])):
    if json.loads(row['request']).get('watch_mode','both')!='exit':existing=row;break
  if existing:return {'ok':True,'duplicate':True,'session':view(c,existing,now)}
  return _create_in_transaction(c,uid,data,now,manual=True)

def start_candidates(connect,uid,mode=False):
 """Owned candidate choices, excluding all open/paused watches by stable identity."""
 import report_ingest
 if mode:
  import intel_workflows
  with connect() as c:source=[row for row in intel_workflows.candidates(c,uid,True,include_history_market=False) if row['active']]
  for entry in source:
   if entry['decision']:entry['candidate']=dict(entry['candidate'],decision=entry['decision'])
 else:
  source=report_ingest.desk(connect,uid).get('candidates',[])
 with connect() as c:
  sessions=c.execute("SELECT candidate_id,request FROM hw_sessions WHERE user_id=? AND is_test=? AND status IN ('CREATED','VALIDATING','ACTIVE','DEGRADED','PAUSED')",(uid,int(mode))).fetchall()
  candidate_ids={row['candidate_id'] for row in sessions}
  assets={json.loads(row['request']).get('asset_id') for row in sessions}
  links={row['candidate_id']:(row['expected_ticker'],row['asset_id']) for row in c.execute('SELECT candidate_id,expected_ticker,asset_id FROM market_asset_links WHERE user_id=?',(uid,))}
  allowed=[];excluded=0;unassessed=0;duplicates=0;seen_assets=set();seen_candidates=set();seen_unresolved=set()
  for item in source:
   candidate=item.get('candidate') or {};cid=candidate.get('candidate_id')
   if not cid:continue
   asset=candidate.get('asset_id');link=links.get(cid)
   if not asset and link and link[0].casefold()==str(candidate.get('ticker') or '').casefold():asset=link[1]
   if cid in candidate_ids or asset and asset in assets:excluded+=1;continue
   decision=item.get('decision') or candidate.get('decision') or {}
   currentness=item.get('currentness') or {}
   try:
    assessed=stamp(decision['decided_at']);deadline=stamp(decision['deadline']) if decision.get('deadline') else assessed+timedelta(hours=24)
    valid=assessed<=utc()<deadline
   except (KeyError,TypeError,ValueError):valid=False
   if decision.get('status') not in ('KØB','AFVENT') or not valid or currentness.get('status') in ('COLD','REVIEW_DUE','UNKNOWN'):
    unassessed+=1;continue
   identity=tuple(str(candidate.get(key) or '').strip().casefold() for key in ('ticker','exchange','company_name'))
   unresolved=not asset and all(identity)
   if cid in seen_candidates or asset and asset in seen_assets or unresolved and identity in seen_unresolved:
    duplicates+=1;continue
   seen_candidates.add(cid)
   if asset:seen_assets.add(asset)
   elif unresolved:seen_unresolved.add(identity)
   allowed.append(item)
 return {'candidates':allowed,'already_watched':excluded,'without_current_assessment':unassessed,'duplicates':duplicates,'is_test':mode}

def create_batch(connect,uid,data,now=None):
 """Explicit, idempotent activation request; report lifecycle alone never calls this."""
 now=now or utc()
 if not isinstance(data,dict):raise EngineError('invalid_input')
 sessions=data.get('sessions')
 if not isinstance(sessions,list) or not 1<=len(sessions)<=40:raise EngineError('activation_batch_limit_exceeded')
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
   if prior.get('source')!='eodhd' or prior.get('asset_id')!=latest.get('asset_id') or prior.get('currency')!=latest.get('currency') or prior.get('verification')!=latest.get('verification') or not str(prior.get('feed_type','')).startswith('EODHD REST real-time endpoint') or not prior.get('previous_close'):continue
   reference=stamp(prior['event_time']);previous=Decimal(prior['previous_close']);current=Decimal(price)
   if reference<=at and reference.astimezone(zone).date()==day and previous>0 and current>0:return format((current/previous-1)*100,'f')
 except (KeyError,ValueError,TypeError,ArithmeticError):pass
 return None

def market_observation(data,status,identity_verified):
 """Display-only observation; no signal, risk or notification mutation."""
 if status not in ('ACTIVE','DEGRADED') or not identity_verified or data.get('price_status')!='FRESH' or data.get('momentum_status')!='READY' or data.get('market_status') not in ('OPEN','PREMARKET','AFTERHOURS'):return None
 for minutes in ('5','1','15','30'):
  value=(data.get('momentum_pct') or {}).get(minutes)
  try:
   change=Decimal(str(value))
   if change.is_finite() and change>0:return {'kind':'RISING','change_pct':format(change,'f'),'window_minutes':int(minutes),'data_timestamp':data.get('event_time'),'source':data.get('source'),'risk_approved':False}
  except (ValueError,TypeError,ArithmeticError):pass
 return None

def view(c,row,now=None):
 now=now or utc()
 request=json.loads(row['request']);
 if request.get('purpose')=='automatic holding watch':
  for key in ('origin_candidate_id','origin_trade_cycle_id','origin_watch_id'):request.pop(key,None)
 state=json.loads(row['state']);sample=c.execute('SELECT payload,received FROM hw_samples WHERE watch_row_id=? ORDER BY id DESC LIMIT 1',(row['id'],)).fetchone();currency=json.loads(sample['payload'])['currency'] if sample else None;context=json.loads(sample['payload'])['context'] if sample else None;extra=c.execute('SELECT payload FROM hw_context_events WHERE watch_row_id=? ORDER BY id DESC LIMIT 1',(row['id'],)).fetchone()
 if extra:
  newer=json.loads(extra['payload'])
  if context is None or newer['as_of'] and (not context['as_of'] or stamp(newer['as_of'])>=stamp(context['as_of'])):context=newer
 last=c.execute('SELECT payload FROM hw_calculations WHERE watch_row_id=? ORDER BY id DESC LIMIT 1',(row['id'],)).fetchone()
 last_action=c.execute("SELECT event_id,event_type,created,data_timestamp,payload FROM hw_events WHERE watch_row_id=? AND event_type IN ('BUY_SIGNAL','SELL_SIGNAL','REDUCE_SIGNAL') ORDER BY id DESC LIMIT 1",(row['id'],)).fetchone()
 stale=not row['last_data'] or (now-stamp(row['last_data'])).total_seconds()>request['risk']['max_quote_age_s']
 display_reasons=[];bar_blocking_detail=None
 if row['last_error']:display_reasons.append(row['last_error'])
 if stale and row['last_data']:display_reasons.append('DATA_STALE')
 effective='NO_DATA' if stale and state.get('signal') not in ['PAUSE','NO_DATA'] else state.get('signal','NO_DATA')
 if effective in ('SELL','REDUCE') and context and context.get('status')=='verified' and context.get('position')=='none':
  effective='NO_DATA';display_reasons.append('POSITION_CONTEXT_CHANGED')
 # Legacy calculations used the market-window high. Never present or dispatch
 # that historical trailing signal as a currently verified position exit.
 if effective in ('SELL','REDUCE') and last:
  old_calculation=json.loads(last['payload']);old_reasons=set(old_calculation.get('reason_codes',[]))
  if old_calculation.get('exit_context_key') and not old_reasons.intersection({'STOP_BREACHED','EXIT_DEADLINE'}):
   from hotwatch_strategy import exit_context_key
   portfolio_ids=request.get('portfolio_ids',[]);scope=checksum({'asset_id':request['asset_id'],'portfolio_id':portfolio_ids[0],'watch_id':row['watch_id'],'trade_cycle_id':request.get('trade_cycle_id')}) if len(portfolio_ids)==1 else None
   if not context or exit_context_key(context,scope)!=old_calculation['exit_context_key']:
    effective='NO_DATA';display_reasons.append('POSITION_CONTEXT_CHANGED')
  if 'TRAILING_EXIT' in old_reasons and old_calculation.get('signal_basis') not in ('verified_position_high','price_context') and not old_reasons.intersection({'STOP_BREACHED','EXIT_DEADLINE'}):
   effective='NO_DATA';display_reasons.append('POSITION_TRAILING_EVIDENCE_REQUIRED')
  elif old_calculation.get('signal_basis')=='verified_position_high':
   from hotwatch_strategy import position_trailing
   check_risk=dict(request['risk']);portfolio_ids=request.get('portfolio_ids',[])
   if len(portfolio_ids)==1:check_risk['_position_scope']=checksum({'asset_id':request['asset_id'],'portfolio_id':portfolio_ids[0],'watch_id':row['watch_id'],'trade_cycle_id':request.get('trade_cycle_id')})
   check_sample=dict(json.loads(sample['payload']),context=context) if sample and context else None
   proof,_=position_trailing(check_sample,check_risk,state,now,False) if check_sample else (None,None)
   if not proof or not proof.get('high') or proof['high']!=(old_calculation.get('position_trailing') or {}).get('high'):
    effective='NO_DATA';display_reasons.append('POSITION_TRAILING_EVIDENCE_REQUIRED')
 if effective not in ('NO_DATA','PAUSE') and (not context or context.get('status')!='verified' or not context.get('as_of') or not 0<=(now-stamp(context['as_of'])).total_seconds()<=300):effective='NO_DATA';display_reasons.append('POSITION_CONTEXT_UNKNOWN')
 if sample and effective not in ('NO_DATA','PAUSE'):
  latest_sample=json.loads(sample['payload']);max_age=request['risk']['max_quote_age_s']
  if latest_sample['source']=='eodhd' and latest_sample['market_status']!='UNKNOWN':
   fields=['status_at']+(['bid_at','ask_at'] if effective=='BUY' else [])
   if any(not latest_sample.get(k) or not 0<=(now-stamp(latest_sample[k])).total_seconds()<=max_age for k in fields):effective='NO_DATA';display_reasons.append('MARKET_EVIDENCE_STALE')
   computed=json.loads(last['payload']) if last else {}
   price_exit=effective in ('SELL','REDUCE') and (computed.get('signal_basis') in ('price_context','verified_position_high') or set(computed.get('reason_codes',[]))&{'STOP_BREACHED','EXIT_DEADLINE'})
   if latest_sample.get('bar_history') and computed.get('analysis_uses_bars',True) and not price_exit:
    from datetime import timedelta
    try:
     bar_end=stamp(latest_sample['bar_history'][-1]['bar_open_at'])+timedelta(seconds=60)
     schedule_at=stamp(latest_sample['bar_evidence']['schedule_received_at']);bar_age=(now-bar_end).total_seconds();schedule_age=(now-schedule_at).total_seconds()
     if not 0<=bar_age<=max_age or not 0<=schedule_age<=max_age:
      effective='NO_DATA';display_reasons.append('BAR_EVIDENCE_STALE')
      bar_blocking_detail={'bar_last_closed_at':bar_end.isoformat(),'schedule_received_at':schedule_at.isoformat(),'bar_age_s':round(bar_age,3),'schedule_age_s':round(schedule_age,3),'max_age_s':max_age,'blocking_inputs':[name for name,age in (('bar',bar_age),('schedule',schedule_age)) if not 0<=age<=max_age],'analysis_uses_bars':True}
    except (KeyError,TypeError,ValueError,IndexError):effective='NO_DATA';display_reasons.append('BAR_EVIDENCE_STALE')
 # A pilot BUY must still satisfy its evidence at the time it is shown or
 # sent to the manual trading flow, even before the next market sample.
 if effective=='BUY' and sample and last:
  strategy_data=json.loads(row['strategy']);stored=json.loads(last['payload'])
  if strategy_data.get('schema_version')==2:
   import strategy_center
   from hotwatch_strategy import early_watch,matches
   current_sample=json.loads(sample['payload']);current_sample['context']=context or current_sample['context']
   current_metrics=dict(stored.get('supporting_metrics') or {})
   try:
    strategy_center.early_inputs(c,row,request,current_sample,current_metrics,now)
    extra_macd=not strategy_data['parameters']['use_macd_confirmation'] or current_metrics.get('macd_histogram') is not None and Decimal(str(current_metrics['macd_histogram']))>0
    if not extra_macd or not early_watch(strategy_data,current_metrics) or not matches(strategy_data['entry_rules'],current_metrics,strategy_data['parameters']):
     effective='NO_DATA';display_reasons.append('EARLY_EVIDENCE_STALE')
   except (ValueError,TypeError,KeyError,ArithmeticError):
    effective='NO_DATA';display_reasons.append('EARLY_EVIDENCE_STALE')
 profile=state.get('adaptive_profile',request['profile'])
 # The API and worker can have different environment settings. Show the
 # interval actually selected by the worker, without recalculating its budget.
 budget_interval=state.get('scheduled_interval_s')
 interval_basis='worker_schedule'
 if type(budget_interval) not in (int,float) or not 0<budget_interval<=86400:
  budget_interval=effective_poll_interval(c,request,profile);interval_basis='reader_estimate'
 latest_payload=json.loads(sample['payload']) if sample else None
 if latest_payload and latest_payload.get('bar_history'):
  # Older bar arrays are not needed for quote-to-quote comparisons; omit them
  # so each dashboard refresh does not deserialize thousands of old bars.
  previous=c.execute("SELECT json_remove(payload,'$.bar_history','$.bar_evidence') AS payload FROM hw_samples WHERE watch_row_id=? AND event_epoch<? ORDER BY event_epoch DESC,id DESC LIMIT 119",(row['id'],stamp(latest_payload['event_time']).timestamp())).fetchall()
  history=[json.loads(x['payload']) for x in reversed(previous)]+[latest_payload]
 else:history=[json.loads(x['payload']) for x in reversed(c.execute('SELECT payload FROM hw_samples WHERE watch_row_id=? ORDER BY event_epoch DESC,id DESC LIMIT 120',(row['id'],)).fetchall())]
 if latest_payload and latest_payload.get('bar_history') and verified_bar_samples(latest_payload,request,now) is None:
  history[-1]={k:v for k,v in latest_payload.items() if k not in ('bar_history','bar_evidence')}
 data_status=observation_status(history,now,request['risk']['max_quote_age_s'],effective,row['status'])
 if bar_blocking_detail:data_status['bar_blocking_detail']=bar_blocking_detail
 # Exchange-open evidence is separate from the instrument's session and can
 # never assert that extended-hours trading is unavailable.
 regular={'status':'UNKNOWN','received_at':None,'exchange':None,'source':'EODHD exchange details'}
 symbol=request.get('provider_symbol') or ''
 exchange=symbol.rsplit('.',1)[-1].upper() if '.' in symbol else ''
 if request.get('provider')=='eodhd' and not row['is_test'] and exchange:
  observed=c.execute('SELECT received,is_open FROM hw_exchange_status WHERE exchange=?',(exchange,)).fetchone()
  if observed and observed['received'] and observed['is_open'] in (0,1):
   try:
    if 0<=(now-stamp(observed['received'])).total_seconds()<=300:regular={'status':'OPEN' if observed['is_open'] else 'CLOSED','received_at':observed['received'],'exchange':exchange,'source':'EODHD exchange details'}
   except (ValueError,TypeError):pass
  if regular['status']=='UNKNOWN':regular=scheduled_regular_close(c,exchange,now) or regular
 if regular['status']=='CLOSED' and data_status['market_status']=='OPEN' and data_status.get('market_status_at'):
  try:
   if stamp(data_status['market_status_at'])>stamp(regular['received_at']):regular={'status':'UNKNOWN','received_at':regular['received_at'],'exchange':exchange,'source':'EODHD exchange details; nyere instrumentstatus afviger'}
   else:
    data_status['market_status']='UNKNOWN'
    if effective not in ('NO_DATA','PAUSE'):
     effective='NO_DATA';data_status['signal_status']='WAITING_FOR_DATA';display_reasons.append('REGULAR_SESSION_CLOSED')
  except (ValueError,TypeError):regular={'status':'UNKNOWN','received_at':None,'exchange':exchange,'source':'EODHD exchange details'}
 data_status['regular_session']=regular
 if effective=='NO_DATA' and (regular['status']=='CLOSED' or request.get('provider')=='pluto' and regular['status']=='UNKNOWN') and data_status['market_status'] not in ('AFTERHOURS','HALTED'):
  data_status['next_market_session']=expected_regular_open(c,request,now)
 # A previous-close value from an earlier EODHD snapshot for this same watch
 # can accompany a later trade only on the same verified exchange-local date.
 # It remains a provider-reported reference, never an official-close claim.
 if data_status['daily_change_pct'] is None:
  reported_daily=reported_daily_from_history(history,request,data_status['price'])
  if reported_daily is not None:data_status.update(daily_change_pct=reported_daily,daily_change_source='EODHD reported previousClose')
 display_status={'BUY':'KØBSSIGNAL','SELL':'SÆLGSSIGNAL','REDUCE':'EXIT WATCH','WAIT':'AFVENT','NO_DATA':'DATA MANGLER','PAUSE':'DATA MANGLER'}.get(effective,'HOT WATCH')
 if effective=='NO_DATA' and data_status['price'] is not None:display_status='DATA FOR GAMLE' if stale else 'AFVENTER SIGNALDATA'
 pilot=(json.loads(last['payload']).get('early_catalyst') if last else None)
 if pilot and not stale and effective in ('WAIT','NO_DATA'):
  display_status='EARLY WATCH' if pilot.get('watch_state')=='EARLY_WATCH' and 'EARLY_EVIDENCE_STALE' not in display_reasons else 'AFVENTER EARLY WATCH'
 if effective in ('NO_DATA','PAUSE') and data_status['market_status'] in ('CLOSED','HALTED') and row['status'] in ('CREATED','VALIDATING','ACTIVE','DEGRADED'):
  display_status='MARKED LUKKET' if data_status['market_status']=='CLOSED' else 'HANDEL STANDSET'
 if effective in ('NO_DATA','PAUSE') and row['status'] in ('CREATED','VALIDATING','ACTIVE','DEGRADED') and regular['status']=='CLOSED' and data_status['market_status'] not in ('PREMARKET','AFTERHOURS','HALTED'):
  display_status='MARKED LUKKET (ORDINÆR HANDEL)'
 candidate_review=None
 if request.get('report_id')!='manual-pluto' and request.get('watch_mode','both')!='exit' and row['status'] in ('CREATED','VALIDATING','ACTIVE','DEGRADED','PAUSED'):
  from intel_workflows import candidate_currentness
  candidate_review=candidate_currentness(c,row['user_id'],row['is_test'],row['candidate_id'],now,report_fallback=request.get('purpose')=='automatic discovery')
  if candidate_review['status']=='REVIEW_DUE' and row['status']!='PAUSED':display_status='REVURDERING FORFALDET'
  if candidate_review['status']=='REPORT_ONLY' and row['status']!='PAUSED':display_status='MANGLER VURDERING'
 provisional=c.execute('SELECT symbol,evidence FROM hw_provisional_feed_links WHERE watch_row_id=?',(row['id'],)).fetchone()
 if provisional and request.get('provider')=='pluto':
  try:
   reference=json.loads(provisional['evidence'])
   if reference.get('basis')=='user_supplied_provisional_crypto' and reference.get('asset_id')==request.get('asset_id'):
    data_status['reference_candidate']={'symbol':provisional['symbol'],'verified':False,'note':reference.get('note')}
  except (ValueError,TypeError,AttributeError):pass
 if provisional and request.get('provider')=='eodhd':
  data_status['identity_verification']='unverified';data_status['identity_evidence']=json.loads(provisional['evidence'])
  if not row['is_test']:
   data_status.update(price=None,bid=None,ask=None,daily_change_pct=None,since_last_pct=None,momentum_pct={str(n):None for n in (1,5,15,30)},price_status='UNVERIFIED')
 if (data_status.get('identity_verification')=='unverified' or latest_payload and latest_payload.get('verification')!='verified') and row['status']!='PAUSED':
  display_status='KURSKILDE IKKE BEKRÆFTET';display_reasons.append('DATA_UNVERIFIED')
 holding_verified=None
 if context and context.get('status')=='verified' and context.get('as_of'):
  try:
   if context.get('position') in ('held','none') and 0<=(now-stamp(context['as_of'])).total_seconds()<=300:holding_verified=context.get('position')=='held'
  except (ValueError,TypeError):pass
 link=c.execute('SELECT symbol,verified_epoch FROM hw_verified_feed_links WHERE user_id=? AND asset_id=?',(row['user_id'],request.get('asset_id'))).fetchone()
 instrument_match_verified=bool(link and request.get('provider')=='eodhd' and link['symbol']==request.get('provider_symbol') and 0<=now.timestamp()-link['verified_epoch']<=7*86400)
 cxe_link=c.execute('SELECT symbol,verified_epoch,status,payload FROM hw_cxe_feed_evidence WHERE user_id=? AND asset_id=?',(row['user_id'],request.get('asset_id'))).fetchone()
 if cxe_link:instrument_match_verified=bool(instrument_match_verified and valid_cxe_evidence(c,row['user_id'],request,now))
 if not row['is_test'] and request.get('purpose') in ('automatic discovery','automatic holding watch') and request.get('provider')=='eodhd':instrument_match_verified=verified_automatic_feed(c,row['user_id'],request,now)
 evidence=None
 if cxe_link:
  try:
   stored_evidence=json.loads(cxe_link['payload']);evidence={key:stored_evidence.get(key) for key in ('basis','reference_source','reference_created_at','cxe_symbol','cxe_symbols','cxe_references','primary_ticker','primary_mic','cxe_asset_class','catalog_source','catalog_received_at','catalog_exchange','catalog_type','pluto_type','type_note','symbol','isin','currency','currency_basis','last_revalidation_error')};pluto_evidence=stored_evidence.get('pluto') or {};evidence['pluto']={key:pluto_evidence.get(key) for key in ('ticker','name','exchange','currency','type')}
  except (ValueError,TypeError,AttributeError):instrument_match_verified=False
 quote_feed_verified=bool(latest_payload and latest_payload.get('source')=='eodhd' and latest_payload.get('verification')=='verified' and instrument_match_verified and stamp(sample['received']).timestamp()>=link['verified_epoch'])
 if request.get('provider')=='eodhd' and (cxe_link or not row['is_test'] and request.get('purpose') in ('automatic discovery','automatic holding watch')) and not quote_feed_verified:
  if row['status']!='PAUSED':effective='NO_DATA';display_status='KURSKILDE IKKE BEKRÆFTET' if not instrument_match_verified and (provisional or not cxe_link) else 'MARKED LUKKET (ORDINÆR HANDEL)' if instrument_match_verified and regular['status']=='CLOSED' else 'DATA MANGLER';data_status['signal_status']='WAITING_FOR_DATA'
  data_status.update(identity_verification='verified' if instrument_match_verified else 'unverified',price=None,bid=None,ask=None,daily_change_pct=None,since_last_pct=None,momentum_pct={str(n):None for n in (1,5,15,30)},price_status='UNVERIFIED')
  display_reasons.append('EODHD_INSTRUMENT_REVALIDATION_REQUIRED' if not instrument_match_verified else 'WAITING_FOR_NEW_VERIFIED_QUOTE')
 quote_freshness='UNKNOWN'
 if latest_payload and latest_payload.get('event_time'):
  age=(now-stamp(latest_payload['event_time'])).total_seconds()
  quote_freshness='FUTURE' if age<0 else 'FRESH' if age<=request['risk']['max_quote_age_s'] else 'STALE'
 if evidence and evidence.get('basis')=='user_authorized_btc_monitoring' and quote_feed_verified and quote_freshness=='FRESH' and effective=='NO_DATA' and not row['last_error'] and row['status'] in ('CREATED','VALIDATING','ACTIVE','DEGRADED'):
  display_status='KURS MODTAGET · MARKEDSSTATUS UKENDT' if data_status['market_status']=='UNKNOWN' else 'KURS MODTAGET · AFVENTER SIGNALDATA'
 data_status.update(holding_verified=holding_verified,instrument_match_verified=instrument_match_verified,instrument_match_evidence=evidence,quote_feed_verified=quote_feed_verified,quote_freshness=quote_freshness)
 if not row['is_test'] and request.get('provider')=='eodhd' and not instrument_match_verified:data_status.pop('next_market_session',None)
 # A fresh quote is useful even if there is no fresh trade. It remains a
 # separately timestamped observation and never changes risk or signal state.
 if effective=='NO_DATA' and request.get('provider')=='eodhd' and (row['is_test'] or instrument_match_verified):
  # A quote attached to an earlier trade can itself still be fresh after the
  # trade or another mandatory input has expired. Preserve both source times.
  try:
   if latest_payload and (row['is_test'] or quote_feed_verified) and latest_payload.get('source')=='eodhd' and latest_payload.get('currency')==request.get('quote_currency') and latest_payload.get('quote_feed') and latest_payload.get('bid') is not None and latest_payload.get('ask') is not None and Decimal(latest_payload['bid'])>0 and Decimal(latest_payload['ask'])>=Decimal(latest_payload['bid']) and all(0<=(now-stamp(latest_payload[k])).total_seconds()<=request['risk']['max_quote_age_s'] for k in ('bid_at','ask_at')):
    data_status['partial_quote']={'bid':latest_payload['bid'],'ask':latest_payload['ask'],'currency':latest_payload['currency'],'source_time':min((latest_payload['bid_at'],latest_payload['ask_at']),key=stamp),'received_at':sample['received'],'source':'eodhd'}
  except (ValueError,TypeError,KeyError,ArithmeticError):pass
  partials=c.execute("SELECT created,payload FROM hw_events WHERE watch_row_id=? AND event_type='PARTIAL_MARKET_OBSERVATION' ORDER BY id DESC LIMIT 10",(row['id'],)).fetchall()
  for partial in partials:
   try:
    item=json.loads(partial['payload'])['supporting_metrics']
    if item.get('quality') in ('TRADE_MISSING','QUOTE_ONLY') and item.get('source')=='eodhd' and item.get('currency')==request.get('quote_currency') and item.get('bid') is not None and item.get('ask') is not None and Decimal(item['bid'])>0 and Decimal(item['ask'])>=Decimal(item['bid']) and 0<=(now-stamp(item['source_time'])).total_seconds()<=request['risk']['max_quote_age_s'] and (row['is_test'] or link and stamp(partial['created']).timestamp()>=link['verified_epoch']):
     prior=data_status.get('partial_quote')
     if not prior or stamp(item['source_time'])>stamp(prior['source_time']):data_status['partial_quote']={k:item.get(k) for k in ('bid','ask','currency','source_time','received_at','source')}
     break
   except (ValueError,TypeError,KeyError,ArithmeticError):continue
  if data_status.get('partial_quote'):
   # Quote freshness is independent of the last trade's age and cannot make
   # that trade, its signal, or its market-status evidence fresh.
   data_status['quote_status']='FRESH'
   if display_status in ('MARKED LUKKET (ORDINÆR HANDEL)','DATA MANGLER','DATA FOR GAMLE','AFVENTER SIGNALDATA'):
    display_status='EFTERMARKED AKTIVT · SIGNAL AFVENTER' if data_status['market_status']=='AFTERHOURS' else 'BID/ASK MODTAGET · SIGNAL AFVENTER'
 import hotwatch_warmup
 data_status['analysis_warmup']=hotwatch_warmup.status(c,row,request,now)
 import hotwatch_buy_plan
 buy_plan=hotwatch_buy_plan.get(c,row,now)
 if buy_plan and context:
  context=dict(context,fx_to_dkk=buy_plan['fx_to_dkk'] if buy_plan['fresh'] else None,fees_dkk=buy_plan['fees_dkk'] if buy_plan['fresh'] else None)
 if buy_plan and (not buy_plan['fresh'] or not row['last_calculation'] or stamp(row['last_calculation'])<=max(stamp(buy_plan['selected_at']),stamp(buy_plan['verified_at']))) and effective=='BUY':
  effective='WAIT';display_status='RISIKODATA MANGLER';display_reasons.append('BUY_PLAN_RECHECK_REQUIRED')
 # Missing broker event time is distinct from an absent broker price. Never
 # treat the fetch time or a provisional crypto match as signal evidence.
 if effective=='NO_DATA' and row['status'] in ('CREATED','VALIDATING','ACTIVE','DEGRADED') and request.get('provider')=='pluto' and row['last_error']=='PLUTO_QUOTE_TIME_UNKNOWN':
  display_status='KURSTID MANGLER'
 # A verified instrument without a usable schedule must not be presented as
 # a confirmed closed market. Explain the missing market status instead.
 if effective=='NO_DATA' and row['status'] in ('CREATED','VALIDATING','ACTIVE','DEGRADED') and display_status=='DATA MANGLER' and request.get('provider')=='eodhd' and instrument_match_verified and regular['status']=='UNKNOWN' and data_status['market_status']=='UNKNOWN':
  display_status='MARKEDSSTATUS UKENDT'
  display_reasons.append('EXCHANGE_STATUS_UNKNOWN')
 data_status['market_observation']=market_observation(data_status,row['status'],bool(row['is_test'] or instrument_match_verified))
 # One current status for API, dashboard and engine views. Only a calculation
 # for the latest observation can establish signal warmup; an independent
 # historical-analysis cache cannot override a decision or data/risk gate.
 calculation=json.loads(last['payload']) if last else {}
 if effective=='NO_DATA' and display_status=='AFVENTER SIGNALDATA' and not stale and not row['last_error'] and data_status.get('price') is not None and set(calculation.get('reason_codes',[]))=={'WARMUP'} and calculation.get('data_timestamp')==row['last_data']:
  display_status='WARMUP'
 display_status={'PAUSED':'PAUSERET','COMPLETED':'AFSLUTTET','EXPIRED':'UDLØBET','ERROR':'FEJL'}.get(row['status'],display_status)
 action=None
 if last_action:
  event_data=json.loads(last_action['payload']);side=last_action['event_type'].removesuffix('_SIGNAL')
  active=row['status']=='ACTIVE' and effective==side
  missing=row['status'] in ('CREATED','VALIDATING','ACTIVE','DEGRADED') and effective=='NO_DATA'
  acknowledged=c.execute("SELECT created FROM hw_events WHERE watch_row_id=? AND event_type='SIGNAL_ACKNOWLEDGED' AND json_extract(payload,'$.supporting_metrics.action_event_id')=? ORDER BY id DESC LIMIT 1",(row['id'],last_action['event_id'])).fetchone()
  action={k:last_action[k] for k in ('event_id','event_type','created','data_timestamp')}
  action.update(signal=side,reason=event_data.get('reason'),state='ACTIVE' if active else 'DATA_MISSING' if missing else 'WITHDRAWN',acknowledged_at=acknowledged['created'] if acknowledged else None,current_reason_codes=list(dict.fromkeys(display_reasons or calculation.get('reason_codes',[]))))
 return {'buy_plan':buy_plan,'last_action_signal':action,'watch_id':row['watch_id'],'latest_currency':currency,'latest_context':context,'is_test':bool(row['is_test']),'status':row['status'],'request':request,'candidate_review':candidate_review,'strategy_checksum':checksum(json.loads(row['strategy'])),'minimum_required_samples':json.loads(row['strategy'])['parameters']['min_samples'],'signal':effective,'display_status':display_status,'display_reason_codes':list(dict.fromkeys(display_reasons)),'data_status':data_status,'last_computed_signal':json.loads(last['payload'])['signal'] if last else 'NO_DATA','data_stale':stale,'latest_calculation':json.loads(last['payload']) if last else None,'last_data_at':row['last_data'],'last_calculation_at':row['last_calculation'],'updated_at':row['updated'],'last_error':row['last_error'],'adaptive_profile':profile,'target_interval_s':PROFILES[profile],'effective_min_interval_s':budget_interval,'interval_basis':interval_basis,'next_due_at':datetime.fromtimestamp(row['next_due'],timezone.utc).isoformat(),'failures':row['failures']}

def sessions(connect,uid,mode=False,after=0,limit=50):
 with connect() as c:
  rows=c.execute('SELECT * FROM hw_sessions WHERE user_id=? AND is_test=? AND id>? ORDER BY id LIMIT ?',(uid,int(mode),after,limit+1)).fetchall();control=c.execute('SELECT killed,reason,changed FROM hw_control WHERE user_id=?',(uid,)).fetchone();beat=c.execute('SELECT updated,status FROM hw_heartbeat WHERE id=1').fetchone();supervisor=c.execute('SELECT updated,status,reason,attempts FROM hw_supervisor_status WHERE id=1').fetchone()
  return {'sessions':[view(c,r) for r in rows[:limit]],'next_cursor':rows[limit-1]['id'] if len(rows)>limit else None,'is_test':mode,'operator_kill_switch':bool(c.execute('SELECT killed FROM hw_system_control WHERE id=1').fetchone()[0]),'kill_switch':dict(control) if control else {'killed':0,'reason':'','changed':None},'worker':dict(beat) if beat else None,'supervisor':dict(supervisor) if supervisor else None,'capacity':capacity(),'phase':'1-2','deferred':['backtest','shadow','qualified strategy activation/rollback']}

def reconcile_candidates(connect,now=None,connection=None):
 """Expire report-only entry watches without relying on a market-data read."""
 from intel_workflows import candidate_currentness
 now=now or utc();changed=0
 if connection is None:
  # The worker runs this repeatedly. Avoid reserving the single SQLite writer
  # when all sessions are already current; re-evaluate after acquiring it.
  with connect() as preflight:
   rows=preflight.execute("SELECT * FROM hw_sessions WHERE status IN ('CREATED','VALIDATING','ACTIVE','PAUSED','DEGRADED')").fetchall()
   needed=False
   for row in rows:
    req=json.loads(row['request']);mode=req.get('watch_mode','both')
    if row['status']=='DEGRADED' and row['last_error']=='sample_id_conflict' and row['lease_until']<=now.timestamp() and row['next_due']>now.timestamp()+effective_poll_interval(preflight,req):needed=True;break
    if req.get('end_at') and stamp(req['end_at'])<=now:needed=True;break
    if mode=='exit' or req.get('purpose')=='automatic holding watch' or req.get('report_id')=='manual-pluto':continue
    current=candidate_currentness(preflight,row['user_id'],row['is_test'],row['candidate_id'],now,report_fallback=req.get('purpose')=='automatic discovery')
    if current['status']=='COLD' or json.loads(row['state']).get('candidate_cold'):needed=True;break
   if not needed:return 0
 with (nullcontext(connection) if connection is not None else connect()) as c:
  if connection is None:c.execute('BEGIN IMMEDIATE')
  rows=c.execute("SELECT * FROM hw_sessions WHERE status IN ('CREATED','VALIDATING','ACTIVE','PAUSED','DEGRADED')").fetchall()
  for row in rows:
   req=json.loads(row['request']);mode=req.get('watch_mode','both')
   if row['status']=='DEGRADED' and row['last_error']=='sample_id_conflict' and row['lease_until']<=now.timestamp() and row['next_due']>now.timestamp()+effective_poll_interval(c,req):
    c.execute('UPDATE hw_sessions SET next_due=?,updated=?,revision=revision+1 WHERE id=?',(now.timestamp(),now.isoformat(),row['id']))
    event(c,row,'CONFLICT_RETRY_RESCHEDULED',now,'Tidligere udsat kontrol er fremrykket; konfliktende data er fortsat afvist',data_time=row['last_data']);changed+=1
   if req.get('end_at') and stamp(req['end_at'])<=now:
    c.execute("UPDATE hw_sessions SET status='EXPIRED',updated=?,revision=revision+1,lease_owner=NULL,lease_until=0 WHERE id=?",(now.isoformat(),row['id']))
    event(c,row,'WATCH_EXPIRED',now,'Session deadline reached');changed+=1
    continue
   if mode=='exit' or req.get('purpose')=='automatic holding watch' or req.get('report_id')=='manual-pluto':continue
   current=candidate_currentness(c,row['user_id'],row['is_test'],row['candidate_id'],now,report_fallback=req.get('purpose')=='automatic discovery')
   if current['status']!='COLD':
    state=json.loads(row['state'])
    if state.pop('candidate_cold',None):
     c.execute('UPDATE hw_sessions SET state=?,updated=?,revision=revision+1,lease_owner=NULL,lease_until=0 WHERE id=?',(canonical(state),now.isoformat(),row['id']))
     event(c,row,'CANDIDATE_REASSESSED',now,'Ny gyldig vurdering');changed+=1
    continue
   if mode=='entry':
    c.execute("UPDATE hw_sessions SET status='EXPIRED',updated=?,revision=revision+1,lease_owner=NULL,lease_until=0 WHERE id=?",(now.isoformat(),row['id']))
    event(c,row,'CANDIDATE_WATCH_EXPIRED',now,current['reason']);changed+=1
   else:
    # A legacy combined watch also carries exit protection. Split it in the
    # same transaction, retaining its scope and pause state before closing it.
    retained=dict(req);retained['watch_id']='hw-exit-'+hashlib.sha256((str(row['user_id'])+'|'+row['watch_id']).encode()).hexdigest()[:28]
    retained['purpose']='retained exit '+row['watch_id'];retained['watch_mode']='exit'
    retained['activation_reason']='Exit-overvågning bevaret ved lukning af rapportkandidat'
    retained['end_at']=None
    existing=c.execute('SELECT * FROM hw_sessions WHERE user_id=? AND watch_id=?',(row['user_id'],retained['watch_id'])).fetchone()
    if not existing:
     alternatives=c.execute("SELECT * FROM hw_sessions WHERE user_id=? AND is_test=? AND id!=? AND status IN ('CREATED','VALIDATING','ACTIVE','PAUSED','DEGRADED') AND json_extract(request,'$.asset_id')=?",(row['user_id'],row['is_test'],row['id'],req.get('asset_id'))).fetchall()
     existing=next((other for other in alternatives if json.loads(other['request']).get('watch_mode')=='exit' and set(json.loads(other['request']).get('portfolio_ids',[]))==set(req.get('portfolio_ids',[])) and (row['status']=='PAUSED' or other['status']!='PAUSED')),None)
    if existing and existing['status'] in ('COMPLETED','EXPIRED','ERROR'):raise EngineError('retained_exit_watch_was_manually_ended',409)
    if not existing:
     state={'signal':'PAUSE' if row['status']=='PAUSED' else 'NO_DATA','alert_codes':[],'retained_from_watch_id':row['watch_id']}
     cur=c.execute('INSERT INTO hw_sessions(user_id,watch_id,is_test,candidate_id,purpose,status,request,digest,strategy,state,created,updated,next_due) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(row['user_id'],retained['watch_id'],row['is_test'],row['candidate_id'],retained['purpose'].strip().casefold(),'PAUSED' if row['status']=='PAUSED' else 'VALIDATING',canonical(retained),checksum(retained),row['strategy'],canonical(state),now.isoformat(),now.isoformat(),now.timestamp()))
     child=c.execute('SELECT * FROM hw_sessions WHERE id=?',(cur.lastrowid,)).fetchone();event(c,child,'EXIT_WATCH_RETAINED',now,'Exit-overvågning bevaret fra '+row['watch_id'])
    c.execute("UPDATE hw_sessions SET status='EXPIRED',updated=?,revision=revision+1,lease_owner=NULL,lease_until=0 WHERE id=?",(now.isoformat(),row['id']))
    event(c,row,'CANDIDATE_WATCH_EXPIRED',now,current['reason']);changed+=1
 return changed

def acknowledge_signal(connect,uid,wid,mode,event_id,now=None):
 """Acknowledge a historical notice only; never change a session or order."""
 if type(mode) is not bool or not isinstance(event_id,str) or not re.fullmatch(r'hw-[a-f0-9]{24}',event_id):raise EngineError('invalid_signal_acknowledgement')
 now=now or utc()
 with connect() as c:
  c.execute('BEGIN IMMEDIATE');row=row_for(c,uid,wid,mode)
  action=c.execute("SELECT 1 FROM hw_events WHERE watch_row_id=? AND event_id=? AND event_type IN ('BUY_SIGNAL','SELL_SIGNAL','REDUCE_SIGNAL')",(row['id'],event_id)).fetchone()
  if not action:raise EngineError('signal_not_found',404)
  prior=c.execute("SELECT 1 FROM hw_events WHERE watch_row_id=? AND event_type='SIGNAL_ACKNOWLEDGED' AND json_extract(payload,'$.supporting_metrics.action_event_id')=?",(row['id'],event_id)).fetchone()
  if not prior:event(c,row,'SIGNAL_ACKNOWLEDGED',now,'Advarsel læst; ingen ændring af signal eller handel',{'action_event_id':event_id})
 return {'ok':True,'event_id':event_id,'acknowledged':True}

def item(connect,uid,wid,mode=False):
 with connect() as c:return {'session':view(c,row_for(c,uid,wid,mode))}

def installed_revision():
 """A commit is reported only when explicit archive/deployment metadata exists."""
 from pathlib import Path
 value=os.environ.get('ESCAPE_BUILD_COMMIT','').strip();source='ESCAPE_BUILD_COMMIT'
 if not re.fullmatch(r'[0-9a-fA-F]{40}',value):
  try:value=Path(__file__).with_name('BUILD_COMMIT').read_text(encoding='ascii').strip();source='archive metadata'
  except (OSError,UnicodeError):value=''
 return {'commit':value.lower() if re.fullmatch(r'[0-9a-fA-F]{40}',value) else None,'source':source if re.fullmatch(r'[0-9a-fA-F]{40}',value) else 'unavailable'}

def sync(connect,uid,mode=False,after=0,limit=50,sessions_after=0,session_limit=100,summary_only=False):
 """Read owned open sessions and events with separate pagination cursors."""
 # Rendering a full session includes several dependent reads. Bound the
 # consistent snapshot so one status request cannot hold a read lock across
 # every session; existing cursors continue to expose the complete list.
 session_limit=min(session_limit,10);now=utc()
 from hotwatch_supervisor import application_error_fallback
 application_errors=application_error_fallback()
 from hotwatch_service import recent_scan_log
 with connect() as c:
  c.execute('BEGIN')
  opened=c.execute("SELECT * FROM hw_sessions WHERE user_id=? AND is_test=? AND id>? AND status IN ('CREATED','VALIDATING','ACTIVE','PAUSED','DEGRADED') ORDER BY id LIMIT ?",(uid,int(mode),sessions_after,session_limit+1)).fetchall()
  beat=c.execute('SELECT updated,status FROM hw_heartbeat WHERE id=1').fetchone();worker=dict(beat) if beat else None
  supervisor_row=c.execute('SELECT updated,status,reason,attempts FROM hw_supervisor_status WHERE id=1').fetchone()
  supervisor=dict(supervisor_row) if supervisor_row else None
  supervisor_events=[dict(row) for row in c.execute('SELECT created,event,code FROM hw_supervisor_events ORDER BY id DESC LIMIT 30').fetchall()]
  try:worker_fresh=bool(worker and worker['status']=='running' and 0<=(now-stamp(worker['updated'])).total_seconds()<15)
  except (ValueError,TypeError):worker_fresh=False
  events=c.execute('SELECT e.id,e.event_id,e.event_type,e.severity,e.created,e.data_timestamp,e.payload,s.watch_id,s.candidate_id FROM hw_events e JOIN hw_sessions s ON s.id=e.watch_row_id WHERE s.user_id=? AND s.is_test=? AND e.id>? ORDER BY e.id LIMIT ?',(uid,int(mode),after,limit+1)).fetchall()
  items=[{'sequence':r['id'],'event_id':r['event_id'],'event_type':r['event_type'],'severity':r['severity'],'created_at':r['created'],'data_timestamp':r['data_timestamp'],'watch_id':r['watch_id'],'candidate_id':r['candidate_id'],**({} if summary_only else {'data':json.loads(r['payload'])})} for r in events[:limit]]
  sessions=[]
  for r in opened[:session_limit]:
   req=json.loads(r['request']);purpose=req.get('purpose','');source='holding' if req.get('watch_mode')=='exit' or req.get('report_id')=='automatic-holdings' or purpose in ('automatic holding watch',) or purpose.startswith('retained exit ') else 'manual' if req.get('report_id')=='manual-pluto' else 'candidate'
   if summary_only:
    recovery=c.execute('SELECT status,next_attempt FROM hw_feed_recovery WHERE watch_row_id=?',(r['id'],)).fetchone()
    provisional=c.execute('SELECT symbol FROM hw_provisional_feed_links WHERE watch_row_id=?',(r['id'],)).fetchone()
    unverified=bool(provisional and req.get('provider')=='eodhd')
    sample=c.execute("SELECT json_extract(payload,'$.verification') AS verification FROM hw_samples WHERE watch_row_id=? ORDER BY event_epoch DESC,id DESC LIMIT 1",(r['id'],)).fetchone()
    review=None
    if source=='candidate':
     from intel_workflows import candidate_currentness
     review=candidate_currentness(c,uid,mode,r['candidate_id'],now,report_fallback=purpose=='automatic discovery')
    detail=view(c,r,now);data_status=detail['data_status']
    if not mode and purpose in ('automatic discovery','automatic holding watch') and req.get('provider')=='eodhd' and not data_status['instrument_match_verified']:unverified=True
    calculation=detail.get('latest_calculation') or {}
    reasons=calculation.get('reason_codes') if isinstance(calculation,dict) else None
    if not isinstance(reasons,list):reasons=[]
    reasons=[x for x in reasons if isinstance(x,str) and re.fullmatch(r'[A-Z0-9_]{1,80}',x)][:30]
    health=c.execute('SELECT attempted,succeeded,code,payload FROM hw_provider_health WHERE user_id=? AND is_test=? AND source=?',(uid,int(mode),req.get('provider'))).fetchone()
    provider_diagnostics=None
    if health:
     try:
      payload=json.loads(health['payload']);allowed=('websocket_trade_status','websocket_quote_status','websocket_status_status','exchange_status','minute_bars_status','bar_history_status','intraday_status')
      fields={k:payload[k] for k in allowed if isinstance(payload,dict) and isinstance(payload.get(k),str) and re.fullmatch(r'[A-Z0-9_]{1,80}',payload[k])}
      timing={k:payload[k] for k in ('begin_wait_ms','scope_entry_wait_ms','sqlite_begin_ms','work_before_commit_ms','ingest_compute_ms') if isinstance(payload,dict) and type(payload.get(k)) in (int,float) and 0<=payload[k]<=3600000}
      pipeline={k:payload[k] for k in ('provider_ms','pluto_context_ms','websocket_capture_ms','adapter_to_journal_ms','event_to_adapter_receive_ms') if isinstance(payload,dict) and type(payload.get(k)) in (int,float) and 0<=payload[k]<=3600000}
      provider_diagnostics={'scope':'provider_wide_not_session','last_attempt_at':health['attempted'],'last_success_at':health['succeeded'],'last_error':health['code'],'last_successful_feed_statuses':fields,'last_successful_sqlite_timing_ms':timing,'last_successful_pipeline_timing_ms':pipeline}
      settings=payload.get('worker_settings') if isinstance(payload,dict) else None
      if isinstance(settings,dict):provider_diagnostics['worker_settings']={k:v for k,v in settings.items() if k.startswith('ESCAPE_HW_') and (v is None or isinstance(v,str) and re.fullmatch(r'[A-Za-z0-9_,.-]{0,100}',v))}
      for key in ('session_capacity','parallel_scans_default','concurrency_default'):
       if type(payload.get(key)) is int:provider_diagnostics[key]=payload[key]
      worker_timing=payload.get('worker_database_timing') if isinstance(payload,dict) else None
      if isinstance(worker_timing,dict) and worker_timing.get('scope')=='worker_process':
       safe={'scope':'worker_process','basis':'high_water_since_worker_start'}
       safe.update({k:worker_timing[k] for k in ('completed_scopes','max_wait_ms','max_scope_ms') if type(worker_timing.get(k)) in (int,float) and 0<=worker_timing[k]<=1000000000})
       safe.update({k:worker_timing[k] for k in ('slowest_module','slowest_function') if isinstance(worker_timing.get(k),str) and re.fullmatch('[A-Za-z_][A-Za-z0-9_]{0,79}',worker_timing[k])})
       provider_diagnostics['worker_database_timing']=safe
     except (ValueError,TypeError):pass
    context_diagnostic=(detail.get('latest_context') or {}).get('diagnostic')
    if not isinstance(context_diagnostic,str) or not re.fullmatch(r'[A-Z0-9_]{1,100}',context_diagnostic):context_diagnostic=None
    sessions.append({'watch_id':r['watch_id'],'candidate_id':r['candidate_id'],'ticker':req.get('ticker'),'status':r['status'],'purpose':purpose,'watch_kind':source,'watch_mode':req.get('watch_mode','both'),'candidate_review':review,'updated_at':r['updated'],'last_data_at':r['last_data'],'last_calculation_at':r['last_calculation'],'last_computed_signal':detail['last_computed_signal'],'signal':detail['signal'],'display_status':detail['display_status'],'last_action_signal':detail['last_action_signal'],'context_diagnostic':context_diagnostic,'last_calculation_reason_codes':reasons,'display_reason_codes':detail['display_reason_codes'],'next_due_at':detail['next_due_at'],'effective_min_interval_s':detail['effective_min_interval_s'],'interval_basis':detail['interval_basis'],'provider_feed_diagnostics':provider_diagnostics,'provider':req.get('provider'),'last_error':r['last_error'],'identity_verification':'unverified' if unverified else sample['verification'] if sample else None,'holding_verified':data_status['holding_verified'],'instrument_match_verified':data_status['instrument_match_verified'],'instrument_match_evidence':data_status['instrument_match_evidence'],'reference_candidate':data_status.get('reference_candidate'),'quote_feed_verified':data_status['quote_feed_verified'],'quote_freshness':data_status['quote_freshness'],'price_status':data_status.get('price_status'),'bid_ask_status':data_status.get('quote_status'),'bar_blocking_detail':data_status.get('bar_blocking_detail'),'next_market_session':data_status.get('next_market_session'),'feed_recovery_status':recovery['status'] if recovery else None,'next_feed_recovery_at':datetime.fromtimestamp(recovery['next_attempt'],timezone.utc).isoformat() if recovery else None})
   else:sessions.append({**view(c,r,now),'candidate_id':r['candidate_id'],'ticker':req.get('ticker'),'purpose':purpose,'watch_kind':source,'watch_mode':req.get('watch_mode','both')})
  more=len(opened)>session_limit
  from eodhd_capacity import snapshot as capacity_snapshot
  return {'installation':installed_revision(),'worker_scan_log':recent_scan_log(uid,mode,[r['watch_id'] for r in opened[:session_limit]]),'provider_capacity':capacity_snapshot(c,now.timestamp()),'as_of':now.isoformat(),'is_test':mode,'open_sessions':sessions,'open_sessions_complete':sessions_after==0 and not more,'next_sessions_cursor':opened[session_limit-1]['id'] if more else None,'sessions_have_more':more,'worker':worker,'worker_heartbeat_fresh':worker_fresh,'supervisor':supervisor,'supervisor_events':supervisor_events,'application_error_fallback':application_errors,'events':items,'next_cursor':items[-1]['sequence'] if items else after,'has_more':len(events)>limit,'detail_level':'status' if summary_only else 'full'}

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
   if request.get('watch_mode','both')=='entry' and request.get('report_id')!='manual-pluto':
    from intel_workflows import candidate_currentness
    if candidate_currentness(c,uid,mode,row['candidate_id'],now,report_fallback=request.get('purpose')=='automatic discovery')['status'] not in ('CURRENT','REVIEW_DUE','REPORT_ONLY'):raise EngineError('candidate_not_current',409)
   new='VALIDATING'
  elif action=='stop':new='COMPLETED'
  else:raise EngineError('unknown_action')
  if status==new or action=='resume' and status in ['VALIDATING','ACTIVE']:return {'ok':True,'duplicate':True,'session':view(c,row,now)}
  if status in ['EXPIRED','COMPLETED','ERROR']:raise EngineError('watch_is_terminal',409)
  c.execute('UPDATE hw_sessions SET status=?,updated=?,revision=revision+1,lease_owner=NULL,lease_until=0,next_due=?,state=? WHERE id=?',(new,now.isoformat(),now.timestamp(),canonical({**json.loads(row['state']),'signal':'PAUSE' if action=='pause' else 'NO_DATA','pending':None,'confirmations':0}),row['id']))
  event(c,row,{'pause':'WATCH_PAUSED','resume':'WATCH_RESUMED','stop':'WATCH_COMPLETED'}[action],now,action)
  return {'ok':True,'duplicate':False,'session':view(c,row_for(c,uid,wid,mode),now)}

def reset_automatic_candidates(connect,uid,now=None):
 """Explicit operator reset of running entry-only radar watches, not holdings."""
 now=now or utc();closed=[];paused=0;generation=secrets.token_hex(16)
 with connect() as c:
  c.execute('BEGIN IMMEDIATE')
  if not c.execute('SELECT 1 FROM users WHERE id=? AND active=1',(uid,)).fetchone():raise EngineError('user_not_found',404)
  rows=c.execute("SELECT * FROM hw_sessions WHERE user_id=? AND is_test=0 AND purpose='automatic discovery' AND status IN ('CREATED','VALIDATING','ACTIVE','PAUSED','DEGRADED')",(uid,)).fetchall()
  for row in rows:
   request=json.loads(row['request'])
   if request.get('watch_mode')!='entry':continue
   if row['status']=='PAUSED':paused+=1;continue
   c.execute("UPDATE hw_sessions SET status='COMPLETED',updated=?,revision=revision+1,lease_owner=NULL,lease_until=0 WHERE id=?",(now.isoformat(),row['id']))
   event(c,row,'WATCH_RESET',now,'Brugerbestilt nulstilling af rapportkandidat; historik og beholdningsovervågning bevares')
   closed.append({'watch_id':row['watch_id'],'candidate_id':row['candidate_id'],'ticker':request.get('ticker')})
  previous=c.execute('SELECT reset_at FROM hw_discovery_resets WHERE user_id=?',(uid,)).fetchone()
  if not closed and previous:return {'reset_at':previous['reset_at'],'closed':[],'paused_preserved':paused,'new_assessment_required':True,'duplicate':True}
  c.execute("UPDATE hw_holding_autowatch SET next_attempt=? WHERE user_id=? AND status='CAPACITY_LIMIT'",(now.timestamp(),uid))
  c.execute('INSERT INTO hw_discovery_resets VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET reset_at=excluded.reset_at,generation=excluded.generation',(uid,now.isoformat(),generation))
 return {'reset_at':now.isoformat(),'closed':closed,'paused_preserved':paused,'new_assessment_required':True,'duplicate':False}

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
  if sample['market_status']!='UNKNOWN':
   if not sample.get('status_at') or not sample.get('status_feed'):raise EngineError('market_status_evidence_missing')
   if not 0<=(now-stamp(sample['status_at'])).total_seconds()<=request['risk']['max_quote_age_s']:raise EngineError('market_status_evidence_stale')
 # Optional analytical history cannot invalidate an otherwise valid market
 # observation. Its eligibility is checked separately before feature calculation.
 context=sample['context']
 if context['as_of'] and stamp(context['as_of'])>now:raise EngineError('future_position_context')
 if context.get('instrument_type_at') and stamp(context['instrument_type_at'])>now:raise EngineError('future_position_context')
 if context['position']=='held' and (context['quantity'] is None or Decimal(context['quantity'])<=0):raise EngineError('invalid_position_quantity')
 if context['position']=='none' and context['quantity'] is not None and Decimal(context['quantity'])!=0:raise EngineError('invalid_position_quantity')
 return sample

def analysis_snapshot(c,row,sample,request,now):
 """Immutable history/version for pure feature work outside the writer lock."""
 newest=c.execute('SELECT id,digest FROM hw_samples WHERE watch_row_id=? ORDER BY id DESC LIMIT 1',(row['id'],)).fetchone()
 version=(row['request'],row['strategy'],(newest['id'],newest['digest']) if newest else None)
 bars=verified_bar_samples(sample,request,now) if sample.get('bar_history') else None
 if bars is not None:samples=[sample]
 else:
  prior=c.execute('SELECT payload FROM hw_samples WHERE watch_row_id=? AND event_epoch<? ORDER BY event_epoch DESC,id DESC LIMIT 119',(row['id'],stamp(sample['event_time']).timestamp())).fetchall()
  samples=[json.loads(r['payload']) for r in reversed(prior)]+[sample]
 return version,bars,samples

def sample_conflict(previous,current,keys):
 """Describe rejected market differences without exposing broker context."""
 error=EngineError('sample_id_conflict',409)
 fields=sorted(k for k in keys if k!='context' and k in SAMPLE['properties'] and previous.get(k)!=current.get(k))
 public={'event_time','price','bid','ask','volume','volume_type','open','high','low','close','trade_size','interval_s','price_time_kind','market_status','bid_at','ask_at','status_at'}
 error.market_conflict={'fields':fields,'previous':{k:previous.get(k) for k in fields if k in public},'incoming':{k:current.get(k) for k in fields if k in public}}
 # Safe market-only identity and original event times make two conflicting
 # observations diagnosable without recording broker context or credentials.
 def observation(sample):
  result={}
  if sample.get('source') in ('eodhd','pluto','synthetic','report_inbox'):result['source']=sample['source']
  if sample.get('price_time_kind') in ('trade','bar_open'):result['price_time_kind']=sample['price_time_kind']
  feed=sample.get('feed_type')
  if isinstance(feed,str):
   for prefix,kind in (('EODHD WebSocket us trade','US_WS_TRADE'),('EODHD WebSocket eu trade','EU_WS_TRADE'),('EODHD realtime closed 1m bar','REALTIME_BAR'),('EODHD intraday closed 1m bar','INTRADAY_BAR'),('EODHD REST real-time endpoint','REST_SNAPSHOT')):
    if feed.startswith(prefix):result['feed_kind']=kind;break
  for key in ('event_time','bid_at','ask_at','status_at'):
   try:
    if sample.get(key):result[key]=stamp(sample[key]).isoformat()
   except (ValueError,TypeError,AttributeError):pass
  identity=sample.get('sample_id')
  if isinstance(identity,str) and identity:result['sample_ref']=hashlib.sha256(identity.encode()).hexdigest()[:16]
  return result
 error.market_conflict['observations']={'previous':observation(previous),'incoming':observation(current)}
 return error

def refreshed_trade_evidence(previous,current,request,now):
 """Renew separately timestamped evidence, never the trade or confirmations."""
 groups=[('bid_at',('bid','ask','bid_at','ask_at','quote_feed')),
         ('status_at',('market_status','session_key','status_at','status_feed')),
         ('bar_evidence',('bar_history','bar_evidence'))]
 auxiliary={'context','sample_id','interval_s'}|{k for _,keys in groups for k in keys}
 if previous.get('source')!='eodhd' or previous.get('price_time_kind')!='trade':return current
 if {k:v for k,v in previous.items() if k not in auxiliary}!={k:v for k,v in current.items() if k not in auxiliary}:raise sample_conflict(previous,current,(set(previous)|set(current))-auxiliary)
 merged=dict(previous,context=current['context'])
 for time_key,keys in groups:
  if time_key=='bar_evidence':
   if verified_bar_samples(current,request,now) is None:continue
   old_time=(previous.get('bar_evidence') or {}).get('schedule_received_at');new_time=current['bar_evidence']['schedule_received_at']
   if previous.get('bar_history') and stamp(current['bar_history'][-1]['bar_open_at'])<stamp(previous['bar_history'][-1]['bar_open_at']):continue
  else:
   old_time=previous.get(time_key);new_time=current.get(time_key)
   if time_key=='bid_at' and previous.get('ask_at') and current.get('ask_at') and stamp(current['ask_at'])<stamp(previous['ask_at']):continue
  if not new_time or old_time and stamp(new_time)<stamp(old_time):continue
  def changed(k):
   old,new=previous.get(k),current.get(k)
   if k in ('bid_at','ask_at','status_at') and old and new:return stamp(old)!=stamp(new)
   return old!=new
  if old_time and stamp(old_time)==stamp(new_time) and time_key!='bar_evidence':
   if any(changed(k) for k in keys):
    if time_key!='bid_at':raise sample_conflict(previous,current,keys)
    # Distinct venue quotes may share the same millisecond. Without a source
    # sequence their ordering is unknowable: keep the trade, invalidate the
    # ambiguous spread, and do not accept that timestamp again as fresh proof.
    merged.update(bid=None,ask=None,bid_at=old_time,ask_at=previous.get('ask_at') or old_time,quote_feed=None)
   continue
  for key in keys:
   if key in current:merged[key]=current[key]
   else:merged.pop(key,None)
 return merged

def ingest(connect,uid,wid,mode,sample,now=None,lease=None,include_session=True):
 now=now or utc()
 prepared_version=None
 try:
  with connect() as c:
   preview=row_for(c,uid,wid,mode);preview_request=json.loads(preview['request']);sample_errors(sample,preview_request,now)
   prepared_version,prepared_bars,prepared_samples=analysis_snapshot(c,preview,sample,preview_request,now)
  prepared_metrics=features(prepared_bars if prepared_bars is not None else prepared_samples,json.loads(preview['strategy'])['parameters'])
 except EngineError:
  # Keep authoritative lease, ownership and identity checks in their original
  # order below. An invalid input cannot use this optional precomputation.
  prepared_version=None
 lock_requested=time.perf_counter()
 with connect() as c:
  # Scope entry includes the worker's serialized gate and connection setup;
  # BEGIN time includes the SQL call itself, not only lock contention.
  scope_entered=time.perf_counter()
  c.execute('BEGIN IMMEDIATE');lock_acquired=time.perf_counter();row=row_for(c,uid,wid,mode);request=json.loads(row['request'])
  if lease and (row['lease_owner']!=lease or row['lease_until']<now.timestamp()):raise EngineError('lease_lost',409)
  if row['status'] not in ['CREATED','VALIDATING','ACTIVE','DEGRADED']:raise EngineError('watch_not_running',409)
  killed=c.execute('SELECT killed FROM hw_control WHERE user_id=?',(uid,)).fetchone()
  if killed and killed['killed']:raise EngineError('kill_switch_active',409)
  if c.execute('SELECT killed FROM hw_system_control WHERE id=1').fetchone()[0]:raise EngineError('operator_kill_switch',409)
  if request.get('provider')=='eodhd':
   from instrument_resolver import BTC_PLUTO_ASSET_ID,PEPE_PLUTO_ASSET_ID
   valid=valid_cxe_evidence(c,uid,request,now)
   if request.get('asset_id')==PEPE_PLUTO_ASSET_ID:raise EngineError('EODHD_INSTRUMENT_UNVERIFIED',409)
   if valid is False or request.get('asset_id')==BTC_PLUTO_ASSET_ID and valid is not True:raise EngineError('EODHD_INSTRUMENT_REVALIDATION_REQUIRED',409)
  provisional=c.execute('SELECT symbol FROM hw_provisional_feed_links WHERE watch_row_id=?',(row['id'],)).fetchone()
  if provisional and isinstance(sample,dict) and request.get('provider')=='eodhd':
   if not mode:raise EngineError('EODHD_INSTRUMENT_UNVERIFIED',409)
   sample=dict(sample);sample['verification']='unverified';sample.pop('bar_history',None);sample.pop('bar_evidence',None)
  if request.get('provider')=='eodhd' and not mode and request.get('purpose') in ('automatic discovery','automatic holding watch') and not verified_automatic_feed(c,uid,request,now):raise EngineError('EODHD_INSTRUMENT_REVALIDATION_REQUIRED',409)
  if request['end_at'] and stamp(request['end_at'])<=now:
   c.execute("UPDATE hw_sessions SET status='EXPIRED',updated=?,lease_owner=NULL,lease_until=0 WHERE id=?",(now.isoformat(),row['id']));event(c,row,'WATCH_EXPIRED',now,'Session deadline reached');return {'ok':True,'expired':True}
  sample_errors(sample,request,now)
  newest=c.execute('SELECT id,digest FROM hw_samples WHERE watch_row_id=? ORDER BY id DESC LIMIT 1',(row['id'],)).fetchone()
  same_history=prepared_version==(row['request'],row['strategy'],(newest['id'],newest['digest']) if newest else None) and sample==prepared_samples[-1]
  old=c.execute('SELECT id,digest,payload,received FROM hw_samples WHERE watch_row_id=? AND source=? AND sample_id=?',(row['id'],sample['source'],sample['sample_id'])).fetchone()
  if old is None and row['last_data'] and stamp(sample['event_time'])==stamp(row['last_data']):old=c.execute('SELECT id,digest,payload,received FROM hw_samples WHERE watch_row_id=? AND source=? AND event_epoch=? ORDER BY id DESC LIMIT 1',(row['id'],sample['source'],stamp(sample['event_time']).timestamp())).fetchone()
  new_market_event=True
  if old:
   if row['last_data'] and stamp(json.loads(old['payload'])['event_time'])!=stamp(row['last_data']):raise EngineError('historical_sample_context_update',409)
   previous_sample=json.loads(old['payload']);incoming=sample
   try:sample=refreshed_trade_evidence(previous_sample,sample,request,now)
   except EngineError as error:
    if error.code=='sample_id_conflict' and getattr(error,'market_conflict',None):error.market_conflict.update(previous_journal_received_at=old['received'],ingest_attempt_at=now.isoformat())
    raise
   if sample!=incoming:
    same_history=False;sample_errors(sample,request,now)
   previous_market={k:v for k,v in previous_sample.items() if k not in ['context','sample_id']};current_market={k:v for k,v in sample.items() if k not in ['context','sample_id']}
   evidence_changed=previous_market!=current_market
   if evidence_changed and not (sample['source']=='eodhd' and sample.get('price_time_kind')=='trade'):
    error=sample_conflict(previous_sample,sample,set(previous_market)|set(current_market))
    error.market_conflict.update(previous_journal_received_at=old['received'],ingest_attempt_at=now.isoformat())
    raise error
   extra=c.execute('SELECT payload FROM hw_context_events WHERE watch_row_id=? ORDER BY id DESC LIMIT 1',(row['id'],)).fetchone()
   prior_context=json.loads(extra['payload']) if extra else previous_sample['context'];current_context=sample['context']
   if prior_context.get('as_of') and current_context.get('as_of') and stamp(current_context['as_of'])<stamp(prior_context['as_of']):
    current_context=prior_context;sample=dict(sample,context=prior_context);same_history=False
   material=lambda context:{k:v for k,v in context.items() if k!='as_of'}
   fresh=lambda context:bool(context['as_of'] and 0<=now.timestamp()-stamp(context['as_of']).timestamp()<=300)
   renewed=current_context.get('as_of') and (not prior_context.get('as_of') or stamp(current_context['as_of'])>stamp(prior_context['as_of']))
   if material(prior_context)==material(current_context) and fresh(prior_context)==fresh(current_context) and not renewed and not evidence_changed:
    result={'ok':True,'duplicate':True}
    if include_session:result['session']=view(c,row,now)
    return result
   if prior_context!=current_context:
    c.execute('INSERT INTO hw_context_events(watch_row_id,sample_row_id,observed,payload) VALUES(?,?,?,?)',(row['id'],old['id'],now.isoformat(),canonical(current_context)))
    event(c,row,'BROKER_CONTEXT_UPDATED',now,'Position/order context changed; no new market observation',data_time=current_context['as_of'])
   if evidence_changed:
    c.execute('UPDATE hw_samples SET payload=?,digest=? WHERE id=?',(canonical(sample),checksum(sample),old['id']))
    event(c,row,'MARKET_EVIDENCE_UPDATED',now,'Quote/calendar evidence renewed; original trade time unchanged',metrics={'previous_digest':old['digest'],'current_digest':checksum(sample),'bid_at':sample.get('bid_at'),'ask_at':sample.get('ask_at'),'status_at':sample.get('status_at')},data_time=sample['event_time'])
   sample_row_id=old['id'];new_market_event=False
  else:
   if row['last_data'] and stamp(sample['event_time'])<=stamp(row['last_data']):raise EngineError('out_of_order_market_data',409)
   cur=c.execute('INSERT INTO hw_samples(watch_row_id,source,sample_id,event_epoch,received,payload,digest) VALUES(?,?,?,?,?,?,?)',(row['id'],sample['source'],sample['sample_id'],stamp(sample['event_time']).timestamp(),now.isoformat(),canonical(sample),checksum(sample)))
   sample_row_id=cur.lastrowid
  strategy_data=json.loads(row['strategy']);state=json.loads(row['state'])
  previous_calculation=c.execute('SELECT payload FROM hw_calculations WHERE watch_row_id=? ORDER BY id DESC LIMIT 1',(row['id'],)).fetchone() if state.get('signal')=='SELL' or state.get('pending')=='SELL' else None
  if previous_calculation:
   prior=json.loads(previous_calculation['payload']);codes=set(prior.get('reason_codes',[]))
   if 'TRAILING_EXIT' in codes and prior.get('signal_basis') not in ('verified_position_high','price_context') and not codes.intersection({'STOP_BREACHED','EXIT_DEADLINE'}):
    state.update(signal='NO_DATA',pending=None,confirmations=0,pending_since=None)
  if same_history:
   bar_samples,samples,metrics=prepared_bars,prepared_samples,prepared_metrics
  else:
   # A concurrent update invalidates the prepared calculation; never commit it.
   _,bar_samples,samples=analysis_snapshot(c,row,sample,request,now)
   metrics=features(bar_samples if bar_samples is not None else samples,strategy_data['parameters'])
  if bar_samples is not None:
   live_metrics=features([sample],strategy_data['parameters'])
   reference=max(Decimal(b['price']) for b in bar_samples[-metrics['sample_count']:])
   metrics.update(price=sample['price'],distance_high_pct=format((Decimal(sample['price'])/max(reference,Decimal(sample['price']))-1)*100,'f'),spread=live_metrics.get('spread'),spread_pct=live_metrics.get('spread_pct'),bar_history_count=len(bar_samples))
  elif new_market_event and sample.get('source')=='eodhd' and sample.get('verification')=='verified':
   # Historical bars provide indicator context only for a new, genuinely
   # observed live sample. All existing market, freshness and risk gates in
   # calculate() remain mandatory; a history fetch never runs calculate().
   import hotwatch_warmup
   history=hotwatch_warmup.status(c,row,request,now)
   safe_session=sample.get('market_status') in ('UNKNOWN','CLOSED','HALTED') or history and hotwatch_warmup.signal_session_verified(c,request,sample,history,now)
   if history and safe_session and history['historical_count']>0 and history['freshness']=='FRESH' and history.get('latest_live_sample_id')==sample['sample_id']:
    live_metrics=features([sample],strategy_data['parameters']);metrics=dict(history['metrics']);metrics.update(price=sample['price'],spread=live_metrics.get('spread'),spread_pct=live_metrics.get('spread_pct'),bar_history_count=history['historical_count'])
  if sample.get('bar_history') and bar_samples is None:metrics['bar_history_status']='INVALID_OR_STALE'
  pilot=None
  if strategy_data.get('schema_version')==2:
   import strategy_center
   pilot=strategy_center.early_inputs(c,row,request,sample,metrics,now)
  import intel_workflows,candidate_lifecycle
  decision=intel_workflows.prior_decision(c,uid,mode,request['candidate_id'])
  from intel_workflows import candidate_currentness
  currentness={'status':'CURRENT'} if request.get('report_id')=='manual-pluto' else candidate_currentness(c,uid,mode,row['candidate_id'],now,report_fallback=request.get('purpose')=='automatic discovery') if request.get('report_id')!='automatic-holdings' else {'status':'UNKNOWN'}
  risk=dict(request['risk'],entry_allowed=request.get('watch_mode','both')!='exit' and currentness['status'] in ('CURRENT','REVIEW_DUE') and (not decision or decision[1]['status']!='FRAVÆLG'),exit_allowed=request.get('watch_mode','both')!='entry')
  # Never aggregate high-water marks across depots or trade cycles.
  if len(request.get('portfolio_ids',[]))==1:
   risk['_position_scope']=checksum({'asset_id':request['asset_id'],'portfolio_id':request['portfolio_ids'][0],'watch_id':wid,'trade_cycle_id':request.get('trade_cycle_id')})
  import hotwatch_buy_plan
  risk_sample,risk,buy_plan=hotwatch_buy_plan.apply(c,row,request,sample,risk,now)
  result,nextstate=calculate(risk_sample,metrics,strategy_data,risk,state,now,new_market_event=new_market_event)
  if pilot is not None:
   from hotwatch_strategy import early_watch
   if early_watch(strategy_data,metrics):pilot['watch_state']='EARLY_WATCH'
   result['early_catalyst']=pilot
  result['analysis_uses_bars']=bar_samples is not None
  result['position_context']=risk_sample['context'];result['new_market_observation']=new_market_event
  result.update(engine_version='1.0-phase1-2',feature_version='1.3.0',risk_version='1.1.0',global_risk_limits=GLOBAL_RISK,algorithm_constraints={'max_volatility_pct':'5','max_price_gap_pct':'5','max_action_signals_hour':20,'max_context_age_s':300},risk_parameters=risk,prior_signal_state=state,input_sample_ids=[s['sample_id'] for s in samples])
  metrics['quote_age_s']=format(Decimal(str(now.timestamp()-stamp(sample['event_time']).timestamp())),'f');result['supporting_metrics']=metrics
  c.execute('INSERT INTO hw_calculations(watch_row_id,sample_row_id,calculated,payload,strategy_checksum) VALUES(?,?,?,?,?)',(row['id'],sample_row_id,now.isoformat(),canonical(result),result['strategy_checksum']))
  cycle=request.get('trade_cycle_id') or 'cycle:'+checksum({'watch_id':wid})[:24]
  if result['signal']=='BUY' and state.get('signal')!='BUY':candidate_lifecycle.record(c,uid,mode,request['candidate_id'],'BUY_SIGNAL',now.isoformat(),'Deterministisk motor, ikke en udført handel',wid,cycle)
  if sample['source']!='report_inbox':candidate_lifecycle.observe_pluto(c,uid,mode,request['candidate_id'],sample['context'],now.isoformat(),wid,cycle,result['signal'],synthetic=sample['source']=='synthetic')
  # A holding observation proves current ownership, not its acquisition
  # from an accepted intent. Do not propagate it to an inferred origin cycle.
  normal_close=result['signal']=='PAUSE' and 'MARKET_CLOSED' in result['reason_codes'] and not (set(result['reason_codes'])-{'MARKET_CLOSED','WARMUP'})
  new_status='DEGRADED' if result['signal'] in ['NO_DATA','PAUSE'] and not normal_close else 'ACTIVE'
  codes=set(result['reason_codes'])&{'DATA_UNVERIFIED','DATA_STALE','DATA_FUTURE','MARKET_HALTED','MARKET_CLOSED','MARKET_STATUS_UNKNOWN','POSITION_CONTEXT_UNKNOWN','SPREAD_TOO_WIDE','SPREAD_UNKNOWN','LOSS_BUDGET_LIMIT','POSITION_SIZE_LIMIT','EXPOSURE_LIMIT','STOP_BREACHED','EXIT_DEADLINE','RISK_INPUTS_UNKNOWN'}
  oldcodes=set(state.get('alert_codes',[]))
  for code in sorted(codes-oldcodes):event(c,row,'DATA_STALE' if code=='DATA_STALE' else 'RISK_REJECTION',now,code,metrics,'critical' if code in ['STOP_BREACHED','EXIT_DEADLINE'] else 'warning',sample['event_time'])
  if oldcodes-codes:event(c,row,'DATA_RECOVERED',now,';'.join(sorted(oldcodes-codes)),metrics,data_time=sample['event_time'])
  if result['signal']!=state.get('signal','NO_DATA'):event(c,row,{'BUY':'BUY_SIGNAL','SELL':'SELL_SIGNAL','REDUCE':'REDUCE_SIGNAL','WAIT':'WAIT_SIGNAL','NO_DATA':'NO_DATA','PAUSE':'WATCH_PAUSED'}[result['signal']],now,result['human_readable_explanation'],metrics,'critical' if result['critical_override'] else 'info',sample['event_time'])
  if result['critical_override'] and state.get('signal')!='SELL':event(c,row,'CRITICAL_OVERRIDE',now,'Critical exit bypassed confirmation/cooldown; no order created',metrics,'critical',sample['event_time'])
  # Notification episode state is separate from the calculated signal. WAIT or
  # NO_DATA alone cannot end an exit; a new, valid no-trigger observation can.
  reason_set=set(result['reason_codes'])
  rearmed=new_market_event and result['signal']=='WAIT' and reason_set=={'NO_TRIGGER'} and result['risk_level']=='normal' and risk_sample['context'].get('position')=='held'
  if rearmed:
   nextstate.pop('push_trailing_anchor',None)
   nextstate.pop('push_critical_anchors',None)
  # Critical stops normally emit only on a code transition. While the stop
  # stays breached, emit a new notification event when the existing strategy's
  # trailing distance is exceeded or verified exit exposure/limits change.
  # These anchors affect notifications only, never the calculated signal.
  stored_anchors=state.get('push_critical_anchors')
  anchors={} if rearmed or not isinstance(stored_anchors,dict) else dict(stored_anchors)
  context=risk_sample['context']
  if context.get('status')=='verified' and context.get('position')=='held' and context.get('quantity') is not None and sample.get('price'):
   for code in sorted(codes&{'STOP_BREACHED','EXIT_DEADLINE'}):
    current={'price':str(sample['price']),'quantity':format(Decimal(str(context['quantity'])).normalize(),'f'),'stop_price':format(Decimal(str(risk['stop_price'])).normalize(),'f') if risk.get('stop_price') is not None else None,'exit_deadline':risk.get('exit_deadline'),'strategy_checksum':result['strategy_checksum']}
    old=anchors.get(code)
    if not isinstance(old,dict) or not old.get('price'):old=None
    changed=bool(old and any(old.get(k)!=current[k] for k in ('quantity','stop_price','exit_deadline','strategy_checksum')))
    try:
     threshold=Decimal(str(strategy_data['parameters']['trailing_pct']))
     if not threshold.is_finite() or not Decimal('0')<threshold<=Decimal('100'):
      worsened=bool(old and new_market_event and Decimal(current['price'])!=Decimal(str(old['price'])))
     else:worsened=bool(old and new_market_event and trailing_notification_worsened(current['price'],old['price'],threshold))
    except (ArithmeticError,TypeError,ValueError,KeyError):old=None;worsened=False
    if code in oldcodes and (old is None or changed or worsened):
     event(c,row,'RISK_REJECTION',now,code,metrics,'critical',sample['event_time'])
    if old is None or changed or worsened:anchors[code]=current
   if anchors:nextstate['push_critical_anchors']=anchors
  if new_market_event and result['signal']=='SELL' and 'TRAILING_EXIT' in reason_set and not result['critical_override']:
   price=Decimal(sample['price']);anchor=state.get('push_trailing_anchor')
   threshold=Decimal(str(strategy_data['parameters']['trailing_pct']))
   if anchor is None:nextstate['push_trailing_anchor']=str(price)
   elif trailing_notification_worsened(price,anchor,threshold):
    event(c,row,'TRAILING_EXIT_WORSENED',now,'Trailing-exit er væsentligt forværret',metrics,'warning',sample['event_time'])
    nextstate['push_trailing_anchor']=str(price)
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
  baseline=effective_poll_interval(c,request,adaptive)
  interval=observation_poll_interval(c,request,adaptive,now,sample,baseline=baseline)
  if sample['market_status'] in ['CLOSED','HALTED']:interval=max(interval,300)
  nextstate['scheduled_interval_s']=interval
  nextstate['quiet_market_poll']=interval>baseline
  nextstate['quiet_baseline_s']=baseline if interval>baseline else None
  c.execute('UPDATE hw_sessions SET status=?,state=?,updated=?,last_data=?,last_calculation=?,next_due=?,failures=0,last_error=NULL,lease_owner=NULL,lease_until=0 WHERE id=?',(new_status,canonical(nextstate),now.isoformat(),sample['event_time'],now.isoformat(),now.timestamp()+interval,row['id']))
  response={'ok':True,'duplicate':False,'calculation':result,'sqlite_timing':{'begin_wait_ms':round((lock_acquired-lock_requested)*1000,3),'scope_entry_wait_ms':round((scope_entered-lock_requested)*1000,3),'sqlite_begin_ms':round((lock_acquired-scope_entered)*1000,3),'work_before_commit_ms':round((time.perf_counter()-lock_acquired)*1000,3)}}
  if include_session:response['session']=view(c,row_for(c,uid,wid,mode),now)
  return response

def record_partial_observation(connect,uid,wid,mode,observation,now=None,lease=None):
 """Journal an incomplete price or quote without a signal sample."""
 now=now or utc()
 base={'source','price','currency','source_time','received_at','quality'}
 if not isinstance(observation,dict) or not base<=set(observation) or set(observation)-base-{'bid','ask','trade_size'} or observation['source'] not in ('pluto','eodhd') or observation['quality'] not in ('TIME_UNKNOWN','TRADE_MISSING','QUOTE_ONLY'):raise EngineError('invalid_partial_observation')
 if observation['quality']=='TIME_UNKNOWN' and observation['source_time'] is not None:raise EngineError('invalid_partial_observation')
 if observation['quality'] in ('TRADE_MISSING','QUOTE_ONLY'):
  try:
   if observation['source']!='eodhd' or not observation['source_time'] or stamp(observation['source_time'])>now:raise ValueError()
  except (ValueError,TypeError,AttributeError):raise EngineError('invalid_partial_observation') from None
 if all(observation.get(key) is None for key in ('price','bid','ask')):raise EngineError('invalid_partial_observation')
 for key in ('price','bid','ask','trade_size'):
  value=observation.get(key)
  if value is not None and (not isinstance(value,str) or not re.fullmatch(r'\d{1,31}(?:\.\d{1,12})?',value) or Decimal(value)<0 or key=='price' and Decimal(value)<=0):raise EngineError('invalid_partial_observation')
 received=observation['received_at']
 if received is not None:
  try:
   if stamp(received)>now:raise ValueError()
  except (ValueError,TypeError,AttributeError):raise EngineError('invalid_partial_observation') from None
 with connect() as c:
  c.execute('BEGIN IMMEDIATE');row=row_for(c,uid,wid,mode);request=json.loads(row['request'])
  if lease and (row['lease_owner']!=lease or row['lease_until']<now.timestamp()):raise EngineError('lease_lost',409)
  if row['status'] not in ('CREATED','VALIDATING','ACTIVE','DEGRADED'):raise EngineError('watch_not_running',409)
  if request['provider']!=observation['source'] or request['quote_currency']!=observation['currency']:raise EngineError('invalid_partial_observation')
  if c.execute('SELECT killed FROM hw_system_control WHERE id=1').fetchone()[0]:raise EngineError('operator_kill_switch',409)
  killed=c.execute('SELECT killed FROM hw_control WHERE user_id=?',(uid,)).fetchone()
  if killed and killed['killed']:raise EngineError('kill_switch_active',409)
  previous=c.execute("SELECT payload FROM hw_events WHERE watch_row_id=? AND event_type='PARTIAL_MARKET_OBSERVATION' ORDER BY id DESC LIMIT 1",(row['id'],)).fetchone()
  if previous and json.loads(previous['payload']).get('supporting_metrics')==observation:return False
  event(c,row,'PARTIAL_MARKET_OBSERVATION',now,'Ufuldstændige markedsdata; kun observation, ikke handelssignal',observation,data_time=observation['source_time'])
 return True

def observe_context(connect,uid,wid,mode,context,now=None,lease=None,broker_source=None):
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
  if request['provider'] not in ['pluto','synthetic'] and not (request['provider']=='eodhd' and broker_source=='pluto'):raise EngineError('broker_context_source_required')
  if request['provider']=='synthetic' and not mode:raise EngineError('synthetic_requires_test_mode')
  if request['end_at'] and stamp(request['end_at'])<=now:raise EngineError('watch_not_running',409)
  previous=c.execute('SELECT payload FROM hw_context_events WHERE watch_row_id=? ORDER BY id DESC LIMIT 1',(row['id'],)).fetchone()
  if previous:
   try:
    old=json.loads(previous['payload'])
    if not isinstance(old,dict):raise ValueError('invalid previous context')
    old_time=stamp(old['as_of']) if old.get('as_of') is not None else None
   except (ValueError,TypeError,KeyError):raise EngineError('invalid_previous_position_context',409) from None
   if old_time is not None and stamp(context['as_of'])<old_time:raise EngineError('out_of_order_position_context',409)
   if old==context:return {'ok':True,'duplicate':True}
  c.execute('INSERT INTO hw_context_events(watch_row_id,sample_row_id,observed,payload) VALUES(?,NULL,?,?)',(row['id'],now.isoformat(),canonical(context)))
  import candidate_lifecycle
  cycle=request.get('trade_cycle_id') or 'cycle:'+checksum({'watch_id':wid})[:24]
  candidate_lifecycle.observe_pluto(c,uid,mode,request['candidate_id'],context,now.isoformat(),wid,cycle,'NO_DATA',synthetic=request['provider']=='synthetic')
  material=lambda value:{k:v for k,v in value.items() if k!='as_of'}
  state=json.loads(row['state'])
  from hotwatch_strategy import exit_context_key
  portfolio_ids=request.get('portfolio_ids',[]);scope=checksum({'asset_id':request['asset_id'],'portfolio_id':portfolio_ids[0],'watch_id':wid,'trade_cycle_id':request.get('trade_cycle_id')}) if len(portfolio_ids)==1 else None
  prior_key=state.get('exit_context_key');current_key=exit_context_key(context,scope)
  changed=bool(prior_key and prior_key!=current_key)
  material_changed=not previous or material(old)!=material(context)
  prior_trailing=state.get('position_trailing');reset_trailing=False;refreshed=False
  if prior_trailing and (material_changed or changed):
   from hotwatch_strategy import position_trailing
   last_sample=c.execute('SELECT payload FROM hw_samples WHERE watch_row_id=? ORDER BY id DESC LIMIT 1',(row['id'],)).fetchone()
   risk=dict(request['risk'],_position_scope=scope)
   candidate,_=position_trailing(dict(json.loads(last_sample['payload']),context=context),risk,state,now,False) if last_sample else (None,None)
   if candidate and candidate.get('basis')==prior_trailing.get('basis') and candidate.get('high')==prior_trailing.get('high') and candidate.get('high_time')==prior_trailing.get('high_time'):
    state['position_trailing']=candidate;refreshed=True
   else:
    state.pop('position_trailing',None);reset_trailing=True
  if current_key is None:state.pop('exit_context_key',None)
  else:state['exit_context_key']=current_key
  if (reset_trailing or changed) and state.get('pending') in ('SELL','REDUCE'):state.update(pending=None,confirmations=0,pending_since=None)
  if refreshed or reset_trailing or prior_key!=current_key:c.execute('UPDATE hw_sessions SET state=? WHERE id=?',(canonical(state),row['id']))
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
  # A locally denied request collected no observation. Retry once the shared
  # minute budget renews instead of treating it as a completed scan and
  # postponing this session for an entire multi-minute polling cycle.
  # The same limiter still charges every actual upstream request.
  if code=='PROVIDER_RATE_BUDGET':interval=61-now.timestamp()%60 if request['provider']=='eodhd' else 60
  # Daily HTTP budget does not prevent a fresh WebSocket trade. Continue
  # checking on the normal sustainable cadence rather than backing off 30 min.
  if code=='EODHD_DAILY_BUDGET':interval=effective_poll_interval(c,request)
  # A stale observation is not a failed provider or rate-limit response.
  # Recheck at the sustainable cadence so repeated closed-market samples do
  # not push the next check half an hour past a new market event. A rejected
  # same-timestamp conflict also needs a new observation, not a 30-minute
  # provider-error backoff; the conflicting observation remains rejected.
  if code in ('DATA_STALE','sample_id_conflict'):
   interval=effective_poll_interval(c,request)
   if code=='DATA_STALE' and not set(state.get('alert_codes',[]))&{'STOP_BREACHED','EXIT_DEADLINE'}:interval=quiet_market_interval(c,request,state.get('adaptive_profile',request['profile']),now,interval)
  # A transient SQLite contention is not a failed market feed. Do not let
  # exponential provider backoff postpone a position or candidate for 30 min.
  if code.startswith('PROCESSING_DATABASE_BUSY_'):interval=60
  if request['provider']=='eodhd' and code in ('EODHD_RATE_LIMIT','PROVIDER_RATE_BUDGET') and retry_after_s is not None:interval=max(1,retry_after_s)
  elif retry_after_s is not None:interval=max(interval,max(0,retry_after_s))
  state['scheduled_interval_s']=interval
  # Only stale-data scheduling uses the quiet-market baseline. Other errors
  # do not need a full shared-session budget lookup while holding the writer.
  baseline=effective_poll_interval(c,request,state.get('adaptive_profile',request['profile'])) if code=='DATA_STALE' else None
  state['quiet_market_poll']=code=='DATA_STALE' and interval>baseline
  state['quiet_baseline_s']=baseline if state['quiet_market_poll'] else None
  if row['last_error']!=code:
   previous=json.loads(row['strategy']);result={'signal':'NO_DATA','reason_codes':[code],'human_readable_explanation':code,'supporting_metrics':{'quote_age_s':(now-stamp(row['last_data'])).total_seconds() if row['last_data'] else None},'calculation_timestamp':now.isoformat(),'data_timestamp':row['last_data'],'strategy_id':previous['strategy_id'],'strategy_version':previous['version'],'strategy_checksum':checksum(previous),'confidence_score':0,'risk_level':'critical' if set(state.get('alert_codes',[]))&{'STOP_BREACHED','EXIT_DEADLINE'} else 'high','rules_score_note':'No valid current market input','critical_override':False}
   c.execute('INSERT INTO hw_calculations(watch_row_id,sample_row_id,calculated,payload,strategy_checksum) VALUES(?,NULL,?,?,?)',(row['id'],now.isoformat(),canonical(result),result['strategy_checksum']))
  state['alert_codes']=sorted(set(state.get('alert_codes',[]))|{code})
  status='ERROR' if code in ['quote_currency_mismatch','sample_identity_mismatch','PLUTO_ASSET_NOT_CONFIRMED','EODHD_RATE_LIMIT_MANUAL_REVIEW'] else 'DEGRADED'
  if status=='ERROR' and row['status']!='ERROR':event(c,row,'WATCH_ERROR',now,'Manual review required: '+code,severity='critical')
  c.execute("UPDATE hw_sessions SET status=?,state=?,last_error=?,failures=?,updated=?,next_due=?,lease_owner=NULL,lease_until=0 WHERE id=?",(status,canonical(state),code,failures,now.isoformat(),now.timestamp()+interval,row['id']))

def claim(connect,now=None,watch_id=None,exclude_ids=()):
 now=now or utc();owner=secrets.token_hex(16);excluded=json.dumps(list(exclude_ids))
 # Avoid competing for the SQLite writer lock when the queue is empty.
 # The complete query and all kill switches are checked again under the
 # transaction below; this read-only preflight cannot claim a session.
 with connect() as c:
  pending=c.execute("SELECT 1 FROM hw_sessions s JOIN users u ON u.id=s.user_id AND u.active=1 LEFT JOIN hw_control k ON k.user_id=s.user_id WHERE s.status IN ('CREATED','VALIDATING','ACTIVE','DEGRADED') AND s.next_due<=? AND s.lease_until<=? AND s.id NOT IN (SELECT value FROM json_each(?)) AND COALESCE(k.killed,0)=0 AND (? IS NULL OR s.watch_id=?) LIMIT 1",(now.timestamp(),now.timestamp(),excluded,watch_id,watch_id)).fetchone()
 if not pending:return None
 with connect() as c:
  c.execute('BEGIN IMMEDIATE')
  if c.execute('SELECT killed FROM hw_system_control WHERE id=1').fetchone()[0]:return None
  concurrency=max(1,min(10,int(os.environ.get('ESCAPE_HW_CONCURRENCY','2'))))
  occupied=c.execute('SELECT count(*) FROM hw_sessions WHERE lease_owner IS NOT NULL AND lease_until>?',(now.timestamp(),)).fetchone()[0]
  if occupied>=concurrency:return None
  # next_due already encodes each watch's urgency and polling profile.
  # Serve the earliest deadline first; exits/catalysts break equal deadlines.
  # Giving newly due holdings absolute priority until candidates missed a
  # whole extra interval systematically delayed NORMAL candidates by 60s.
  row=c.execute("SELECT s.* FROM hw_sessions s JOIN users u ON u.id=s.user_id AND u.active=1 LEFT JOIN hw_control k ON k.user_id=s.user_id WHERE s.status IN ('CREATED','VALIDATING','ACTIVE','DEGRADED') AND s.next_due<=? AND s.lease_until<=? AND s.id NOT IN (SELECT value FROM json_each(?)) AND COALESCE(k.killed,0)=0 AND (? IS NULL OR s.watch_id=?) ORDER BY s.next_due,CASE WHEN json_extract(s.request,'$.watch_mode')='exit' AND json_extract(s.state,'$.adaptive_profile')='CRITICAL' THEN 0 ELSE 1 END,CASE WHEN json_extract(s.request,'$.watch_mode')='exit' THEN 0 ELSE 1 END,CASE WHEN COALESCE(json_extract(s.state,'$.catalyst_priority_until'),0)>? THEN 0 ELSE 1 END,CASE json_extract(s.state,'$.adaptive_profile') WHEN 'CRITICAL' THEN 0 ELSE 1 END,CASE json_extract(s.request,'$.priority') WHEN 'CRITICAL' THEN 0 WHEN 'HIGH' THEN 1 ELSE 2 END,s.created,s.id LIMIT 1",(now.timestamp(),now.timestamp(),excluded,watch_id,watch_id,now.timestamp())).fetchone()
  if not row:return None
  # Provider adapters charge the shared budget immediately before each actual
  # upstream request. Claiming a job is not itself a provider request.
  request=json.loads(row['request'])
  c.execute("UPDATE hw_sessions SET status=CASE WHEN status='CREATED' THEN 'VALIDATING' ELSE status END,lease_owner=?,lease_until=? WHERE id=?",(owner,now.timestamp()+120,row['id']))
  due_count=c.execute("SELECT count(*) FROM hw_sessions WHERE status IN ('CREATED','VALIDATING','ACTIVE','DEGRADED') AND next_due<=? AND lease_until<=?",(now.timestamp(),now.timestamp())).fetchone()[0]
  return dict(row,lease_owner=owner,request_data=request,diagnostic_occupied_workers=occupied+1,diagnostic_due_sessions=due_count)

def release(connect,job,now=None,sample=None,pending_feed=False):
 now=now or utc();request=job['request_data']
 with connect() as c:
  if pending_feed:
   # The runner excludes this job until the shared capture completes. Keep
   # the original deadline and no sleeping lease or extra database wake-up.
   c.execute('UPDATE hw_sessions SET lease_owner=NULL,lease_until=0 WHERE id=? AND lease_owner=?',(job['id'],job['lease_owner']))
   return
  profile=json.loads(job.get('state') or '{}').get('adaptive_profile') or request['profile']
  baseline=effective_poll_interval(c,request,profile)
  interval=observation_poll_interval(c,request,profile,now,sample,baseline=baseline)
  reduced=interval>baseline
  c.execute("UPDATE hw_sessions SET next_due=?,state=json_set(state,'$.scheduled_interval_s',?,'$.quiet_market_poll',json(?),'$.quiet_baseline_s',?),lease_owner=NULL,lease_until=0 WHERE id=? AND lease_owner=?",(now.timestamp()+interval,interval,'true' if reduced else 'false',baseline if reduced else None,job['id'],job['lease_owner']))


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
