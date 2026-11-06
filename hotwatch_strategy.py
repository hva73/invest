"""Bounded declarative strategies, mandatory central risk gate and anti-noise."""
from decimal import Decimal,InvalidOperation,localcontext
import math,re
from hotwatch_contract import EngineError,GLOBAL_RISK,checksum
from report_validation import stamp

PARAMETERS={'min_relative_volume':'1.8','max_spread_pct':'0.8','momentum_pct':'0.3','min_acceleration':'0','max_volatility_pct':'3','short_period':5,'long_period':13,'rsi_period':14,'atr_period':14,'breakout_window':10,'min_samples':34,'confirmation_count':3,'cooldown_s':60,'minimum_signal_s':15,'release_momentum_pct':'0.1','exit_return_pct':'-0.8','trailing_pct':'2','allow_reduce':False}
METRICS={'sample_count','price','trend_up','return_1_pct','return_3_pct','return_5_pct','return_10_pct','velocity_pct_s','acceleration_pct_s2','sma_short','sma_long','ema_short','ema_long','rsi','macd','macd_signal','macd_histogram','breakout','breakdown','range_position_pct','distance_high_pct','distance_low_pct','volatility_pct','atr','spread','spread_pct','interval_volume','relative_volume','volume_acceleration','rising_price_falling_volume'}
OPERATORS={'>=','<=','>','<','==','!='}
BASELINE={'schema_version':1,'strategy_id':'escape_momentum','version':'1.0.0','description':'Konservativ kausal momentum-baseline; ingen dokumenteret profitabilitet.','parameters':PARAMETERS,'entry_rules':{'all':[{'metric':'return_3_pct','operator':'>=','parameter':'momentum_pct'},{'metric':'acceleration_pct_s2','operator':'>=','parameter':'min_acceleration'},{'metric':'relative_volume','operator':'>=','parameter':'min_relative_volume'},{'metric':'spread_pct','operator':'<=','parameter':'max_spread_pct'},{'metric':'volatility_pct','operator':'<=','parameter':'max_volatility_pct'},{'metric':'breakout','operator':'==','value':True},{'metric':'macd_histogram','operator':'>','value':'0'},{'metric':'trend_up','operator':'==','value':True},{'metric':'rsi','operator':'<=','value':'80'}]},'exit_rules':{'all':[{'metric':'return_3_pct','operator':'<=','parameter':'exit_return_pct'},{'metric':'breakdown','operator':'==','value':True}]}}

def validate_strategy(data):
 errors=[];nodes=0
 def error(path,message):errors.append({'path':path,'code':'invalid_strategy','message':message})
 if not isinstance(data,dict):return [{'path':'$','code':'invalid_type','message':'Expected strategy object'}]
 keys={'schema_version','strategy_id','version','description','parameters','entry_rules','exit_rules'}
 if set(data)!=keys:error('$','Exact strategy members required')
 if data.get('schema_version')!=1 or type(data.get('schema_version')) is not int:error('schema_version','Expected 1')
 for field,pattern in [('strategy_id',r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,99}'),('version',r'\d{1,4}\.\d{1,4}\.\d{1,4}')]:
  if not isinstance(data.get(field),str) or not re.fullmatch(pattern,data[field]):error(field,'Invalid stable ID or semantic version')
 if not isinstance(data.get('description'),str) or not 1<=len(data['description'])<=4000:error('description','Expected nonempty description up to 4000 characters')
 p=data.get('parameters');p=p if isinstance(p,dict) else {}
 if set(p)!=set(PARAMETERS):error('parameters','Exact documented parameter set required')
 integers={'short_period':(2,30),'long_period':(3,60),'rsi_period':(2,30),'atr_period':(2,30),'breakout_window':(3,60),'min_samples':(34,120),'confirmation_count':(2,10),'cooldown_s':(30,3600),'minimum_signal_s':(5,600)}
 for name,(lo,hi) in integers.items():
  if type(p.get(name)) is not int or not lo<=p[name]<=hi:error('parameters.'+name,f'Expected integer {lo}..{hi}')
 if type(p.get('allow_reduce')) is not bool:error('parameters.allow_reduce','Expected boolean')
 for name in set(PARAMETERS)-set(integers)-{'allow_reduce'}:
  try:
   if type(p.get(name)) not in [str,int,float]:raise ValueError()
   v=Decimal(str(p[name]))
   if not v.is_finite() or abs(v)>1000:raise ValueError()
   if name not in ['min_acceleration','exit_return_pct'] and v<=0:raise ValueError()
   if name=='exit_return_pct' and v>=0:raise ValueError()
  except (ValueError,InvalidOperation):error('parameters.'+name,'Expected bounded finite numeric threshold')
 if type(p.get('short_period')) is int and type(p.get('long_period')) is int and p['short_period']>=p['long_period']:error('parameters.long_period','Must exceed short period')
 def rule(r,path,depth):
  nonlocal nodes
  nodes+=1
  if nodes>64 or depth>4:error(path,'Maximum 64 rule nodes and depth 4');return
  if not isinstance(r,dict):error(path,'Expected rule object');return
  if set(r) in [{'all'},{'any'}]:
   field=next(iter(r));items=r[field]
   if not isinstance(items,list) or not 1<=len(items)<=12:error(path,'Expected 1..12 child rules');return
   for i,child in enumerate(items):rule(child,f'{path}.{field}[{i}]',depth+1)
  else:
   if set(r) not in [{'metric','operator','value'},{'metric','operator','parameter'}]:error(path,'Expected metric/operator and exactly one value or parameter');return
   if not isinstance(r.get('metric'),str) or r['metric'] not in METRICS or not isinstance(r.get('operator'),str) or r['operator'] not in OPERATORS:error(path,'Unknown indicator or operator')
   if 'parameter' in r and (not isinstance(r['parameter'],str) or r['parameter'] not in PARAMETERS):error(path,'Unknown parameter')
   if 'value' in r:
    if type(r['value']) is bool:return
    try:
     v=Decimal(str(r['value']))
     if not v.is_finite() or abs(v)>1000000000:raise ValueError()
    except (InvalidOperation,ValueError,TypeError):error(path,'Expected finite numeric or boolean constant')
 for key in ['entry_rules','exit_rules']:rule(data.get(key),key,1)
 return errors

def matches(rule,metrics,parameters):
 if 'all' in rule:return all(matches(r,metrics,parameters) for r in rule['all'])
 if 'any' in rule:return any(matches(r,metrics,parameters) for r in rule['any'])
 a=metrics.get(rule['metric']);b=parameters[rule['parameter']] if 'parameter' in rule else rule['value']
 if a is None:return False
 if type(a) is bool or type(b) is bool:
  if type(a) is not type(b):return False
 else:a=Decimal(str(a));b=Decimal(str(b))
 op=rule['operator'];return {'>=':lambda:a>=b,'<=':lambda:a<=b,'>':lambda:a>b,'<':lambda:a<b,'==':lambda:a==b,'!=':lambda:a!=b}[op]()

def _risk_gate(sample,metrics,risk,now,raw):
 """Mandatory for every strategy version. Session limits only tighten globals."""
 codes=[];critical=[];price=Decimal(sample['price']) if sample['price'] is not None else None
 age=now.timestamp()-stamp(sample['event_time']).timestamp();context=sample['context'];held=context['position']=='held'
 if sample['verification']!='verified' or sample['error_code']:codes.append('DATA_UNVERIFIED')
 if price is None or price<=0:codes.append('PRICE_MISSING')
 if age<0 or age>min(risk['max_quote_age_s'],GLOBAL_RISK['max_quote_age_s']):codes.append('DATA_STALE' if age>=0 else 'DATA_FUTURE')
 if sample['market_status'] in ['HALTED','CLOSED']:codes.append('MARKET_HALTED' if sample['market_status']=='HALTED' else 'MARKET_CLOSED')
 if sample['market_status']=='UNKNOWN':codes.append('MARKET_STATUS_UNKNOWN')
 context_fresh=context['status']=='verified' and context['as_of'] and 0<=now.timestamp()-stamp(context['as_of']).timestamp()<=300
 if not context_fresh or context['position']=='unknown':codes.append('POSITION_CONTEXT_UNKNOWN')
 if held and sample['verification']=='verified' and price is not None and risk['stop_price'] is not None and price<=Decimal(risk['stop_price']):critical.append('STOP_BREACHED')
 if held and risk['exit_deadline'] and now>=stamp(risk['exit_deadline']):critical.append('EXIT_DEADLINE')
 if codes:return 'NO_DATA' if not any(x in codes for x in ['MARKET_HALTED','MARKET_CLOSED']) else 'PAUSE',codes,critical
 if critical and held:
  if not risk.get('exit_allowed',True):return 'WAIT',['EXIT_OUTSIDE_WATCH_SCOPE'],critical
  return 'SELL',([] if sample['market_status']=='REGULAR' else ['EXTENDED_HOURS_EXECUTION_UNCONFIRMED']),critical
 if raw in ['SELL','REDUCE'] and not risk.get('exit_allowed',True):return 'WAIT',['EXIT_OUTSIDE_WATCH_SCOPE'],critical
 if raw!='BUY':return raw,codes,critical
 if context.get('tradability')!='available':codes.append('TRADABILITY_UNCONFIRMED')
 if not risk.get('entry_allowed',True):codes.append('ENTRY_NOT_AUTHORIZED_BY_CANDIDATE_DECISION')
 if metrics.get('volatility_pct') is not None and Decimal(metrics['volatility_pct'])>5:codes.append('VOLATILITY_LIMIT')
 if metrics.get('return_1_pct') is not None and abs(Decimal(metrics['return_1_pct']))>5:codes.append('PRICE_GAP_LIMIT')
 if sample['market_status']!='REGULAR':codes.append('OUTSIDE_REGULAR_SESSION')
 spread=metrics.get('spread_pct')
 if spread is None:codes.append('SPREAD_UNKNOWN')
 elif Decimal(spread)>min(Decimal(risk['max_spread_pct']),Decimal(GLOBAL_RISK['max_spread_pct'])):codes.append('SPREAD_TOO_WIDE')
 required=['relative_volume','volatility_pct','return_3_pct','acceleration_pct_s2','macd_histogram']
 if any(metrics.get(k) is None for k in required):codes.append('FEATURES_INSUFFICIENT')
 qty=risk['proposed_quantity'];fx=context['fx_to_dkk'];fees=context['fees_dkk'];equity=context['portfolio_equity_dkk'];exposure=context['exposure_dkk'];stop=risk['stop_price']
 if any(v is None for v in [qty,fx,fees,equity,exposure,stop]):codes.append('RISK_INPUTS_UNKNOWN')
 else:
  q=Decimal(qty);conversion=Decimal(fx);costs=Decimal(fees);capital=Decimal(equity);current=Decimal(exposure);limit=Decimal(stop)
  if q<=0 or conversion<=0 or capital<=0 or limit>=price:codes.append('RISK_INPUTS_INVALID')
  else:
   notional=q*price*conversion+costs;loss=q*(price-limit)*conversion+costs
   if notional>min(Decimal(risk['max_notional_dkk']),Decimal(GLOBAL_RISK['max_notional_dkk'])):codes.append('POSITION_SIZE_LIMIT')
   if loss>min(Decimal(risk['max_loss_dkk']),Decimal(GLOBAL_RISK['max_loss_dkk'])):codes.append('LOSS_BUDGET_LIMIT')
   if (current+notional)/capital*100>min(Decimal(risk['max_position_fraction_pct']),Decimal(GLOBAL_RISK['max_position_fraction_pct'])):codes.append('EXPOSURE_LIMIT')
 return ('WAIT' if codes else 'BUY'),codes,critical

def risk_gate(sample,metrics,risk,now,raw):
 with localcontext() as context:
  context.prec=80
  return _risk_gate(sample,metrics,risk,now,raw)

def calculate(sample,metrics,strategy,risk,state,now,killed=False,new_market_event=True):
 p=strategy['parameters'];held=sample['context']['position']=='held';raw='WAIT';reasons=[]
 if metrics.get('sample_count',0)<p['min_samples']:raw='NO_DATA';reasons.append('WARMUP')
 elif held and matches(strategy['exit_rules'],metrics,p):raw='REDUCE' if p['allow_reduce'] else 'SELL';reasons.append('EXIT_RULES')
 elif not held and matches(strategy['entry_rules'],metrics,p):raw='BUY';reasons.append('ENTRY_RULES')
 if held and metrics.get('distance_high_pct') is not None and Decimal(metrics['distance_high_pct'])<=-Decimal(str(p['trailing_pct'])):raw='SELL';reasons.append('TRAILING_EXIT')
 check='BUY' if raw=='WAIT' and not held else raw
 signal,risk_codes,critical=risk_gate(sample,metrics,risk,now,check)
 if raw=='WAIT' and signal=='BUY':signal='WAIT'
 if killed:signal='PAUSE';risk_codes=['KILL_SWITCH'];critical=[]
 reasons+=risk_codes+critical;at=now.timestamp();previous=state.get('signal','NO_DATA');newstate=dict(state)
 if signal in ['BUY','SELL','REDUCE'] and not critical:
  pending=state.get('pending')==signal;count=state.get('confirmations',0)+(1 if new_market_event else 0) if pending else (1 if new_market_event else 0)
  since=state.get('pending_since',at) if pending else at
  newstate.update(pending=signal,confirmations=count,pending_since=since)
  if not new_market_event and signal!=previous:signal='WAIT';reasons.append('NEW_MARKET_CONFIRMATION_REQUIRED')
  elif count<p['confirmation_count'] or at-since<p['minimum_signal_s']:signal='WAIT';reasons.append('CONFIRMATION_PENDING')
  elif signal!=previous and at-state.get('last_action_at',0)<p['cooldown_s']:signal='WAIT';reasons.append('COOLDOWN')
 else:newstate.update(pending=None,confirmations=0,pending_since=None)
 # Hysteresis only on valid, risk-approved data. Never retain BUY through a
 # stale quote, risk rejection, changed position or trading halt.
 if signal=='WAIT' and previous=='BUY' and not held and not risk_codes and metrics.get('return_3_pct') is not None and Decimal(metrics['return_3_pct'])>=Decimal(str(p['release_momentum_pct'])) and at-state.get('last_signal_at',0)<p['minimum_signal_s']:signal='BUY';reasons.append('HYSTERESIS_HOLD')
 if signal in ['BUY','SELL','REDUCE'] and signal!=previous and not critical and at-state.get('hour_started',at)<3600 and state.get('hour_signals',0)>=20:signal='WAIT';reasons.append('SIGNAL_RATE_LIMIT')
 if at-state.get('hour_started',at)>=3600 or 'hour_started' not in state:newstate.update(hour_started=at,hour_signals=0)
 if signal!=previous:
  newstate.update(signal=signal,last_signal_at=at)
  if signal in ['BUY','SELL','REDUCE']:
   newstate['hour_signals']=newstate.get('hour_signals',0)+1;newstate['last_action_at']=at
 score=0 if signal in ['NO_DATA','PAUSE'] else sum(1 for k in ['return_3_pct','relative_volume','spread_pct','volatility_pct','macd_histogram'] if metrics.get(k) is not None)*20
 explanations={'NO_TRIGGER':'Ingen bekræftet trigger','ENTRY_RULES':'Momentum, volumen, trend og kursbrud opfylder de deklarative indgangsregler','EXIT_RULES':'De deklarative exitbetingelser er opfyldt','WARMUP':'Der mangler sammenlignelige observationer til indikatorerne','CONFIRMATION_PENDING':'Afventer gentagne bekræftelser og minimumsvarighed','COOLDOWN':'Et nyt handlingssignal afventer cooldown','DATA_STALE':'Kursdata er for gamle','DATA_UNVERIFIED':'Kilden er ikke verificeret','STOP_BREACHED':'Den konfigurerede stopgrænse er brudt','EXIT_DEADLINE':'Den konfigurerede exitdeadline er nået','SPREAD_TOO_WIDE':'Spread overstiger den centrale risikogrænse','SPREAD_UNKNOWN':'Bid/ask-grundlaget mangler','POSITION_CONTEXT_UNKNOWN':'Aktuel depotkontekst mangler','TRADABILITY_UNCONFIRMED':'Pluto-handelsbarhed er ikke bekræftet','RISK_INPUTS_UNKNOWN':'Der mangler oplysninger om størrelse, valuta, gebyrer eller risiko','MARKET_STATUS_UNKNOWN':'Handelssessionen er ikke verificeret','NEW_MARKET_CONFIRMATION_REQUIRED':'En opdateret depotstatus tæller ikke som ny kursbekræftelse'}
 result={'signal':signal,'confidence_score':score,'signal_strength':'strong' if signal in ['BUY','SELL','REDUCE'] else 'neutral','reason_codes':list(dict.fromkeys(reasons)) or ['NO_TRIGGER'],'human_readable_explanation':'; '.join(explanations.get(code,code.replace('_',' ').lower()) for code in (list(dict.fromkeys(reasons)) or ['NO_TRIGGER'])),'supporting_metrics':metrics,'invalidating_conditions':['stale/unverified data','risk rejection','changed position','market halt'],'next_trigger':'Ny verificeret observation og opfyldte bekræftelses-/risikoregler','recommended_action':{'BUY':'KØB-signal · kræver særskilt godkendt handelsflow','SELL':'SÆLG-signal · ingen ordre oprettet','REDUCE':'REDUCÉR-signal · ingen ordre oprettet','WAIT':'VENT','NO_DATA':'INGEN DATA','PAUSE':'PAUSE'}[signal],'risk_level':'critical' if critical else 'high' if risk_codes else 'normal','calculation_timestamp':now.isoformat(),'data_timestamp':sample['event_time'],'strategy_id':strategy['strategy_id'],'strategy_version':strategy['version'],'strategy_checksum':checksum(strategy),'critical_override':bool(critical and signal=='SELL' and previous!='SELL'),'rules_score_note':'0–100 datapunktsdækning af fem regelinputs; ikke en statistisk sandsynlighed eller performanceprognose.'}
 return result,newstate
