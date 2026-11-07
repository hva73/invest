"""Browser smoke test of real-value portfolio chart using a disposable database."""
import threading
from datetime import datetime,timezone,timedelta
from unittest.mock import patch
import app,portfolio_data,portfolios
from test_portfolio_value_chart import PortfolioValueChart
from playwright.sync_api import sync_playwright,expect

def main():
 case=PortfolioValueChart();case.setUp()
 try:
  now=datetime.now(timezone.utc).replace(microsecond=0)
  case.save(case.root,'1000',now-timedelta(minutes=10),result='20');case.save(case.root,'1100',now,result='30')
  server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
  try:
   with patch('mcp_client.MCP.request',side_effect=AssertionError('No broker calls in browser test')),sync_playwright() as pw:
    browser=pw.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox']);page=browser.new_page(viewport={'width':1440,'height':1000});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(f'http://127.0.0.1:{server.server_port}');page.locator('#login-form [name=password]').fill('test-password-long-enough');page.locator('#login-form button').click()
    expect(page.locator('.dash-chart-svg')).to_be_visible();expect(page.locator('.dash-chart-change')).to_contain_text('+10,00')
    page.locator('[data-dashboard-range=year]').click();expect(page.locator('[data-dashboard-range=year]')).to_have_attribute('aria-pressed','true');expect(page.locator('.dash-chart-svg')).to_be_visible()
    for width in (320,390,768,1440):
     page.set_viewport_size({'width':width,'height':1000});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),width
     if width in (390,1440):page.locator('.dash-hero').screenshot(path=f'/tmp/escape-value-chart-{width}.png')
    assert not errors,errors;browser.close()
   print('PASS: recorded portfolio result chart, range selection, signs and mobile widths')
  finally:server.shutdown();server.server_close()
 finally:case.tearDown()
if __name__=='__main__':main()
