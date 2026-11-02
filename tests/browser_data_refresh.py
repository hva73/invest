"""Synthetic, local-only mobile refresh and age integration; no provider traffic."""
import copy,json,sys,tempfile,threading
from datetime import datetime,timedelta,timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app,portfolios,portfolio_data,report_ingest
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]
def main():
 previous=app.DB
 with tempfile.TemporaryDirectory() as directory:
  app.DB=directory+'/db';app.init();app.create_user('browser-test-password-long')
  now=datetime.now(timezone.utc);stamp=lambda minutes:(now-timedelta(minutes=minutes)).isoformat()
  with app.connect() as c:
   portfolios.replace_pluto(c,1,[{'id':'portfolios:synthetic','name':'Syntetisk Pluto-konto','kind':'portfolio'}]);pid=c.execute('SELECT id FROM portfolios').fetchone()[0]
   # Dummy encrypted data is never used: broker endpoints below are intercepted.
   c.execute('INSERT INTO oauth_tokens VALUES(?,?,?,?)',(1,b'synthetic-not-a-token',now.timestamp()+3600,now.timestamp()))
   payload={'source':'Pluto Markets','observed':stamp(1),'kind':'portfolio','positions':[],'pending_orders':[],'accounts':[{'currency':'DKK','balance':{'amount':'200','currency':'DKK'},'reserved':None,'withdrawal_power':None,'buying_power':None,'source_time':stamp(20)}],'value':{'value':{'amount':'1000','currency':'DKK'},'source_time':stamp(40)},'errors':[],'complete':True,'orders_complete':True,'positions_complete':True}
   portfolio_data.save(c,1,pid,payload)
  report=json.loads((ROOT/'examples/report-v2-test.json').read_text());report.update(report_id='synthetic-new-report',generated_at=stamp(0),is_test=False);report_ingest.save(app.connect,1,report)
  server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
  try:
   with sync_playwright() as p:
    browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox']);context=browser.new_context(viewport={'width':390,'height':844},is_mobile=True,has_touch=True);page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)));calls=[];fail=[False];edit_during_read=[False]
    def data_route(route):
     calls.append('data')
     if fail[0]:
      with app.connect() as c:portfolio_data.mark_failed(c,1,pid,'Seneste Pluto-opslag fejlede; gemte data kan være forældede')
      route.fulfill(status=502,json={'error':'Syntetisk forbindelsesfejl'});return
     fresh=copy.deepcopy(payload);fresh['observed']=datetime.now(timezone.utc).isoformat()
     with app.connect() as c:portfolio_data.save(c,1,pid,fresh)
     if edit_during_read[0]:
      page.locator('#proposal [name=ticker]').fill('UNSAVED-DRAFT');page.locator('#proposal button').focus()
     route.fulfill(json={'ok':True,'complete':True,'errors':[],'message':'Synthetic read complete'})
    page.route('**/api/portfolios/data',data_route);page.route('**/api/portfolios/sync',lambda route:route.fulfill(json={'ok':True,'count':1}))
    page.goto(f'http://127.0.0.1:{server.server_port}');page.locator('#login-form [name=password]').fill('browser-test-password-long');page.locator('#login-form button').click();page.locator('.wealth-panel .freshness-stale').wait_for();assert 'Rapportøjebliksbillede' in page.locator('.desk-summary').inner_text();page.locator('#refresh-status[data-kind=success]').wait_for();assert calls==['data']
    page.locator('#refresh-current').click();page.locator('#refresh-status[data-kind=success]').wait_for();assert calls==['data','data'];assert page.locator('.wealth-panel .freshness-stale').count()==1
    # Pull gesture at the top must execute the same broker refresh, exactly once.
    page.evaluate('''()=>{window.scrollTo(0,0);document.activeElement.blur();const target=document.querySelector('h1');const touch=y=>new Touch({identifier:1,target,clientX:180,clientY:y});target.dispatchEvent(new TouchEvent('touchstart',{bubbles:true,touches:[touch(240)]}));target.dispatchEvent(new TouchEvent('touchmove',{bubbles:true,cancelable:true,touches:[touch(360)]}));target.dispatchEvent(new TouchEvent('touchend',{bubbles:true,touches:[]}));}''')
    page.locator('#refresh-status[data-kind=success]').wait_for();assert len(calls)==3
    page.locator(f'[data-open-portfolio="{pid}"]').first.click();page.locator('.pluto-detail-data').wait_for();assert page.locator('.pluto-detail-data>.freshness-stale').count()==1
    # Bad fetch preserves source time and shows an error, not a success timestamp.
    fail[0]=True;page.locator('#refresh-current').click();page.locator('#refresh-status[data-kind=warning]').wait_for();page.get_by_text('Seneste opslag fejlede · tidligere data',exact=True).first.wait_for()
    assert '1.000,00' in page.locator('.detail-value').inner_text()
    page.screenshot(path='/tmp/escape-data-age-mobile.png',full_page=True)
    for width in [320,390,430,768,1440]:
     page.set_viewport_size({'width':width,'height':900});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
    fail[0]=False;before=len(calls);page.locator('nav [data-view=reports]').click();page.locator('.intel-header').wait_for();page.locator('#refresh-current').click();page.locator('#refresh-status[data-kind=success]').wait_for();assert len(calls)==before+1;assert 'Pluto hentet' in page.locator('#refresh-status').inner_text();before=len(calls)
    # Automatic updates work from Reports too, without navigating to a portfolio.
    fail[0]=False;page.evaluate('()=>{nextAutomaticAt=0;return maybeAutoRefresh()}');assert len(calls)==before+1
    page.evaluate('()=>maybeAutoRefresh()');assert len(calls)==before+1  # five-minute browser cooldown
    # Hidden tabs must not initiate another provider read.
    page.evaluate("()=>{Object.defineProperty(document,'hidden',{get:()=>true,configurable:true});nextAutomaticAt=0;return maybeAutoRefresh()}");assert len(calls)==before+1
    page.evaluate("()=>{Object.defineProperty(document,'hidden',{get:()=>false,configurable:true});return maybeAutoRefresh()}");assert len(calls)==before+2
    # A form started during a provider read must survive the response unchanged.
    page.locator('nav [data-view=trade]').click();page.locator('.legacy-trade>summary').click();edit_during_read[0]=True
    page.evaluate('()=>{document.activeElement.blur();nextAutomaticAt=0;return maybeAutoRefresh()}');assert len(calls)==before+3
    assert page.locator('#proposal [name=ticker]').input_value()=='UNSAVED-DRAFT'
    page.evaluate('()=>{nextAutomaticAt=0;return maybeAutoRefresh()}');assert len(calls)==before+3  # dirty draft pauses the next cycle
    page.locator('nav [data-view=overview]').click();edit_during_read[0]=False
    # An expired connection that can renew is eligible; a disconnected one is not.
    page.evaluate('()=>{state.connection.connected=false;state.connection.can_renew=false;nextAutomaticAt=0;return maybeAutoRefresh()}');assert len(calls)==before+3
    page.evaluate('()=>{state.connection.can_renew=true;return maybeAutoRefresh()}');assert len(calls)==before+4
    assert not errors,errors;browser.close()
   print('PASS: automatic refresh on login and from Reports, five-minute cooldown, hidden-tab pause, unsaved form protection, renewable/disconnected eligibility, mobile button and pull refresh, stale Pluto survives a new ChatGPT report and successful fetch, failed refresh preservation, report-only refresh and 320–1440px')
  finally:server.shutdown();server.server_close();app.DB=previous
if __name__=='__main__':main()
