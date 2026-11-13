"""Position graph with real synthetic source points, entry marker and inspection."""
import os,sys,threading
from pathlib import Path
from datetime import datetime,timezone
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
import app,market_data,portfolio_data
import test_market_data as fixtures
from playwright.sync_api import sync_playwright,expect

def main():
 case=fixtures.Quotes();case.setUp();now=datetime.now(timezone.utc).isoformat()
 positions=portfolio_data.normalize_positions([{'assetId':'synthetic-chart-asset','ticker':'CHART','name':'Synthetic chart','quantity':'1','value':'100','currency':'USD','averageEntryPrice':'18.50'}])
 payload={'source':'Synthetic','observed':now,'kind':'portfolio','positions':positions,'pending_orders':[],'accounts':[],'value':None,'errors':[],'complete':True,'orders_complete':True,'positions_complete':True}
 with app.connect() as c:portfolio_data.save(c,1,case.case.root,payload)
 server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
 try:
  with patch('trade_service.MCP',case.factory),sync_playwright() as p:
   browser=p.chromium.launch(headless=True)
   for width,touch in [(1440,False),(390,True)]:
    context=browser.new_context(viewport={'width':width,'height':900},is_mobile=touch,has_touch=touch);page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    def chart(route):
     data=route.request.post_data_json
     assert data['holding_portfolio_id']==case.case.root and data['holding_asset_id']=='synthetic-chart-asset'
     route.fulfill(json=market_data.normalized(case.raw,'synthetic-chart-asset',case.fixed))
    page.route('**/api/market/quote',chart)
    page.route('**/api/portfolios/data',lambda route:route.fulfill(json={'ok':True,'complete':True,'errors':[],'message':'Synthetic'}))
    page.route('**/api/portfolios/sync',lambda route:route.fulfill(json={'ok':True,'count':1}))
    page.goto(f'http://127.0.0.1:{server.server_port}');page.locator('#login-form [name=password]').fill('test-password-long-enough');page.locator('#login-form button').click();page.locator('[data-dashboard-open]:visible').first.click()
    graph=page.locator('#dashboard-detail .market-slot');expect(graph.locator('.market-price')).to_be_visible();graph.locator('[data-market-period=week]').click();expect(graph.locator('.market-line')).to_be_visible();assert graph.locator('.market-line').get_attribute('d').count('L')==81
    entry=graph.locator('.market-marker-entry');expect(entry).to_have_count(1);assert entry.get_attribute('y1')==entry.get_attribute('y2');assert entry.evaluate("e=>getComputedStyle(e).strokeDasharray") not in ('none','0px')
    expect(graph.locator('.market-entry-label')).to_contain_text('Gns. købskurs');expect(graph.locator('.market-entry-label')).to_contain_text('18,5');expect(graph.locator('.market-peak-label')).to_contain_text('Top')
    svg=graph.locator('.market-plot svg');svg.scroll_into_view_if_needed();box=svg.bounding_box();x=box['x']+box['width']*.55;y=box['y']+box['height']*.5;tip=graph.locator('.market-hover')
    if touch:
     cdp=context.new_cdp_session(page);cdp.send('Input.dispatchTouchEvent',{'type':'touchStart','touchPoints':[{'x':x,'y':y}]})
    else:page.mouse.move(x,y)
    expect(tip).to_be_visible();expect(tip.locator('strong')).to_contain_text('USD');tipbox=tip.bounding_box();assert tipbox['y']+tipbox['height']<=box['y'] or tipbox['y']>=box['y']+box['height'],(width,tipbox,box)
    if touch:cdp.send('Input.dispatchTouchEvent',{'type':'touchEnd','touchPoints':[]})
    else:page.mouse.move(0,0)
    expect(tip).to_be_hidden();assert not errors,errors;context.close()
   browser.close()
 finally:server.shutdown();server.server_close();case.tearDown()
 print('PASS: position entry, actual high, nonoverlapping inspection, mobile and desktop')
if __name__=='__main__':main()
