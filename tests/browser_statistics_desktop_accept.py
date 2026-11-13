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
rows=[{'ticker':'DELSALG','name':'Fiktiv aktie','currency':'DKK','gross':'8','gross_percent':'20','quantity':'4','buy_price':'10','sell_price':'12','cost_basis':'40','sale_proceeds':'48','sell_time':None,'buy_origin':'unknown','sell_origin':'unknown'},{'ticker':'TAB','name':'Fiktiv tabshandel','currency':'DKK','gross':'-4','gross_percent':'-20','quantity':'2','buy_price':'10','sell_price':'8','cost_basis':'20','sale_proceeds':'16','sell_time':None,'buy_origin':'unknown','sell_origin':'unknown'},{'ticker':'NUL','name':'Fiktiv neutral handel','currency':'DKK','gross':'0','gross_percent':'0','quantity':'1','buy_price':'10','sell_price':'10','cost_basis':'10','sale_proceeds':'10','sell_time':None,'buy_origin':'unknown','sell_origin':'unknown'},{'ticker':'USD_ONLY','name':'Fiktiv handel i USD','currency':'USD','gross':'100','gross_percent':'10','quantity':'1','buy_price':'1000','sell_price':'1100','cost_basis':'1000','sale_proceeds':'1100','sell_time':None,'buy_origin':'unknown','sell_origin':'unknown'}]
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
