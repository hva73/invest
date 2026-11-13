import sys,time,json,threading,os
sys.path[:0]=['.', 'tests']
from unittest.mock import patch
from datetime import datetime,timezone
import app,sector_intelligence as sector
from test_portfolio_value_chart import PortfolioValueChart
from playwright.sync_api import sync_playwright,expect
case=PortfolioValueChart();case.setUp()
now=time.time();today=datetime.now(timezone.utc).date().isoformat();series=json.dumps([{'date':'2026-10-01','close':100},{'date':today,'close':110}]);series_extra=json.dumps([{'date':'2026-10-01','close':100},{'date':'2026-10-18','close':105},{'date':today,'close':110}])
with app.connect() as c:
 for symbol,region,sectorname,src in [('XLU.US','USA','Forsyning','x'),('XLY.US','USA','Forbrug','x'),('EXH4.XETRA','Europa','Industri','x'),('IXN.US','Globalt','Teknologi','x')]:
  c.execute('INSERT INTO sector_benchmarks(symbol,region,sector,status,updated,next_attempt,proof_source,currency) VALUES(?,?,?,?,?,?,?,?)',(symbol,region,sectorname,'VERIFIED',now,now+86400,src,'USD'))
  c.execute('INSERT INTO sector_market(symbol,region,sector,payload,status,updated,next_attempt,price_basis) VALUES(?,?,?,?,?,?,?,?)',(symbol,region,sectorname,series_extra if symbol=='XLY.US' else series,'OK',now,now+86400,'close'))
 c.execute("UPDATE sector_benchmarks SET name=?,exchange='XETRA' WHERE symbol='EXH4.XETRA'",('iShares STOXX Europe 600 Industrial Goods & Services UCITS ETF (DE)',))
server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
try:
 with sync_playwright() as p:
  browser=p.chromium.launch(**({} if os.environ.get('ESCAPE_PLAYWRIGHT_MANAGED') else {'executable_path':'/usr/bin/chromium'}),headless=True,args=['--no-sandbox']);page=browser.new_page(viewport={'width':1440,'height':900},has_touch=True);errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
  page.add_init_script('Date.now = (() => { const actual = Date.now; return () => actual() + 3600000; })();');page.goto(f'http://127.0.0.1:{server.server_port}');page.locator('#login-form [name=password]').fill('test-password-long-enough');page.locator('#login-form button').click();page.locator('nav [data-view=sectors]').click();page.locator('.sector-heat[data-sector-market="XLU.US"]').wait_for()
  rotation=page.locator('.si-rotation-chart');expect(rotation).to_be_visible();assert rotation.locator('.dash-chart-point').count()==5
  rotation.scroll_into_view_if_needed();box=rotation.bounding_box();page.mouse.move(box['x']+box['width']*.5,box['y']+box['height']*.5);expect(rotation.locator('xpath=..').locator('.dash-chart-tooltip')).to_be_visible()
  page.set_viewport_size({'width':390,'height':900});rotation.scroll_into_view_if_needed();box=rotation.bounding_box();page.touchscreen.tap(box['x']+box['width']*.5,box['y']+box['height']*.5);tip=rotation.locator('xpath=..').locator('.dash-chart-tooltip');expect(tip).to_be_visible();expect(tip.locator('[data-chart-value]')).not_to_be_empty()
  page.set_viewport_size({'width':1440,'height':900})
  expect(page.locator('.si-market-period [data-sector-period="30"]')).to_have_attribute('aria-pressed','true')
  page.locator('.si-market-period [data-sector-period="7"]').click()
  expect(page.locator('.si-market-period [data-sector-period="7"]')).to_have_attribute('aria-pressed','true')
  expect(page.locator('.si-filter-bar [data-sector-period="7"]')).to_have_class('active')
  page.locator('.si-market-period [data-sector-period="30"]').click()
  expect(page.locator('.sector-heat[data-sector-market="XLU.US"]')).to_contain_text('01.10.2026 →')
  page.locator('.sector-heat[data-sector-market="XLU.US"]').click();expect(page.locator('[role=dialog]')).to_be_visible();print('USA opened:',page.locator('[role=dialog]').inner_text()[:120])
  with patch('ssga_holdings.fetch',return_value={'rows':[{'name':'NextEra Energy','ticker':'NEE','weight':13.5,'identifier':'65339F101'}],'as_of':'2026-11-05'}):sector.refresh_tick(app.connect)
  expect(page.locator('[role=dialog]')).to_contain_text('NextEra Energy',timeout=18000);print('USA list:',page.locator('.si-etf-holding').count())
  with app.connect() as c:c.execute("UPDATE sector_holding_prices SET status='OK',payload=?,updated=? WHERE ticker='NEE'",(json.dumps({'periods':{'30':{'value':10,'from':'2026-10-01','to':today}},'basis':'justeret'}),time.time()))
  expect(page.locator('.si-etf-metrics strong.positive')).to_contain_text('+10,00 %',timeout=18000);expect(page.locator('.si-etf-metrics small')).to_contain_text('Fondsandel')
  page.locator('[data-sector-holdings-close]').click();page.locator('[data-sector-region="Europa"]').click();page.locator('[data-sector-market="EXH4.XETRA"]').click();expect(page.locator('[role=dialog]')).to_be_visible();print('Europa opened:',page.locator('[role=dialog]').inner_text()[:120])
  with patch('ishares_holdings.fetch_europe',return_value={'rows':[{'name':'European holding','ticker':'EXAMPLE','weight':5.0,'identifier':None}],'as_of':today}):sector.refresh_tick(app.connect)
  expect(page.locator('[role=dialog]')).to_contain_text('European holding',timeout=18000)
  expect(page.locator('[role=dialog]')).to_contain_text('iShares / BlackRock')
  page.locator('[data-sector-holdings-close]').click();page.locator('[data-sector-region="Globalt"]').click();page.locator('[data-sector-market="IXN.US"]').wait_for()
  page.locator('[data-sector-market="IXN.US"]').click()
  with patch('ishares_holdings.fetch',return_value={'rows':[{'name':'Synthetic holding','ticker':'TEST','weight':12.0,'identifier':None}],'as_of':today}):sector.refresh_tick(app.connect)
  expect(page.locator('[role=dialog]')).to_contain_text('Synthetic holding',timeout=18000)
  expect(page.locator('[role=dialog]')).to_contain_text('iShares / BlackRock')
  page.locator('[data-sector-holdings-close]').click()
  for width in (320,1440):
   page.set_viewport_size({'width':width,'height':900})
   for key,title in [('value','Depotværdi'),('result','Resultat oplyst af Pluto'),('best','Bedste sektor'),('worst','Svageste sektor')]:
    page.locator(f'[data-sector-summary="{key}"]').click()
    dialog=page.locator('#si-summary-dialog')
    expect(dialog).to_be_visible();expect(dialog.locator('h2')).to_have_text(title)
    page.keyboard.press('Escape');expect(dialog).not_to_be_visible()
  assert not errors,errors;print('PASS: sector holdings, summary dialogs, mobile and desktop');browser.close()
finally:server.shutdown();server.server_close();case.tearDown()
