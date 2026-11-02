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
    page.locator('nav [data-view=portfolios]').click();page.locator('.local-portfolio-tools>summary').click();page.locator('#portfolio-create [name=name]').fill('Browser test portfolio');page.locator('#portfolio-create button').click();page.get_by_text('Lokal portefølje gemt.',exact=False).wait_for();page.locator('nav [data-view=trade]').click();page.locator('.legacy-trade>summary').click();page.locator('#proposal [name=portfolio_id]').select_option(index=1)
    for name,value in {'ticker':'TEST','quantity':'1','price':'100','stop':'90','target':'120','costs':'0','fx':'1'}.items():page.locator(f'#proposal [name={name}]').fill(value)
    page.locator('#proposal button').click();page.locator('[data-approve]').wait_for();page.locator('[data-approve]').click();page.get_by_text('Godkendt lokalt',exact=True).wait_for()
    page.locator('nav [data-view=reports]').click();page.locator('.report-operations>summary').click();page.locator('#queue-ecb').click();page.get_by_text('queued',exact=False).first.wait_for()
    # Financial UI fixture is confined to this temporary test database.
    import portfolios,portfolio_data
    with app.connect() as c:
     portfolios.replace_pluto(c,1,[{'id':'portfolios:browser-test','name':'Browser fixture','kind':'portfolio'},{'id':'collections:browser-child','name':'Browser collection fixture','kind':'collection','parent_external_id':'portfolios:browser-test'}]);pid=c.execute("SELECT id FROM portfolios WHERE source='pluto' AND external_id='portfolios:browser-test'").fetchone()[0]
     payload={'observed':'2026-01-01T12:00:00+00:00','value':{'value':{'amount':'1000','currency':'DKK'},'source_time':None},'positions_complete':True,'positions':portfolio_data.normalize_positions([{'name':'Test holding','currency':'USD','quantity':2,'price':'10','value':None,'costBasis':'17.5'},{'name':'Test negative holding','currency':'USD','quantity':1,'price':None,'value':None,'unrealisedPnL':'-1.5'}]),'accounts':portfolio_data.normalize_accounts([{'currency':'DKK','balance':'500','reservedForOrders':'100','buyingPower':'400'}]),'errors':[]}
     import asset_quotes
     asset_quotes.calculate(payload['positions'][0]);payload['value']['reported_result']={'amount':'2.5','currency':'DKK'}
     import pending_orders
     payload['pending_orders']=[pending_orders.normalize({'name':'Pending test '+str(i),'status':'ACTIVE_BUY','orderId':'test-'+str(i),'quantity':'1','allocatedAmount':{'amount':'50','currency':'DKK'}},'test fixture') for i in range(2)]
     payload['orders_complete']=True;payload['reservation_note']='Test fixture: no cash arithmetic.'
     portfolio_data.save(c,1,pid,payload)
    page.reload();page.locator('nav [data-view=portfolios]').click();page.locator('.collection-children').wait_for();assert 'Browser collection fixture' in page.locator('.collection-children').inner_text();page.locator(f'[data-open-portfolio="{pid}"]').first.click();page.get_by_text('Kontanter pr. konto og valuta',exact=True).wait_for();page.get_by_text('Test holding',exact=False).wait_for()
    assert 'DKK' in page.locator('#content').inner_text()
    page.get_by_text('Afventende handler',exact=True).wait_for();assert page.get_by_text('ACTIVE_BUY',exact=True).count()==2
    page.locator('.pnl.positive').first.wait_for();assert '↗' in page.locator('.pnl.positive').first.inner_text();page.locator('.pnl.negative').wait_for();assert page.locator('.pnl.positive svg').first.is_visible()
    page.get_by_text('Beregnet · antal × pris',exact=True).wait_for();page.get_by_text('Beregnet · værdi − kostpris',exact=True).wait_for();page.get_by_text('Plutos oplyste resultat',exact=True).wait_for()
    page.screenshot(path='/tmp/escape-desktop-design.png',full_page=True)
    page.locator('nav [data-view=settings]').click();page.locator('#invite').click();invitation=page.locator('#invitation input');invitation.wait_for();token=invitation.input_value()
    other=browser.new_context(viewport={'width':390,'height':844},is_mobile=True,has_touch=True);other_page=other.new_page();other_page.goto(url);other_page.locator('#login details summary').click()
    for name,value in {'invitation':' '+token[:15]+' '+token[15:]+' ','username':'Browser-Member','password':'short'}.items():other_page.locator(f'#register-form [name={name}]').fill(value)
    other_page.locator('#register-form button').click();other_page.locator('#register-status').filter(has_text='mindst 14').wait_for();assert other_page.locator('#register-status').is_visible();other_page.locator('#register-form [name=password]').fill('member-password-long-enough');other_page.locator('#register-form button').click();other_page.locator('#register-status[data-kind=success]').wait_for();assert other_page.locator('#login-form [name=username]').input_value()=='browser-member';assert other_page.evaluate('document.documentElement.scrollWidth <= window.innerWidth');other_page.locator('#login-form [name=password]').fill('member-password-long-enough');other_page.locator('#login-form button').click();other_page.locator('#content .hero').wait_for();other_page.locator('nav [data-view=trade]').click();other_page.locator('.legacy-trade>summary').click();other_page.get_by_text('Ingen handelsforslag',exact=True).wait_for()
    mobile=browser.new_context(viewport={'width':390,'height':844},is_mobile=True,has_touch=True);mobile_page=mobile.new_page();mobile_page.goto(url)
    mobile_page.locator('#login-form [name=password]').fill('browser-test-password-long');mobile_page.locator('#login-form button').click();mobile_page.locator('.account-overview').wait_for()
    assert mobile_page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'Mobile layout overflows'
    mobile_page.locator(f'[data-open-portfolio="{pid}"]').first.click()
    mobile_page.get_by_text('Afventende handler',exact=True).wait_for()
    for width in [320,375,390,430]:
     mobile_page.set_viewport_size({'width':width,'height':844})
     assert mobile_page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), f'Detail overflows at {width}px'
     assert mobile_page.locator('.responsive-table thead').first.is_hidden()
     assert mobile_page.locator('.order-card').count()==2
    mobile_page.set_viewport_size({'width':390,'height':844})
    mobile_page.screenshot(path='/tmp/escape-mobile-design.png',full_page=True);mobile_page.locator('nav [data-view=reports]').click();mobile_page.locator('.report-operations>summary').click();mobile_page.get_by_text('Data & kørsler',exact=True).wait_for()
    assert not errors,errors
    browser.close();print('PASS: desktop login, proposal approval, job queue, invitation, account isolation financial snapshot display and 390px mobile navigation')
  finally:server.shutdown();server.server_close();app.DB=previous
if __name__=='__main__':main()
