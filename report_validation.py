"""Shared, non-mutating report validation. No broker imports or writes.

JSON structure is declared once; semantic and account-scoped references are
checked here. Diagnostics contain field paths, never submitted field values.
"""
import hashlib,json,re
from datetime import date,datetime,timezone
from decimal import Decimal,localcontext
from urllib.parse import urlsplit
import report_v2

LIMITS={1:16384,2:262144}

def schema_v1():
    def string(limit=100):return {'type':'string','minLength':1,'maxLength':limit,'pattern':r'\S'}
    def array(props):return {'type':'array','maxItems':30,'items':{'type':'object','properties':props,'required':list(props),'additionalProperties':False}}
    props={'schema_version':{'type':'integer','const':1},'report_id':dict(string(),pattern='^[A-Za-z0-9_.:-]{1,100}$'),'generated_at':dict(string(50),format='date-time'),'source':string(),'is_test':{'type':'boolean'},'portfolio_values':array({'name':string(),'amount':{'type':'string','pattern':r'^-?\d{1,18}(\.\d{1,10})?$'},'currency':{'type':'string','pattern':'^[A-Z]{3}$'},'includes_collections':{'type':'boolean'}}),'candidates':array({'symbol':string(),'market':string(),'reason':string(2000)}),'assessments':array({'subject':string(),'assessment':string(2000)}),'orders':array({'reference':string(),'status':string(),'note':string(2000)})}
    return report_v2.strict_patterns({'type':'object','properties':props,'required':list(props),'additionalProperties':False})

# Field-level constraints remain visible to clients that flatten schemas.
# Version conditionals additionally enforce the exact selected structure.
def transport_schema():
    def merge(a,b):
        if a==b:return a
        if a.get('type')==b.get('type')=='object':
            keys=list(dict.fromkeys([*a['properties'],*b['properties']]))
            return {'type':'object','properties':{k:merge(a['properties'][k],b['properties'][k]) if k in a['properties'] and k in b['properties'] else a['properties'].get(k,b['properties'].get(k)) for k in keys},'required':[k for k in a['required'] if k in b['required']],'additionalProperties':False}
        if a.get('type')==b.get('type')=='array':return {'type':'array','maxItems':max(a['maxItems'],b['maxItems']),'items':merge(a['items'],b['items'])}
        return {'anyOf':[a,b]}
    versions=[schema_v1(),report_v2.SCHEMA];schema=merge(*versions)
    schema['properties']['schema_version']={'type':'integer','enum':[1,2]}
    schema['allOf']=[{'if':{'properties':{'schema_version':{'const':i}},'required':['schema_version']},'then':s} for i,s in enumerate(versions,1)]
    schema['description']='Exact v1/v2 structure. Use validate_report before send_report. All nullable fields remain required; use null for unknown values. Semantic/reference and canonical UTF-8 size checks are reported by the shared validator. No records are removed.'
    return schema

def issue(path,code,message,expected=None):
    result={'path':path or '$','code':code,'message':message}
    if expected is not None:result['expected']=expected
    return result

def expected(schema):
    if 'anyOf' in schema:return ' or '.join(dict.fromkeys(expected(s) for s in schema['anyOf']))
    kind=schema.get('type','value');return ' or '.join(kind) if isinstance(kind,list) else kind

def stamp(value):
    if not isinstance(value,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[Zz]|[+-]\d{2}:\d{2})',value):raise ValueError('date-time')
    result=datetime.fromisoformat(value.upper().replace('Z','+00:00'))
    if result.tzinfo is None:raise ValueError('timezone')
    return result

def schema_errors(value,schema,path=''):
    errors=[]
    def add(code,message,want=None):errors.append(issue(path,code,message,want))
    if 'anyOf' in schema:
        options=[schema_errors(value,s,path) for s in schema['anyOf']]
        if any(not e for e in options):return []
        # Prefer diagnostics inside a branch of the right type over a generic union failure.
        typed=[e for e in options if not any(x['path']==(path or '$') and x['code']=='invalid_type' for x in e)]
        return min(typed,key=len) if typed else [issue(path,'invalid_type','Expected '+expected(schema),expected(schema))]
    if 'type' not in schema:
        for child in schema.get('allOf',[]):errors.extend(schema_errors(value,child,path))
        if 'if' in schema and not schema_errors(value,schema['if'],path) and 'then' in schema:errors.extend(schema_errors(value,schema['then'],path))
        return errors
    kind=schema['type'];kinds=kind if isinstance(kind,list) else [kind]
    actual='null' if value is None else 'boolean' if type(value) is bool else 'integer' if type(value) is int else 'string' if isinstance(value,str) else 'object' if isinstance(value,dict) else 'array' if isinstance(value,list) else 'number' if type(value) is float else 'invalid'
    if actual not in kinds:return [issue(path,'invalid_type','Expected '+expected(schema),expected(schema))]
    if 'const' in schema and value!=schema['const']:add('invalid_const','Expected '+str(schema['const']))
    if 'enum' in schema and value not in schema['enum']:add('invalid_enum','Expected one of: '+', '.join(map(str,schema['enum'])))
    if actual=='object':
        for key in schema.get('required',[]):
            if key not in value:errors.append(issue((path+'.' if path else '')+key,'required','Required field; expected '+expected(schema['properties'][key]),expected(schema['properties'][key])))
        for key,child in value.items():
            loc=(path+'.' if path else '')+str(key)
            if key in schema.get('properties',{}):errors.extend(schema_errors(child,schema['properties'][key],loc))
            elif schema.get('additionalProperties') is False:errors.append(issue(loc,'unknown_field','Field is not part of this report version'))
    elif actual=='array':
        if len(value)>schema.get('maxItems',len(value)):add('max_items','Maximum '+str(schema['maxItems'])+' items')
        if len(value)<schema.get('minItems',0):add('min_items','Minimum '+str(schema['minItems'])+' items')
        if schema.get('uniqueItems') and len({json.dumps(v,sort_keys=True,default=str) for v in value})!=len(value):add('duplicate_items','Expected unique items')
        for i,child in enumerate(value):errors.extend(schema_errors(child,schema['items'],path+'['+str(i)+']'))
    elif actual=='string':
        if not value.strip() or len(value)<schema.get('minLength',0):add('min_length','Expected non-blank string')
        if len(value)>schema.get('maxLength',len(value)):add('max_length','Maximum '+str(schema['maxLength'])+' characters')
        if schema.get('pattern') and not re.search(schema['pattern'],value):add('invalid_format','Expected string matching '+schema['pattern'],'string matching '+schema['pattern'])
        try:
            fmt=schema.get('format')
            if fmt=='https-url':
                p=urlsplit(value)
                if p.scheme!='https' or not p.hostname or p.username or p.password or any(ch.isspace() or ord(ch)<32 for ch in value) or p.port is not None and not 1<=p.port<=65535:raise ValueError()
            elif fmt=='date-time':stamp(value)
            elif fmt=='date':
                if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',value):raise ValueError()
                date.fromisoformat(value)
        except (ValueError,OverflowError):add('invalid_format','Expected '+{'date-time':'RFC 3339 timestamp with timezone','date':'YYYY-MM-DD date','https-url':'HTTPS URL without credentials'}.get(schema.get('format'),'valid format'))
    for child in schema.get('allOf',[]):errors.extend(schema_errors(value,child,path))
    if 'if' in schema and not schema_errors(value,schema['if'],path):
        if 'then' in schema:errors.extend(schema_errors(value,schema['then'],path))
    elif 'if' in schema and 'else' in schema:errors.extend(schema_errors(value,schema['else'],path))
    return errors

def counts(data):
    def size(value):return len(value) if isinstance(value,list) else 0
    if not isinstance(data,dict):return {k:0 for k in ['portfolios','positions','orders','candidates','sources','regions']}
    return {'portfolios':size(data.get('portfolios',data.get('portfolio_values'))),'positions':size(data.get('positions')),'orders':size(data.get('orders')),'candidates':size(data.get('candidates')),'sources':size(data.get('sources')),'regions':size(data.get('summary',{}).get('regions')) if isinstance(data.get('summary'),dict) else 0}

def validate(data,connection=None,user_id=None):
    version=data.get('schema_version') if isinstance(data,dict) and type(data.get('schema_version')) is int else None
    errors=[];warnings=[]
    result={'valid':False,'schema_version':version,'errors':errors,'warnings':warnings,'counts':counts(data)}
    if not isinstance(data,dict):
        errors.append(issue('$','invalid_type','Expected object','object'));return result
    if version not in [1,2]:
        errors.append(issue('schema_version','invalid_version','Expected integer 1 or 2','integer'));return result
    schema=schema_v1() if version==1 else report_v2.SCHEMA
    errors.extend(schema_errors(data,schema))
    try:
        if len(json.dumps(data,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode())>LIMITS[version]:errors.append(issue('$','max_bytes','Maximum canonical UTF-8 size: '+str(LIMITS[version])+' bytes'))
    except (ValueError,TypeError,UnicodeError,OverflowError,RecursionError):errors.append(issue('$','invalid_json','Expected finite JSON values and valid UTF-8'))
    if connection is not None and user_id is not None and isinstance(data.get('report_id'),str):
        old=connection.execute('SELECT digest FROM ingested_reports WHERE user_id=? AND report_id=?',(user_id,data['report_id'])).fetchone()
        if old:
            try:digest=hashlib.sha256(json.dumps(data,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
            except (ValueError,TypeError,UnicodeError,OverflowError,RecursionError):digest=None
            if digest!=old['digest']:errors.append(issue('report_id','report_id_conflict','This report_id already exists with different content; the stored report is immutable'))
    if version==2:semantic(data,errors,warnings,connection,user_id)
    result['valid']=not errors
    return result

def semantic(data,errors,warnings,connection,user_id):
    def add(path,code,message):errors.append(issue(path,code,message))
    def rows(key):return [(i,r) for i,r in enumerate(data.get(key,[])) if isinstance(r,dict)] if isinstance(data.get(key),list) else []
    def mapping(value):return value if isinstance(value,dict) else {}
    def ids(value):return [x for x in value if isinstance(x,str)] if isinstance(value,list) else []
    maps={}
    for key,field in [('sources','source_id'),('portfolios','portfolio_id'),('candidates','candidate_id'),('positions','position_id'),('orders','order_id'),('journal','entry_id')]:
        maps[key]={}
        for i,row in rows(key):
            identity=row.get(field)
            if not isinstance(identity,str):continue
            if identity in maps[key]:add(f'{key}[{i}].{field}','duplicate_id','ID must be unique within '+key)
            else:maps[key][identity]=row
    def references(value,path=''):
        if isinstance(value,dict):
            refs=value.get('source_ids')
            if isinstance(refs,list):
                seen=set()
                for i,ref in enumerate(refs):
                    if not isinstance(ref,str):continue
                    loc=(path+'.' if path else '')+'source_ids['+str(i)+']'
                    if ref not in maps['sources']:add(loc,'unknown_reference','Expected source_id in this report')
                    if ref in seen:add(loc,'duplicate_reference','Source reference must be unique')
                    seen.add(ref)
            for k,v in value.items():references(v,(path+'.' if path else '')+k)
        elif isinstance(value,list):
            for i,v in enumerate(value):references(v,path+'['+str(i)+']')
    references(data)
    def verified(refs):return bool(ids(refs)) and all(maps['sources'].get(k,{}).get('verification')=='verified' and maps['sources'].get(k,{}).get('verified_at') is not None for k in ids(refs))
    for i,source in rows('sources'):
        if source.get('verification')=='verified' and source.get('verified_at') is None:add(f'sources[{i}].verified_at','required_evidence','Verified source requires verification timestamp')
    quality=mapping(data.get('data_quality'))
    if quality.get('status')=='verified':
        if quality.get('as_of') is None:add('data_quality.as_of','required_evidence','Verified report requires observation timestamp')
        if not maps['sources'] or any(s.get('verification')!='verified' for s in maps['sources'].values()):add('data_quality.status','required_evidence','Verified report requires verified sources')
    for i,p in rows('portfolios'):
        parent=p.get('parent_portfolio_id')
        if isinstance(parent,str) and (parent==p.get('portfolio_id') or parent not in maps['portfolios'] or maps['portfolios'][parent].get('kind')!='portfolio' or p.get('kind')!='collection'):add(f'portfolios[{i}].parent_portfolio_id','invalid_reference','Expected parent root portfolio for a collection')
    scoped=connection is not None and user_id is not None and type(data.get('is_test')) is bool
    history={};prior=None
    if scoped:
        # SELECT only; validation never touches reports, OAuth or rate-limit tables.
        history={r['candidate_id'] for r in connection.execute('SELECT DISTINCT candidate_id FROM report_candidate_links WHERE user_id=? AND is_test=?',(user_id,int(data['is_test'])))}
        prior=connection.execute("SELECT payload FROM ingested_reports WHERE user_id=? AND is_test=? AND report_type!='deep_analysis' ORDER BY generated_epoch DESC,id DESC LIMIT 1",(user_id,int(data['is_test']))).fetchone()
    for key in ['positions','orders','journal']:
        for i,row in rows(key):
            if key in ['positions','orders'] and isinstance(row.get('portfolio_id'),str) and row['portfolio_id'] not in maps['portfolios']:add(f'{key}[{i}].portfolio_id','unknown_reference','Expected portfolio_id in this report')
            cid=row.get('candidate_id')
            if isinstance(cid,str) and cid not in maps['candidates']:
                if scoped and cid not in history:add(f'{key}[{i}].candidate_id','unknown_reference','Expected candidate_id in this report or owned history in the same test category')
                elif not scoped:warnings.append(issue(f'{key}[{i}].candidate_id','context_required','Historical candidate reference requires account-scoped validation'))
            if key=='journal':
                for field,target in [('position_id','positions'),('order_id','orders')]:
                    ref=row.get(field)
                    if isinstance(ref,str) and ref not in maps[target]:add(f'journal[{i}].{field}','unknown_reference','Expected '+field+' in this report')
                for field,target in [('position_id','positions'),('order_id','orders')]:
                    linked=maps[target].get(row.get(field)) if isinstance(row.get(field),str) else None
                    if linked and isinstance(cid,str) and isinstance(linked.get('candidate_id'),str) and cid!=linked['candidate_id']:add(f'journal[{i}].{field}','reference_mismatch','Journal and referenced object identify different candidates')
    for i,row in rows('candidates'):
        base=f'candidates[{i}]';market=mapping(row.get('market'));tradable=mapping(row.get('tradability'))
        if market.get('verification')=='verified':
            if market.get('as_of') is None:add(base+'.market.as_of','required_evidence','Verified market data requires timestamp')
            if not verified(market.get('source_ids')):add(base+'.market.source_ids','required_evidence','Verified market data requires verified source references')
        elif market.get('verification') in ['unknown','unverified']:
            for key in ['price','volume','spread','fees']:
                if market.get(key) is not None:add(base+'.market.'+key,'unverified_value','Expected null until market data is verified')
        for key in ['price','spread','fees']:
            value=mapping(market.get(key));amount=value.get('amount')
            if isinstance(amount,str) and re.fullmatch(r'-?\d{1,18}(\.\d{1,12})?',amount) and Decimal(amount)<0:add(base+'.market.'+key+'.amount','negative_value','Expected non-negative decimal string')
            if isinstance(value.get('currency'),str) and value['currency']!=market.get('currency'):add(base+'.market.'+key+'.currency','currency_mismatch','Expected market.currency')
        if tradable.get('status') in ['available','unavailable']:
            if tradable.get('checked_at') is None:add(base+'.tradability.checked_at','required_evidence','Known tradability requires verification timestamp')
            if not verified(tradable.get('source_ids')):add(base+'.tradability.source_ids','required_evidence','Known tradability requires verified source references')
        for key in ['stop_price','target_price','max_loss']:
            value=mapping(mapping(row.get('exit_plan')).get(key));amount=value.get('amount')
            if isinstance(amount,str) and re.fullmatch(r'-?\d{1,18}(\.\d{1,12})?',amount) and Decimal(amount)<0:add(base+'.exit_plan.'+key+'.amount','negative_value','Expected non-negative decimal string')
    linked=mapping(data.get('analysis_for'))
    if linked:
        if data.get('report_type')!='deep_analysis':add('analysis_for','invalid_analysis_link','analysis_for requires report_type deep_analysis')
        if isinstance(linked.get('candidate_id'),str) and linked['candidate_id'] not in maps['candidates']:add('analysis_for.candidate_id','unknown_reference','Deep analysis must include the referenced candidate')
        if scoped and isinstance(linked.get('candidate_id'),str) and isinstance(linked.get('report_id'),str):
            parent=connection.execute('SELECT 1 FROM ingested_reports r JOIN report_candidate_links l ON l.report_row_id=r.id WHERE l.user_id=? AND l.is_test=? AND l.candidate_id=? AND r.report_id=?',(user_id,int(data['is_test']),linked['candidate_id'],linked['report_id'])).fetchone()
            if not parent:add('analysis_for.report_id','unknown_reference','Expected original report containing candidate on this account in the same test category')
        elif not scoped:warnings.append(issue('analysis_for','context_required','Original report link requires account-scoped validation'))
    consolidation(data,maps,errors,verified)
    if prior and data.get('report_type') not in ['deep_analysis','historical']:
        previous=json.loads(prior['payload'])
        if previous.get('schema_version')==2:
            missing=set(r['candidate_id'] for r in previous['candidates'])-maps['candidates'].keys()
            if missing:warnings.append(issue('candidates','candidates_omitted',str(len(missing))+' candidates from the latest main report are absent; nothing is automatically restored or removed from stored reports'))
    if scoped:
        cached={}
        for i,row in rows('candidates'):
            cid=row.get('candidate_id')
            if not isinstance(cid,str) or not isinstance(row.get('ticker'),str):continue
            saved=connection.execute('SELECT r.id,r.payload FROM report_candidate_links l JOIN ingested_reports r ON r.id=l.report_row_id WHERE l.user_id=? AND l.is_test=? AND l.candidate_id=? ORDER BY l.generated DESC,r.id DESC LIMIT 1',(user_id,int(data['is_test']),cid)).fetchone()
            if not saved:continue
            if saved['id'] not in cached:cached[saved['id']]={c['candidate_id']:c for c in json.loads(saved['payload'])['candidates']}
            before=cached[saved['id']].get(cid)
            if before and row['ticker'].upper()!=before['ticker'].upper():warnings.append(issue(f'candidates[{i}].candidate_id','candidate_identity_changed','Existing candidate_id has a different ticker; verify stable instrument identity before sending'))

def consolidation(data,maps,errors,verified):
    con=data.get('consolidation');con=con if isinstance(con,dict) else {}
    def add(field,message):errors.append(issue('consolidation'+('.'+field if field else ''),'invalid_consolidation',message))
    if con.get('status')=='unknown':
        for k in ['value','method']:
            if con.get(k) is not None:add(k,'Expected null for undocumented total')
        return
    if con.get('status')!='documented':return
    refs=con.get('portfolio_ids');refs=refs if isinstance(refs,list) else []
    seen=set()
    for i,key in enumerate(refs):
        if not isinstance(key,str):continue
        if key in seen:add(f'portfolio_ids[{i}]','Expected unique root portfolio references')
        if key not in maps['portfolios']:add(f'portfolio_ids[{i}]','Expected portfolio_id in this report')
        seen.add(key)
    if not refs:add('portfolio_ids','Expected at least one root portfolio')
    if con.get('value') is None:add('value','Documented total requires value')
    if con.get('method')!='root_totals_including_collections':add('method','Expected root_totals_including_collections')
    if not verified(con.get('source_ids')):add('source_ids','Documented total requires verified sources')
    selected=[maps['portfolios'][k] for k in refs if isinstance(k,str) and k in maps['portfolios']]
    if any(p.get('kind')!='portfolio' or p.get('parent_portfolio_id') is not None or p.get('includes_collections') is not True or p.get('value') is None or not verified(p.get('source_ids')) for p in selected):add('portfolio_ids','Only documented root totals including collections may be summed');return
    try:
        times={stamp(p.get('as_of')).astimezone(timezone.utc) for p in selected}
        if len(times)!=1:add('portfolio_ids','Expected same observation time for all totals')
        total=con['value']
        with localcontext() as context:
            context.prec=60
            if any(p['value']['currency']!=total['currency'] for p in selected) or sum(Decimal(p['value']['amount']) for p in selected)!=Decimal(total['amount']):add('value','Total or currency does not match documented roots')
    except (KeyError,TypeError,ValueError,ArithmeticError):
        # Structural diagnostics already identify invalid money/timestamps.
        if any(p.get('as_of') is None for p in selected):add('portfolio_ids','Expected non-null observation times')

def unique_object(entries):
    result={}
    for key,value in entries:
        if key in result:
            raise ReportValidationError({'valid':False,'schema_version':None,'errors':[issue('$','duplicate_key','Duplicate JSON object fields are not accepted')],'warnings':[],'counts':counts(None)})
        result[key]=value
    return result

class ReportValidationError(ValueError):
    def __init__(self,result):
        self.result=result
        super().__init__('; '.join(e['path']+': '+e['message'] for e in result['errors']))

def require(data,connection=None,user_id=None):
    result=validate(data,connection,user_id)
    if not result['valid']:raise ReportValidationError(result)
    return result
