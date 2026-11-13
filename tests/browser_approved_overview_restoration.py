"""Verify approved portfolio presentation with synthetic data."""
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
  with patch('mcp_client.MCP.request',side_effect=AssertionError('No provider calls')),sync_playwright() as p:
   browser=p.chromium.launch(headless=True)
   for width,touch in ((390,True),(1440,False)):
    page=browser.new_page(viewport={'width':width,'height':900},has_touch=touch);errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(f'http://127.0.0.1:{server.server_port}');page.locator('#login-form [name=password]').fill('test-password-long-enough');page.locator('#login-form button').click();expect(page.locator('.dashboard-v1')).to_be_visible()
    hero=page.locator('.dash-hero');expect(hero.locator('.dash-overview-updated')).to_be_visible();assert hero.locator('.dash-updated-mobile').count()==0
    expect(hero).not_to_contain_text('oplyst af Pluto');expect(hero).not_to_contain_text('af depotværdi');expect(hero).not_to_contain_text('af startværdi');expect(hero).not_to_contain_text('viste punkter');expect(hero).not_to_contain_text('registreringer')
    if width==390:
     rows=page.locator('.mobile-holding');expect(rows.first).to_be_visible()
    else:rows=page.locator('.dash-row');expect(rows.first).to_be_visible()
    for label in ('kurstid ukendt','Hentet ','hentet '):expect(rows.first).not_to_contain_text(label)
    for period in ('day','week','month','year'):
     page.locator('[data-dashboard-range='+period+']').click();expect(hero.locator('.dash-history-status')).to_have_count(1)
     svg=hero.locator('.dash-chart-svg');svg.scroll_into_view_if_needed();box=svg.bounding_box();x=box['x']+box['width']*.6;y=box['y']+box['height']*.5
     if touch:svg.dispatch_event('pointerdown',{'pointerType':'touch','clientX':x,'clientY':y,'bubbles':True})
     else:page.mouse.move(x,y)
     tip=hero.locator('.dash-chart-tooltip');expect(tip).to_be_visible();expect(tip.locator('[data-chart-date]')).not_to_be_empty();expect(tip.locator('[data-chart-value]')).not_to_be_empty()
     tipbox=tip.bounding_box();chartbox=svg.bounding_box();assert tipbox['y']+tipbox['height']<=chartbox['y']+2,(width,period,tipbox,chartbox)
     selected=svg.locator('.dash-chart-point.is-selected');expect(selected).to_have_count(1);guide=svg.locator('.dash-chart-guide');assert guide.get_attribute('x1')==selected.get_attribute('cx')
     if touch:svg.dispatch_event('pointerup',{'pointerType':'touch','clientX':x,'clientY':y,'bubbles':True})
     else:page.locator('.dash-hero-intro h2').hover()
     expect(tip).to_be_hidden();expect(guide).to_be_hidden()
    page.locator('[data-dashboard-range=day]').click();expect(hero.locator('.dash-history-status')).to_have_count(1)
    label=hero.locator('.dash-chart-latest-time');expect(label).to_be_visible();assert label.bounding_box()['width']<80
    Path('visual-review').mkdir(exist_ok=True);page.screenshot(path=f'visual-review/overblik-{width}.png',full_page=True)
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1')
    assert not errors,errors
    page.close()
   browser.close()
 finally:server.shutdown();server.server_close();case.tearDown()
 print('PASS: approved labels, touch release, mouse exit, position list and unscaled timestamp')
if __name__=='__main__':main()
