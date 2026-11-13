"""Graph point fidelity and pointer interaction using synthetic test data."""
import os,re,sys,threading
from pathlib import Path
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
import app
from desktop_fixture import seed
from test_portfolio_value_chart import PortfolioValueChart
from playwright.sync_api import sync_playwright,expect

def main():
 case=PortfolioValueChart();case.setUp();seed(case)
 server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);threading.Thread(target=server.serve_forever,daemon=True).start();base=f'http://127.0.0.1:{server.server_port}'
 try:
  with patch('mcp_client.MCP.request',side_effect=AssertionError('No broker calls')),sync_playwright() as p:
   browser=p.chromium.launch(headless=True)
   for width,touch in [(1440,False),(390,True)]:
    context=browser.new_context(viewport={'width':width,'height':900},is_mobile=touch,has_touch=touch);page=context.new_page();errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
    assert page.request.get(base+'/api/dashboard/portfolio-history').status==401
    page.goto(base);page.locator('#login-form [name=password]').fill('test-password-long-enough');page.locator('#login-form button').click();expect(page.locator('.dashboard-v1')).to_be_visible()
    page.locator('[data-dashboard-range=week]').click();status=page.locator('.dash-history-status');expect(status).to_be_visible()
    response=page.request.get(base+'/api/dashboard/portfolio-history?period=week');assert response.ok
    data=response.json();valid=[x for x in data['points'] if x['reported_result'] is not None];assert len(valid)>70
    assert page.locator('#dashboard-value-chart .dash-chart-point').count()==len(valid),(width,len(valid),page.locator('#dashboard-value-chart .dash-chart-point').count())
    assert str(data['total'])+' registreringer' in status.inner_text()
    assert page.request.get(base+'/api/dashboard/portfolio-history?period=week&scope=wrong').status==400
    svg=page.locator('#dashboard-value-chart .dash-chart-svg');svg.scroll_into_view_if_needed();box=svg.bounding_box();x=box['x']+box['width']*.55;y=box['y']+box['height']*.5
    if touch:page.touchscreen.tap(x,y)
    else:page.mouse.move(x,y)
    tip=page.locator('#dashboard-value-chart .dash-chart-tooltip');expect(tip).to_be_visible();expect(tip.locator('[data-chart-date]')).to_have_text(re.compile(r'^\d{2}\.\d{2}\.\d{2}$'));expect(tip.locator('[data-chart-value]')).not_to_have_text('—');expect(tip.locator('[data-chart-result]')).not_to_have_text('—')
    assert not errors,errors;context.close()
   browser.close()
  print('PASS: authenticated full history compared with rendered points, desktop mouse and mobile touch')
 finally:server.shutdown();server.server_close();case.tearDown()
if __name__=='__main__':main()
