"""Real application routing on a disposable fixture; no live broker calls."""
import os,sys,threading
from pathlib import Path
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
import app
from test_portfolio_value_chart import PortfolioValueChart
from playwright.sync_api import sync_playwright,expect
from browser_mobile_account_isolation import run_account_isolation

CAPTURE_STORED_POLL = """() => {
 const interval = window.setInterval;
 window.setInterval = (callback, delay, ...args) => {
  if (delay === 30000 && callback.toString().includes('storedPollBusy')) window.storedPoll = callback;
  return interval(callback, delay, ...args);
 };
}"""

CHECK_STORED_POLL = """async () => {
 const originalFetch = window.fetch;
 const watch = 'fixture-repaint-watch';
 const session = {watch_id: watch, status: 'ACTIVE', signal: 'WAIT',
   request: {ticker: 'FIXTURE', watch_mode: 'entry', portfolio_ids: []}};
 const answer = data => Promise.resolve(new Response(JSON.stringify(data)));
 try {
  for (const action of ['dashboardWatch', 'dashboardDecision']) {
   const dashboard = document.querySelector('.dashboard-v1');
   const before = {...state};
   delete before.automation;
   delete before.report_desk;
   let releaseState;
   window.fetch = (url, options) => {
    if (url === '/api/state') {
     if (!releaseState) return new Promise(resolve => { releaseState = () => resolve(answer(before)); });
     return answer({...before, fixture_repaint: action});
    }
    if (url.startsWith('/api/v1/hotwatch/sessions/' + watch)) {
     return answer(url.includes('/samples?') || url.includes('/events?') ? {items: []} : {session});
    }
    return originalFetch(url, options);
   };
   const button = document.createElement('button');
   button.dataset[action] = watch;
   dashboard.append(button);
   const opening = DashboardUI.click(button);
   await window.storedPoll();
   const repainted = !dashboard.isConnected && Boolean(document.querySelector('.dashboard-v1'));
   releaseState();
   await opening;
   const dialog = document.getElementById('engine-dialog');
   if (!repainted || !dialog?.open || !dialog.querySelector('h2').textContent.includes('FIXTURE')) {
    throw Error(action + ' did not open after the stored-data poll repainted Overview');
   }
   dialog.close();
  }
 } finally { window.fetch = originalFetch; }
}"""

CHECK_HOLDING_DIALOG = """async () => {
 const originalFetch = window.fetch;
 const originalDashboard = state.dashboard;
 const watch = 'fixture-holding-watch';
 const session = {watch_id: watch, status: 'ACTIVE', signal: 'WAIT', display_status: 'AFVENT',
   request: {ticker: 'HOLDING A', watch_mode: 'exit', portfolio_ids: []}};
 const portfolio = state.portfolios.find(row => row.source === 'pluto' && row.kind === 'portfolio');
 const sample = {portfolio_id: portfolio.id, portfolio_kind: portfolio.kind, portfolio_name: portfolio.name,
   quantity: '1', verification: 'broker_snapshot', raw: {}, missing: {}, conflicts: []};
 const holdingA = {...sample, key: 'holding-a', asset_id: 'holding-a', ticker: 'HOLDING A', hot_watch: {session}};
 const holdingB = {...sample, key: 'holding-b', asset_id: 'holding-b', ticker: 'HOLDING B', hot_watch: {}};
 const answer = (data, status = 200) => new Response(JSON.stringify(data), {status});
 const nextTask = () => new Promise(resolve => setTimeout(resolve, 0));
 const notice = document.getElementById('notice');
 const originalNotice = notice.textContent;
 const originalNoticeKind = notice.dataset.kind;
 let action, receiveRead;
 window.fetch = (url, options) => {
  if (url === '/api/state' && action === 'dashboardWatch') {
   return new Promise(resolve => receiveRead(resolve));
  }
  if (url.startsWith('/api/v1/hotwatch/sessions/' + watch)) {
   if (action === 'dashboardDecision') return new Promise(resolve => receiveRead(resolve));
   return Promise.resolve(answer(url.includes('/samples?') || url.includes('/events?') ? {items: []} : {session}));
  }
  return originalFetch(url, options);
 };
 try {
  state.dashboard = {...originalDashboard, positions: [holdingA, holdingB], overview_positions: [holdingA, holdingB]};
  const failures = [];
  for (action of ['dashboardWatch', 'dashboardDecision']) {
   for (const outcome of ['success', 'error']) {
    for (const dismissed of [false, true]) {
     render();
     const watchButton = document.querySelector('[data-dashboard-watch="' + watch + '"]');
     const holdingButton = document.querySelector('.mobile-holding[data-dashboard-open="1"]');
     if (!watchButton || !holdingButton) throw Error('Missing fixture holdings on Overview');
     watchButton.dataset[action] = watch;
     if (action === 'dashboardDecision') delete watchButton.dataset.dashboardWatch;
     const reading = new Promise(resolve => { receiveRead = resolve; });
     watchButton.click();
     const finishRead = await reading;
     holdingButton.click();
     await nextTask();
     const holding = document.querySelector('#dashboard-detail[open]');
     if (!holding?.querySelector('h2').textContent.includes('HOLDING B')) throw Error('Holding B did not open');
     if (dismissed) {
      holding.querySelector('[data-dashboard-close]').click();
      await nextTask();
     }
     const previousNotice = 'Holding B · ' + [action, outcome, dismissed].join('/');
     notice.textContent = previousNotice;
     finishRead(outcome === 'success' ? answer(action === 'dashboardWatch' ? state : {session}) :
       answer({error: 'Obsolete holding error'}, 500));
     await nextTask();
     if (notice.textContent !== previousNotice || holding.open === dismissed ||
         document.querySelector('#engine-dialog[open]')) {
      failures.push([action, outcome, dismissed].join('/'));
     }
     document.querySelectorAll('dialog[open]').forEach(dialog => dialog.close());
    }
   }
  }
  if (failures.length) throw Error('Obsolete HOT WATCH response reached holding B: ' + failures.join(', '));
 } finally {
  window.fetch = originalFetch;
  state.dashboard = originalDashboard;
  notice.textContent = originalNotice;
  if (originalNoticeKind === undefined) delete notice.dataset.kind;
  else notice.dataset.kind = originalNoticeKind;
  render();
 }
}"""

CHECK_MANUAL_START_FOCUS = """async () => {
 const originalFetch = window.fetch;
 const candidateId = 'fixture-history';
 const watch = 'fixture-manual-start';
 const answer = data => new Response(JSON.stringify(data));
 const nextTask = () => new Promise(resolve => setTimeout(resolve, 0));
 const list = {sessions: [], kill_switch: {}};
 const session = {watch_id: watch, status: 'ACTIVE', signal: 'WAIT',
   request: {ticker: 'MANUAL', watch_mode: 'entry', portfolio_ids: []}};
 let receiveStart, receiveList, receiveDetail, detailReads = 0;
 window.fetch = (url, options) => {
  if (url.includes('view=current')) {
   if (!receiveList) return Promise.resolve(answer(list));
   const receive = receiveList;
   receiveList = null;
   return new Promise(resolve => receive(() => resolve(answer(list))));
  }
  if (url.includes('view=history')) return Promise.resolve(answer({sessions: []}));
  if (url.startsWith('/api/reports/candidate-registry?')) return Promise.resolve(answer({candidates: []}));
  if (url.startsWith('/api/v1/hotwatch/manual-search?')) {
   return Promise.resolve(answer({assets: [{asset_id: 'fixture-asset', ticker: 'MANUAL'}]}));
  }
  if (url.startsWith('/api/v1/hotwatch/manual-start?')) {
   if (receiveStart) return new Promise(resolve => receiveStart(() => {
    resolve(new Response(JSON.stringify({error: 'Obsolete start error'}), {status: 500}));
   }));
   return Promise.resolve(answer({session}));
  }
  if (url.startsWith('/api/v1/hotwatch/sessions/' + watch)) {
   if (url.includes('/samples?') || url.includes('/events?')) return Promise.resolve(answer({items: []}));
   detailReads++;
   if (receiveDetail) {
    const receive = receiveDetail;
    receiveDetail = null;
    return new Promise(resolve => receive(() => resolve(answer({session}))));
   }
   return Promise.resolve(answer({session}));
  }
  if (url.startsWith('/api/reports/candidate-history?')) return Promise.resolve(answer({events: []}));
  if (url.startsWith('/api/reports/hot-watch?')) return Promise.resolve(answer({groups: []}));
  return originalFetch(url, options);
 };
 try {
  view = 'hot-watch';
  render();
  await nextTask();
  const historyButton = document.createElement('button');
  historyButton.dataset.intelHistory = candidateId;
  document.getElementById('watch-content').append(historyButton);
  const failures = [];
  async function search() {
   await EngineUI.click(document.querySelector('[data-engine-new]'));
   const form = document.getElementById('engine-manual-search');
   form.elements.query.value = 'MANUAL';
   await EngineUI.submit({target: form, preventDefault() {}});
   return document.querySelector('[data-engine-manual]');
  }
  async function openHistory() {
   await IntelUI.click(historyButton);
   const history = document.querySelector('#intel-detail-dialog[open]');
   if (!history?.textContent.includes(candidateId)) throw Error('Candidate history did not open');
   return history;
  }
  {
   const button = await search();
   const status = document.getElementById('engine-manual-status');
   const previousStatus = status.textContent;
   const startPending = new Promise(resolve => { receiveStart = resolve; });
   const start = EngineUI.click(button);
   const finishStart = await startPending;
   receiveStart = null;
   const history = await openHistory();
   await IntelUI.click(history.querySelector('[data-intel-close]'));
   finishStart();
   await start;
   if (button.disabled || status.textContent !== previousStatus) failures.push('start error after dismissal');
   button.closest('dialog').close();
  }
  for (const phase of ['refresh', 'refresh after dismissal', 'detail', 'uninterrupted']) {
   const button = await search();
   const listPending = new Promise(resolve => { receiveList = resolve; });
   const start = EngineUI.click(button);
   const finishList = await listPending;
   const priorReads = detailReads;
   let finishDetail;
   if (phase === 'detail') {
    const detailPending = new Promise(resolve => { receiveDetail = resolve; });
    finishList();
    finishDetail = await detailPending;
   }
   let history;
   if (phase !== 'uninterrupted') {
    history = await openHistory();
    if (phase === 'refresh after dismissal') await IntelUI.click(history.querySelector('[data-intel-close]'));
   }
   (finishDetail || finishList)();
   await start;
   const detail = document.querySelector('#engine-dialog[open]');
   if (phase === 'uninterrupted') {
    if (detail?.dataset.watchId !== watch || detailReads !== priorReads + 1) failures.push(phase);
   } else if (detail || detailReads !== priorReads + Number(phase === 'detail') ||
              (history.open && document.activeElement !== history.querySelector('h2')) ||
              history.open !== (phase !== 'refresh after dismissal')) {
    failures.push(phase);
   }
   document.querySelectorAll('dialog[open]').forEach(dialog => dialog.close());
  }
  if (failures.length) throw Error('Manual start interfered with candidate history: ' + failures.join(', '));
 } finally {
  window.fetch = originalFetch;
  view = 'overview';
  render();
 }
}"""

CHECK_MANUAL_SALE_SESSION = """async () => {
 const originalFetch = window.fetch;
 const watch = 'fixture-manual-sale';
 const user = state.user.username;
 const portfolio = state.portfolios.find(p => p.source === 'pluto' && p.active && p.kind === 'portfolio');
 const session = {watch_id: watch, status: 'DEGRADED', signal: 'SELL',
   request: {ticker: 'FIXTURE', portfolio_ids: [portfolio.id]}};
 const answer = (data, status = 200) => new Response(JSON.stringify(data), {status});
 const check = (value, message) => { if (!value) throw Error(message); };
 const nextTask = () => new Promise(resolve => setTimeout(resolve, 0));
 let receiveRead;
 window.fetch = (url, options) => {
  if (url === '/api/v1/hotwatch/sessions/' + watch + '?is_test=false') {
   return Promise.resolve(answer({session}));
  }
  if (url === '/api/state' && receiveRead) {
   const receive = receiveRead;
   receiveRead = null;
   return new Promise(resolve => receive(resolve));
  }
  return originalFetch(url, options);
 };
 const manualButton = () => document.querySelector('#engine-dialog[open] [data-signal-manual-portfolio]');
 function readManualSale(button = manualButton()) {
  const pending = new Promise(resolve => { receiveRead = resolve; });
  button.click();
  return pending;
 }
 async function startManualSale() {
  await EngineUI.openNotification(watch);
  const button = manualButton();
  check(button?.textContent.includes('Åbn depot for manuelt salg'), 'Missing the manual sale button');
  return readManualSale(button);
 }
 const staleAccount = {
  portfolios: [{...portfolio, name: 'Prior session portfolio'}],
  dashboard: {...state.dashboard, positions: [{asset_id: 'prior-session-asset'}]},
  portfolio_snapshots: {}
 };
 const notice = document.getElementById('notice');
 try {
  const failures = [];
  for (const outcome of ['success', 'error']) {
   const finish = await startManualSale();
   const epoch = sessionEpoch;
   await document.getElementById('logout').onclick();
   check(!state, 'Logout did not clear the account');
   const form = document.getElementById('login-form');
   form.elements.username.value = user;
   form.elements.password.value = 'test-password-long-enough';
   await form.onsubmit({target: form, preventDefault() {}});
   check(state?.user.username === user && sessionEpoch !== epoch && view === 'overview',
    'Fixture did not log back into the same account on Overview');
   const {portfolios, dashboard, portfolio_snapshots} = state;
   notice.textContent = 'New session notice';
   finish(outcome === 'success' ? answer(staleAccount) : answer({error: 'Prior session error'}, 500));
   await nextTask();
   if (view !== 'overview' || portfolios !== state.portfolios || dashboard !== state.dashboard ||
       portfolio_snapshots !== state.portfolio_snapshots || notice.textContent !== 'New session notice') {
    failures.push(outcome);
    view = 'overview';
    await refresh();
   }
  }
  check(!failures.length, 'Prior-session manual sale changed the new session: ' + failures.join(', '));

  const dismissed = await startManualSale();
  manualButton().closest('dialog').close();
  dismissed(answer({error: 'Dismissed manual sale error'}, 500));
  await nextTask();
  check(view === 'overview' && notice.textContent === 'New session notice',
   'A dismissed manual sale reached the notice');

  const superseded = await startManualSale();
  const fail = await readManualSale();
  superseded(answer(staleAccount));
  await nextTask();
  check(view === 'overview' && manualButton(), 'An older click opened a depot before the latest click resolved');
  fail(answer({error: 'Current manual sale error'}, 500));
  await nextTask();
  check(notice.textContent === 'Current manual sale error' && manualButton(),
   'Current manual sale failure did not leave the dialog retryable');

  const unverified = await readManualSale();
  const currentAccount = state.portfolios;
  unverified(answer({portfolios: [{...portfolio, active: false}]}));
  await nextTask();
  check(view === 'overview' && state.portfolios === currentAccount && manualButton() &&
   notice.textContent.includes('Depotet kan ikke bekræftes'),
   'An inactive depot replaced current account data or opened holdings');

  const finishRetry = await readManualSale();
  const updated = {...portfolio, name: 'Current verified depot'};
  const dashboard = {...state.dashboard, manual_sale_fixture: true};
  const snapshots = {...state.portfolio_snapshots, manual_sale_fixture: true};
  finishRetry(answer({portfolios: [updated], dashboard, portfolio_snapshots: snapshots}));
  await nextTask();
  const holdings = portfolioSection === 'holdings' || document.activeElement?.dataset.portfolioSection === 'holdings';
  check(view === 'portfolio-detail' && selectedPortfolio === Number(portfolio.id) &&
   holdings && !manualButton() &&
   document.querySelector('.portfolio-detail-hero h2')?.textContent === updated.name &&
   state.dashboard.manual_sale_fixture && state.portfolio_snapshots.manual_sale_fixture,
   'Current manual sale did not open the verified depot holdings');
 } finally { window.fetch = originalFetch; }
}"""

run_account_isolation()
case=PortfolioValueChart();case.setUp()
server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
threading.Thread(target=server.serve_forever,daemon=True).start()
try:
 with patch('mcp_client.MCP.request',side_effect=AssertionError('Live broker calls disabled')),sync_playwright() as p:
  browser=p.chromium.launch(headless=True)
  for width in (320,390,768,1280):
   page=browser.new_page(viewport={'width':width,'height':844});errors=[]
   page.on('pageerror',lambda e:errors.append(str(e)))
   if width==390:page.add_init_script(f"({CAPTURE_STORED_POLL})()")
   page.goto(f'http://127.0.0.1:{server.server_port}')
   page.locator('#login-form [name=password]').fill('test-password-long-enough')
   page.locator('#login-form button').click();expect(page.locator('.dashboard-v1')).to_be_visible()
   screenshot_dir=os.environ.get('ESCAPE_SCREENSHOTS')
   if screenshot_dir:
    Path(screenshot_dir).mkdir(parents=True,exist_ok=True)
    page.screenshot(path=str(Path(screenshot_dir)/f'overview-{width}.png'))
   nav=page.locator('body > aside nav')
   if width<=900:
    more=page.locator('#mobile-more');expect(more).to_be_visible()
    assert nav.locator(':scope > button[data-view]').evaluate_all('xs => xs.map(x => x.dataset.view)')==['overview','portfolios','hot-watch','sectors']
    for target in ('portfolios','hot-watch','sectors','overview'):
     nav.locator(f':scope > [data-view="{target}"]').click()
     expect(nav.locator(f':scope > [data-view="{target}"]')).to_have_class('active')
     if width<=700 and target=='portfolios':
      expect(page.locator('.portfolio-catalog-heading .section-heading>div')).to_be_hidden();expect(page.locator('.portfolio-catalog-heading button')).to_be_visible()
      if screenshot_dir:page.screenshot(path=str(Path(screenshot_dir)/f'clean-portfolios-{width}.png'))
     if width<=700 and target=='hot-watch':
      expect(page.locator('.engine-overview')).to_be_visible();expect(page.locator('.engine-hero>div')).to_be_hidden();expect(page.locator('[data-engine-new]')).to_be_visible();expect(page.locator('[data-watch-refresh]')).to_be_visible()
      if screenshot_dir:page.screenshot(path=str(Path(screenshot_dir)/f'clean-hotwatch-{width}.png'))
     assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1'),(width,target)
    more.click();expect(page.locator('#mobile-more-panel')).to_be_visible()
    expect(page.locator('#mobile-more-panel [data-view=radar]')).to_be_visible()
    page.locator('#mobile-more-panel [data-view=radar]').click()
    expect(page.locator('#mobile-more-panel')).to_be_hidden()
    expect(page.locator('#mobile-more-panel [data-view=radar]')).to_have_class('active')
    more.click();expect(page.locator('#mobile-more-panel')).to_be_visible()
    for action in ('profile-open','refresh-current','logout'):
     assert page.locator(f'#mobile-more-panel #{action}').count()==1,(width,action)
    if screenshot_dir:page.screenshot(path=str(Path(screenshot_dir)/f'menu-{width}.png'))
    page.locator('#mobile-more-panel [data-view=trade]').click()
    expect(page.locator('.broker-trade')).to_be_visible();expect(page.locator('#mobile-more-panel')).to_be_hidden()
    assert page.locator('#mobile-more-panel [data-view=trade]').evaluate("e=>e.classList.contains('active')")
    more.click();page.keyboard.press('Escape');expect(page.locator('#mobile-more-panel')).to_be_hidden()
    page.locator('nav [data-view=overview]').click()
    before=nav.bounding_box();page.evaluate('window.scrollTo(0,document.body.scrollHeight)');after=nav.bounding_box()
    assert abs(before['y']-after['y'])<2,(width,before,after)
    if width==390:
     page.evaluate(CHECK_STORED_POLL)
     page.evaluate(CHECK_HOLDING_DIALOG)
     page.evaluate(CHECK_MANUAL_START_FOCUS)
     page.evaluate(CHECK_MANUAL_SALE_SESSION)
   else:
    expect(page.locator('#mobile-more')).to_be_hidden();assert page.locator('main > header #logout').count()==1;nav.locator('[data-view=trade]').click();expect(page.locator('.broker-trade')).to_be_visible()
   assert not errors,(width,errors)
   page.close()
  browser.close()
 print('PASS: mobile, tablet and desktop routing in real app fixture')
finally:
 server.shutdown();server.server_close();case.tearDown()
