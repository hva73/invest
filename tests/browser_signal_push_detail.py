"""Synthetic push-to-detail journey; no broker orders or real market data."""
import os,sys,threading,re
from datetime import datetime,timezone,timedelta
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
import app
from test_portfolio_value_chart import PortfolioValueChart
from playwright.sync_api import sync_playwright,expect

def main():
 case=PortfolioValueChart();case.setUp();server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
 now=datetime.now(timezone.utc);stamp=now.isoformat()
 session={'watch_id':'synthetic-push','status':'ACTIVE','signal':'SELL','display_status':'SÆLGSSIGNAL','is_test':False,'request':{'ticker':'TSM','asset_id':'synthetic-asset','quote_currency':'USD','provider':'eodhd','strategy_id':'TEST','strategy_version':'1','portfolio_ids':[case.root],'watch_mode':'exit','risk':{'stop_price':'2.95'}},'last_data_at':stamp,'last_calculation_at':stamp,'data_stale':False,'data_status':{'price':'3.1','price_status':'FRESH','market_status':'OPEN','identity_verification':'verified'},'latest_currency':'USD','latest_context':{'status':'verified','position':'held','tradability':'unknown','as_of':stamp,'orders':[]},'latest_calculation':{'reason_codes':['EXIT_RULES','TRAILING_EXIT']},'last_action_signal':{'event_id':'hw-'+'a'*24,'event_type':'SELL_SIGNAL','created':stamp,'data_timestamp':(now-timedelta(hours=1)).isoformat(),'reason':'Syntetisk exit','state':'ACTIVE','acknowledged_at':None}}
 holding={'key':'synthetic-row','portfolio_id':case.root,'portfolio_name':'Test depot','portfolio_kind':'portfolio','asset_id':'synthetic-asset','ticker':'TSM','name':'Taiwan Semiconductor Manufacturing Company Limited','quantity':'2','price':{'amount':'3.1','currency':'USD'},'value':{'amount':'6.2','currency':'USD'},'average_entry':{'amount':'3.55','currency':'USD'},'unrealized':{'amount':'-6.3','currency':'DKK'},'unrealized_percent':'-12.68','daily':{'amount':'-0.1','percent':'-3','currency':'USD'},'snapshot_at':stamp,'verification':'broker_snapshot','conflicts':[],'analysis_freshness':{},'hot_watch':{'session':{'watch_id':'synthetic-push'}}}
 series=[{'price':str(v),'epoch':(now-timedelta(minutes=120-5*i)).timestamp(),'timestamp':(now-timedelta(minutes=120-5*i)).isoformat(),'date':now.date().isoformat()} for i,v in enumerate([3.4,3.37,3.41,3.38,3.36,3.39,3.34,3.31,3.35,3.32,3.29,3.33,3.30,3.27,3.29,3.25,3.28,3.23,3.26,3.21,3.24,3.18,3.20,3.15,3.1])]
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
   # Same mobile row is reused for sector holdings, with exact depot identity.
   rows=page.evaluate("""(h) => {const old=state.dashboard.positions;
    const first={...h,key:'one',portfolio_id:1},second={...h,key:'two',portfolio_id:2};
    state.dashboard.positions=[first,second];
    const ok=window.DashboardUI.mobilePositionRow(second,true);
    const mismatch=window.DashboardUI.mobilePositionRow({...second,portfolio_id:1},true);
    state.dashboard.positions=[first,{...second,portfolio_id:1},second];
    const duplicate=window.DashboardUI.mobilePositionRow(second,true);
    state.dashboard.positions=old;return {ok,mismatch,duplicate};}""",holding)
   assert 'data-dashboard-member="two"' in rows['ok']
   assert 'disabled' in rows['mismatch'] and 'data-dashboard-member' not in rows['mismatch']
   assert 'disabled' in rows['duplicate'] and 'data-dashboard-member' not in rows['duplicate']

   def market(route):
    periods.append(route.request.post_data_json.get('period'));route.fulfill(json=quote)
   page.route('**/api/market/quote',market)
   page.evaluate("window.EngineUI.openNotification('synthetic-push')")
   d=page.locator('#engine-dialog');expect(d.locator('h2')).to_have_text('TSM');expect(d.locator('h2')).not_to_contain_text('SÆLGSSIGNAL');expect(d).to_contain_text('siden køb');expect(d).to_contain_text('ikke sendt en ordre')
   expect(d).to_contain_text('Data brugt til signalet');expect(d).to_contain_text('Seneste modtagne data');expect(d).to_contain_text('Kursændring i dag');expect(d).to_contain_text('Min position');expect(d.get_by_role('button',name='Sælg')).to_be_visible();expect(d.get_by_role('button',name='Ignorér og luk signalet')).to_be_visible();expect(d.locator('[data-asset-trade=BUY]')).to_have_count(0)
   expect(d.locator('.signal-action-bar .signal-help')).to_have_count(0)
   ignored=[];page.on('request',lambda r:ignored.append(r.url) if '/ack-signal' in r.url else None)
   d.get_by_role('button',name='Ignorér og luk signalet').click();expect(d).not_to_be_visible();assert not orders and not ignored
   page.evaluate("window.EngineUI.openNotification('synthetic-push')");expect(d).to_be_visible()
   assert page.evaluate("getComputedStyle(document.documentElement).overflowY")=='hidden'
   background=page.evaluate('window.scrollY');page.mouse.move(2,2);page.mouse.wheel(0,900);page.wait_for_timeout(150);assert page.evaluate('window.scrollY')==background
   shot=os.environ.get('ESCAPE_SCREENSHOTS');
   expect(d.locator('.market-slot .market-price')).to_be_visible()
   expect(d.locator('.market-about')).not_to_be_visible();expect(d.locator('[data-market-refresh]')).to_be_visible()
   if shot:
    page.wait_for_timeout(600)
    import json
    diag=page.evaluate("""() => Object.fromEntries(['.market-plot-canvas','.market-peak-label','.market-entry-label'].map(s=>{let e=document.querySelector(s),r=e.getBoundingClientRect(),c=getComputedStyle(e);return [s,{x:r.x,y:r.y,width:r.width,height:r.height,position:c.position,top:c.top,left:c.left,transform:c.transform}]}))""")
    Path(f'{shot}/diagnostic.json').write_text(json.dumps(diag))
    page.screenshot(path=f'{shot}/signal-sell-390.png')
    d.evaluate('(e)=>e.scrollTop=650');page.screenshot(path=f'{shot}/signal-sell-details.png');d.evaluate('(e)=>e.scrollTop=0')
   page.evaluate('state.dashboard.positions=[]')
   d.get_by_role('button',name='Sælg').click()
   quick=page.locator('#quick-trade-dialog');expect(quick).to_contain_text('Sælg · TSM');expect(quick.locator('[name=portfolio_id]')).to_have_value(str(case.root));expect(quick.locator('[name=asset_id]')).to_have_value('synthetic-asset')
   quick.locator('[data-quick-close]').click();page.evaluate("window.EngineUI.openNotification('synthetic-push')");expect(d).to_be_visible()
   slot=d.locator('.market-slot');expect(slot.locator('.market-price')).to_be_visible();expect(slot.locator('[data-market-period=day]')).to_have_attribute('aria-pressed','true')
   expect(slot.locator('.signal-chart-peak')).to_contain_text('højeste viste punkt');expect(slot.locator('.market-marker-entry')).to_have_count(1);expect(slot.locator('.market-marker-signal')).to_have_count(0);assert 5<=float(slot.locator('.market-marker-entry').get_attribute('y1'))<=57;expect(slot.locator('.market-entry-label')).to_have_text('Gns. købskurs 3,55 USD');expect(slot.locator('.market-peak-label')).to_have_text('Top 3,41 USD')
   canvas=slot.locator('.market-plot-canvas').bounding_box()
   peak=slot.locator('.market-peak-label').bounding_box()
   entry=slot.locator('.market-entry-label').bounding_box()
   line=slot.locator('.market-marker-entry').bounding_box()
   assert canvas and peak and entry and line
   assert peak['x']>=canvas['x'] and peak['x']+peak['width']<=canvas['x']+canvas['width'], (peak,canvas)
   assert peak['y']>canvas['y'] and peak['y']+peak['height']<canvas['y']+canvas['height']-10, (peak,canvas)
   assert abs(entry['y']+entry['height']-line['y'])<10, (entry,line)
   expect(slot.locator('.market-about')).not_to_be_visible()
   expect(slot.locator('[data-market-refresh]')).to_be_visible()
   graph=slot.locator('.market-plot-canvas svg');box=graph.bounding_box()
   page.touchscreen.tap(box['x']+box['width']*.5,box['y']+box['height']*.5)
   expect(slot.locator('.market-hover')).to_be_visible()
   plot=slot.locator('[data-market-plot]');plot.focus();page.keyboard.press('ArrowLeft')
   expect(plot.locator('.market-hover')).to_be_visible();expect(plot.locator('.market-hover small')).to_have_text(re.compile(r'^\d{2}\.\d{2}$'))
   expect(plot.locator('.market-hover strong')).to_contain_text('USD')
   if shot:page.screenshot(path=f'{shot}/signal-hover-390.png')
   for name in ['week','month','year','day']:
    slot.locator('[data-market-period='+name+']').click();expect(slot.locator('[data-market-period='+name+']')).to_have_attribute('aria-pressed','true');page.wait_for_timeout(300);plot=slot.locator('[data-market-plot]');plot.focus();page.keyboard.press('ArrowLeft');expect(plot.locator('.market-hover small')).to_have_text(re.compile(r'^\d{2}\.\d{2}$' if name=='day' else r'^\d{2}\.\d{2}\.\d{2}$'))
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
   d.locator('[data-engine-close]').first.click();page.evaluate("window.EngineUI.openNotification('synthetic-push')");expect(d.locator('h2')).to_have_text('TSM');d.get_by_text('Tekniske detaljer og overvågning').click()
   d.locator('[data-engine-ack=synthetic-push]').click();expect(d).not_to_be_visible()
   assert acknowledgements==[{'event_id':'hw-'+'a'*24,'is_test':False}],acknowledgements
   session.update(status='DEGRADED',signal='NO_DATA',display_status='DATA FOR GAMLE',data_stale=True,latest_context={})
   session['data_status']={'price':None,'price_status':'STALE','market_status':'UNKNOWN'}
   page.evaluate("window.EngineUI.openNotification('synthetic-push')")
   expect(d).to_contain_text('ikke længere aktivt');expect(d.locator('[data-trade-watch]')).to_have_count(0);expect(d.get_by_role('button',name='Åbn depot for manuelt salg →')).to_be_visible()
   d.locator('[data-engine-close]').first.click();expect(d).not_to_be_visible();assert page.evaluate("getComputedStyle(document.documentElement).overflowY")!='hidden'
   session.update(status='ACTIVE',signal='SELL',display_status='SÆLGSSIGNAL',data_stale=False,latest_context={'status':'verified','position':'held','tradability':'available','as_of':stamp,'orders':[]});session['data_status']={'price':'3.1','price_status':'FRESH','market_status':'UNKNOWN','identity_verification':'verified'}
   page.evaluate("window.EngineUI.openNotification('synthetic-push')");expect(d).to_contain_text('Handelstid er lukket eller ikke bekræftet');expect(d.locator('[data-trade-watch]')).to_have_count(0);expect(d.get_by_role('button',name='Åbn depot for manuelt salg →')).to_be_visible();d.locator('[data-engine-close]').first.click()
   session['data_status']['market_status']='OPEN'
   for scope in ([],[case.root,999]):
    session['request']['portfolio_ids']=scope;page.evaluate("window.EngineUI.openNotification('synthetic-push')");expect(d.locator('[data-trade-watch]')).to_have_count(0);expect(d).to_contain_text('Signalet er ikke knyttet til ét entydigt depot');expect(d.get_by_role('button',name='Vælg depot for manuelt salg →')).to_be_visible();d.locator('[data-engine-close]').first.click()
   session['request']['portfolio_ids']=[case.root]
   holding['portfolio_kind']='collection';account['portfolios'][0]['kind']='collection';session['data_status']['market_status']='OPEN'
   page.evaluate("window.EngineUI.openNotification('synthetic-push')");expect(d).to_contain_text('Aktien er i en Collection og kan ikke sælges enkeltvis her');expect(d.get_by_role('button',name='Vælg depot for manuelt salg →')).to_be_visible();expect(d.locator('[data-trade-watch]')).to_have_count(0);d.locator('[data-engine-close]').first.click()
   holding['portfolio_kind']='portfolio';account['portfolios'][0]['kind']='portfolio'
   session['latest_context']['tradability']='available';session.update(signal='BUY',display_status='KØBSSIGNAL');session['last_action_signal'].update(state='ACTIVE',event_type='BUY_SIGNAL');page.evaluate("window.EngineUI.openNotification('synthetic-push')");expect(d).to_contain_text('muligt køb');expect(d.get_by_role('button',name='Ignorér og luk signalet')).to_be_visible();expect(d.locator('[data-trade-watch]')).to_have_count(0)
   d.locator('[data-engine-close]').first.click()
   session['data_status']['market_status']='OPEN';session['buy_plan']={'fresh':True,'portfolio_id':case.root,'quantity':'2','budget_dkk':'500','limit_price':'20','stop_price':'18'}
   page.evaluate("window.EngineUI.openNotification('synthetic-push')");expect(d.get_by_role('button',name='Køb')).to_be_visible();expect(d.locator('[data-trade-watch]')).to_have_attribute('data-trade-signal','BUY');expect(d.locator('.market-slot .market-price')).to_be_visible()
   d.get_by_role('button',name='Køb').click();expect(quick).to_contain_text('Køb · TSM');expect(quick.locator('[name=portfolio_id]')).to_have_value(str(case.root));expect(quick.locator('[name=asset_id]')).to_have_value('synthetic-asset');quick.locator('[data-quick-close]').click()
   account['dashboard']['positions']=[];session['latest_context']['position']='none';session['request']['report_id']='synthetic-report';session['request']['candidate_id']='synthetic-candidate'
   page.evaluate("window.EngineUI.openNotification('synthetic-push')");expect(d.locator('.market-slot .market-price')).to_be_visible();expect(d.locator('.market-marker-entry')).to_have_count(0);expect(d.locator('.market-entry-label')).to_have_count(0);expect(d.locator('.market-marker-signal')).to_have_count(0);expect(d.locator('.market-peak-label')).to_have_text('Top 3,41 USD');expect(d.get_by_role('button',name='Køb')).to_be_visible()
   if shot:
    page.screenshot(path=f'{shot}/signal-buy-390.png')
    d.evaluate('(e)=>e.scrollTop=650');page.screenshot(path=f'{shot}/signal-buy-details.png');d.evaluate('(e)=>e.scrollTop=0')
   d.get_by_role('button',name='Ignorér og luk signalet').click();expect(d).not_to_be_visible()
   account['dashboard']['positions']=[holding];session['latest_context']['position']='held';session['request'].pop('report_id');session['request'].pop('candidate_id')
   session.update(status='DEGRADED',signal='NO_DATA',display_status='DATA FOR GAMLE',data_stale=True);session['last_action_signal'].update(event_type='SELL_SIGNAL',state='DATA_MISSING');page.evaluate("window.EngineUI.openNotification('synthetic-push')");d.get_by_role('button',name='Åbn depot for manuelt salg →').click();page.wait_for_function("() => view==='portfolio-detail'");assert page.evaluate('selectedPortfolio')==case.root;assert page.evaluate("state.dashboard.positions[0].asset_id")=='synthetic-asset'
   assert not errors,errors;assert not orders,orders
   # Landscape phone: sticky action remains reachable while scrolling.
   page.set_viewport_size({'width':667,'height':375})
   session.update(status='ACTIVE',signal='SELL',display_status='SÆLGSSIGNAL',data_stale=False,latest_context={'status':'verified','position':'held','tradability':'unknown','as_of':stamp,'orders':[]})
   session['last_action_signal'].update(state='ACTIVE',event_type='SELL_SIGNAL')
   session['data_status']={'price':'3.1','price_status':'FRESH','market_status':'OPEN','identity_verification':'verified'}
   page.evaluate("window.EngineUI.openNotification('synthetic-push')")
   expect(d.get_by_role('button',name='Sælg')).to_be_visible()
   for offset in (0,300,800):
    d.evaluate('(e,y)=>e.scrollTop=y',offset);rect=d.locator('.signal-action-bar').bounding_box()
    assert rect and rect['y']>=0 and rect['y']+rect['height']<=376,rect
   assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
   d.locator('[data-engine-close]').first.click()
   desktop=browser.new_page(viewport={'width':1280,'height':800});desktop.on('request',lambda r:orders.append(r.url) if '/api/trade/' in r.url else None)
   desktop.goto(f'http://127.0.0.1:{server.server_port}');desktop.locator('#login-form [name=password]').fill('test-password-long-enough');desktop.locator('#login-form button').click();desktop.locator('.dashboard-v1').wait_for()
   session.update(status='ACTIVE',signal='SELL',display_status='SÆLGSSIGNAL',data_stale=False,latest_context={'status':'verified','position':'held','tradability':'available','as_of':stamp,'orders':[]});session['last_action_signal'].update(state='ACTIVE',event_type='SELL_SIGNAL');session['data_status']={'price':'3.1','price_status':'FRESH','market_status':'OPEN','identity_verification':'verified'}
   desktop.route('**/api/v1/hotwatch/sessions/synthetic-push?is_test=false',lambda route:route.fulfill(json={'session':session}));desktop.route('**/api/state',lambda route:route.fulfill(json=account))
   desktop.evaluate("window.EngineUI.openNotification('synthetic-push')");signal=desktop.locator('#engine-dialog');signal.get_by_role('button',name='Sælg').click();form=desktop.locator('#quick-trade-dialog');expect(form).to_contain_text('Sælg · TSM');expect(form.locator('[name=portfolio_id]')).to_have_value(str(case.root));form.locator('[data-quick-close]').click()
   session.update(signal='BUY',display_status='KØBSSIGNAL');session['last_action_signal'].update(state='ACTIVE',event_type='BUY_SIGNAL');session['buy_plan']={'fresh':True,'portfolio_id':case.root,'quantity':'2','budget_dkk':'500','limit_price':'20','stop_price':'18'}
   desktop.evaluate("window.EngineUI.openNotification('synthetic-push')");signal.get_by_role('button',name='Køb').click();expect(form).to_contain_text('Køb · TSM');expect(form.locator('[name=portfolio_id]')).to_have_value(str(case.root));form.locator('[data-quick-close]').click()
   session.update(status='DEGRADED',signal='NO_DATA',display_status='DATA FOR GAMLE',data_stale=True);session['last_action_signal'].update(state='DATA_MISSING',event_type='SELL_SIGNAL');desktop.evaluate("window.EngineUI.openNotification('synthetic-push')");signal.get_by_role('button',name='Åbn depot for manuelt salg →').click();desktop.wait_for_function("() => view==='portfolio-detail'");assert desktop.evaluate('selectedPortfolio')==case.root
   assert not orders,orders;desktop.close();browser.close()
  print('PASS: synthetic push → mobile detail, four periods, Pluto identity, real-point high, sticky actions and no order')
 finally:server.shutdown();server.server_close();case.tearDown()
if __name__=='__main__':main()

