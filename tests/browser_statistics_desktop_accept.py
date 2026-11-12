"""Desktop statistics acceptance on synthetic sold quantities; never calls Pluto."""
import os, sys, threading
from pathlib import Path
from unittest.mock import patch
sys.path[:0]=['.','tests']
import app
from test_portfolio_value_chart import PortfolioValueChart
from playwright.sync_api import expect,sync_playwright

case=PortfolioValueChart();case.setUp()
server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
rows=[{'ticker':'DELSALG','name':'Fiktiv aktie','currency':'DKK','gross':'8','gross_percent':'20','quantity':'4','buy_price':'10','sell_price':'12','sell_time':None,'note':'Foreløbigt før omkostninger','gross_dkk':'8','net_dkk':None,'fees_status':'unknown','buy_origin':'unknown','sell_origin':'unknown'},{'ticker':'TAB','name':'Fiktiv tabshandel','currency':'DKK','gross':'-4','gross_percent':'-20','quantity':'2','buy_price':'10','sell_price':'8','sell_time':None,'note':'Foreløbigt før omkostninger','gross_dkk':'-4','net_dkk':None,'fees_status':'unknown'},{'ticker':'NUL','name':'Fiktiv neutral handel','currency':'DKK','gross':'0','gross_percent':'0','quantity':'1','buy_price':'10','sell_price':'10','sell_time':None,'note':'Foreløbigt før omkostninger','gross_dkk':'0','net_dkk':None,'fees_status':'unknown'},{'ticker':'USD_ONLY','name':'Fiktiv handel i USD','currency':'USD','gross':'100','gross_percent':'10','quantity':'1','buy_price':'1000','sell_price':'1100','sell_time':None,'note':'Foreløbigt før omkostninger','gross_dkk':None,'net_dkk':None,'fees_status':'unknown'}]
summary={'DKK':{'sales':3,'wins':1,'losses':1,'flat':1,'gains':'8','losses_total':'-4','gross_total':'4','win_rate_percent':'33.333333333333333333'},'USD':{'sales':1,'wins':1,'losses':0,'flat':0,'gains':'100','losses_total':'0','gross_total':'100','win_rate_percent':'100'}}
payload={'portfolios':[{'portfolio_id':1,'name':'Fiktivt depot','items':rows,'summary_by_currency':summary,'omitted':1,'history_complete':False}],'errors':[],'history_complete':False}
try:
 with patch('mcp_client.MCP.request',side_effect=AssertionError('No broker calls')),sync_playwright() as p:
  browser=p.chromium.launch(headless=True)
  for width in (1280,1440):
   page=browser.new_page(viewport={'width':width,'height':1000});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
   page.route('**/api/realized-statistics',lambda route:route.fulfill(json=payload))
   page.goto(f'http://127.0.0.1:{server.server_port}/');page.locator('#login-form [name=password]').fill('test-password-long-enough');page.locator('#login-form button').click();page.locator('nav [data-view=statistics]').click()
   expect(page.locator('#statistics-title')).to_have_text('Hvordan står det til?')
   page.locator('[data-statistics-currency]').select_option('DKK')
   view=page.locator('.statistics-view');expect(view).to_contain_text('DELSALG');expect(view).to_contain_text('TAB');expect(view).to_contain_text('NUL');expect(view).not_to_contain_text('USD_ONLY')
   expect(view).to_contain_text('33,33');expect(view).to_contain_text('8,00');expect(view).to_contain_text('4,00');expect(view).to_contain_text('foreløbig',ignore_case=True)
   # Only sold quantities are part of the screen; absence of fill time must never be fabricated.
   trade=page.locator('.statistics-trade').filter(has_text='DELSALG');expect(trade).to_have_count(1);trade.locator('summary').click();detail=trade.locator('.statistics-detail');expect(detail).to_be_visible();expect(detail).to_contain_text('4');expect(detail).to_contain_text('10');expect(detail).to_contain_text('12');expect(detail).to_contain_text('omkostning',ignore_case=True);expect(detail).to_contain_text('Ikke afklaret');assert detail.inner_text().count('Ikke afklaret')==2
   page.locator('[data-statistics-currency]').select_option('USD');expect(view).to_contain_text('USD_ONLY');expect(view).not_to_contain_text('DELSALG')
   assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),width
   assert not errors,errors;page.close()
  browser.close()
 print('PASS desktop: sold-only, neutral wins denominator, currency isolation, expandable detail')
finally:server.shutdown();server.server_close();case.tearDown()
