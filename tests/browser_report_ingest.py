"""Manual HTTP-to-browser integration test using synthetic data and temporary DB."""
import sys,json,os,secrets,tempfile,threading,http.client
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app
from playwright.sync_api import sync_playwright

def main():
 previous=app.DB
 with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'ESCAPE_REPORT_INGEST_KEY':secrets.token_urlsafe(48),'ESCAPE_REPORT_INGEST_USER':'owner'}):
  app.DB=directory+'/test.db';app.init();app.create_user('browser-test-password-long')
  server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
  data=json.loads((Path(__file__).resolve().parents[1]/'examples/report-ingest-test.json').read_text())
  def post(value,auth=True,content_type='application/json'):
   c=http.client.HTTPConnection('127.0.0.1',server.server_port)
   headers={'Content-Type':content_type}
   if auth:headers['Authorization']='Bearer '+os.environ['ESCAPE_REPORT_INGEST_KEY']
   c.request('POST','/api/reports/ingest',value,headers);r=c.getresponse();result=(r.status,json.loads(r.read()));c.close();return result
  try:
   assert post(json.dumps(data),False)[0]==401
   assert post(json.dumps(data),content_type='text/plain')[0]==415
   assert post('x'*16385)[0]==413
   assert post('{"report_id":"one","report_id":"two"}')[0]==400
   assert post(json.dumps(data))[0]==201
   status,duplicate=post(json.dumps(data));assert status==200 and duplicate['duplicate']
   conflict=dict(data,source='Different source');assert post(json.dumps(conflict))[0]==409
   with app.connect() as c:
    assert c.execute('SELECT COUNT(*) FROM ingested_reports').fetchone()[0]==1
    assert c.execute('SELECT COUNT(*) FROM proposals').fetchone()[0]==0
   import report_ingest
   assert report_ingest.latest(app.connect,999)['report'] is None
   with sync_playwright() as p:
    browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
    page=browser.new_page(viewport={'width':390,'height':844});errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
    page.goto(f'http://127.0.0.1:{server.server_port}')
    page.locator('#login-form [name=password]').fill('browser-test-password-long');page.locator('#login-form button').click();page.locator('#content .hero').wait_for()
    page.locator('nav [data-view=reports]').click();page.locator('[data-view=inbox]').click();page.locator('#report-mode').select_option('true');page.locator('#load-ingested-report').click()
    page.get_by_text('TESTDATA · ingen rigtige porteføljeværdier',exact=True).wait_for()
    for text in ['Testportefølje','Testmarked','Testkandidat','TEST-ORDER-001','1.000,00']:
     assert text in page.locator('#ingested-report').inner_text(),text
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.screenshot(path='/tmp/escape-report-ingest-test.png',full_page=True)
    assert not errors,errors
    browser.close()
   print('PASS: authenticated HTTP ingest → temporary SQLite → mobile report inbox; replay, conflict, auth, size, isolation and no proposals checked')
  finally:server.shutdown();server.server_close();app.DB=previous
if __name__=='__main__':main()
