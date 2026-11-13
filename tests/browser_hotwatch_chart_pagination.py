"""Synthetic HOT WATCH chart pagination and touch/mouse interaction."""
import os,sys,tempfile,threading
from pathlib import Path
from datetime import timedelta
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
import app,report_ingest,hotwatch_engine as engine
from test_hotwatch_engine import request,tick
from test_intel_workflows import merc_report
from playwright.sync_api import sync_playwright,expect
def main():
 old=app.DB
 with tempfile.TemporaryDirectory() as tmp:
  app.DB=tmp+'/db';app.init();app.create_user('test-password-long-enough')
  fixed=engine.utc().replace(microsecond=0);base=fixed-timedelta(minutes=130);report_ingest.save(app.connect,1,merc_report(True));req=request();engine.create(app.connect,1,req,base)
  for i in range(130):
   at=base+timedelta(minutes=i);item=tick(at,i,str(100+i/100));engine.ingest(app.connect,1,req['watch_id'],True,item,at)
  server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
  try:
   with patch('hotwatch_engine.utc',return_value=fixed),patch('mcp_client.MCP.request',side_effect=AssertionError('No broker calls')),sync_playwright() as p:
    browser=p.chromium.launch(**({} if os.environ.get('ESCAPE_PLAYWRIGHT_MANAGED') else {'executable_path':'/usr/bin/chromium'}),headless=True,args=['--no-sandbox'])
    page=browser.new_page(viewport={'width':1440,'height':1000},has_touch=True);errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(f'http://127.0.0.1:{server.server_port}');page.locator('#login-form [name=password]').fill('test-password-long-enough');page.locator('#login-form button').click();page.locator('nav [data-view=hot-watch]').click();page.locator('#engine-root').wait_for()
    page.evaluate('window.EngineUI.mount(true)')
    page.locator('[data-engine-detail="'+req['watch_id']+'"]').first.click()
    dialog=page.locator('#engine-dialog');expect(dialog).to_be_visible()
    expect(dialog.locator('[data-engine-sample-status]')).to_have_text('130 observationer hentet',timeout=30000)
    curve=dialog.locator('.engine-chart .inspect-chart-svg');assert curve.locator('.dash-chart-point').count()==130
    curve.scroll_into_view_if_needed();box=curve.bounding_box();page.mouse.move(box['x']+box['width']*.5,box['y']+box['height']*.5);tip=dialog.locator('.engine-chart .dash-chart-tooltip');expect(tip).to_be_visible();expect(tip.locator('[data-chart-date]')).not_to_be_empty()
    page.set_viewport_size({'width':390,'height':1000});curve.scroll_into_view_if_needed();box=curve.bounding_box();page.touchscreen.tap(box['x']+box['width']*.5,box['y']+box['height']*.5);expect(tip).to_be_visible();expect(tip.locator('[data-chart-value]')).not_to_be_empty()
    assert not errors,errors;browser.close()
  finally:server.shutdown();server.server_close()
 app.DB=old
 print('PASS: 130 actual recorded samples, touch and mouse')
if __name__=='__main__':main()
