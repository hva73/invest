"""End-to-end proposal UI against synthetic Pluto; never contacts the provider."""
import sys,threading
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]));sys.path.insert(0,str(Path(__file__).resolve().parent))
import app
from test_trade_service import Trading
from playwright.sync_api import sync_playwright
from datetime import datetime,timezone

def main():
 case=Trading();case.setUp();payload={'source':'Synthetic','observed':datetime.now(timezone.utc).isoformat(),'kind':'portfolio','positions':[],'accounts':[],'pending_orders':[],'value':None,'errors':[],'complete':True,'orders_complete':True}
 server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
 try:
  with patch('trade_service.MCP',case.factory),patch('mcp_client.MCP',case.factory),patch('portfolio_data.read',return_value=payload),sync_playwright() as p:
   browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox']);page=browser.new_page(viewport={'width':1440,'height':1000});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
   page.goto(f'http://127.0.0.1:{server.server_port}');page.locator('#login-form [name=password]').fill('test-password-long-enough');page.locator('#login-form button').click();page.locator('#refresh-status[data-kind=success]').wait_for()
   page.locator('nav [data-view=trade]').click();page.locator('[data-trade-source]').first.click();page.locator('#broker-form [name=portfolio_id]').select_option(str(case.root));page.locator('#broker-form [name=currency]').select_option('DKK');page.locator('#broker-search').click();page.locator('#broker-assets option[value=asset-test]').wait_for(state='attached');page.locator('#broker-assets').select_option('asset-test')
   for name,value in {'size':'2','limit_price':'100.50'}.items():page.locator(f'#broker-form [name={name}]').fill(value)
   page.locator('#broker-form [name=order_type]').select_option('LIMIT');page.locator('#broker-form [name=time_in_force]').select_option('DAY');page.locator('#broker-form button.primary').click();page.locator('#broker-send').wait_for();assert not case.writes()
   page.locator('#broker-send').click();page.locator('#broker-status').filter(has_text='Bekræft først').wait_for();assert not case.writes()
   # Editing after an estimate invalidates the displayed review.
   page.locator('#broker-form [name=size]').fill('3');assert page.locator('#broker-send').count()==0;page.locator('#broker-form button.primary').click();page.locator('#broker-send').wait_for()
   for width in [320,390,430,768,1440]:page.set_viewport_size({'width':width,'height':900});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
   page.set_viewport_size({'width':390,'height':844});page.locator('#broker-confirm').check();page.screenshot(path='/tmp/escape-trade-review-mobile.png',full_page=True);page.locator('#broker-send').click();page.locator('#broker-status').filter(has_text='Forslaget er sendt til godkendelse').wait_for();assert len(case.writes())==1;assert case.writes()[0]['arguments']['orders'][0]['shares']=='3'
   page.locator('[data-broker-check]').first.click();page.locator('#broker-status').filter(has_text='ikke bevis for udført').wait_for();assert 'accepted' in page.locator('#broker-review').text_content()
   page.locator('nav [data-view=journal]').click();page.get_by_text('Forslagsjournal',exact=True).wait_for();assert 'Godkendt i Pluto · udførelse ikke bekræftet' in page.locator('#content').inner_text();assert 'trade-source' in page.locator('#content').inner_text();assert len(case.writes())==1
   before=len(case.writes());assert page.request.post(f'http://127.0.0.1:{server.server_port}/api/trade/send',data={'id':1,'confirm':True}).status==403;assert len(case.writes())==before
   outsider=browser.new_context();assert outsider.request.post(f'http://127.0.0.1:{server.server_port}/api/trade/history',data={}).status==401;outsider.close()
   assert not errors,errors;browser.close()
  print('PASS: report-to-proposal, explicit asset selection, live synthetic estimate, review invalidation, confirmation required, single proposal call, status distinct from fill, journal and 320–1440px')
 finally:server.shutdown();server.server_close();case.tearDown()
if __name__=='__main__':main()
