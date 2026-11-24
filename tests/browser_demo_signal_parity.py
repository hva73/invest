"""Actual offline demo route, shared signal renderer. No broker or production."""
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
   page=browser.new_page(viewport={'width':390,'height':850},is_mobile=True,has_touch=True)
   errors=[];requests=[]
   page.on('pageerror',lambda e:errors.append(str(e)))
   page.on('request',lambda r:requests.append(r.url))
   page.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin+'/') else route.abort())
   page.goto(origin+'/demo')
   expect(page.locator('.demo-banner')).to_be_visible()
   expect(page.locator('.dashboard-v1')).to_be_visible(timeout=30000)
   dialog=page.locator('#engine-dialog')
   for width in (320,390,768):
    page.set_viewport_size({'width':width,'height':850})
    for side,ticker in [('BUY','NOVOB'),('SELL','TSLA')]:
     page.evaluate("(id)=>window.EngineUI.openNotification(id)",'demo-'+ticker)
     expect(dialog).to_be_visible()
     expect(dialog.locator('.market-price')).to_be_visible(timeout=15000)
     expect(dialog.locator('.market-axis span').first).to_have_text('00:00')
     expect(dialog.locator('.market-peak-marker')).to_have_count(1)
     expect(dialog.locator('.market-entry-marker')).to_have_count(1 if side=='SELL' else 0)
     expect(dialog.locator('.signal-mobile-metrics > div small')).to_have_text(['År','Måned','Dag'])
     action=dialog.get_by_role('button',name='Køb' if side=='BUY' else 'Sælg',exact=True)
     expect(action).to_be_visible();expect(action).to_be_enabled()
     assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
     if width<=700:
      # Use the actual data warning when present; exercise the same real DOM
      # with deterministic warning evidence even when fixture freshness changes.
      injected=dialog.evaluate("""d=>{
       const slot=d.querySelector('.market-slot');
       if(slot.querySelector('.market-warning'))return false;
       const warning=document.createElement('small');warning.className='market-warning';
       warning.textContent='Forældede data (syntetisk QA)';
       slot.append(warning);return true;
      }""")
      warning=dialog.locator('.market-slot > .market-warning')
      expect(warning).to_be_visible()
      ticker=dialog.locator('.signal-mobile-instrument > strong').bounding_box()
      quote=dialog.locator('.market-quote').bounding_box()
      notice=warning.bounding_box()
      assert ticker and quote and notice and notice['y']>=max(ticker['y']+ticker['height'],quote['y']+quote['height'])-1,('mobile warning overlaps quote/ticker',width,side,ticker,quote,notice)
      assert warning.inner_text().strip(), 'data-quality warning must remain legible'
      if injected:warning.evaluate('e=>e.remove()')
     shot=os.environ.get('ESCAPE_SCREENSHOTS')
     if shot:page.screenshot(path=f'{shot}/demo-signal-{side.lower()}-{width}.png')
     dialog.locator('[data-engine-close]:visible').first.click()
     expect(dialog).not_to_be_visible()
   assert not errors,errors
   assert all(u.startswith(origin+'/') and '/api/' not in u for u in requests),requests
   browser.close()
 finally:server.shutdown();server.server_close();case.tearDown()
 print('PASS: actual offline demo uses shared BUY/SELL renderer, midnight axis, real fixture Top/entry, no broker or API request')
if __name__=='__main__':main()
