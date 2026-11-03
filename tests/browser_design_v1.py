"""Synthetic broker-first redesign: actual computed colors, compact rows and all nine widths."""
import sys,copy,threading
from pathlib import Path
from datetime import timedelta
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]));sys.path.insert(0,str(Path(__file__).resolve().parent))
import app,portfolio_data,report_ingest,hotwatch_engine as engine
import test_design_v1_acceptance as fixtures
from playwright.sync_api import sync_playwright,expect

def main():
 case=fixtures.DesignAcceptance();case.setUp();now=fixtures.NOW
 try:
  d=copy.deepcopy(case.report);d.update(report_id='design-browser-assessment',generated_at=(now+timedelta(seconds=1)).isoformat());d['positions'][1]['assessment'].update(action='SÆLG',assessed_at=d['generated_at']);d['positions'][0]['assessment']['assessed_at']=(now-timedelta(hours=25)).isoformat();report_ingest.save(app.connect,1,d)
  with app.connect() as c:
   for port in case.ports:
    snap=portfolio_data.snapshots(c,1)[str(port['id'])]['data']
    for row in snap['positions']:
     if row['ticker']=='TSLA':row['unrealized']['amount']='-10';row['value']={'amount':'100','currency':'USD'}
     if row['ticker']=='MSFT':row['official_close_reference']['price']='51'
    portfolio_data.save(c,1,port['id'],snap)
  waiting=copy.deepcopy(d);waiting.update(report_id='design-waiting-trigger',generated_at=(now+timedelta(seconds=2)).isoformat());waiting['candidates'][1]['lifecycle']={'status':'WAITING_TRIGGER','changed_at':waiting['generated_at'],'reason':'SYNTHETIC waiting trigger','source_ids':['synthetic-source'],'trade_cycle_id':'synthetic-waiting'};report_ingest.save(app.connect,1,waiting)
  from test_hotwatch_engine import request
  for status in ['DEGRADED','ERROR','PAUSED','COMPLETED']:
   req=request(False,'synthetic-browser-'+status);req.update(report_id=waiting['report_id'],candidate_id=waiting['candidates'][0]['candidate_id'],ticker=waiting['candidates'][0]['ticker'],purpose='SYNTHETIC '+status,provider='report_inbox');engine.create(app.connect,1,req)
   if status in ['DEGRADED','ERROR']:engine.fault(app.connect,1,req['watch_id'],False,'sample_identity_mismatch' if status=='ERROR' else 'SYNTHETIC_SOURCE_ERROR')
   else:engine.control(app.connect,1,req['watch_id'],False,'pause' if status=='PAUSED' else 'stop')
  server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
  try:
   with patch('mcp_client.MCP.request',side_effect=AssertionError('No live broker in design acceptance')),sync_playwright() as pw:
    browser=pw.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox']);page=browser.new_page(viewport={'width':1440,'height':1000});errors=[];page.on('pageerror',lambda e:errors.append(str(e)));page.goto(f'http://127.0.0.1:{server.server_port}');page.locator('#login-form [name=password]').fill('test-password-long-enough');page.locator('#login-form button').click();page.locator('.dash-row').first.wait_for();expect(page.locator('.dash-row')).to_have_count(12)
    self_count=page.locator('.dash-row .dash-instrument strong').filter(has_text='BTC').count();assert self_count==2
    tsla=page.locator('.dash-row').filter(has=page.locator('.dash-instrument strong',has_text='TSLA'));msft=page.locator('.dash-row').filter(has=page.locator('.dash-instrument strong',has_text='MSFT'))
    assert 'USD' in tsla.inner_text() or 'US$' in tsla.inner_text();assert 'Analyse >24 timer' in tsla.inner_text();assert tsla.locator('.dash-daily').inner_text().startswith('↑');assert tsla.locator('.dash-pnl .dash-change').evaluate('(n)=>getComputedStyle(n).color')=='rgb(240, 154, 166)'
    for node,expected,arrow in [(tsla.locator('.dash-daily .dash-change'),'rgb(139, 223, 184)','↑'),(msft.locator('.dash-daily .dash-change'),'rgb(240, 154, 166)','↓')]:
     assert arrow in node.inner_text();assert node.evaluate('(n)=>getComputedStyle(n).color')==expected
     node.hover();assert node.evaluate('(n)=>getComputedStyle(n).color')==expected
    assert tsla.locator('.dash-value').evaluate('(n)=>getComputedStyle(n).color') not in ['rgb(139, 223, 184)','rgb(240, 154, 166)'];assert page.locator('.dash-total').count()==1;assert '1.000,00' in page.locator('.dash-total').inner_text()
    page.locator('#dashboard-sort').select_option('ticker');expect(page.locator('.dash-instrument strong').first).to_have_text('AMGN')
    for width in [320,375,390,430,768,1024,1280,1440,1920]:
     page.set_viewport_size({'width':width,'height':1000});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),('overflow',width);expect(page.locator('.dash-row')).to_have_count(12)
     if width<=900:
      assert max(page.locator('.dash-row').evaluate_all('(rows)=>rows.map(n=>n.getBoundingClientRect().height)'))<220,('rows too tall',width)
     tsla.locator('[data-dashboard-open]').first.click();dialog=page.locator('#dashboard-detail');dialog.wait_for(state='visible');assert 'Fuld præcision' in dialog.inner_text();assert dialog.evaluate('(n)=>n.scrollWidth<=n.clientWidth+1'),('dialog',width);page.keyboard.press('Escape');expect(dialog).not_to_be_visible()
     if width in [390,1440]:page.screenshot(path=f'/tmp/escape-design-v1-overview-{width}.png',full_page=True)
    page.locator('nav [data-view=portfolios]').click();page.locator(f'[data-open-portfolio="{case.root["id"]}"]').first.click();page.locator('.dash-holdings').wait_for();expect(page.locator('.dash-row')).to_have_count(7);page.locator('#dashboard-sort').select_option('ticker');expect(page.locator('.dash-row')).to_have_count(7)
    for width in [320,375,390,430,768,1024,1280,1440,1920]:
     page.set_viewport_size({'width':width,'height':1000});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),('portfolio',width)
    # All eight functions remain reachable; journal/report/source details remain read-only.
    for target in ['portfolios','radar','hot-watch','trade','journal','reports','settings','overview']:
     page.locator('nav [data-view='+target+']').click();page.wait_for_timeout(200)
     for width in [320,375,390,430,768,1024,1280,1440,1920]:
      page.set_viewport_size({'width':width,'height':1000});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),(target,width)
      if width in [390,1440]:page.screenshot(path=f'/tmp/escape-design-v1-{target}-{width}.png',full_page=True)
     if target=='hot-watch':
      page.locator('.watch-waiting').wait_for();assert not page.locator('.watch-waiting').evaluate('(n)=>n.open');assert '1' in page.locator('.watch-waiting>summary').inner_text();page.locator('.engine-session-group.critical').wait_for();assert page.locator('.engine-session-group.critical').is_visible();assert page.locator('.engine-session-group.warning').is_visible();assert not page.locator('details[data-engine-group=history]').evaluate('(n)=>n.open');page.locator('[data-engine-filter=BUY]').click();assert page.locator('.engine-session-group.critical .engine-card').is_visible()
     if target=='journal':page.locator('#journal-events').wait_for();assert page.locator('#journal-days').input_value()=='7';assert 'could not' not in page.locator('#journal-events').inner_text().lower()
     if target=='reports':page.locator('.report-contents').wait_for();assert not page.locator('.report-full-analysis').evaluate('(n)=>n.open');page.locator('.report-contents a').first.click();assert page.locator('.report-full-analysis').evaluate('(n)=>n.open')
    assert not errors,errors;browser.close()
   with app.connect() as c:assert c.execute('SELECT count(*) FROM broker_proposals').fetchone()[0]==0
   print('PASS T03/T04/T06/T10/T11/T12/T13/T14/T17/T23/T24: 12 broker holdings, neutral absolute values, actual red/green+arrows+hover, stale assessment retained, two BTC depots, exact root total, unknown FX fallback, sorting/dialogs, all 9 widths, eight functions, no broker calls or proposals')
  finally:server.shutdown();server.server_close()
 finally:case.tearDown()
if __name__=='__main__':main()
