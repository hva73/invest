"""Keyboard disclosure regression using the actual app, synthetic demo only."""
import os,sys,threading
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
import app
from test_portfolio_value_chart import PortfolioValueChart
from playwright.sync_api import sync_playwright,expect

def main():
 case=PortfolioValueChart();case.setUp()
 server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
 threading.Thread(target=server.serve_forever,daemon=True).start()
 origin=f'http://127.0.0.1:{server.server_port}'
 try:
  with sync_playwright() as pw:
   browser=pw.chromium.launch(headless=True,**({} if os.environ.get('ESCAPE_PLAYWRIGHT_MANAGED') else {'executable_path':'/usr/bin/chromium'}))
   for width,height in ((320,700),(390,844),(844,390),(768,1024),(1440,900)):
    page=browser.new_page(viewport={'width':width,'height':height})
    page.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin+'/') and '/api/' not in r.request.url else r.abort())
    page.goto(origin+'/demo')
    expect(page.locator('.dashboard-v1')).to_be_visible(timeout=30000)
    more=page.locator('#mobile-more');panel=page.locator('#mobile-more-panel')
    radar=panel.locator('[data-view=radar]');sectors=page.locator('nav > [data-view=sectors]')
    sectors.focus();page.keyboard.press('Tab')
    if width<=900:
     expect(more).to_be_focused()
     expect(panel).to_be_hidden()
     page.keyboard.press('Enter');expect(panel).to_be_visible()
     page.keyboard.press('Tab')
     assert radar.evaluate('e=>e===document.activeElement'),'disclosure tab skips first menu link'
     page.keyboard.press('Escape');expect(panel).to_be_hidden();expect(more).to_be_focused()
     page.keyboard.press('Space');expect(panel).to_be_visible()
     page.keyboard.press('Tab');expect(radar).to_be_focused()
     page.keyboard.press('Enter');expect(panel).to_be_hidden()
    else:
     expect(more).to_be_hidden();expect(radar).to_be_focused()
    page.close()
   browser.close()
 finally:server.shutdown();server.server_close();case.tearDown()
 print('PASS: keyboard More disclosure portrait/landscape/tablet and unchanged desktop tab order')
if __name__=='__main__':main()
