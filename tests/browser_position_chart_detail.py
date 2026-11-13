"""Position chart from synthetic source, desktop and mobile."""
import os,sys,threading
from datetime import datetime,timezone
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
    route.fulfill(json=market_data.normalized(case.raw,'synthetic-chart-asset',case.fixed))
   page.route('**/api/market/quote',chart)
   page.route('**/api/portfolios/data',lambda route:route.fulfill(json={'ok':True,'complete':True,'errors':[],'message':'Synthetic'}))
   page.route('**/api/portfolios/sync',lambda route:route.fulfill(json={'ok':True,'count':1}))
   page.goto(f'http://127.0.0.1:{server.server_port}');page.locator('#login-form [name=password]').fill('test-password-long-enough');page.locator('#login-form button').click()
   page.locator('[data-dashboard-open]').first.click();graph=page.locator('#dashboard-detail .market-slot');expect(graph.locator('.market-price')).to_be_visible()
   graph.locator('[data-market-period=week]').click();assert graph.locator('.market-line').get_attribute('d').count('L')==81
   plot=graph.locator('.market-plot svg');plot.scroll_into_view_if_needed();plot.hover();expect(graph.locator('.market-hover')).to_be_visible()
   page.set_viewport_size({'width':390,'height':900});plot.scroll_into_view_if_needed();box=plot.bounding_box();page.touchscreen.tap(box['x']+box['width']*.5,box['y']+box['height']*.5);expect(graph.locator('.market-hover')).to_be_visible();expect(graph.locator('.market-hover strong')).to_contain_text('USD')
   assert not errors,errors;browser.close()
 finally:server.shutdown();server.server_close();case.tearDown()
 print('PASS: position chart points, touch and mouse')
if __name__=='__main__':main()
