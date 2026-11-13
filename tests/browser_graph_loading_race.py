"""Synthetic touch/mouse inspection while full history loads asynchronously."""
import sys,threading,time
from pathlib import Path
from urllib.parse import urlsplit
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
import app
from desktop_fixture import seed
from test_portfolio_value_chart import PortfolioValueChart
from playwright.sync_api import sync_playwright,expect
class SlowHistory(app.Handler):
 def _get(self):
  if urlsplit(self.path).path=='/api/dashboard/portfolio-history':time.sleep(3)
  return super()._get()
def main():
 case=PortfolioValueChart();case.setUp();seed(case)
 server=app.ThreadingHTTPServer(('127.0.0.1',0),SlowHistory);threading.Thread(target=server.serve_forever,daemon=True).start()
 try:
  with patch('mcp_client.MCP.request',side_effect=AssertionError('No broker calls')),sync_playwright() as p:
   browser=p.chromium.launch(headless=True)
   for width,touch in [(1440,False),(390,True)]:
    context=browser.new_context(viewport={'width':width,'height':900},is_mobile=touch,has_touch=touch);page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(f'http://127.0.0.1:{server.server_port}');page.locator('#login-form [name=password]').fill('test-password-long-enough');page.locator('#login-form button').click();expect(page.locator('#dashboard-value-chart .dash-history-status')).to_be_visible(timeout=15000)
    page.locator('[data-dashboard-range=week]').click();assert page.locator('#dashboard-value-chart .dash-history-status').count()==0;curve=page.locator('#dashboard-value-chart .dash-chart-svg');curve.scroll_into_view_if_needed();box=curve.bounding_box();x=box['x']+box['width']*.55;y=box['y']+box['height']*.5
    if touch:page.touchscreen.tap(x,y)
    else:page.mouse.move(x,y)
    tip=page.locator('#dashboard-value-chart .dash-chart-tooltip');expect(tip).to_be_visible();date=tip.locator('[data-chart-date]').inner_text();value=tip.locator('[data-chart-value]').inner_text();assert date and value and value!='—'
    expect(page.locator('#dashboard-value-chart .dash-history-status')).to_be_visible(timeout=15000)
    expect(tip).to_be_visible();expect(tip.locator('[data-chart-date]')).to_have_text(date);expect(tip.locator('[data-chart-value]')).to_have_text(value)
    assert not errors,errors;context.close()
   browser.close()
 finally:server.shutdown();server.server_close();case.tearDown()
 print('PASS: inspected actual date and value persist across delayed history render on mobile and desktop')
if __name__=='__main__':main()
