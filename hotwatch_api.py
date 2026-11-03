"""Versioned management API sharing ESCAPE auth; no trading endpoints."""
import hmac,json,re
from urllib.parse import urlsplit,parse_qs,unquote
import hotwatch_engine as engine
from hotwatch_contract import EngineError,SESSION,SAMPLE
from report_validation import unique_object
PREFIX='/api/v1/hotwatch'

def handle(h,connect,method):
 request=urlsplit(h.path)
 if not (request.path==PREFIX or request.path.startswith(PREFIX+'/')):return False
 import mcp_reports
 try:
  auth=h.headers.get('Authorization');kind='cookie'
  if auth:
   identity=mcp_reports.bearer(connect,auth)
   if not identity:raise EngineError('authentication_required',401)
   with connect() as c:user=c.execute('SELECT role,username FROM users WHERE id=? AND active=1',(identity['user_id'],)).fetchone()
   if not user:raise EngineError('authentication_required',401)
   uid=identity['user_id'];role=user['role'];username=user['username'];kind='bearer';scopes=set(identity['scope'].split())
   if ('hotwatch:read' if method=='GET' else 'hotwatch:manage') not in scopes:raise EngineError('insufficient_scope',403)
  else:
   session=h.session()
   if not session:raise EngineError('authentication_required',401)
   uid=session['user_id'];role=session['role'];username=session['username']
   if method=='POST' and not hmac.compare_digest(h.headers.get('X-CSRF-Token',''),session['csrf']):raise EngineError('invalid_csrf',403)
  mcp_reports.memory_limit('hw-api:'+str(uid),120)
  q=parse_qs(request.query,keep_blank_values=True,max_num_fields=10)
  if any(len(v)!=1 for v in q.values()) or set(q)-{'is_test','after','limit','order','before'}:raise EngineError('invalid_query')
  mode=q.get('is_test',['false'])[0]
  if mode not in ['true','false']:raise EngineError('invalid_test_category')
  order=q.get('order',['asc'])[0]
  if order not in ['asc','desc']:raise EngineError('invalid_order')
  mode=mode=='true';after=int(q.get('after',['0'])[0]);limit=int(q.get('limit',['50'])[0])
  if not 0<=after<=10**15 or not 1<=limit<=100:raise EngineError('invalid_pagination')
  parts=[unquote(part) for part in request.path[len(PREFIX):].strip('/').split('/')];parts=[] if parts==[''] else parts
  data={}
  if method=='POST':
   if h.headers.get('Content-Type','').split(';')[0].lower()!='application/json':raise EngineError('json_required',415)
   if h.headers.get('Transfer-Encoding') or h.headers.get('Content-Encoding'):raise EngineError('unsupported_encoding')
   length=int(h.headers.get('Content-Length','0'))
   if not 0<length<=131072:raise EngineError('request_size',413)
   raw=h.rfile.read(length)
   if len(raw)!=length:raise EngineError('incomplete_request')
   data=json.loads(raw,object_pairs_hook=unique_object,parse_constant=lambda _:(_ for _ in ()).throw(ValueError()))
   if not isinstance(data,dict):raise EngineError('object_required')
  if method not in ['GET','POST']:raise EngineError('method_not_allowed',405)
  result=None;status=200
  if method=='GET' and parts==['schema']:result={'session':SESSION,'sample':SAMPLE,'engine_version':'1.0-phase1-2','deferred':['backtest','shadow','qualified strategy activation/rollback']}
  elif method=='GET' and parts==['providers']:
   from hotwatch_adapters import providers
   result={'providers':providers(connect,uid,mode)}
  elif len(parts)>=2 and parts[0]=='candidates' and method=='GET':
   import intel_workflows,candidate_lifecycle
   if len(parts)==2:
    with connect() as c:rows=intel_workflows.candidates(c,uid,mode,parts[1])
    if not rows:raise EngineError('candidate_not_found',404)
    result={'candidate':rows[0]}
   elif len(parts)==3 and parts[2]=='history':result=candidate_lifecycle.history(connect,uid,parts[1],mode,q.get('before',[None])[0],min(200,limit))
  elif parts==['sessions']:
   if method=='GET':result=engine.sessions(connect,uid,mode,after,limit)
   else:result=engine.create(connect,uid,data);status=200 if result['duplicate'] else 201
  elif len(parts)>=2 and parts[0]=='sessions':
   wid=parts[1]
   if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,100}',wid):raise EngineError('invalid_watch_id')
   if method=='GET' and len(parts)==2:result=engine.item(connect,uid,wid,mode)
   elif method=='GET' and len(parts)==3:result=engine.history(connect,uid,wid,mode,parts[2],after,limit,order)
   elif method=='POST' and len(parts)==3 and parts[2] in ['pause','resume','stop']:
    if set(data)!={'is_test'} or type(data['is_test']) is not bool:raise EngineError('is_test_required')
    result=engine.control(connect,uid,wid,data['is_test'],parts[2])
   elif method=='POST' and len(parts)==3 and parts[2]=='samples':
    if role!='admin' or kind!='cookie':raise EngineError('manual_test_ingestion_only',403)
    if not mode:raise EngineError('production_samples_require_trusted_adapter',403)
    if data.get('source')!='synthetic':raise EngineError('synthetic_test_adapter_required',403)
    result=engine.ingest(connect,uid,wid,True,data)
  elif parts and parts[0]=='strategies':
   if method=='GET' and len(parts)==1:result=engine.strategies(connect,uid)
   elif method=='POST' and len(parts)==1:
    if role!='admin' or kind!='cookie':raise EngineError('manual_admin_required',403)
    result=engine.upload_strategy(connect,uid,username,data);status=200 if result['duplicate'] else 201
   elif len(parts)>=2:
    version=q.get('version')
    # Versions are explicit in the path so immutable IDs remain unambiguous.
    if len(parts)<3:raise EngineError('strategy_version_required')
    with connect() as c:record=engine.strategy(c,uid,parts[1],parts[2]);payload=json.loads(record['payload'])
    if method=='GET' and len(parts)==3:result={'strategy':payload,'checksum':record['checksum'],'validation_status':record['validation_status']}
    elif method=='POST' and len(parts)==4 and parts[3]=='validate':
     from hotwatch_strategy import validate_strategy
     errors=validate_strategy(payload);result={'valid':not errors,'errors':errors,'qualification':'schema and bounded rule checks; historical/shadow qualification is deferred'}
    elif method=='POST' and len(parts)==4 and parts[3] in ['backtest','shadow','activate','rollback']:
     if role!='admin' or kind!='cookie':raise EngineError('manual_admin_required',403)
     raise EngineError('phase3_not_implemented',501)
  elif parts==['kill-switch'] and method=='POST':
   if role!='admin' or kind!='cookie':raise EngineError('manual_admin_required',403)
   if set(data)!={'enabled','reason'}:raise EngineError('invalid_kill_switch')
   result=engine.kill(connect,uid,data['enabled'],data['reason'])
  if result is None:raise EngineError('endpoint_not_found',404)
  h.send(status,result)
 except EngineError as error:h.send(error.status,error.result())
 except (ValueError,TypeError,KeyError,OverflowError,RecursionError):h.send(400,{'ok':False,'code':'invalid_request'})
 except Exception:h.send(500,{'ok':False,'code':'engine_internal_error'})
 return True
