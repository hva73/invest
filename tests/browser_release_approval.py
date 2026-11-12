"""Synthetic browser exercise: no push delivery and no installation."""
import os,sys,threading
sys.path[:0]=[os.path.dirname(os.path.dirname(os.path.abspath(__file__))),os.path.dirname(os.path.abspath(__file__))]
import app,release_approval
from test_portfolio_value_chart import PortfolioValueChart
from playwright.sync_api import sync_playwright,expect

case=PortfolioValueChart();case.setUp()
candidate=release_approval.prepare(app.connect,'a'*40,'Test: mobil og data',1)
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
  expect(dialog).to_be_visible();expect(dialog).to_contain_text(candidate['sha']);expect(dialog).to_contain_text('Test: mobil og data')
  dialog.locator('[data-release-confirm]').click()
  expect(dialog.locator('[data-release-status]')).to_have_text('Godkendelsen er registreret. Installationen er ikke startet.')
  browser.close()
 print('PASS: expired-login entry, exact version and synthetic owner approval; no deployment')
finally:
 server.shutdown();server.server_close();case.tearDown()
