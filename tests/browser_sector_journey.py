"""Sector navigation using real frontend and explicitly synthetic portfolio snapshots."""
import json, os, sys, threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch
sys.path[:0] = ['.', 'tests']
import app, portfolios, portfolio_data, dashboard_projection
from playwright.sync_api import expect, sync_playwright
from test_portfolio_value_chart import PortfolioValueChart

case=PortfolioValueChart();case.setUp()
case.save(case.root,'5357.70',case.now,result='141.30')
case.save(case.child,'540.60',case.now,result='45')
at=case.now.isoformat()
root_rows=[
 {'assetId':'synthetic-novo','ticker':'NOVO-B','name':'Novo Nordisk B','quantity':'5','price':'270.30','currency':'DKK','value':'1351.50','unrealisedPnL':'112.50','costBasis':'1239.00','averageEntryPrice':'247.80','dailyChange':'6.30','dailyChangePercent':'2.39','priceAsOf':at},
 {'assetId':'synthetic-zealand','ticker':'ZEAL','name':'Zealand Pharma','quantity':'4','price':'411.40','currency':'DKK','value':'1645.60','unrealisedPnL':'-96.20','costBasis':'1741.80','averageEntryPrice':'435.45','dailyChange':'-3.60','dailyChangePercent':'-0.87','priceAsOf':at},
 {'assetId':'synthetic-tech','ticker':'MSFT','name':'Microsoft','quantity':'2','price':'910','currency':'DKK','value':'1820','unrealisedPnL':'80','priceAsOf':at}]
child_rows=[{'assetId':'synthetic-novo','ticker':'NOVO-B','name':'Novo Nordisk B','quantity':'2','price':'270.30','currency':'DKK','value':'540.60','unrealisedPnL':'45','costBasis':'495.60','averageEntryPrice':'247.80','dailyChange':'6.30','dailyChangePercent':'2.39','priceAsOf':at}]
with app.connect() as c:
 for pid,rows in ((case.root,root_rows),(case.child,child_rows)):
  existing=json.loads(c.execute('SELECT payload FROM portfolio_snapshots WHERE portfolio_id=?',(pid,)).fetchone()['payload'])
  existing.update(positions=portfolio_data.normalize_positions(rows),positions_complete=True,accounts=[],pending_orders=[],errors=[],complete=True)
  portfolio_data.save(c,1,pid,existing)
 owned=portfolios.list_owned(c,1); snapshots=portfolio_data.snapshots(c,1)
dashboard=dashboard_projection.build(app.connect,1,owned,snapshots)
for row in dashboard['positions']:
 row['sector_intelligence']={'sector':'Teknologi' if row['ticker']=='MSFT' else 'Sundhed'}
dashboard['positions'].append({'key':'synthetic-missing','portfolio_id':case.child,'portfolio_name':'AI','asset_id':'synthetic-missing','ticker':'AFVENTER','name':'Fiktiv position','value':None,'unrealized':None,'sector_intelligence':{'sector':'Sundhed'}})
for account in dashboard['accounts']:
 portfolio=next(p for p in owned if p['id']==account['id'])
 account.update(external_id=portfolio.get('external_id'),cash_status='available',cash_accounts=[],positions_status='available')
dates=[(case.now-timedelta(days=n)).date().isoformat() for n in (40,15,0)]
markets=[{'symbol':'SYNTH-TECH.US','sector':'Teknologi','region':'USA','benchmark_currency':'USD','price_basis':'close','status':'OK','series':[{'date':date,'close':value} for date,value in zip(dates,[100,105,112])]},
         {'symbol':'SYNTH-HEALTH.US','sector':'Sundhed','region':'USA','benchmark_currency':'USD','price_basis':'close','status':'OK','series':[{'date':date,'close':value} for date,value in zip(dates,[100,96,93])]}]
payload={'dashboard':dashboard,'markets':markets,'history':[],'regions':['USA','Europa','Asien','Globalt'],'benchmark_holdings':[],'holding_prices':[],'fx_quotes':[],'fx':None}
screens=Path(os.environ.get('ESCAPE_SCREENSHOTS','/tmp/escape-sector-journey'));screens.mkdir(parents=True,exist_ok=True)
server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
try:
 with patch('mcp_client.MCP.request',side_effect=AssertionError('No broker calls')),sync_playwright() as p:
  browser=p.chromium.launch(headless=True)
  for width,height in ((390,844),(844,390),(1440,900)):
   page=browser.new_page(viewport={'width':width,'height':height});errors=[];writes=[]
   page.on('pageerror',lambda e:errors.append(str(e)))
   page.on('request',lambda r:writes.append(r.url) if '/api/trade/send' in r.url else None)
   page.route('**/api/sector-intelligence',lambda route:route.fulfill(json=payload))
   page.route('**/api/sector-intelligence/holdings',lambda route:route.fulfill(json={'status':'PENDING'}))
   page.goto(f'http://127.0.0.1:{server.server_port}/')
   page.locator('#login-form [name=password]').fill('test-password-long-enough');page.locator('#login-form button').click()
   page.evaluate("""() => {const x=document.createElement('div');x.textContent='FIKTIVE TESTDATA';Object.assign(x.style,{position:'fixed',bottom:'4px',left:'4px',zIndex:'99999',background:'#0a2229',color:'#b6ddd1',padding:'4px 8px',fontSize:'10px'});document.body.append(x)}""")
   page.locator('nav [data-view=sectors]').click()
   expect(page.locator('.sector-row').filter(has_text='Sundhed')).to_be_visible()
   if width >= 901:
    bar=page.locator('.si-bar-column[data-sector-select]').first;bar.hover();tip=bar.locator('.dash-chart-tooltip');expect(tip).to_be_visible();expect(tip).to_contain_text('Resultat');expect(tip.locator('[data-chart-value]')).not_to_have_text('—')
    bar.focus();expect(tip).to_be_visible();page.locator('.sector-heading h2').first.hover();expect(tip).to_be_hidden()
    arc=page.locator('[data-sector-donut="Sundhed"]');arc.focus();donut=page.locator('.si-donut-wrap .dash-chart-tooltip');expect(donut).to_be_visible();expect(donut).to_contain_text('Andel');page.locator('.sector-heading h2').first.click();expect(donut).to_be_hidden()
    rotation=page.locator('.si-rotation-chart.inspect-chart-svg');rotation.scroll_into_view_if_needed();box=rotation.bounding_box();page.mouse.move(box['x']+box['width']*.5,box['y']+box['height']*.5);rtip=page.locator('.si-rotation .dash-chart-tooltip');expect(rtip).to_be_visible();expect(rtip).to_contain_text('Kurs');expect(rtip.locator('[data-chart-share]')).to_contain_text('%')
    page.locator('.si-rotation').screenshot(path=str(screens/'sektor-sammenligning-mouseover.png'))
    page.locator('.sector-heading h2').first.hover();expect(rtip).to_be_hidden()
   page.screenshot(path=str(screens/f'sektor-oversigt-{width}.png'),full_page=True)
   page.locator('.sector-row').filter(has_text='Sundhed').click()
   journey=page.locator('#sector-journey');expect(journey).to_be_visible()
   expect(journey.locator('h2')).to_have_text('Sundhed')
   expect(journey.locator('[data-sector-position]')).to_have_count(4)
   expect(journey).to_contain_text('Root');expect(journey).to_contain_text('AI')
   expect(journey).not_to_contain_text('Kontantbeholdning')
   expect(journey.locator('[data-sector-position]').filter(has_text='AFVENTER')).to_be_disabled()
   page.screenshot(path=str(screens/f'sektor-positioner-{width}.png'))
   root=journey.locator('[data-sector-position]').filter(has_text='Root').filter(has_text='NOVO-B')
   child=journey.locator('[data-sector-position]').filter(has_text='AI').filter(has_text='NOVO-B')
   expect(root).to_be_enabled();expect(child).to_be_enabled()
   details=root.locator('.si-desktop-position')
   if width >= 901:
    expect(details).to_be_visible();expect(details).to_contain_text('Gns. køb');expect(details).not_to_contain_text('stk.');expect(details).to_contain_text('270,30');expect(details).to_contain_text('247,80');expect(details).to_contain_text('+31,50');expect(details).to_contain_text('estimat')
    expect(journey.locator('.si-desktop-columns')).to_be_visible()
   else: expect(details).to_be_hidden()
   expect(root).to_contain_text('I dag · kurs pr. stk.')
   expect(root).to_contain_text('+6,30')
   expect(root).to_contain_text('+2,39 %')
   expect(root).to_contain_text('Siden køb')
   expect(root).to_contain_text('+112,50')
   expect(root).to_contain_text('+9,08 %')
   missing=journey.locator('[data-sector-position]').filter(has_text='AFVENTER')
   expect(missing).to_contain_text('— · —')
   child.click();detail=page.locator('#dashboard-detail');expect(detail).to_be_visible()
   expect(detail.locator('h2')).to_contain_text('NOVO-B');expect(detail.locator('h2')).to_contain_text('AI')
   page.screenshot(path=str(screens/f'sektor-positionsdetalje-{width}.png'))
   detail.locator('[data-dashboard-close]').click();expect(journey).to_be_visible()
   root.click();expect(detail).to_be_visible();expect(detail.locator('h2')).to_contain_text('Root')
   detail.locator('[data-dashboard-close]').click();journey.locator('[data-sector-journey-close]').first.click()
   expect(journey).not_to_be_visible();expect(page.locator('.sector-row').filter(has_text='Sundhed')).to_be_visible()
   arc=page.locator('[data-sector-donut="Sundhed"]');arc.focus();page.keyboard.press('Enter')
   expect(journey).to_be_visible();page.keyboard.press('Escape');expect(journey).not_to_be_visible()
   expect(page.locator('.sector-row').filter(has_text='Sundhed')).to_be_focused()
   child_row=next(r for r in payload['dashboard']['positions'] if r.get('asset_id')=='synthetic-novo' and r.get('portfolio_id')==case.child)
   original_freshness=child_row['price_freshness']
   child_row['price_freshness']={'state':'stale'}
   page.reload();page.locator('nav [data-view=sectors]').click()
   page.locator('.sector-row').filter(has_text='Sundhed').click()
   stale=page.locator('#sector-journey [data-sector-position]').filter(has_text='AI').filter(has_text='NOVO-B')
   expect(stale.locator('.si-position-metrics small').first).to_contain_text('— · —')
   expect(stale).to_contain_text('+45,00')
   child_row['price_freshness']=original_freshness
   if width >= 901:
    page.locator('[data-sector-journey-close]').first.click();page.locator('[data-sector-market="SYNTH-TECH.US"]').first.click()
    curve=page.locator('.sector-chart.inspect-chart-svg');expect(curve).to_be_visible();curve.scroll_into_view_if_needed();box=curve.bounding_box();page.mouse.move(box['x']+box['width']*.55,box['y']+box['height']*.5)
    ctip=page.locator('.si-detail .dash-chart-tooltip');expect(ctip).to_be_visible();expect(ctip).to_contain_text('Kurs');expect(ctip.locator('[data-chart-share]')).to_contain_text('%')
    page.locator('.si-detail').screenshot(path=str(screens/'sektor-kurs-mouseover.png'))
   assert not writes,writes
   assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),width
   assert not errors,(width,errors)
   page.close()
  browser.close()
 print('PASS: sector to exact portfolio position and back on mobile, landscape and desktop')
finally:
 server.shutdown();server.server_close();case.tearDown()
