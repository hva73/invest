import os,sys,threading
sys.path[:0]=[os.path.dirname(os.path.dirname(os.path.abspath(__file__))),os.path.dirname(os.path.abspath(__file__))]
import app
from test_portfolio_value_chart import PortfolioValueChart
from playwright.sync_api import sync_playwright,expect
case=PortfolioValueChart();case.setUp()
server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
try:
 with sync_playwright() as p:
  browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox']);page=browser.new_page(viewport={'width':390,'height':844});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
  page.goto(f'http://127.0.0.1:{server.server_port}');page.locator('#login-form [name=password]').fill('test-password-long-enough');page.locator('#login-form button').click();page.locator('#profile-open').wait_for()
  assert not page.locator('#profile-dialog').is_visible()
  page.locator('#profile-open').click();page.locator('#profile-dialog').wait_for();assert page.locator('#profile-close').is_hidden()
  page.keyboard.press('Escape');assert page.locator('#profile-dialog').is_visible()
  page.reload();page.locator('#profile-dialog').wait_for();form=page.locator('#profile-form')
  form.locator('[name=name]').fill('Test Person');form.locator('[name=email]').fill('test@example.org');form.locator('[name=street]').fill('Testvej 1');form.locator('[name=postal_code]').fill('7100');expect(form.locator('[name=city]')).to_have_value('Vejle');form.locator('[name=postal_code]').fill('7140');expect(form.locator('[name=city]')).to_have_value('Stouby');form.locator('[name=birth_date]').fill('1980-02-29');form.locator('[name=contact_consent]').select_option('no');form.locator('[name=marketing_consent]').select_option('no');form.locator('[type=submit]').click();page.locator('#profile-dialog').wait_for(state='hidden')
  page.reload();page.locator('#profile-open').wait_for();assert not page.locator('#profile-dialog').is_visible();page.locator('#profile-open').click();expect(page.locator('#profile-dialog')).to_be_visible();assert page.locator('[name=marketing_consent]').input_value()=='no';assert page.locator('#profile-close').is_visible();page.locator('#profile-close').click()
  assert not errors,errors
  print('Profile persistence, required completion, opt-out and reopening: OK')
  browser.close()
finally:server.shutdown();server.server_close();case.tearDown()
