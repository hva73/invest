import json,os,sys,threading
from datetime import datetime,timezone,timedelta
sys.path[:0]=[os.path.dirname(os.path.dirname(os.path.abspath(__file__))),os.path.dirname(os.path.abspath(__file__))]
import app
from test_portfolio_value_chart import PortfolioValueChart
from playwright.sync_api import sync_playwright
case=PortfolioValueChart();case.setUp();now=datetime.now(timezone.utc)
case.save(case.root,'1000',now-timedelta(hours=2),result='-20');case.save(case.root,'1020',now,result='-10')
with app.connect() as c:
 row=c.execute('SELECT payload FROM portfolio_snapshots WHERE portfolio_id=?',(case.root,)).fetchone()
 payload=json.loads(row['payload']);payload.update(errors=[],accounts=[],pending_orders=[],unconfirmed_orders=[])
 c.execute('UPDATE portfolio_snapshots SET payload=? WHERE portfolio_id=?',(json.dumps(payload),case.root))
server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
try:
 with sync_playwright() as p:
  browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox']);page=browser.new_page(viewport={'width':390,'height':844});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
  page.goto(f'http://127.0.0.1:{server.server_port}');page.locator('#login-form [name=password]').fill('test-password-long-enough');page.locator('#login-form button').click();page.locator('nav [data-view=overview]').wait_for()
  targets=page.locator('nav [data-view]').evaluate_all('(x)=>x.map(n=>n.dataset.view)')
  for width in (320,390,768,1440):
   page.set_viewport_size({'width':width,'height':900})
   for target in targets:
    page.locator(f'nav [data-view="{target}"]').click()
    page.wait_for_timeout(150)
    overflow=page.evaluate('({doc:document.documentElement.scrollWidth,win:innerWidth})')
    assert overflow['doc']<=overflow['win']+1, (width,target,overflow)
    notice=page.locator('#notice').inner_text()
    assert 'Cannot read properties' not in notice, (width,target,notice)
  page.locator('nav [data-view="portfolios"]').click()
  page.locator('.portfolio-value-link').first.click()
  page.locator('.portfolio-detail-hero').wait_for()
  page.locator('.portfolio-detail-hero [data-view="portfolios"]').click()
  page.locator('.portfolio-catalog-heading').wait_for()
  assert page.locator('nav [data-view="journal"]').count()==0
  page.locator('nav [data-view="trade"]').click();page.locator('.broker-trade [data-view="journal"]').click();page.locator('.unified-journal').wait_for()
  assert 'active' in (page.locator('nav [data-view="trade"]').get_attribute('class') or '')
  page.locator('.unified-journal [data-view="trade"]').click();page.locator('.broker-trade').wait_for()
  page.evaluate('''() => {
   const rows=[['TAB','-8'],['GEVINST','4'],['UKENDT',null],['LILLE TAB','-1']].map(([ticker,p])=>({ticker,name:ticker,key:ticker,portfolio_name:'Test',portfolio_kind:ticker==='GEVINST'?'collection':'portfolio',unrealized:{amount:p,currency:'DKK'},unrealized_percent:p,value:{amount:'100',currency:'DKK'},conflicts:[],hot_watch:{}}));
   const html=window.DashboardUI.render({dashboard:{positions:rows,totals:[],warnings:[],orders:[],critical_sessions:[],accounts:[]}}),doc=new DOMParser().parseFromString(html,'text/html');
   const order=Array.from(doc.querySelectorAll('.dash-instrument strong'),n=>n.childNodes[0].textContent).join(',');
   if(order!=='GEVINST,LILLE TAB,TAB,UKENDT')throw Error('Incorrect result sorting: '+order);
   if(doc.querySelectorAll('.dash-collection-mark').length!==1||doc.querySelector('.dash-collection-mark').textContent!=='©')throw Error('Collection marker missing');
   const date=formatTime('2026-11-07T20:05:09Z');if(!date.includes('07.11.2026')||!date.includes('21.05.09'))throw Error('Incorrect Danish date/time: '+date);
  }''')
  page.evaluate('''() => {
   const box=document.createElement('div');box.className='si-summary-dialog';box.innerHTML='<div class="sector-detail"><small class="positive">1</small><small class="negative">-1</small></div>';
   document.body.append(box);const colors=Array.from(box.querySelectorAll('small'),x=>getComputedStyle(x).color);
   if(colors[0]!=='rgb(130, 218, 180)'||colors[1]!=='rgb(255, 159, 169)')throw Error('Sector result colors missing: '+colors);
   box.remove();
  }''')
  page.evaluate('''async () => {
   const scope=document.createElement('section');scope.className='desk-radar';
   scope.innerHTML=window.CandidateUI.filters()+'<div class="desk-candidate" data-candidate-active="true" data-candidate-lifecycle="DISCOVERED" data-candidate-position="false" data-attention="green"></div><div class="desk-candidate" data-candidate-active="true" data-candidate-lifecycle="POSITION_OPEN" data-candidate-position="true" data-attention="yellow"></div>';
   document.body.append(scope);const cards=scope.querySelectorAll('.desk-candidate'),toggle=scope.querySelector('[data-candidate-own]');
   window.CandidateUI.applyFilters(scope);if(cards[0].hidden||!cards[1].hidden)throw Error('Default filter failed');
   await window.CandidateUI.click(toggle);if(cards[1].hidden||toggle.getAttribute('aria-pressed')!=='true')throw Error('Own positions toggle failed');
   await window.CandidateUI.click(toggle);if(cards[0].hidden||!cards[1].hidden)throw Error('Hiding own positions failed');
   await window.CandidateUI.click(scope.querySelector('[data-candidate-filter=waiting]'));if(!cards[0].hidden||!cards[1].hidden)throw Error('Waiting filter failed');
   await window.CandidateUI.click(scope.querySelector('[data-candidate-filter=active]'));if(cards[0].hidden||!cards[1].hidden)throw Error('Active filter failed');
   scope.remove();
  }''')
  def sessions_route(route):
   sessions=[] if 'view=history' in route.request.url else [
    {'watch_id':'owned','watch_kind':'holding','request':{'ticker':'EGEN','exchange':'US','provider':'eodhd'},'status':'ACTIVE','signal':'WAIT','data_status':{}},
    {'watch_id':'idea','watch_kind':'candidate','request':{'ticker':'IDÉ','exchange':'US','provider':'eodhd'},'status':'ACTIVE','signal':'WAIT','data_status':{}}]
   route.fulfill(json={'sessions':sessions,'kill_switch':{'killed':False},'worker':None,'discovery_attempts':[]})
  page.route('**/api/v1/hotwatch/sessions?*',sessions_route)
  page.route('**/api/reports/candidate-registry?*',lambda route:route.fulfill(json={'candidates':[]}))
  page.locator('nav [data-view="hot-watch"]').click()
  page.locator('.engine-overview').wait_for()
  assert page.locator('.engine-list-row').count()==1
  assert 'IDÉ' in page.locator('.engine-list-row').inner_text()
  page.locator('[data-engine-own]').click()
  assert page.locator('.engine-list-row').count()==2
  page.locator('[data-engine-own]').click()
  assert page.locator('.engine-list-row').count()==1
  page.route('**/api/portfolios/sync',lambda route:route.fulfill(json={'ok':True}))
  page.route('**/api/portfolios/data',lambda route:route.fulfill(json={'cached':False,'complete':False,'errors':['positions: Beholdningslisten er ufuldstændig']}))
  page.evaluate('state.connection.has_tokens=true')
  page.locator('#refresh-current').click()
  page.locator('#refresh-status[data-kind="warning"]').wait_for()
  assert 'positions: Beholdningslisten er ufuldstændig' in page.locator('#refresh-status').inner_text()
  assert not errors, errors
  print('NAVIGATION',','.join(targets));print('JAVASCRIPT',errors)
  browser.close()
finally:server.shutdown();server.server_close();case.tearDown()
