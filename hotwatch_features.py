"""Deterministic causal features. No providers, DB, interpolation or AI."""
from decimal import Decimal,localcontext

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
 last=samples[-1];identity=lambda s:tuple(s[k] for k in ['source','asset_id','currency','venue','session_key','market_status','interval_s'])
 rows=[]
 for s in reversed(samples):
  if identity(s)!=identity(last):break
  if rows:
   from report_validation import stamp
   gap=(stamp(rows[-1]['event_time'])-stamp(s['event_time'])).total_seconds()
   if gap>last['interval_s']*1.5 or gap<last['interval_s']*0.5:break
  rows.append(s)
 rows.reverse();prices=[number(r['price']) for r in rows]
 if any(p is None or p<=0 for p in prices):return {'sample_count':len(rows)}
 with localcontext() as ctx:
  ctx.prec=40
  p=prices[-1];f={'sample_count':len(rows),'price':p,'quote_age_s':None}
  returns=[(b/a-1)*100 for a,b in zip(prices,prices[1:])]
  for n in [1,3,5,10]:f['return_'+str(n)+'_pct']=(p/prices[-n-1]-1)*100 if len(prices)>n else None
  from report_validation import stamp
  times=[stamp(r['event_time']).timestamp() for r in rows]
  speeds=[r/Decimal(str(b-a)) for r,a,b in zip(returns,times,times[1:]) if b>a]
  f['velocity_pct_s']=speeds[-1] if speeds else None;f['acceleration_pct_s2']=(speeds[-1]-speeds[-2])/Decimal(str(times[-1]-times[-2])) if len(speeds)>=2 else None
  short=int(parameters['short_period']);long=int(parameters['long_period'])
  f['sma_short']=average(prices[-short:]) if len(prices)>=short else None;f['sma_long']=average(prices[-long:]) if len(prices)>=long else None
  f['ema_short']=ema(prices,short);f['ema_long']=ema(prices,long)
  f['trend_up']=f['ema_short'] is not None and f['ema_long'] is not None and p>f['ema_short']>f['ema_long']
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
  f['breakout']=len(prior)==window and p>max(prior);f['breakdown']=len(prior)==window and p<min(prior)
  f['range_position_pct']=(p-min(prices))/(max(prices)-min(prices))*100 if max(prices)>min(prices) else None
  f['distance_high_pct']=(p/max(prices)-1)*100;f['distance_low_pct']=(p/min(prices)-1)*100
  f['volatility_pct']=average([(r-average(returns))**2 for r in returns]).sqrt() if len(returns)>=2 else None
  ranges=[]
  for i,r in enumerate(rows):
   if r['high'] is None or r['low'] is None or r['close'] is None:continue
   high,low=number(r['high']),number(r['low']);prev=number(rows[i-1]['close']) if i else None
   if i and prev is None:continue
   ranges.append(max([high-low]+([abs(high-prev),abs(low-prev)] if prev is not None else [])))
  atr=int(parameters['atr_period']);f['atr']=average(ranges[-atr:]) if len(ranges)>=atr and len(ranges)==len(rows) else None
  bid,ask=number(last['bid']),number(last['ask']);f['spread']=ask-bid if bid is not None and ask is not None and ask>=bid else None
  f['spread_pct']=f['spread']/((ask+bid)/2)*100 if f['spread'] is not None and ask+bid>0 else None
  volumes=[]
  for i,r in enumerate(rows):
   v=number(r['volume'])
   if r['volume_type']=='interval':volumes.append(v)
   elif r['volume_type']=='cumulative' and i and r['volume_type']==rows[i-1]['volume_type'] and v is not None and rows[i-1]['volume'] is not None:
    d=v-number(rows[i-1]['volume']);volumes.append(d if d>=0 else None)
   else:volumes.append(None)
  f['interval_volume']=volumes[-1]
  baseline=[v for v in volumes[-window-1:-1] if v is not None]
  f['relative_volume']=volumes[-1]/average(baseline) if volumes[-1] is not None and len(baseline)==window and average(baseline)>0 else None
  f['volume_acceleration']=volumes[-1]-2*volumes[-2]+volumes[-3] if len(volumes)>=3 and all(v is not None for v in volumes[-3:]) else None
  f['rising_price_falling_volume']=bool(returns and returns[-1]>0 and len(volumes)>1 and volumes[-1] is not None and volumes[-2] is not None and volumes[-1]<volumes[-2])
  return {k:format(v,'f') if isinstance(v,Decimal) else v for k,v in f.items()}
