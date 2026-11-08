"""Synthetic mobile and desktop checks for the compact HOT WATCH overview."""
import os,sys,tempfile,threading
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]));sys.path.insert(0,str(Path(__file__).resolve().parent))
import app,report_ingest,hotwatch_engine as engine
from test_intel_workflows import merc_report
from test_hotwatch_engine import request,tick
from playwright.sync_api import sync_playwright,expect

def main():
 old=app.DB
 with tempfile.TemporaryDirectory() as tmp:
  app.DB=tmp+'/db';app.init();app.create_user('test-password-long-enough');report_ingest.save(app.connect,1,merc_report(True));req=request();now=engine.utc();before=now-timedelta(seconds=60);engine.create(app.connect,1,req,before)
  engine.ingest(app.connect,1,req['watch_id'],True,tick(before,1,'100'),before);engine.ingest(app.connect,1,req['watch_id'],True,tick(now,2,'99'),now)
  with app.connect() as c:
   for i in range(3):
    c.execute("INSERT INTO hw_sessions(user_id,watch_id,is_test,candidate_id,purpose,status,request,digest,strategy,state,created,updated,next_due) SELECT user_id,?,is_test,candidate_id,?,'COMPLETED',request,digest,strategy,state,created,updated,next_due FROM hw_sessions WHERE watch_id=?",(f'historical-{i}',f'old-{i}',req['watch_id']))
  server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
  asset={'id':'test-asset','ticker':'ABC','exchange':'NASDAQ','currency':'USD','name':'ABC Company'}
  def call(client,tools,name,data):return [{'id':'test-asset','ticker':'ABC'}] if name=='search_assets' else {'asset':asset}
  try:
   with patch('trade_service.search',return_value={'assets':[{'asset_id':'test-asset','ticker':'ABC','name':'ABC Company','currency':'USD','isin':''}]}),patch('trade_service.client',return_value=(object(),{})),patch('trade_service.call',side_effect=call),patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'0'}),sync_playwright() as pw:
    browser=pw.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox']);page=browser.new_page(viewport={'width':390,'height':900});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(f'http://127.0.0.1:{server.server_port}');page.locator('#login-form [name=password]').fill('test-password-long-enough');page.locator('#login-form button').click();page.locator('nav [data-view=hot-watch]').click();page.locator('.engine-overview').wait_for()
    mode_box=page.locator('.hotwatch-mode > summary').bounding_box();refresh_box=page.locator('[data-watch-refresh]').bounding_box()
    assert abs(mode_box['y']-refresh_box['y'])<1 and abs(mode_box['height']-refresh_box['height'])<1,(mode_box,refresh_box)
    page.locator('.hotwatch-mode > summary').click();page.locator('#watch-mode').select_option('true');expect(page.locator('.hotwatch-mode > summary')).to_contain_text('Testdata');page.locator('.engine-list-row').first.wait_for();expect(page.locator('[data-engine-filter="NO_DATA"] strong')).to_have_text('1')
    page.locator('.engine-candidates > summary').click();page.locator('.engine-candidate-row').first.click();expect(page.locator('#intel-detail-dialog')).to_be_visible();page.keyboard.press('Escape')
    page.locator('[data-engine-filter=BUY]').click();expect(page.locator('.engine-filter-empty')).to_be_visible();expect(page.locator('[data-engine-filter=BUY]')).to_have_attribute('aria-pressed','true')
    page.locator('[data-engine-filter=NO_DATA]').click();expect(page.locator('.engine-list-row:not([hidden])')).to_have_count(1)
    page.locator('[data-engine-filter=all]').click();expect(page.locator('[data-engine-filter=all]')).to_have_attribute('aria-pressed','true')
    for width in (320,390,768,1440):
     page.set_viewport_size({'width':width,'height':900});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),width
     if width in (390,1440):page.screenshot(path=f'/tmp/hotwatch-redesign-{width}.png',full_page=True)
     page.locator('.engine-list-value').first.click();dialog=page.locator('#engine-dialog');dialog.wait_for(state='visible');assert dialog.evaluate('(n)=>n.scrollWidth<=n.clientWidth+1'),width
     assert dialog.locator('.engine-chart path').get_attribute('stroke')=='#f08d9b'
     assert dialog.locator('[data-engine-control=pause]').count()==1;page.keyboard.press('Escape');dialog.wait_for(state='hidden')
    later=now+timedelta(seconds=60);engine.ingest(app.connect,1,req['watch_id'],True,tick(later,3,'101'),later);page.locator('.engine-list-identity').first.click();dialog.wait_for(state='visible');assert dialog.locator('.engine-chart path').get_attribute('stroke')=='#8ddbc8'
    dialog.locator('[data-engine-control=pause]').click();expect(dialog.locator('[data-engine-control=resume]')).to_have_count(1);dialog.locator('[data-engine-control=resume]').click();expect(dialog.locator('[data-engine-control=pause]')).to_have_count(1);page.keyboard.press('Escape');dialog.wait_for(state='hidden')
    if not page.locator('.hotwatch-mode').evaluate('(n)=>n.open'):page.locator('.hotwatch-mode > summary').click()
    page.locator('#watch-mode').select_option('false');page.locator('.engine-settings > summary').click();page.locator('[data-engine-strategies]').click();expect(page.locator('#engine-dialog h2')).to_contain_text('Strategier og datakilder');page.keyboard.press('Escape');page.locator('[data-engine-new]').click();page.locator('#engine-manual-search input').fill('ABC');page.locator('#engine-manual-search button').click();page.locator('[data-engine-manual="0"]').click();expect(page.locator('#engine-dialog h2')).to_have_text('ABC · motorforløb');assert not errors,errors
    with app.connect() as c:assert c.execute("SELECT count(*) FROM hw_sessions WHERE purpose='manual pluto'").fetchone()[0]==1
    browser.close();print('PASS: compact mobile/desktop list, detail controls, Pluto search and manual watch')
  finally:server.shutdown();server.server_close();app.DB=old
if __name__=='__main__':main()
