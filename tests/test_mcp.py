import io,json,unittest
from unittest.mock import patch
from mcp_client import MCP
class Response(io.BytesIO):
 def __init__(self,data,sse=False):
  raw=json.dumps(data).encode();super().__init__(b'data: '+raw+b'\n\n' if sse else raw);self.headers={'Content-Type':'text/event-stream' if sse else 'application/json','Mcp-Session-Id':'test-mcp-session'}
class Catalog(unittest.TestCase):
 def test_only_initialization_and_listing(self):
  methods=[]
  class Opener:
   def open(self,request,timeout):
    data=json.loads(request.data);methods.append(data['method'])
    if data['method']=='initialize':return Response({'id':data['id'],'result':{'protocolVersion':'2025-06-18'}})
    if data['method']=='notifications/initialized':return Response({})
    if data['method']=='tools/list':
     assert request.get_header('Mcp-session-id')=='test-mcp-session'
     return Response({'id':data['id'],'result':{'tools':[{'name':'test_tool','inputSchema':{'type':'object'}}]}},True)
    raise AssertionError('No tool execution permitted')
  with patch('mcp_client.urllib.request.build_opener',return_value=Opener()):result=MCP('test-token').tools()
  self.assertEqual(result[0]['name'],'test_tool');self.assertEqual(methods,['initialize','notifications/initialized','tools/list'])
 def test_contract_gate_and_live_records(self):
  import mcp_client,tempfile,app,oauth,time
  from pathlib import Path
  from unittest.mock import patch
  schema={'type':'object','required':['collections'],'properties':{'collections':{'type':'array','items':{'type':'object','required':['id','name'],'properties':{'id':{'type':'string'},'name':{'type':'string'}}}}}}
  tool={'name':'list_collections','annotations':{'readOnlyHint':True},'inputSchema':{'type':'object'},'outputSchema':schema}
  self.assertEqual(mcp_client.compatible(tool),'collections')
  self.assertIsNone(mcp_client.compatible({**tool,'name':'place_order'}))
  self.assertIsNone(mcp_client.compatible({**tool,'annotations':{}}))
  self.assertIsNone(mcp_client.compatible({**tool,'inputSchema':{'required':['account_id']}}))
  previous=app.DB
  with tempfile.TemporaryDirectory() as directory:
   try:
    app.DB=directory+'/mcp.db';app.init();app.create_user('a-test-password-long')
    with patch.dict('os.environ',{'ESCAPE_TOKEN_KEY_FILE':directory+'/token.key'}):
     oauth.setup_key()
     with app.connect() as c:c.execute('INSERT INTO oauth_tokens VALUES(?,?,?,?)',(1,oauth.seal(1,{'token':{'access_token':'test'}}),time.time()+100,time.time()))
     class Client:
      def __init__(self,token):pass
      def tools(self):return [tool]
      def request(self,method,params):
       assert method=='tools/call' and params=={'name':'list_collections','arguments':{}}
       return {'structuredContent':{'collections':[{'id':'abc','name':'Any user name'}]}}
     self.assertEqual(mcp_client.read_portfolios(app.connect,1,Client),[{'id':'collections:abc','name':'Any user name'}])
   finally:app.DB=previous
