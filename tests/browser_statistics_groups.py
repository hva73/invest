from playwright.sync_api import sync_playwright
from pathlib import Path
import json
fixture={'portfolios':[{'portfolio_id':'1','name':'Fiktivt','items':[
 {'ticker':'WIN','name':'Winner','currency':'DKK','gross':'1200.00','gross_percent':'8.00','quantity':'12','sell_price':'1350','buy_price':'1250','cost_basis':'15000','sale_proceeds':'16200','note':'Foreløbigt'},
 {'ticker':'LOSS','name':'Loser','currency':'DKK','gross':'-300.00','gross_percent':'-5.00','quantity':'1','sell_price':'5700','note':'Foreløbigt'}]}]}
with sync_playwright() as p:
 browser=p.chromium.launch()
 for width in (320,390,768,1440):
  page=browser.new_page(viewport={'width':width,'height':900})
  page.set_content('<main id="test"></main>')
  page.add_style_tag(path='static/statistics.css')
  page.add_script_tag(path='static/statistics-ui.js')
  page.evaluate('(data) => StatisticsUI.mount(document.querySelector("#test"), async () => data)',fixture)
  page.wait_for_selector('[data-statistics-group=wins]')
  assert page.locator('.statistics-trade').count()==0
  page.locator('[data-statistics-group=wins]').click()
  assert page.locator('.statistics-trade').count()==1 and 'WIN' in page.locator('.statistics-list').inner_text()
  page.locator('.statistics-trade-button').click()
  assert page.locator('dialog:modal').count()==1
  assert '15000' in page.locator('dialog:modal .statistics-detail').inner_text()
  page.keyboard.press('Escape')
  assert page.locator('dialog:modal').count()==0
  assert page.locator('.statistics-trade-button').evaluate('(el) => document.activeElement === el')
  page.locator('.statistics-trade-button').click()
  page.locator('dialog button[aria-label="Luk"]').click()
  assert page.locator('dialog:modal').count()==0
  page.locator('[data-statistics-group=losses]').click()
  assert page.locator('.statistics-trade').count()==1 and 'LOSS' in page.locator('.statistics-list').inner_text()
  page.locator('[data-statistics-group=losses]').click()
  assert page.locator('.statistics-trade').count()==0
  assert page.evaluate('document.documentElement.scrollWidth') <= width
  page.close()
 browser.close()
print('PASS: category interactions and responsive layouts')
