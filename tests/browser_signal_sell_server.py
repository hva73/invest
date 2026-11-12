"""Synthetic exit signal -> browser -> real app server -> synthetic Pluto.
No network calls to a real broker and no production data are used.
"""
import os, sys, threading
from datetime import datetime, timezone
from unittest.mock import patch
sys.path[:0]=[os.getcwd(),os.path.join(os.getcwd(),'tests')]
import app
from test_trade_service import Trading
from playwright.sync_api import sync_playwright, expect

case=Trading();case.setUp();now=datetime.now(timezone.utc).isoformat()
server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
threading.Thread(target=server.serve_forever,daemon=True).start()
session={'watch_id':'synthetic-push','status':'ACTIVE','signal':'SELL','display_status':'SÆLGSSIGNAL','is_test':False,'request':{'ticker':'TEST','asset_id':'asset-test','quote_currency':'USD','provider':'eodhd','strategy_id':'TEST','strategy_version':'1','portfolio_ids':[case.root],'watch_mode':'exit','risk':{'stop_price':'2.95'}},'last_data_at':now,'last_calculation_at':now,'data_stale':False,'data_status':{'price':'3.1','price_status':'FRESH','market_status':'OPEN','identity_verification':'verified'},'latest_currency':'USD','latest_context':{'status':'verified','position':'held','tradability':'unknown','as_of':now,'orders':[]},'latest_calculation':{'reason_codes':['EXIT_RULES','TRAILING_EXIT']},'last_action_signal':{'event_id':'hw-'+'a'*24,'event_type':'SELL_SIGNAL','created':now,'data_timestamp':now,'reason':'Syntetisk exit','state':'ACTIVE','acknowledged_at':None}}
holding={'positions_complete':True,'observed':now,'positions':[{'kind':'holding','asset_id':'asset-test','quantity':'8'}]}
try:
 with patch('hotwatch_engine.item',return_value={'session':session}),patch('portfolio_data.read',return_value=holding),patch('trade_service.MCP',case.factory),sync_playwright() as p:
  browser=p.chromium.launch(headless=True);page=browser.new_page(viewport={'width':390,'height':844},is_mobile=True,has_touch=True)
  page.goto(f'http://127.0.0.1:{server.server_port}');page.locator('#login-form [name=password]').fill('test-password-long-enough');page.locator('#login-form button').click();page.locator('.dashboard-v1').wait_for()
  page.evaluate("""([pid,at]) => {state.connection.connected=true;
   state.portfolios=[{id:pid,name:'Syntetisk depot',source:'pluto',active:true,kind:'portfolio',can_trade:true}];
   state.dashboard.positions=[{key:'synthetic',portfolio_id:pid,portfolio_name:'Syntetisk depot',portfolio_kind:'portfolio',asset_id:'asset-test',ticker:'TEST',name:'Syntetisk aktie',quantity:'8',price:{amount:'3.1',currency:'USD'},value:{amount:'24.8',currency:'USD'},snapshot_at:at,verification:'broker_snapshot',conflicts:[],analysis_freshness:{},hot_watch:{session:{watch_id:'synthetic-push'}}}];} """,[case.root,now])
  page.route('**/api/market/quote',lambda route:route.fulfill(json={'price':'3.1','currency':'USD','ticker':'TEST','asset_id':'asset-test','price_time':now,'fetched_at':now,'series':[]}))
  page.evaluate("window.EngineUI.openNotification('synthetic-push')")
  signal=page.locator('#engine-dialog');expect(signal.get_by_role('button',name='Sælg')).to_be_visible();signal.get_by_role('button',name='Sælg').click()
  quick=page.locator('#quick-trade-dialog');expect(quick).to_contain_text('Sælg · TEST');quick.locator('[name=size]').fill('25');quick.locator('[name=currency]').select_option('DKK')
  assert not case.writes()
  quick.locator('button[type=submit]').click();expect(quick.locator('#quick-trade-review')).to_contain_text('Gennemgå salget');expect(quick.locator('#quick-trade-review')).to_contain_text('2 stk.')
  assert not case.writes()
  quick.locator('#quick-trade-confirm').check();quick.locator('[data-quick-send]').click();expect(quick).to_contain_text('Åbn Pluto')
  assert len(case.writes())==1,case.writes()
  order=case.writes()[0]['arguments']['orders'][0];assert order['side']=='SELL' and order['shares']=='2',order
  browser.close()
 print('PASS: synthetic exit with unknown buy permission -> real app -> synthetic 25% sell proposal; no live broker')
finally:
 server.shutdown();server.server_close();case.tearDown()
