"""Full private OAuth + MCP + inbox flow through the Passenger WSGI adapter."""
import sys,json,os,secrets,tempfile,threading,http.client,base64,hashlib
from pathlib import Path
from urllib.parse import urlencode,urlsplit,parse_qs
from unittest.mock import patch
from wsgiref.simple_server import make_server,WSGIRequestHandler
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app
from playwright.sync_api import sync_playwright
from test_report_delivery import synthetic

BASE='https://escape.example'
CALLBACK='https://client.example/callback'
class Silent(WSGIRequestHandler):
 def log_message(self,*args):pass

def main():
 previous=app.DB
 with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'ESCAPE_MCP_ENABLED':'1','ESCAPE_PUBLIC_URL':BASE,'ESCAPE_MCP_REDIRECT_URIS':CALLBACK}):
  app.DB=directory+'/test.db'
  import passenger_wsgi
  app.init();app.create_user('browser-test-password-long')
  server=make_server('127.0.0.1',0,passenger_wsgi.application,handler_class=Silent);threading.Thread(target=server.serve_forever,daemon=True).start()
  local=f'http://127.0.0.1:{server.server_port}'
  def request(path,data=None,token=None,form=False):
   c=http.client.HTTPConnection('127.0.0.1',server.server_port)
   headers={'Content-Type':'application/x-www-form-urlencoded' if form else 'application/json'}
   if token:headers['Authorization']='Bearer '+token
   body=(urlencode(data) if form else json.dumps(data)).encode() if data is not None else None
   c.request('POST' if data is not None else 'GET',path,body,headers);r=c.getresponse();raw=r.read();result=(r.status,json.loads(raw) if raw else None,dict(r.getheaders()));c.close();return result
  try:
   status,client,_=request('/oauth/register',{'redirect_uris':[CALLBACK],'token_endpoint_auth_method':'none'});assert status==201
   verifier=secrets.token_urlsafe(48);challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
   status,_,headers=request('/oauth/authorize?'+urlencode({'client_id':client['client_id'],'redirect_uri':CALLBACK,'response_type':'code','state':'browser-test-state','resource':BASE+'/mcp','scope':'reports:read reports:write','code_challenge_method':'S256','code_challenge':challenge}));assert status==303
   with sync_playwright() as p:
    browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
    context=browser.new_context(viewport={'width':390,'height':844});page=context.new_page();errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
    # Terminate HTTPS in the test browser and forward to the actual local WSGI app.
    def proxy(route):
     parsed=urlsplit(route.request.url)
     response=route.fetch(url=local+parsed.path+('?' + parsed.query if parsed.query else ''))
     route.fulfill(response=response)
    page.route(BASE+'/**',proxy)
    page.route(CALLBACK+'**',lambda route:route.fulfill(status=200,body='OAuth client callback test'))
    page.goto(BASE+headers['Location'])
    page.locator('#login-form [name=password]').fill('browser-test-password-long');page.locator('#login-form button').click()
    page.get_by_role('button',name='Godkend rapportadgang',exact=True).wait_for()
    assert 'owner' in page.locator('#mcp-consent-body').inner_text()
    page.screenshot(path='/tmp/escape-mcp-consent-test.png',full_page=True)
    page.get_by_role('button',name='Godkend rapportadgang',exact=True).click();page.wait_for_url(CALLBACK+'**')
    query=parse_qs(urlsplit(page.url).query);assert query['state']==['browser-test-state']
    status,tokens,_=request('/oauth/token',{'grant_type':'authorization_code','client_id':client['client_id'],'redirect_uri':CALLBACK,'code':query['code'][0],'code_verifier':verifier,'resource':BASE+'/mcp'},form=True);assert status==200,(status,tokens)
    def rpc(method,params):
     status,result,_=request('/mcp',{'jsonrpc':'2.0','id':1,'method':method,'params':params},tokens['access_token']);assert status==200,(status,result);return result['result']
    assert rpc('initialize',{'protocolVersion':'2025-06-18'})['serverInfo']['name']=='escape-reports'
    advertised=rpc('tools/list',{})['tools'];assert len(advertised)==3
    send_schema=next(t['inputSchema'] for t in advertised if t['name']=='send_report');assert send_schema['properties']['schema_version']['enum']==[1,2]
    sample=json.loads((Path(__file__).resolve().parents[1]/'examples/report-ingest-test.json').read_text())
    result=rpc('tools/call',{'name':'send_report','arguments':sample});assert not result['isError']
    saved=rpc('tools/call',{'name':'get_latest_report','arguments':{'is_test':True}})['structuredContent']['report'];assert saved['data']==sample
    assert rpc('tools/call',{'name':'get_latest_report','arguments':{}})['structuredContent']['report'] is None
    v2=json.loads((Path(__file__).resolve().parents[1]/'examples/report-v2-test.json').read_text())
    preflight=rpc('tools/call',{'name':'validate_report','arguments':v2});assert not preflight['isError'];assert preflight['structuredContent']['valid']
    result=rpc('tools/call',{'name':'send_report','arguments':v2});assert not result['isError']
    latest=rpc('tools/call',{'name':'get_latest_report','arguments':{'is_test':True}})['structuredContent']['report'];assert latest['data']==v2
    page.goto(BASE+'/');page.locator('#content .hero').wait_for();page.locator('nav [data-view=reports]').click()
    page.locator('#load-ingested-report').click();page.get_by_text('Ingen rapport modtaget',exact=True).wait_for()
    page.locator('#report-mode').select_option('true');page.locator('#load-ingested-report').click();page.get_by_text('TESTDATA · ingen rigtige porteføljeværdier',exact=True).wait_for()
    assert '1.000,00' in page.locator('#ingested-report').inner_text()
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.screenshot(path='/tmp/escape-mcp-report-test.png',full_page=True)
    # Same real Passenger adapter and OAuth grant, isolated synthetic production report.
    production=synthetic(False)
    with app.connect() as c:original=[tuple(r) for r in c.execute('SELECT id,payload,digest FROM ingested_reports ORDER BY id')]
    assert rpc('tools/call',{'name':'validate_report','arguments':production})['structuredContent']['valid']
    saved_production=rpc('tools/call',{'name':'send_report','arguments':production});assert not saved_production['isError'];assert saved_production['structuredContent']['counts']=={'portfolios':2,'positions':11,'orders':15,'candidates':12,'sources':11,'regions':4}
    assert rpc('tools/call',{'name':'get_latest_report','arguments':{'is_test':False}})['structuredContent']['report']['data']==production
    assert rpc('tools/call',{'name':'send_report','arguments':production})['structuredContent']['duplicate']
    page.locator('#report-mode').select_option('false');page.get_by_text('SYNTHETISK INTEGRATIONSTEST – ingen investeringsrapport',exact=True).wait_for()
    with app.connect() as c:assert [tuple(r) for r in c.execute('SELECT id,payload,digest FROM ingested_reports ORDER BY id LIMIT 2')]==original
    assert not errors,errors
    browser.close()
   with app.connect() as c:
    assert c.execute('SELECT COUNT(*) FROM ingested_reports').fetchone()[0]==3
    assert c.execute('SELECT COUNT(*) FROM proposals').fetchone()[0]==0
   print('PASS: WSGI → OAuth PKCE → browser login/consent → token → MCP tools/list v1+v2 → send/read both versions → separate test inbox and full 12-candidate synthetic production delivery/readback/idempotency at 390px; original reports unchanged; no broker calls')
  finally:server.shutdown();server.server_close();app.DB=previous
if __name__=='__main__':main()
