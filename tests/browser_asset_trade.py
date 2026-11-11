import os
import sys,threading
from datetime import datetime,timezone,timedelta
from pathlib import Path
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
import app
import test_design_v1_acceptance as fixture
from playwright.sync_api import sync_playwright,expect
case=fixture.DesignAcceptance();case.setUp()
server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
try:
 with patch('mcp_client.MCP.request',side_effect=AssertionError('No live broker calls')),sync_playwright() as pw:
  browser=(pw.chromium.launch(headless=True) if os.environ.get('ESCAPE_PLAYWRIGHT_MANAGED')=='1' else pw.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox']));page=browser.new_page(viewport={'width':390,'height':700});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
  page.goto(f'http://127.0.0.1:{server.server_port}');page.locator('#login-form [name=password]').fill('test-password-long-enough');page.locator('#login-form button').click()
  page.locator('.dashboard-v1').wait_for();page.evaluate('state.connection.connected=true')
  now=datetime.now(timezone.utc);series=[{'price':str(47+i),'epoch':(now-timedelta(hours=5-i)).timestamp(),'timestamp':(now-timedelta(hours=5-i)).isoformat(),'date':now.date().isoformat()} for i in range(6)]
  def quote(route):
   assert route.request.post_data_json.get('holding_asset_id'), 'Chart must use holding identity'
   route.fulfill(json={'asset_id':'synthetic-asset','ticker':'TSLA','name':'Synthetic stock','exchange':'NASDAQ','currency':'DKK','price':'52','price_time':now.isoformat(),'fetched_at':now.isoformat(),'daily_change_percent':'2','daily_change':'1','series':series})
  page.route('**/api/market/quote',quote)
  row=page.locator('.dash-holdings .dash-row').filter(has=page.locator('.dash-instrument strong',has_text='TSLA')).first
  page.set_viewport_size({'width':320,'height':700});row.scroll_into_view_if_needed()
  assert row.bounding_box()['height']<170,row.bounding_box()
  for left,right in [('.dash-instrument','.dash-value'),('.dash-instrument','.dash-pnl'),('.dash-watch','.dash-daily')]:
   if row.locator(left).count() and row.locator(right).count():
    a=row.locator(left).bounding_box();b=row.locator(right).bounding_box()
    assert a['x']+a['width']<=b['x']+1,(left,right,a,b)
  screenshot_dir=os.environ.get('ESCAPE_SCREENSHOTS')
  if screenshot_dir:
   Path(screenshot_dir).mkdir(parents=True,exist_ok=True);page.screenshot(path=str(Path(screenshot_dir)/'holdings-320.png'))
  page.set_viewport_size({'width':390,'height':700});row.locator('[data-dashboard-open]').first.click();dialog=page.locator('#dashboard-detail');expect(dialog).to_be_visible()
  
  graph=dialog.locator('.market-slot');expect(graph.locator('.market-line')).to_be_visible();graph.locator('[data-market-period=week]').click();expect(graph.locator('.market-line')).to_be_visible()
  boxes=[graph.locator(f'[data-market-period={p}]').bounding_box() for p in ('day','week','month','year')];assert max(b['y'] for b in boxes)-min(b['y'] for b in boxes)<2,boxes
  screenshot_dir=os.environ.get('ESCAPE_SCREENSHOTS')
  if screenshot_dir:
   Path(screenshot_dir).mkdir(parents=True,exist_ok=True);page.screenshot(path=str(Path(screenshot_dir)/'holding-390.png'))
  buy=dialog.locator('[data-asset-trade=BUY]');sell=dialog.locator('[data-asset-trade=SELL]');expect(buy).to_be_visible();expect(sell).to_be_enabled()
  dialog.evaluate('(n)=>n.scrollTop=0');box1=buy.bounding_box();dialog.evaluate('(n)=>n.scrollTop=n.scrollHeight');box2=buy.bounding_box();assert abs(box1['y']-box2['y'])<8,(box1,box2)
  sell.click();quick=page.locator('#quick-trade-dialog');expect(quick).to_contain_text('Sælg · TSLA');assert quick.locator('[name=size]').input_value()=='';assert quick.locator('[name=asset_id]').input_value()!='';quick.locator('[data-quick-close]').click()
  buy.click();expect(quick).to_contain_text('Køb · TSLA');
  if screenshot_dir:page.screenshot(path=str(Path(screenshot_dir)/'trade-390.png'))
  assert quick.locator('[name=size]').input_value()=='';quick.locator('[data-quick-close]').click();dialog.locator('[data-dashboard-close]').click()
  page.evaluate('''() => {const host=document.createElement('dialog');host.id='test-unowned';document.body.append(host);host.innerHTML=window.TradeUI.assetActions({ticker:'NY',assetId:'unowned-id'});host.showModal()}''')
  assert page.locator('#test-unowned [data-asset-trade=BUY]').count()==1;assert page.locator('#test-unowned [data-asset-trade=SELL]').count()==0
  page.locator('#test-unowned [data-asset-trade=BUY]').click();expect(quick).to_contain_text('Køb · NY');assert quick.locator('[name=asset_id]').input_value()=='unowned-id';assert not errors,errors
  browser.close();print('PASS: manual buy/sell, existing position, unowned asset and mobile sticky action bar')
finally:server.shutdown();server.server_close();case.tearDown()
