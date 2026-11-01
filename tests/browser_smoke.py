"""Optional browser integration check; uses a temporary DB and no external data."""
import sys,tempfile,threading
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app
from playwright.sync_api import sync_playwright

def main():
 previous=app.DB
 with tempfile.TemporaryDirectory() as directory:
  app.DB=directory+'/browser.sqlite';app.init();app.create_user('browser-test-password-long')
  server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
  try:
   with sync_playwright() as p:
    browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
    page=browser.new_page(viewport={'width':1440,'height':1000});errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
    url=f'http://127.0.0.1:{server.server_port}'
    page.goto(url);page.locator('#login-form [name=password]').fill('browser-test-password-long');page.locator('#login-form button').click();page.locator('#content .hero').wait_for()
    page.locator('nav [data-view=trade]').click()
    for name,value in {'ticker':'TEST','quantity':'1','price':'100','stop':'90','target':'120','costs':'0','fx':'1'}.items():page.locator(f'#proposal [name={name}]').fill(value)
    page.locator('#proposal button').click();page.locator('[data-approve]').wait_for();page.locator('[data-approve]').click();page.get_by_text('Godkendt lokalt',exact=True).wait_for()
    page.locator('nav [data-view=reports]').click();page.locator('#queue-ecb').click();page.get_by_text('queued',exact=False).first.wait_for()
    page.locator('nav [data-view=settings]').click();page.locator('#invite').click();invitation=page.locator('#invitation input');invitation.wait_for();token=invitation.input_value()
    other=browser.new_context();other_page=other.new_page();other_page.goto(url);other_page.locator('#login details summary').click()
    for name,value in {'invitation':token,'username':'browser-member','password':'member-password-long-enough'}.items():other_page.locator(f'#register-form [name={name}]').fill(value)
    other_page.locator('#register-form button').click();other_page.get_by_text('Din konto er oprettet.',exact=False).wait_for();other_page.locator('#login-form [name=password]').fill('member-password-long-enough');other_page.locator('#login-form button').click();other_page.locator('#content .hero').wait_for();other_page.locator('nav [data-view=trade]').click();other_page.get_by_text('Ingen handelsforslag',exact=True).wait_for()
    mobile=browser.new_context(viewport={'width':390,'height':844},is_mobile=True,has_touch=True);mobile_page=mobile.new_page();mobile_page.goto(url)
    mobile_page.locator('#login-form [name=password]').fill('browser-test-password-long');mobile_page.locator('#login-form button').click();mobile_page.locator('#content .hero').wait_for()
    assert mobile_page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'Mobile layout overflows'
    mobile_page.locator('nav [data-view=reports]').click();mobile_page.get_by_text('Data & kørsler',exact=True).wait_for()
    assert not errors,errors
    browser.close();print('PASS: desktop login, proposal approval, job queue, invitation, account isolation and 390px mobile navigation')
  finally:server.shutdown();server.server_close();app.DB=previous
if __name__=='__main__':main()
