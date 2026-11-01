"""Fixed-provider MCP discovery only. Never invokes tools/call."""
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
    with connect() as c:row=c.execute('SELECT payload,expires FROM oauth_tokens WHERE user_id=?',(user_id,)).fetchone()
    if not row or row['expires']<=time.time():raise oauth.SetupRequired('Log ind hos Pluto igen før værktøjsopslag')
    token=oauth.unseal(user_id,row['payload'])['token']['access_token']
    return {'tools':MCP(token).tools(),'message':'Kun værktøjsbeskrivelser er hentet. Ingen værktøjer er udført, og ingen handler er oprettet.'}

# Only these list operations, explicitly advertised read-only and with a fully
# recognized output contract, may be called. Unknown schemas fail closed.
READ_LISTS={'list_portfolios':'portfolios','get_portfolios':'portfolios','list_collections':'collections','get_collections':'collections'}

def compatible(tool):
    root=READ_LISTS.get(tool.get('name'))
    if not root or tool.get('annotations',{}).get('readOnlyHint') is not True:return None
    inputs=tool.get('inputSchema',{})
    if inputs.get('required'):return None
    schema=tool.get('outputSchema',{})
    props=schema.get('properties',{})
    if schema.get('type')!='object' or set(props)!={root} or root not in schema.get('required',[]):return None
    array=props[root];item=array.get('items',{});fields=item.get('properties',{})
    if array.get('type')!='array' or item.get('type')!='object' or not {'id','name'}.issubset(item.get('required',[])):return None
    if fields.get('id',{}).get('type')!='string' or fields.get('name',{}).get('type')!='string':return None
    return root

def read_portfolios(connect,user_id,client_factory=None):
    with connect() as c:row=c.execute('SELECT payload,expires FROM oauth_tokens WHERE user_id=?',(user_id,)).fetchone()
    if not row or row['expires']<=time.time():raise oauth.SetupRequired('Log ind hos Pluto igen før porteføljeopslag')
    token=oauth.unseal(user_id,row['payload'])['token']['access_token']
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
        if response.get('isError'):raise ValueError('Pluto returned an error')
        data=response.get('structuredContent')
        if not isinstance(data,dict) or set(data)!={root} or not isinstance(data[root],list):raise ValueError('Unsupported or partial portfolio output')
        for item in data[root]:
            if not isinstance(item,dict) or not isinstance(item.get('id'),str) or not item['id'] or not isinstance(item.get('name'),str) or not item['name'].strip():raise ValueError('Invalid portfolio record')
            items.append({'id':root+':'+item['id'],'name':item['name']})
    return items
