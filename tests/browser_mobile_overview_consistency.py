"""Browser contract for mobile ranking, readable metrics and floating nav clearance."""
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

def main():
 with sync_playwright() as pw:
  browser=pw.chromium.launch(headless=True,args=['--no-sandbox'])
  page=browser.new_page(viewport={'width':390,'height':844},is_mobile=True,has_touch=True)
  page.set_content('<!doctype html><html lang="da"><head><meta name="viewport" content="width=device-width,initial-scale=1"></head><body><aside><nav><button>Overblik</button></nav></aside><main id="screen"></main></body></html>')
  for path in ('static/style.css','static/desktop-experience.css'):
   page.add_style_tag(content=Path(path).read_text())
  page.add_script_tag(path='static/dashboard-ui.js')
  page.evaluate("""() => {
    const now=new Date().toISOString();
    const mk=(ticker,profit,currency='DKK')=>({
      key:ticker,ticker,name:'Test '+ticker,portfolio_id:1,portfolio_name:'Test depot',
      portfolio_kind:'portfolio',asset_id:ticker,quantity:'1',verification:'broker_snapshot',
      price:{amount:'100',currency:'USD'},price_time:now,price_freshness:{state:'fresh'},
      value:{amount:currency==='DKK'?'300':'100',currency},
      unrealized:{amount:String(profit),currency},unrealized_percent:profit/3,
      daily:{amount:'-1.2',percent:'-1.2',currency:'USD',to:now,basis:'pluto_reported_daily_change'},
      conflicts:[],hot_watch:{},analysis_freshness:{}
    });
    const state={dashboard:{
      positions:[mk('LOSS',-30),mk('FX',100,'EUR'),mk('GAIN',20),mk('WINNER',80)],
      accounts:[],totals:[],warnings:[],orders:[],critical_sessions:[]
    },report_desk:null};
    window.DashboardUI.setup({api:()=>{},escape:String,formatTime:String,formatQuantity:String,state:()=>state});
    document.querySelector('#screen').innerHTML=window.DashboardUI.render(state);
  }""")
  cards=page.locator('.mobile-holdings-list .mobile-holding-card')
  expect(cards).to_have_count(4)
  names=cards.locator('.mobile-holding-name>strong').all_text_contents()
  assert names==['WINNER','GAIN','LOSS','FX'], names
  for index in range(4):
   card=cards.nth(index)
   expect(card.locator('.mobile-holding-total.neutral')).to_be_visible()
   assert card.locator('.mobile-holding-total').inner_text().strip()[:1] not in ('↑','↓')
   expect(card.locator('.mobile-holding-daily > span')).to_have_count(2)
   amount=card.locator('.mobile-holding-daily > span').first.inner_text()
   assert '↑' not in amount and '↓' not in amount, amount
  assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
  page.evaluate('window.scrollTo(0,document.documentElement.scrollHeight)')
  page.wait_for_timeout(100)
  bottom=cards.last.bounding_box()
  nav=page.locator('aside nav').bounding_box()
  assert bottom and nav and bottom['y']+bottom['height']<nav['y']-5,(bottom,nav)
  browser.close()

if __name__=='__main__':main()
