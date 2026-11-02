"""Interactive overview, synthetic reports and stubbed quote reads only."""
import copy,sys,threading
from pathlib import Path
from datetime import datetime,timezone
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]));sys.path.insert(0,str(Path(__file__).resolve().parent))
import app,report_ingest,market_data,portfolio_data
import test_market_data as market_fixture
from test_report_validation import full_report
from playwright.sync_api import sync_playwright,expect

def main():
 case=market_fixture.Quotes();case.setUp();previous=full_report(9);previous.update(report_id='overview-base',is_test=False,generated_at='2027-01-02T12:00:00Z')
 for p in previous['portfolios']:p['as_of']=previous['generated_at']
 report_ingest.save(app.connect,1,previous)
 current=full_report(12);current.update(report_id='overview-current',is_test=False,generated_at='2027-01-03T12:00:00Z')
 for p in current['portfolios']:p['as_of']=current['generated_at']
 current['portfolios'][0].update(value={'amount':'1025.25','currency':'DKK'},cash=[{'amount':'175.50','currency':'DKK'}])
 for i,c in enumerate(current['candidates']):c.update(signal='AFVENT' if i==0 else 'OVERVÅG' if i==1 else 'BEHOLD',assessment='Konkret syntetisk vurdering '+str(i),next_action='Kontrollér den nævnte begivenhed '+str(i))
 current['candidates'][0]['ticker']='CHART';report_ingest.save(app.connect,1,current)
 calls=[]
 def quote(connect,uid,data):
  assert uid==1 and data['report_id']=='overview-current';c=next(c for c in current['candidates'] if c['candidate_id']==data['candidate_id']);calls.append(data)
  q=market_data.normalized(case.raw,'synthetic-chart-asset',datetime.now(timezone.utc));q['ticker']=c['ticker'];q['asset_id']='synthetic-'+c['candidate_id']
  if c['signal']=='OVERVÅG':q.update(daily_change='-0.225',daily_change_percent='-1.222')
  return q
 payload={'source':'Synthetic','observed':datetime.now(timezone.utc).isoformat(),'kind':'portfolio','positions':[],'accounts':[],'pending_orders':[],'value':{'value':{'amount':'1000','currency':'DKK'},'reported_result':{'amount':'-12.50','currency':'DKK'},'source_time':datetime.now(timezone.utc).isoformat()},'errors':[],'complete':True,'orders_complete':True}
 payload['accounts']=portfolio_data.normalize_accounts([{'currency':'DKK','balance':'300','reservedForOrders':'100','buyingPower':'200','asOf':datetime.now(timezone.utc).isoformat()}])
 items=[{'id':'portfolios:root','name':'Synthetic root','kind':'portfolio','can_trade':True}]
 server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
 try:
  with patch('market_data.quote',side_effect=quote),patch('mcp_client.read_portfolios',return_value=items),patch('portfolio_data.read',return_value=payload),patch('trade_service.MCP',side_effect=AssertionError('No trades')),sync_playwright() as p:
   browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox']);page=browser.new_page(viewport={'width':1440,'height':1000});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
   page.goto(f'http://127.0.0.1:{server.server_port}');page.locator('#login-form [name=password]').fill('test-password-long-enough');page.locator('#login-form button').click();page.locator('.desk-summary').wait_for();page.locator('#refresh-status[data-kind=success]').wait_for()
   assert page.locator('.account-overview-card').count()==1;assert page.locator('.collection-children').count()==0;assert page.locator('.account-result .pnl.negative').count()==1;assert not page.locator('.overview-report-values').evaluate('(n)=>n.open')
   assert 'Dine porteføljer / Collections' not in page.locator('#content').inner_text()
   assert 'Hold øje med disse kandidater' in page.locator('.desk-summary').inner_text();page.locator('.overview-next .market-slot').first.scroll_into_view_if_needed();page.locator('.overview-next .market-change.market-positive').wait_for();page.locator('.overview-next .market-change.market-negative').wait_for()
   assert page.locator('.overview-next .market-origin').first.is_visible();assert 'kurstid ukendt' in page.locator('.overview-next .market-origin').first.inner_text()
   positive=page.locator('.overview-next .market-change.market-positive');negative=page.locator('.overview-next .market-change.market-negative');assert positive.evaluate('(n)=>getComputedStyle(n).color')!=negative.evaluate('(n)=>getComputedStyle(n).color')
   before=len(calls);page.locator('.overview-next [data-market-expand]').first.click();chart=page.locator('#market-chart-dialog');chart.wait_for(state='visible');assert chart.locator('.market-line').get_attribute('d').count('L')==1
   chart.locator('[data-market-period=week]').click();assert chart.locator('.market-line').get_attribute('d').count('L')==81;assert len(calls)==before
   page.keyboard.press('Escape');expect(page.locator('.overview-next [data-market-expand]').first).to_be_focused()
   assert page.locator('.overview-value-link.market-positive').count()==1;assert page.locator('.overview-cash-link.market-negative').count()==1
   page.locator('.overview-report-values>summary').click();page.locator('.overview-value-link').click();dialog=page.locator('#overview-detail-dialog');dialog.wait_for(state='visible');assert dialog.locator('[data-open-report=overview-base]').count()==1;assert dialog.locator('.overview-detail-row').count()==12;page.keyboard.press('Escape')
   for kind,count in [('positions',11),('orders',15),('candidates',12)]:
    button=page.locator('.overview-counts [data-overview-detail='+kind+']');button.click();assert dialog.locator('.overview-detail-row').count()==count;page.keyboard.press('Escape');assert button.evaluate('(n)=>n===document.activeElement')
   page.locator('.overview-status-links [data-overview-index=red]').click();assert 'Ingen kandidater i denne gruppe' in dialog.inner_text();dialog.locator('[data-overview-index=yellow]').click();assert dialog.locator('.overview-detail-row').count()==2
   dialog.locator('.overview-candidate-link').first.click();assert 'Konkret syntetisk vurdering 0' in dialog.inner_text();assert 'Kontrollér den nævnte begivenhed 0' in dialog.inner_text();dialog.locator('[data-overview-close]').click()
   page.locator('.overview-next [data-deep]').first.click();page.locator('#analysis-dialog').wait_for(state='visible');assert 'overview-current' in page.locator('#analysis-prompt').input_value();page.locator('[data-close-analysis]').click()
   page.locator('.overview-report-values>summary').click()
   for width in [320,390,430,768,1024,1440,1920]:
    page.set_viewport_size({'width':width,'height':1000});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),width
    page.locator('.overview-counts [data-overview-detail=orders]').click();assert dialog.evaluate('(n)=>n.scrollWidth<=n.clientWidth+1'),('dialog',width);dialog.locator('[data-overview-close]').click()
    page.locator('.overview-next [data-market-expand]').first.click();assert chart.evaluate('(n)=>n.scrollWidth<=n.clientWidth+1'),('chart',width);page.keyboard.press('Escape')
    if width in [390,1440]:page.screenshot(path=f'/tmp/escape-overview-actions-{width}.png',full_page=True)
   assert not errors,errors;assert calls;browser.close()
  with app.connect() as c:assert c.execute('SELECT COUNT(*) FROM proposals').fetchone()[0]==0;assert c.execute('SELECT COUNT(*) FROM broker_proposals').fetchone()[0]==0
  print('PASS: every overview metric opens exact source records; 11 positions, 15 orders, 12 candidates; zero/nonzero status filters; concrete candidate details/deep package; green/red daily quotes and balance changes; keyboard focus/Escape; 320–1920px; no proposals')
 finally:server.shutdown();server.server_close();case.tearDown()
if __name__=='__main__':main()
