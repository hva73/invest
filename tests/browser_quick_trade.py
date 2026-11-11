import os
"""Synthetic end-to-end interaction; all trade endpoints are mocked."""
import sys,threading
sys.path[:0]=['.','tests']
import app
from test_portfolio_value_chart import PortfolioValueChart
from playwright.sync_api import sync_playwright,expect
case=PortfolioValueChart();case.setUp()
from tasks.pepe_test_signal import enable
enable(app.DB,'owner','Root')
server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
try:
 with sync_playwright() as p:
  browser=(p.chromium.launch(headless=True) if os.environ.get('ESCAPE_PLAYWRIGHT_MANAGED')=='1' else p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox']))
  page=browser.new_page(viewport={'width':390,'height':844});errors=[];calls=[];page.on('pageerror',lambda e:errors.append(str(e)))
  def estimate(route):
   data=route.request.post_data_json;calls.append(('estimate',data));sell=data['size_mode']=='percent'
   order={'assetId':'asset-test','side':'SELL' if sell else 'BUY','shares':'1' if sell else None,'amount':None if sell else data['size'],'currency':data['currency'],'orderType':'MARKET','timeInForce':'DAY'}
   proposal={'id':1,'status':'estimated','review_token':'synthetic','portfolio_id':case.root,'kind':'direct','payload':{'orders':[order]},'asset':{'asset':{'name':'Syntetisk aktie','isin':'TEST'}},'estimate':{'quote':{'estimatedAmount':'100','currency':'DKK'},'active_orders':[]},'sell_basis':{'quantity':'2','percentage':data['size'],'shares':'1'} if sell else None}
   route.fulfill(json={'proposal':proposal})
  def send(route):
   calls.append(('send',route.request.post_data_json));route.fulfill(json={'proposal':{'status':'sent'}})
  page.route('**/api/trade/estimate',estimate);page.route('**/api/trade/send',send)
  def review_and_send(dialog):
   before=len([x for x in calls if x[0]=='send'])
   dialog.locator('button[type=submit]').click()
   expect(dialog.locator('#quick-trade-review')).to_contain_text('Gennemgå')
   assert len([x for x in calls if x[0]=='send'])==before
   dialog.locator('#quick-trade-confirm').check();dialog.locator('[data-quick-send]').click()
   expect(dialog).to_contain_text('Åbn Pluto')
   assert len([x for x in calls if x[0]=='send'])==before+1
  page.route('**/api/trade/search',lambda route:route.fulfill(json={'assets':[{'asset_id':'asset-test','name':'Synthetic PEPE','ticker':'PEPE','isin':'','currency':'USD'}]}))
  page.route('**/api/v1/hotwatch/sessions/watch-1?*',lambda route:route.fulfill(json={'session':{'signal':'BUY','display_status':'KØBSSIGNAL','data_status':{'bid':'10.1','ask':'10.2','currency':'USD','quote_status':'STALE','bid_at':'2026-11-08T09:00:00Z','ask_at':'2026-11-08T09:00:01Z'},'request':{'ticker':'TEST','asset_id':'asset-test'},'latest_calculation':{'signal':'BUY','reason_codes':['ENTRY_RULES'],'supporting_metrics':{'return_3_pct':'2.5','interval_volume':'1200','relative_volume':'1.4','spread_pct':'0.25'}}}}))
  page.goto(f'http://127.0.0.1:{server.server_port}');page.locator('#login-form [name=password]').fill('test-password-long-enough');page.locator('#login-form button').click();page.locator('.dashboard-v1').wait_for()
  page.evaluate("pid => state.dashboard.positions.push({portfolio_id:pid,ticker:'PEPE',asset_id:'asset-test',verification:'broker_snapshot'})",case.root)
  expect(page.locator('.dash-attention [data-explain-test]')).to_be_visible();page.locator('.dash-attention [data-explain-test]').click();expect(page.locator('#signal-explanation-dialog')).to_contain_text('ikke på en markedsberegning');page.locator('[data-explanation-close]').click()
  expect(page.locator('.dash-attention [data-trade-test-buy]')).to_be_visible();page.locator('.dash-attention [data-trade-test-buy]').click();dialog=page.locator('#quick-trade-dialog');expect(dialog).to_be_visible()
  expect(dialog.locator('[name=size]')).to_have_value('');dialog.locator('[name=size]').fill('20');expect(dialog.locator('[name=portfolio_id]')).to_have_value(str(case.root))
  expect(dialog.locator('#quick-trade-query')).to_have_count(0);expect(dialog.locator('[name=asset_id]')).to_have_value('asset-test')
  assert not calls
  review_and_send(dialog)
  assert calls[-2][1]['report_id']=='@manual-buy' and calls[-2][1]['size']=='20' and calls[-1][0]=='send'
  dialog.locator('[data-quick-close]').click()
  page.evaluate("() => {const b=document.createElement('button');b.dataset.tradeWatch='watch-1';b.textContent='KØB';document.getElementById('content').append(b)}")
  expect(page.locator('[data-explain-watch="watch-1"]')).to_be_visible();page.locator('[data-explain-watch="watch-1"]').click();expect(page.locator('#signal-explanation-dialog')).to_contain_text('betingelser for køb er opfyldt');expect(page.locator('#signal-explanation-dialog')).to_contain_text('2,5%');expect(page.locator('#signal-explanation-dialog')).to_contain_text('1.200');expect(page.locator('#signal-explanation-dialog')).to_contain_text('0,25 %');expect(page.locator('#signal-explanation-dialog')).to_contain_text('10,1 USD');expect(page.locator('#signal-explanation-dialog')).to_contain_text('for gamle');page.locator('[data-explanation-close]').click()
  for side,size,expected in [('BUY','1','shares'),('SELL','50','percent')]:
   page.evaluate("""([side,pid])=>window.TradeUI.openQuick({report_id:'@hotwatch',candidate_id:'watch-1',ticker:'TEST',asset_id:'asset-test',signal:side,risk_plan:side==='BUY'?{portfolio_id:pid,budget_dkk:'100',quantity:'1',limit_price:'12',stop_price:'10'}:null})""",[side,case.root])
   dialog=page.locator('#quick-trade-dialog');expect(dialog).to_be_visible()
   if side=='BUY':
    expect(dialog.locator('[name=size]')).to_be_disabled();expect(dialog).to_contain_text('Din kontrollerede købsplan')
   else:dialog.locator('[name=size]').fill(size);dialog.locator('[name=currency]').select_option('DKK')
   count=len([x for x in calls if x[0]=='send'])
   review_and_send(dialog)
   assert calls[-2][1]['size_mode']==expected and calls[-2][1]['size']==size
   if side=='BUY':assert calls[-2][1]['order_type']=='LIMIT' and calls[-2][1]['limit_price']=='12'
   assert len([x for x in calls if x[0]=='send'])==count+1
   dialog.locator('[data-quick-close]').click()
  page.evaluate("""() => {
   state.report_desk=state.report_desk||{};state.report_desk.candidates=[{report_id:'report-1',candidate:{candidate_id:'candidate-1',ticker:'TEST',asset_id:'asset-test',signal:'KØB'}}];
   const b=document.createElement('button');b.dataset.tradeReport='report-1';b.dataset.tradeCandidate='candidate-1';b.textContent='KØB';document.getElementById('content').append(b);
  }""")
  page.locator('[data-trade-report="report-1"]').click();dialog=page.locator('#quick-trade-dialog');dialog.locator('[name=size]').fill('75');review_and_send(dialog)
  assert calls[-2][1]['report_id']=='report-1' and calls[-2][1]['candidate_id']=='candidate-1'
  dialog.locator('[data-quick-close]').click()
  enable(app.DB,'owner','Root',side='SELL');page.reload();page.locator('.dashboard-v1').wait_for()
  page.evaluate("pid => state.dashboard.positions.push({portfolio_id:pid,ticker:'PEPE',asset_id:'asset-test',verification:'broker_snapshot'})",case.root)
  page.locator('.dash-attention [data-trade-test-buy]').click();dialog=page.locator('#quick-trade-dialog');expect(dialog.locator('h2')).to_contain_text('Sælg')
  expect(dialog.locator('[name=size]')).to_have_value('');dialog.locator('[name=size]').fill('10');review_and_send(dialog)
  assert calls[-2][1]['report_id']=='@manual-sell' and calls[-2][1]['size_mode']=='percent' and calls[-2][1]['size']=='10'
  dialog.locator('[data-quick-close]').click()
  page.route('**/api/trade/estimate',lambda route:route.fulfill(json={'duplicate':True,'proposal':{'status':'sent'}}))
  page.evaluate("() => window.TradeUI.openQuick({report_id:'@manual-buy',ticker:'TEST',asset_id:'asset-test',signal:'BUY'})")
  dialog=page.locator('#quick-trade-dialog');dialog.locator('[name=size]').fill('20');sent_count=len([x for x in calls if x[0]=='send'])
  dialog.locator('button[type=submit]').click();expect(dialog).to_contain_text('Der er ikke sendt et nyt forslag')
  assert len([x for x in calls if x[0]=='send'])==sent_count
  dialog.locator('[data-quick-close]').click();page.locator('#mobile-more').click();page.locator('nav [data-view="trade"]').click()
  sample={'id':9,'status':'sent','intent_id':'synthetic-intent','report_id':'synthetic','portfolio_id':case.root,'kind':'direct','payload':{'orders':[{'assetId':'asset-test','side':'BUY','amount':'20','currency':'DKK','orderType':'MARKET','timeInForce':'DAY'}]},'asset':{'asset':{'name':'Test'}},'response':{'status':'CANCELLED'}}
  page.route('**/api/trade/history',lambda route:route.fulfill(json={'proposals':[sample]}))
  page.route('**/api/trade/cancel',lambda route:route.fulfill(json={'cancelled':True,'proposal':sample}))
  page.locator('details:has(#broker-history) > summary').click();page.locator('#broker-history').click();expect(page.locator('[data-broker-cancel="9"]')).to_be_visible()
  page.once('dialog',lambda d:d.accept());page.locator('[data-broker-cancel="9"]').click();expect(page.locator('#broker-status')).to_contain_text('trukket tilbage')
  assert not errors,errors
  browser.close()
 print('PASS: synthetic buy and percentage sell review and send flow on mobile')
finally:server.shutdown();server.server_close();case.tearDown()
