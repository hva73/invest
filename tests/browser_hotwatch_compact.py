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
  server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
  asset={'id':'test-asset','ticker':'ABC','exchange':'NASDAQ','currency':'USD','name':'ABC Company'}
  def call(client,tools,name,data):return [{'id':'test-asset','ticker':'ABC'}] if name=='search_assets' else {'asset':asset}
  try:
   with patch('trade_service.search',return_value={'assets':[{'asset_id':'test-asset','ticker':'ABC','name':'ABC Company','currency':'USD','isin':''}]}),patch('trade_service.client',return_value=(object(),{})),patch('trade_service.call',side_effect=call),patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'0'}),sync_playwright() as pw:
    browser=pw.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox']);page=browser.new_page(viewport={'width':390,'height':900});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(f'http://127.0.0.1:{server.server_port}');page.locator('#login-form [name=password]').fill('test-password-long-enough');page.locator('#login-form button').click();page.locator('nav [data-view=hot-watch]').click();page.locator('.engine-overview').wait_for()
    page.locator('#watch-mode').select_option('true');page.locator('.engine-list-row').first.wait_for()
    for width in (320,390,768,1440):
     page.set_viewport_size({'width':width,'height':900});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),width
     page.locator('.engine-list-identity').first.click();dialog=page.locator('#engine-dialog');dialog.wait_for(state='visible');assert dialog.evaluate('(n)=>n.scrollWidth<=n.clientWidth+1'),width
     assert dialog.locator('.engine-chart path').get_attribute('stroke')=='#f08d9b'
     assert dialog.locator('[data-engine-control=pause]').count()==1;page.keyboard.press('Escape');dialog.wait_for(state='hidden')
    later=now+timedelta(seconds=60);engine.ingest(app.connect,1,req['watch_id'],True,tick(later,3,'101'),later);page.locator('.engine-list-identity').first.click();dialog.wait_for(state='visible');assert dialog.locator('.engine-chart path').get_attribute('stroke')=='#8ddbc8'
    dialog.locator('[data-engine-control=pause]').click();expect(dialog.locator('[data-engine-control=resume]')).to_have_count(1);dialog.locator('[data-engine-control=resume]').click();expect(dialog.locator('[data-engine-control=pause]')).to_have_count(1);page.keyboard.press('Escape');dialog.wait_for(state='hidden')
    page.locator('#watch-mode').select_option('false');page.locator('[data-engine-new]').click();page.locator('#engine-manual-search input').fill('ABC');page.locator('#engine-manual-search button').click();page.locator('[data-engine-manual="0"]').click();expect(page.locator('#engine-dialog h2')).to_have_text('ABC · motorforløb');assert not errors,errors
    with app.connect() as c:assert c.execute("SELECT count(*) FROM hw_sessions WHERE purpose='manual pluto'").fetchone()[0]==1
    browser.close();print('PASS: compact mobile/desktop list, detail controls, Pluto search and manual watch')
  finally:server.shutdown();server.server_close();app.DB=old
if __name__=='__main__':main()
