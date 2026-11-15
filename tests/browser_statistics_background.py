"""Regression: background state updates must not reload broker statistics."""
import sys, threading
from unittest.mock import patch
sys.path[:0]=['.','tests']
import app
from test_portfolio_value_chart import PortfolioValueChart
from playwright.sync_api import sync_playwright,expect

case=PortfolioValueChart();case.setUp()
server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
payload={'portfolios':[{'portfolio_id':1,'name':'A','items':[{'ticker':'ONE','name':'Test','currency':'EUR','gross':'2','gross_percent':'2','quantity':'1','buy_price':'100','sell_price':'102'},{'ticker':'TWO','name':'Test','currency':'USD','gross':'3','gross_percent':'3','quantity':'1','buy_price':'100','sell_price':'103'}]},{'portfolio_id':2,'name':'B','items':[]}], 'errors':[], 'history_complete':False}
try:
 with patch('mcp_client.MCP.request',side_effect=AssertionError('No broker')),sync_playwright() as pw:
  browser=pw.chromium.launch(headless=True);page=browser.new_page()
  page.add_init_script("""(() => {const original=window.setInterval;window.testTimers=[];window.setInterval=(fn,ms,...args)=>{if(ms===30000)window.testTimers.push(()=>fn(...args));return original(fn,ms,...args)}})()""")
  counts={'stats':0,'state':0}
  def stat(route):counts['stats']+=1;route.fulfill(json=payload)
  def state(route):
   counts['state']+=1;res=route.fetch();data=res.json();data['synthetic_revision']=counts['state'];route.fulfill(response=res,json=data)
  page.route('**/api/realized-statistics',stat);page.route('**/api/state',state)
  page.goto(f'http://127.0.0.1:{server.server_port}/');page.locator('#login-form [name=password]').fill('test-password-long-enough');page.locator('#login-form button').click();expect(page.locator('.dashboard-v1')).to_be_visible()
  page.locator('nav [data-view=statistics]').click();expect(page.locator('#statistics-title')).to_be_visible()
  page.locator('[data-statistics-currency]').select_option('USD');assert counts['stats']==1
  page.locator('[data-statistics-portfolio]').select_option('2');assert counts['stats']==1
  page.locator('[data-statistics-portfolio]').select_option('1');page.locator('[data-statistics-currency]').select_option('USD');page.locator('h1').click()
  page.evaluate('Promise.all(window.testTimers.map(fn=>fn()))');page.wait_for_timeout(300)
  assert counts['stats']==1,counts
  expect(page.locator('[data-statistics-currency]')).to_have_value('USD')
  page.locator('[data-statistics-reload]').click();expect(page.locator('#statistics-title')).to_be_visible()
  assert counts['stats']==2,counts
  browser.close()
 print('PASS: background refresh, filters and explicit reload')
finally:server.shutdown();server.server_close();case.tearDown()
