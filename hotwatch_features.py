"""Deterministic causal features. No providers, DB, interpolation or AI."""
from decimal import Decimal,localcontext
from datetime import datetime,timedelta,time as day_time
from zoneinfo import ZoneInfo,ZoneInfoNotFoundError

def verified_bar_samples(sample,request,now):
 """Validate actual closed bars against explicit source/session evidence."""
 from report_validation import stamp
 bars=sample.get('bar_history');e=sample.get('bar_evidence')
 if not isinstance(bars,list) or not bars or len(bars)>120 or not isinstance(e,dict):return None
 try:
  symbol=request['provider_symbol'];market='us' if symbol.endswith('.US') else 'eu'
  phase=sample['market_status']
  if sample['source']!='eodhd' or sample.get('price_time_kind')!='trade' or phase not in ('REGULAR','PRE','AFTER') or e['exchange_open'] is not (phase=='REGULAR') or e['feed']!='eodhd_realtime_history' or e['provider_symbol']!=symbol or e['market']!=market or e['exchange']!=symbol.rsplit('.',1)[1]:return None
  if phase in ('PRE','AFTER') and (sample.get('status_feed')!=market+'_trades' or not sample.get('status_at') or stamp(sample['status_at'])!=stamp(sample['event_time'])):return None
  trade_at=stamp(sample['event_time']);received=stamp(e['schedule_received_at'])
  if not 0<=(now-received).total_seconds()<=request['risk']['max_quote_age_s']:return None
  zone=ZoneInfo(e['timezone']);local=trade_at.astimezone(zone);date=local.date();opening=day_time.fromisoformat(e['open']);closing=day_time.fromisoformat(e['close'])
  if received.astimezone(zone).date()!=date:return None
  if opening.tzinfo or closing.tzinfo or opening>=closing or e['session_date']!=date.isoformat() or date.isoformat() in e['excluded_dates'] or ('Mon','Tue','Wed','Thu','Fri','Sat','Sun')[date.weekday()] not in e['working_days']:return None
  in_phase=lambda t:(opening<=t<closing) if phase=='REGULAR' else (t<opening if phase=='PRE' else t>=closing)
  if not in_phase(local.time()):return None
  output=[];previous=None
  for bar in bars:
   at=stamp(bar['bar_open_at']);end=at+timedelta(seconds=60);start_local=at.astimezone(zone);end_local=end.astimezone(zone)
   if previous is not None and at<=previous:return None
   if start_local.date()!=date or end_local.date()!=date or not in_phase(start_local.time()) or not in_phase((end-timedelta(microseconds=1)).astimezone(zone).time()) or end>trade_at:return None
   values=[number(bar[k]) for k in ('open','high','low','close')]
   if any(v is None or v<=0 for v in values) or values[1]<max(values[0],values[3]) or values[2]>min(values[0],values[3]) or values[2]>values[1] or (bar['volume'] is not None and number(bar['volume'])<0):return None
   output.append({**sample,'bar_history':None,'bar_evidence':None,'event_time':bar['bar_open_at'],'interval_s':60,'feed_type':'EODHD verified real-time closed 1m bars','price_time_kind':'bar_open','price':bar['close'],'open':bar['open'],'high':bar['high'],'low':bar['low'],'close':bar['close'],'volume':bar['volume'],'volume_type':'interval','bid':None,'ask':None})
   previous=at
  if not output:return None
  bar_end=stamp(output[-1]['event_time'])+timedelta(seconds=60)
  if not 0<=(trade_at-bar_end).total_seconds()<=request['risk']['max_quote_age_s'] or not 0<=(now-bar_end).total_seconds()<=request['risk']['max_quote_age_s']:return None
  return output
 except (KeyError,ValueError,TypeError,ArithmeticError,ZoneInfoNotFoundError):return None

def observation_status(samples,now,max_age_s,signal,watch_status):
 """Read-only data quality and time-horizon changes; never a trading input."""
 from report_validation import stamp
 result={'price_status':'MISSING','market_status':'UNKNOWN','last_market_status':'UNKNOWN','market_status_at':None,'momentum_status':'UNAVAILABLE','quote_status':'UNAVAILABLE','signal_status':'WAITING_FOR_DATA','price':None,'currency':None,'source':None,'venue':None,'price_type':None,'feed_description':None,'event_time':None,'age_s':None,'bid':None,'ask':None,'bid_at':None,'ask_at':None,'daily_change_pct':None,'since_last_pct':None,'momentum_pct':{str(n):None for n in (1,5,15,30)}}
 if watch_status in ('PAUSED','COMPLETED','EXPIRED','ERROR'):result['signal_status']='NOT_APPLICABLE'
 elif signal=='PAUSE':result['signal_status']='BLOCKED'
 elif signal!='NO_DATA':result['signal_status']='READY'
 if not samples:return result
 latest=samples[-1];event=stamp(latest['event_time']);age=(now-event).total_seconds()
 result.update(price=latest['price'],currency=latest['currency'],source=latest['source'],venue=latest['venue'],price_type={'bar_open':'bar_close','trade':'trade','snapshot':'snapshot'}.get(latest.get('price_time_kind')),feed_description=latest['feed_type'],event_time=latest['event_time'],age_s=round(age,3),identity_verification=latest.get('verification','unknown'))
 if latest.get('bid') is not None and latest.get('ask') is not None and latest.get('bid_at') and latest.get('ask_at'):
  result.update(bid=latest['bid'],ask=latest['ask'],bid_at=latest['bid_at'],ask_at=latest['ask_at'])
  result['quote_status']='FRESH' if all(0<=(now-stamp(latest[k])).total_seconds()<=max_age_s for k in ('bid_at','ask_at')) else 'STALE'
 phase={'REGULAR':'OPEN','PRE':'PREMARKET','AFTER':'AFTERHOURS','CLOSED':'CLOSED','HALTED':'HALTED'}.get(latest['market_status'],'UNKNOWN')
 status_at=latest.get('status_at') or (latest['event_time'] if latest['source']!='eodhd' else None)
 result.update(last_market_status=phase,market_status_at=status_at)
 if status_at and 0<=(now-stamp(status_at)).total_seconds()<=max_age_s:result['market_status']=phase
 if latest['price'] is None:return result
 if latest.get('previous_close') is not None and number(latest['previous_close'])>0:result['daily_change_pct']=format((number(latest['price'])/number(latest['previous_close'])-1)*100,'f')
 delay=latest.get('documented_delay_s')
 if age<0:result['price_status']='MISSING'
 elif delay and age<=delay+max_age_s:result['price_status']='DELAYED'
 elif age>max_age_s:result['price_status']='STALE'
 else:result['price_status']='FRESH'
 if latest.get('verification')!='verified':result['price_status']='UNVERIFIED'
 if latest['market_status']=='UNKNOWN':return result
 identity=lambda s:tuple(s[k] for k in ('source','asset_id','currency','venue','session_key','market_status','feed_type'))+(s.get('price_time_kind'),s.get('verification','unknown'))
 comparable=[s for s in samples[:-1] if identity(s)==identity(latest) and s.get('price') is not None and stamp(s['event_time'])<event]
 if comparable:
  prior=max(comparable,key=lambda s:stamp(s['event_time']))
  if number(prior['price'])>0:result['since_last_pct']=format((number(latest['price'])/number(prior['price'])-1)*100,'f')
 history=latest.get('bar_history')
 if isinstance(history,list) and history:
  last_bar=history[-1];last_time=stamp(last_bar['bar_open_at']);last_price=number(last_bar['close'])
  for minutes in (1,5,15,30):
   choices=[b for b in history[:-1] if (last_time-stamp(b['bar_open_at'])).total_seconds()==minutes*60]
   if choices and number(choices[-1]['close'])>0:result['momentum_pct'][str(minutes)]=format((last_price/number(choices[-1]['close'])-1)*100,'f')
  bar_age=(now-(last_time+timedelta(seconds=60))).total_seconds()
  result['momentum_status']='STALE' if result['price_status']!='FRESH' or not 0<=bar_age<=max_age_s else 'READY' if any(v is not None for v in result['momentum_pct'].values()) else 'INSUFFICIENT_HISTORY'
  return result
 if not comparable:result['momentum_status']='INSUFFICIENT_HISTORY';return result
 for minutes in (1,5,15,30):
  target=minutes*60
  choices=[s for s in comparable if abs((event-stamp(s['event_time'])).total_seconds()-target)<=5]
  if choices:
   previous=min(choices,key=lambda s:abs((event-stamp(s['event_time'])).total_seconds()-target))
   before=number(previous['price']);after=number(latest['price'])
   if before is not None and before>0:result['momentum_pct'][str(minutes)]=format((after/before-1)*100,'f')
 result['momentum_status']='STALE' if result['price_status']!='FRESH' else 'READY' if any(v is not None for v in result['momentum_pct'].values()) else 'INSUFFICIENT_HISTORY'
 return result

def number(v):return Decimal(v) if v is not None else None
def average(values):return sum(values)/len(values) if values else None
def ema(values,period):
 if len(values)<period:return None
 value=average(values[:period]);alpha=Decimal(2)/(period+1)
 for x in values[period:]:value=alpha*x+(1-alpha)*value
 return value

def features(samples,parameters):
 if not samples:return {}
 # Caller supplies ascending, unique event times. Do not mix providers,
 # currencies, venues, sessions, bar durations or market phases.
 last=samples[-1];live=last.get('source')=='eodhd' and last.get('price_time_kind')=='trade'
 # Poll cadence is not a candle duration. Use actual observations approximately
 # one minute apart; extra fast polls do not reset the analysis window.
 interval=60 if live else last['interval_s']
 identity=lambda s:tuple(s[k] for k in ['source','asset_id','currency','venue','session_key','market_status','feed_type'])+(() if live else (s['interval_s'],))+(s.get('price_time_kind'),s.get('verification','unknown'))
 # Period indicators use actual observations. A missing minute does not
 # erase the earlier evidence; time-based features below check their own
 # timestamps. Provider, instrument and session boundaries still reset.
 sparse_bars=last.get('verification')=='verified' and last.get('price_time_kind')=='bar_open' and last.get('feed_type')=='EODHD verified real-time closed 1m bars'
 rows=[]
 for s in reversed(samples):
  if identity(s)!=identity(last):break
  if rows:
   from report_validation import stamp
   gap=(stamp(rows[-1]['event_time'])-stamp(s['event_time'])).total_seconds()
   if gap<=0:break
  rows.append(s)
 rows.reverse();prices=[number(r['price']) for r in rows]
 if any(p is None or p<=0 for p in prices):return {'sample_count':len(rows)}
 with localcontext() as ctx:
  ctx.prec=40
  p=prices[-1];f={'sample_count':len(rows),'price':p,'quote_age_s':None}
  returns=[(b/a-1)*100 for a,b in zip(prices,prices[1:])]
  from report_validation import stamp
  times=[stamp(r['event_time']).timestamp() for r in rows]
  for n in [1,3,5,10]:
   # A return over N minutes needs the observed price at that time. N sparse
   # bars can span much longer; never relabel that return as N minutes.
   candidates=[i for i in range(len(times)-1) if abs(times[-1]-times[i]-n*60)<=(0 if sparse_bars else 5)]
   index=min(candidates,key=lambda i:abs(times[-1]-times[i]-n*60)) if candidates else None
   f['return_'+str(n)+'_pct']=(p/prices[index]-1)*100 if index is not None else None
  window_seconds=int(parameters.get('momentum_window_minutes',3))*60
  previous_window=[i for i in range(len(times)-1) if abs((times[-1]-times[i])-window_seconds)<=5]
  best_window=min(previous_window,key=lambda i:abs((times[-1]-times[i])-window_seconds)) if previous_window else None
  f['return_window_pct']=(p/prices[best_window]-1)*100 if best_window is not None else None
  speeds=[r/Decimal(str(b-a)) for r,a,b in zip(returns,times,times[1:]) if b>a]
  f['velocity_pct_s']=speeds[-1] if speeds else None;f['acceleration_pct_s2']=(speeds[-1]-speeds[-2])/Decimal(str(times[-1]-times[-2])) if len(speeds)>=2 else None
  recent_minutes=len(times)>=3 and all(0<times[i]-times[i-1]<=interval*1.5 for i in (-1,-2))
  if sparse_bars:recent_minutes=recent_minutes and all(times[i]-times[i-1]==interval for i in (-1,-2))
  if not recent_minutes:f['acceleration_pct_s2']=None
  if sparse_bars:
   # Missing adjacent minutes cannot establish the one-minute velocity or
   # acceleration used by the existing entry and price-gap safeguards.
   if len(times)<2 or times[-1]-times[-2]!=interval:f['velocity_pct_s']=None
   if not recent_minutes:f['acceleration_pct_s2']=None
  short=int(parameters['short_period']);long=int(parameters['long_period'])
  f['sma_short']=average(prices[-short:]) if len(prices)>=short else None;f['sma_long']=average(prices[-long:]) if len(prices)>=long else None
  f['ema_short']=ema(prices,short);f['ema_long']=ema(prices,long)
  f['trend_up']=p>f['ema_short']>f['ema_long'] if f['ema_short'] is not None and f['ema_long'] is not None else None
  rsi=int(parameters['rsi_period']);changes=[b-a for a,b in zip(prices,prices[1:])]
  if len(changes)>=rsi:
   gains=average([max(x,Decimal(0)) for x in changes[:rsi]]);losses=average([max(-x,Decimal(0)) for x in changes[:rsi]])
   for change in changes[rsi:]:gains=(gains*(rsi-1)+max(change,Decimal(0)))/rsi;losses=(losses*(rsi-1)+max(-change,Decimal(0)))/rsi
   f['rsi']=Decimal(50) if gains==losses==0 else Decimal(100) if losses==0 else 100-100/(1+gains/losses)
  else:f['rsi']=None
  macd=[]
  for n in range(26,len(prices)+1):macd.append(ema(prices[:n],12)-ema(prices[:n],26))
  f['macd']=macd[-1] if macd else None;f['macd_signal']=ema(macd,9);f['macd_histogram']=f['macd']-f['macd_signal'] if f['macd_signal'] is not None else None
  window=int(parameters['breakout_window']);prior=prices[-window-1:-1]
  f['breakout']=p>max(prior) if len(prior)==window else None;f['breakdown']=p<min(prior) if len(prior)==window else None
  f['range_position_pct']=(p-min(prices))/(max(prices)-min(prices))*100 if max(prices)>min(prices) else None
  f['distance_high_pct']=(p/max(prices)-1)*100;f['distance_low_pct']=(p/min(prices)-1)*100
  f['volatility_pct']=average([(r-average(returns))**2 for r in returns]).sqrt() if len(returns)>=2 else None
  ranges=[]
  for i,r in enumerate(rows):
   if r['high'] is None or r['low'] is None or r['close'] is None:ranges.append(None);continue
   high,low=number(r['high']),number(r['low']);prev=number(rows[i-1]['close']) if i else None
   if i and prev is None:ranges.append(None);continue
   ranges.append(max([high-low]+([abs(high-prev),abs(low-prev)] if prev is not None else [])))
  atr=int(parameters['atr_period']);f['atr']=average(ranges[-atr:]) if len(ranges)>=atr and all(v is not None for v in ranges[-atr:]) else None
  bid,ask=number(last['bid']),number(last['ask']);f['spread']=ask-bid if bid is not None and ask is not None and ask>=bid else None
  f['spread_pct']=f['spread']/((ask+bid)/2)*100 if f['spread'] is not None and ask+bid>0 else None
  volumes=[]
  for i,r in enumerate(rows):
   v=number(r['volume'])
   if r['volume_type']=='interval':volumes.append(v)
   elif r['volume_type']=='cumulative' and i and r['volume_type']==rows[i-1]['volume_type'] and v is not None and rows[i-1]['volume'] is not None:
    d=v-number(rows[i-1]['volume']);volumes.append(d if d>=0 and interval*0.5<=times[i]-times[i-1]<=interval*1.5 else None)
   else:volumes.append(None)
  f['interval_volume']=volumes[-1]
  baseline=[v for v in volumes[-window-1:-1] if v is not None]
  f['relative_volume']=volumes[-1]/average(baseline) if volumes[-1] is not None and len(baseline)==window and average(baseline)>0 else None
  f['volume_acceleration']=volumes[-1]-2*volumes[-2]+volumes[-3] if recent_minutes and len(volumes)>=3 and all(v is not None for v in volumes[-3:]) else None
  f['rising_price_falling_volume']=returns[-1]>0 and volumes[-1]<volumes[-2] if returns and len(volumes)>1 and volumes[-1] is not None and volumes[-2] is not None else None
  return {k:format(v,'f') if isinstance(v,Decimal) else v for k,v in f.items()}
