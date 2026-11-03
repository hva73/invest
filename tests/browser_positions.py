"""Complete synthetic holdings, Collections and source-linked report totals."""
import copy,sys,threading
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]));sys.path.insert(0,str(Path(__file__).resolve().parent))
import app,report_ingest,portfolio_data,trade_service
import test_market_data as quotes
from test_position_reports import full_positions
from playwright.sync_api import sync_playwright,expect

def main():
 case=quotes.Quotes();case.setUp();old=full_positions('positions-old','2027-01-02T15:00:00Z');report_ingest.save(app.connect,1,old)
 data=full_positions('positions-current','2027-01-03T15:00:00Z');data['positions'][0]['assessment']=None;data['positions'][9]['assessment']['action']='REDUCÉR'
 data['orders']=[{'order_id':'stop-test','portfolio_id':'test-main','candidate_id':None,'asset_id':'synthetic-asset-TSLA','ticker':'TSLA','side':'SELL','order_type':'STOP','status':'ACTIVE_STOP','lifecycle':'pending','requested_quantity':'2','filled_quantity':'0','allocated':None,'as_of':data['generated_at'],'source_ids':['synthetic-source'],'note':'Kun syntetisk ordreobservation','stop_price':{'amount':'20','currency':'USD'}}];report_ingest.save(app.connect,1,data)
 calls=[]
 class Client:
  def __init__(self,token):assert token=='synthetic'
  def tools(self):return [{'name':n,'inputSchema':copy.deepcopy(trade_service.CONTRACT[n]['inputSchema']),'annotations':{'readOnlyHint':True}} for n in ['search_assets','get_asset']]
  def request(self,method,args):
   calls.append(args);aid=args['arguments'].get('assetId','synthetic-search')
   if args['name']=='search_assets':return {'structuredContent':{'assets':[{'id':'synthetic-search','ticker':args['arguments']['query'],'name':'Synthetic searched asset','currency':'USD'}]}}
   assert args['name']=='get_asset';raw=copy.deepcopy(case.raw);raw['asset'].update(id=aid,ticker=aid.removeprefix('synthetic-asset-'));raw['price']['assetId']=aid
   if aid.endswith('PEPE'):raw['price'].update(currentPrice='0.0000000123456789',dailyChange='0.0000000000123',dailyChangePercent='0.0996')
   if aid.endswith('MSFT'):raw['price'].update(dailyChange='-0.225',dailyChangePercent='-1.22')
   if aid.endswith('ASML'):raw['price'].update(dailyChange='0',dailyChangePercent='0')
   return {'structuredContent':raw}
 items=[{'id':'portfolios:root','name':'Syntetisk hovedkonto','kind':'portfolio','can_trade':True},{'id':'collections:child','name':'Syntetisk AI Collection','kind':'collection','parent_external_id':'portfolios:root'}]
 now=datetime.now(timezone.utc).isoformat();payload={'source':'Synthetic','observed':now,'kind':'portfolio','value':{'value':{'amount':'1000','currency':'DKK'},'reported_result':{'amount':'25','currency':'DKK'},'source_time':now},'positions':portfolio_data.normalize_positions([{'assetId':'synthetic-btc','name':'Syntetisk BTC-beholdning','ticker':'BTC','quantity':'2','price':'10','currency':'USD','value':'20','unrealisedPnL':'-5','priceAsOf':now}]),'positions_complete':True,'accounts':portfolio_data.normalize_accounts([{'currency':'DKK','balance':'300','buyingPower':'200','asOf':now}]),'pending_orders':[],'orders_complete':True,'complete':True,'errors':[]}
 server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
 try:
  with patch('trade_service.MCP',Client),patch('mcp_client.read_portfolios',return_value=items),patch('portfolio_data.read',return_value=payload),sync_playwright() as p:
   browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox']);page=browser.new_page(viewport={'width':1440,'height':1000});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
   page.goto(f'http://127.0.0.1:{server.server_port}');page.locator('#login-form [name=password]').fill('test-password-long-enough');page.locator('#login-form button').click();page.locator('#refresh-status[data-kind=success]').wait_for();page.locator('nav [data-view=reports]').click();page.locator('.report-full-analysis>summary').click();panel=page.locator('.positions-panel');panel.wait_for();assert panel.locator('.position-row').count()==12;assert panel.locator('.position-portfolio').count()==2
   btc=panel.locator('.position-identity>strong').filter(has_text='BTC');assert btc.count()==2
   tsla=panel.locator('[data-position-key="test-main / test-main.TSLA"]');assert 'DATA MANGLER' in tsla.inner_text();assert 'BEHOLD' not in tsla.inner_text();assert 'FCX' in panel.inner_text()
   root_btc=panel.locator('[data-position-key="test-main / test-main.BTC"]');root_btc.locator('.market-slot').scroll_into_view_if_needed();root_btc.locator('.market-price').wait_for();root_btc.locator('[data-market-expand]').first.click();chart=page.locator('#market-chart-dialog');chart.wait_for(state='visible');assert chart.locator('[data-market-position="test-main.BTC"]').count()==1;assert chart.locator('.market-line').count()==1;page.keyboard.press('Escape')
   # Provider dailyChange without a documented official close stays neutral; new verified-reference colors are tested in browser_design_v1.
   for symbol,expected,arrow in [('BTC','rgb(168, 189, 205)','—'),('MSFT','rgb(168, 189, 205)','—'),('ASML','rgb(168, 189, 205)','—')]:
    row=panel.locator('.position-row').filter(has=page.locator('.position-identity>strong',has_text=symbol)).first
    row.locator('.market-slot').scroll_into_view_if_needed();change=row.locator('.market-change');change.wait_for();assert arrow in change.inner_text(),(symbol,change.inner_text())
    assert change.evaluate('(n)=>getComputedStyle(n).color')==expected,(symbol,change.evaluate('(n)=>getComputedStyle(n).color'))
    change.hover();assert change.evaluate('(n)=>getComputedStyle(n).color')==expected,('hover',symbol)
   panel.locator('[data-position-filter=red]').click();assert panel.locator('.position-row:visible').count()==1;panel.locator('[data-position-filter=all]').click()
   tsla.locator('[data-position-open]').click();dialog=page.locator('#position-dialog');dialog.wait_for(state='visible');assert 'Ingen individuel vurdering' in dialog.inner_text() or 'ingen individuel vurdering' in dialog.inner_text();assert 'ACTIVE_STOP' in dialog.inner_text();assert 'ingen bekræftet fyldning' in dialog.inner_text();assert 'gennemført salg' in dialog.inner_text();page.keyboard.press('Escape')
   child=panel.locator('[data-position-key="test-child / test-child.BTC"]');child.locator('[data-position-open]').click();assert 'REDUCÉR' in dialog.inner_text();assert 'test-child BTC' in dialog.inner_text();dialog.locator('[data-position-history]').click();dialog.get_by_text('Positionshistorik',exact=True).wait_for();assert 'positions-old' in dialog.inner_text();assert 'positions-current' in dialog.inner_text();page.keyboard.press('Escape')
   # Existing Collections retain their actual breakdown and the same clickable totals, now neutral as required; provider P/L remains separate.
   page.locator('nav [data-view=portfolios]').click();page.locator('.collection-spec').first.wait_for();page.locator('.collection-spec>summary').first.click();assert 'Syntetisk BTC-beholdning' in page.locator('.collection-spec').first.inner_text() or 'BTC' in page.locator('.collection-spec').first.inner_text();assert page.locator('.portfolio-value-link.financial-neutral').count()>=1
   page.locator('.collection-spec [data-detail-section=holdings]').first.click();page.locator('.dash-holdings').wait_for();assert page.evaluate('document.activeElement.dataset.portfolioSection')=='holdings'
   page.locator('nav [data-view=reports]').click();page.locator('.report-full-analysis>summary').click();page.locator('.intel-portfolio [data-report-portfolio]').first.wait_for();assert page.locator('.intel-portfolio [data-report-portfolio].market-neutral').count()>=1;page.locator('.intel-portfolio [data-report-portfolio]').first.click();dialog.wait_for(state='visible');assert 'PORTEFØLJESPECIFIKATION' in dialog.inner_text();assert 'BTC' in dialog.inner_text();page.keyboard.press('Escape')
   page.locator('nav [data-view=reports]').click();page.locator('.report-full-analysis>summary').click();panel.wait_for()
   for width in [320,375,390,430,768,1024,1440,1920]:
    page.set_viewport_size({'width':width,'height':1000});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),width
    panel.locator('[data-position-open]').first.click();assert dialog.evaluate('(n)=>n.scrollWidth<=n.clientWidth+1'),('dialog',width);page.keyboard.press('Escape')
    if width in [390,1440]:panel.scroll_into_view_if_needed();page.screenshot(path=f'/tmp/escape-positions-{width}.png',full_page=True)
   # A later full snapshot closes only the identified position; its history stays available.
   closed=copy.deepcopy(data);closed.update(report_id='positions-closed',generated_at='2027-01-04T15:00:00Z');closed['positions'][0].update(quantity='0',position_status='closed');report_ingest.save(app.connect,1,closed)
   page.locator('#refresh-current').click();page.locator('#refresh-status[data-kind=success]').wait_for();page.locator('.report-full-analysis>summary').click();expect(page.locator('.position-row')).to_have_count(11);assert page.locator('[data-position-key="test-main / test-main.TSLA"]').count()==0;assert 'Tidligere positionsposter' in page.locator('.positions-panel').inner_text()
   assert not errors,errors;assert all(c['name'] in ['search_assets','get_asset'] for c in calls);browser.close()
  with app.connect() as c:assert c.execute('SELECT COUNT(*) FROM broker_proposals').fetchone()[0]==0;assert c.execute('SELECT COUNT(*) FROM proposals').fetchone()[0]==0
  print('PASS: 12 holdings in two portfolios, two independent BTC assessments, missing-data fallback, active STOP not a sale, history, dynamic closure, Collections breakdown and neutral clickable totals / separate provider P/L, 320–1920px, no trading')
 finally:server.shutdown();server.server_close();case.tearDown()
if __name__=='__main__':main()
