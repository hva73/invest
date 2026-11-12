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
    'snapshot_at':stamp,'value':cash(1200),'unrealized':cash(120),'cost_basis':cash(1080),
    'sector_intelligence':{'sector':'Teknologi'}},
   {'asset_id':'child','ticker':'TESTB','name':'Fiktiv aktie B','portfolio_id':2,
    'snapshot_at':older,'value':cash(800),'unrealized':cash(80),'cost_basis':cash(720),
    'sector_intelligence':{'sector':'Sundhed'}}],
  'snapshot_at':stamp,'warnings':[], 'portfolio_value_history':{}},
 'markets':[],'history':[],'regions':['USA','Europa','Asien','Globalt'],
 'benchmark_holdings':[],'holding_prices':[],'fx_quotes':[],'fx':None}
payload['dashboard']['positions'][0].update(key='holding-one',portfolio_name='Hoved',quantity='2',verification='broker_snapshot',conflicts=[],missing={},raw={},unrealized=cash(-60),unrealized_percent='-4.76',price=cash(600),price_freshness={'state':'fresh'},daily={'amount':'-6','percent':'-1','currency':'DKK','to':stamp})
screens = Path(os.environ.get('ESCAPE_SCREENSHOTS','/tmp/escape-sector-cash'))
screens.mkdir(parents=True,exist_ok=True)
try:
 with patch('mcp_client.MCP.request',side_effect=AssertionError('No broker calls')), sync_playwright() as p:
  browser = p.chromium.launch(headless=True)
  for width in (320,390,667,1440):
   page=browser.new_page(viewport={'width':width,'height':375 if width==667 else 900})
   errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
   page.route('**/api/sector-intelligence',lambda route:route.fulfill(json=payload))
   page.goto(f'http://127.0.0.1:{server.server_port}')
   page.locator('#login-form [name=password]').fill('test-password-long-enough')
   page.locator('#login-form button').click()
   page.locator('nav [data-view=sectors]').click()
   expect(page.locator('.si-donut strong')).to_contain_text('2.600,00')
   expect(page.locator('.si-donut')).to_contain_text('2 positioner')
   if width >= 901:
    zero = page.locator('.si-results .si-zero-line').bounding_box()['y']
    up = page.locator('.si-results .si-bar.up').bounding_box()
    down = page.locator('.si-results .si-bar.down').bounding_box()
    assert abs((up['y']+up['height'])-zero)<=2,(width,up,zero)
    assert abs(down['y']-zero)<=2,(width,down,zero)
   expect(page.locator('.si-allocation')).to_contain_text('Fordelingens datagrundlag: ældste')
   expect(page.locator('.sector-row').filter(has_text='Kontantbeholdning')).to_contain_text('600,00')
   # Open a sector holding using the same mobile row and exact depot identity.
   if width<700:
    row=payload['dashboard']['positions'][0]
    page.evaluate("(r)=>{state.dashboard.positions=[r]}",row)
    page.locator('.sector-row').filter(has_text='Teknologi').click()
    mobile=page.locator('.sector-mobile-holdings [data-dashboard-member="holding-one"]')
    expect(mobile).to_be_visible()
    expect(page.locator('.si-detail-metrics .signed-negative')).to_contain_text('↓')
    expect(mobile.locator('.mobile-holding-daily .signed-negative')).to_have_count(2)
    expect(mobile.locator('.dash-change.negative')).to_contain_text('↓')
    page.screenshot(path=str(screens / f'sector-position-{width}.png'),full_page=True)
    page.locator('.si-detail').screenshot(path=str(screens / f'sector-detail-{width}.png'))
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
   assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),width
   assert not errors,(width,errors)
   page.close()
  browser.close()
 print('PASS: sector allocation includes cash and collection once on mobile/desktop')
finally:
 server.shutdown()
 server.server_close()
 case.tearDown()
