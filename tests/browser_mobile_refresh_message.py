import sys,threading
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
import app
from test_portfolio_value_chart import PortfolioValueChart
from playwright.sync_api import sync_playwright,expect
case=PortfolioValueChart();case.setUp()
server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
try:
 with sync_playwright() as pw:
  browser=pw.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox']);page=browser.new_page(viewport={'width':390,'height':844},is_mobile=True,has_touch=True);errors=[];page.on('pageerror',lambda e:errors.append(str(e)));bad=[False]
  page.route('**/api/portfolios/sync',lambda r:r.fulfill(json={'ok':True}))
  page.route('**/api/portfolios/data',lambda r:r.fulfill(json={'ok':True,'complete':not bad[0],'errors':['Syntetisk fejl'] if bad[0] else []}))
  page.goto(f'http://127.0.0.1:{server.server_port}');page.locator('#login-form [name=password]').fill('test-password-long-enough');page.locator('#login-form button').click();expect(page.locator('#profile-open')).to_be_visible()
  page.evaluate('state.connection.has_tokens=true');page.evaluate('finishPull()')
  expect(page.locator('#pull-refresh-status')).to_be_visible();assert page.locator('#refresh-status').is_hidden();expect(page.locator('#pull-refresh-status')).to_be_hidden(timeout=5000);expect(page.locator('#refresh-status')).to_be_hidden(timeout=5000)
  bad[0]=True;page.evaluate('state.connection.has_tokens=true');page.locator('#refresh-current').click();expect(page.locator('#refresh-status[data-kind=warning]')).to_be_visible();page.wait_for_timeout(3500);expect(page.locator('#refresh-status[data-kind=warning]')).to_be_visible();assert 'Syntetisk fejl' in page.locator('#refresh-status').inner_text()
  assert not errors,errors;browser.close();print('PASS: one transient pull message, success clears, warning stays readable')
finally:server.shutdown();server.server_close();case.tearDown()
