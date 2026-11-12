"""User-selected, bounded LIMIT buy plans. Broker calls in this module are read-only."""
import copy,json
from decimal import Decimal,ROUND_DOWN,ROUND_UP,localcontext
import trade_service as trade
from hotwatch_contract import EngineError,canonical
from report_validation import stamp

TTL=120

def init(c):
 c.execute('CREATE TABLE IF NOT EXISTS hw_buy_plans(watch_row_id INTEGER PRIMARY KEY REFERENCES hw_sessions(id),payload TEXT NOT NULL,verified REAL NOT NULL)')

def number(value,zero=False):
 if type(value) not in (str,int,float):raise ValueError('numeric value required')
 n=Decimal(str(value))
 if not n.is_finite() or n<0 or not zero and n==0 or n>Decimal('1e12'):raise ValueError('invalid number')
 return n

def quote(raw,request,order):
 """Accept only the actually observed Pluto estimate shape; never a guessed FX."""
 try:
  e=raw['estimate'];a=e['asset'];currency=request['quote_currency']
  if e['side']!='BUY' or e['type']!='LIMIT' or a['ticker'].casefold()!=request['ticker'].casefold() or a['currency']!=currency:raise ValueError()
  if number(e['limitPrice'])!=number(order['limitPrice']):raise ValueError()
  if e['commissionCurrency']!='DKK' or e['filledAccountNotionalCurrency']!='DKK':raise ValueError()
  fee=number(e['commission'],True);cost=number(e['filledAccountNotional'])
  fx=e.get('assetBankFx')
  if currency=='DKK' and fx is None:rate=Decimal('1')  # Identity conversion, not an inferred broker rate.
  else:
   if fx['base']!=currency or fx['quote']!='DKK':raise ValueError()
   rate=number(fx['rate'])
  quantity=number(e['quantity']) if e.get('quantity') is not None else None
  if 'shares' in order and quantity!=number(order['shares']):raise ValueError()
  # A shares estimate can round the asset-currency notional to cents before
  # FX and then round the settlement amount. Bound both rounding steps; do not
  # accept arbitrary price/FX discrepancies as merely a rounding difference.
  if quantity is not None:
   exact=quantity*number(order['limitPrice'])*rate
   tolerance=rate*Decimal('.005')+Decimal('.005') if currency in ('USD','EUR','DKK') else Decimal('.02')
   if abs(cost-exact)>tolerance:raise ValueError()
   # Never let a rounded-down estimate understate the user's budget exposure.
   cost=max(cost,exact).quantize(Decimal('.01'),rounding=ROUND_UP)
  return {'fx_to_dkk':str(rate),'fees_dkk':str(fee),'account_notional_dkk':str(cost),'quantity':str(quantity) if quantity is not None else None}
 except (KeyError,TypeError,AttributeError,ArithmeticError,ValueError):
  raise EngineError('BUY_PLAN_ESTIMATE_INCOMPLETE',409) from None

def order_for(request,plan):
 return {'assetId':request['asset_id'],'side':'BUY','currency':'DKK','orderType':'LIMIT','timeInForce':'DAY','extendedHours':False,'shares':plan['quantity'],'limitPrice':plan['limit_price']}

def metadata(connect,uid,request,factory=None):
 cl,tools=trade.client(connect,uid,factory)
 return trade.call(cl,tools,'get_asset',{'assetId':request['asset_id']})

def read_quote(connect,uid,request,p,order,factory=None):
 payload={'portfolioId':p['external_id'].split(':',1)[1],'orders':[order]}
 result,asset=trade.read_estimate(connect,uid,p,payload,'direct',factory)
 a=asset.get('asset',{})
 if a.get('currency')!=request['quote_currency'] or a.get('ticker','').casefold()!=request['ticker'].casefold() or a.get('exchange')!=request['exchange'] or a.get('type')!='CS':raise EngineError('BUY_PLAN_INSTRUMENT_MISMATCH',409)
 if asset.get('buyBy',{}).get('shares') is not True:raise EngineError('BUY_PLAN_SHARES_UNSUPPORTED',409)
 return quote(result['quote'],request,order),asset

def bounded(plan,values):
 if number(values['account_notional_dkk'])+number(values['fees_dkk'],True)>number(plan['budget_dkk']):raise EngineError('BUY_PLAN_BUDGET_EXCEEDED',409)


def prepare(connect,uid,wid,data,factory=None):
 import hotwatch_engine as engine
 if set(data)!={'portfolio_id','budget_dkk','limit_price','stop_price'}:raise EngineError('invalid_buy_plan')
 try:
  budget=trade.positive(data['budget_dkk'],2,'1000');limit=trade.positive(data['limit_price'],2);stop=trade.positive(data['stop_price'],2)
  if number(stop)>=number(limit):raise ValueError()
  if type(data['portfolio_id']) is not int:raise ValueError()
 except (ValueError,ArithmeticError):raise EngineError('invalid_buy_plan') from None
 with connect() as c:
  row=engine.row_for(c,uid,wid,False);request=json.loads(row['request']);revision=row['revision']
  if request.get('watch_mode')!='entry' or row['status'] not in ('CREATED','VALIDATING','ACTIVE','DEGRADED'):raise EngineError('BUY_PLAN_ENTRY_REQUIRED',409)
  if c.execute('SELECT killed FROM hw_system_control WHERE id=1').fetchone()[0] or c.execute('SELECT 1 FROM hw_control WHERE user_id=? AND killed=1',(uid,)).fetchone():raise EngineError('kill_switch_active',409)
 p=trade.owned(connect,uid,data['portfolio_id'])
 if p['kind']!='portfolio':raise EngineError('BUY_PLAN_ROOT_REQUIRED',409)
 plan={'portfolio_id':p['id'],'budget_dkk':budget,'limit_price':limit,'stop_price':stop}
 # Obtain explicit FX and commission before deriving a maximum *limit-order*
 # quantity. This does not infer the quantity of a market order with null size.
 base={'assetId':request['asset_id'],'side':'BUY','currency':'DKK','orderType':'LIMIT','timeInForce':'DAY','extendedHours':False,'amount':budget,'limitPrice':limit}
 asset=metadata(connect,uid,request,factory)
 if asset.get('buyBy',{}).get('amount') is False:
  base.pop('amount');base['shares']='1'
 values,asset=read_quote(connect,uid,request,p,base,factory)
 with localcontext() as ctx:
  ctx.prec=60
  q=(number(budget)-number(values['fees_dkk'],True))/(number(limit)*number(values['fx_to_dkk']))
  fractional=asset.get('fractional',{}).get('buy')
  if type(fractional) is not bool:raise EngineError('BUY_PLAN_FRACTIONS_UNKNOWN',409)
  q=q.quantize(Decimal('.00000001') if fractional else Decimal('1'),rounding=ROUND_DOWN)
  if q<=0:raise EngineError('BUY_PLAN_BUDGET_TOO_SMALL',409)
  plan['quantity']=format(q,'f')
 values,_=read_quote(connect,uid,request,p,order_for(request,plan),factory)
 try:bounded(plan,values)
 except EngineError as error:
  if error.code!='BUY_PLAN_BUDGET_EXCEEDED':raise
  # Broker rounding or a changed FX quote can put the first estimate over the
  # selected budget. Shrink once, then require a fresh matching estimate.
  with localcontext() as ctx:
   ctx.prec=60
   quantum=Decimal('.00000001') if fractional else Decimal('1')
   fx=number(values['fx_to_dkk']);fee=number(values['fees_dkk'],True)
   buffer=fx*Decimal('.005')+Decimal('.01') if request['quote_currency'] in ('USD','EUR','DKK') else Decimal('.02')
   available=number(budget)-fee-buffer
   revised=(available/(number(limit)*fx)).quantize(quantum,rounding=ROUND_DOWN) if available>0 else Decimal('0')
   q=min(revised,number(plan['quantity'])-quantum)
   if q<=0:raise EngineError('BUY_PLAN_BUDGET_TOO_SMALL',409)
   plan['quantity']=format(q.quantize(quantum,rounding=ROUND_DOWN),'f')
  values,_=read_quote(connect,uid,request,p,order_for(request,plan),factory);bounded(plan,values)
 plan.update(values);now=engine.utc();plan['verified_at']=now.isoformat();plan['selected_at']=now.isoformat()
 with connect() as c:
  c.execute('BEGIN IMMEDIATE');current=engine.row_for(c,uid,wid,False)
  if current['revision']!=revision or current['status']!=row['status']:raise EngineError('BUY_PLAN_SESSION_CHANGED',409)
  request['portfolio_ids']=[p['id']];request['risk'].update(proposed_quantity=plan['quantity'],stop_price=stop)
  c.execute('INSERT INTO hw_buy_plans VALUES(?,?,?) ON CONFLICT(watch_row_id) DO UPDATE SET payload=excluded.payload,verified=excluded.verified',(row['id'],canonical(plan),now.timestamp()))
  state=json.loads(current['state']);state.update(signal='NO_DATA',pending=None,confirmations=0,pending_since=None)
  c.execute('UPDATE hw_sessions SET request=?,state=?,updated=?,revision=revision+1,lease_owner=NULL,lease_until=0,next_due=? WHERE id=?',(canonical(request),canonical(state),now.isoformat(),now.timestamp(),row['id']))
  engine.event(c,current,'BUY_PLAN_UPDATED',now,'Brugervalgt budget, limit og analytisk stop; ingen ordre oprettet')
 return {'ok':True,'broker_read_only':True,'order_created':False,'plan':plan,'note':'Afventer nye markedsobservationer og risikokontrol. Stop er analytisk; ingen stopordre oprettet.'}

def get(c,row,now):
 record=c.execute('SELECT * FROM hw_buy_plans WHERE watch_row_id=?',(row['id'],)).fetchone()
 if not record:return None
 plan=json.loads(record['payload']);plan['fresh']=0<=now.timestamp()-record['verified']<=TTL
 return plan

def refresh(connect,uid,request,factory=None):
 """Refresh fixed quantity/limit costs only; no resizing, proposal or execution."""
 import hotwatch_engine as engine
 now=engine.utc()
 with connect() as c:
  row=c.execute('SELECT * FROM hw_sessions WHERE user_id=? AND watch_id=? AND is_test=0',(uid,request['watch_id'])).fetchone()
  plan=get(c,row,now) if row else None
 if not plan or plan['fresh']:return
 p=trade.owned(connect,uid,plan['portfolio_id']);values,_=read_quote(connect,uid,request,p,order_for(request,plan),factory);bounded(plan,values)
 plan.pop('fresh',None);plan.update(values);plan['verified_at']=engine.utc().isoformat()
 with connect() as c:
  c.execute('UPDATE hw_buy_plans SET payload=?,verified=? WHERE watch_row_id=? AND EXISTS(SELECT 1 FROM hw_sessions WHERE id=? AND revision=? AND request=?)',(canonical(plan),stamp(plan['verified_at']).timestamp(),row['id'],row['id'],row['revision'],row['request']))

def apply(c,row,request,sample,risk,now):
 """Bind fresh costs and worst-case entry price centrally, never trust client data."""
 plan=get(c,row,now)
 if not plan:return sample,risk,None
 sample=copy.deepcopy(sample);risk=dict(risk);context=sample['context']
 context.update(fx_to_dkk=None,fees_dkk=None)
 match=plan['fresh'] and request['portfolio_ids']==[plan['portfolio_id']] and request['risk']['proposed_quantity']==plan['quantity'] and request['risk']['stop_price']==plan['stop_price']
 if match:
  context.update(fx_to_dkk=plan['fx_to_dkk'],fees_dkk=plan['fees_dkk'])
  risk.update(entry_price=plan['limit_price'],entry_limit=plan['limit_price'])
 return sample,risk,plan

def check_proposal(connect,uid,wid,payload,portfolio_id,raw=None):
 """Every HOT WATCH buy proposal must equal its plan, including size and scope."""
 import hotwatch_engine as engine
 try:
  with connect() as c:
   row=engine.row_for(c,uid,wid,False);request=json.loads(row['request']);plan=get(c,row,engine.utc())
 except EngineError:raise trade.TradeError('HOT WATCH-købsplanen findes ikke på din konto.') from None
 if not plan or not plan['fresh']:raise trade.TradeError('Købsplanen mangler eller er udløbet. Opdatér risikogrundlaget.')
 orders=payload.get('orders');expected=order_for(request,plan)
 try:
  same=isinstance(orders,list) and len(orders)==1 and set(orders[0])==set(expected) and all(number(orders[0][k])==number(v) if k in ('shares','limitPrice') else orders[0][k]==v for k,v in expected.items())
 except (TypeError,ValueError,ArithmeticError):same=False
 if portfolio_id!=plan['portfolio_id'] or not same:raise trade.TradeError('Forslaget svarer ikke til den risikokontrollerede købsplan. Opdatér planen før ændringer.')
 if raw is not None:
  try:
   values=quote(raw,request,order_for(request,plan));bounded(plan,values)
   if any(number(values[k],k=='fees_dkk')!=number(plan[k],k=='fees_dkk') for k in ('quantity','fx_to_dkk','fees_dkk','account_notional_dkk')):raise ValueError()
  except (EngineError,ValueError,ArithmeticError):raise trade.TradeError('Plutos valuta, størrelse eller gebyr er ændret eller ukendt. Opdatér købsplanen og signalet før afsendelse.') from None
