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
    return {key:candidate[key] for key in ['ticker','company_name','signal','assessment','catalysts','risks','next_action','exit_plan','analysis_urls']}|{'tradability':candidate['tradability']['status'],'market_verification':candidate['market']['verification']}

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
