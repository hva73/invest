import io,json,unittest,urllib.error
from pluto import discover,MCP_URL,NoRedirect
class Response(io.BytesIO):
 status=200
class Opener:
 def __init__(self,payload):self.payload=payload;self.urls=[]
 def open(self,request,timeout):
  self.urls.append(request.full_url)
  if isinstance(self.payload,Exception):raise self.payload
  return Response(json.dumps(self.payload).encode())
class Discovery(unittest.TestCase):
 def test_valid_metadata_never_connects_or_follows_issuer(self):
  opener=Opener({'resource':MCP_URL,'authorization_servers':['https://auth.example.org']})
  result=discover(opener);self.assertTrue(result['discovery_valid']);self.assertFalse(result['connected']);self.assertEqual(result['authorization_hosts'],['auth.example.org']);self.assertEqual(len(opener.urls),1)
 def test_wrong_resource_and_bad_issuer_rejected(self):
  for payload in [{'resource':'https://other.example','authorization_servers':['https://auth.example']},{'resource':MCP_URL,'authorization_servers':['http://localhost']},{'resource':MCP_URL,'authorization_servers':['https://user:secret@example.org']}]:
   self.assertFalse(discover(Opener(payload))['discovery_valid'])
 def test_network_denial_is_not_connected(self):
  result=discover(Opener(urllib.error.HTTPError(MCP_URL,403,'Forbidden',{},None)));self.assertFalse(result['connected']);self.assertFalse(result['discovery_valid']);self.assertEqual(result['attempts'][0]['http_status'],403)
 def test_no_redirects(self):self.assertIsNone(NoRedirect().redirect_request(None,None,302,'',{},'http://localhost'))
