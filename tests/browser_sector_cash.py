"""Exercise real sector UI with synthetic root, collection and cash."""
import os, sys, threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path[:0] = ['.', 'tests']
import app
from playwright.sync_api import expect, sync_playwright
from test_portfolio_value_chart import PortfolioValueChart

case = PortfolioValueChart()
case.setUp()
server = app.ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
stamp = datetime.now(timezone.utc).isoformat()
older = (datetime.now(timezone.utc)-timedelta(days=2)).isoformat()
cash = lambda amount: {'amount':str(amount), 'currency':'DKK'}
payload = {
 'dashboard': {
  'accounts':[
   {'id':1,'name':'Hoved','kind':'portfolio','external_id':'portfolios:main',
    'snapshot_at':stamp,'value':cash(2600),'positions_status':'available','cash_status':'available','cash_accounts':[cash(500)]},
   {'id':2,'name':'AI','kind':'collection','parent_external_id':'portfolios:main',
    'snapshot_at':older,'value':cash(900),'positions_status':'available','cash_status':'available','cash_accounts':[cash(100)]}],
  'positions':[
   {'asset_id':'direct','ticker':'TESTA','name':'Fiktiv aktie A','portfolio_id':1,
    'snapshot_at':stamp,'value':cash(1200),'unrealized':cash(0),'cost_basis':cash(1200),
    'sector_intelligence':{'sector':'Teknologi'}},
   {'asset_id':'child','ticker':'TESTB','name':'Fiktiv aktie B','portfolio_id':2,
    'snapshot_at':older,'value':cash(800),'unrealized':cash(0),'cost_basis':cash(800),
    'sector_intelligence':{'sector':'Sundhed'}}],
  'snapshot_at':stamp,'warnings':[], 'portfolio_value_history':{}},
 'markets':[],'history':[],'regions':['USA','Europa','Asien','Globalt'],
 'benchmark_holdings':[],'holding_prices':[],'fx_quotes':[],'fx':None}
payload['dashboard']['positions'][0].update(key='holding-one',portfolio_name='Hoved',quantity='1',verification='broker_snapshot',conflicts=[],missing={},raw={})
screens = Path(os.environ.get('ESCAPE_SCREENSHOTS','/tmp/escape-sector-cash'))
screens.mkdir(parents=True,exist_ok=True)
try:
 with patch('mcp_client.MCP.request',side_effect=AssertionError('No broker calls')), sync_playwright() as p:
  browser = p.chromium.launch(headless=True)
  for width in (320,390,1440):
   page=browser.new_page(viewport={'width':width,'height':900})
   errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
   page.route('**/api/sector-intelligence',lambda route:route.fulfill(json=payload))
   page.goto(f'http://127.0.0.1:{server.server_port}')
   page.locator('#login-form [name=password]').fill('test-password-long-enough')
   page.locator('#login-form button').click()
   page.locator('nav [data-view=sectors]').click()
   expect(page.locator('.si-donut strong')).to_contain_text('2.600,00')
   expect(page.locator('.si-donut')).to_contain_text('2 positioner')
   expect(page.locator('.si-allocation')).to_contain_text('Fordelingens datagrundlag: ældste')
   expect(page.locator('.sector-row').filter(has_text='Kontantbeholdning')).to_contain_text('600,00')
   # Open a sector holding using the same mobile row and exact depot identity.
   if width<700:
    row=payload['dashboard']['positions'][0]
    page.evaluate("(r)=>{state.dashboard.positions=[r]}",row)
    page.locator('.sector-row').filter(has_text='Teknologi').click()
    mobile=page.locator('.sector-mobile-holdings [data-dashboard-member="holding-one"]')
    expect(mobile).to_be_visible()
    page.screenshot(path=str(screens / f'sector-position-{width}.png'),full_page=True)
    mobile.click()
    expect(page.locator('#dashboard-detail h2')).to_contain_text('TESTA · Hoved')
    page.locator('#dashboard-detail [data-dashboard-close]').click()
   page.screenshot(path=str(screens / f'sector-cash-{width}.png'),full_page=True)
   page.locator('[data-sector-scope="2"]').click()
   expect(page.locator('.si-donut strong')).to_contain_text('900,00')
   expect(page.locator('.si-allocation')).to_contain_text('Fordelingens datagrundlag: opdateret')
   expect(page.locator('.sector-row').filter(has_text='Kontantbeholdning')).to_contain_text('100,00')
   page.locator('[data-sector-scope="1"]').click()
   expect(page.locator('.si-donut strong')).to_contain_text('2.600,00')
   payload['dashboard']['accounts'][1]['positions_status']='unavailable'
   page.reload()
   page.locator('nav [data-view=sectors]').click()
   expect(page.locator('.si-donut')).to_contain_text('DELVIS FORDELING')
   expect(page.locator('.si-allocation')).to_contain_text('Positioner for et eller flere valgte depoter')
   page.locator('[data-sector-scope="2"]').click()
   expect(page.locator('.si-allocation')).to_contain_text('Positioner for et eller flere valgte depoter')
   payload['dashboard']['accounts'][1]['positions_status']='available'
   payload['dashboard']['accounts'].append({'id':3,'name':'Mangler','kind':'collection','parent_external_id':'portfolios:main',
    'external_id':'collections:missing','value':None,'cash_status':'unavailable','cash_accounts':[],'snapshot_missing':True})
   page.reload()
   page.locator('nav [data-view=sectors]').click()
   expect(page.locator('.si-donut')).to_contain_text('DELVIS FORDELING')
   expect(page.locator('.si-allocation')).to_contain_text('mangler data om positioner og kontanter')
   page.locator('[data-sector-scope="2"]').click()
   expect(page.locator('.si-allocation')).not_to_contain_text('mangler data om positioner og kontanter')
   payload['dashboard']['accounts'].pop()
   print('OVERFLOW',width,page.evaluate("""()=>[...document.querySelectorAll('body *')].map(e=>({tag:e.tagName,cls:e.className?.baseVal??e.className,right:e.getBoundingClientRect().right,width:e.getBoundingClientRect().width})).filter(o=>o.right>innerWidth+1).slice(0,15)"""))
   assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),width
   assert not errors,(width,errors)
   page.close()
  browser.close()
 print('PASS: sector allocation includes cash and collection once on mobile/desktop')
finally:
 server.shutdown()
 server.server_close()
 case.tearDown()
