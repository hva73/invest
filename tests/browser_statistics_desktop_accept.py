"""Synthetic end-to-end statistics UI; no Pluto or order operations."""
import os,sys,threading
from pathlib import Path
from unittest.mock import patch
sys.path[:0]=['.','tests']
import app
from test_portfolio_value_chart import PortfolioValueChart
from playwright.sync_api import expect,sync_playwright
case=PortfolioValueChart();case.setUp()
server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
from realized_statistics import project
from test_realized_statistics import order
buy=order('BUY','10','10','2026-01-01T00:00:00Z','b')
sales=[order('SELL','4','12','2026-01-02T00:00:00Z','s1'),order('SELL','2','8','2026-01-03T00:00:00Z','s2'),order('SELL','1','10','2026-01-04T00:00:00Z','s3')]
for row in [buy,*sales]: row['asset']={'ticker':'SYNTH','name':'Fiktiv aktie','currency':'DKK'}
rows=project([buy,*sales])['items']
assert [(r['cost_basis'],r['sale_proceeds'],r['gross']) for r in rows]==[('40','48','8'),('20','16','-4'),('10','10','0')]
for row,ticker in zip(rows,['DELSALG','TAB','NUL']):row['ticker']=ticker
usd_buy=order('BUY','1','1000','2026-01-01T00:00:00Z','b2');usd_sell=order('SELL','1','1100','2026-01-02T00:00:00Z','s4')
for row in [usd_buy,usd_sell]:row['asset']={'ticker':'USD_ONLY','name':'Fiktiv handel i USD','currency':'USD'}
rows+=project([usd_buy,usd_sell])['items']
tiny_buy=order('BUY','1000000000','0.000000001','2026-01-01T00:00:00Z','tiny-buy');tiny_sell=order('SELL','1000000000','0.000000002','2026-01-02T00:00:00Z','tiny-sell')
for row in [tiny_buy,tiny_sell]:row['asset']={'ticker':'TINY','name':'Fiktiv lille kurs','currency':'DKK'}
tiny_rows=project([tiny_buy,tiny_sell])['items']
payload={'portfolios':[{'portfolio_id':1,'name':'Fiktivt depot','items':rows,'omitted':1,'history_complete':False},{'portfolio_id':2,'name':'Fiktiv lille kurs','items':tiny_rows,'omitted':0,'history_complete':False}],'errors':[],'history_complete':False}
try:
 with patch('mcp_client.MCP.request',side_effect=AssertionError('No broker calls')),sync_playwright() as p:
  browser=p.chromium.launch(headless=True)
  for width in (390,768,1280,1440):
   page=browser.new_page(viewport={'width':width,'height':1000},is_mobile=width==390,has_touch=width==390);errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
   page.route('**/api/realized-statistics',lambda route:route.fulfill(json=payload))
   page.goto(f'http://127.0.0.1:{server.server_port}/');page.locator('#login-form [name=password]').fill('test-password-long-enough');page.locator('#login-form button').click()
   if width<=900:page.locator('#mobile-more').click()
   page.locator('nav [data-view=statistics]').click();expect(page.locator('#statistics-title')).to_have_text('Hvordan står det til?')
   page.locator('[data-statistics-portfolio]').select_option('1')
   view=page.locator('.statistics-view')
   expect(view).to_contain_text('50 %');expect(view.locator('.st-total')).to_contain_text('+4,00 kr.');expect(view).to_contain_text('3 af 4 salg')
   expect(view.locator('.statistics-warning')).to_contain_text('fuldstændighed')
   assert page.locator('[data-statistics-currency]').count()==0
   page.locator('.st-gains [data-statistics-show-group=wins]').click();group=page.locator('dialog:modal')
   expect(group).to_contain_text('DELSALG');expect(group).to_contain_text('USD_ONLY');expect(group).not_to_contain_text('TAB')
   opener=group.locator('[data-statistics-trade]').first;opener.click();dialog=page.locator('dialog:modal').last
   for value in ['Solgt mængde','Gns. købspris','Kostpris, solgte andele','+40,00 DKK','+48,00 DKK','Ikke afklaret','omkostninger']:expect(dialog).to_contain_text(value)
   dialog.get_by_role('button',name='Luk',exact=True).click()
   group.get_by_role('button',name='Luk',exact=True).click()
   page.locator('.st-gains [data-statistics-show-group=losses]').click();group=page.locator('dialog:modal')
   expect(group).to_contain_text('TAB');expect(group).not_to_contain_text('DELSALG');group.get_by_role('button',name='Luk',exact=True).click()
   page.locator('.st-coverage').click();group=page.locator('dialog:modal');expect(group).to_contain_text('USD_ONLY');group.get_by_role('button',name='Luk',exact=True).click()
   page.locator('[data-statistics-portfolio]').select_option('2');page.locator('.st-gains [data-statistics-show-group=wins]').click()
   page.locator('dialog:modal [data-statistics-trade]').click();dialog=page.locator('dialog:modal').last;expect(dialog).to_contain_text('+0,000000001 DKK');dialog.get_by_role('button',name='Luk',exact=True).click()
   page.locator('dialog:modal').get_by_role('button',name='Luk',exact=True).click()
   assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),width
   assert not errors,errors;page.close()
  browser.close()
 print('PASS: actual category, popup, totals, partial sales and currency scope')
finally:server.shutdown();server.server_close();case.tearDown()
