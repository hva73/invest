"""Permanent candidate identity; lifecycle, recommendation and execution are separate."""
import json,hashlib
from datetime import datetime,timezone
from decimal import Decimal
from report_validation import stamp,issue
from report_v2 import CANDIDATE_LIFECYCLE as LIFECYCLE,LIFECYCLE_STATUSES as STATUSES
DECISIONS={'KØB':'BUY','AFVENT':'WAIT','FRAVÆLG':'REJECT'}
def canonical(d):return json.dumps(d,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
def init(c):
 old=c.execute("SELECT 1 FROM sqlite_master WHERE name='candidate_lifecycle_events'").fetchone()
 c.execute('CREATE TABLE IF NOT EXISTS candidate_trade_cycles(user_id INTEGER NOT NULL,is_test INTEGER NOT NULL,candidate_id TEXT NOT NULL,cycle_id TEXT NOT NULL,created TEXT NOT NULL,reason TEXT NOT NULL,origin TEXT NOT NULL,PRIMARY KEY(user_id,is_test,candidate_id,cycle_id))')
 c.execute('CREATE TABLE IF NOT EXISTS candidate_lifecycle_events(id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL,is_test INTEGER NOT NULL,candidate_id TEXT NOT NULL,event_key TEXT NOT NULL,status TEXT NOT NULL,reported_status TEXT,occurred REAL NOT NULL,occurred_at TEXT NOT NULL,reason TEXT NOT NULL,cycle_id TEXT,origin TEXT NOT NULL,evidence TEXT NOT NULL,payload TEXT NOT NULL,UNIQUE(user_id,is_test,candidate_id,event_key))')
 c.execute('CREATE INDEX IF NOT EXISTS candidate_lifecycle_time ON candidate_lifecycle_events(user_id,is_test,candidate_id,occurred,id)')
 c.execute('CREATE TABLE IF NOT EXISTS candidate_execution_events(id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL,is_test INTEGER NOT NULL,candidate_id TEXT NOT NULL,cycle_id TEXT,order_id TEXT NOT NULL,event_key TEXT NOT NULL,status TEXT NOT NULL,occurred REAL NOT NULL,occurred_at TEXT NOT NULL,origin TEXT NOT NULL,verification TEXT NOT NULL,payload TEXT NOT NULL,UNIQUE(user_id,is_test,candidate_id,event_key))')
 if not old:
  for row in c.execute('SELECT user_id,payload FROM ingested_reports ORDER BY generated_epoch,id'):
   d=json.loads(row['payload'])
   if d.get('schema_version')==2:index_report(c,row['user_id'],d,migration=True)

def latest(c,uid,mode,cid):
 return c.execute('SELECT * FROM candidate_lifecycle_events WHERE user_id=? AND is_test=? AND candidate_id=? ORDER BY occurred DESC,id DESC LIMIT 1',(uid,int(mode),cid)).fetchone()

def record(c,uid,mode,cid,status,at,reason,origin,cycle=None,evidence='analysis',reported=None,details=None):
 if status not in STATUSES:raise ValueError('Unknown lifecycle status')
 epoch=stamp(at).timestamp();previous=latest(c,uid,mode,cid)
 payload={'status':status,'reported_status':reported,'reason':reason,'trade_cycle_id':cycle,'evidence':evidence,'details':details or {}}
 key=hashlib.sha256((cid+canonical(payload)+str(epoch)).encode()).hexdigest()
 if previous and all(previous[k]==v for k,v in [('status',status),('reported_status',reported),('reason',reason),('cycle_id',cycle),('evidence',evidence)]):
  # Record material changes to a position, without journaling every refresh.
  before=json.loads(previous['payload']).get('details') or {};after=details or {}
  keys=('quantity','cost_price','price_currency')
  if status not in ('POSITION_OPEN','EXIT_WATCH') or all(before.get(k)==after.get(k) for k in keys):return False
 if cycle:c.execute('INSERT OR IGNORE INTO candidate_trade_cycles VALUES(?,?,?,?,?,?,?)',(uid,int(mode),cid,cycle,at,reason,origin))
 c.execute('INSERT OR IGNORE INTO candidate_lifecycle_events(user_id,is_test,candidate_id,event_key,status,reported_status,occurred,occurred_at,reason,cycle_id,origin,evidence,payload) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(uid,int(mode),cid,key,status,reported,epoch,at,reason,cycle,origin,evidence,canonical(payload)))
 return True

def position_proof(c,uid,candidate,now=None):
 now=now or datetime.now(timezone.utc);aid=candidate.get('asset_id')
 # This table exists in already installed v2.2; during first migration the
 # caller may be before portfolio_data.init. Missing proof stays unknown.
 if not c.execute("SELECT 1 FROM sqlite_master WHERE name='portfolio_snapshots'").fetchone():return None
 if not aid:
  if c.execute("SELECT 1 FROM sqlite_master WHERE name='market_asset_links'").fetchone():
   link=c.execute('SELECT asset_id,expected_ticker FROM market_asset_links WHERE user_id=? AND candidate_id=?',(uid,candidate['candidate_id'])).fetchone()
   if link and link['expected_ticker'].casefold()==candidate['ticker'].casefold():aid=link['asset_id']
 if not aid:return None
 stale_proof=None
 for row in c.execute("SELECT s.payload,s.last_error,p.id FROM portfolio_snapshots s JOIN portfolios p ON p.id=s.portfolio_id WHERE s.user_id=? AND p.user_id=? AND p.source='pluto' AND p.active=1",(uid,uid)):
  if row['last_error']:continue
  data=json.loads(row['payload'])
  if not data.get('positions_complete'):continue
  for p in data.get('positions',[]):
   if p.get('kind','holding')=='holding' and p.get('asset_id')==aid and (not p.get('ticker') or p['ticker'].casefold()==candidate['ticker'].casefold()) and p.get('quantity') is not None and Decimal(p['quantity'])>0:
    proof={'asset_id':aid,'portfolio_id':row['id'],'quantity':p['quantity'],'as_of':data['observed'],'stale':not 0<=(now-stamp(data['observed'])).total_seconds()<=300,'source':'authenticated Pluto snapshot'}
    if not proof['stale']:return proof
    if stale_proof is None:stale_proof=proof
 return stale_proof

def index_report(c,uid,data,migration=False):
 mode=data['is_test'];at=data['generated_at'];origin=data['report_id']
 for candidate in data['candidates']:
  cid=candidate['candidate_id'];previous=latest(c,uid,mode,cid)
  if not previous:record(c,uid,mode,cid,'DISCOVERED',at,'Første rapporterede observation',origin,details={'source_ids':candidate['source_ids'],'ticker':candidate['ticker'],'exchange':candidate.get('exchange'),'asset_id':candidate.get('asset_id')})
  lc=candidate.get('lifecycle');decision=candidate.get('decision')
  if not lc and decision:
   status={'KØB':'BUY_SIGNAL','AFVENT':'WAITING_TRIGGER','FRAVÆLG':'ARCHIVED'}[decision['status']]
   record(c,uid,mode,cid,status,decision['decided_at'],decision['reason'],origin,evidence='analysis',details={'decision':DECISIONS[decision['status']],'source_ids':decision['source_ids']})
  if lc:
   status=lc['status'];reported=None;proof=None
   if status in ['POSITION_OPEN','EXIT_WATCH']:
    proof=None if mode or migration else position_proof(c,uid,candidate)
    if not proof or proof['stale']:
     previous=latest(c,uid,mode,cid);reported=status;status=previous['status'] if previous else 'DISCOVERED'
   record(c,uid,mode,cid,status,lc['changed_at'],lc['reason'],origin,lc['trade_cycle_id'],'pluto_snapshot' if proof and not proof['stale'] else 'reported_unconfirmed' if reported else 'analysis',reported,{'source_ids':lc['source_ids'],'position_proof':proof})

def semantic(data,errors,warnings,c=None,uid=None):
 rows=data.get('candidates') if isinstance(data.get('candidates'),list) else [];cycles={}
 for i,candidate in enumerate(rows):
  if not isinstance(candidate,dict):continue
  lc=candidate.get('lifecycle');cid=candidate.get('candidate_id')
  if c is not None and uid is not None and type(data.get('is_test')) is bool and isinstance(cid,str) and isinstance(candidate.get('asset_id'),str):
   prior=c.execute('SELECT r.payload FROM report_candidate_links l JOIN ingested_reports r ON r.id=l.report_row_id WHERE l.user_id=? AND l.is_test=? AND l.candidate_id=? ORDER BY l.generated DESC,r.id DESC LIMIT 1',(uid,int(data['is_test']),cid)).fetchone()
   if prior:
    before=next(x for x in json.loads(prior['payload'])['candidates'] if x['candidate_id']==cid)
    if before.get('asset_id') and before['asset_id']!=candidate['asset_id']:errors.append(issue(f'candidates[{i}].asset_id','candidate_identity_conflict','Stable candidate_id belongs to another Pluto asset'))
  if not isinstance(lc,dict):continue
  try:
   if stamp(lc.get('changed_at'))>stamp(data.get('generated_at')):errors.append(issue(f'candidates[{i}].lifecycle.changed_at','future_evidence','Lifecycle change cannot be newer than its report'))
  except (ValueError,TypeError):pass
  if isinstance(lc.get('trade_cycle_id'),str) and isinstance(cid,str):cycles[(cid,lc['trade_cycle_id'])]=True
  if lc.get('status') in ['POSITION_OPEN','EXIT_WATCH']:warnings.append(issue(f'candidates[{i}].lifecycle.status','pluto_confirmation_required','Reported lifecycle is not proof of an executed trade; only owned broker evidence can confirm the position'))
  if c is not None and uid is not None and type(data.get('is_test')) is bool and isinstance(cid,str):
   try:epoch=stamp(lc.get('changed_at')).timestamp()
   except (ValueError,TypeError):epoch=None
   previous=c.execute('SELECT * FROM candidate_lifecycle_events WHERE user_id=? AND is_test=? AND candidate_id=? AND occurred<=? ORDER BY occurred DESC,id DESC LIMIT 1',(uid,int(data['is_test']),cid,epoch)).fetchone() if epoch is not None else None
   if previous and previous['occurred']==epoch and previous['status']!='DISCOVERED' and ((previous['reported_status'] or previous['status'])!=lc.get('status') or previous['reason']!=lc.get('reason')):errors.append(issue(f'candidates[{i}].lifecycle.changed_at','lifecycle_time_conflict','Same lifecycle timestamp has different content'))
   if previous and previous['status'] in ['ARCHIVED','CLOSED'] and lc.get('status') not in ['ARCHIVED','CLOSED'] and not candidate.get('reactivation_reason') and not (candidate['decision'].get('reactivation_reason') if isinstance(candidate.get('decision'),dict) else None):errors.append(issue(f'candidates[{i}].reactivation_reason','reactivation_evidence_required','Reopening a closed or archived candidate requires a documented new catalyst'))
 for collection in ['positions','orders','journal']:
  for i,row in enumerate(data.get(collection,[]) if isinstance(data.get(collection),list) else []):
   if not isinstance(row,dict) or row.get('trade_cycle_id') is None:continue
   cid=row.get('candidate_id');cycle=row['trade_cycle_id']
   if not isinstance(cid,str) or not isinstance(cycle,str):
    errors.append(issue(f'{collection}[{i}].trade_cycle_id','ambiguous_reference','Trade cycle requires explicit candidate_id'));continue
   found=(cid,cycle) in cycles
   if not found and c is not None and uid is not None and type(data.get('is_test')) is bool:found=c.execute('SELECT 1 FROM candidate_trade_cycles WHERE user_id=? AND is_test=? AND candidate_id=? AND cycle_id=?',(uid,int(data['is_test']),cid,cycle)).fetchone()
   if not found and c is None:
    warnings.append(issue(f'{collection}[{i}].trade_cycle_id','context_required','Historical trade cycle requires account-scoped validation'));continue
   if not found:errors.append(issue(f'{collection}[{i}].trade_cycle_id','unknown_reference','Expected trade cycle in candidate.lifecycle or owned history in the same category'))

def observe_pluto(c,uid,mode,cid,context,at,origin,cycle,signal=None,synthetic=False,price_currency=None):
 if context['status']!='verified' or not context['as_of'] or not 0<=stamp(at).timestamp()-stamp(context['as_of']).timestamp()<=300:return
 evidence='synthetic_test' if synthetic and mode else 'pluto'
 previous=latest(c,uid,mode,cid)
 last_broker=c.execute("SELECT * FROM candidate_lifecycle_events WHERE user_id=? AND is_test=? AND candidate_id=? AND cycle_id IS ? AND evidence IN ('pluto','pluto_snapshot','synthetic_test') ORDER BY occurred DESC,id DESC LIMIT 1",(uid,int(mode),cid,cycle)).fetchone()
 if context['position']=='none' and last_broker and last_broker['status'] in ['POSITION_OPEN','EXIT_WATCH']:
  target=previous['status'] if previous and previous['status'] in ['CLOSED','ARCHIVED'] else 'WAITING_TRIGGER'
  record(c,uid,mode,cid,target,at,'Pluto viser ingen position i konteksten; salg udledes ikke uden fyldningsbevis',origin,cycle,evidence,details={'position_state':'none','quantity':'0','as_of':context['as_of']})
 if context['position']=='held':
  target='EXIT_WATCH' if signal in ['SELL','REDUCE'] else 'POSITION_OPEN'
  record(c,uid,mode,cid,target,at,'Bekræftet depotobservation; adskilt fra nykøbsbeslutning',origin,cycle,evidence,details={'quantity':context['quantity'],'cost_price':context.get('cost_price'),'price_currency':price_currency if context.get('cost_price') is not None else None,'as_of':context['as_of']})
 for order in context['orders']:
  known=c.execute('SELECT cycle_id,status FROM candidate_execution_events WHERE user_id=? AND is_test=? AND candidate_id=? AND order_id=? ORDER BY id LIMIT 1',(uid,int(mode),cid,order['order_id'])).fetchone()
  if known and known['cycle_id'] is not None and known['cycle_id']!=cycle:continue
  raw=order['status'].upper();q=Decimal(order['filled_quantity']) if order['filled_quantity'] is not None else None;requested=Decimal(order['requested_quantity']) if order['requested_quantity'] is not None else None
  status='SUBMITTED' if raw in ['ACCEPTED','ACTIVE','OPEN','NEW'] else 'CANCELLED' if raw in ['CANCELLED','CANCELED'] else 'REJECTED' if raw=='REJECTED' else 'UNKNOWN'
  if q is not None and q>0 and status not in ['CANCELLED','REJECTED']:
   if requested is not None and q==requested and raw in ['FILLED','EXECUTED','COMPLETED']:status='FILLED'
   elif requested is not None and q<requested:status='PARTIALLY_FILLED'
  assigned_cycle=known['cycle_id'] if known else cycle
  if not known and status in ['FILLED','PARTIALLY_FILLED']:
   created=c.execute('SELECT created FROM candidate_trade_cycles WHERE user_id=? AND is_test=? AND candidate_id=? AND cycle_id=?',(uid,int(mode),cid,cycle)).fetchone()
   if not created or not order.get('status_time') or stamp(order['status_time'])<stamp(created['created']):assigned_cycle=None
  key=hashlib.sha256((order['order_id']+canonical(order)).encode()).hexdigest()
  c.execute('INSERT OR IGNORE INTO candidate_execution_events(user_id,is_test,candidate_id,cycle_id,order_id,event_key,status,occurred,occurred_at,origin,verification,payload) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(uid,int(mode),cid,assigned_cycle,order['order_id'],key,status,stamp(at).timestamp(),at,origin,evidence,canonical(order)))
  if context['position']=='none' and status=='FILLED' and order['side']=='SELL' and assigned_cycle==cycle:
   record(c,uid,mode,cid,'CLOSED',at,'Pluto bekræfter udført salg og ingen position i den kontrollerede depotkontekst',origin,cycle,evidence,details={'order_id':order['order_id'],'filled_quantity':order['filled_quantity']})

def projection(c,uid,mode,candidate,decision=None):
 cid=candidate['candidate_id'];row=latest(c,uid,mode,cid);lifecycle={'status':row['status'],'reported_status':row['reported_status'],'changed_at':row['occurred_at'],'reason':row['reason'],'trade_cycle_id':row['cycle_id'],'evidence':row['evidence']} if row else {'status':'DISCOVERED','reported_status':None,'changed_at':None,'reason':'Historisk kandidat; ingen eksplicit statusændring','trade_cycle_id':None,'evidence':'historical'}
 executions=[];seen=set()
 for e in c.execute('SELECT * FROM candidate_execution_events WHERE user_id=? AND is_test=? AND candidate_id=? ORDER BY occurred DESC,id DESC',(uid,int(mode),cid)):
  if e['order_id'] in seen:continue
  seen.add(e['order_id']);executions.append({'order_id':e['order_id'],'trade_cycle_id':e['cycle_id'],'status':e['status'],'verification':e['verification'],'as_of':e['occurred_at'],'data':json.loads(e['payload'])})
 proof=None if mode else position_proof(c,uid,candidate)
 broker_states={}
 for event in c.execute("SELECT * FROM candidate_lifecycle_events WHERE user_id=? AND is_test=? AND candidate_id=? AND evidence IN ('pluto','pluto_snapshot','synthetic_test') ORDER BY occurred DESC,id DESC",(uid,int(mode),cid)):
  if event['cycle_id'] in broker_states:continue
  detail=json.loads(event['payload'])['details'];broker_states[event['cycle_id']]=event['status'] in ['POSITION_OPEN','EXIT_WATCH'] and detail.get('position_state')!='none'
 historical_position=any(broker_states.values())
 cycles=[dict(r) for r in c.execute('SELECT cycle_id,created,reason,origin FROM candidate_trade_cycles WHERE user_id=? AND is_test=? AND candidate_id=? ORDER BY created',(uid,int(mode),cid))]
 return {'lifecycle':lifecycle,'normalized_decision':DECISIONS.get((decision or {}).get('status')),'execution':executions,'has_confirmed_position':bool(proof or historical_position),'position_proof':proof,'trade_cycles':cycles}

def history(connect,uid,cid,mode=False,before=None,limit=200):
 import re
 args=[uid,int(mode),cid];bound=''
 if before:
  if not isinstance(before,str) or not re.fullmatch(r'-?\d{1,12}(?:\.\d{1,9})?:\d{1,15}',before):raise ValueError('Invalid lifecycle cursor')
  epoch,identity=before.split(':');bound=' AND (occurred<? OR (occurred=? AND id<?))';args.extend([float(epoch),float(epoch),int(identity)])
 if type(limit) is not int or not 1<=limit<=200:raise ValueError('Invalid lifecycle page size')
 args.append(limit+1)
 with connect() as c:
  rows=c.execute('SELECT * FROM candidate_lifecycle_events WHERE user_id=? AND is_test=? AND candidate_id=?'+bound+' ORDER BY occurred DESC,id DESC LIMIT ?',args).fetchall()
  return {'candidate_id':cid,'is_test':mode,'events':[{'event_id':r['event_key'],'occurred_at':r['occurred_at'],'origin':r['origin'],**json.loads(r['payload'])} for r in rows[:limit]],'next_cursor':str(rows[limit-1]['occurred'])+':'+str(rows[limit-1]['id']) if len(rows)>limit else None,'truncated':len(rows)>limit}
