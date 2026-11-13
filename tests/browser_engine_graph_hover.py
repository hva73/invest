"""Engine plus three-dimensional candidate lifecycle; fully synthetic browser test."""
import copy,json,os,sys,tempfile,threading,time
from pathlib import Path
from datetime import timedelta
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]));sys.path.insert(0,str(Path(__file__).resolve().parent))
import app,report_ingest,portfolio_data,portfolios,hotwatch_engine as engine
from hotwatch_strategy import BASELINE
from test_hotwatch_engine import request,tick
from test_intel_workflows import merc_report,decision
from playwright.sync_api import sync_playwright,expect

def main():
 def eodhd_fake(*args):
  time.sleep(.4)
  return {'ticker':'MERC','choices':[{'symbol':'MERC.US','name':'SYNTHETISK MERC-ACCEPTTEST','exchange':'US','currency':'USD','isin':None}]}
 old=app.DB
 with tempfile.TemporaryDirectory() as tmp:
  app.DB=tmp+'/db';app.init();app.create_user('test-password-long-enough');fixed=engine.utc().replace(microsecond=0);base=fixed-timedelta(minutes=40);r=merc_report(True);report_ingest.save(app.connect,1,r);req=request();engine.create(app.connect,1,req,base)
  prices=['100' if i%2==0 else '100.5' for i in range(34)]+['100.55','100.70','100.90','101.15','101.45','101.80']
  for i,price in enumerate(prices):
   at=base+timedelta(minutes=i);t=tick(at,i,price);t['volume']=str(100 if i<34 else 1000*2**(i-34));engine.ingest(app.connect,1,req['watch_id'],True,t,at)
  prod=merc_report(False);prod['report_id']='SYNTHETIC-STATUS-PRODUCTION-FIXTURE';prod['source']='KUN SYNTETISKE TESTDATA I MIDLERTIDIG DATABASE'
  for index,status in [(0,'CLOSED'),(1,'ARCHIVED')]:prod['candidates'][index]['lifecycle']={'status':status,'changed_at':prod['generated_at'],'reason':'Syntetisk lukning uden udført handel','source_ids':['synthetic-source'],'trade_cycle_id':'synthetic-cycle-'+str(index)}
  prod['candidates'][4].update(asset_id='synthetic-FCX',decision=decision('FRAVÆLG',prod['generated_at']));report_ingest.save(app.connect,1,prod)
  with app.connect() as c:
   portfolios.replace_pluto(c,1,[{'id':'portfolios:synthetic','name':'SYNTHETISK Pluto-depot','kind':'portfolio','can_trade':False}]);pid=c.execute("SELECT id FROM portfolios WHERE external_id='portfolios:synthetic'").fetchone()[0]
   payload={'source':'SYNTHETIC PROVIDER FIXTURE','observed':fixed.isoformat(),'kind':'portfolio','value':{'value':{'amount':'1000','currency':'DKK'},'reported_result':None,'source_time':fixed.isoformat()},'positions':portfolio_data.normalize_positions([{'assetId':'synthetic-FCX','ticker':'FCX','name':'SYNTHETISK FCX','quantity':'1','value':'100','currency':'USD'}]),'positions_complete':True,'accounts':[],'pending_orders':[],'complete':True,'orders_complete':True,'errors':[]};portfolio_data.save(c,1,pid,payload)
  server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
  try:
   with patch('hotwatch_engine.utc',return_value=fixed),patch('mcp_client.MCP.request',side_effect=AssertionError('No provider calls in this test')),patch('hotwatch_adapters.search_eodhd_symbols',side_effect=eodhd_fake),sync_playwright() as pw:
    browser=pw.chromium.launch(headless=True) if os.environ.get('ESCAPE_PLAYWRIGHT_MANAGED')=='1' else pw.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox']);page=browser.new_page(viewport={'width':1440,'height':1000});errors=[];page.on('pageerror',lambda e:errors.append(str(e)));page.goto(f'http://127.0.0.1:{server.server_port}');page.locator('#login-form [name=password]').fill('test-password-long-enough');page.locator('#login-form button').click();page.locator('nav [data-view=hot-watch]').click();page.locator('.engine-overview').wait_for();assert page.locator('.engine-list-row').count()==0
    page.locator('.hotwatch-mode summary').click();page.locator('#watch-mode').select_option('true');page.locator('.engine-list-row').wait_for();expect(page.locator('.engine-list-row')).to_contain_text('KØB');page.locator('.engine-list-row .engine-list-identity').click();dialog=page.locator('#engine-dialog');dialog.wait_for(state='visible');assert dialog.locator('.engine-chart path').count()==1
    curve=dialog.locator('.engine-chart .inspect-chart-svg');curve.scroll_into_view_if_needed();box=curve.bounding_box();page.mouse.move(box['x']+box['width']*.55,box['y']+box['height']*.5);tip=dialog.locator('.engine-chart .dash-chart-tooltip');expect(tip).to_be_visible();expect(tip).to_contain_text('Kurs');expect(tip.locator('[data-chart-share]')).to_contain_text('%')
    if os.environ.get('ESCAPE_SCREENSHOTS'): dialog.screenshot(path=str(Path(os.environ['ESCAPE_SCREENSHOTS'])/'motor-kurs-mouseover.png'))
    dialog.locator('h2').first.hover();expect(tip).to_be_hidden();curve.locator('.dash-chart-point').first.focus();expect(tip).to_be_visible()
    assert not errors,errors;browser.close()
   print('PASS: engine chart mouse and keyboard hover with real synthetic samples')
  finally:server.shutdown();server.server_close();app.DB=old
if __name__=='__main__':main()
