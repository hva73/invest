"""Real dashboard with disposable synthetic positions; no network to brokers."""
import os,sys,threading
from pathlib import Path
from unittest.mock import patch
sys.path[:0]=['.','tests']
import app
from test_portfolio_value_chart import PortfolioValueChart
from playwright.sync_api import sync_playwright,expect
case=PortfolioValueChart();case.setUp();server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
try:
 with patch('mcp_client.MCP.request',side_effect=AssertionError('Live broker calls disabled')),sync_playwright() as pw:
  browser=pw.chromium.launch(headless=True)
  for width in (320,375,390,430,1280):
   page=browser.new_page(viewport={'width':width,'height':844},is_mobile=width<700,has_touch=width<700)
   page.goto(f'http://127.0.0.1:{server.server_port}/');page.locator('#login-form [name=password]').fill('test-password-long-enough');page.locator('#login-form button').click();expect(page.locator('.dashboard-v1')).to_be_visible()
   page.evaluate('''() => {const money=n=>({amount:String(n),currency:'DKK'});state.dashboard.positions=Array.from({length:18},(_,i)=>({key:'mock-'+i,ticker:'TEST'+i,name:'Syntetisk selskab med meget langt navn '+i,portfolio_name:'Test depot',portfolio_kind:'portfolio',portfolio_id:1,asset_id:'asset-'+i,quantity:'2',price:money(100+i),value:money(200+i*2),cost_basis:money(190),unrealized:money(10+i*2),unrealized_percent:'5',unrealized_estimated:false,verification:'broker_snapshot',critical:i===0,conflicts:[],raw:{},missing:{},hot_watch:{session:i===0?{watch_id:'watch-0',status:'ACTIVE',signal:'SELL',display_status:'SÆLGSSIGNAL',data_stale:false,display_freshness:{state:'fresh'},data_status:{market_status:'OPEN',price_status:'FRESH'},last_action_signal:{state:'ACTIVE',event_type:'SELL_SIGNAL'}}:i===1?{watch_id:'watch-1',status:'ACTIVE',signal:'WAIT',display_status:'AFVENT',data_status:{market_status:'CLOSED'}}:null}}));state.dashboard.overview_positions=state.dashboard.positions;render()}''')
   if width<=700:
    section=page.locator('.mobile-holdings');expect(section).to_be_visible();expect(section.locator('.mobile-holding')).to_have_count(6)
    expect(section.locator('.mobile-holding').first).to_contain_text('SÆLGSSIGNAL');expect(page.locator('#dashboard-value-chart')).to_be_visible();expect(page.locator('#dashboard-value-chart')).to_contain_text('Afventer flere registrerede resultater');expect(page.locator('.dash-signals')).to_be_hidden();expect(page.locator('.dash-quality')).to_be_hidden()
    section.locator('.mobile-holding').first.click();signal_detail=page.locator('#dashboard-detail');expect(signal_detail).to_be_visible();expect(signal_detail.locator('.position-actions-mobile [data-asset-trade=BUY]')).to_be_visible();expect(signal_detail.locator('.position-actions-mobile [data-asset-trade=SELL]')).to_be_visible();expect(signal_detail.locator('.position-details-desktop')).to_be_hidden();expect(signal_detail.locator('.position-mobile-summary [data-dashboard-decision=watch-0]')).to_be_visible();expect(signal_detail.locator('.position-mobile-summary')).not_to_contain_text('broker_snapshot');expect(signal_detail.locator('.position-mobile-summary')).not_to_contain_text('candidate_id')
    for side,label in [('BUY','Køb'),('SELL','Sælg')]:
     signal_detail.locator(f'.position-actions-mobile [data-asset-trade={side}]').click();quick=page.locator('#quick-trade-dialog');expect(quick).to_contain_text(label+' · TEST0');quick.locator('[data-quick-close]').click();expect(signal_detail).to_be_visible()
    page.evaluate('() => {window.oldDecision=window.EngineUI.openNotification; window.EngineUI.openNotification=async id=>{window.selectedDecision=id}}') ;signal_detail.locator('.position-mobile-summary [data-dashboard-decision=watch-0]').click();expect(signal_detail).to_be_hidden();assert page.evaluate('window.selectedDecision')=='watch-0';page.evaluate('() => {window.EngineUI.openNotification=window.oldDecision}')
    section.get_by_role('button',name='Kræver handling').click();expect(section.locator('.mobile-holding')).to_have_count(1)
    section.get_by_role('button',name='Marked lukket').click();expect(section.locator('.mobile-holding')).to_have_count(1)
    section.get_by_role('button',name='Alle',exact=True).click();section.get_by_role('button',name='Se alle 18 beholdninger').click();expect(section.locator('.mobile-holding')).to_have_count(18)
    last=section.locator('.mobile-holding').last;last.scroll_into_view_if_needed();box=last.bounding_box();nav=page.locator('body > aside nav').bounding_box();assert box['y']+box['height']<=nav['y'] or box['y']>=nav['y']+nav['height'],(width,box,nav)
    last.click();dialog=page.locator('#dashboard-detail');expect(dialog).to_be_visible();expect(dialog).to_contain_text('Kursudvikling');expect(dialog.locator('.position-actions-mobile [data-asset-trade=BUY]')).to_be_visible();expect(dialog.locator('.position-actions-mobile [data-asset-trade=SELL]')).to_be_visible();assert page.evaluate("getComputedStyle(document.documentElement).overflowY")=='hidden'
    dialog.get_by_role('button',name='Luk position').click();expect(dialog).to_be_hidden();expect(last).to_be_focused()
    if os.environ.get('ESCAPE_SCREENSHOTS'):page.screenshot(path=str(Path(os.environ['ESCAPE_SCREENSHOTS'])/f'decision-overview-{width}.png'))
   else:
    expect(page.locator('.mobile-holdings')).to_be_hidden();expect(page.locator('.dash-holdings .dash-table')).to_be_visible()
   assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),width
   page.close()
  browser.close()
 print('PASS: compact overview, filters, 18 rows, navigation and modal at mobile/desktop widths')
finally:server.shutdown();server.server_close();case.tearDown()
