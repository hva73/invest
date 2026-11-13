from playwright.sync_api import sync_playwright
data={'portfolios':[{'portfolio_id':'1','name':'Fiktivt','items':[{'ticker':'TEST','name':'Fiktiv aktie','currency':'DKK','gross':'2','gross_percent':'5','quantity':'3','buy_price':'13.33333333333333333333333333','cost_basis':'40','sell_price':'14','sale_proceeds':'42','note':'Foreløbigt'}]}]}
with sync_playwright() as p:
 browser=p.chromium.launch()
 page=browser.new_page(viewport={'width':320,'height':760})
 page.set_content('<style>body { margin:0; background:#071721; font:14px Arial }</style><main id="test"></main>')
 page.add_style_tag(path='static/statistics.css')
 page.add_script_tag(path='static/statistics-ui.js')
 page.evaluate('(data) => StatisticsUI.mount(document.querySelector("#test"), async () => data)',data)
 page.wait_for_selector('[data-statistics-group=wins]')
 page.locator('[data-statistics-group=wins]').click()
 page.locator('.statistics-trade-button').click()
 page.wait_for_selector('dialog:modal')
 page.screenshot(path='statistics-long-decimal-320.png')
 result=page.locator('dialog').evaluate('el => ({scroll:el.scrollWidth,client:el.clientWidth, rows:[...el.querySelectorAll(".statistics-calc > div")].map(x=>({scroll:x.scrollWidth,client:x.clientWidth,text:x.innerText}))})')
 print(result,flush=True)
 assert result['scroll']<=result['client'] and all(x['scroll']<=x['client'] for x in result['rows']), 'Popup indhold flyder vandret over'
 browser.close()
