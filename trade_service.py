"""Explicit, user-reviewed Pluto proposals. No direct execution or background writes."""
import hashlib,json,re,secrets,time
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
import oauth,report_ingest
from mcp_client import MCP,decode_result,normalize,compatible

CONTRACT=json.loads((Path(__file__).parent/'pluto_trade_contract.json').read_text())
class TradeError(ValueError):pass

def init(c):
    c.execute('CREATE TABLE IF NOT EXISTS broker_proposals(id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),fingerprint TEXT NOT NULL,report_id TEXT NOT NULL,candidate_id TEXT NOT NULL,kind TEXT NOT NULL,portfolio_id INTEGER NOT NULL REFERENCES portfolios(id),payload TEXT NOT NULL,status TEXT NOT NULL,created REAL NOT NULL,estimated REAL,review_token TEXT,estimate TEXT,asset TEXT,intent_id TEXT,response TEXT,error TEXT,UNIQUE(user_id,fingerprint))')
    if 'sell_basis' not in {r[1] for r in c.execute('PRAGMA table_info(broker_proposals)')}:c.execute('ALTER TABLE broker_proposals ADD COLUMN sell_basis TEXT')
    c.execute('CREATE TABLE IF NOT EXISTS manual_test_signals(user_id INTEGER PRIMARY KEY REFERENCES users(id),portfolio_id INTEGER NOT NULL REFERENCES portfolios(id),ticker TEXT NOT NULL,amount TEXT NOT NULL,expires REAL NOT NULL)')
    if 'side' not in {r[1] for r in c.execute('PRAGMA table_info(manual_test_signals)')}:c.execute("ALTER TABLE manual_test_signals ADD COLUMN side TEXT NOT NULL DEFAULT 'BUY'")

def active_test_signal(c,user_id,now=None):
    row=c.execute("SELECT t.portfolio_id,t.ticker,t.side,t.expires FROM manual_test_signals t JOIN portfolios p ON p.id=t.portfolio_id AND p.user_id=t.user_id WHERE t.user_id=? AND t.expires>? AND p.active=1 AND p.source='pluto' AND p.kind='portfolio'",(user_id,time.time() if now is None else now)).fetchone()
    return dict(row) if row else None

def structural(v):
    if isinstance(v,dict):return {k:structural(x) for k,x in v.items() if k not in ['description','title','$schema','default','examples']}
    if isinstance(v,list):return [structural(x) for x in v]
    return v

def client(connect,user_id,factory=None):
    result=(factory or MCP)(oauth.access_token(connect,user_id));return result,{t['name']:t for t in result.tools()}

def estimate_error(response,client):
    """Display only bounded provider error messages, never the response or credentials."""
    messages=[]
    def collect(value,depth=0):
        if depth>3:return
        if isinstance(value,str):
            try:parsed=json.loads(value)
            except (ValueError,TypeError):messages.append(value);return
            if isinstance(parsed,(dict,list)):collect(parsed,depth+1)
            else:messages.append(value)
        elif isinstance(value,dict):
            for key in ['error','message','error_description','detail','reason']:
                if key in value:collect(value[key],depth+1)
        elif isinstance(value,list):
            for item in value[:5]:collect(item,depth+1)
    if isinstance(response,dict):
        collect(response.get('structuredContent'))
        for block in response.get('content',[]) if isinstance(response.get('content'),list) else []:
            if isinstance(block,dict) and block.get('type')=='text':collect(block.get('text'))
        collect(response.get('error'))
    text=' · '.join(dict.fromkeys(messages))
    if re.search(r'(?i)connection may only read',text) and re.search(r'(?i)propose orders',text):
        return 'Pluto-forbindelsen har kun læseadgang. Gå til Forbindelser og vælg “Forbind med adgang til handelsforslag”, og godkend hos Pluto. Intet handelsforslag er sendt.'
    for attr in ['token','session']:
        secret=getattr(client,attr,None)
        if isinstance(secret,str) and secret:text=text.replace(secret,'[skjult]')
    if re.search(r'(?i)access_token|refresh_token|authorization|client_secret|password|api_key',text):
        text='[Fejltekst med loginfelter skjult]'
    text=re.sub(r'(?i)bearer\s+[^\s,;]+','Bearer [skjult]',text)
    text=re.sub(r'(?i)(access_token|refresh_token|authorization|client_secret|password|api_key)[\s"\']*[:=][\s"\']*[^\s,;}]+',r'\1=[skjult]',text)
    text=re.sub(r'https?://[^\s]+','[adresse skjult]',text)
    text=re.sub(r'[A-Za-z0-9_.+/-]{32,}','[id skjult]',text)
    text=' '.join(text.split())[:600]
    return 'Pluto afviste estimatet'+(': '+text if text else '; ingen nærmere begrundelse blev leveret')+'. Intet handelsforslag er oprettet eller sendt hos Pluto af dette opslag.'

def call(client,tools,name,args):
    expected=CONTRACT.get(name);actual=tools.get(name,{})
    if not expected or actual.get('annotations',{}).get('readOnlyHint') is not expected['readOnlyHint'] or structural(actual.get('inputSchema'))!=expected['inputSchema']:
        raise TradeError('Plutos værktøjskontrakt for '+name+' skal gennemgås før brug.')
    response=client.request('tools/call',{'name':name,'arguments':args})
    if name.startswith('estimate_') and isinstance(response,dict) and response.get('isError'):
        raise TradeError(estimate_error(response,client))
    result=decode_result(response,name)
    if name.startswith('estimate_') and isinstance(result,dict) and (result.get('error') or result.get('success') is False):
        raise TradeError(estimate_error({'structuredContent':result},client))
    return result

def positive(value,places=8,maximum='1000000000000'):
    if not isinstance(value,str) or not re.fullmatch(r'\d+(?:\.\d{1,'+str(places)+r'})?',value):raise TradeError('Brug positive tal med punktum og højst '+str(places)+' decimaler.')
    number=Decimal(value)
    if not 0<number<=Decimal(maximum):raise TradeError('Beløbet eller antallet ligger uden for det tilladte interval.')
    return format(number.normalize(),'f')

def candidate(connect,user_id,report_id,candidate_id):
    rows=report_ingest.desk(connect,user_id)['candidates']
    record=next((r for r in rows if r['schema_version']==2 and r['report_id']==report_id and r['candidate'].get('candidate_id')==candidate_id),None)
    if not record:raise TradeError('Vælg et aktuelt KØB- eller SÆLG-forslag fra dine driftsrapporter.')
    signal=(record.get('decision') or {}).get('status') or record['candidate']['signal']
    if signal not in ['KØB','SÆLG']:raise TradeError('Vælg et aktuelt KØB- eller SÆLG-forslag fra dine driftsrapporter.')
    report=report_ingest.item(connect,user_id,report_id,False)['report']['data']
    if report.get('report_type')=='historical' or report.get('data_quality',{}).get('status')=='historical':raise TradeError('Historiske rapporter kan ikke sendes som handelsforslag.')
    return {**record['candidate'],'signal':signal}

def signal_source(connect,user_id,report_id,candidate_id):
    if report_id in ('@manual-buy','@manual-sell'):
        if not isinstance(candidate_id,str) or not 1<=len(candidate_id)<=200 or any(ord(x)<33 for x in candidate_id):raise TradeError('Vælg et gyldigt Pluto-aktiv.')
        return {'signal':'KØB' if report_id=='@manual-buy' else 'SÆLG','asset_id':candidate_id}
    if report_id!='@hotwatch':return candidate(connect,user_id,report_id,candidate_id)
    import hotwatch_engine
    try:session=hotwatch_engine.item(connect,user_id,candidate_id,False)['session']
    except Exception as error:raise TradeError('HOT WATCH-signalet kan ikke kontrolleres.') from error
    signal=session.get('signal');request=session.get('request') or {}
    if session.get('status')!='ACTIVE' or signal not in ('BUY','SELL','REDUCE'):
        raise TradeError('HOT WATCH-signalet er ikke længere et aktivt købs- eller salgssignal.')
    if session.get('display_status')!={'BUY':'KØBSSIGNAL','SELL':'SÆLGSSIGNAL','REDUCE':'EXIT WATCH'}[signal]:
        raise TradeError('Signalet afventer kontrol eller revurdering. Intet forslag er sendt.')
    asset=request.get('asset_id')
    if not isinstance(asset,str) or not asset:raise TradeError('Signalets Pluto-aktiv er ikke verificeret.')
    return {'signal':'KØB' if signal=='BUY' else 'SÆLG','asset_id':asset,'ticker':request.get('ticker')}

def verify_proposal_source(connect,user_id,row):
    source=signal_source(connect,user_id,row['report_id'],row['candidate_id'])
    payload=json.loads(row['payload']);orders=payload.get('orders') or []
    expected='BUY' if source['signal']=='KØB' else 'SELL'
    if row['kind']=='direct' and (len(orders)!=1 or orders[0].get('side')!=expected):
        raise TradeError('Signalets retning er ændret. Hent et nyt estimat.')
    if row['kind']=='direct' and source.get('asset_id') and orders[0].get('assetId')!=source['asset_id']:
        raise TradeError('Signalets aktiv er ændret. Hent et nyt estimat.')
    if row['kind']=='collection_buy' and expected!='BUY' or row['kind']=='collection_sell' and expected!='SELL':
        raise TradeError('Signalets retning er ændret. Hent et nyt estimat.')
    if row['report_id']=='@hotwatch':
        if row['kind']!='direct' or orders[0].get('assetId')!=source['asset_id']:
            raise TradeError('Signalets aktiv eller retning er ændret. Hent et nyt estimat.')

def owned(connect,user_id,pid):
    with connect() as c:row=c.execute("SELECT * FROM portfolios WHERE id=? AND user_id=? AND source='pluto' AND active=1",(pid,user_id)).fetchone()
    if not row:raise TradeError('Vælg en aktiv Pluto-enhed på din egen konto.')
    return dict(row)

def build(connect,user_id,data,preview=False):
    if preview:
        if data.get('kind')!='direct' or data.get('side') not in ['BUY','SELL']:raise TradeError('Testestimatet kræver et direkte aktiv og en valgt køb/salg-retning.')
        side=data['side']
    else:
        c=signal_source(connect,user_id,str(data.get('report_id','')),str(data.get('candidate_id','')))
        side='BUY' if c['signal']=='KØB' else 'SELL'
    try:pid=int(data.get('portfolio_id'))
    except (ValueError,TypeError):raise TradeError('Vælg en aktiv Pluto-enhed før beregningen.')
    p=owned(connect,user_id,pid);kind=data.get('kind')
    currency=data.get('currency')
    if currency not in ['DKK','EUR','USD']:raise TradeError('Vælg afregningsvaluta: DKK, EUR eller USD.')
    if kind=='direct':
        if p['kind']!='portfolio':raise TradeError('Direkte aktiver skal handles på hovedporteføljen. Collection-handler er særskilte.')
        aid=data.get('asset_id','')
        if not isinstance(aid,str) or not 1<=len(aid)<=200 or any(ord(x)<33 for x in aid):raise TradeError('Vælg det konkrete aktiv fra Plutos søgeresultater.')
        if not preview and c.get('asset_id') and aid!=c['asset_id']:raise TradeError('Aktivet svarer ikke til signalet.')
        order={'assetId':aid,'side':side,'currency':currency,'orderType':data.get('order_type'),'timeInForce':data.get('time_in_force'),'extendedHours':False}
        if order['orderType'] not in ['MARKET','LIMIT','STOP','STOP_LIMIT'] or order['timeInForce'] not in ['DAY','GTC']:raise TradeError('Vælg ordretype og gyldighed.')
        if order['orderType']=='MARKET' and order['timeInForce']!='DAY':raise TradeError('Markedsordrer understøttes kun med DAY.')
        mode=data.get('size_mode')
        if mode not in ['shares','amount'] or side=='SELL' and mode!='shares':raise TradeError('Salg af direkte aktiver skal angives i antal.')
        order[mode]=positive(data.get('size'))
        if order['orderType'] in ['LIMIT','STOP_LIMIT']:order['limitPrice']=positive(data.get('limit_price'),2)
        if order['orderType'] in ['STOP','STOP_LIMIT']:order['stopPrice']=positive(data.get('stop_price'),2)
        payload={'portfolioId':p['external_id'].split(':',1)[1],'orders':[order]}
    elif kind in ['collection_buy','collection_sell']:
        if not preview and data.get('report_id')=='@hotwatch':raise TradeError('Et aktiesignal gælder ikke handel med hele Collectionen.')
        if p['kind']!='collection' or (kind=='collection_buy')!=(side=='BUY'):raise TradeError('Vælg en Collection og en handling, der svarer til rapportens signal.')
        with connect() as db:root=db.execute("SELECT * FROM portfolios WHERE user_id=? AND external_id=? AND source='pluto' AND active=1 AND kind='portfolio'",(user_id,p['parent_external_id'])).fetchone()
        if not root:raise TradeError('Collectionens hovedportefølje er ikke kendt. Opdatér Pluto-listen.')
        payload={'collectionId':p['external_id'].split(':',1)[1],'currency':currency}
        if kind=='collection_buy':payload.update(portfolioId=root['external_id'].split(':',1)[1],amount=positive(data.get('size')))
        else:payload['percentage']=float(positive(data.get('size'),4,'100'))
    else:raise TradeError('Vælg direkte handel eller køb/salg af en hel Collection.')
    return p,payload

def fresh_permission(client,tools,connect,user_id,p):
    # Recheck trading access at Pluto, rather than trusting a stale local flag.
    tool=tools.get('list_portfolios',{})
    if compatible(tool)!='portfolios':raise TradeError('Plutos aktuelle porteføljeadgang kan ikke kontrolleres.')
    items=normalize(decode_result(client.request('tools/call',{'name':'list_portfolios','arguments':{}}),'list_portfolios'),'portfolios')
    root_id=p['external_id'] if p['kind']=='portfolio' else p['parent_external_id']
    root=next((r for r in items if r['id']==root_id),None)
    if not root or root.get('can_trade') is not True:raise TradeError('Pluto bekræfter ikke handelsadgang til den valgte hovedportefølje.')
    if p['kind']=='collection':
        t=tools.get('list_collections',{})
        if compatible(t)!='collections':raise TradeError('Collectionens aktuelle tilknytning kan ikke kontrolleres.')
        rows=normalize(decode_result(client.request('tools/call',{'name':'list_collections','arguments':{}}),'list_collections'),'collections')
        if not any(r['id']==p['external_id'] and r['parent_external_id']==root_id for r in rows):raise TradeError('Collectionens tilknytning er ændret. Opdatér listen.')

def preflight(cl,tools,p):
    root=p['external_id'] if p['kind']=='portfolio' else p['parent_external_id']
    pid=root.split(':',1)[1]
    accounts=call(cl,tools,'get_accounts',{'portfolioId':pid})
    orders=call(cl,tools,'list_orders',{'portfolioId':pid,'statusGroup':'ACTIVE','scope':'DIRECT' if p['kind']=='portfolio' else 'COLLECTION','limit':50})
    if not isinstance(accounts,(dict,list)) or not isinstance(orders,(dict,list)):raise TradeError('Pluto har ikke returneret læsbare konto- og ordreobservationer.')
    return {'accounts':accounts,'active_orders':orders,'note':'Aktuelle Pluto-observationer. Ordrelisten er begrænset til 50 poster; den er ikke nødvendigvis fuldstændig. Kontanter, reservationer og købekraft må ikke lægges sammen eller fratrækkes igen.'}

def view(row):
    r=dict(row)
    for key in ['payload','estimate','asset','response','sell_basis']:r[key]=json.loads(r[key]) if r[key] else None
    if r['status']=='uncertain' and r['response'] and not r['intent_id']:
        reference=intent_reference(r['response'],r['payload'])
        if reference:r['status']='sent';r['intent_id']=reference;r['error']=None
    r.pop('fingerprint',None);r.pop('user_id',None)
    if r['status']!='estimated':r.pop('review_token',None)
    return r

def history(connect,user_id):
    with connect() as c:return [view(r) for r in c.execute('SELECT * FROM broker_proposals WHERE user_id=? ORDER BY id DESC LIMIT 50',(user_id,))]

def get(connect,user_id,pid):
    with connect() as c:r=c.execute('SELECT * FROM broker_proposals WHERE user_id=? AND id=?',(user_id,pid)).fetchone()
    if not r:raise TradeError('Forslaget findes ikke på din konto.')
    return r

def search(connect,user_id,query,factory=None):
    if not isinstance(query,str) or not 1<=len(query.strip())<=120:raise TradeError('Skriv et navn, ticker eller ISIN.')
    cl,tools=client(connect,user_id,factory);raw=call(cl,tools,'search_assets',{'query':query.strip(),'limit':10,'assetType':'ALL'})
    if isinstance(raw,list):rows=raw
    elif isinstance(raw,dict):
        lists=[raw[k] for k in ['assets','results','items'] if isinstance(raw.get(k),list)]
        rows=lists[0] if len(lists)==1 else []
    else:rows=[]
    choices=[]
    for r in rows:
        if not isinstance(r,dict):continue
        ids=[r[k] for k in ['id','assetId'] if isinstance(r.get(k),str) and r[k]]
        if not ids or len(set(ids))!=1:continue
        choices.append({'asset_id':ids[0],'name':str(r.get('name') or r.get('ticker') or ids[0]),'ticker':str(r.get('ticker') or ''),'isin':str(r.get('isin') or ''),'currency':str(r.get('currency') or '')})
    if not choices:raise TradeError('Ingen entydige søgeresultater i det understøttede Pluto-format. Ingen handel er oprettet.')
    return {'assets':choices}

def read_estimate(connect,user_id,p,payload,kind,factory=None):
    cl,tools=client(connect,user_id,factory);fresh_permission(cl,tools,connect,user_id,p);context=preflight(cl,tools,p);asset=None
    if kind=='direct':
        order=payload['orders'][0];asset=call(cl,tools,'get_asset',{'assetId':order['assetId']})
        node=asset.get('asset',asset) if isinstance(asset,dict) else {}
        ids=[node[k] for k in ['id','assetId'] if k in node]
        if not ids or any(v!=order['assetId'] for v in ids):raise TradeError('Plutos aktivsvar har ikke en entydig matchende identitet.')
        side=order['side'].lower()
        buy_by=asset.get('buyBy',{})
        if order['side']=='BUY' and isinstance(buy_by,dict) and buy_by.get('amount' if 'amount' in order else 'shares') is False:
            raise TradeError('Pluto understøtter ikke den valgte størrelsestype for aktivet. Vælg antal i stedet for beløb, hvis aktivet tillader det. Intet forslag er sendt.')
        types=asset.get('orderTypes',{})
        allowed=types.get(side) if isinstance(types,dict) else None
        if isinstance(allowed,list) and order['orderType'] not in allowed:
            raise TradeError('Pluto understøtter ikke den valgte ordretype for dette aktiv og denne retning. Intet forslag er sendt.')
        raw=call(cl,tools,'estimate_order',{'portfolioId':payload['portfolioId'],**order})
    else:raw=call(cl,tools,'estimate_buy_collection' if kind=='collection_buy' else 'estimate_sell_collection',payload)
    if not isinstance(raw,dict) or not raw or raw.get('error') or raw.get('success') is False:raise TradeError('Pluto har ikke returneret et anvendeligt estimat. Intet forslag er sendt.')
    return {'quote':raw,**context},asset

def preview(connect,user_id,data,factory=None):
    """Read-only probe: no report needed, no draft/review token and no proposal call."""
    p,payload=build(connect,user_id,data,preview=True)
    result,asset=read_estimate(connect,user_id,p,payload,'direct',factory)
    return {'read_only':True,'kind':'direct','portfolio_id':p['id'],'payload':payload,'estimate':result,'asset':asset,'estimated':time.time()}

def direct_sell_basis(connect,user_id,pid,asset_id,percentage,factory=None):
    """Resolve a percentage only against a fresh, complete direct holding."""
    import portfolio_data
    p=owned(connect,user_id,pid)
    if p['kind']!='portfolio':raise TradeError('Enkeltaktier sælges separat fra salg af en hel Collection.')
    try: snapshot=portfolio_data.read(connect,user_id,pid,client_factory=factory,strict_positions=True)
    except Exception as error:raise TradeError('Plutos aktuelle beholdning kunne ikke kontrolleres. Intet forslag er sendt.') from error
    if not snapshot.get('positions_complete'):raise TradeError('Plutos beholdningsliste er ufuldstændig. Intet forslag er sendt.')
    matches=[r for r in snapshot.get('positions',[]) if r.get('kind')=='holding' and r.get('asset_id')==asset_id]
    if len(matches)!=1 or matches[0].get('quantity') is None:raise TradeError('Aktivet findes ikke entydigt i den direkte beholdning. Intet forslag er sendt.')
    try:
        quantity=Decimal(str(matches[0]['quantity']));percent=Decimal(positive(percentage,4,'100'))
        if not quantity.is_finite() or quantity<=0:raise ValueError('quantity')
        shares=(quantity*percent/Decimal(100)).quantize(Decimal('0.00000001'),rounding=ROUND_DOWN)
    except Exception as error:raise TradeError('Beholdningens antal eller salgsprocent kan ikke beregnes sikkert.') from error
    if shares<=0:raise TradeError('Den valgte procent giver et for lille antal at sælge.')
    return {'asset_id':asset_id,'quantity':format(quantity,'f'),'percentage':format(percent,'f'),'shares':format(shares.normalize(),'f'),'observed':snapshot.get('observed')}

def estimate(connect,user_id,data,factory=None):
    basis=None
    if data.get('report_id')=='@manual-buy':
        if data.get('kind')!='direct' or data.get('size_mode')!='amount':raise TradeError('Et manuelt køb skal være et direkte køb for et beløb.')
        data={**data,'candidate_id':data.get('asset_id')}
    if data.get('report_id')=='@manual-sell':
        if data.get('kind')!='direct' or data.get('size_mode')!='percent':raise TradeError('Et manuelt salg skal angives som procent af en direkte beholdning.')
        data={**data,'candidate_id':data.get('asset_id')}
    if data.get('kind')=='direct' and data.get('size_mode')=='percent':
        c=signal_source(connect,user_id,str(data.get('report_id','')),str(data.get('candidate_id','')))
        if c['signal']!='SÆLG':raise TradeError('Procent af en beholdning kan kun bruges til salg.')
        try:portfolio_id=int(data.get('portfolio_id'))
        except (ValueError,TypeError):raise TradeError('Vælg et depot.')
        basis=direct_sell_basis(connect,user_id,portfolio_id,data.get('asset_id'),data.get('size'),factory)
        data={**data,'size_mode':'shares','size':basis['shares']}
    p,payload=build(connect,user_id,data);kind=data['kind'];fingerprint=hashlib.sha256(json.dumps({'report':data['report_id'],'candidate':data['candidate_id'],'kind':kind,'payload':payload},sort_keys=True).encode()).hexdigest()
    with connect() as c:
        c.execute('BEGIN IMMEDIATE')
        active=c.execute("SELECT * FROM broker_proposals WHERE user_id=? AND kind=? AND payload=? AND status IN ('sending','sent','uncertain') ORDER BY id DESC LIMIT 1",(user_id,kind,json.dumps(payload))).fetchone()
        if active:return {'proposal':view(active),'duplicate':True}
        c.execute("INSERT OR IGNORE INTO broker_proposals(user_id,fingerprint,report_id,candidate_id,kind,portfolio_id,payload,status,created) VALUES(?,?,?,?,?,?,?,'draft',?)",(user_id,fingerprint,data['report_id'],data['candidate_id'],kind,p['id'],json.dumps(payload),time.time()))
        row=c.execute('SELECT * FROM broker_proposals WHERE user_id=? AND fingerprint=?',(user_id,fingerprint)).fetchone()
        if row['status'] not in ['draft','estimated']:return {'proposal':view(row)}
        pid=row['id']
    result,asset=read_estimate(connect,user_id,p,payload,kind,factory)
    with connect() as c:
        c.execute("UPDATE broker_proposals SET status='estimated',estimated=?,review_token=?,estimate=?,asset=?,sell_basis=?,error=NULL WHERE id=? AND user_id=? AND status IN ('draft','estimated')",(time.time(),secrets.token_urlsafe(24),json.dumps(result),json.dumps(asset),json.dumps(basis) if basis else None,pid,user_id))
    return {'proposal':view(get(connect,user_id,pid))}

def intent_reference(raw,payload):
    if not isinstance(raw,dict):return None
    intent=raw.get('orderIntentId')
    if not intent and isinstance(raw.get('orderIntents'),list):
        items=raw['orderIntents'];orders=payload.get('orders') or []
        if len(items)==len(orders)==1 and isinstance(items[0],dict):
            item=items[0];order=orders[0]
            if all(item.get(k)==order.get(k) for k in ('assetId','side','orderType','timeInForce')):intent=item.get('orderIntentId')
    return intent if isinstance(intent,str) and 1<=len(intent)<=200 else None

def send(connect,user_id,data,factory=None):
    row=get(connect,user_id,int(data['id']))
    if row['status'] in ['sending','sent','uncertain']:return {'proposal':view(row),'duplicate':True}
    if row['status']!='estimated' or time.time()-row['estimated']>120:raise TradeError('Estimatet er udløbet. Hent et nyt estimat før afsendelse.')
    if data.get('confirm') is not True or not secrets.compare_digest(str(data.get('review_token','')),row['review_token'] or ''):raise TradeError('Gennemgå estimatet og bekræft afsendelsen først.')
    verify_proposal_source(connect,user_id,row);p=owned(connect,user_id,row['portfolio_id'])
    if row['sell_basis']:
        basis=json.loads(row['sell_basis']);current=direct_sell_basis(connect,user_id,row['portfolio_id'],basis['asset_id'],basis['percentage'],factory)
        if Decimal(current['quantity'])!=Decimal(basis['quantity']):raise TradeError('Beholdningens antal er ændret. Hent et nyt estimat før afsendelse.')
    cl,tools=client(connect,user_id,factory);fresh_permission(cl,tools,connect,user_id,p);preflight(cl,tools,p)
    name={'direct':'propose_orders','collection_buy':'propose_buy_collection','collection_sell':'propose_sell_collection'}[row['kind']]
    # Validate write contract before claiming the single send attempt.
    actual=tools.get(name,{})
    if actual.get('annotations',{}).get('readOnlyHint') is not False or structural(actual.get('inputSchema'))!=CONTRACT[name]['inputSchema']:raise TradeError('Plutos forslagskontrakt er ændret. Ingen afsendelse er forsøgt.')
    with connect() as c:
        c.execute('BEGIN IMMEDIATE')
        verify_proposal_source(connect,user_id,row)
        active=c.execute("SELECT * FROM broker_proposals WHERE user_id=? AND kind=? AND payload=? AND id!=? AND status IN ('sending','sent','uncertain') ORDER BY id DESC LIMIT 1",(user_id,row['kind'],row['payload'],row['id'])).fetchone()
        if active:return {'proposal':view(active),'duplicate':True}
        changed=c.execute("UPDATE broker_proposals SET status='sending',review_token=NULL WHERE id=? AND user_id=? AND status='estimated' AND review_token=? AND estimated>?",(row['id'],user_id,row['review_token'],time.time()-120)).rowcount
    if not changed:return {'proposal':view(get(connect,user_id,row['id'])),'duplicate':True}
    try:
        raw=call(cl,tools,name,json.loads(row['payload']))
        intent=intent_reference(raw,json.loads(row['payload']))
        status='sent' if intent else 'uncertain';error=None if intent else 'Pluto har svaret uden en genkendelig reference. Kontrollér i Pluto; forslaget genafsendes ikke.'
        with connect() as c:c.execute('UPDATE broker_proposals SET status=?,intent_id=?,response=?,error=? WHERE id=? AND user_id=?',(status,intent,json.dumps(raw),error,row['id'],user_id))
    except Exception:
        with connect() as c:c.execute("UPDATE broker_proposals SET status='uncertain',error=? WHERE id=? AND user_id=?",('Afsendelsens resultat er uafklaret. Kontrollér i Pluto. Ingen automatisk genafsendelse.',row['id'],user_id))
    return {'proposal':view(get(connect,user_id,row['id']))}

def check(connect,user_id,pid,factory=None):
    row=get(connect,user_id,int(pid))
    reference=view(row)['intent_id']
    if not reference:raise TradeError('Ingen sikker Pluto-reference. Kontrollér forslaget i Pluto-appen.')
    cl,tools=client(connect,user_id,factory);raw=call(cl,tools,'get_order_intent',{'orderIntentId':reference})
    # Preserve exact provider status separately. Acceptance is never a fill.
    with connect() as c:c.execute("UPDATE broker_proposals SET response=?,intent_id=?,status='sent',error=NULL WHERE id=? AND user_id=?",(json.dumps(raw),reference,row['id'],user_id))
    return {'proposal':view(get(connect,user_id,row['id']))}

def cancel_intent(connect,user_id,pid,factory=None):
    """Withdraw only an owned, unapproved proposal; never cancel an order."""
    row=get(connect,user_id,int(pid));reference=view(row)['intent_id']
    if not reference:raise TradeError('Forslaget har ingen verificeret Pluto-reference. Kontrollér det i Pluto.')
    cl,tools=client(connect,user_id,factory)
    current=call(cl,tools,'get_order_intent',{'orderIntentId':reference})
    if not isinstance(current,dict) or current.get('orderIntentId')!=reference:raise TradeError('Pluto bekræftede ikke forslagsidentiteten. Intet er annulleret.')
    status=str(current.get('status') or '').upper()
    if status in ('CANCELLED','CANCELED','DECLINED','EXPIRED','ACCEPTED','CONFIRMED'):
        with connect() as c:c.execute("UPDATE broker_proposals SET response=?,intent_id=?,status='sent',error=NULL WHERE id=? AND user_id=?",(json.dumps(current),reference,row['id'],user_id))
        return {'proposal':view(get(connect,user_id,row['id'])),'cancelled':status in ('CANCELLED','CANCELED'),'already_final':True}
    if status not in ('PENDING','WAITING','AWAITING_APPROVAL','PROPOSED'):
        raise TradeError('Pluto returnerede en ukendt forslagsstatus. Intet er annulleret; kontrollér i Pluto.')
    try:
        call(cl,tools,'cancel_order_intent',{'orderIntentId':reference})
        after=call(cl,tools,'get_order_intent',{'orderIntentId':reference})
    except Exception:
        raise TradeError('Resultatet af tilbagetrækningen er uafklaret. Kontrollér status i Pluto.')
    if not isinstance(after,dict) or after.get('orderIntentId')!=reference:raise TradeError('Plutos svar kunne ikke bekræftes. Kontrollér status i Pluto.')
    with connect() as c:c.execute("UPDATE broker_proposals SET response=?,intent_id=?,status='sent',error=NULL WHERE id=? AND user_id=?",(json.dumps(after),reference,row['id'],user_id))
    return {'proposal':view(get(connect,user_id,row['id'])),'cancelled':str(after.get('status') or '').upper() in ('CANCELLED','CANCELED')}


def summaries(connect,user_id):
    with connect() as c:rows=c.execute('SELECT * FROM broker_proposals WHERE user_id=? ORDER BY id DESC LIMIT 50',(user_id,)).fetchall()
    result=[]
    for row in rows:
        source=view(row);response=source.get('response');status=response.get('status') if isinstance(response,dict) else None
        orders=(source.get('payload') or {}).get('orders') or []
        item={k:source.get(k) for k in ('id','report_id','candidate_id','kind','portfolio_id','status','created','intent_id','error')}
        item.update(asset_id=orders[0].get('assetId') if len(orders)==1 else None,side=orders[0].get('side') if len(orders)==1 else None,expires_at=response.get('expiresAt') if isinstance(response,dict) else None)
        item['provider_status']=status if isinstance(status,str) and len(status)<=100 else None
        result.append(item)
    return result
