"""Actual EODHD minute history for analysis only; never creates signals/orders."""
from eodhd_capacity import Capacity
import json, os
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from hotwatch_contract import stamp

def init(c):
 c.execute('CREATE TABLE IF NOT EXISTS hw_warmup_history(watch_row_id INTEGER PRIMARY KEY REFERENCES hw_sessions(id),symbol TEXT NOT NULL,received TEXT NOT NULL,bars TEXT NOT NULL,next_attempt REAL NOT NULL,status TEXT NOT NULL)')

def valid_bars(rows,now):
 """Keep only the most recent contiguous run of distinct, closed 1m bars."""
 from hotwatch_features import number
 if not isinstance(rows,list):return []
 by_time={}
 try:
  for bar in rows:
   if not isinstance(bar,dict):return []
   if any(isinstance(bar.get(k),bool) for k in ('open','high','low','close','volume')):continue
   at=stamp(bar['bar_open_at']);values=[number(bar[k]) for k in ('open','high','low','close')];volume=number(bar.get('volume'))
   if at.second or at.microsecond or any(v is None or not v.is_finite() or v<=0 for v in values) or values[1]<max(values[0],values[3]) or values[2]>min(values[0],values[3]) or values[2]>values[1] or volume is None or not volume.is_finite() or volume<0:continue
   if at+timedelta(minutes=1)>now:continue
   cleaned={k:bar.get(k) for k in ('bar_open_at','open','high','low','close','volume')}
   if at in by_time and by_time[at]!=cleaned:return []
   by_time[at]=cleaned
  ordered=sorted(by_time);tail=[];later=None
  for at in reversed(ordered):
   if later and (later-at).total_seconds()!=60:break
   tail.append(by_time[at]);later=at
   if len(tail)==34:break
  return list(reversed(tail))
 except (KeyError,ValueError,TypeError,ArithmeticError,InvalidOperation):return []

def refresh(connect,job,now,client=None):
 """Read at most one intraday response; never mutate a session or its journal."""
 from instrument_resolver import PEPE_PLUTO_ASSET_ID,BTC_PLUTO_ASSET_ID
 from hotwatch_engine import valid_cxe_evidence
 from eodhd_feeds import EODHDFeeds
 req=job['request_data'];symbol=req.get('provider_symbol')
 if job['is_test'] or req.get('provider')!='eodhd' or not symbol or req.get('asset_id')==PEPE_PLUTO_ASSET_ID:return None
 with connect() as c:
  cached=c.execute('SELECT next_attempt,symbol FROM hw_warmup_history WHERE watch_row_id=?',(job['id'],)).fetchone()
  if cached and cached['symbol']==symbol and cached['next_attempt']>now.timestamp():return None
  row=c.execute("SELECT * FROM hw_sessions WHERE id=? AND user_id=? AND status IN ('CREATED','VALIDATING','ACTIVE','DEGRADED')",(job['id'],job['user_id'])).fetchone()
  if not row or json.loads(row['request'])!=req:return None
  if c.execute('SELECT killed FROM hw_system_control WHERE id=1').fetchone()[0]:return None
  killed=c.execute('SELECT killed FROM hw_control WHERE user_id=?',(job['user_id'],)).fetchone()
  if killed and killed['killed']:return None
  link=c.execute('SELECT * FROM hw_verified_feed_links WHERE user_id=? AND asset_id=?',(job['user_id'],req['asset_id'])).fetchone()
  proof=valid_cxe_evidence(c,job['user_id'],req,now)
  if not link or link['symbol']!=symbol or link['currency']!=req['quote_currency'] or str(link['ticker']).casefold()!=str(req.get('ticker','')).casefold() or str(link['exchange']).casefold()!=str(req.get('exchange','')).casefold() or not 0<=now.timestamp()-link['verified_epoch']<=7*86400 or proof is False or req.get('asset_id')==BTC_PLUTO_ASSET_ID and proof is not True:return None
 feed=client or EODHDFeeds(os.environ.get('ESCAPE_EODHD_API_KEY',''),capacity=Capacity(connect))
 lookback=7200 if symbol.upper().endswith('.CC') else 7*86400
 try:response=feed.intraday(symbol,interval='1m',start=int(now.timestamp())-lookback,end=int(now.timestamp()))
 except Exception:response={'status':'UNAVAILABLE'}
 status=response.get('status','UNAVAILABLE') if isinstance(response,dict) else 'UNAVAILABLE'
 source_bars=response.get('bars') if status=='OK' else None
 bars=valid_bars(source_bars,now) if isinstance(source_bars,list) and all(isinstance(x,dict) and x.get('symbol') in (None,symbol) for x in source_bars) else []
 if status=='OK' and not bars:status='NO_VALID_BARS'
 with connect() as c:
  c.execute('BEGIN IMMEDIATE')
  row=c.execute("SELECT request FROM hw_sessions WHERE id=? AND user_id=? AND status IN ('CREATED','VALIDATING','ACTIVE','DEGRADED')",(job['id'],job['user_id'])).fetchone()
  if not row or json.loads(row['request'])!=req:return None
  if c.execute('SELECT killed FROM hw_system_control WHERE id=1').fetchone()[0]:return None
  killed=c.execute('SELECT killed FROM hw_control WHERE user_id=?',(job['user_id'],)).fetchone()
  if killed and killed['killed']:return None
  current_link=c.execute('SELECT * FROM hw_verified_feed_links WHERE user_id=? AND asset_id=?',(job['user_id'],req['asset_id'])).fetchone()
  current_proof=valid_cxe_evidence(c,job['user_id'],req,now)
  if not current_link or any(current_link[k]!=link[k] for k in ('symbol','currency','ticker','exchange','isin','verified_epoch')) or current_proof is False or req.get('asset_id')==BTC_PLUTO_ASSET_ID and current_proof is not True:return None
  # Failed refreshes retain usable earlier bars; retries remain bounded.
  old=c.execute('SELECT symbol,bars FROM hw_warmup_history WHERE watch_row_id=?',(job['id'],)).fetchone()
  if not bars and old and old['symbol']==symbol:bars=json.loads(old['bars'])
  c.execute('INSERT INTO hw_warmup_history VALUES(?,?,?,?,?,?) ON CONFLICT(watch_row_id) DO UPDATE SET symbol=excluded.symbol,received=excluded.received,bars=excluded.bars,next_attempt=excluded.next_attempt,status=excluded.status',(job['id'],symbol,now.isoformat(),json.dumps(bars),now.timestamp()+300,status))
 return status

def status(c,row,request,now):
 """Count real closed bars and subsequent live observations by minute."""
 if request.get('provider')!='eodhd':return None
 from hotwatch_engine import valid_cxe_evidence
 from instrument_resolver import BTC_PLUTO_ASSET_ID,PEPE_PLUTO_ASSET_ID
 if request.get('asset_id')==PEPE_PLUTO_ASSET_ID:return None
 link=c.execute('SELECT * FROM hw_verified_feed_links WHERE user_id=? AND asset_id=?',(row['user_id'],request.get('asset_id'))).fetchone()
 proof=valid_cxe_evidence(c,row['user_id'],request,now)
 if not link or link['symbol']!=request.get('provider_symbol') or link['currency']!=request.get('quote_currency') or str(link['ticker']).casefold()!=str(request.get('ticker','')).casefold() or str(link['exchange']).casefold()!=str(request.get('exchange','')).casefold() or not 0<=now.timestamp()-link['verified_epoch']<=7*86400 or proof is False or request.get('asset_id')==BTC_PLUTO_ASSET_ID and proof is not True:return None
 saved=c.execute('SELECT * FROM hw_warmup_history WHERE watch_row_id=? AND symbol=?',(row['id'],request.get('provider_symbol'))).fetchone()
 if not saved:return None
 try:
  from hotwatch_features import features
  bars=valid_bars(json.loads(saved['bars']),now);minutes={};latest=None
  parameters=json.loads(row['strategy'])['parameters'];required=parameters['min_samples']
  common={'source':'eodhd','asset_id':request['asset_id'],'currency':request['quote_currency'],'venue':'EODHD:'+request['provider_symbol'].rsplit('.',1)[-1],'session_key':'analysis','market_status':'UNKNOWN','interval_s':60,'feed_type':'EODHD historical warmup analysis','price_time_kind':None,'verification':'verified','bid':None,'ask':None}
  for bar in bars:
   at=stamp(bar['bar_open_at']);latest=at+timedelta(minutes=1)
   minutes[int(at.timestamp()//60)]={**common,'event_time':latest.isoformat(),'price':bar['close'],'open':bar['open'],'high':bar['high'],'low':bar['low'],'close':bar['close'],'volume':bar['volume'],'volume_type':'interval'}
  historical_end=latest
  for item in c.execute("SELECT payload,received FROM hw_samples WHERE watch_row_id=? AND source='eodhd' ORDER BY event_epoch DESC LIMIT 120",(row['id'],)):
   sample=json.loads(item['payload']);at=stamp(sample['event_time'])
   if sample.get('verification')!='verified' or sample.get('asset_id')!=request.get('asset_id') or sample.get('currency')!=request.get('quote_currency') or stamp(item['received']).timestamp()<link['verified_epoch'] or at>now or not sample.get('price') or Decimal(sample['price'])<=0:continue
   if latest is None or at>latest:latest=at
   if historical_end and (at-historical_end).total_seconds()<30:continue
   slot=int(at.timestamp()//60)-(1 if at.second==0 and at.microsecond==0 else 0)
   minutes.setdefault(slot,{**common,'sample_id':sample.get('sample_id'),'event_time':at.isoformat(),'price':sample['price'],'open':sample.get('open'),'high':sample.get('high'),'low':sample.get('low'),'close':sample.get('close'),'volume':sample.get('volume') if sample.get('volume_type')=='interval' else None,'volume_type':sample.get('volume_type') if sample.get('volume_type')=='interval' else 'unknown','bid':sample.get('bid'),'ask':sample.get('ask')})
  slots=sorted(minutes,reverse=True);selected=[];previous=None
  for slot in slots:
   if previous is not None and previous-slot!=1:break
   selected.append(minutes[slot]);previous=slot
   if len(selected)>=max(34,required):break
  metrics=features(list(reversed(selected)),parameters);count=metrics.get('sample_count',0)
  age=(now-latest).total_seconds() if latest else None
  return {'state':'WARMUP COMPLETE' if count>=required else 'WARMUP','count':count,'required':required,'remaining':max(0,required-count),'freshness':'FRESH' if age is not None and 0<=age<=request['risk']['max_quote_age_s'] else 'DATA STALE','first_observed':selected[-1]['event_time'] if selected else None,'last_observed':latest.isoformat() if latest else None,'latest_live_sample_id':selected[0].get('sample_id') if selected else None,'historical_count':len(bars),'source_status':saved['status'],'analysis_only':True,'metrics':metrics}
 except (KeyError,ValueError,TypeError,ArithmeticError,InvalidOperation):return None

def signal_session_verified(c,request,sample,history,now):
 """Require current provider schedule and a single regular equity session."""
 from datetime import datetime
 from zoneinfo import ZoneInfo
 try:
  if sample['market_status']!='REGULAR' or request['provider_symbol'].endswith('.CC'):return False
  exchange=request['provider_symbol'].rsplit('.',1)[1].upper()
  row=c.execute('SELECT received,timezone,calendar FROM hw_exchange_calendar WHERE exchange=?',(exchange,)).fetchone()
  if not row:return False
  received=stamp(row['received']);zone=ZoneInfo(row['timezone']);schedule=json.loads(row['calendar']);current=stamp(sample['event_time']).astimezone(zone);first=(stamp(history['first_observed'])-timedelta(minutes=1)).astimezone(zone)
  if not 0<=(now-received).total_seconds()<=request['risk']['max_quote_age_s'] or received.astimezone(zone).date()!=current.date() or first.date()!=current.date():return False
  if current.date().isoformat() in schedule['excluded_dates'] or current.strftime('%a') not in schedule['working_days']:return False
  opening=datetime.strptime(schedule['open'],'%H:%M:%S').time();closing=datetime.strptime(schedule['close'],'%H:%M:%S').time()
  return opening<closing and opening<=first.time() and current.time()<closing
 except (KeyError,ValueError,TypeError,ArithmeticError):return False
