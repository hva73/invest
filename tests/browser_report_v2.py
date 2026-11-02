"""Synthetic report v2, archive, deep-analysis fallback and import UI verification."""
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
  legacy=json.loads((ROOT/'examples/report-ingest-test.json').read_text());legacy.update(report_id='escape-historical-20261101-2200-v1',is_test=True)
  # All fixtures stay in the test partition, including the synthetic legacy-id regression.
  for i in range(2):report_ingest.save(app.connect,1,dict(legacy,report_id='legacy-dummy-'+str(i)))
  assert report_ingest.save(app.connect,1,legacy)[1]['id']==3
  data=json.loads((ROOT/'examples/report-v2-test.json').read_text())
  for i in range(5):
   candidate=copy.deepcopy(data['candidates'][0]);candidate.update(candidate_id='extra-'+str(i),ticker='SYN-'+str(i),company_name='Syntetisk selskab '+str(i));data['candidates'].append(candidate)
  data['candidates'][0]['risks']=['Lang syntetisk risikobeskrivelse. '*150]
  for i in range(60):data['sources'].append(dict(data['sources'][0],source_id='synthetic-extra-'+str(i)))
  report_ingest.save(app.connect,1,data)
  follow=copy.deepcopy(data);follow.update(report_id='escape-v2-synthetic-002',generated_at='2026-01-03T12:00:00Z');follow['candidates'][0]['signal']='AFVENT';report_ingest.save(app.connect,1,follow)
  server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
  try:
   with sync_playwright() as p:
    browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
    context=browser.new_context(viewport={'width':1440,'height':1000},permissions=['clipboard-read','clipboard-write'])
    context.route('https://chatgpt.com/**',lambda route:route.fulfill(status=200,body='ChatGPT destination stub; no plugin selection or delivery.'))
    page=context.new_page();page.route('**/report-ui.js',lambda route:route.abort());errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(f'http://127.0.0.1:{server.server_port}')
    page.locator('#login-form [name=password]').fill('browser-test-password-long');page.locator('#login-form button').click();page.locator('#content .hero').wait_for()
    page.locator('nav [data-view=reports]').click();page.locator('[data-view=inbox]').click();page.locator('#report-mode').select_option('true');page.locator('#load-ingested-report').click()
    page.locator('.intel-header').wait_for();assert page.locator('.intel-candidate').count()==6
    assert 'Samlet værdi vises ikke' in page.locator('.intel-consolidation').inner_text()
    assert 'signal' in page.locator('#ingested-report').inner_text()
    page.screenshot(path='/tmp/escape-intelligence-desktop.png')
    for width in [320,375,390,430,768]:
     page.set_viewport_size({'width':width,'height':844})
     assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
    page.set_viewport_size({'width':390,'height':844});page.locator('.intel-header').scroll_into_view_if_needed();page.screenshot(path='/tmp/escape-intelligence-mobile.png')
    first=page.locator('.intel-candidate').first
    first.locator('header').scroll_into_view_if_needed();page.screenshot(path='/tmp/escape-intelligence-candidate-mobile.png')
    first.locator('[data-deep]').click();page.locator('#analysis-dialog').wait_for(state='visible')
    prompt=page.locator('#analysis-prompt').input_value();assert 'test-candidate-alpha' in prompt and 'escape-v2-synthetic-002' in prompt and 'Lang syntetisk' in prompt
    page.locator('#copy-analysis').click();page.get_by_text('Analysepakken er kopieret.',exact=False).wait_for();assert await_clipboard(page)==prompt
    with page.expect_popup() as popup:page.get_by_role('link',name='Åbn ChatGPT',exact=False).click()
    destination=popup.value;destination.wait_for_load_state();assert destination.url=='https://chatgpt.com/';destination.close()
    page.evaluate("Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:()=>Promise.reject(new Error('denied'))}})")
    page.locator('#copy-analysis').click();page.get_by_text('Automatisk kopiering er ikke tilgængelig.',exact=False).wait_for()
    assert page.locator('#analysis-prompt').evaluate('(x)=>x.selectionEnd-x.selectionStart')==len(prompt)
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    page.screenshot(path='/tmp/escape-intelligence-deep-fallback.png')
    page.locator('[data-close-analysis]').click();first.locator('[data-candidate-history]').click();page.get_by_text('Vedvarende kandidathistorik',exact=True).wait_for()
    # Return a deeper analysis through the actual authenticated import endpoint.
    deep=copy.deepcopy(follow);deep.update(report_id='escape-deep-return-test',report_type='deep_analysis',generated_at='2026-01-04T12:00:00Z',analysis_for={'candidate_id':'test-candidate-alpha','report_id':follow['report_id']});deep['candidates'][0]['assessment']='Uddybning modtaget fra syntetisk import.'
    file=Path(directory)/'deep.json';file.write_text(json.dumps(deep,ensure_ascii=False))
    page.get_by_text('Importér analyse fra ChatGPT',exact=True).click();page.once('dialog',lambda dialog:dialog.accept());page.locator('#report-import').set_input_files(str(file))
    page.get_by_text('Rapporten er importeret.',exact=True).wait_for();page.get_by_text('Uddybning modtaget fra syntetisk import.',exact=True).first.wait_for()
    first=page.locator('.intel-candidate').first;first.locator('[data-candidate-history]').click();page.locator('.intel-candidate-history').first.get_by_text('escape-v2-synthetic-002',exact=False).wait_for();assert 'escape-v2-synthetic-002' in page.locator('.intel-candidate-history').first.inner_text()
    # Legacy DB id 3 is preserved and uncertainty is explicit.
    page.locator('#report-history').select_option(legacy['report_id']);page.get_by_text('Collection-overlap er ikke dokumenteret;',exact=False).wait_for()
    assert page.locator('[data-deep-legacy]').count()==1
    page.locator('[data-deep-legacy]').click();page.locator('#analysis-dialog').wait_for(state='visible');assert '"candidate_id": null' in page.locator('#analysis-prompt').input_value();page.locator('[data-close-analysis]').click()
    page.locator('#report-mode').select_option('false');page.locator('#load-ingested-report').click();page.get_by_text('Ingen rapport modtaget',exact=True).wait_for()
    assert not errors,errors
    browser.close()
   with app.connect() as c:
    assert c.execute('SELECT COUNT(*) FROM proposals').fetchone()[0]==0
    assert json.loads(c.execute('SELECT payload FROM ingested_reports WHERE id=3').fetchone()[0])==legacy
   print('PASS: v2 many candidates/sources, historical overlap warning, 320–768px, archive comparison, clipboard + denied fallback, ChatGPT homepage link, deep JSON import, candidate history, immutable v1 id3 and test isolation')
  finally:server.shutdown();server.server_close();app.DB=previous

def await_clipboard(page):return page.evaluate('navigator.clipboard.readText()')
if __name__=='__main__':main()
