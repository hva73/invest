"""Display and review buy/sell dialogs with local stub responses only."""
import os
from pathlib import Path
from playwright.sync_api import expect, sync_playwright

screens = Path(os.environ.get('ESCAPE_SCREENSHOTS', '/tmp/escape-desktop-screens'))
screens.mkdir(parents=True, exist_ok=True)
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={'width': 1440, 'height': 900})
    page.set_content('<!doctype html><html lang="da"><head><meta name="viewport" content="width=device-width,initial-scale=1"></head><body><main></main></body></html>')
    page.add_style_tag(path=str(Path('static/style.css').resolve()))
    page.add_style_tag(path=str(Path('static/desktop-experience.css').resolve()))
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
        throw Error('Unexpected endpoint: '+name);
      };
      TradeUI.setup({api,escape:x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),formatTime:String,updated(){},getState:()=>state});
      document.addEventListener('click', e=>{const b=e.target.closest('button');if(b)TradeUI.click(b)});
      document.addEventListener('submit', e=>TradeUI.submit(e));
      document.addEventListener('change', e=>TradeUI.change(e));
    }''')
    for side in ('BUY', 'SELL'):
        page.evaluate("side => TradeUI.openQuick({report_id:side==='BUY'?'@manual-buy':'@manual-sell',ticker:'TEST',asset_id:'test-id',portfolio_id:7,signal:side})", side)
        dialog = page.locator('#quick-trade-dialog')
        expect(dialog).to_be_visible()
        expect(dialog.locator('h2')).to_be_focused()
        dialog.locator('[name=size]').fill('50')
        dialog.locator('button[type=submit]').click()
        expect(dialog.locator('#quick-trade-review')).to_contain_text('Gennemgå')
        assert page.evaluate("calls.filter(c=>c.name==='trade/send').length") == 0
        box = dialog.bounding_box()
        assert box['x'] >= 0 and box['x'] + box['width'] <= 1441, box
        page.screenshot(path=str(screens / f'trade-{side.lower()}-1440.png'))
        dialog.locator('[data-quick-close]').click()
    browser.close()
print('PASS: synthetic desktop buy/sell dialogs; no order submitted')
