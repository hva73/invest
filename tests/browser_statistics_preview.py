"""Static statistics component preview. Entirely synthetic; no broker access."""
import os
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

sample={'portfolios':[{'portfolio_id':1,'name':'Fiktivt hoveddepot','items':[
 {'ticker':'NOVA','name':'Fiktiv vækstaktie','currency':'USD','gross':'12.35','gross_percent':'6.2','quantity':'2','buy_price':'100','sell_price':'106.175','note':'Foreløbigt bruttoresultat','sell_time':None},
 {'ticker':'ALFA','name':'Fiktiv industrivirksomhed','currency':'USD','gross':'-4.1','gross_percent':'-2.4','quantity':'1','buy_price':'170','sell_price':'165.9','note':'Foreløbigt bruttoresultat','sell_time':None}]},{'portfolio_id':2,'name':'Fiktiv Collection','items':[]}],'errors':[]}
out=Path(os.environ.get('ESCAPE_SCREENSHOTS','/tmp/statistics-preview'));out.mkdir(parents=True,exist_ok=True)
with sync_playwright() as p:
 browser=p.chromium.launch(headless=True)
 for width in (320,390,768,1280):
  page=browser.new_page(viewport={'width':width,'height':900},device_scale_factor=1)
  page.set_content('<!doctype html><html lang="da"><meta name="viewport" content="width=device-width,initial-scale=1"><body style="margin:0;padding:20px;background:#091820;font-family:system-ui"><p style="color:#b6cec5">DESIGNFORSLAG · FIKTIVE DATA</p><main id="content"></main></body></html>')
  page.add_style_tag(path='static/statistics.css');page.add_script_tag(path='static/statistics-ui.js')
  page.evaluate('(data) => StatisticsUI.mount(document.querySelector("#content"), async () => data)',sample)
  expect(page.locator('#statistics-title')).to_contain_text('Hvordan står det til')
  expect(page.locator('.statistics-summary>div:first-child>strong')).to_contain_text('+8,25 USD')
  page.locator('[data-statistics-group=wins]').click();page.locator('.statistics-trade-button').first.click();expect(page.locator('dialog:modal .statistics-detail')).to_be_visible()
  assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1'),width
  page.screenshot(path=str(out/f'statistik-fiktiv-{width}.png'),full_page=True)
  page.close()
 browser.close()
print('PASS: synthetic isolated statistics preview and detail at 320/390/768/1280')
