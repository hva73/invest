"""Synthetic browser -> owner approval -> guarded bridge adapter, never a deployment."""
import os,sys,threading,tempfile,time
from pathlib import Path
sys.path[:0]=[os.path.dirname(os.path.dirname(os.path.abspath(__file__))),os.path.dirname(os.path.abspath(__file__)),os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),'tools')]
import app,release_approval,nordicway_app_release
from test_portfolio_value_chart import PortfolioValueChart
from playwright.sync_api import sync_playwright,expect

case=PortfolioValueChart();case.setUp()
bridge=tempfile.TemporaryDirectory();Path(bridge.name).chmod(0o700)
key=Path(bridge.name)/'owner-approval-key';key.write_bytes(b'k'*32);key.chmod(0o600)
calls=[];ready=threading.Event();results=[]
def runner(sha,token,owner_request):
 calls.append((sha,owner_request))
 return {'operation':'deploy','status':'ok','stage':'complete','recovery_required':False,'service_restored':True}
def stage():
 results.append(nordicway_app_release.run(app.connect,'a'*40,'Test: mobil og data','synthetic-token-123',bridge.name,
  runner=runner,create_proof=lambda sha,key:('proof',sha),notify=lambda uid:ready.set(),lifetime=30))
worker=threading.Thread(target=stage,daemon=True);worker.start()
assert ready.wait(5)
server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
threading.Thread(target=server.serve_forever,daemon=True).start()
try:
 with sync_playwright() as p:
  browser=p.chromium.launch(executable_path=None if os.getenv('ESCAPE_PLAYWRIGHT_MANAGED') else '/usr/bin/chromium',headless=True,args=['--no-sandbox'])
  page=browser.new_page(viewport={'width':390,'height':844})
  page.goto(f'http://127.0.0.1:{server.server_port}/?release_approval=1')
  page.locator('#login-form [name=password]').fill('test-password-long-enough')
  page.locator('#login-form button').click()
  dialog=page.locator('#release-approval-dialog')
  expect(dialog).to_be_visible();expect(dialog).to_contain_text('a'*40);expect(dialog).to_contain_text('Test: mobil og data')
  assert calls==[], 'Runner must not start before owner approval'
  dialog.locator('[data-release-confirm]').click()
  expect(dialog).not_to_be_visible()
  worker.join(timeout=5)
  assert not worker.is_alive() and results[0]['status']=='completed'
  assert calls==[('a'*40,('proof','a'*40))],calls
  page.locator('#release-approval-open').click()
  expect(dialog.locator('[data-release-status]')).to_have_text('Installationen er gennemført. Kontrol af app og data følger.')
  browser.close()
 print('PASS: owner login -> exact SHA approval -> simulated runner once -> persistent status; no deployment')
finally:
 server.shutdown();server.server_close();worker.join(timeout=1);bridge.cleanup();case.tearDown()
