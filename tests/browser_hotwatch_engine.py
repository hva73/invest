"""Engine plus three-dimensional candidate lifecycle; fully synthetic browser test."""
import copy,json,sys,tempfile,threading
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
   with patch('hotwatch_engine.utc',return_value=fixed),patch('mcp_client.MCP.request',side_effect=AssertionError('No provider calls in this test')),sync_playwright() as pw:
    browser=pw.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox']);page=browser.new_page(viewport={'width':1440,'height':1000});errors=[];page.on('pageerror',lambda e:errors.append(str(e)));page.goto(f'http://127.0.0.1:{server.server_port}');page.locator('#login-form [name=password]').fill('test-password-long-enough');page.locator('#login-form button').click();page.locator('nav [data-view=hot-watch]').click();page.locator('.engine-overview').wait_for();assert page.locator('.engine-card').count()==0
    page.locator('#watch-mode').select_option('true');page.locator('.engine-card').wait_for();expect(page.locator('.engine-card')).to_contain_text('KØB');page.locator('.engine-card .engine-title').click();dialog=page.locator('#engine-dialog');dialog.wait_for(state='visible');assert dialog.locator('.engine-chart path').count()==1;assert 'Ingen bekræftet fyldning' not in dialog.inner_text();assert 'escape_momentum v1.0.0' in dialog.inner_text();assert 'ikke en statistisk' in dialog.inner_text();page.keyboard.press('Escape');dialog.wait_for(state='hidden')
    page.locator('[data-engine-control=pause]').click();expect(page.locator('.engine-card')).to_contain_text('Pauseret');page.locator('[data-engine-control=resume]').click();expect(page.locator('.engine-card')).to_contain_text('Validerer')
    page.locator('[data-engine-new]').click();dialog.wait_for(state='visible');form=page.locator('#engine-create');form.locator('[name=candidate]').select_option('0');form.locator('[name=provider]').select_option('synthetic');form.locator('[name=exchange]').fill('NASDAQ');form.locator('[name=asset_id]').fill('synthetic-MERC');form.locator('[name=quote_currency]').fill('USD');form.locator('[name=purpose]').fill('manual-synthetic-check');form.locator('[name=activation_reason]').fill('Syntetisk UI-test, ingen reel investering');form.locator('button').click();dialog.wait_for(state='hidden');expect(page.locator('.engine-card')).to_have_count(2)
    page.locator('[data-engine-strategies]').click();dialog.wait_for(state='visible');strategy=copy.deepcopy(BASELINE);strategy['version']='1.1.0';page.locator('#engine-strategy-file').set_input_files({'name':'synthetic-strategy.json','mimeType':'application/json','buffer':json.dumps(strategy).encode()});expect(page.locator('#engine-strategy-status')).to_contain_text('gemt inaktiv');assert 'ikke implementeret' in dialog.inner_text();page.keyboard.press('Escape');dialog.wait_for(state='hidden')
    page.once('dialog',lambda d:d.accept());page.locator('[data-engine-kill=on]').click();expect(page.locator('.engine-alert')).to_contain_text('NØDSTOP');assert page.locator('[data-engine-control=resume]').count()==2
    for width in [320,375,390,430,768,1024,1440,1920]:
     page.set_viewport_size({'width':width,'height':1000});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),('engine-overflow',width);page.locator('.engine-title').first.click();dialog.wait_for(state='visible');assert dialog.evaluate('(n)=>n.scrollWidth<=n.clientWidth+1'),('detail-overflow',width);page.keyboard.press('Escape');dialog.wait_for(state='hidden')
     if width in [390,1440]:page.screenshot(path=f'/tmp/escape-engine-{width}.png',full_page=True)
    page.locator('nav [data-view=radar]').click();page.locator('.candidate-lifecycle-filters').wait_for();page.locator('[data-candidate-filter=closed]').click();expect(page.locator('.desk-candidate:not([hidden])')).to_have_count(1);expect(page.locator('.desk-candidate:not([hidden])')).to_contain_text('MERC');assert 'Ingen bekræftet udførelse' in page.locator('.desk-candidate:not([hidden])').inner_text()
    page.locator('[data-candidate-filter=position]').click();expect(page.locator('.desk-candidate:not([hidden])')).to_have_count(1);expect(page.locator('.desk-candidate:not([hidden])')).to_contain_text('FCX');assert 'FRAVÆLG' in page.locator('.desk-candidate:not([hidden])').inner_text();assert 'Egen position er særskilt bekræftet' in page.locator('.desk-candidate:not([hidden])').inner_text()
    # Attention buttons must not resurrect closed/archived rows or discard the lifecycle selection.
    page.locator('[data-candidate-filter=active]').click();active_count=page.locator('.desk-candidate:not([hidden])').count();page.locator('.desk-radar [data-attention-filter=all]').click();expect(page.locator('.desk-candidate:not([hidden])')).to_have_count(active_count);assert page.locator('.desk-candidate[data-candidate-lifecycle=CLOSED]:not([hidden]),.desk-candidate[data-candidate-lifecycle=ARCHIVED]:not([hidden])').count()==0
    page.locator('[data-candidate-filter=closed]').click();page.locator('.desk-radar [data-attention-filter=all]').click();expect(page.locator('.desk-candidate:not([hidden])')).to_have_count(1)
    page.locator('[data-candidate-filter=archived]').click();expect(page.locator('.desk-candidate:not([hidden])')).to_have_count(2);page.locator('[data-candidate-filter=all]').click();expect(page.locator('.desk-candidate:not([hidden])')).to_have_count(12)
    assert not errors,errors;browser.close()
   with app.connect() as c:
    assert c.execute('SELECT count(*) FROM broker_proposals').fetchone()[0]==0
    assert c.execute('SELECT count(*) FROM proposals').fetchone()[0]==0
   print('PASS: synthetic engine BUY, immutable chart/features/events, pause/resume, manual test session, inactive strategy upload, kill switch, 320–1920px; independent lifecycle/decision/execution filters, owned FCX with REJECT, persistent closed/archived candidates; no provider or trading calls')
  finally:server.shutdown();server.server_close();app.DB=old
if __name__=='__main__':main()
