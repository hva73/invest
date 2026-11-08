"""Radar filters and reset using only disposable data; no provider calls."""
import copy,sys,tempfile,threading
from pathlib import Path
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
import app,report_ingest
from test_intel_workflows import merc_report
from playwright.sync_api import sync_playwright,expect

def main():
 old=app.DB
 with tempfile.TemporaryDirectory() as tmp:
  app.DB=tmp+'/db';app.init();app.create_user('test-password-long-enough');report=merc_report();report_ingest.save(app.connect,1,report)
  server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
  try:
   with patch('mcp_client.MCP.request',side_effect=AssertionError('No Pluto calls')),sync_playwright() as p:
    browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox']);page=browser.new_page(viewport={'width':390,'height':844});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(f'http://127.0.0.1:{server.server_port}');page.locator('#login-form [name=password]').fill('test-password-long-enough');page.locator('#login-form button').click();page.locator('nav [data-view=radar]').click()
    page.locator('.desk-radar').wait_for();expect(page.locator('button[data-candidate-own]')).to_have_attribute('aria-pressed','false')
    page.locator('button[data-candidate-filter=all]').click();expect(page.locator('.desk-candidate:not([hidden])')).to_have_count(12)
    page.locator('button[data-attention-filter=yellow]').click();expect(page.locator('button[data-attention-filter=yellow]')).to_have_attribute('aria-pressed','true')
    page.evaluate('render()');expect(page.locator('button[data-candidate-filter=all]')).to_have_attribute('aria-pressed','true');expect(page.locator('button[data-attention-filter=yellow]')).to_have_attribute('aria-pressed','true')
    for width in (320,390,768,1440):
     page.set_viewport_size({'width':width,'height':900});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),width
     if width in (390,1440):page.screenshot(path=f'/tmp/radar-redesign-{width}.png',full_page=True)
    page.once('dialog',lambda dialog:dialog.accept());page.locator('[data-radar-reset]').click();expect(page.locator('.desk-candidate')).to_have_count(0)
    expect(page.locator('button[data-candidate-filter=active]')).to_have_attribute('aria-pressed','true');expect(page.locator('button[data-attention-filter=all]')).to_have_attribute('aria-pressed','true')
    assert report_ingest.item(app.connect,1,report['report_id'])['report'] is not None
    newer=copy.deepcopy(report);newer['report_id']='browser-new-generation';newer['candidates'][-1]['candidate_id']='new-candidate-id';report_ingest.save(app.connect,1,newer)
    page.locator('#refresh-current').click();expect(page.locator('.desk-candidate:not([hidden])')).to_have_count(1)
    assert not errors,errors;browser.close()
  finally:server.shutdown();server.server_close();app.DB=old
 print('PASS: radar filters, responsive design and reset retain reports and accept new candidate IDs')
if __name__=='__main__':main()
