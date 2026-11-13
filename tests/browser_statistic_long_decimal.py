from playwright.sync_api import sync_playwright
import sys
sys.path.insert(0,'.')
from realized_statistics import project
def order(side, quantity, price, timestamp, ident):
 return {'id':ident,'side':side,'status':'FILLED','filledQuantity':quantity,'filledAveragePrice':price,'createdAt':timestamp,'filledAt':timestamp,'scope':'ROOT','collectionId':None,'asset':{'ticker':'TEST','name':'Fiktiv aktie','currency':'DKK'}}
buys=[order('BUY','1','12','2026-01-01T00:00:00Z','b1'),order('BUY','2','14','2026-01-02T00:00:00Z','b2')]
sale=order('SELL','3','14','2026-01-03T00:00:00Z','s')
result=project([], [('c',row) for row in [*buys,sale]])
assert len(result['items'])==1
row=result['items'][0]
assert (row['cost_basis'],row['sale_proceeds'],row['gross'])==('40','42','2')
data={'portfolios':[{'portfolio_id':'1','name':'Fiktivt',**result}]}
with sync_playwright() as p:
 browser=p.chromium.launch()
 page=browser.new_page(viewport={'width':320,'height':760})
 page.set_content('<style>* { box-sizing:border-box } body { margin:0; background:#071721; font:14px Arial }</style><main id="test"></main>')
 page.add_style_tag(path='static/statistics.css')
 page.add_script_tag(path='static/statistics-ui.js')
 page.evaluate('(data) => StatisticsUI.mount(document.querySelector("#test"), async () => data)',data)
 page.wait_for_selector('[data-statistics-group=wins]')
 page.locator('[data-statistics-group=wins]').click()
 page.locator('.statistics-trade-button').click()
 page.wait_for_selector('dialog:modal')
 assert '40 kr.' in page.locator('dialog:modal').inner_text()
 assert '42 kr.' in page.locator('dialog:modal').inner_text()
 assert '+2,00 kr.' in page.locator('dialog:modal').inner_text()
 page.screenshot(path='statistics-long-decimal-320.png')
 result=page.locator('dialog').evaluate('el => ({scroll:el.scrollWidth,client:el.clientWidth, rows:[...el.querySelectorAll(".statistics-calc > div")].map(x=>({scroll:x.scrollWidth,client:x.clientWidth,text:x.innerText}))})')
 print(result,flush=True)
 assert result['scroll']<=result['client'] and all(x['scroll']<=x['client'] for x in result['rows']), 'Popup indhold flyder vandret over'
 tiny_buy=order('BUY','1000000000','0.000000001','2026-01-01T00:00:00Z','tb')
 tiny_sale=order('SELL','1000000000','0.000000002','2026-01-02T00:00:00Z','ts')
 tiny=project([tiny_buy,tiny_sale])['items'][0]
 tiny_html=page.evaluate('(row) => StatisticsUI.render({portfolios:[{portfolio_id:1,name:"Test",items:[row]}]}, {group:"wins"})',tiny)
 page.locator('#test').evaluate('(el, html) => el.innerHTML=html',tiny_html)
 shown=page.locator('.statistics-calc > div').nth(1).locator('strong').text_content()
 print('Shown nonzero buy price:',shown,flush=True)
 assert shown == '<0,000001 kr.', 'Ikke-nul købspris skal vises under afrundingsgrænsen'
 browser.close()
