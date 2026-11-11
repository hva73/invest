"""HOT WATCH Engine v1 contracts; independent of immutable report schemas."""
import json,hashlib,os
from report_v2 import obj,array,string,nullable,enum,ID,TIME,NUM,NONNEG_MONEY,SIGNED_NUM,strict_patterns
from report_validation import schema_errors,stamp
AT=TIME['anyOf'][0]
NUMBER=nullable({'type':'string','pattern':r'^-?\d{1,18}(\.\d{1,12})?$'})
RISK=obj({'max_notional_dkk':NUM['anyOf'][0],'max_loss_dkk':NUM['anyOf'][0],'max_spread_pct':NUM['anyOf'][0],'max_quote_age_s':{'type':'integer','minimum':1},'max_position_fraction_pct':NUM['anyOf'][0],'proposed_quantity':NUM,'stop_price':NUM,'exit_deadline':TIME})
SESSION=obj({'watch_id':ID,'report_id':ID,'candidate_id':ID,'is_test':{'type':'boolean'},'purpose':string(200),'ticker':string(60),'exchange':string(200),'asset_id':ID,'quote_currency':{'type':'string','pattern':'^[A-Z]{3}$'},'portfolio_ids':array({'type':'integer','minimum':1},30),'priority':enum('NORMAL','HIGH','CRITICAL'),'profile':enum('NORMAL','ACTIVE','CRITICAL','IDLE'),'provider':enum('pluto','report_inbox','eodhd','synthetic'),'end_at':TIME,'activation_reason':string(4000),'strategy_id':ID,'strategy_version':string(30),'risk':RISK})
SESSION['properties']['watch_id']=dict(ID,pattern=r'^[A-Za-z0-9][A-Za-z0-9_.:-]{0,99}$')
SESSION['properties'].update({'provider_symbol':nullable(string(80)),'trade_cycle_id':nullable(ID),'reactivation_reason':nullable(string(4000)),'watch_mode':enum('entry','exit','both')})
SESSION['properties'].update({'origin_candidate_id':nullable(ID),'origin_trade_cycle_id':nullable(ID),'origin_watch_id':nullable(ID)})
ACTIVATION_BATCH=obj({'request_id':ID,'is_test':{'type':'boolean'},'sessions':array(SESSION,40)})
ACTIVATION_BATCH['properties']['sessions']['maxItems']=40
CONTEXT=obj({'tradability':enum('available','unavailable','unknown'),'status':enum('verified','unknown'),'as_of':TIME,'position':enum('held','none','unknown'),'quantity':NUM,'cost_price':NUM,'portfolio_equity_dkk':NUM,'exposure_dkk':NUM,'fx_to_dkk':NUM,'fees_dkk':NUM,'orders':array(obj({'order_id':ID,'status':string(100),'requested_quantity':NUM,'filled_quantity':NUM,'side':nullable(enum('BUY','SELL'))}),100)})
SAMPLE=obj({'sample_id':ID,'source':enum('pluto','eodhd','report_inbox','synthetic'),'ticker':string(60),'asset_id':ID,'venue':nullable(string(200)),'currency':{'type':'string','pattern':'^[A-Z]{3}$'},'event_time':AT,'session_key':string(100),'market_status':enum('PRE','REGULAR','AFTER','CLOSED','HALTED','UNKNOWN'),'feed_type':string(200),'documented_delay_s':nullable({'type':'integer','minimum':0}),'verification':enum('verified','unverified','unknown'),'error_code':nullable(ID),'interval_s':{'type':'integer','minimum':1},'price':NUM,'bid':NUM,'ask':NUM,'volume':NUM,'volume_type':enum('interval','cumulative','unknown'),'open':NUM,'high':NUM,'low':NUM,'close':NUM,'context':CONTEXT})
# Additive evidence fields keep old journal records and clients valid.
SAMPLE['properties'].update({'bid_at':TIME,'ask_at':TIME,'status_at':TIME,'quote_feed':nullable(string(200)),'status_feed':nullable(string(200)),'price_time_kind':enum('trade','bar_open','snapshot'),'previous_close':NUM,'trade_size':NUM})
BAR=obj({'bar_open_at':AT,'open':NUM,'high':NUM,'low':NUM,'close':NUM,'volume':NUM})
BAR_EVIDENCE=obj({'provider_symbol':string(80),'market':enum('us','eu'),'exchange':string(16),'timezone':string(64),'session_date':dict(string(10),format='date'),'open':string(16),'close':string(16),'working_days':array(enum('Mon','Tue','Wed','Thu','Fri','Sat','Sun'),7),'excluded_dates':array(dict(string(10),format='date'),400),'schedule_received_at':AT,'exchange_open':{'type':'boolean'},'feed':enum('eodhd_realtime_history')})
SAMPLE['properties'].update({'bar_history':array(BAR,120),'bar_evidence':BAR_EVIDENCE})
CONTEXT['properties']['orders']['items']['properties'].update({'status_time':TIME,'average_fill_price':NUM,'limit_price':NUM,'stop_price':NUM,'order_type':nullable(string(100))})
CONTEXT['properties']['orders_complete']={'type':'boolean'}
# Stronger than a complete list of open orders: the trusted adapter must have
# accounted for all fills affecting this scoped position over the observation.
CONTEXT['properties']['position_history_complete']={'type':'boolean'}
CONTEXT['properties']['diagnostic']=nullable(string(100))
# Pluto get_asset type evidence is optional and distinct from sender claims.
CONTEXT['properties'].update({'instrument_type':nullable(string(100)),'instrument_type_at':TIME})
for s in [SESSION,SAMPLE]:strict_patterns(s)
STATES={'CREATED','VALIDATING','ACTIVE','PAUSED','DEGRADED','EXPIRED','COMPLETED','ERROR'}
OPEN_STATES={'CREATED','VALIDATING','ACTIVE','PAUSED','DEGRADED'}
PROFILES={'NORMAL':60,'ACTIVE':15,'CRITICAL':5,'IDLE':300}
def provider_floor(source):
 """Live feeds use the existing 5/15/60 second profiles; REST remains a reference."""
 if source!='eodhd':return {'pluto':300,'report_inbox':60,'synthetic':5}[source]
 if os.environ.get('ESCAPE_HW_EODHD_FAST_POLL_ENABLED')!='1':
  # The shared provider budget governs load; source timestamps govern signals.
  return 5 if os.environ.get('ESCAPE_HW_EODHD_WS_TRADES_ENABLED')=='1' and os.environ.get('ESCAPE_HW_EODHD_FUSE_ENABLED')=='1' else 300
 try:value=int(os.environ.get('ESCAPE_HW_EODHD_MIN_POLL_S','300'))
 except (TypeError,ValueError):return 300
 return value if 5<=value<=300 else 300
GLOBAL_RISK={'max_notional_dkk':'1000','max_loss_dkk':'100','max_spread_pct':'1','max_quote_age_s':120,'max_position_fraction_pct':'20'}
class EngineError(ValueError):
 def __init__(self,code,status=400,errors=None):
  self.code=code;self.status=status;self.errors=errors or [];super().__init__(code)
 def result(self):return {'ok':False,'code':self.code,'errors':self.errors}
def canonical(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
def checksum(value):return hashlib.sha256(canonical(value).encode()).hexdigest()
def require(data,schema):
 errors=schema_errors(data,schema)
 try:
  if len(canonical(data).encode())>131072:errors.append({'path':'$','code':'max_bytes','message':'Maximum 128 KiB'})
 except (ValueError,TypeError,UnicodeError):errors.append({'path':'$','code':'invalid_json','message':'Expected finite JSON'})
 if errors:raise EngineError('invalid_input',400,errors)
 return data
