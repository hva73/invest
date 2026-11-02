"""Versioned, declarative report contract. All content remains sender claims."""
from datetime import datetime,timezone
from decimal import Decimal,localcontext
from urllib.parse import urlsplit
import re

ID={'type':'string','pattern':r'^[A-Za-z0-9_.:-]{1,100}$'}
def string(limit=4000):return {'type':'string','minLength':1,'maxLength':limit}
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
    if 'anyOf' in schema:
        for option in schema['anyOf']:
            try:check(value,option,path);return
            except ValueError:pass
        raise ValueError(path+': forkert type eller værdi')
    kind=schema['type'];kinds=kind if isinstance(kind,list) else [kind]
    actual='null' if value is None else 'boolean' if type(value) is bool else 'integer' if type(value) is int else 'string' if isinstance(value,str) else 'object' if isinstance(value,dict) else 'array' if isinstance(value,list) else 'invalid'
    if actual not in kinds:raise ValueError(path+': forkert type')
    if 'const' in schema and value!=schema['const']:raise ValueError(path+': forkert version')
    if 'enum' in schema and value not in schema['enum']:raise ValueError(path+': ukendt værdi')
    if actual=='object':
        if set(value)!=set(schema['required']):raise ValueError(path+': felter matcher ikke v2')
        for key,child in schema['properties'].items():check(value[key],child,path+'.'+key)
    elif actual=='array':
        if len(value)>schema['maxItems']:raise ValueError(path+': for mange poster')
        for i,child in enumerate(value):check(child,schema['items'],path+'['+str(i)+']')
    elif actual=='string':
        if not value.strip() or len(value)>schema.get('maxLength',100000):raise ValueError(path+': ugyldig tekst')
        if schema.get('pattern') and not re.fullmatch(schema['pattern'].removeprefix('^').removesuffix('$'),value):raise ValueError(path+': ugyldigt format')
        fmt=schema.get('format')
        if fmt=='https-url':
            p=urlsplit(value)
            if p.scheme!='https' or not p.hostname or p.username or p.password or any(ch.isspace() or ord(ch)<32 for ch in value) or (p.port is not None and not 1<=p.port<=65535):raise ValueError(path+': HTTPS-link kræves')
        elif fmt=='date-time':
            stamp=datetime.fromisoformat(value.replace('Z','+00:00'))
            if stamp.tzinfo is None:raise ValueError(path+': tidszone kræves')
        elif fmt=='date':
            from datetime import date
            if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',value):raise ValueError(path+': dato kræves')
            date.fromisoformat(value)

def validate(data):
    check(data,SCHEMA)
    maps={}
    for key,idkey in [('sources','source_id'),('portfolios','portfolio_id'),('candidates','candidate_id'),('positions','position_id'),('orders','order_id'),('journal','entry_id')]:
        maps[key]={row[idkey]:row for row in data[key]}
        if len(maps[key])!=len(data[key]):raise ValueError('Gentagne ID i '+key)
    def refs(value):
        if isinstance(value,dict):
            if 'source_ids' in value and not set(value['source_ids'])<=maps['sources'].keys():raise ValueError('Ukendt kilde-ID')
            for child in value.values():refs(child)
        elif isinstance(value,list):
            for child in value:refs(child)
    refs(data)
    for source in data['sources']:
        if source['verification']=='verified' and source['verified_at'] is None:raise ValueError('Verificeret kilde kræver kontroltid')
    def verified_sources(ids):return bool(ids) and all(maps['sources'][key]['verification']=='verified' for key in ids)
    if data['data_quality']['status']=='verified' and (data['data_quality']['as_of'] is None or not data['sources'] or any(s['verification']!='verified' for s in data['sources'])):raise ValueError('Verificeret rapport kræver verificerede kilder og datatid')
    for p in data['portfolios']:
        parent=p['parent_portfolio_id']
        if parent is not None and (parent==p['portfolio_id'] or parent not in maps['portfolios'] or maps['portfolios'][parent]['kind']!='portfolio' or p['kind']!='collection'):raise ValueError('Uklar porteføljehierarki')
    for key in ['positions','orders']:
        for row in data[key]:
            if row['portfolio_id'] not in maps['portfolios']:raise ValueError('Ukendt portefølje-ID')
    for row in data['journal']:
        for field,target in [('position_id','positions'),('order_id','orders')]:
            if row[field] is not None and row[field] not in maps[target]:raise ValueError('Ukendt journalreference')
    for row in data['candidates']:
        market=row['market'];tradable=row['tradability']
        if market['verification']=='verified' and (market['as_of'] is None or not verified_sources(market['source_ids'])):raise ValueError('Verificerede markedsdata kræver kilder og tidspunkt')
        if market['verification']!='verified' and any(market[k] is not None for k in ['price','volume','spread','fees']):raise ValueError('Uverificerede kursfelter skal være null')
        for k in ['price','spread','fees']:
            if market[k] and Decimal(market[k]['amount'])<0:raise ValueError('Kurs, spread og gebyrer må ikke være negative')
            if market[k] and market[k]['currency']!=market['currency']:raise ValueError('Modstridende markedsvaluta')
        if tradable['status']!='unknown' and (tradable['checked_at'] is None or not verified_sources(tradable['source_ids'])):raise ValueError('Handelsbarhed kræver verificeret kilde og kontroltid')
    for candidate in data['candidates']:
        for key in ['stop_price','target_price','max_loss']:
            value=candidate['exit_plan'][key]
            if value and Decimal(value['amount'])<0:raise ValueError('Exitbeløb må ikke være negativt')
    con=data['consolidation']
    if con['status']=='unknown':
        if con['value'] is not None or con['method'] is not None:raise ValueError('Udokumenteret samlet værdi skal være null')
    else:
        ids=con['portfolio_ids']
        if not ids or len(set(ids))!=len(ids) or not set(ids)<=maps['portfolios'].keys() or con['value'] is None or con['method']!='root_totals_including_collections' or not verified_sources(con['source_ids']):raise ValueError('Dokumentation for samlet værdi mangler')
        selected=[maps['portfolios'][key] for key in ids]
        if any(p['kind']!='portfolio' or p['parent_portfolio_id'] is not None or p['includes_collections'] is not True or p['value'] is None or not verified_sources(p['source_ids']) for p in selected):raise ValueError('Collections må ikke summeres med hovedporteføljer')
        times={datetime.fromisoformat(p['as_of'].replace('Z','+00:00')).astimezone(timezone.utc) if p['as_of'] else None for p in selected}
        if len(times)!=1 or None in times:raise ValueError('Samlet værdi kræver samme datatidspunkt')
        with localcontext() as context:
            context.prec=60
            if any(p['value']['currency']!=con['value']['currency'] for p in selected) or sum(Decimal(p['value']['amount']) for p in selected)!=Decimal(con['value']['amount']):raise ValueError('Samlet beløb eller valuta stemmer ikke')
    return data

def material(candidate):
    return {key:candidate[key] for key in ['ticker','company_name','signal','assessment','catalysts','risks','next_action','exit_plan','analysis_urls']}|{'tradability':candidate['tradability']['status'],'market_verification':candidate['market']['verification']}
