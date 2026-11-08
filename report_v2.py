"""Versioned, declarative report contract. All content remains sender claims."""
ID={'type':'string','pattern':r'^[A-Za-z0-9_.:-]{1,100}$'}
def string(limit=4000):return {'type':'string','minLength':1,'maxLength':limit,'pattern':r'\S'}
def nullable(s):return {'anyOf':[s,{'type':'null'}]}
def array(s,limit=80):return {'type':'array','items':s,'maxItems':limit}
def obj(props):return {'type':'object','properties':props,'required':list(props),'additionalProperties':False}
def enum(*items):return {'type':'string','enum':list(items)}
TIME=nullable(dict(string(50),format='date-time'))
NUM=nullable({'type':'string','pattern':r'^\d{1,18}(\.\d{1,12})?$'})
MONEY=nullable(obj({'amount':{'type':'string','pattern':r'^-?\d{1,18}(\.\d{1,12})?$'},'currency':{'type':'string','pattern':'^[A-Z]{3}$'}}))
REFS=array(ID)
URL=dict(string(2000),format='https-url')
SOURCE=obj({'source_id':ID,'url':URL,'publisher':nullable(string(200)),'published_at':TIME,'verified_at':TIME,'verification':enum('verified','unverified','historical','unknown')})
PORTFOLIO=obj({'portfolio_id':ID,'name':string(200),'role':enum('main','ai_trader','other'),'kind':enum('portfolio','collection'),'parent_portfolio_id':nullable(ID),'includes_collections':{'type':['boolean','null']},'value':MONEY,'cash':array(MONEY,10),'earmarked':array(MONEY,10),'as_of':TIME,'source_ids':REFS})
CANDIDATE=obj({'candidate_id':ID,'ticker':string(60),'company_name':nullable(string(200)),'region':nullable(string(100)),'sector':nullable(string(100)),'signal':enum('KØB','SÆLG','BEHOLD','AFVENT','OVERVÅG'),'assessment':nullable(string(12000)),'catalysts':array(obj({'date':nullable(dict(string(10),format='date')),'expectation':nullable(string()),'risks':nullable(string()),'source_ids':REFS}),20),'risks':array(string(12000),20),'next_action':nullable(string()),'source_ids':REFS,'tradability':obj({'status':enum('available','unavailable','unknown'),'checked_at':TIME,'source_ids':REFS}),'market':obj({'price':MONEY,'volume':NUM,'currency':nullable({'type':'string','pattern':'^[A-Z]{3}$'}),'spread':MONEY,'fees':MONEY,'as_of':TIME,'verification':enum('verified','unverified','unknown'),'source_ids':REFS}),'exit_plan':obj({'strategy':nullable(string()),'stop_price':MONEY,'target_price':MONEY,'max_loss':MONEY,'note':nullable(string())}),'analysis_urls':array(URL,10)})
SCHEMA=obj({'schema_version':{'type':'integer','const':2},'report_id':ID,'generated_at':dict(string(50),format='date-time'),'source':string(200),'is_test':{'type':'boolean'},'report_type':enum('morning','intraday','evening','daily','deep_analysis','historical'),'data_quality':obj({'status':enum('verified','unverified','historical','mixed','unknown'),'as_of':TIME,'note':nullable(string())}),'summary':obj({'overview':nullable(string(12000)),'regions':array(obj({'region':string(100),'summary':nullable(string(12000)),'source_ids':REFS}),20)}),'sources':array(SOURCE,150),'portfolios':array(PORTFOLIO,30),'consolidation':obj({'status':enum('unknown','documented'),'value':MONEY,'portfolio_ids':array(ID,30),'method':nullable(enum('root_totals_including_collections')),'source_ids':REFS,'note':nullable(string())}),'positions':array(obj({'position_id':ID,'portfolio_id':ID,'candidate_id':nullable(ID),'ticker':nullable(string(60)),'quantity':NUM,'value':MONEY,'cost_basis':MONEY,'as_of':TIME,'source_ids':REFS}),150),'orders':array(obj({'order_id':ID,'portfolio_id':ID,'candidate_id':nullable(ID),'ticker':nullable(string(60)),'status':string(100),'lifecycle':enum('pending','partial','filled','cancelled','rejected','unknown'),'requested_quantity':NUM,'filled_quantity':NUM,'allocated':MONEY,'as_of':TIME,'source_ids':REFS,'note':nullable(string())}),100),'candidates':array(CANDIDATE,80),'journal':array(obj({'entry_id':ID,'candidate_id':nullable(ID),'position_id':nullable(ID),'order_id':nullable(ID),'occurred_at':TIME,'kind':enum('observation','analysis','reported_trade','reported_order','note'),'text':string(12000),'source_ids':REFS}),100),'analysis_for':nullable(obj({'candidate_id':ID,'report_id':ID}))})

def check(value,schema,path='$'):
    from report_validation import schema_errors,ReportValidationError
    errors=schema_errors(value,schema,'' if path=='$' else path)
    if errors:raise ReportValidationError({'valid':False,'errors':errors,'warnings':[]})

def validate(data):
    from report_validation import require
    require(data)
    return data

def material(candidate):
    return {'decision':candidate.get('decision'),'strategy_proposal':candidate.get('strategy_proposal'),**{key:candidate[key] for key in ['ticker','company_name','signal','assessment','catalysts','risks','next_action','exit_plan','analysis_urls']}|{'tradability':candidate['tradability']['status'],'market_verification':candidate['market']['verification']}}

# Announce local dependencies already enforced by the backend. Cross-object
# source/identity checks remain in report_validation, where account data exists.
def condition(field,values,props):
    return {'if':{'type':'object','properties':{field:enum(*values)},'required':[field]},'then':{'type':'object','properties':props}}
NONNEG_MONEY=nullable(obj({'amount':NUM['anyOf'][0],'currency':{'type':'string','pattern':'^[A-Z]{3}$'}}))
SOURCE['allOf']=[condition('verification',['verified'],{'verified_at':TIME['anyOf'][0]})]
REFS['uniqueItems']=True
market=CANDIDATE['properties']['market']
for field in ['price','spread','fees']:market['properties'][field]=NONNEG_MONEY
for field in ['stop_price','target_price','max_loss']:CANDIDATE['properties']['exit_plan']['properties'][field]=NONNEG_MONEY
market['allOf']=[condition('verification',['verified'],{'as_of':TIME['anyOf'][0],'source_ids':dict(REFS,minItems=1)}),condition('verification',['unknown','unverified'],{k:{'type':'null'} for k in ['price','volume','spread','fees']})]
CANDIDATE['properties']['tradability']['allOf']=[condition('status',['available','unavailable'],{'checked_at':TIME['anyOf'][0],'source_ids':dict(REFS,minItems=1)})]
SCHEMA['properties']['data_quality']['allOf']=[condition('status',['verified'],{'as_of':TIME['anyOf'][0]})]
SCHEMA['properties']['consolidation']['allOf']=[condition('status',['unknown'],{'value':{'type':'null'},'method':{'type':'null'}}),condition('status',['documented'],{'value':MONEY['anyOf'][0],'method':enum('root_totals_including_collections'),'portfolio_ids':dict(array(ID,30),minItems=1,uniqueItems=True),'source_ids':dict(REFS,minItems=1)})]
SCHEMA['allOf']=[{'if':{'type':'object','properties':{'analysis_for':{'type':'object'}},'required':['analysis_for']},'then':{'type':'object','properties':{'report_type':enum('deep_analysis')}}}, {'if':{'type':'object','properties':{'data_quality':{'type':'object','properties':{'status':enum('verified')},'required':['status']}},'required':['data_quality']},'then':{'type':'object','properties':{'sources':{'type':'array','minItems':1,'items':{'type':'object','properties':{'verification':enum('verified')}}}}}}]


def strict_patterns(value):
    # JSON Schema uses search semantics and `$` may match before a newline.
    # Keep the original backend's full-match rule explicit in the contract.
    if isinstance(value,dict):
        pattern=value.get('pattern')
        if isinstance(pattern,str) and pattern.endswith('$'):value['pattern']=pattern+r'(?![\s\S])'
        for child in value.values():strict_patterns(child)
    elif isinstance(value,list):
        for child in value:strict_patterns(child)
    return value
strict_patterns(SCHEMA)

# Optional positions extension: old v2 objects remain valid and immutable.
from copy import deepcopy
POSITION=SCHEMA['properties']['positions']['items']
SIGNED_NUM=nullable({'type':'string','pattern':r'^-?\d{1,18}(\.\d{1,18})?$'})
POSITION_ASSESSMENT=obj({'action':enum('BEHOLD','OVERVÅG','AFVENT','REDUCÉR','SÆLG'),'reason':string(12000),'risk_level':enum('low','medium','high','unknown'),'next_action':nullable(string()),'assessed_at':TIME['anyOf'][0],'source_ids':dict(REFS,minItems=1),'data_quality':deepcopy(SCHEMA['properties']['data_quality'])})
POSITION_MARKET=obj({'price':NONNEG_MONEY,'daily_change':MONEY,'daily_change_percent':SIGNED_NUM,'price_as_of':TIME,'change_as_of':TIME,'verification':enum('verified','unverified','unknown'),'source_ids':REFS})
POSITION_MARKET['allOf']=[condition('verification',['verified'],{'price_as_of':TIME['anyOf'][0],'source_ids':dict(REFS,minItems=1)}),condition('verification',['unknown','unverified'],{k:{'type':'null'} for k in ['price','daily_change','daily_change_percent']})]
POSITION['properties'].update({'asset_id':nullable(ID),'asset_name':nullable(string(200)),'assessment':nullable(POSITION_ASSESSMENT),'market':nullable(POSITION_MARKET),'unrealized_pnl':MONEY,'position_status':enum('open','closed','unknown')})
SCHEMA['properties']['orders']['items']['properties'].update({'asset_id':nullable(ID),'side':nullable(enum('BUY','SELL')),'order_type':nullable(enum('MARKET','LIMIT','STOP','STOP_LIMIT')),'stop_price':NONNEG_MONEY,'limit_price':NONNEG_MONEY})
strict_patterns(SCHEMA)

PORTFOLIO['properties']['reported_result']=MONEY
strict_patterns(SCHEMA)

SCHEMA['properties']['journal']['items']['properties']['portfolio_id']=nullable(ID)
strict_patterns(SCHEMA)

# Optional V2.2 fields; legacy required fields remain unchanged.
"""Additive v2.2 contracts; observation payloads are stored independently."""
from copy import deepcopy
AT=TIME['anyOf'][0]
DECISION=obj({'status':enum('KØB','AFVENT','FRAVÆLG'),'decided_at':AT,'reason':string(12000),'next_trigger':nullable(string()),'deadline':TIME,'data_as_of':TIME,'source_ids':dict(REFS,minItems=1),'reactivation_reason':nullable(string()),'buy_plan':nullable(obj({'max_limit_price':NONNEG_MONEY['anyOf'][0],'amount_dkk':NONNEG_MONEY['anyOf'][0],'horizon':string(500),'expires_at':AT,'risk_budget':NONNEG_MONEY['anyOf'][0],'upside':string(2000),'downside':string(2000),'exit_method':string(4000),'approval':enum('proposed','awaiting_approval','approved','rejected','unknown')}))})
DECISION['allOf']=[{'if':{'properties':{'status':{'const':'KØB'}},'required':['status']},'then':{'properties':{'buy_plan':DECISION['properties']['buy_plan']['anyOf'][0]}}},{'if':{'properties':{'status':{'const':'AFVENT'}},'required':['status']},'then':{'properties':{'next_trigger':string(),'deadline':AT,'data_as_of':AT}}}]
COVERAGE=obj({'exchanges':array(string(200),80),'status':enum('OK','FEJL','IKKE KØRT'),'screening_count':nullable({'type':'integer','minimum':0}),'data_at':TIME,'news_checked_at':TIME,'new_signals':nullable({'type':'integer','minimum':0}),'pluto_verified':nullable({'type':'integer','minimum':0}),'excluded':nullable({'type':'integer','minimum':0}),'gaps':array(string(),30),'basis':enum('intraday','previous_close','unknown')})
COVERAGE['allOf']=[{'if':{'properties':{'status':{'const':'OK'}},'required':['status']},'then':{'properties':{'exchanges':dict(array(string(200),80),minItems=1),'data_at':AT,'screening_count':{'type':'integer','minimum':0}}}}]
OBSERVATION=obj({'observation_id':ID,'report_id':ID,'candidate_id':ID,'is_test':{'type':'boolean'},'observed_at':AT,'deadline':AT,'instrument':obj({'ticker':string(60),'exchange':nullable(string(200)),'asset_id':nullable(ID)}),'market':obj({'price':NONNEG_MONEY,'price_at':TIME,'bid':NONNEG_MONEY,'bid_at':TIME,'ask':NONNEG_MONEY,'ask_at':TIME,'spread':NONNEG_MONEY,'spread_percent':NUM,'volume':NUM,'volume_at':TIME,'volume_basis':nullable(string(200)),'intraday_percent':SIGNED_NUM,'momentum':enum('accelerating','decelerating','unknown'),'venue':nullable(string(200)),'feed_type':nullable(string(200)),'delay_seconds':nullable({'type':'integer','minimum':0}),'verification':enum('verified','unverified','unknown'),'price_source':enum('pluto','eodhd','other','unknown'),'source_ids':REFS}),'recent_trades':array(obj({'trade_id':ID,'price':NONNEG_MONEY['anyOf'][0],'quantity':NUM['anyOf'][0],'occurred_at':AT,'source_ids':REFS}),50),'decision':nullable(deepcopy(DECISION)),'next_trigger':nullable(string()),'position_ref':nullable(obj({'portfolio_id':ID,'position_id':ID})),'order_ids':array(ID,100),'position_action':nullable(obj({'action':enum('BEHOLD','OVERVÅG','AFVENT','REDUCÉR','SÆLG'),'reason':string(12000),'assessed_at':AT,'source_ids':REFS})),'sources':array(SOURCE,150),'note':nullable(string(4000))})

def extend(schema):
    p=schema['properties']
    SOURCE['properties'].update({'data_at':TIME,'venue':nullable(string(200)),'feed_type':nullable(string(200)),'delay_seconds':nullable({'type':'integer','minimum':0}),'primary_news_url':nullable(URL)})
    p['candidates']['items']['properties']['decision']=nullable(deepcopy(DECISION))
    p['summary']['properties']['regions']['items']['properties']['coverage']=nullable(deepcopy(COVERAGE))
    p['portfolios']['items']['properties'].update({'valuation_method':nullable(string(200)),'liquidity':nullable(obj({'available':array(NONNEG_MONEY,10),'reserved':array(NONNEG_MONEY,10),'earmarked':array(NONNEG_MONEY,10),'unknown':array(NONNEG_MONEY,10)}))})
    p['orders']['items']['properties']['lifecycle']['enum'].append('expired')
    p['orders']['items']['properties'].update({'approval_status':nullable(enum('proposed','awaiting_approval','approved','rejected','unknown')),'average_fill_price':NONNEG_MONEY,'created_at':TIME,'status_changed_at':TIME,'expires_at':TIME,'realized_pnl':MONEY,'execution_source':nullable(enum('pluto','other','unknown'))})
    return strict_patterns(schema)
strict_patterns(OBSERVATION)
extend(SCHEMA)

# Additive permanent candidate lifecycle. Decision remains the existing v2
# KØB/AFVENT/FRAVÆLG object; API projections also expose BUY/WAIT/REJECT.
LIFECYCLE_STATUSES=['DISCOVERED','ANALYZING','HOT_WATCH','WAITING_TRIGGER','BUY_SIGNAL','ORDER_PENDING','POSITION_OPEN','EXIT_WATCH','CLOSED','ARCHIVED']
CANDIDATE_LIFECYCLE=obj({'status':enum(*LIFECYCLE_STATUSES),'changed_at':TIME['anyOf'][0],'reason':string(4000),'source_ids':REFS,'trade_cycle_id':nullable(ID)})
CANDIDATE['properties'].update({'asset_id':nullable(ID),'exchange':nullable(string(200)),'lifecycle':nullable(CANDIDATE_LIFECYCLE),'reactivation_reason':nullable(string(4000))})
for collection in ['positions','orders','journal']:SCHEMA['properties'][collection]['items']['properties']['trade_cycle_id']=nullable(ID)
strict_patterns(SCHEMA)

# Optional exact provider reference; sender claims do not confer broker authority.
PORTFOLIO['properties']['broker_reference']=nullable(obj({'provider':enum('pluto'),'external_id':ID}))

# Optional explicit strategy proposal. It is an attributed recommendation,
# not an authorization to change an existing session or execute a trade.
STRATEGY_PROPOSAL=obj({'strategy_id':ID,'version':dict(string(30),pattern=r'^\d{1,4}\.\d{1,4}\.\d{1,4}$'),'reason':string(4000),'proposed_at':AT,'source_ids':dict(REFS,minItems=1)})
STRATEGY_CATALYST=obj({'kind':string(200),'published_at':AT,'available_at':AT,'source_ids':dict(REFS,minItems=1)})
STRATEGY_PROPOSAL['properties']['catalyst']=nullable(STRATEGY_CATALYST)
CANDIDATE['properties']['strategy_proposal']=nullable(STRATEGY_PROPOSAL)
strict_patterns(SCHEMA)

# Optional attributed evidence for Early Catalyst. All values remain sender
# claims until corroborated by a trusted provider; missing fields remain unknown.
STRATEGY_QUOTE=obj({'price':NONNEG_MONEY['anyOf'][0],'observed_at':AT,'available_at':AT,'source_ids':dict(REFS,minItems=1)})
STRATEGY_PROPOSAL['properties'].update({'news_check':nullable(obj({'status':enum('verified_news','no_verified_news','unknown'),'checked_at':AT,'source_ids':dict(REFS,minItems=1)})), 'reference_close':nullable(STRATEGY_QUOTE),'pre_news_price':nullable(deepcopy(STRATEGY_QUOTE)),'news_session':nullable(enum('during_regular','after_close','before_open','unknown'))})
strict_patterns(SCHEMA)
STRATEGY_PROPOSAL['properties']['news_check']['description']='Afsenderens kildekontrol: status, checked_at og source_ids. Verified news kræver en dateret catalyst og fælles kilde. Ikke uafhængigt verificeret af ESCAPE.'
STRATEGY_PROPOSAL['properties']['reference_close']['description']='Oplyst ordinær lukkekurs med valuta, observationstid, tilgængelighedstid og kilde. ESCAPE kræver yderligere lokal bekræftelse.'
STRATEGY_PROPOSAL['properties']['pre_news_price']['description']='Oplyst kurs umiddelbart før nyhedens offentliggørelse. Kræver dato, valuta, kilde og lokal matchende observation.'
STRATEGY_PROPOSAL['properties']['news_session']['description']='Afsenderens forslag til markedsfase; ESCAPE bruger selvstændig børskalender når den er tilgængelig.'
