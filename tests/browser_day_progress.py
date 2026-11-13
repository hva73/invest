"""Period captions for real dashboard rendering with disposable data."""
import sys,threading
from pathlib import Path
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
import app
from playwright.sync_api import sync_playwright,expect
from test_portfolio_value_chart import PortfolioValueChart

case=PortfolioValueChart();case.setUp()
server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
threading.Thread(target=server.serve_forever,daemon=True).start()
try:
 with patch('mcp_client.MCP.request',side_effect=AssertionError('No broker calls')),sync_playwright() as pw:
  browser=pw.chromium.launch(headless=True)
  for width,height in ((320,700),(390,844),(844,390),(1280,800)):
   page=browser.new_page(viewport={'width':width,'height':height})
   page.goto(f'http://127.0.0.1:{server.server_port}/')
   page.locator('#login-form [name=password]').fill('test-password-long-enough');page.locator('#login-form button').click()
   chart=page.locator('#dashboard-value-chart');expect(chart).to_be_visible()
   expect(chart).to_contain_text('Dagens udvikling')
   expect(chart).to_contain_text('Ikke nok historik');expect(chart).not_to_contain_text('siden første måling')
   for period in ('week','month','year'):
    chart.locator(f'[data-dashboard-range={period}]').click()
    expect(chart).to_contain_text('Udvikling i valgt periode')
    expect(chart).not_to_contain_text('Dagens udvikling')
   chart.locator('[data-dashboard-range=day]').click();expect(chart).to_contain_text('Dagens udvikling')
   assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),(width,height)
   page.close()
  browser.close()
 print('PASS: today and other period captions, unavailable history, portrait/landscape/desktop')
finally:
 server.shutdown();server.server_close();case.tearDown()
