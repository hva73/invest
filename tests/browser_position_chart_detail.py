"""Position chart from synthetic source, desktop and mobile."""
import os,sys,threading
from datetime import datetime,timezone,timedelta
from pathlib import Path
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
import app,market_data,portfolio_data
import test_market_data as fixtures
from playwright.sync_api import sync_playwright,expect
def main():
 case=fixtures.Quotes();case.setUp();now=datetime.now(timezone.utc).isoformat()
 positions=portfolio_data.normalize_positions([{'assetId':'synthetic-chart-asset','ticker':'CHART','name':'Synthetic chart','quantity':'1','value':'100','currency':'USD'}])
 payload={'source':'Synthetic','observed':now,'kind':'portfolio','positions':positions,'pending_orders':[],'accounts':[],'value':None,'errors':[],'complete':True,'orders_complete':True,'positions_complete':True}
 with app.connect() as c:portfolio_data.save(c,1,case.case.root,payload)
 server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
 try:
  with patch('trade_service.MCP',case.factory),sync_playwright() as p:
   browser=p.chromium.launch(**({} if os.environ.get('ESCAPE_PLAYWRIGHT_MANAGED') else {'executable_path':'/usr/bin/chromium'}),headless=True,args=['--no-sandbox'])
   page=browser.new_page(viewport={'width':1200,'height':900},has_touch=True);errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
   def chart(route):
    data=route.request.post_data_json
    assert data['holding_portfolio_id']==case.case.root and data['holding_asset_id']=='synthetic-chart-asset'
    result=market_data.normalized(case.raw,'synthetic-chart-asset',case.fixed)
    if data.get('include_intraday')=='day':
     start=case.fixed-timedelta(minutes=30)
     result.update(intraday_period='day',intraday_status='SOURCE_INCOMPLETE',intraday_interval='1m',intraday_source='EODHD · syntetiske lukkede minutbarer',intraday_series=[
      {'timestamp':(start+timedelta(minutes=i)).isoformat(),'epoch':(start+timedelta(minutes=i)).timestamp(),'price':18+i*.01,'date':'2026-11-02'} for i in range(30)])
    route.fulfill(json=result)
   page.route('**/api/market/quote',chart)
   page.route('**/api/portfolios/data',lambda route:route.fulfill(json={'ok':True,'complete':True,'errors':[],'message':'Synthetic'}))
   page.route('**/api/portfolios/sync',lambda route:route.fulfill(json={'ok':True,'count':1}))
   page.goto(f'http://127.0.0.1:{server.server_port}');page.locator('#login-form [name=password]').fill('test-password-long-enough');page.locator('#login-form button').click()
   page.locator('[data-dashboard-open]:visible').first.click();graph=page.locator('#dashboard-detail .market-slot');expect(graph.locator('.market-price')).to_be_visible()
   # A verified dense but incomplete excerpt is preferred on position detail,
   # with the longer Pluto period still available via the explicit toggle.
   expect(graph.locator('.market-source-choice')).to_be_visible()
   expect(graph.locator('.market-session')).to_contain_text('30 faktiske punkter')
   expect(graph.locator('.market-peak-marker')).to_be_visible()
   assert graph.locator('.market-quote .market-change').inner_text().count('↑')==1
   graph.locator('[data-market-excerpt]').click()
   expect(graph.locator('.market-session')).to_contain_text('Pluto')
   graph.locator('[data-market-excerpt]').click()
   expect(graph.locator('.market-session')).to_contain_text('30 faktiske punkter')
   graph.locator('[data-market-period=week]').click();assert graph.locator('.market-line').get_attribute('d').count('L')==81
   plot=graph.locator('.market-plot svg');plot.scroll_into_view_if_needed();plot.hover();tip=graph.locator('.market-hover');expect(tip).to_be_visible();assert tip.bounding_box()['y']+tip.bounding_box()['height']<=plot.bounding_box()['y']
   page.set_viewport_size({'width':390,'height':900});plot.scroll_into_view_if_needed();box=plot.bounding_box();plot.dispatch_event('pointerdown',{'pointerType':'touch','clientX':box['x']+box['width']*.5,'clientY':box['y']+box['height']*.5});expect(tip).to_be_visible();expect(graph.locator('.market-hover strong')).to_contain_text('USD');assert tip.bounding_box()['y']+tip.bounding_box()['height']<=plot.bounding_box()['y'];plot.dispatch_event('pointerup',{'pointerType':'touch'});expect(tip).to_be_hidden()
   assert not errors,errors;browser.close()
 finally:server.shutdown();server.server_close();case.tearDown()
 print('PASS: position chart points, touch and mouse')
if __name__=='__main__':main()
