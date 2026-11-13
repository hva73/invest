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
    browser=pw.chromium.launch(**({} if __import__('os').environ.get('ESCAPE_PLAYWRIGHT_MANAGED') else {'executable_path':'/usr/bin/chromium'}),headless=True,args=['--no-sandbox']);page=browser.new_page(viewport={'width':1440,'height':1000},has_touch=True);errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(f'http://127.0.0.1:{server.server_port}');page.locator('#login-form [name=password]').fill('test-password-long-enough');page.locator('#login-form button').click()
    expect(page.locator('.dash-chart-svg')).to_be_visible();expect(page.locator('.dash-chart-change')).to_contain_text('+10,00');expect(page.locator('.dash-chart-summary .dash-result-share').first).to_contain_text('+1,00 %');expect(page.locator('.dash-chart-summary .dash-result-share').last).to_contain_text('+2,73 %');assert page.locator('.dash-chart-summary .dash-result-share').first.evaluate('(n)=>getComputedStyle(n).color')=='rgb(139, 223, 184)'
    page.locator('.dash-chart-svg').hover();expect(page.locator('.dash-chart-tooltip')).to_be_visible();expect(page.locator('.dash-chart-tooltip [data-chart-date]')).not_to_be_empty();expect(page.locator('.dash-chart-tooltip [data-chart-value]')).not_to_be_empty()
    page.set_viewport_size({'width':390,'height':1000});plot=page.locator('.dash-chart-svg');plot.scroll_into_view_if_needed();box=plot.bounding_box();plot.dispatch_event('pointerdown',{'pointerType':'touch','clientX':box['x']+box['width']*.5,'clientY':box['y']+box['height']*.5});expect(page.locator('.dash-chart-tooltip')).to_be_visible();expect(page.locator('.dash-chart-tooltip [data-chart-date]')).not_to_be_empty();expect(page.locator('.dash-chart-tooltip [data-chart-value]')).not_to_be_empty();plot.dispatch_event('pointerup',{'pointerType':'touch'});expect(page.locator('.dash-chart-tooltip')).to_be_hidden()
    page.set_viewport_size({'width':1440,'height':1000})
    page.evaluate('''() => {
     const points=[{at:'2026-11-07T23:04:00Z',amount:'2830',reported_result:'-169.44',currency:'DKK'},{at:'2026-11-07T23:10:00Z',amount:'2830',reported_result:'-169.25',currency:'DKK'}];
     const chart=p=>new DOMParser().parseFromString(window.DashboardUI.portfolioChart({portfolio_value_history:{day_start:'2026-11-07T23:00:00Z',day_end:'2026-11-08T23:00:00Z',periods:{day:p}}}),'text/html');
     const doc=chart(points),dots=doc.querySelectorAll('.dash-chart-point');
     if(dots.length!==2||Number(dots[1].getAttribute('cx'))>5)throw Error('Day chart does not use full-day axis');
     if(Math.abs(Number(dots[0].getAttribute('cy'))-Number(dots[1].getAttribute('cy')))>12)throw Error('Small changes are exaggerated');
     if(!doc.querySelector('.dash-chart-scale')||!doc.querySelector('.dash-chart-dates').textContent.includes('24.00'))throw Error('Day scale is missing');
     const negative=new DOMParser().parseFromString(window.DashboardUI.resultShare({amount:'-163.94',currency:'DKK'},{amount:'2836.06',currency:'DKK'}),'text/html').body.firstElementChild;if(!negative||!negative.classList.contains('negative')||!negative.textContent.includes('-5,78 %'))throw Error('Negative result share incorrect');if(window.DashboardUI.resultShare({amount:'1',currency:'EUR'},{amount:'100',currency:'DKK'})||window.DashboardUI.resultShare({amount:'1',currency:'DKK'},{amount:'0',currency:'DKK'}))throw Error('Invalid comparison shown');
     const marker=doc.querySelector('.dash-chart-latest-time');if(!marker||!marker.textContent.includes('00.10')||marker.textContent.includes('00.10.00'))throw Error('Last timestamp is not shown in hours and minutes');
     if(marker.tagName!=='SPAN'||!marker.hasAttribute('data-chart-left')||!marker.hasAttribute('data-chart-top'))throw Error('Last timestamp is not positioned as readable text');
     const later=chart([points[0],{...points[1],at:'2026-11-08T17:00:00Z'}]);if(later.querySelector('.dash-chart-latest-time').dataset.chartLeft===marker.dataset.chartLeft)throw Error('Time does not follow later chart point');
     if(chart(points.slice(0,1)).querySelectorAll('.dash-chart-point').length!==1)throw Error('First daily observation not displayed');
    }''')
    page.evaluate('''() => {
     const points=[{at:'2026-11-08T08:00:00Z',reported_result:'-169',currency:'DKK'},{at:'2026-11-08T14:00:00Z',reported_result:'-168',currency:'DKK'}];
     document.querySelector('#dashboard-value-chart').innerHTML=window.DashboardUI.portfolioChart({portfolio_value_history:{day_start:'2026-11-07T23:00:00Z',day_end:'2026-11-08T23:00:00Z',periods:{day:points}}});
    }''')
    page.wait_for_function("document.querySelector('.dash-chart-latest-time').style.left !== ''")
    page.evaluate('''() => {
     const dot=document.querySelectorAll('.dash-chart-point')[1].getBoundingClientRect(),label=document.querySelector('.dash-chart-latest-time').getBoundingClientRect();
     if(Math.abs((label.left+label.right-dot.left-dot.right)/2)>2||label.bottom>dot.top+3)throw Error('Visible label is not above the latest point');
    }''')
    page.evaluate("document.querySelector('#dashboard-value-chart').innerHTML=window.DashboardUI.portfolioChart(state.dashboard)")
    page.locator('[data-dashboard-range=year]').click();expect(page.locator('[data-dashboard-range=year]')).to_have_attribute('aria-pressed','true');expect(page.locator('.dash-chart-svg')).to_be_visible()
    for width in (320,390,768,1440):
     page.set_viewport_size({'width':width,'height':1000});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),width
     if width in (390,1440):page.locator('.dash-hero').screenshot(path=f'/tmp/escape-value-chart-{width}.png')
    assert not errors,errors;browser.close()
   print('PASS: recorded portfolio result chart, range selection, signs and mobile widths')
  finally:server.shutdown();server.server_close()
 finally:case.tearDown()
if __name__=='__main__':main()
