"""Synthetic V2.2 browser acceptance; no broker connections or live data."""
import copy,sys,tempfile,threading
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]));sys.path.insert(0,str(Path(__file__).resolve().parent))
import app,report_ingest,intel_workflows as flow
from test_intel_workflows import merc_report,observation,decision
from playwright.sync_api import sync_playwright,expect

def main():
 old=app.DB
 with tempfile.TemporaryDirectory() as tmp:
  app.DB=tmp+'/db';app.init();app.create_user('test-password-long-enough');r=merc_report();root,ai=r['portfolios'];root.update(value={'amount':'1000','currency':'DKK'},valuation_method='synthetic-comparable',includes_collections=True,liquidity={'available':[{'amount':'100','currency':'DKK'}],'reserved':[{'amount':'20','currency':'DKK'}],'earmarked':[],'unknown':[]});ai.update(value={'amount':'200','currency':'DKK'},valuation_method='synthetic-comparable')
  r['summary']['regions']=[{'region':name,'summary':'Syntetisk regionsstatus','source_ids':['synthetic-source'],'coverage':{'exchanges':['SYNTHETIC EXCHANGE'],'status':status,'screening_count':5 if status=='OK' else None,'data_at':r['generated_at'] if status=='OK' else None,'news_checked_at':None,'new_signals':1 if status=='OK' else None,'pluto_verified':None,'excluded':None,'gaps':['Syntetisk dækningshul'],'basis':'previous_close' if status=='OK' else 'unknown'}} for name,status in [('Europa / Norden','OK'),('USA / Canada','OK'),('Asien / Stillehav','FEJL'),('Råvarer / Metaller','IKKE KØRT')]]
  report_ingest.save(app.connect,1,r);a=observation(r);flow.record(app.connect,1,a);b=observation(r,'SYNTHETIC-MERC-OBS-2','2026-11-03T10:10:00Z');b['market']['price']['amount']='8';b['market']['momentum']='accelerating';b['position_action']={'action':'SÆLG','reason':'Syntetisk positionsbeslutning, ingen handel','assessed_at':b['observed_at'],'source_ids':['synthetic-source']};flow.record(app.connect,1,b)
  server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
  try:
   with patch('mcp_client.MCP',side_effect=AssertionError('No broker reads/writes in this browser acceptance')),sync_playwright() as pw:
    browser=pw.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox']);page=browser.new_page(viewport={'width':1440,'height':1000});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(f'http://127.0.0.1:{server.server_port}');page.locator('#login-form [name=password]').fill('test-password-long-enough');page.locator('#login-form button').click();summary=page.locator('.intel-control-summary');summary.wait_for();assert '800,00' in summary.inner_text();assert '1.000,00' in summary.inner_text();summary.locator('[data-view=hot-watch]').click();page.locator('.watch-group').wait_for();assert page.locator('.watch-observation').count()==2;expect(page.locator('.watch-group')).to_contain_text('AFVENT');page.locator('.watch-group>details').last.locator('summary').click();assert 'ingen bekræftet fyldning' in page.locator('.watch-group').inner_text();page.locator('.watch-observation>summary').first.click();assert 'SÆLG' in page.locator('.watch-observation').first.inner_text();assert 'Dette er en vurdering, ikke en udført handel' in page.locator('.watch-observation').first.inner_text()
    page.locator('[data-intel-history]').first.click();dialog=page.locator('#intel-detail-dialog');dialog.wait_for(state='visible');assert 'SYNTHETIC-MERC-BASE' in dialog.inner_text();assert dialog.locator('.watch-observation').count()==2;page.keyboard.press('Escape');dialog.wait_for(state='hidden')
    for width in [320,375,390,430,768,1024,1440,1920]:
     page.set_viewport_size({'width':width,'height':1000});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),('watch-overflow',width)
     page.locator('[data-intel-history]').first.click();dialog.wait_for(state='visible');assert dialog.evaluate('(n)=>n.scrollWidth<=n.clientWidth+1'),('history-overflow',width);page.keyboard.press('Escape');dialog.wait_for(state='hidden')
     if width in [390,1440]:page.screenshot(path=f'/tmp/escape-hot-watch-{width}.png',full_page=True)
    page.locator('#watch-mode').select_option('true');expect(page.locator('#watch-content')).to_contain_text('Ingen HOT WATCH');assert page.locator('.watch-group').count()==0;page.locator('#watch-mode').select_option('false');page.locator('.watch-group').wait_for()
    # A report can independently confirm partial execution after the last watch measurement.
    new=copy.deepcopy(r);new.update(report_id='SYNTHETIC-MERC-PARTIAL',generated_at='2026-11-03T10:20:00Z');new['orders'][0].update(status='PARTIALLY_FILLED',lifecycle='partial',filled_quantity='4',average_fill_price={'amount':'8','currency':'USD'});report_ingest.save(app.connect,1,new);page.locator('[data-watch-refresh]').click();expect(page.locator('.watch-group')).to_contain_text('Delvist udført');page.locator('.watch-group>details').last.locator('summary').click();assert 'Pluto-status som oplyst: PARTIALLY_FILLED' in page.locator('.watch-group').inner_text()
    page.locator('nav [data-view=reports]').click();page.locator('.region-coverage').first.wait_for();assert page.locator('.region-coverage').count()==4;assert 'Senest afsluttede handelsdag' in page.locator('.region-coverage').first.inner_text();assert 'FEJL' in page.locator('.region-coverage').nth(2).inner_text();assert 'IKKE KØRT' in page.locator('.region-coverage').nth(3).inner_text();expect(page.locator('.delivery-evidence')).to_contain_text('Læst tilbage')
    for width in [320,390,768,1440]:
     page.set_viewport_size({'width':width,'height':1000});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),('analysis-overflow',width)
    page.locator('nav [data-view=radar]').click();page.locator('.candidate-decision').first.wait_for();assert page.locator('.desk-candidate').count()==12
    # FRAVÆLG removes only the active candidate; history stays clickable.
    end=copy.deepcopy(new);end.update(report_id='SYNTHETIC-MERC-REJECTED',generated_at='2026-11-03T10:30:00Z');end['candidates'][0]['decision']=decision('FRAVÆLG',end['generated_at']);report_ingest.save(app.connect,1,end);page.locator('#refresh-current').click();expect(page.locator('.desk-candidate')).to_have_count(11);expect(page.locator('.dormant-candidates')).to_contain_text('MERC');page.locator('.dormant-candidates>summary').click();page.locator('.dormant-candidates [data-intel-history]').click();dialog.wait_for(state='visible');assert 'FRAVÆLG' in dialog.inner_text();assert not errors,errors;browser.close()
   with app.connect() as c:
    assert c.execute('SELECT count(*) FROM broker_proposals').fetchone()[0]==0
    assert c.execute('SELECT count(*) FROM proposals').fetchone()[0]==0
   print('PASS: HOT WATCH MERC timeline, independent sale assessment and zero/partial fill, current order evidence, candidate history and dormant state, category isolation, comparable root-minus-AI, four region statuses, readback evidence, 320–1920px, no broker access')
  finally:server.shutdown();server.server_close();app.DB=old
if __name__=='__main__':main()
