"""Trusted touch input on a local mobile browser; all broker reads are synthetic."""
import json,sys,tempfile,threading
from datetime import datetime,timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app,portfolio_data,portfolios
from playwright.sync_api import sync_playwright

def main():
 previous=app.DB
 with tempfile.TemporaryDirectory() as directory:
  app.DB=directory+'/db';app.init();app.create_user('browser-test-password-long')
  with app.connect() as c:
   portfolios.replace_pluto(c,1,[{'id':'portfolios:root','name':'Synthetic root','kind':'portfolio'},{'id':'collections:child','name':'Synthetic child','kind':'collection','parent_external_id':'portfolios:root'}])
   ids=[r['id'] for r in c.execute("SELECT id FROM portfolios WHERE source='pluto' ORDER BY id")]
   c.execute('INSERT INTO oauth_tokens VALUES(?,?,?,?)',(1,b'not-a-real-token',datetime.now(timezone.utc).timestamp()+3600,0))
  server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
  try:
   with sync_playwright() as p:
    browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
    context=browser.new_context(viewport={'width':390,'height':844},is_mobile=True,has_touch=True);page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)));calls=[];modes=[];held=[];hold=[False]
    def complete(route):
     pid=json.loads(route.request.post_data)['id'];observed=datetime.now(timezone.utc).isoformat()
     payload={'observed':observed,'value':None,'positions':[],'accounts':[],'pending_orders':[],'errors':[],'complete':True,'orders_complete':True,'positions_complete':True}
     with app.connect() as c:portfolio_data.save(c,1,pid,payload)
     route.fulfill(json={'ok':True,'complete':True,'errors':[]})
    def read(route):
     calls.append(json.loads(route.request.post_data)['id']);modes.append(json.loads(route.request.post_data).get('automatic'))
     if hold[0]:held.append(route)
     else:complete(route)
    page.route('**/api/portfolios/data',read);page.route('**/api/portfolios/sync',lambda r:r.fulfill(json={'ok':True}))
    page.goto(f'http://127.0.0.1:{server.server_port}');page.locator('#login-form [name=password]').fill('browser-test-password-long');page.locator('#login-form button').click();page.locator('#refresh-status[data-kind=success]').wait_for();assert sorted(calls)==sorted(ids);refresh_order=list(calls)
    cdp=context.new_cdp_session(page)
    def pull(selector='nav [data-view=overview]',dx=55,dy=120):
     page.evaluate('()=>{window.scrollTo(0,0);document.activeElement.blur()}');box=page.locator(selector).bounding_box();x=box['x']+box['width']/2;y=box['y']+box['height']/2
     cdp.send('Input.dispatchTouchEvent',{'type':'touchStart','touchPoints':[{'x':x,'y':y,'id':1}]})
     for step in range(1,7):
      cdp.send('Input.dispatchTouchEvent',{'type':'touchMove','touchPoints':[{'x':x+dx*step/6,'y':y+dy*step/6,'id':1}]});page.wait_for_timeout(25)
     cdp.send('Input.dispatchTouchEvent',{'type':'touchEnd','touchPoints':[]})
    before=len(calls);pull();page.locator('#pull-refresh-status').filter(has_text='Pluto hentet').wait_for();assert calls[before:]==refresh_order;assert page.locator('nav [data-view=overview]').get_attribute('class')=='active'
    # A short drag is not a refresh and a navigation button still works as a tap.
    before=len(calls);pull(dx=0,dy=35);assert len(calls)==before;page.locator('nav [data-view=reports]').tap();page.locator('.intel-shell').wait_for()
    pull('nav [data-view=reports]');page.locator('#pull-refresh-status').filter(has_text='Pluto hentet').wait_for();assert calls[before:]==refresh_order
    # Even when viewing one child, a pull refreshes the whole active account list.
    page.locator('nav [data-view=portfolios]').tap();page.locator(f'[data-open-portfolio="{ids[1]}"]').first.click();before=len(calls)
    pull('nav [data-view=portfolios]');page.locator('#pull-refresh-status').filter(has_text='Pluto hentet').wait_for();assert calls[before:]==refresh_order
    # Native browser pull/reload is also an explicit full fetch, not the automatic cache path.
    before=len(calls);page.reload();page.locator('#refresh-status[data-kind=success]').wait_for();assert calls[before:]==refresh_order;assert modes[before:]==[False,False]
    # Pull during an automatic read joins that cycle, with visible progress, no duplicates.
    page.locator('nav [data-view=overview]').tap();hold[0]=True
    page.evaluate('()=>{nextAutomaticAt=0;maybeAutoRefresh()}');page.locator('#refresh-status').filter(has_text='Opdaterer automatisk').wait_for();before=len(calls)
    pull();page.locator('#pull-refresh-status').filter(has_text='Opdatering er i gang').wait_for();assert len(calls)==before;hold[0]=False
    for route in held:complete(route)
    held.clear();page.locator('#pull-refresh-status').filter(has_text='Pluto opdateret automatisk').wait_for();assert calls[before-1:]==refresh_order
    # Dirty forms are protected from gesture refresh.
    page.locator('nav [data-view=trade]').tap();page.locator('.legacy-trade>summary').click();page.locator('#proposal [name=ticker]').fill('UNSAVED');page.locator('#proposal button').focus();before=len(calls);pull('nav [data-view=trade]',dx=0);assert len(calls)==before;assert page.locator('#proposal [name=ticker]').input_value()=='UNSAVED'
    assert not errors,errors;browser.close()
   print('PASS: trusted mobile touch, diagonal drag from navigation button, short drag, Reports and detail refresh all portfolios, in-flight automatic refresh joins without duplicates, draft preserved')
  finally:server.shutdown();server.server_close();app.DB=previous
if __name__=='__main__':main()
