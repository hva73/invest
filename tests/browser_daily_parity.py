"""Browser verification of daily results with synthetic Pluto-shaped data."""
import os,sys,threading
from pathlib import Path
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
import app
from desktop_fixture import seed
from test_portfolio_value_chart import PortfolioValueChart
from playwright.sync_api import sync_playwright,expect

def main():
 case=PortfolioValueChart();case.setUp();seed(case)
 server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
 try:
  with patch('mcp_client.MCP.request',side_effect=AssertionError('No broker calls')),sync_playwright() as p:
   browser=p.chromium.launch(headless=True)
   for width in (390,1440):
    page=browser.new_page(viewport={'width':width,'height':900})
    page.goto(f'http://127.0.0.1:{server.server_port}');page.locator('#login-form [name=password]').fill('test-password-long-enough');page.locator('#login-form button').click();expect(page.locator('.dashboard-v1')).to_be_visible()
    for freshness,offset,basis,visible in [('unknown',-1000,'pluto_reported_daily_change',True),('unknown',-301000,'pluto_reported_daily_change',False),('unknown',60000,'pluto_reported_daily_change',False),('error',-1000,'pluto_reported_daily_change',False),('stale',-1000,'pluto_reported_daily_change',False),('unknown',-1000,'other',False)]:
     page.evaluate("""([freshness,offset,basis]) => {
      const row=state.dashboard.positions[0];row.price_time=null;row.price_freshness={state:freshness};row.verification='broker_snapshot';row.daily={to:new Date(Date.now()+offset).toISOString(),basis,percent:'2',amount:'1',currency:row.price.currency};state.dashboard.positions=[row];state.dashboard.overview_positions=[row];
      document.querySelector('#content').innerHTML=window.DashboardUI.render(state);
     }""",[freshness,offset,basis])
     if width==390: result=page.locator('.mobile-holding-daily').first
     else: result=page.locator('.dash-row .dash-day-desktop').first
     expect(result).to_be_visible();expect(result).to_contain_text('+2,00 %' if visible else '—')
     if visible:
      page.evaluate("""() => {const n=document.createElement('div');n.textContent='FIKTIVE TESTDATA';Object.assign(n.style,{position:'fixed',top:'0',left:'0',zIndex:'99999',background:'#b6eddf',color:'#102c29',fontWeight:'bold',padding:'6px 12px'});document.body.append(n)}""")
      Path('daily-parity-screens').mkdir(exist_ok=True);page.screenshot(path=f'daily-parity-screens/oversigt-{width}.png',full_page=True)
    page.close()
   browser.close()
 finally:server.shutdown();server.server_close();case.tearDown()
 print('PASS: same Pluto daily value and invalid-data handling on mobile and desktop')
if __name__=='__main__':main()
