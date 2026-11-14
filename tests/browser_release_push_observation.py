"""Authenticated owner UI, synthetic delivery counts; never sends a push."""
import sys,threading
sys.path[:0]=['.','tests']
import app,release_approval,web_push
from test_portfolio_value_chart import PortfolioValueChart
from playwright.sync_api import sync_playwright,expect

case=PortfolioValueChart();case.setUp()
candidate=release_approval.prepare(app.connect,'a'*40,'Testopdatering',1)
assert web_push.notify_release_ready(app.connect,1)=={'sent':0,'failed':0}
server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
threading.Thread(target=server.serve_forever,daemon=True).start()
try:
 with sync_playwright() as p:
  browser=p.chromium.launch(headless=True)
  for width in (390,1280):
   page=browser.new_page(viewport={'width':width,'height':850},is_mobile=width<700,has_touch=width<700)
   page.goto(f'http://127.0.0.1:{server.server_port}/?release_approval=1')
   page.locator('#login-form [name=password]').fill('test-password-long-enough');page.locator('#login-form button').click()
   dialog=page.locator('#release-approval-dialog');expect(dialog).to_be_visible()
   expect(dialog).to_contain_text('Ingen enheder kunne modtage notifikationen')
   expect(dialog.locator('[data-release-confirm]')).to_be_visible()
   page.close()
  browser.close()
 print('PASS: authenticated mobile and desktop show no-device status and approval remains available')
finally:
 server.shutdown();server.server_close();case.tearDown()
