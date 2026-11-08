import sys,threading
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
import app
from test_portfolio_value_chart import PortfolioValueChart
from playwright.sync_api import sync_playwright,expect
case=PortfolioValueChart();case.setUp();server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
try:
 with sync_playwright() as pw:
  browser=pw.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox']);page=browser.new_page(viewport={'width':390,'height':844});calls=[];errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
  def preview(route):
   data=route.request.post_data_json;calls.append(('preview',data))
   if data['size']=='500':route.fulfill(status=409,json={'code':'insufficient_buying_power','available':'125.50','currency':'EUR','error':'Ikke nok købekraft'})
   else:route.fulfill(json={'read_only':True})
  page.route('**/api/trade/preview',preview)
  def estimate(route):
   data=route.request.post_data_json;calls.append(('estimate',data))
   if data['size']=='500':route.fulfill(status=409,json={'code':'insufficient_buying_power','available':'125.50','currency':'EUR','error':'Ikke nok købekraft'})
   else:route.fulfill(json={'proposal':{'id':1,'status':'estimated','review_token':'synthetic'}})
  page.route('**/api/trade/estimate',estimate);page.route('**/api/trade/send',lambda r:(calls.append(('send',r.request.post_data_json)),r.fulfill(json={'proposal':{'status':'sent'}})))
  page.goto(f'http://127.0.0.1:{server.server_port}');page.locator('#login-form [name=password]').fill('test-password-long-enough');page.locator('#login-form button').click();expect(page.locator('#profile-open')).to_be_visible()
  page.evaluate("pid=>window.TradeUI.openQuick({report_id:'@manual-buy',ticker:'TEST',asset_id:'asset-test',portfolio_id:pid,signal:'BUY'})",case.root)
  dialog=page.locator('#quick-trade-dialog');dialog.locator('[name=currency]').select_option('EUR');dialog.locator('[name=size]').fill('500');expect(dialog.locator('#quick-buying-power')).to_contain_text('125,50 EUR');assert [x[0] for x in calls]==['preview'];dialog.locator('[type=submit]').click();assert not any(x[0] in ('estimate','send') for x in calls)
  dialog.locator('[data-use-buying-power]').click();expect(dialog.locator('[name=size]')).to_have_value('125,50');assert not any(x[0]=='send' for x in calls)
  dialog.locator('[type=submit]').click();expect(dialog).to_contain_text('Åbn Pluto');assert calls[-2][1]['size']=='125.50' and calls[-2][1]['currency']=='EUR' and calls[-1][0]=='send';assert not errors,errors
  browser.close();print('PASS: shortfall prompt and explicit retry in selected currency, no automatic order')
finally:server.shutdown();server.server_close();case.tearDown()
