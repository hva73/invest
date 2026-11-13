"""Synthetic holding chart integration; all provider responses are local."""
import json,os,sys,threading
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
import app,market_data,portfolio_data,hotwatch_service,hotwatch_engine
from test_hotwatch_engine import tick
import test_market_data as fixtures
from playwright.sync_api import sync_playwright,expect

def main():
 case=fixtures.Quotes();case.setUp()
 now=datetime.now(timezone.utc).isoformat()
 positions=portfolio_data.normalize_positions([{'assetId':'synthetic-chart-asset','ticker':'CHART','name':'Synthetic chart','quantity':'1','value':'100','currency':'USD'},{'assetId':'synthetic-pending','ticker':'PENDING','name':'Synthetic pending','quantity':'1','value':'50','currency':'USD'}])
 payload={'source':'Pluto Markets','observed':now,'kind':'portfolio','positions':positions,'pending_orders':[],'accounts':[],'value':None,'errors':[],'complete':True,'orders_complete':True,'positions_complete':True}
 with app.connect() as c:
  portfolio_data.save(c,1,case.case.root,payload)
  c.execute('INSERT INTO market_asset_links VALUES(?,?,?,?)',(1,case.cid,'CHART','synthetic-chart-asset'))
  c.execute('INSERT INTO hw_holding_autowatch VALUES(?,?,?,?,?,?,?)',(1,case.case.root,'synthetic-pending','PROVIDER_RATE_BUDGET',None,datetime.now(timezone.utc).timestamp()+300,now))
 instrument={'asset_id':'synthetic-chart-asset','ticker':'CHART','exchange':'NASDAQ','currency':'USD','isin':'US1234567890'}
 with patch.dict('os.environ',{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'synthetic'}):
  assert hotwatch_service.auto_holdings_tick(app.connect,verify=lambda *_:instrument,lookup=lambda *_:{'choices':[{'symbol':'CHART.US','currency':'USD','isin':'US1234567890'}]})=='LINKED'
 with app.connect() as c:wid=c.execute("SELECT watch_id FROM hw_sessions WHERE purpose='automatic holding watch'").fetchone()['watch_id']
 sample=tick(datetime.fromisoformat(now));sample.update(source='eodhd',asset_id='synthetic-chart-asset',ticker='CHART',bid_at=now,ask_at=now,status_at=now,quote_feed='synthetic_quotes',status_feed='synthetic_status')
 with patch('hotwatch_engine.verified_automatic_feed',return_value=True):hotwatch_engine.ingest(app.connect,1,wid,False,sample,datetime.fromisoformat(now))
 server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
 try:
  with patch('trade_service.MCP',case.factory),sync_playwright() as pw:
   browser=pw.chromium.launch(**({} if os.environ.get('ESCAPE_PLAYWRIGHT_MANAGED') else {'executable_path':'/usr/bin/chromium'}),headless=True,args=['--no-sandbox']);page=browser.new_page(viewport={'width':1200,'height':900});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
   def chart(route):
    data=route.request.post_data_json
    if 'holding_portfolio_id' not in data:
     route.fulfill(json={'selection_required':True,'choices':[]});return
    assert data['holding_portfolio_id']==case.case.root and data['holding_asset_id']=='synthetic-chart-asset'
    route.fulfill(json=market_data.normalized(case.raw,'synthetic-chart-asset',case.fixed))
   page.route('**/api/market/quote',chart)
   page.route('**/api/portfolios/data',lambda route:route.fulfill(json={'ok':True,'complete':True,'errors':[],'message':'Synthetic'}))
   page.route('**/api/portfolios/sync',lambda route:route.fulfill(json={'ok':True,'count':1}))
   page.goto(f'http://127.0.0.1:{server.server_port}');page.locator('#login-form [name=password]').fill('test-password-long-enough');page.locator('#login-form button').click();page.locator('[data-dashboard-watch-pending]').first.click();page.locator('#engine-dialog').wait_for(state='visible');assert 'fælles budget' in page.locator('#engine-dialog').inner_text()
   with app.connect() as c:c.execute("UPDATE hw_holding_autowatch SET status='VERIFICATION_FAILED' WHERE asset_id='synthetic-pending'")
   expect(page.locator('#engine-dialog')).to_contain_text('Instrumentkontrollen kunne ikke gennemføres',timeout=30000)
   with app.connect() as c:c.execute("UPDATE hw_holding_autowatch SET next_attempt=0 WHERE asset_id='synthetic-pending'")
   pending_instrument={'asset_id':'synthetic-pending','ticker':'PENDING','exchange':'NASDAQ','currency':'USD','isin':'US1234567890'}
   with patch.dict('os.environ',{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'synthetic'}):
    assert hotwatch_service.auto_holdings_tick(app.connect,verify=lambda *_:pending_instrument,lookup=lambda *_:{'choices':[{'symbol':'PENDING.US','currency':'USD','isin':'US1234567890'}]})=='LINKED'
   expect(page.locator('#engine-dialog')).to_contain_text('PENDING · motorforløb',timeout=30000);page.locator('[data-engine-close]').click();page.locator('[data-dashboard-watch]').first.click();page.locator('#engine-dialog').wait_for(state='visible');assert 'motorforløb' in page.locator('#engine-dialog').inner_text();page.locator('[data-engine-close]').click();page.locator('[data-dashboard-open]').first.click()
   graph=page.locator('#dashboard-detail .market-slot');graph.locator('.market-price').wait_for();assert graph.locator('[data-market-period=day]').get_attribute('aria-pressed')=='true';graph.locator('[data-market-period=week]').click();assert graph.locator('.market-line').get_attribute('d').count('L')==81
   page.locator('[data-dashboard-close]').click();page.locator('nav [data-view=hot-watch]').click();page.locator('[data-engine-new]').click();dialog=page.locator('#engine-dialog');dialog.wait_for(state='visible')
   assert 'Søg aktie på Pluto' in dialog.inner_text(),dialog.inner_text();assert dialog.locator('#engine-manual-search').count()==1;assert not errors,errors
   browser.close()
  print('PASS: holding modal chart with day and week; synthetic data')
 finally:server.shutdown();server.server_close();case.tearDown()
if __name__=='__main__':main()
