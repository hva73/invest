"""Temporary database production-partition fixtures; no real reports or trades."""
import sys,copy,json,tempfile,threading
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app,report_ingest
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]
def main():
 previous=app.DB
 with tempfile.TemporaryDirectory() as directory:
  app.DB=directory+'/db';app.init();app.create_user('browser-test-password-long')
  base=json.loads((ROOT/'examples/report-v2-test.json').read_text());base.update(report_id='desk-current-main',is_test=False,generated_at='2026-02-01T12:00:00Z');base['summary']['overview']='Syntetisk aktuel analyse til test af fordeling i appen.';
  for index,signal in enumerate(['OVERVÅG','SÆLG','AFVENT','BEHOLD'],1):
   candidate=copy.deepcopy(base['candidates'][0]);candidate.update(candidate_id='attention-'+str(index),ticker='STATUS-'+str(index),signal=signal,company_name='Syntetisk selskab med et langt navn til mobilkontrol '+str(index));base['candidates'].append(candidate)
  report_ingest.save(app.connect,1,base)
  deep=copy.deepcopy(base);deep.update(report_id='desk-latest-deep',generated_at='2026-02-02T12:00:00Z',report_type='deep_analysis',analysis_for={'candidate_id':'test-candidate-alpha','report_id':base['report_id']});deep['candidates'][0]['signal']='KØB';report_ingest.save(app.connect,1,deep)
  old=copy.deepcopy(base);old.update(report_id='desk-old-late-receipt',generated_at='2026-01-01T12:00:00Z');old['summary']['overview']='Ældre testanalyse, indsendt senere.';report_ingest.save(app.connect,1,old)
  test=copy.deepcopy(base);test.update(report_id='test-must-stay-hidden',is_test=True,generated_at='2026-03-01T12:00:00Z');report_ingest.save(app.connect,1,test)
  server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
  try:
   with sync_playwright() as p:
    browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox']);page=browser.new_page(viewport={'width':1440,'height':1000});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(f'http://127.0.0.1:{server.server_port}');page.locator('#login-form [name=password]').fill('browser-test-password-long');page.locator('#login-form button').click()
    page.locator('.desk-summary').wait_for();assert 'Syntetisk aktuel analyse' in page.locator('.desk-summary').inner_text()
    page.locator('nav [data-view=radar]').click();page.locator('.desk-candidate').first.wait_for();assert 'KØB' in page.locator('.desk-candidate').first.inner_text();assert page.locator('.desk-candidate').evaluate_all('(rows)=>rows.map(r=>r.dataset.attention)')==['red','red','yellow','yellow','green'];assert 'test-must-stay-hidden' not in page.locator('#content').inner_text()
    page.screenshot(path='/tmp/escape-latest-radar-desktop.png')
    for width in [320,390,430]:
     page.set_viewport_size({'width':width,'height':844});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
    page.set_viewport_size({'width':390,'height':844});page.locator('.desk-candidate').first.scroll_into_view_if_needed();page.screenshot(path='/tmp/escape-latest-radar-mobile.png')
    page.locator('.desk-candidate [data-deep]').first.click();page.locator('#analysis-dialog').wait_for(state='visible');assert 'desk-latest-deep' in page.locator('#analysis-prompt').input_value();page.locator('[data-close-analysis]').click()
    page.locator('nav [data-view=portfolios]').click();page.locator('.desk-portfolio').wait_for();assert 'Syntetisk hovedportefølje' in page.locator('.desk-portfolio').inner_text()
    page.locator('nav [data-view=trade]').click();page.get_by_text('Rapporteret ordrestatus',exact=True).wait_for();assert page.locator('#proposal').is_visible()
    page.locator('nav [data-view=journal]').click();page.get_by_text('Journal fra seneste hovedanalyse',exact=True).wait_for();assert 'Beslutningsjournal' in page.locator('#content').inner_text()
    page.locator('nav [data-view=reports]').click();page.locator('.intel-header').wait_for();assert 'desk-latest-deep' in page.locator('.intel-header').inner_text();assert page.locator('.intel-candidate').evaluate_all('(rows)=>rows.map(r=>r.dataset.attention)')==['red','red','yellow','yellow','green'];assert not page.locator('#report-history').is_visible()
    page.locator('.intel-toolbar [data-view=report-archive]').click();page.locator('#report-history').wait_for(state='visible');page.locator('#report-history option[value=desk-old-late-receipt]').wait_for(state='attached');page.locator('#report-history').select_option('desk-old-late-receipt');page.get_by_text('Ældre testanalyse, indsendt senere.',exact=True).wait_for()
    page.locator('.intel-toolbar [data-view=inbox]').click();page.locator('.intel-header').wait_for();assert 'desk-latest-deep' in page.locator('.intel-header').inner_text()
    for width in [320,390,430]:
     page.set_viewport_size({'width':width,'height':844})
     for target in ['overview','radar','portfolios','trade','journal','reports','settings']:
      page.locator('nav [data-view='+target+']').click()
      assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),(width,target)
    assert not errors,errors;browser.close()
   with app.connect() as c:assert c.execute('SELECT COUNT(*) FROM proposals').fetchone()[0]==0
   print('PASS: automatic latest analysis, late history stays archived, deep overlay, test isolation, Radar/portfolio/order/journal projections, 320–430px, direct deep package and separate archive')
  finally:server.shutdown();server.server_close();app.DB=previous
if __name__=='__main__':main()
