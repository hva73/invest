"""Verify statistics percentage is geometrically centered on desktop/mobile."""
from pathlib import Path
from playwright.sync_api import sync_playwright

def main():
 with sync_playwright() as pw:
  browser=pw.chromium.launch(headless=True,args=['--no-sandbox'])
  for width in (390,768,1280,1440):
   page=browser.new_page(viewport={'width':width,'height':900})
   page.set_content('<main id="stats"></main>')
   for path in ('static/style.css','static/desktop-experience.css','static/statistics.css'):
    page.add_style_tag(content=Path(path).read_text())
   page.add_script_tag(path='static/statistics-ui.js')
   for wins,losses in ((1,9),(2,1),(1,0),(0,1)):
    page.evaluate("""([wins,losses])=>{const items=Array.from({length:wins+losses},(_,i)=>({ticker:'TEST',name:'Synthetic',currency:'DKK',gross:i<wins?'1':'-1',gross_percent:i<wins?'1':'-1'}));document.querySelector('#stats').innerHTML=StatisticsUI.render({portfolios:[{name:'Test',portfolio_id:1,items}]});}""",[wins,losses])
    result=page.locator('.st-ring').evaluate("""svg=>{const t=svg.querySelector('text:not(.st-ring-label)'),r=svg.querySelector('.st-ring-base'),b=t.getBBox(),c=r.getBBox(),label=svg.querySelector('.st-ring-label').getBBox();return {dx:b.x+b.width/2-c.x-c.width/2,dy:b.y+b.height/2-c.y-c.height/2,gap:label.y-(b.y+b.height),text:t.textContent};}""")
    assert abs(result['dx'])<=1 and abs(result['dy'])<=2 and result['gap']>=0,(width,result)
   page.close()
  browser.close()
 print('PASS: statistics ring percentage centered at four viewport widths')

if __name__=='__main__':main()
