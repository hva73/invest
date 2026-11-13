"""App navigation and display using synthetic statistics; no Pluto access."""
import os,sys,threading
from pathlib import Path
from unittest.mock import patch
sys.path[:0]=['.','tests']
import app
from test_portfolio_value_chart import PortfolioValueChart
from playwright.sync_api import sync_playwright,expect

case=PortfolioValueChart();case.setUp()
server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
sample={'portfolios':[{'portfolio_id':1,'name':'Fiktivt depot','items':[{'ticker':'NOVA','name':'Fiktiv aktie','currency':'USD','gross':'12.35','gross_percent':'6.2','quantity':'2','buy_price':'100','sell_price':'106.175','note':'Foreløbigt bruttoresultat','sell_time':None},{'ticker':'ALFA','name':'Fiktiv aktie','currency':'USD','gross':'-4.1','gross_percent':'-2.4','quantity':'1','buy_price':'170','sell_price':'165.9','note':'Foreløbigt bruttoresultat','sell_time':None}]}], 'errors':[], 'history_complete':False}
try:
 with patch('mcp_client.MCP.request',side_effect=AssertionError('Live broker calls disabled')),sync_playwright() as pw:
  browser=pw.chromium.launch(headless=True)
  for width in (320,390,768,1280):
   page=browser.new_page(viewport={'width':width,'height':900},is_mobile=width<700,has_touch=width<700)
   page.route('**/api/realized-statistics',lambda route:route.fulfill(json=sample))
   page.goto(f'http://127.0.0.1:{server.server_port}/');page.locator('#login-form [name=password]').fill('test-password-long-enough');page.locator('#login-form button').click();expect(page.locator('.dashboard-v1')).to_be_visible()
   if width<=900:page.locator('#mobile-more').click()
   page.locator('nav [data-view=statistics]').click()
   expect(page.locator('#statistics-title')).to_have_text('Hvordan står det til?')
   assert page.locator('[data-statistics-reload]').evaluate('(e) => e.scrollWidth <= e.clientWidth'), width
   expect(page.locator('.statistics-summary>div:first-child>strong')).to_contain_text('+8,25 USD')
   expect(page.locator('.statistics-summary')).to_contain_text('omkostninger')
   page.locator('[data-statistics-group=wins]').click();page.locator('.statistics-trade-button').first.click();expect(page.locator('dialog:modal .statistics-detail')).to_be_visible();page.locator('dialog:modal button[aria-label="Luk"]').click()
   assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1'),width
   if width<=900:
    page.locator('.statistics-trade-button').last.scroll_into_view_if_needed()
    box=page.locator('.statistics-trade-button').last.bounding_box();nav=page.locator('body > aside nav').bounding_box()
    assert box['y']+box['height']<=nav['y'] or box['y']>=nav['y']+nav['height'],(width,box,nav)
   screenshots=os.environ.get('ESCAPE_SCREENSHOTS')
   if screenshots:
    page.evaluate("document.body.insertAdjacentHTML('afterbegin','<div style=\"background:#b37400;color:white;padding:6px;text-align:center\">DESIGNFORSLAG · FIKTIVE DATA</div>')")
    page.screenshot(path=str(Path(screenshots)/f'statistik-integreret-fiktiv-{width}.png'),full_page=True)
   page.close()
  browser.close()
 print('PASS: statistics navigation and synthetic content at 320/390/768/1280')
finally:server.shutdown();server.server_close();case.tearDown()
