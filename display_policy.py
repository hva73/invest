"""Read-only display rules. Never infer trades, market sessions or price references."""
from datetime import datetime,timezone
from decimal import Decimal,InvalidOperation

LIMITS={'live_quote':60,'snapshot':300,'analysis':86400}
TERMINAL={'CLOSED','ARCHIVED'}
SESSION_GROUPS={'CREATED':'starting','VALIDATING':'starting','ACTIVE':'active','PAUSED':'paused','DEGRADED':'warning','ERROR':'critical','EXPIRED':'history','COMPLETED':'history'}
ORDER_GROUPS={'PROPOSED':'proposal','AWAITING_APPROVAL':'approval','SUBMITTED':'active','ACCEPTED':'uncertain','PARTIALLY_FILLED':'active','UNKNOWN':'uncertain','FILLED':'recent','CANCELLED':'recent','REJECTED':'recent','EXPIRED':'history'}

def stamp(value):
 try:
  dt=datetime.fromisoformat(value.replace('Z','+00:00'))
  return dt.astimezone(timezone.utc) if dt.tzinfo else None
 except (ValueError,TypeError,AttributeError):return None

def decimal(value):
 try:
  if isinstance(value,bool) or value is None:return None
  n=Decimal(str(value));return n if n.is_finite() and abs(n)<=Decimal('1e30') else None
 except (InvalidOperation,ValueError,TypeError):return None

def market_session(at,venue=None,calendar=None,asset_class=None):
 """Calendar entries contain actual UTC open/close times; absent dates stay UNKNOWN."""
 if asset_class=='verified_crypto_24x7':return {'status':'OPEN','verified':True,'basis':'documented_24x7'}
 if not calendar or calendar.get('venue')!=venue or not calendar.get('verified'):return {'status':'UNKNOWN','verified':False}
 for row in calendar.get('sessions',[]):
  opened=stamp(row.get('open'));closed=stamp(row.get('close'))
  if opened and closed and opened<=at<closed:return {'status':'OPEN','verified':True,'session_key':row.get('id'),'close':row['close']}
 # Explicit coverage bounds are required: missing dates do not mean a holiday.
 lower=stamp(calendar.get('coverage_from'));upper=stamp(calendar.get('coverage_to'))
 if lower and upper and lower<=at<=upper:
  previous=[r for r in calendar.get('sessions',[]) if stamp(r.get('close')) and stamp(r['close'])<=at]
  last=max(previous,key=lambda r:stamp(r['close'])) if previous else None
  return {'status':'CLOSED','verified':True,'last_session_close':last['close'] if last else None,'session_key':last.get('id') if last else None}
 return {'status':'UNKNOWN','verified':False}

def freshness(kind,event_time,now=None,market=None,failed=False,session_key=None):
 now=now or datetime.now(timezone.utc);at=stamp(event_time);limit=LIMITS[kind]
 if not at:return {'state':'error' if failed else 'unknown','reason':'SOURCE_ERROR' if failed else 'NOT_PROVIDED','event_time':event_time,'age_s':None,'limit_s':limit}
 age=(now-at).total_seconds()
 if age<0:return {'state':'unknown','reason':'FUTURE_TIMESTAMP','event_time':event_time,'age_s':None,'limit_s':limit}
 if failed:return {'state':'error','reason':'SOURCE_ERROR','event_time':event_time,'age_s':age,'limit_s':limit}
 closed=market and market.get('verified') and market.get('status')=='CLOSED'
 reference=stamp(market.get('last_session_close')) if closed else None
 relevant=closed and reference and session_key and session_key==market.get('session_key') and reference>=at and (reference-at).total_seconds()<=limit
 state='session_close' if kind!='analysis' and relevant else 'stale' if age>limit else 'fresh'
 return {'state':state,'reason':'STALE' if state=='stale' else None,'event_time':event_time,'age_s':age,'limit_s':limit,'market_status':market.get('status','UNKNOWN') if market else 'UNKNOWN'}

def comparison(current,previous):
 keys=['asset_id','source','feed_type','venue','currency','market_phase','session_key','price_type','adjustment_basis']
 if any(not current.get(k) or current.get(k)!=previous.get(k) for k in keys):return None
 a=stamp(current.get('event_time'));b=stamp(previous.get('event_time'));x=decimal(current.get('price'));y=decimal(previous.get('price'))
 if not a or not b or a<=b or x is None or y is None or x<=0 or y<=0:return None
 return {'percent':str((x-y)/y*100),'amount':str(x-y),'currency':current['currency'],'from':previous['event_time'],'to':current['event_time'],'basis':'comparable_observations'}

def daily_change(current,reference):
 if not reference or reference.get('kind')!='official_close' or reference.get('verification')!='verified':return None
 if any(not current.get(k) or current.get(k)!=reference.get(k) for k in ['asset_id','currency','source','price_type','adjustment_basis','venue']):return None
 now=stamp(current.get('event_time'));old=stamp(reference.get('event_time'));x=decimal(current.get('price'));y=decimal(reference.get('price'))
 if not now or not old or old>=now or x is None or y is None or min(x,y)<=0:return None
 if not reference.get('source_id') or not current.get('market_phase') or not reference.get('reference_session') or not current.get('session_key') or reference.get('applies_to_session')!=current.get('session_key'):return None
 return {'percent':str((x-y)/y*100),'amount':str(x-y),'currency':current['currency'],'from':reference['event_time'],'to':current['event_time'],'basis':'official_close','source_id':reference['source_id']}

def unrealized(value,cost,fees=None):
 if not value or not cost or value.get('currency')!=cost.get('currency'):return None
 x=decimal(value.get('amount'));y=decimal(cost.get('amount'));fee=decimal(fees.get('amount')) if fees and fees.get('currency')==value.get('currency') else None
 if x is None or y is None or y<0 or fee is None:return None
 amount=x-y-fee
 return {'amount':str(amount),'currency':value['currency'],'percent':str(amount/y*100) if y>0 else None,'basis':'value_cost_known_fees'}

def account_result(current,opening,flows):
 if not current or not opening or flows is None or current.get('currency')!=opening.get('currency'):return None
 x=decimal(current.get('amount'));y=decimal(opening.get('amount'))
 if x is None or y is None or not flows.get('complete') or flows.get('currency')!=current.get('currency'):return None
 amount=decimal(flows.get('net_amount'))
 if amount is None:return None
 return {'amount':str(x-y-amount),'currency':current['currency'],'basis':'cashflow_adjusted','percent':str((x-y-amount)/y*100) if y>0 else None}

def candidate_group(row):
 lc=row.get('lifecycle',{}).get('status','DISCOVERED');decision=row.get('normalized_decision');owned=row.get('has_confirmed_position',False)
 active_order=row.get('has_active_order') or any(e.get('status') in ['SUBMITTED','ACCEPTED','PARTIALLY_FILLED'] and e.get('verification')=='pluto' for e in row.get('execution',[]))
 if lc in TERMINAL:return 'history'
 if decision=='REJECT' and not owned and not active_order and not row.get('documented_trigger'):return 'history'
 return {'DISCOVERED':'discovered','ANALYZING':'analyzing','WAITING_TRIGGER':'waiting','BUY_SIGNAL':'buy','ORDER_PENDING':'orders','POSITION_OPEN':'positions','EXIT_WATCH':'exit'}.get(lc,'active')

def order_group(status,changed_at,now,critical=False,resolved=False):
 if critical and not resolved:return 'critical'
 group=ORDER_GROUPS.get(status,'uncertain')
 if group=='recent':
  at=stamp(changed_at)
  return 'recent' if at and 0<=(now-at).total_seconds()<=86400 else 'history'
 return group

def journal_visible(event,now,days=7):
 if event.get('severity')=='critical' and not event.get('resolved'):return True
 at=stamp(event.get('timestamp'))
 return bool(at and 0<=(now-at).total_seconds()<=days*86400)
