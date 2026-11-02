"""No-signal read-only preview plus crowded financial layouts; synthetic broker only."""
import copy,sys,threading
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]));sys.path.insert(0,str(Path(__file__).resolve().parent))
import app,asset_quotes,portfolio_data,report_ingest
from test_trade_service import Trading
from playwright.sync_api import sync_playwright

def main():
 case=Trading();case.setUp();now=datetime.now(timezone.utc);stamp=lambda m:(now-timedelta(minutes=m)).isoformat()
 watch=copy.deepcopy(case.report);watch.update(report_id='watch-only-preview',generated_at='2027-01-01T00:00:00Z');watch['candidates'][0]['signal']='OVERVÅG';report_ingest.save(app.connect,1,watch)
 items=[{'id':'portfolios:root','name':'Min hovedportefølje','kind':'portfolio','can_trade':True},{'id':'collections:child','name':'ESCAPE AI Trader · mine beholdninger','kind':'collection','parent_external_id':'portfolios:root'}]
 positions=portfolio_data.normalize_positions([
  {'assetId':'asset-novo','name':'Novo Nordisk A/S','ticker':'NOVOB','quantity':'0.7535795','currency':'DKK','latestPrice':'266.80','costBasis':'200'},
  {'assetId':'asset-asml','name':'ASML Holding NV','ticker':'ASML','quantity':'0.01882311','currency':'EUR','latestPrice':'1421.00','costBasis':'26.71'},
  {'assetId':'asset-eth','name':'Ethereum','ticker':'ETH','quantity':'0.0025','currency':'USD','latestPrice':'2300.123','costBasis':'8.5','priceAsOf':stamp(5)},
  {'assetId':'asset-tiny','name':'Lille kryptoposition med mange decimaler','ticker':'TINY','quantity':'3025474.45','currency':'USD','latestPrice':'0.000005123456','costBasis':'18','priceAsOf':stamp(45)},
  {'name':'Et meget langt instrumentnavn med '+('langtidentifikationsnavn'*4),'ticker':'UNAVAILABLE','quantity':'1','currency':'DKK'}])
 for row in positions:
  row['price_source']='Pluto get_asset · senest kendte pris';row['price_observed']=stamp(0);asset_quotes.calculate(row)
 payload={'source':'Synthetic Pluto','kind':'collection','observed':stamp(0),'value':{'value':{'amount':'1000','currency':'DKK'},'source_time':stamp(0),'reported_result':{'amount':'25.50','currency':'DKK'}},'positions':positions,'positions_complete':True,'pending_orders':[],'accounts':portfolio_data.normalize_accounts([{'currency':'DKK','balance':'300','reservedForOrders':'100','withdrawalPower':'200','buyingPower':'200'},{'currency':'USD','balance':'20.1234','reservedForOrders':'0','buyingPower':'20.1234','asOf':stamp(5)}]),'errors':[],'complete':True,'orders_complete':True}
 server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
 try:
  with patch('trade_service.MCP',case.factory),patch('mcp_client.read_portfolios',return_value=items),patch('portfolio_data.read',return_value=payload),sync_playwright() as p:
   browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox']);page=browser.new_page(viewport={'width':1600,'height':1000});errors=[];page.on('pageerror',lambda e:errors.append(str(e)));url=f'http://127.0.0.1:{server.server_port}'
   page.goto(url);page.locator('#login-form [name=password]').fill('test-password-long-enough');page.locator('#login-form button').click();page.locator('#refresh-status[data-kind=success]').wait_for()
   page.locator('.account-overview-card .account-value').first.wait_for();page.locator('#refresh-status[data-kind=success]').wait_for()
   assert page.locator('.account-overview-card').count()==1;assert page.locator('.collection-children').count()==0
   assert page.locator('.account-result .pnl.positive').count()==1;assert not page.locator('.overview-report-values').evaluate('(n)=>n.open')
   page.locator('.overview-report-values>summary').click();page.locator('#refresh-current').click();page.locator('#refresh-status[data-kind=success]').wait_for();assert page.locator('.overview-report-values').evaluate('(n)=>n.open')
   page.locator('.account-overview-card [data-detail-section=cash]').first.click();page.locator('.cash-panel').wait_for();assert page.evaluate('document.activeElement.dataset.portfolioSection')=='cash';assert 0<=page.locator('.cash-panel').bounding_box()['y']<page.viewport_size['height']-80
   page.locator('nav [data-view=trade]').click();assert page.locator('[data-trade-source]').count()==0;assert page.locator('#preview-form').is_visible()
   page.locator('#preview-query').fill('TEST');page.locator('#preview-search').click();page.locator('#preview-assets option[value=asset-test]').wait_for(state='attached');page.locator('#preview-assets').select_option('asset-test')
   for name,value in {'portfolio_id':str(case.root),'side':'BUY','currency':'DKK','order_type':'MARKET','time_in_force':'DAY'}.items():page.locator(f'#preview-form [name={name}]').select_option(value)
   page.locator('#preview-form [name=size]').fill('1');page.locator('#preview-form button.primary').click();page.locator('#preview-result h3').filter(has_text='Dit testestimat').wait_for();assert not case.writes();assert page.locator('#preview-result #broker-send').count()==0;assert 'kan ikke sendes' in page.locator('#preview-result').inner_text()
   with app.connect() as c:assert c.execute('SELECT COUNT(*) FROM broker_proposals').fetchone()[0]==0
   page.locator('#preview-form [name=size]').fill('2');assert not page.locator('#preview-result').inner_text();assert page.request.post(url+'/api/trade/preview',data={}).status==403
   # Exercise all primary screens, including in-between widths where tables used to break.
   for width in [320,375,390,430,768,1024,1280,1440,1920]:
    page.set_viewport_size({'width':width,'height':1000})
    for target in ['overview','portfolios','radar','trade','journal','reports','settings']:
     page.locator('nav [data-view='+target+']').click();assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),(width,target)
    page.locator('nav [data-view=portfolios]').click();page.locator(f'[data-open-portfolio="{case.child}"]').first.click();page.locator('.holdings-table').wait_for()
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),('detail',width)
    for selector in ['.holdings-table','.cash-table']:
     assert page.locator(selector).evaluate('(t)=>t.scrollWidth<=t.clientWidth+1'),(selector,width)
    assert page.locator('.holdings-table tbody tr').count()==5
    assert page.locator('.holdings-table .freshness-compact').count()==5
    assert page.locator('.holdings-table .pnl').first.bounding_box()['height']<45
    assert '0,000005123' in page.locator('.holdings-table').inner_text()
    assert page.locator('.holdings-table .freshness-stale').count()==1
    assert page.locator('.holdings-table .freshness-unknown').count()==3
    if width>=1440:
     assert page.locator('.holdings-table thead').is_visible();assert page.locator('.holdings-table tbody tr').first.bounding_box()['height']<150
    else:assert page.locator('.holdings-table thead').is_hidden()
    page.locator('.holdings-table .quote-age summary').first.click();assert page.locator('.holdings-table .quote-age-details').first.is_visible();assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),('open-age',width)
    page.locator('.holdings-table .quote-age summary').first.click();page.evaluate('()=>updateFreshness()');assert page.locator('.holdings-table .freshness-compact').count()==5
    if width in [390,1440]:
     page.locator('.holdings-panel').scroll_into_view_if_needed();page.screenshot(path=f'/tmp/escape-holdings-{width}.png',full_page=False)
   assert not errors,errors;browser.close()
  print('PASS: standalone preview without BUY/SELL, no drafts/proposals, CSRF, seven screens and financial detail at 320–1920px, compact source-age controls, long names, exact tiny-price display, open details and desktop row height')
 finally:server.shutdown();server.server_close();case.tearDown()
if __name__=='__main__':main()
