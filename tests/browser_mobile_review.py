"""Browser regression for quick trade; all API calls are simulated in page."""
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True)
    page.set_content('<!doctype html><html lang="da"><body><main></main></body></html>')
    page.add_script_tag(path=str(Path('static/trade-ui.js').resolve()))
    page.evaluate('''() => {
      window.calls = [];
      const state = {user:{username:'test'},portfolios:[{id:7,name:'Testdepot',source:'pluto',active:true,kind:'portfolio'}]};
      const api = async (name, data) => {
        calls.push({name,data});
        if(name === 'trade/preview') return {};
        if(name === 'trade/estimate') {
          const sell = data.size_mode === 'percent';
          return {proposal:{id:5,status:'estimated',review_token:'test-token',portfolio_id:7,
            payload:{orders:[{assetId:'test-id',side:sell?'SELL':'BUY',amount:sell?null:data.size,shares:sell?'1':null,currency:'DKK',orderType:'MARKET'}]},
            asset:{asset:{name:'Testaktie',isin:'TEST'}},estimate:{quote:{estimatedAmount:'100'},active_orders:[]},
            sell_basis:sell?{quantity:'2',percentage:data.size,shares:'1'}:null}};
        }
        if(name === 'trade/send') return {proposal:{status:'sent'}};
        throw Error('Unexpected endpoint: '+name);
      };
      TradeUI.setup({api,escape:x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),formatTime:String,updated(){},getState:()=>state});
      document.addEventListener('click', e=>{const b=e.target.closest('button');if(b)TradeUI.click(b)});
      document.addEventListener('submit', e=>TradeUI.submit(e));
      document.addEventListener('change', e=>TradeUI.change(e));
    }''')
    for side in ('BUY','SELL'):
        page.evaluate("side => TradeUI.openQuick({report_id:side==='BUY'?'@manual-buy':'@manual-sell',ticker:'TEST',asset_id:'test-id',portfolio_id:7,signal:side})", side)
        dialog=page.locator('#quick-trade-dialog')
        dialog.locator('[name=size]').fill('50')
        before=page.evaluate("calls.filter(c=>c.name==='trade/send').length")
        dialog.locator('button[type=submit]').click()
        expect(dialog.locator('#quick-trade-review')).to_contain_text('Gennemgå')
        assert page.evaluate("calls.filter(c=>c.name==='trade/send').length")==before
        dialog.locator('[data-quick-send]').click()
        expect(dialog.locator('#quick-trade-status')).to_contain_text('Bekræft først')
        assert page.evaluate("calls.filter(c=>c.name==='trade/send').length")==before
        dialog.locator('#quick-trade-confirm').check()
        dialog.locator('[data-quick-send]').click()
        expect(dialog).to_contain_text('Åbn Pluto')
        assert page.evaluate("calls.filter(c=>c.name==='trade/send').length")==before+1
        dialog.locator('[data-quick-close]').click()
    browser.close()
print('PASS: browser review for simulated buy and sell; no live broker')
