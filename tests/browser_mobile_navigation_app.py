"""Real application routing on a disposable fixture; no live broker calls."""
import os,sys,threading
from pathlib import Path
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
import app
from test_portfolio_value_chart import PortfolioValueChart
from playwright.sync_api import sync_playwright,expect
case=PortfolioValueChart();case.setUp()
server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
threading.Thread(target=server.serve_forever,daemon=True).start()
try:
 with patch('mcp_client.MCP.request',side_effect=AssertionError('Live broker calls disabled')),sync_playwright() as p:
  browser=p.chromium.launch(headless=True)
  for width in (320,390,768,1280):
   page=browser.new_page(viewport={'width':width,'height':844});errors=[]
   page.on('pageerror',lambda e:errors.append(str(e)))
   page.goto(f'http://127.0.0.1:{server.server_port}')
   page.locator('#login-form [name=password]').fill('test-password-long-enough')
   page.locator('#login-form button').click();expect(page.locator('.dashboard-v1')).to_be_visible()
   screenshot_dir=os.environ.get('ESCAPE_SCREENSHOTS')
   if screenshot_dir:
    Path(screenshot_dir).mkdir(parents=True,exist_ok=True)
    page.screenshot(path=str(Path(screenshot_dir)/f'overview-{width}.png'))
   nav=page.locator('body > aside nav')
   if width<=900:
    more=page.locator('#mobile-more');expect(more).to_be_visible()
    assert nav.locator(':scope > button[data-view]').evaluate_all('xs => xs.map(x => x.dataset.view)')==['overview','portfolios','hot-watch','sectors']
    for target in ('portfolios','hot-watch','sectors','overview'):
     nav.locator(f':scope > [data-view="{target}"]').click()
     expect(nav.locator(f':scope > [data-view="{target}"]')).to_have_class('active')
     assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1'),(width,target)
    more.click();expect(page.locator('#mobile-more-panel')).to_be_visible()
    expect(page.locator('#mobile-more-panel [data-view=radar]')).to_be_visible()
    page.locator('#mobile-more-panel [data-view=radar]').click()
    expect(page.locator('#mobile-more-panel')).to_be_hidden()
    expect(page.locator('#mobile-more-panel [data-view=radar]')).to_have_class('active')
    more.click();expect(page.locator('#mobile-more-panel')).to_be_visible()
    for action in ('profile-open','refresh-current','logout'):
     assert page.locator(f'#mobile-more-panel #{action}').count()==1,(width,action)
    if screenshot_dir:page.screenshot(path=str(Path(screenshot_dir)/f'menu-{width}.png'))
    page.locator('#mobile-more-panel [data-view=trade]').click()
    expect(page.locator('.broker-trade')).to_be_visible();expect(page.locator('#mobile-more-panel')).to_be_hidden()
    assert page.locator('#mobile-more-panel [data-view=trade]').evaluate("e=>e.classList.contains('active')")
    more.click();page.keyboard.press('Escape');expect(page.locator('#mobile-more-panel')).to_be_hidden()
    page.locator('nav [data-view=overview]').click()
    before=nav.bounding_box();page.evaluate('window.scrollTo(0,document.body.scrollHeight)');after=nav.bounding_box()
    assert abs(before['y']-after['y'])<2,(width,before,after)
   else:
    expect(page.locator('#mobile-more')).to_be_hidden();assert page.locator('main > header #logout').count()==1;nav.locator('[data-view=trade]').click();expect(page.locator('.broker-trade')).to_be_visible()
   assert not errors,(width,errors)
   page.close()
  browser.close()
 print('PASS: mobile, tablet and desktop routing in real app fixture')
finally:
 server.shutdown();server.server_close();case.tearDown()
