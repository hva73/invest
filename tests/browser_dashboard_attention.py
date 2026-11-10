"""Synthetic desktop and mobile acceptance for actionable dashboard items."""
from pathlib import Path
from playwright.sync_api import sync_playwright,expect

def main():
 with sync_playwright() as pw:
  browser=pw.chromium.launch(headless=True,args=['--no-sandbox'])
  for width in (390,1280):
   page=browser.new_page(viewport={'width':width,'height':800})
   page.set_content('<!doctype html><html lang="da"><head></head><body><main id="screen"></main></body></html>')
   page.add_style_tag(content=Path('static/style.css').read_text())
   page.add_script_tag(path='static/dashboard-ui.js')
   page.evaluate('''() => {
    window.DashboardUI.setup({api:()=>{},escape:String,formatTime:String,formatQuantity:String,state:()=>({})});
    const mk=(ticker,id,signal,status='ACTIVE')=>({key:ticker+id,ticker,name:ticker,portfolio_id:id,portfolio_name:'Depot '+id,conflicts:[],hot_watch:{session:{watch_id:ticker+id,status,signal,display_status:signal==='SELL'?'SÆLGSSIGNAL':'AFVENT',last_action_signal:{event_id:'old',event_type:'SELL_SIGNAL',state:'WITHDRAWN'}}}});
    const positions=['ASML','MSFT','TSM','NRG','MPWR','ETN','VRT','ORCL'].map(t=>mk(t,1,'WAIT'));
    positions.push(mk('ZETA',1,'SELL'),mk('ZETA',2,'SELL'),mk('ZETA',1,'SELL'));
    window.testState={dashboard:{positions,accounts:[],totals:[],warnings:[],orders:[],critical_sessions:[]}};
    document.querySelector('#screen').innerHTML=window.DashboardUI.render(window.testState);
   }''')
   panel=page.locator('.dash-attention');expect(panel.locator('.dash-count')).to_have_text('2');expect(panel.locator('tbody tr')).to_have_count(2)
   expect(panel).to_contain_text('Depot 1');expect(panel).to_contain_text('Depot 2');expect(panel).not_to_contain_text('ASML');expect(panel).not_to_contain_text('Tidligere')
   expect(panel.locator('[data-view="hot-watch"]')).to_have_text('Se alle overvågninger →')
   page.evaluate('''() => {
    const o={key:'order:synthetic',verified_id:true,portfolio_id:1,portfolio_name:'Depot 1',ticker:'XYZ',status:'AWAITING_APPROVAL',source:'Pluto',verification:'broker_snapshot',observed_at:new Date().toISOString()};
    testState.dashboard.orders=[o,{...o}];document.querySelector('#screen').innerHTML=window.DashboardUI.render(testState);
   }''')
   expect(page.locator('.dash-attention .dash-count')).to_have_text('3');expect(page.locator('.dash-approval')).to_have_count(1);expect(page.locator('.dash-approval')).to_contain_text('status dokumenterer ikke, at handlen er udført');expect(page.locator('.dash-approval [data-open-portfolio="1"]')).to_be_visible()
   page.evaluate("testState.dashboard.orders=[]")
   page.evaluate("testState.dashboard.positions=testState.dashboard.positions.slice(0,8);document.querySelector('#screen').innerHTML=window.DashboardUI.render(testState)")
   expect(page.locator('.dash-attention .dash-count')).to_have_text('0');expect(page.locator('.dash-attention')).to_contain_text('Ingen aktuelle købs-, salgs- eller handlingskrævende advarsler')
   page.close()
  browser.close()
 print('PASS: desktop and mobile dashboard actions, separate depots, count and empty state')
if __name__=='__main__':main()
