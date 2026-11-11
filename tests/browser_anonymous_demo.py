"""Exercise an anonymous demo with synthetic fixtures and no API traffic."""
import os,re,sys,threading
sys.path[:0]=['.','tests']
import app
from test_design_v1_acceptance import DesignAcceptance
from playwright.sync_api import sync_playwright,expect
case=DesignAcceptance();case.setUp()
received_posts=[]
original_post=app.Handler.do_POST
def tracked_post(handler):
 received_posts.append(handler.path)
 return original_post(handler)
app.Handler.do_POST=tracked_post
server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
threading.Thread(target=server.serve_forever,daemon=True).start()
try:
 with sync_playwright() as pw:
  browser=pw.chromium.launch(headless=True)
  for width in (320,390,768,1280):
   page=browser.new_page(viewport={'width':width,'height':844});requests=[];errors=[]
   page.on('request',lambda r:requests.append(r.url));page.on('pageerror',lambda e:errors.append(str(e)))
   page.goto(f'http://127.0.0.1:{server.server_port}/');expect(page.locator('#login')).to_be_visible();expect(page.locator('aside nav')).to_be_hidden()
   shot=os.environ.get('ESCAPE_SCREENSHOTS')
   if shot and width in (320,390):page.screenshot(path=f'{shot}/demo-welcome-{width}.png')
   page.get_by_role('link',name='Prøv ESCAPE med demodata').click();expect(page.locator('.demo-banner')).to_be_visible()
   expect(page.locator('.dashboard-v1')).to_be_visible();expect(page.locator('aside nav')).to_be_visible();expect(page.locator('.dash-chart-svg')).to_be_visible()
   expect(page.locator('.dash-attention')).to_contain_text('KØBSSIGNAL');expect(page.locator('.dash-attention')).to_contain_text('SÆLGSSIGNAL')
   expect(page.locator('.dash-hero-metrics')).to_contain_text('52.080,00');requests.clear()
   if shot and width in (320,390):page.screenshot(path=f'{shot}/demo-overview-{width}.png')
   row=page.get_by_role('button',name='Åbn position TSLA i Demodepot');row.click()
   dialog=page.locator('#dashboard-detail');expect(dialog).to_be_visible()
   for period in ('day','week','month','year'):
    dialog.locator(f'[data-market-period={period}]').click()
    chart=dialog.locator('.market-chart svg[role=img]');expect(chart).to_be_visible()
    expect(chart).to_have_attribute('aria-label',re.compile(r'\b(?:1\d\d|2\d\d|3[0-6]\d) observerede punkter'))
    if shot:page.screenshot(path=f'{shot}/demo-chart-{width}-{period}.png')
   if shot and width==390:page.screenshot(path=f'{shot}/demo-position-390.png')
   dialog.locator('[data-asset-trade=BUY]').click();quick=page.locator('#quick-trade-dialog');expect(quick).to_contain_text('Køb · TSLA')
   quick.locator('[name=size]').fill('50');quick.locator('button[type=submit]').click();expect(quick).to_contain_text('Gennemgå købet')
   assert not any('/api/' in url for url in requests),requests
   quick.locator('#quick-trade-confirm').check();quick.locator('[data-quick-send]').click();expect(quick).to_contain_text(re.compile('simuleret',re.I))
   quick.locator('[data-quick-close]').click();dialog.locator('[data-dashboard-close]').click()
   if width<=900:page.locator('#mobile-more').click()
   page.locator('nav [data-view=sectors]').click();expect(page.locator('.sector-shell')).to_be_visible()
   expect(page.locator('.sector-shell')).to_contain_text('Teknologi')
   before_posts=len(received_posts)
   blocked=page.evaluate('''() => new Promise(resolve => {const x=new XMLHttpRequest();x.open('POST','/api/trade/send');x.onload=()=>resolve(false);x.onerror=()=>resolve(true);try{x.send('{}')}catch(e){resolve(true)}})''')
   assert blocked,'CSP must block direct XMLHttpRequest'
   assert len(received_posts)==before_posts,received_posts
   expect(page.locator('.demo-banner')).to_contain_text('Fiktive data')
   page.get_by_role('link',name='Afslut demo / Log ind').click();expect(page.locator('#login')).to_be_visible()
   page.go_back();expect(page.locator('.demo-banner')).to_be_visible();page.reload();expect(page.locator('.dashboard-v1')).to_be_visible()
   page.go_forward();expect(page.locator('#login')).to_be_visible()
   assert not errors,(width,errors)
   page.close()
  # An existing genuine login remains unchanged while demo uses only fixture data.
  page=browser.new_page(viewport={'width':390,'height':844})
  page.goto(f'http://127.0.0.1:{server.server_port}/')
  page.locator('#login-form [name=password]').fill('test-password-long-enough')
  page.locator('#login-form button').click();expect(page.locator('.dashboard-v1')).to_be_visible()
  page.goto(f'http://127.0.0.1:{server.server_port}/demo');expect(page.locator('.demo-banner')).to_be_visible()
  expect(page.get_by_role('button',name='Åbn position TSLA i Demodepot')).to_be_visible()
  page.get_by_role('link',name='Afslut demo / Log ind').click();expect(page.locator('.dashboard-v1')).to_be_visible()
  expect(page.locator('.demo-banner')).to_have_count(0)
  page.close();browser.close()
 print('PASS: anonymous demo, four widths, safe simulated actions and blocked API requests')
finally:
 server.shutdown();server.server_close();app.Handler.do_POST=original_post;case.tearDown()
