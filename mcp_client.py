"""Fixed-provider MCP client. Only explicit portfolio/collection list tools may run."""
import json,time,urllib.request
from pluto import MCP_URL,NoRedirect
import oauth

class MCP:
    def __init__(self,token):self.token=token;self.session=None;self.version=None;self.counter=0
    def request(self,method,params=None,notification=False):
        self.counter+=1;identifier=self.counter
        payload={'jsonrpc':'2.0','method':method}
        if params is not None:payload['params']=params
        if not notification:payload['id']=identifier
        headers={'Authorization':'Bearer '+self.token,'Content-Type':'application/json','Accept':'application/json, text/event-stream'}
        if self.session:headers['Mcp-Session-Id']=self.session
        if self.version:headers['MCP-Protocol-Version']=self.version
        req=urllib.request.Request(MCP_URL,data=json.dumps(payload).encode(),headers=headers)
        with urllib.request.build_opener(NoRedirect()).open(req,timeout=10) as response:
            session=response.headers.get('Mcp-Session-Id')
            if session:
                if len(session)>1024 or any(ord(c)<32 or ord(c)>126 for c in session):raise ValueError('Invalid MCP session')
                self.session=session
            if notification:return None
            if response.headers.get('Content-Type','').startswith('text/event-stream'):
                size=0;lines=[];data=None
                while size<=1048576:
                    line=response.readline(65537);size+=len(line)
                    if not line:break
                    if line.startswith(b'data:'):lines.append(line[5:].strip())
                    if not line.strip() and lines:
                        data=json.loads(b'\n'.join(lines));lines=[]
                        if data.get('id')==identifier:break
                else:raise ValueError('Oversized MCP response')
                if not isinstance(data,dict) or data.get('id')!=identifier:raise ValueError('Missing MCP response')
            else:
                raw=response.read(1048577)
                if len(raw)>1048576:raise ValueError('Oversized MCP response')
                data=json.loads(raw)
            if not isinstance(data,dict) or data.get('id')!=identifier or 'error' in data or 'result' not in data:raise ValueError('MCP request failed')
            return data['result']
    def tools(self):
        initial=self.request('initialize',{'protocolVersion':'2025-06-18','capabilities':{},'clientInfo':{'name':'escape','version':'0.5'}})
        self.version=initial.get('protocolVersion')
        if self.version not in ['2024-11-05','2025-03-26','2025-06-18']:raise ValueError('Unsupported MCP protocol')
        self.request('notifications/initialized',notification=True)
        tools=[];cursor=None;seen=set()
        for _ in range(10):
            result=self.request('tools/list',{'cursor':cursor} if cursor else {})
            page=result.get('tools')
            if not isinstance(page,list):raise ValueError('Invalid tools listing')
            for tool in page:
                if not isinstance(tool,dict) or not isinstance(tool.get('name'),str):raise ValueError('Invalid tool')
                tools.append({k:tool[k] for k in ['name','description','inputSchema','outputSchema','annotations'] if k in tool})
            cursor=result.get('nextCursor')
            if not cursor:return tools
            if not isinstance(cursor,str) or cursor in seen:raise ValueError('Invalid pagination')
            seen.add(cursor)
        raise ValueError('Incomplete tool listing')

def catalog(connect,user_id):
    token=oauth.access_token(connect,user_id)
    return {'tools':MCP(token).tools(),'message':'Kun værktøjsbeskrivelser er hentet. Ingen værktøjer er udført, og ingen handler er oprettet.'}

# Names and argument contracts observed in the user's actual Pluto tools/list.
# readOnlyHint alone is insufficient: some Pluto draft editors also advertise it.
READ_LISTS={'list_portfolios':'portfolios','list_collections':'collections'}

class PortfolioFormatError(oauth.SetupRequired):pass

def shape(value):
    # Report field names/types only. Never include account IDs, names or token values.
    import re
    if isinstance(value,list):return 'array; første post: '+(shape(value[0]) if value else 'tom')
    if isinstance(value,dict):return ', '.join(k+':'+type(v).__name__ for k,v in list(value.items())[:25] if isinstance(k,str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,39}',k))
    return type(value).__name__

def compatible(tool):
    root=READ_LISTS.get(tool.get('name'))
    if not root or tool.get('annotations',{}).get('readOnlyHint') is not True:return None
    inputs=tool.get('inputSchema',{})
    if inputs.get('type')!='object' or inputs.get('required'):return None
    return root

def decode_result(response,tool_name):
    if not isinstance(response,dict) or response.get('isError'):
        raise PortfolioFormatError(tool_name+': Pluto returnerede en fejl; listen er bevaret')
    if response.get('structuredContent') is not None:return response['structuredContent']
    blocks=response.get('content')
    if isinstance(blocks,list):
        texts=[block.get('text') for block in blocks if isinstance(block,dict) and block.get('type')=='text' and isinstance(block.get('text'),str)]
        if texts:
            try:return json.loads(''.join(texts))
            except (ValueError,TypeError):pass
    raise PortfolioFormatError(tool_name+': svaret indeholder ikke understøttet JSON. Ingen data er ændret')

def one_field(item,names):
    values=[item[name] for name in names if name in item and item[name] is not None]
    if not values:return None
    if any(value!=values[0] for value in values):raise PortfolioFormatError('Pluto returnerede modstridende identitetsfelter; listen er bevaret')
    return values[0]

def normalize(data,root):
    original=data
    # Only explicit JSON list envelopes; never recursively search arbitrary data.
    if isinstance(data,dict):
        if data.get('nextToken') or data.get('nextCursor') or data.get('hasMore') is True:
            raise PortfolioFormatError('Pluto returnerede en delvis liste; den eksisterende liste er bevaret')
        arrays=[data[key] for key in [root,'items','data'] if isinstance(data.get(key),list)]
        if len(arrays)!=1:
            raise PortfolioFormatError('Ukendt '+root+'-format (felter og typer): '+shape(data))
        records=arrays[0]
        if 'totalCount' in data and (not isinstance(data['totalCount'],int) or data['totalCount']!=len(records)):
            raise PortfolioFormatError('Pluto-listens antal stemmer ikke; eksisterende data er bevaret')
    elif isinstance(data,list):records=data
    else:raise PortfolioFormatError('Ukendt '+root+'-format: '+shape(data))
    normalized=[];seen=set()
    for item in records:
        if not isinstance(item,dict):raise PortfolioFormatError('Ugyldig '+root+'-post: '+shape(item))
        specific='portfolioId' if root=='portfolios' else 'collectionId'
        identifier=one_field(item,[specific,'id'])
        name=one_field(item,['name','portfolioName' if root=='portfolios' else 'collectionName'])
        if not isinstance(identifier,str) or not identifier or identifier in seen:
            raise PortfolioFormatError('Manglende/gentaget '+specific+'; felter og typer: '+shape(item))
        if not isinstance(name,str) or not name.strip():
            raise PortfolioFormatError('Manglende navn i '+root+'; felter og typer: '+shape(item))
        seen.add(identifier)
        parent=item.get('portfolioId') if root=='collections' else None
        if parent is not None and (not isinstance(parent,str) or not parent):raise PortfolioFormatError('Ugyldig Collection-tilknytning')
        permission=item.get('canTrade')
        if permission is not None and not isinstance(permission,bool):raise PortfolioFormatError('Ugyldig Pluto-adgangsstatus')
        normalized.append({'id':root+':'+identifier,'name':name.strip(),'kind':'collection' if root=='collections' else 'portfolio','parent_external_id':'portfolios:'+parent if parent else None,'can_trade':permission})
    return normalized

def read_portfolios(connect,user_id,client_factory=None):
    token=oauth.access_token(connect,user_id)
    client=(client_factory or MCP)(token);tools=client.tools();by_root={}
    for tool in sorted(tools,key=lambda t:(not t['name'].startswith('list_'),t['name'])):
        root=compatible(tool)
        if root:by_root.setdefault(root,tool)
    selected=[(tool,root) for root,tool in by_root.items()]
    if not selected:raise oauth.SetupRequired('Plutos værktøjskontrakt kræver en tilpasning. Klik Undersøg Plutos porteføljeværktøjer, og del beskrivelserne — aldrig tokens.')
    with connect() as c:previous=[r['external_id'] for r in c.execute("SELECT external_id FROM portfolios WHERE user_id=? AND source='pluto' AND active=1",(user_id,))]
    if any(not value or value.split(':',1)[0] not in by_root for value in previous):
        raise oauth.SetupRequired('Porteføljeadgangen er ændret hos Pluto; eksisterende liste er bevaret til gennemgang')
    items=[]
    for tool,root in selected:
        response=client.request('tools/call',{'name':tool['name'],'arguments':{}})
        items.extend(normalize(decode_result(response,tool['name']),root))
    return items
