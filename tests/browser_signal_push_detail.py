"""Synthetic push-to-detail journey; no broker orders or real market data."""
import os,sys,threading
from datetime import datetime,timezone,timedelta
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
import app
from test_portfolio_value_chart import PortfolioValueChart
from playwright.sync_api import sync_playwright,expect

def main():
 case=PortfolioValueChart();case.setUp();server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
 now=datetime.now(timezone.utc);stamp=now.isoformat()
 session={'watch_id':'synthetic-push','status':'ACTIVE','signal':'SELL','display_status':'SÆLGSSIGNAL','is_test':False,'request':{'ticker':'TSM','asset_id':'synthetic-asset','quote_currency':'USD','provider':'eodhd','strategy_id':'TEST','strategy_version':'1','portfolio_ids':[case.root],'risk':{'stop_price':'2.5'}},'last_data_at':stamp,'last_calculation_at':stamp,'data_stale':False,'data_status':{'price':'3.1','price_status':'FRESH','market_status':'OPEN','identity_verification':'verified'},'latest_currency':'USD','latest_context':{'status':'verified','position':'held','tradability':'available','as_of':stamp,'orders':[]},'latest_calculation':{'reason_codes':['EXIT_RULES','TRAILING_EXIT']},'last_action_signal':{'event_id':'hw-'+'a'*24,'event_type':'SELL_SIGNAL','created':stamp,'data_timestamp':(now-timedelta(hours=1)).isoformat(),'reason':'Syntetisk exit','state':'ACTIVE','acknowledged_at':None}}
 holding={'key':'synthetic-row','portfolio_id':case.root,'portfolio_name':'Test depot','portfolio_kind':'portfolio','asset_id':'synthetic-asset','ticker':'TSM','name':'Taiwan Semiconductor Manufacturing Company Limited','quantity':'2','price':{'amount':'3.1','currency':'USD'},'value':{'amount':'6.2','currency':'USD'},'average_entry':{'amount':'3.25','currency':'USD'},'unrealized':{'amount':'-12','currency':'DKK'},'unrealized_percent':'-5','daily':{'amount':'-0.1','percent':'-3','currency':'USD'},'snapshot_at':stamp,'verification':'broker_snapshot','conflicts':[],'analysis_freshness':{},'hot_watch':{'session':{'watch_id':'synthetic-push'}}}
 series=[{'price':str(v),'epoch':(now-timedelta(hours=2-i)).timestamp(),'timestamp':(now-timedelta(hours=2-i)).isoformat(),'date':now.date().isoformat()} for i,v in enumerate([3.4,3.2,3.1])]
 quote={'price':'3.1','currency':'USD','ticker':'TSM','exchange':'NASDAQ','name':'Taiwan Semiconductor Manufacturing Company Limited','asset_id':'synthetic-asset','asset_type':'CS','price_time':stamp,'fetched_at':stamp,'daily_change_percent':'-3','daily_change':'-0.1','daily_note':None,'series':series,'week_change_percent':'-4'}
 try:
  with sync_playwright() as pw:
   browser=pw.chromium.launch(**({} if os.environ.get('ESCAPE_PLAYWRIGHT_MANAGED') else {'executable_path':'/usr/bin/chromium'}),headless=True,args=['--no-sandbox']);page=browser.new_page(viewport={'width':390,'height':700},is_mobile=True,has_touch=True);errors=[];orders=[];periods=[]
   page.on('pageerror',lambda e:errors.append(str(e)));page.on('request',lambda r:orders.append(r.url) if '/api/trade/' in r.url else None)
   page.goto(f'http://127.0.0.1:{server.server_port}');page.locator('#login-form [name=password]').fill('test-password-long-enough');page.locator('#login-form button').click();page.locator('.dashboard-v1').wait_for()
   page.evaluate('state.connection.connected=true')
   page.route('**/api/v1/hotwatch/sessions/synthetic-push?is_test=false',lambda route:route.fulfill(json={'session':session}))
   account=page.evaluate('structuredClone(state)');account['dashboard']['positions']=[holding];account['portfolios']=[{'id':case.root,'name':'Test depot','source':'pluto','active':True,'kind':'portfolio','can_trade':True}]
   page.route('**/api/state',lambda route:route.fulfill(json=account))
   def market(route):
    periods.append(route.request.post_data_json.get('period'));route.fulfill(json=quote)
   page.route('**/api/market/quote',market)
   page.evaluate("window.EngineUI.openNotification('synthetic-push')")
   d=page.locator('#engine-dialog');expect(d).to_contain_text('SÆLGSSIGNAL');expect(d.locator('h2')).to_contain_text('TSM · SÆLGSSIGNAL');expect(d).to_contain_text('siden køb');expect(d).to_contain_text('ikke sendt en ordre')
   expect(d).to_contain_text('Data brugt til signalet');expect(d).to_contain_text('Seneste modtagne data');expect(d).to_contain_text('Kursændring i dag');expect(d).to_contain_text('Min position');expect(d.get_by_role('button',name='Gennemgå salg →')).to_be_visible();expect(d.get_by_role('button',name='Behold foreløbig')).to_be_visible();expect(d.locator('[data-asset-trade=BUY]')).to_have_count(0)
   expect(d.locator('.signal-action-bar .signal-help')).to_have_count(0)
   assert page.evaluate("getComputedStyle(document.documentElement).overflowY")=='hidden'
   background=page.evaluate('window.scrollY');page.mouse.move(2,2);page.mouse.wheel(0,900);page.wait_for_timeout(150);assert page.evaluate('window.scrollY')==background
   shot=os.environ.get('ESCAPE_SCREENSHOTS');
   if shot:page.screenshot(path=f'{shot}/signal-sell-390.png')
   page.evaluate('state.dashboard.positions=[]')
   d.get_by_role('button',name='Gennemgå salg →').click()
   quick=page.locator('#quick-trade-dialog');expect(quick).to_contain_text('Sælg · TSM');expect(quick.locator('[name=portfolio_id]')).to_have_value(str(case.root));expect(quick.locator('[name=asset_id]')).to_have_value('synthetic-asset')
   quick.locator('[data-quick-close]').click();page.evaluate("window.EngineUI.openNotification('synthetic-push')");expect(d).to_be_visible()
   d.get_by_text('Se begrundelse og kursgraf').click()
   slot=d.locator('.market-slot');expect(slot.locator('.market-price')).to_be_visible();expect(slot.locator('[data-market-period=day]')).to_have_attribute('aria-pressed','true')
   expect(slot.locator('.signal-chart-peak')).to_contain_text('højeste viste punkt');expect(slot.locator('.market-marker-entry')).to_have_count(1);expect(slot.locator('.market-marker-signal')).to_have_count(1);expect(slot.locator('.market-marker-legend')).to_contain_text('Analytisk stop 2.5 USD · uden for skala')
   for name in ['week','month','year','day']:
    slot.locator('[data-market-period='+name+']').click();expect(slot.locator('[data-market-period='+name+']')).to_have_attribute('aria-pressed','true');page.wait_for_timeout(300)
   assert 'ONE_MONTH' in periods and 'ONE_YEAR' in periods,periods
   for offset in (0,300,700,1200):
    d.evaluate('(e,y)=>e.scrollTop=y',offset);box=d.locator('.signal-action-bar').bounding_box();viewport=page.viewport_size;assert box and box['y']>=0 and box['y']+box['height']<=viewport['height']+1,(offset,box)
   assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
   page.screenshot(path='/tmp/escape-signal-push-detail.png')
   acknowledgements=[]
   def ack(route):
    acknowledgements.append(route.request.post_data_json);route.fulfill(json={'ok':True})
   page.route('**/api/v1/hotwatch/sessions/synthetic-push/ack-signal',ack)
   d.get_by_text('Tekniske detaljer og overvågning').click()
   page.route('**/api/v1/hotwatch/sessions/synthetic-push/events*',lambda route:route.fulfill(json={'items':[]}))
   page.route('**/api/v1/hotwatch/sessions/synthetic-push/samples*',lambda route:route.fulfill(json={'items':[]}))
   d.get_by_role('button',name='Se motorforløb og overvågningsstyring').click();expect(d).to_contain_text('motorforløb');expect(d.locator('[data-asset-trade=BUY]')).to_have_count(0);expect(d.locator('[data-trade-watch]')).to_have_count(0)
   d.locator('[data-engine-close]').first.click();page.evaluate("window.EngineUI.openNotification('synthetic-push')");expect(d).to_contain_text('SÆLGSSIGNAL');d.get_by_text('Tekniske detaljer og overvågning').click()
   d.locator('[data-engine-ack=synthetic-push]').click();expect(d).not_to_be_visible()
   assert acknowledgements==[{'event_id':'hw-'+'a'*24,'is_test':False}],acknowledgements
   session.update(status='DEGRADED',signal='NO_DATA',display_status='DATA FOR GAMLE',data_stale=True,latest_context={})
   session['data_status']={'price':None,'price_status':'STALE','market_status':'UNKNOWN'}
   page.evaluate("window.EngineUI.openNotification('synthetic-push')")
   expect(d).to_contain_text('ikke længere aktivt');expect(d.locator('[data-trade-watch]')).to_have_count(0);expect(d.get_by_role('button',name='Åbn depot for manuelt salg →')).to_be_visible()
   d.locator('[data-engine-close]').first.click();expect(d).not_to_be_visible();assert page.evaluate("getComputedStyle(document.documentElement).overflowY")!='hidden'
   session.update(status='ACTIVE',signal='SELL',display_status='SÆLGSSIGNAL',data_stale=False,latest_context={'status':'verified','position':'held','tradability':'available','as_of':stamp,'orders':[]});session['data_status']={'price':'3.1','price_status':'FRESH','market_status':'UNKNOWN','identity_verification':'verified'}
   page.evaluate("window.EngineUI.openNotification('synthetic-push')");expect(d).to_contain_text('Handelstid er lukket eller ikke bekræftet');expect(d.locator('[data-trade-watch]')).to_have_count(0);expect(d.get_by_role('button',name='Åbn depot for manuelt salg →')).to_be_visible();d.locator('[data-engine-close]').first.click()
   session.update(signal='BUY',display_status='KØBSSIGNAL');session['last_action_signal'].update(state='ACTIVE',event_type='BUY_SIGNAL');page.evaluate("window.EngineUI.openNotification('synthetic-push')");expect(d).to_contain_text('muligt køb');expect(d.get_by_role('button',name='Afvent')).to_be_visible();expect(d.locator('[data-trade-watch]')).to_have_count(0)
   if shot:page.screenshot(path=f'{shot}/signal-buy-390.png')
   d.locator('[data-engine-close]').first.click()
   session['data_status']['market_status']='OPEN';session['buy_plan']={'fresh':True,'portfolio_id':case.root,'quantity':'2','budget_dkk':'500','limit_price':'20','stop_price':'18'}
   page.evaluate("window.EngineUI.openNotification('synthetic-push')");expect(d.get_by_role('button',name='Gennemgå køb →')).to_be_visible();expect(d.locator('[data-trade-watch]')).to_have_attribute('data-trade-signal','BUY');d.get_by_role('button',name='Gennemgå køb →').click();expect(quick).to_contain_text('Køb · TSM');expect(quick.locator('[name=portfolio_id]')).to_have_value(str(case.root));expect(quick.locator('[name=asset_id]')).to_have_value('synthetic-asset');quick.locator('[data-quick-close]').click()
   session.update(status='DEGRADED',signal='NO_DATA',display_status='DATA FOR GAMLE',data_stale=True);session['last_action_signal'].update(event_type='SELL_SIGNAL',state='DATA_MISSING');page.evaluate("window.EngineUI.openNotification('synthetic-push')");d.get_by_role('button',name='Åbn depot for manuelt salg →').click();page.wait_for_function("view==='portfolio-detail'");assert page.evaluate('selectedPortfolio')==case.root
   assert not errors,errors;assert not orders,orders
   browser.close()
  print('PASS: synthetic push → mobile detail, four periods, Pluto identity, real-point high, sticky actions and no order')
 finally:server.shutdown();server.server_close();case.tearDown()
if __name__=='__main__':main()

