"""Offline demo UI regression: percentage sale uses the selected direct holding."""
import os,sys,threading
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
import app
from test_portfolio_value_chart import PortfolioValueChart
from playwright.sync_api import sync_playwright,expect

def main():
 case=PortfolioValueChart();case.setUp()
 server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
 origin=f'http://127.0.0.1:{server.server_port}'
 try:
  with sync_playwright() as pw:
   browser=pw.chromium.launch(headless=True,**({} if os.environ.get('ESCAPE_PLAYWRIGHT_MANAGED') else {'executable_path':'/usr/bin/chromium'}))
   for width in (320,390,768):
    page=browser.new_page(viewport={'width':width,'height':850},is_mobile=True,has_touch=True)
    requests=[];errors=[]
    page.on('request',lambda r:requests.append(r.url));page.on('pageerror',lambda e:errors.append(str(e)))
    page.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin+'/') else route.abort())
    page.goto(origin+'/demo')
    expect(page.locator('.dashboard-v1')).to_be_visible(timeout=30000)
    # Exercise the actual signal -> trade review UI without confirming/sending.
    page.evaluate("window.EngineUI.openNotification('demo-TSLA')")
    dialog=page.locator('#engine-dialog');expect(dialog).to_be_visible()
    dialog.locator('[data-trade-watch=demo-TSLA]').click()
    quick=page.locator('#quick-trade-dialog');expect(quick).to_contain_text('Sælg · TSLA')
    quick.locator('[name=size]').fill('50');quick.locator('button[type=submit]').click()
    expect(quick.get_by_role('heading',name='Gennemgå salget')).to_be_visible()
    expect(quick.locator('.trade-review')).to_contain_text('Beholdning: 4 stk.')
    expect(quick.locator('.trade-review')).to_contain_text('Foreslået salg: 2 stk.')
    expect(quick.locator('#quick-trade-confirm')).not_to_be_checked()
    assert not errors,errors
    assert all(u.startswith(origin+'/') and '/api/' not in u for u in requests),requests
    page.close()
   browser.close()
 finally:server.shutdown();server.server_close();case.tearDown()
 print('PASS: actual offline mobile SELL review at 320/390/768; no request or send')
if __name__=='__main__':main()
