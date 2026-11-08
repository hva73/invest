import sys,threading
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
  browser=pw.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox']);page=browser.new_page(viewport={'width':390,'height':700});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
  page.goto(f'http://127.0.0.1:{server.server_port}');page.locator('#login-form [name=password]').fill('test-password-long-enough');page.locator('#login-form button').click()
  row=page.locator('.dash-row').filter(has=page.locator('.dash-instrument strong',has_text='TSLA'));row.locator('[data-dashboard-open]').first.click();dialog=page.locator('#dashboard-detail');expect(dialog).to_be_visible()
  buy=dialog.locator('[data-asset-trade=BUY]');sell=dialog.locator('[data-asset-trade=SELL]');expect(buy).to_be_visible();expect(sell).to_be_enabled()
  dialog.evaluate('(n)=>n.scrollTop=0');box1=buy.bounding_box();dialog.evaluate('(n)=>n.scrollTop=n.scrollHeight');box2=buy.bounding_box();assert abs(box1['y']-box2['y'])<8,(box1,box2)
  sell.click();quick=page.locator('#quick-trade-dialog');expect(quick).to_contain_text('Sælg · TSLA');assert quick.locator('[name=size]').input_value()=='';assert quick.locator('[name=asset_id]').input_value()!='';quick.locator('[data-quick-close]').click()
  buy.click();expect(quick).to_contain_text('Køb · TSLA');assert quick.locator('[name=size]').input_value()=='';quick.locator('[data-quick-close]').click();dialog.locator('[data-dashboard-close]').click()
  page.evaluate('''() => {const host=document.createElement('dialog');host.id='test-unowned';document.body.append(host);host.innerHTML=window.TradeUI.assetActions({ticker:'NY',assetId:'unowned-id'});host.showModal()}''')
  assert page.locator('#test-unowned [data-asset-trade=BUY]').count()==1;assert page.locator('#test-unowned [data-asset-trade=SELL]').count()==0
  page.locator('#test-unowned [data-asset-trade=BUY]').click();expect(quick).to_contain_text('Køb · NY');assert quick.locator('[name=asset_id]').input_value()=='unowned-id';assert not errors,errors
  browser.close();print('PASS: manual buy/sell, existing position, unowned asset and mobile sticky action bar')
finally:server.shutdown();server.server_close();case.tearDown()
