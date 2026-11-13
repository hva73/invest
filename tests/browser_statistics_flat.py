from playwright.sync_api import sync_playwright
data={'portfolios':[{'portfolio_id':1,'name':'Fiktivt','items':[
 {'ticker':'FLAT','name':'Neutral aktie','currency':'DKK','gross':'0','gross_percent':'0','quantity':'3','buy_price':'10','sell_price':'10','cost_basis':'30','sale_proceeds':'30','note':'Foreløbigt'},
 {'ticker':'WIN','name':'Gevinst','currency':'DKK','gross':'2','gross_percent':'10','quantity':'2','buy_price':'10','sell_price':'11','cost_basis':'20','sale_proceeds':'22','note':'Foreløbigt'}]}]}
with sync_playwright() as p:
 browser=p.chromium.launch()
 for width in (320,390,768,1440):
  page=browser.new_page(viewport={'width':width,'height':900})
  page.set_content('<style>*{box-sizing:border-box}body{margin:0}</style><main id="test"></main>')
  page.add_style_tag(path='static/statistics.css')
  page.add_script_tag(path='static/statistics-ui.js')
  page.evaluate('(data) => StatisticsUI.mount(document.querySelector("#test"), async () => data)',data)
  page.wait_for_selector('[data-statistics-group=flat]')
  assert page.locator('.statistics-trade').count()==0
  page.locator('[data-statistics-group=flat]').click()
  assert 'FLAT' in page.locator('.statistics-list').inner_text()
  assert 'WIN' not in page.locator('.statistics-list').inner_text()
  page.locator('.statistics-trade-button').click()
  assert 'Neutral aktie' in page.locator('dialog:modal').inner_text()
  assert '→ 0,00' in page.locator('dialog:modal').inner_text()
  page.keyboard.press('Escape')
  assert page.locator('dialog:modal').count()==0
  page.locator('[data-statistics-group=flat]').click()
  assert page.locator('.statistics-trade').count()==0
  assert page.evaluate('document.documentElement.scrollWidth') <= width
  page.close()
 browser.close()
print('PASS: neutral handler og popup på mobil og desktop')
