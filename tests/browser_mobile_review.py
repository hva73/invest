"""Local regressions for quick trade and #263 release status."""
from pathlib import Path
import json
import shutil
import subprocess
import sys
import tempfile


def review_release_status():
    """Run the production status controller against an injected fetch and clock."""
    static = Path(__file__).resolve().parents[1] / 'static'
    app = (static / 'app.js').read_text()
    controller = app[:app.index('function notice(')]
    worker = (static / 'sw.js').read_text()
    html = (static / 'index.html').read_text()
    for phrase in ('<dialog id="release-overlay"', 'Vi opdaterer ESCAPE',
                   'ESCAPE er midlertidigt utilgængelig, mens vi installerer en ny version.',
                   'Forbindelsen genoprettes automatisk.'):
        assert phrase in html, phrase
    script = """
const output = typeof print === 'function' ? print : console.log;
const assert = (condition, message) => { if (!condition) throw Error(message); };
let current, apiStatus = 404, apiCalls = 0, reloads = 0, nextId = 0;
const timers = new Map(), events = {}, nodes = {};
let probeCalls = 0;
const document = {
 body: { classList: { contains: () => false } },
 querySelector: id => nodes[id] ??= {
  open: false, contains: target => target === 'overlay',
  showModal() { this.open = true; },
  addEventListener: (name, callback) => { events[name] = callback; },
 },
 addEventListener: (name, callback, capture) => { if (capture) events[name] = callback; },
};
const location = {reload: () => reloads++};
const setTimeout = (callback, delay) => {
 timers.set(++nextId, {callback, delay});
 return nextId;
};
const clearTimeout = id => timers.delete(id);
class AbortController {
 constructor(){ this.signal = {}; }
 abort(){ this.signal.abort?.(); }
}
const fetch = async (path, options) => {
 if (path !== '/escape-release/status.json') {
  apiCalls++;
  return {status: apiStatus, ok: apiStatus === 200, json: async () => ({error: 'Oprindelig fejl'})};
 }
 probeCalls++;
 assert(options.cache === 'no-store' && options.redirect === 'error' &&
        options.credentials === 'omit', 'status must bypass the cache and stay same-origin');
 if (current === 'offline') throw Error('Netværksfejl');
 if (current === 'hang') return new Promise((_, reject) => {
  options.signal.abort = () => reject(Object.assign(Error('timeout'), {name:'AbortError'}));
 });
 const [status, state, kind = 'application/json'] = current;
 return {status, headers: {get: () => kind}, json: async () => ({state})};
};
""" + '\nnew Function(' + json.dumps(app) + ');\n' + controller + """
const swEvents = [];
new Function('self', """ + json.dumps(worker) + """)({
 addEventListener: name => swEvents.push(name)
});
assert(!swEvents.includes('fetch'), 'service worker must not serve stale status or navigation');
const overlay = nodes['#release-overlay'];
const title = () => nodes['#release-title'].textContent;
const detail = () => nodes['#release-detail'].textContent;
const retry = () => [...timers.values()].at(-1);
async function run() {
 current = [404, 'maintenance'];
 await api('session').then(
  () => { throw Error('expected original API error'); },
  error => assert(error.status === 404 && error.message === 'Oprindelig fejl', 'API 404 was replaced'),
 );
 await checkReleaseStatus();
 assert(!overlay.open, '404 must not become maintenance');
 current = [200, 'maintenance', 'text/html'];
 await checkReleaseStatus();
 assert(!overlay.open, 'HTML must not become maintenance');
 current = [200, 'normal'];
 await checkReleaseStatus();
 assert(reloads === 0, 'normal startup should not reload');
 current = [503, 'maintenance'];
 apiStatus = 503;
 await api('state').catch(error => assert(error.status === 503, 'original failure was replaced'));
 await releaseProbe;
 assert(!overlay.open, 'generic server outage must keep its original error');
 current = [200, 'maintenance'];
 const beforeSend = apiCalls;
 await api('trade/send', {}).catch(() => {});
 assert(apiCalls === beforeSend, 'preflight must block a send before the next scheduled poll');
 assert(overlay.open && title() === 'Vi opdaterer ESCAPE', 'open session missed maintenance');
 assert(retry().delay === 5000, 'incorrect initial retry delay');
 let cancelled = false;
 events.cancel({preventDefault: () => { cancelled = true; }});
 assert(cancelled, 'Escape must not dismiss maintenance');
 for (const name of ['click', 'submit']) {
  let prevented = false, stopped = false;
  events[name]({target: 'stale CTA', preventDefault: () => { prevented = true; },
   stopImmediatePropagation: () => { stopped = true; }});
  assert(prevented && stopped, 'stale trade UI remained actionable');
 }
 const sent = apiCalls;
 await api('trade/send', {}).catch(() => {});
 assert(apiCalls === sent, 'trade API call escaped maintenance');
 current = 'offline';
 const before = probeCalls;
 const first = checkReleaseStatus();
 assert(checkReleaseStatus() === first && probeCalls === before + 1, 'overlapping probes');
 await first;
 assert(overlay.open && detail().includes('Netværksfejl') && reloads === 0,
        'offline state lost the error or reloaded');
 current = 'hang';
 const pending = checkReleaseStatus();
 assert(retry().delay === 4000, 'status request must time out');
 retry().callback();
 await pending;
 assert(detail().includes('tog for lang tid'), 'timeout was hidden');
 current = [200, 'recovery'];
 await checkReleaseStatus();
 assert(overlay.open && title() !== 'Vi opdaterer ESCAPE' && nodes['#release-reconnect'].hidden,
        'recovery should be distinct from planned maintenance');
 current = [503, 'normal'];
 await checkReleaseStatus();
 assert(retry().delay === 30000, 'retry delay should be capped');
 assert(overlay.open && detail().includes('HTTP 503') && reloads === 0,
        'unverified normal must keep the outage visible');
 current = [200, 'normal'];
 await checkReleaseStatus();
 await checkReleaseStatus();
 assert(reloads === 1 && apiCalls === sent, 'verified normal must reload once without replaying writes');
 output('PASS: #263 maintenance, outage, stale actions, uncached status and verified recovery');
}
run().catch(error => output('FAIL: ' + error.message + ' ' + error.stack));
"""
    jsc = Path('/System/Library/Frameworks/JavaScriptCore.framework/Versions/A/Helpers/jsc')
    runtime = shutil.which('node') or shutil.which('jsc') or (str(jsc) if jsc.is_file() else None)
    assert runtime, 'Node.js or JavaScriptCore is required for the offline status regression'
    with tempfile.TemporaryDirectory() as tmp:
        script_path = Path(tmp) / 'release-status.js'
        script_path.write_text(script)
        result = subprocess.run([runtime, str(script_path)], capture_output=True, text=True)
    assert result.returncode == 0 and result.stdout.startswith('PASS:'), result.stdout + result.stderr
    print(result.stdout.strip())


if '--release-status' in sys.argv:
    review_release_status()
    sys.exit(0)

from playwright.sync_api import sync_playwright, expect

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True)
    page.set_content('<!doctype html><html lang="da"><head><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover"></head><body><main></main></body></html>')
    page.add_style_tag(path=str(Path('static/style.css').resolve()))
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
        expect(dialog.locator('h2')).to_be_focused()
        dialog.locator('[name=size]').fill('50')
        expect(dialog.locator('[name=size]')).to_be_focused()
        assert dialog.locator('[name=size]').evaluate("e=>parseFloat(getComputedStyle(e).fontSize)")>=16
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
