import os,sys,threading
from datetime import datetime,timezone,timedelta
sys.path[:0]=[os.path.dirname(os.path.dirname(os.path.abspath(__file__))),os.path.dirname(os.path.abspath(__file__))]
import app
from test_portfolio_value_chart import PortfolioValueChart
from playwright.sync_api import sync_playwright
case=PortfolioValueChart();case.setUp();now=datetime.now(timezone.utc)
case.save(case.root,'1000',now-timedelta(hours=2),result='-20');case.save(case.root,'1020',now,result='-10')
server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
try:
 with sync_playwright() as p:
  browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox']);page=browser.new_page(viewport={'width':390,'height':844});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
  page.goto(f'http://127.0.0.1:{server.server_port}');page.locator('#login-form [name=password]').fill('test-password-long-enough');page.locator('#login-form button').click();page.locator('nav [data-view=overview]').wait_for()
  targets=page.locator('nav [data-view]').evaluate_all('(x)=>x.map(n=>n.dataset.view)')
  for width in (320,390,768,1440):
   page.set_viewport_size({'width':width,'height':900})
   for target in targets:
    page.locator(f'nav [data-view="{target}"]').click()
    page.wait_for_timeout(150)
    overflow=page.evaluate('({doc:document.documentElement.scrollWidth,win:innerWidth})')
    assert overflow['doc']<=overflow['win']+1, (width,target,overflow)
    notice=page.locator('#notice').inner_text()
    assert 'Cannot read properties' not in notice, (width,target,notice)
  assert not errors, errors
  print('NAVIGATION',','.join(targets));print('JAVASCRIPT',errors)
  browser.close()
finally:server.shutdown();server.server_close();case.tearDown()
