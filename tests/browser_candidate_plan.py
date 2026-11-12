"""Reach an existing buy plan from a synthetic monitored candidate; no broker calls."""
import sys, threading
from pathlib import Path
from unittest.mock import patch
sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
import app
from playwright.sync_api import sync_playwright, expect
from test_portfolio_value_chart import PortfolioValueChart

case = PortfolioValueChart(); case.setUp()
server = app.ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
try:
 with patch('mcp_client.MCP.request', side_effect=AssertionError('No broker calls')), sync_playwright() as pw:
  browser = pw.chromium.launch(headless=True)
  for width in (320, 390, 1280):
   page = browser.new_page(viewport={'width': width, 'height': 844})
   writes = []
   session = {'watch_id':'synthetic-entry', 'watch_kind':'candidate', 'is_test':False, 'status':'ACTIVE', 'signal':'WAIT', 'display_status':'AFVENT', 'data_stale':False, 'request':{'ticker':'TEST', 'exchange':'TEST', 'provider':'synthetic', 'quote_currency':'USD', 'watch_mode':'entry', 'portfolio_ids':[], 'risk':{}}, 'data_status':{'market_status':'OPEN','price_status':'FRESH'}, 'latest_calculation':{'signal':'WAIT','reason_codes':['RISK_INPUTS_UNKNOWN'],'supporting_metrics':{}}, 'buy_plan':None}
   def hotwatch(route):
    url=route.request.url
    if route.request.method != 'GET': writes.append(url)
    if '/samples?' in url: payload={'items':[]}
    elif '/events?' in url: payload={'items':[]}
    elif '/sessions/synthetic-entry?' in url: payload={'session':session}
    elif 'view=history' in url: payload={'sessions':[]}
    else: payload={'sessions':[session], 'kill_switch':{'killed':False}, 'worker':None, 'discovery_attempts':[], 'truncated':False}
    route.fulfill(json=payload)
   page.route('**/api/v1/hotwatch/sessions**', hotwatch)
   page.goto(f'http://127.0.0.1:{server.server_port}/')
   page.locator('#login-form [name=password]').fill('test-password-long-enough');page.locator('#login-form button').click()
   expect(page.locator('.dashboard-v1')).to_be_visible()
   page.locator('nav [data-view=hot-watch]').click()
   row=page.locator('.engine-list-row').filter(has_text='TEST');expect(row).to_be_visible()
   expect(row).to_contain_text('AFVENT');expect(row).not_to_contain_text('KØBSSIGNAL')
   row.get_by_role('button',name='Købsplan mangler · klargør →').click()
   dialog=page.locator('#engine-dialog');expect(dialog).to_be_visible()
   expect(dialog.locator('#engine-buy-plan')).to_be_visible()
   expect(dialog).to_contain_text('Planen opretter ingen ordre')
   expect(dialog).to_contain_text('Et købssignal kræver også friske markedsdata og alle risikokontroller')
   assert not writes, writes
   page.close()
  browser.close()
 print('PASS: candidate WAIT opens existing plan without a signal or broker write')
finally:
 server.shutdown();server.server_close();case.tearDown()
