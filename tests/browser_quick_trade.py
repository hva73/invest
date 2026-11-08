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
  browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
  page=browser.new_page(viewport={'width':390,'height':844});errors=[];calls=[];page.on('pageerror',lambda e:errors.append(str(e)))
  def estimate(route):
   data=route.request.post_data_json;calls.append(('estimate',data));sell=data['size_mode']=='percent'
   order={'assetId':'asset-test','side':'SELL' if sell else 'BUY','shares':'1' if sell else None,'amount':None if sell else data['size'],'currency':data['currency'],'orderType':'MARKET','timeInForce':'DAY'}
   proposal={'id':1,'status':'estimated','review_token':'synthetic','portfolio_id':case.root,'kind':'direct','payload':{'orders':[order]},'asset':{'asset':{'name':'Syntetisk aktie','isin':'TEST'}},'estimate':{'quote':{'estimatedAmount':'100','currency':'DKK'}},'sell_basis':{'quantity':'2','percentage':data['size'],'shares':'1'} if sell else None}
   route.fulfill(json={'proposal':proposal})
  def send(route):
   calls.append(('send',route.request.post_data_json));route.fulfill(json={'proposal':{'status':'sent'}})
  page.route('**/api/trade/estimate',estimate);page.route('**/api/trade/send',send)
  page.route('**/api/trade/search',lambda route:route.fulfill(json={'assets':[{'asset_id':'asset-test','name':'Synthetic PEPE','ticker':'PEPE','isin':'','currency':'USD'}]}))
  page.route('**/api/v1/hotwatch/sessions/watch-1?*',lambda route:route.fulfill(json={'session':{'signal':'BUY','request':{'ticker':'TEST','asset_id':'asset-test'}}}))
  page.goto(f'http://127.0.0.1:{server.server_port}');page.locator('#login-form [name=password]').fill('test-password-long-enough');page.locator('#login-form button').click();page.locator('.dashboard-v1').wait_for()
  expect(page.locator('.dash-attention [data-trade-test-buy]')).to_be_visible();page.locator('.dash-attention [data-trade-test-buy]').click();dialog=page.locator('#quick-trade-dialog');expect(dialog).to_be_visible()
  expect(dialog.locator('[name=size]')).to_have_value('20');expect(dialog.locator('[name=portfolio_id]')).to_have_value(str(case.root))
  expect(dialog.locator('#quick-trade-query')).to_have_value('PEPE');dialog.locator('[data-quick-search]').click();dialog.locator('#quick-trade-assets').select_option('asset-test')
  dialog.locator('button[type=submit]').click();expect(dialog.locator('#quick-trade-confirm')).to_be_visible()
  assert calls[-1][1]['report_id']=='@manual-buy' and calls[-1][1]['size']=='20'
  assert not any(x[0]=='send' for x in calls);dialog.locator('[data-quick-close]').click()
  for side,size,expected in [('BUY','100,50','amount'),('SELL','50','percent')]:
   if side=='BUY':
    page.evaluate("() => {const b=document.createElement('button');b.dataset.tradeWatch='watch-1';b.textContent='KØB';document.body.append(b)}")
    page.locator('[data-trade-watch="watch-1"]').click()
   else:page.evaluate("side=>window.TradeUI.openQuick({report_id:'@hotwatch',candidate_id:'watch-1',ticker:'TEST',asset_id:'asset-test',signal:side})",side)
   dialog=page.locator('#quick-trade-dialog');expect(dialog).to_be_visible();dialog.locator('[name=size]').fill(size)
   dialog.locator('button[type=submit]').click();expect(dialog.locator('#quick-trade-confirm')).to_be_visible()
   assert calls[-1][1]['size_mode']==expected
   assert calls[-1][1]['size']==size.replace(',','.')
   count=len([x for x in calls if x[0]=='send'])
   dialog.locator('[data-quick-send]').click();expect(dialog.locator('#quick-trade-status')).to_contain_text('Bekræft først')
   assert len([x for x in calls if x[0]=='send'])==count
   dialog.locator('[name=size]').fill(size+'0');expect(dialog.locator('#quick-trade-confirm')).to_have_count(0)
   dialog.locator('[name=size]').fill(size);dialog.locator('button[type=submit]').click();expect(dialog.locator('#quick-trade-confirm')).to_be_visible()
   dialog.locator('#quick-trade-confirm').check();dialog.locator('[data-quick-send]').click();expect(dialog).to_contain_text('Åbn Pluto')
   dialog.locator('[data-quick-close]').click()
  assert len([x for x in calls if x[0]=='send'])==2
  page.evaluate('''() => {
   state.report_desk=state.report_desk||{};state.report_desk.candidates=[{report_id:'report-1',candidate:{candidate_id:'candidate-1',ticker:'TEST',asset_id:'asset-test',signal:'KØB'}}];
   const b=document.createElement('button');b.dataset.tradeReport='report-1';b.dataset.tradeCandidate='candidate-1';b.textContent='KØB';document.body.append(b);
  }''')
  page.locator('[data-trade-report="report-1"]').click();dialog=page.locator('#quick-trade-dialog');expect(dialog).to_be_visible()
  dialog.locator('[name=size]').fill('75');dialog.locator('button[type=submit]').click();expect(dialog.locator('#quick-trade-confirm')).to_be_visible()
  assert calls[-1][1]['report_id']=='report-1' and calls[-1][1]['candidate_id']=='candidate-1'
  dialog.locator('[data-quick-close]').click()
  assert len([x for x in calls if x[0]=='send'])==2
  page.locator('nav [data-view="trade"]').click();page.locator('[data-trade-manual-buy]').click()
  dialog=page.locator('#quick-trade-dialog');dialog.locator('#quick-trade-query').fill('PEPE');dialog.locator('[data-quick-search]').click()
  dialog.locator('#quick-trade-assets').select_option('asset-test');dialog.locator('[name=size]').fill('20')
  dialog.locator('button[type=submit]').click();expect(dialog.locator('#quick-trade-confirm')).to_be_visible()
  assert calls[-1][1]['report_id']=='@manual-buy' and calls[-1][1]['asset_id']=='asset-test' and calls[-1][1]['size']=='20'
  assert len([x for x in calls if x[0]=='send'])==2
  dialog.locator('[data-quick-close]').click()
  assert not errors,errors
  browser.close()
 print('PASS: synthetic buy and percentage sell review and send flow on mobile')
finally:server.shutdown();server.server_close();case.tearDown()
