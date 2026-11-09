"""Both dashboard status controls and help use the same synthetic session."""
import sys,threading
from datetime import datetime,timezone
sys.path[:0]=['.','tests']
import app
from test_portfolio_value_chart import PortfolioValueChart
from playwright.sync_api import sync_playwright,expect

case=PortfolioValueChart();case.setUp()
server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
threading.Thread(target=server.serve_forever,daemon=True).start()
now=datetime.now(timezone.utc).isoformat()
session={'watch_id':'synthetic-status','status':'ACTIVE','signal':'SELL','display_status':'SÆLGSSIGNAL','request':{'ticker':'SYNTHETIC','quote_currency':'USD'},'last_calculation_at':now,'warmup':{'analysis_only':True,'count':1,'required':34,'complete':False},'latest_calculation':{'signal':'SELL','reason_codes':['EXIT_RULES','TRAILING_EXIT'],'calculation_timestamp':now,'data_timestamp':now,'supporting_metrics':{'distance_high_pct':'-3'}},'data_status':{}}
try:
 with sync_playwright() as pw:
  browser=pw.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
  page=browser.new_page(viewport={'width':1300,'height':900});errors=[];writes=[]
  page.on('pageerror',lambda e:errors.append(str(e)))
  page.on('request',lambda r:writes.append(r.url) if '/api/trade/' in r.url else None)
  page.route('**/api/v1/hotwatch/sessions/synthetic-status?is_test=false',lambda r:r.fulfill(json={'session':session}))
  page.goto(f'http://127.0.0.1:{server.server_port}')
  page.locator('#login-form [name=password]').fill('test-password-long-enough');page.locator('#login-form button').click()
  page.locator('.dashboard-v1').wait_for()
  def render():
   page.evaluate('''([s,at])=>{
    state.dashboard.positions=[{key:'synthetic-row',portfolio_id:1,portfolio_name:'Syntetisk depot',ticker:'SYNTHETIC',name:'Syntetisk testposition',quantity:'40',price:{amount:'0.3',currency:'USD'},value:{amount:'12',currency:'USD'},snapshot_at:at,unrealized:{amount:'-1',currency:'USD'},unrealized_percent:'-8',conflicts:[],analysis_freshness:{},verification:'broker_snapshot',hot_watch:{session:s}}];
    state.test_trade_signal=null;render();
   }''',[session,now])
  for width in (1300,390):
   page.set_viewport_size({'width':width,'height':900});render()
   buttons=page.locator('[data-trade-watch="synthetic-status"]')
   expect(buttons).to_have_count(2)
   for i in range(2):expect(buttons.nth(i)).to_have_text('SÆLGSSIGNAL →')
   helps=page.locator('[data-explain-watch="synthetic-status"]');expect(helps).to_have_count(2)
   for cell in page.locator('.dash-watch').all():expect(cell).not_to_contain_text('WARMUP')
   for i in range(2):
    helps.nth(i).click();dialog=page.locator('#signal-explanation-dialog')
    expect(dialog).to_contain_text('Aktuel status: SÆLGSSIGNAL')
    expect(dialog).to_contain_text('ikke afkast siden dit køb')
    page.locator('[data-explanation-close]').click()
  session.update(status='DEGRADED',signal='NO_DATA',display_status='DATA FOR GAMLE',display_reason_codes=['DATA_STALE'])
  render();expect(page.locator('[data-trade-watch="synthetic-status"]')).to_have_count(0)
  expect(page.locator('[data-explain-watch="synthetic-status"]')).to_have_count(1)
  page.locator('[data-explain-watch="synthetic-status"]').click()
  expect(page.locator('#signal-explanation-dialog')).to_contain_text('Aktuel status: DATA FOR GAMLE')
  expect(page.locator('#signal-explanation-dialog')).to_contain_text('Den seneste beregning er ikke det aktuelle signal')
  assert not errors,errors
  assert not writes,writes
  browser.close()
 print('PASS: same SELL and help in both tables on desktop/mobile; stale status refreshes help; no trade requests')
finally:
 server.shutdown();server.server_close();case.tearDown()
