"""Synthetic Pluto series rendered in candidate cards; no external data or trades."""
import copy,os,sys,threading
from pathlib import Path
from unittest.mock import patch
from datetime import datetime,timezone,timedelta
sys.path.insert(0,str(Path(__file__).resolve().parents[1]));sys.path.insert(0,str(Path(__file__).resolve().parent))
import app,market_data
import test_market_data as fixtures
from playwright.sync_api import sync_playwright

def account_isolation(page):
 page.add_script_tag(content="""
  window.IntersectionObserver = class { constructor(callback) { window.testChartObserver=callback; } observe() {} disconnect() {} };
 """)
 page.add_script_tag(path=str(Path(__file__).resolve().parents[1]/'static/market-ui.js'))
 page.evaluate(ACCOUNT_ISOLATION)

ACCOUNT_ISOLATION = r"""
async () => {
 const assert = (condition, message) => { if (!condition) throw new Error(message); };
 let hidden=false;
 Object.defineProperty(document, 'hidden', {get:()=>hidden});
 const requests = [], timers = [];
 const realTimeout = window.setTimeout;
 window.setTimeout = (callback, delay) => timers.push({callback, delay});
 const flush = () => new Promise(resolve => realTimeout(resolve, 0));
 let owner = 'A';
 const root = document.body.appendChild(document.createElement('div'));
 root.className = 'signal-overview';
 const timestamp = '2026-11-02T10:00:00Z';
 const quote = price => ({
  name: 'Synthetic', ticker: 'SYN', currency: 'USD', price, fetched_at: timestamp,
  series: [18, 19].map((price, i) => ({
   price, timestamp: new Date(Date.parse(timestamp) + i * 3600000).toISOString(),
   epoch: Date.parse(timestamp) / 1000 + i * 3600,
  })),
 });
 MarketUI.setup({
  api: (_, body) => new Promise(resolve => requests.push({owner, ...body, resolve})),
  escape: value => String(value).replaceAll('&', '&amp;').replaceAll('"', '&quot;'),
  formatAmount: ({amount}) => String(amount), formatTime: String,
  owner: () => owner, connected: () => true, now: () => Date.parse(timestamp),
  age: () => ({tone: 'fresh', minutes: 0}),
 });
 const mount = (...ids) => {
  root.innerHTML = ids.map(candidate_id => MarketUI.slot({
   report_id: 'synthetic', candidate_id,
   markers: [{kind: 'entry', value: 18.5, currency: 'USD'}],
  })).join('');
  MarketUI.mount();
 };
 const slot = id => root.querySelector('[data-market-candidate="' + id + '"]');
 const click = (id, action = 'load') => MarketUI.click(slot(id).querySelector('[data-market-' + action + ']'));
 const finish = async (request, result) => { request.resolve(result); await flush(); };
 const retry = async () => {
  const timer = timers.shift();
  assert(timer?.delay === 2000, 'Expected a pending quote retry');
  timer.callback();
  await flush();
 };

 mount('retry', 'main', 'block', 'queued');
 await click('retry');
 await finish(requests[0], {pending: true});
 await click('main');
 await click('block');
 await click('queued');
 assert(requests.length === 3, 'Third simultaneous request should stay queued');

 // Re-render the same account with the same key while its old node is queued.
 mount('retry', 'main', 'block', 'queued');
 await finish(requests[2], quote(19));
 assert(requests.length === 3, 'Detached queue entry started on a replacement chart');
 await click('block', 'refresh');
 await click('queued');
 assert(requests.length === 4, 'Replacement chart did not queue independently');

 owner = 'B';
 mount('main');
 await click('main');
 await finish(requests[3], quote(20));
 assert(requests[4]?.owner === 'B', 'B did not start its own request');
 owner = 'A';
 mount('main', 'retry', 'queued');
 const current = slot('main');
 current.querySelector('span').textContent = 'Current A';
 await finish(requests[1], {pending: true});
 assert(current.textContent.includes('Current A'), 'Old A response repainted the current chart');
 assert(timers.length === 1, 'Old A response armed a new retry');
 assert(requests.length === 5, 'Obsolete queued request survived the owner change');
 await finish(requests[4], quote(23));
 await retry();
 assert(requests.length === 5, 'Old A timer started a request after A returned');
 assert(!root.querySelector('.market-price'), 'Previous account data appeared in current charts');

 await click('main');
 assert(requests[5]?.owner === 'A', 'Current A could not load its chart');
 await finish(requests[5], {pending: true});
 await retry();
 assert(requests[6]?.candidate_id === 'main', 'Current pending chart did not retry');
 await finish(requests[6], quote(21));
 mount('main', 'main');
 assert(root.querySelectorAll('.market-price').length === 2, 'Same-session charts did not share cached data');
 await click('main', 'refresh');
 assert(requests[7]?.refresh === true, 'Current chart could not refresh');
 await finish(requests[7], quote(22));
 assert([...root.querySelectorAll('.market-price')].every(n => n.textContent === '22'),
        'Current refresh did not update both charts');
 assert(root.querySelectorAll('.signal-chart-peak').length === 2, 'Chart peak was lost');
 assert(root.querySelectorAll('.market-marker-entry').length === 2, 'Purchase markers were lost');

 const select = period => MarketUI.click(slot('main').querySelector('[data-market-period="' + period + '"]'));
 const selected = period => {
  const buttons = [...root.querySelectorAll('[aria-pressed="true"]')];
  return buttons.length === 2 && buttons.every(button => button.dataset.marketPeriod === period);
 };
 await click('main', 'refresh');
 await select('week');
 await select('month');
 await finish(requests[8], quote(23));
 const followup = timers.shift();
 assert(followup?.delay === 0 && selected('month'), 'Week response discarded the selected month');
 assert(!root.querySelector('.market-line'), 'Week series appeared under the month tab');

 // A visible refresh can load the missing period before the deferred follow-up runs.
 const refreshing = MarketUI.refreshVisible();
 assert(requests.length === 10 && requests[9].period === 'ONE_MONTH', 'Visible refresh did not coalesce');
 await finish(requests[9], quote(24));
 await refreshing;
 followup.callback();
 await flush();
 assert(requests.length === 10 && selected('month'), 'Deferred follow-up duplicated the month request');

 await select('day');
 await click('main', 'refresh');
 await finish(requests[10], {pending: true});
 await select('month');
 await retry();
 assert(requests.length === 11 && selected('month'), 'Week retry refreshed the selected month');

 await select('day');
 await click('main', 'refresh');
 await select('year');
 await finish(requests[11], {pending: true});
 const yearFollowup = timers.shift();
 assert(yearFollowup?.delay === 0 && !root.querySelector('.market-warning'),
        'Obsolete week response blocked or marked the selected year');
 yearFollowup.callback();
 assert(requests[12]?.period === 'ONE_YEAR', 'Latest uncached period was not requested');
 await finish(requests[12], quote(25));
 assert(requests.length === 13 && selected('year'), 'Year view was lost');
 await select('day');
 const firstTick = slot('main').querySelector('.market-axis span').textContent;
 assert(selected('day') && /^11[.:]00$/.test(firstTick),
        'Day axis lost Copenhagen time');
 assert(root.querySelectorAll('.signal-chart-peak strong').length === 2, 'Peak display was lost');
 assert(root.querySelectorAll('.market-marker-entry').length === 2, 'Average cost markers were lost');

 await click('main', 'refresh');
 await select('month');
 let refreshed = false;
 const cachedRefresh = MarketUI.refreshVisible().then(() => { refreshed = true; });
 assert(requests.length === 14, 'Cached month refresh overlapped the active week request');
 await finish(requests[13], quote(26));
 assert(selected('month') && [...root.querySelectorAll('.market-price')].every(n => n.textContent === '24'),
        'Week response overwrote the cached month');
 assert(requests.length === 15 && requests[14].period === 'ONE_MONTH' && requests[14].refresh,
        'Cached month refresh was lost or duplicated');
 assert(!refreshed, 'Visible refresh completed before the month response');
 await finish(requests[14], quote(27));
 await cachedRefresh;
 assert(requests.length === 15 && selected('month') &&
        [...root.querySelectorAll('.market-price')].every(n => n.textContent === '27'),
        'Refreshed month did not update both charts');

 // A pending retry must not start hidden work, but visibility must release it.
 await click('main','refresh');
 await finish(requests[15],{pending:true});
 hidden=true;
 await retry();
 assert(requests.length===16,'Hidden retry initiated a request');
 hidden=false;
 document.dispatchEvent(new Event('visibilitychange'));
 await flush();
 assert(requests.length===17 && requests[16].period==='ONE_MONTH','Visible chart remained throttled');
 await finish(requests[16],quote(28));

 // The same rule applies when the chart was offscreen at the retry deadline.
 mount('main');
 await click('main','refresh');
 await finish(requests[17],{pending:true});
 const offscreen=slot('main');
 offscreen.style.position='absolute';offscreen.style.top='10000px';
 await retry();
 assert(requests.length===18,'Offscreen retry initiated a request');
 offscreen.style.position='';offscreen.style.top='';
 window.testChartObserver([{target:offscreen,isIntersecting:true}]);
 await flush();
 assert(requests.length===19,'Returning chart remained throttled');
 await finish(requests[18],quote(29));

 // Fresh chart with no cached month. The visible refresh must await that
 // month, not just the previous day request.
 mount('uncached');
 const uncached=slot('uncached');
 await click('uncached');
 await MarketUI.click(uncached.querySelector('[data-market-period="month"]'));
 let completed=false;
 const pendingRefresh=MarketUI.refreshVisible().then(()=>{completed=true});
 assert(requests.length===20,'Uncached refresh overlapped day request');
 await finish(requests[19],quote(30));
 assert(!completed && requests.length===21 && requests[20].period==='ONE_MONTH',
        'Uncached refresh completed before selected period');
 await finish(requests[20],quote(31));
 await pendingRefresh;
 const delayed=timers.shift();
 assert(delayed?.delay===0,'Missing guarded automatic follow-up');
 delayed.callback();
 await flush();
 assert(requests.length===21 && completed,'Uncached month duplicated or failed to complete');
}
"""

def main():
 case=fixtures.Quotes();case.setUp();payload={'source':'Synthetic','observed':datetime.now(timezone.utc).isoformat(),'kind':'portfolio','positions':[],'accounts':[],'pending_orders':[],'value':None,'errors':[],'complete':True,'orders_complete':True}
 items=[{'id':'portfolios:root','name':'Synthetic root','kind':'portfolio','can_trade':True},{'id':'collections:child','name':'Synthetic child','kind':'collection','parent_external_id':'portfolios:root'}]
 real_normalize=market_data.normalized
 class Extended(case.factory):
  def request(self,method,params):
   if params['name']=='get_asset' and params['arguments']['period'] in ('ONE_MONTH','ONE_YEAR'):
    case.calls.append(params);raw=copy.deepcopy(case.raw);raw['performance']['period']=params['arguments']['period'];return {'structuredContent':raw}
   return super().request(method,params)
 server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
 try:
  with patch('trade_service.MCP',Extended),patch('mcp_client.read_portfolios',return_value=items),patch('portfolio_data.read',return_value=payload),patch('market_data.normalized',side_effect=lambda raw,aid,**kw:real_normalize(raw,aid,case.fixed,**kw)),sync_playwright() as p:
   browser=p.chromium.launch(**({} if os.environ.get('ESCAPE_PLAYWRIGHT_MANAGED') else {'executable_path':'/usr/bin/chromium'}),headless=True,args=['--no-sandbox']);page=browser.new_page(viewport={'width':1440,'height':1000});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
   page.goto(f'http://127.0.0.1:{server.server_port}');page.locator('#login-form [name=password]').fill('test-password-long-enough');page.locator('#login-form button').click();page.locator('#refresh-status[data-kind=success]').wait_for()
   page.locator('nav [data-view=radar]').click();slot=page.locator('.market-slot').first;slot.locator('.market-price').wait_for();assert '18,636' in slot.inner_text();assert '+1,22' in slot.inner_text();assert 'Førmarked' in slot.inner_text();assert 'kurstid ukendt' in slot.inner_text();assert slot.locator('[data-market-period=day]').get_attribute('aria-pressed')=='true'
   assert slot.locator('.market-line').get_attribute('d').count('L')==1;assert slot.locator('.market-change.market-positive').count()==1
   assert slot.locator('.market-plot.market-negative').count()==1;assert '2 punkter' in slot.inner_text();assert 'Skala' in slot.inner_text()
   coords=slot.locator('.market-line').get_attribute('d').replace('M','').replace('L','').split();ys=[float(v.split(',')[1]) for v in coords];assert 0<abs(ys[1]-ys[0])<10
   slot.locator('svg').hover(position={'x':10,'y':20});assert abs(float(slot.locator('.market-focus').get_attribute('cy'))-ys[0])<.01
   assert page.locator('.desk-candidate').first.get_attribute('data-attention')=='yellow'
   slot.locator('[data-market-period=week]').click();assert slot.locator('.market-line').get_attribute('d').count('L')==81;assert 'Uge' in slot.locator('.market-period-title').inner_text();assert '-5,69' in slot.inner_text();assert slot.locator('.market-plot.market-negative').count()==1;assert slot.locator('.market-change.market-positive').count()==1
   slot.locator('[data-market-period=month]').click();slot.locator('.market-period-title').filter(has_text='Måned').wait_for();slot.locator('.market-line').wait_for()
   slot.locator('[data-market-period=year]').click();slot.locator('.market-period-title').filter(has_text='År').wait_for();slot.locator('.market-line').wait_for()
   slot.locator('[data-market-period=day]').click();slot.locator('.market-about summary').click();assert 'Dagsændring er Plutos oplyste tal' in slot.inner_text();assert 'Ikke oplyst af Pluto' in slot.inner_text();slot.locator('.market-about summary').click()
   slot.locator('.market-about summary').click();slot.locator('[data-market-choose]').click();slot.locator('[data-market-asset]').wait_for();slot.locator('[data-market-asset]').select_option('synthetic-chart-asset');slot.locator('[data-market-select]').click();slot.locator('.market-price').wait_for()
   # Current readings in full report cards retain the same daily/weekly distinction.
   slot=page.locator('.desk-candidate .market-slot').first;slot.locator('.market-price').wait_for()
   for width in [320,390,430,768,1024,1440,1920]:
    page.set_viewport_size({'width':width,'height':1000});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),width
    for selector in ['.desk-candidate','.market-slot']:
     assert page.locator(selector).first.evaluate('(n)=>n.scrollWidth<=n.clientWidth+1'),(width,selector)
    slot.locator('.market-about summary').click();assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),('about',width);slot.locator('.market-about summary').click()
    if width in [390,1440]:page.locator('.desk-candidate').first.scroll_into_view_if_needed();page.screenshot(path=f'/tmp/escape-market-{width}.png')
   # Rolling day includes the previous evening: 25 hourly observations give 24 points.
   end=datetime(2026,11,2,10,tzinfo=timezone.utc)
   case.raw['performance']['series']=[{'timestamp':(end-timedelta(hours=24-i)).isoformat(),'close':18+i*.01} for i in range(25)]
   with app.connect() as c:c.execute('UPDATE market_asset_cache SET attempted=0')
   slot.locator('[data-market-refresh]').click();slot.locator('.market-session').filter(has_text='24 punkter').wait_for()
   assert slot.locator('.market-line').get_attribute('d').count('L')==23
   assert slot.locator('.market-plot.market-positive').count()==1
   assert 'Døgn' in slot.inner_text() or 'døgn' in slot.inner_text()
   # Source signs control return colors; report signal remains unchanged.
   case.raw['price'].update(dailyChange='-0.225',dailyChangePercent='-1.222')
   with app.connect() as c:c.execute('UPDATE market_asset_cache SET attempted=0')
   slot.locator('[data-market-refresh]').click();slot.locator('.market-change.market-negative').wait_for();assert page.locator('.desk-candidate').first.get_attribute('data-attention')=='yellow'
   assert all(c['name'] in ['search_assets','get_asset'] for c in case.calls)
   assert not errors,errors
   isolation_page=browser.new_page(viewport={'width':1440,'height':1000})
   account_isolation(isolation_page)
   browser.close()
  print('PASS: chart isolation, shared cache, and period/refresh races')
  print('PASS: actual-shape hourly series, day defaults to 2 points, optional week has 82 points, rolling 24h crosses midnight with 24 samples; sparse decline stays small/red while daily remains green; yellow AFVENT unchanged, premarket and unknown quote time, full report/Radar and 320–1920px')
 finally:server.shutdown();server.server_close();case.tearDown()
if __name__=='__main__':main()
