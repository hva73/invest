"""Browser E2E simulation: admin TEST SELL → approved signal modal → existing Pluto draft, no broker writes."""
import os,sys,threading,time
from datetime import datetime,timezone
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
import app
from test_portfolio_value_chart import PortfolioValueChart
from playwright.sync_api import sync_playwright,expect


def main():
 case=PortfolioValueChart();case.setUp()
 server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
 thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
 try:
  with sync_playwright() as pw:
   browser=pw.chromium.launch(headless=True,args=['--no-sandbox'],
     **({} if os.environ.get('ESCAPE_PLAYWRIGHT_MANAGED') else {'executable_path':'/usr/bin/chromium'}))
   page=browser.new_page(viewport={'width':390,'height':700},is_mobile=True,has_touch=True)
   errors=[];api_writes=[]
   page.on('pageerror',lambda e:errors.append(str(e)))
   page.on('request',lambda r:api_writes.append(r.url) if '/api/trade/send' in r.url else None)
   page.on('dialog',lambda d:d.accept())
   page.goto('http://127.0.0.1:'+str(server.server_port)+'/')
   page.locator('#login-form [name=password]').fill('test-password-long-enough')
   page.locator('#login-form button').click()
   page.locator('.dashboard-v1').wait_for()
   base=page.evaluate('structuredClone(state)')
   now=datetime.now(timezone.utc).isoformat()
   holding={'key':'manual-test','portfolio_id':case.root,'portfolio_name':'Root','portfolio_kind':'portfolio',
    'asset_id':'caba-asset-id','ticker':'CABA','name':'Cabaletta Bio, Inc. Common Stock','quantity':'10',
    'price':{'amount':'1.29','currency':'USD'},'value':{'amount':'12.90','currency':'USD'},
    'average_entry':{'amount':'1.37','currency':'USD'},'unrealized':{'amount':'-0.8','currency':'USD'},
    'unrealized_percent':'-5.84','daily':{'percent':'0.78','amount':'0.01','currency':'USD'},
    'snapshot_at':now,'verification':'broker_snapshot','hot_watch':{},'conflicts':[]}
   base['dashboard']['positions']=[holding]
   base['portfolios']=[{'id':case.root,'name':'Root','source':'pluto','kind':'portfolio','active':True,'can_trade':True}]
   base['test_trade_signal']={'portfolio_id':case.root,'ticker':'CABA','side':'SELL','expires':time.time()+900}
   page.route('**/api/state',lambda route:route.fulfill(json=base))
   def create(route):
    assert route.request.post_data_json=={'ticker':'CABA'}
    route.fulfill(json={'ticker':'CABA','side':'SELL','quantity':'1','broker_order_created':False,'push':{'sent':1,'failed':0}})
   page.route('**/api/admin/test-sell-signal',create)
   page.evaluate("view='settings';render()")
   expect(page.locator('#test-sell-start')).to_be_visible()
   page.locator('#test-sell-start').click()
   signal=page.locator('#engine-dialog')
   expect(signal).to_be_visible()
   expect(signal).to_contain_text('FIKTIVT TESTSIGNAL')
   expect(signal).to_contain_text('CABA')
   expect(signal.locator('.signal-mobile-metrics')).to_contain_text('Dagsændring')
   expect(signal.locator('.signal-mobile-metrics')).to_contain_text('Måned')
   expect(signal.locator('.signal-mobile-metrics')).to_contain_text('År')
   expect(signal.locator('[data-trade-test-buy]')).to_be_visible()
   Path('visual-review').mkdir(exist_ok=True)
   page.screenshot(path='visual-review/manual-caba-sell-test-390.png',full_page=True)
   signal.locator('[data-trade-test-buy]').click()
   expect(page.locator('#quick-trade-dialog')).to_be_visible()
   expect(page.locator('#quick-trade-dialog')).to_contain_text('CABA')
   assert not api_writes,api_writes
   # A push click only opens the isolated test, never an active motor session.
   page.goto('http://127.0.0.1:'+str(server.server_port)+'/?test_sell=1')
   expect(page.locator('#engine-dialog')).to_be_visible()
   expect(page.locator('#engine-dialog')).to_contain_text('FIKTIVT TESTSIGNAL')
   assert not api_writes,api_writes
   assert not errors,errors
   browser.close()
 finally:
  server.shutdown();case.tearDown()
 print('PASS: admin fixture, mobile push deep link, approved SELL dialog, real Pluto draft UI, no order')


if __name__=='__main__':main()
