"""Real app navigation with synthetic completed trades; all broker calls disabled."""
import os,sys,threading
from pathlib import Path
from unittest.mock import patch
sys.path[:0]=['.','tests']
import app
from test_portfolio_value_chart import PortfolioValueChart
from playwright.sync_api import sync_playwright,expect
case=PortfolioValueChart();case.setUp()
server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
def item(ticker,currency,gross,dkk,origin):
 return dict(ticker=ticker,name=ticker+' Fiktiv',currency=currency,gross=gross,display_gross_dkk=dkk,gross_percent='10' if float(gross)>0 else '-5',quantity='2',buy_price='10',sell_price='11',cost_basis='20',sale_proceeds='22',sell_origin=origin,buy_origin='own',display_fx={'rate':'6.8' if currency=='USD' else '7.46','source':'ECB','as_of':'2026-11-13'})
sample={'portfolios':[{'portfolio_id':1,'name':'Fiktivt depot','items':[item('NOVA','USD','12.35','83.98','signal'),item('ALFA','USD','-4.1','-27.88','own')]},{'portfolio_id':2,'name':'Fiktiv Collection','items':[item('EURO','EUR','3','22.38','unknown')],'unresolved_sales':[dict(ticker='MISSING',name='Fiktivt salg uden kostpris',currency='USD',quantity='1',sell_price='4',sale_proceeds='4')]}],'errors':[]}
try:
 with patch('mcp_client.MCP.request',side_effect=AssertionError('Live broker calls disabled')),sync_playwright() as pw:
  launch={'headless':True}
  if os.environ.get('ESCAPE_SYSTEM_CHROMIUM'):launch.update(executable_path='/usr/bin/chromium',args=['--no-sandbox'])
  browser=pw.chromium.launch(**launch)
  for width in (320,390,768,1280,1440):
   page=browser.new_page(viewport={'width':width,'height':940},is_mobile=width<700,has_touch=width<700);errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
   mode={'failure':False}
   def route(r):
    if mode['failure']:r.fulfill(status=503,json={'error':'Historik utilgængelig','diagnostic':'BROKER_CATALOG'})
    else:r.fulfill(json=sample)
   page.route('**/api/realized-statistics',route)
   page.goto(f'http://127.0.0.1:{server.server_port}/');page.locator('#login-form [name=password]').fill('test-password-long-enough');page.locator('#login-form button').click();expect(page.locator('.dashboard-v1')).to_be_visible()
   if width<=900:page.locator('#mobile-more').click()
   page.locator('nav [data-view=statistics]').click();expect(page.locator('#statistics-title')).to_have_text('Hvordan står det til?')
   expect(page.locator('.st-total')).to_contain_text('+78,48 kr.');expect(page.locator('.st-subtitle')).to_have_text('3 af 4 salg · omregnet til DKK')
   assert page.locator('[data-statistics-currency]').count()==0
   assert page.locator('.statistics-dialog:modal').count()==0
   page.locator('.st-gains [data-statistics-show-group=wins]').click();group=page.locator('dialog:modal');expect(group).to_contain_text('NOVA');expect(group).to_contain_text('EURO');expect(group).not_to_contain_text('ALFA')
   group.locator('[data-statistics-trade]').first.click();detail=page.locator('dialog:modal').last;expect(detail).to_contain_text('Gns. købspris');expect(detail).to_contain_text('ESCAPE-signal');expect(detail).to_contain_text('referencekurs');detail.get_by_role('button',name='Luk',exact=True).click()
   page.locator('dialog:modal').get_by_role('button',name='Luk',exact=True).click()
   page.locator('.st-gains [data-statistics-show-group=losses]').click();expect(page.locator('dialog:modal')).to_contain_text('ALFA');expect(page.locator('dialog:modal')).not_to_contain_text('NOVA');page.locator('dialog:modal').get_by_role('button',name='Luk',exact=True).click()
   page.locator('.st-source[data-statistics-show-group=signal]').click();expect(page.locator('dialog:modal')).to_contain_text('NOVA');page.locator('dialog:modal').get_by_role('button',name='Luk',exact=True).click()
   page.locator('.st-coverage').click();expect(page.locator('dialog:modal')).to_contain_text('MISSING');page.locator('dialog:modal').get_by_role('button',name='Luk',exact=True).click()
   assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1'),width
   shots=os.environ.get('ESCAPE_SCREENSHOTS')
   if shots:
    Path(shots).mkdir(parents=True,exist_ok=True)
    page.evaluate("document.body.insertAdjacentHTML('afterbegin','<div style=\"background:#253747;color:#cad8e2;padding:5px;text-align:center;font-size:11px\">DESIGNKONTROL · FIKTIVE DATA</div>')")
    page.screenshot(path=str(Path(shots)/f'statistik-dkk-{width}.png'),full_page=True)
   page.locator('[data-statistics-portfolio]').select_option('1');expect(page.locator('.st-total')).to_contain_text('+56,10 kr.');page.locator('[data-statistics-portfolio]').select_option('all')
   mode['failure']=True;page.locator('[data-statistics-reload]').click();expect(page.locator('#content')).to_contain_text('BROKER_CATALOG');mode['failure']=False;page.locator('[data-statistics-reload]').click();expect(page.locator('.st-total')).to_contain_text('+78,48 kr.')
   assert not errors,errors
   page.close()
  browser.close()
 print('PASS: compact DKK overview, gains/loss/source drilldown, trade details, missing basis, depot and retry at 320/390/768/1280/1440')
finally:server.shutdown();server.server_close();case.tearDown()
