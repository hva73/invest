"""Synthetic end-to-end statistics UI; no Pluto or order operations."""
import os,sys,threading
from pathlib import Path
from unittest.mock import patch
sys.path[:0]=['.','tests']
import app
from test_portfolio_value_chart import PortfolioValueChart
from playwright.sync_api import expect,sync_playwright
case=PortfolioValueChart();case.setUp()
server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
from realized_statistics import project
from test_realized_statistics import order
buy=order('BUY','10','10','2026-01-01T00:00:00Z','b')
sales=[order('SELL','4','12','2026-01-02T00:00:00Z','s1'),order('SELL','2','8','2026-01-03T00:00:00Z','s2'),order('SELL','1','10','2026-01-04T00:00:00Z','s3')]
for row in [buy,*sales]: row['asset']={'ticker':'SYNTH','name':'Fiktiv aktie','currency':'DKK'}
rows=project([buy,*sales])['items']
assert [(r['cost_basis'],r['sale_proceeds'],r['gross']) for r in rows]==[('40','48','8'),('20','16','-4'),('10','10','0')]
for row,ticker in zip(rows,['DELSALG','TAB','NUL']):row['ticker']=ticker
usd_buy=order('BUY','1','1000','2026-01-01T00:00:00Z','b2');usd_sell=order('SELL','1','1100','2026-01-02T00:00:00Z','s4')
for row in [usd_buy,usd_sell]:row['asset']={'ticker':'USD_ONLY','name':'Fiktiv handel i USD','currency':'USD'}
rows+=project([usd_buy,usd_sell])['items']
payload={'portfolios':[{'portfolio_id':1,'name':'Fiktivt depot','items':rows,'omitted':1,'history_complete':False}],'errors':[],'history_complete':False}
try:
 with patch('mcp_client.MCP.request',side_effect=AssertionError('No broker calls')),sync_playwright() as p:
  browser=p.chromium.launch(headless=True)
  for width in (390,768,1280,1440):
   page=browser.new_page(viewport={'width':width,'height':1000},is_mobile=width==390,has_touch=width==390);errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
   page.route('**/api/realized-statistics',lambda route:route.fulfill(json=payload))
   page.goto(f'http://127.0.0.1:{server.server_port}/');page.locator('#login-form [name=password]').fill('test-password-long-enough');page.locator('#login-form button').click()
   if width<=900:page.locator('#mobile-more').click()
   page.locator('nav [data-view=statistics]').click();expect(page.locator('#statistics-title')).to_have_text('Hvordan står det til?')
   page.locator('[data-statistics-currency]').select_option('DKK');view=page.locator('.statistics-view')
   expect(view).to_contain_text('33,33');expect(view).to_contain_text('8,00');expect(view).to_contain_text('4,00');expect(view).to_contain_text('foreløbig',ignore_case=True);expect(view).to_contain_text('ufuldstændig',ignore_case=True)
   assert page.locator('.statistics-trade').count()==0
   bars=page.locator('[data-statistics-segment]');assert bars.count()==3
   assert all(bars.nth(i).bounding_box()['width']>0 for i in range(3))
   if os.environ.get('ESCAPE_SCREENSHOTS') and width>=1280:
    page.evaluate("""() => {const n=document.createElement('div');n.textContent='FIKTIVE TESTDATA';Object.assign(n.style,{position:'fixed',zIndex:'9999',top:'4px',left:'230px',background:'#6d531a',color:'white',padding:'6px'});document.body.append(n)}""")
    page.screenshot(path=str(Path(os.environ['ESCAPE_SCREENSHOTS'])/f'desktop-overblik-{width}.png'))
   page.locator('[data-statistics-group=wins]').click();expect(page.locator('.statistics-list')).to_contain_text('DELSALG');expect(page.locator('.statistics-list')).not_to_contain_text('TAB');assert page.locator('dialog:modal').count()==0
   if os.environ.get('ESCAPE_SCREENSHOTS') and width>=1280:page.screenshot(path=str(Path(os.environ['ESCAPE_SCREENSHOTS'])/f'desktop-gevinst-{width}.png'))
   opener=page.locator('.statistics-trade-button');opener.click();dialog=page.locator('dialog:modal');expect(dialog).to_be_visible()
   for text in ['Solgt mængde','4','10','40','12','48','8,00','omkostning','Ikke afklaret']:expect(dialog).to_contain_text(text,ignore_case=True)
   assert dialog.inner_text().count('Ikke afklaret')==2
   if os.environ.get('ESCAPE_SCREENSHOTS') and width>=1280:page.screenshot(path=str(Path(os.environ['ESCAPE_SCREENSHOTS'])/f'desktop-popup-{width}.png'))
   page.keyboard.press('Escape');expect(dialog).to_have_count(0);expect(opener).to_be_focused()
   opener.click();page.locator('dialog:modal button[aria-label="Luk"]').click();expect(page.locator('dialog:modal')).to_have_count(0)
   page.locator('[data-statistics-group=losses]').click();expect(page.locator('.statistics-list')).to_contain_text('TAB');expect(page.locator('.statistics-list')).not_to_contain_text('DELSALG')
   page.locator('[data-statistics-group=losses]').click();expect(page.locator('.statistics-list')).to_have_count(0)
   page.locator('[data-statistics-currency]').select_option('USD');page.locator('[data-statistics-group=wins]').click();expect(page.locator('.statistics-list')).to_contain_text('USD_ONLY');expect(page.locator('.statistics-list')).not_to_contain_text('DELSALG')
   assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),width
   assert not errors,errors;page.close()
  browser.close()
 print('PASS: actual category, popup, totals, partial sales and currency scope')
finally:server.shutdown();server.server_close();case.tearDown()
