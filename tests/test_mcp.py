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
     result=mcp_client.read_portfolios(app.connect,1,Client)
     self.assertEqual(result[0]['id'],'collections:abc');self.assertEqual(result[0]['name'],'Any user name');self.assertEqual(result[0]['kind'],'collection')
   finally:app.DB=previous

 def test_actual_advertised_inputs_without_output_schema(self):
  from mcp_client import compatible
  portfolios={'name':'list_portfolios','inputSchema':{'type':'object','properties':{}},'annotations':{'readOnlyHint':True,'openWorldHint':False}}
  collections={'name':'list_collections','inputSchema':{'type':'object','properties':{'portfolioId':{'type':'string'}}},'annotations':{'readOnlyHint':True,'openWorldHint':False}}
  self.assertEqual(compatible(portfolios),'portfolios');self.assertEqual(compatible(collections),'collections')
  self.assertIsNone(compatible({**collections,'name':'edit_collection_weights'}))
  self.assertIsNone(compatible({**collections,'name':'create_collection'}))
 def test_text_json_and_identity_variants(self):
  from mcp_client import normalize,decode_result
  # Synthetic response fixture; real account payloads are never saved to tests.
  raw={'content':[{'type':'text','text':json.dumps([{'collectionId':'test-collection','name':'New dynamic name','portfolioId':'test-account','canTrade':False}])}]}
  items=normalize(decode_result(raw,'list_collections'),'collections')
  self.assertEqual(items[0]['parent_external_id'],'portfolios:test-account');self.assertFalse(items[0]['can_trade'])
  self.assertEqual(normalize({'portfolios':[{'id':'test','name':'Anything'}],'totalCount':1},'portfolios')[0]['id'],'portfolios:test')
 def test_partial_ambiguous_and_error_results_rejected(self):
  from mcp_client import normalize,decode_result,PortfolioFormatError
  bad=[{'portfolios':[],'nextToken':'more'},{'portfolios':[],'totalCount':1},{'portfolios':[],'items':[]},[{'id':'a','portfolioId':'b','name':'A'}],[{'id':'a','name':'A'},{'id':'a','name':'B'}]]
  for data in bad:
   with self.assertRaises(PortfolioFormatError):normalize(data,'portfolios')
  with self.assertRaises(PortfolioFormatError):decode_result({'isError':True,'content':[{'type':'text','text':'secret'}]},'list_portfolios')
 def test_unknown_shape_does_not_disclose_values(self):
  from mcp_client import normalize,PortfolioFormatError
  with self.assertRaises(PortfolioFormatError) as result:normalize([{'customId':'private-account-id','customName':'private-name'}],'portfolios')
  message=str(result.exception);self.assertIn('customId',message);self.assertNotIn('private-account-id',message);self.assertNotIn('private-name',message)
