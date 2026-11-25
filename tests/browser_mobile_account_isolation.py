"""Synthetic HOT WATCH races at 390px. Run with python3 tests/browser_mobile_account_isolation.py."""
from pathlib import Path


def browser_fixture():
    source = (Path(__file__).resolve().parents[1] / "static/engine-ui.js").read_text()
    # Exercise the retained report-candidate form without adding a production entry point.
    source = source.replace("return {openHoldingStatus,", "return {legacyCreation,openHoldingStatus,", 1)
    return """<!doctype html><meta name="viewport" content="width=device-width, initial-scale=1">
<p id="notice"></p><div id="content"></div>
<script>""" + source + """
const content = document.getElementById('content');
const pending = [];
const userIds = {alpha: 11, beta: 22};
let username,epoch=0,holdCurrentLoad=false,omitHistory=false,poll;
// Run polling deterministically even when the browser fixture has no focused window.
Object.defineProperty(document, 'hidden', {value: false});
const realTimeout = window.setTimeout;
window.setTimeout = (callback, delay) => {
    if (delay === 15000) { poll = callback; return null; }
    return realTimeout(callback, delay);
};
const session = (watch_id, status = 'ACTIVE') => ({
    watch_id, status, signal: 'WAIT',
    request: {ticker: watch_id, watch_mode: 'entry', portfolio_ids: []}
});
const assert = (condition, message) => { if (!condition) throw Error(message); };
const byId = id => document.getElementById(id);
const api = (path, args) => {
    const user = username;
    if (path === 'market/quote' || path === 'state' || path.includes('&before=') || path.endsWith('/pause') || path.endsWith('/ack-signal') || /manual-(search|start)/.test(path) || /sessions\/notification-/.test(path) || (holdCurrentLoad&&path.includes('view=current'))) {
        return new Promise((resolve, reject) => pending.push({path, args, user, resolve, reject}));
    }
    if (path.includes('/start-candidates')) return Promise.resolve({candidates: [0, 1].map(i => ({
        report_id: user + '-report',
        candidate: {candidate_id: user + '-' + i, ticker: user + i}
    }))});
    if (/\\/(samples|events)\\?/.test(path)) return Promise.resolve({items: []});
    if (/\\/sessions\\//.test(path)) return Promise.resolve({session: {
        status: 'ACTIVE', signal: 'WAIT', request: {ticker: user, watch_mode: 'entry', portfolio_ids: []}
    }});
    if (path.includes('view=current')) return Promise.resolve({
        sessions: [session(user + '-watch'), session(user + '-next')], kill_switch: {}
    });
    if (path.includes('view=history')) return Promise.resolve({
        sessions: omitHistory ? [] : [session(user + '-closed', 'COMPLETED')], next_cursor: user + '-cursor'
    });
    if (path.startsWith('reports/')) return Promise.resolve({candidates: []});
    return Promise.resolve({sessions: [], kill_switch: {}});
};
const take = (path, user) => {
    const index = pending.findIndex(request => request.path.includes(path) && request.user === user);
    assert(index >= 0, 'Missing ' + user + ' request: ' + path);
    return pending.splice(index, 1)[0];
};
const account = user => ({
    portfolios: [{id: userIds[user], name: user + '-depot', active: true, source: 'pluto', kind: 'portfolio'}],
    portfolio_snapshots: {[userIds[user]]: {data: {positions_complete: true, positions: [
        {kind: 'holding', asset_id: 'shared-asset', quantity: 1}
    ]}}}
});
const switchAccount = user => {
    epoch++;
    username = user;
    content.innerHTML = user ? '<div id="engine-root"></div>' : '';
    if (user) EngineUI.mount(false);
};
const quote = (asset_id = 'shared-asset') => ({asset_id, currency: 'DKK', exchange: 'XCSE'});
const create = async user => {
    const action = EngineUI.legacyCreation();
    take('state', user).resolve(account(user));
    await new Promise(resolve => setTimeout(resolve, 0));
    return {action, request: take('market/quote', user)};
};
const select = index => {
    const target = byId('engine-create').elements.candidate;
    target.value = index;
    return EngineUI.change({target});
};
const run = async () => {
    assert(innerWidth === 390, 'Expected 390px viewport');
    EngineUI.setup({api, owner: () => username, session:()=>epoch, isAdmin: () => false, editing: () => false,
        escape: value => String(value ?? ''), formatTime: String});
    switchAccount('alpha');
    const alpha = await create('alpha');
    const staleDetail = EngineUI.openDetail('alpha-watch');
    const alphaDetail = take('state', 'alpha');
    const staleError = EngineUI.openDetail('alpha-error-watch');
    const alphaError = take('state', 'alpha');
    const oldNotification=EngineUI.openNotification('notification-alpha');
    const oldNotice=take('/sessions/notification-alpha','alpha');
    const oldNoticeState=take('state','alpha');
    switchAccount(null);
    switchAccount('beta');
    oldNotice.reject(Error('private alpha notification error'));
    oldNoticeState.resolve(account('alpha'));
    await oldNotification;

    const beta = await create('beta');
    alphaDetail.resolve(account('alpha'));
    await staleDetail;
    assert(!byId('engine-buy-plan'), 'Stale detail replaced beta form');
    assert(!byId('engine-create').textContent.includes('alpha'), 'Alpha candidate or depot leaked');
    beta.request.resolve(quote());
    await beta.action;
    const form = byId('engine-create');
    assert(form.elements.portfolios.value === '22', 'Stale detail changed beta holding match');
    const betaStatus = byId('engine-form-status').textContent;
    alphaError.reject(Error('private alpha detail error'));
    await staleError;
    alpha.request.resolve({selection_required: true, choices: [{asset_id: 'alpha-secret'}]});
    await alpha.action;
    assert(!byId('engine-asset-choice'), 'Stale alpha choices appeared in beta form');
    assert(byId('engine-form-status').textContent === betaStatus, 'Stale quote overwrote beta status');

    const first = select(1);
    const firstQuote = take('market/quote', 'beta');
    const second = select(0);
    take('market/quote', 'beta').resolve(quote('beta-new'));
    await second;
    firstQuote.reject(Error('stale quote failure'));
    await first;
    assert(form.elements.asset_id.value === 'beta-new', 'Newest instrument did not win');
    assert(byId('engine-form-status').textContent.includes('beta-new'), 'Stale error changed form status');

    const oldLookup = select(0);
    const oldQuote = take('market/quote', 'beta');
    const newLookup = select(0);
    take('market/quote', 'beta').resolve(quote('beta-latest'));
    await newLookup;
    oldQuote.resolve(quote('beta-old'));
    await oldLookup;
    assert(form.elements.asset_id.value === 'beta-latest', 'Older quote overwrote the same candidate');

    const beforeModeChange = select(0);
    const outdatedModeQuote = take('market/quote', 'beta');
    EngineUI.mount(true);
    EngineUI.mount(false);
    outdatedModeQuote.resolve(quote('beta-previous-mode'));
    await beforeModeChange;
    assert(form.elements.asset_id.value === 'beta-latest', 'Quote survived a live/test round trip');

    // Exercise the production manual-search/start and notification entry points.
    const newButton=()=>byId('engine-root').querySelector('[data-engine-new]');
    const notice=EngineUI.openNotification('notification-beta');
    const noticeRequest=take('/sessions/notification-beta','beta');
    const noticeState=take('state','beta');
    await EngineUI.click(newButton());
    noticeRequest.resolve({session:{status:'ACTIVE',signal:'WAIT',request:{ticker:'old-notice'}}});
    noticeState.resolve(account('beta'));
    await notice;
    assert(byId('engine-manual-search'), 'Old notification replaced a newer dialog');

    const manual=byId('engine-manual-search');
    manual.elements.query.value='BETA';
    const search=EngineUI.submit({target:manual,preventDefault(){}});
    take('manual-search','beta').resolve({assets:[{asset_id:'shared-asset',ticker:'BETA',name:'Beta asset'}]});
    await search;
    const start=EngineUI.click(byId('engine-manual-results').querySelector('[data-engine-manual]'));
    const startRequest=take('manual-start','beta');
    holdCurrentLoad=true;
    startRequest.resolve({session:{watch_id:'beta-new-watch'}});
    await new Promise(resolve=>setTimeout(resolve,0));
    const loadRequest=take('view=current','beta');
    holdCurrentLoad=false;
    await EngineUI.click(newButton());
    loadRequest.resolve({sessions: [session('beta-watch'), session('beta-next')], kill_switch: {}});
    await start;
    assert(byId('engine-manual-search'), 'Old manual start replaced a newer dialog');

    // Poll the currently open dialog while a newer detail is waiting for account data.
    const button = selector => content.querySelector(selector);
    const open = wid => EngineUI.click(button('[data-engine-detail="' + wid + '"]'));
    const previous = open('beta-watch');
    take('state', 'beta').resolve(account('beta'));
    await previous;
    const next = open('beta-next');
    const nextState = take('state', 'beta');
    holdCurrentLoad = true;
    const cycle = poll();
    const pollLoad = take('view=current', 'beta');
    holdCurrentLoad = false;
    pollLoad.resolve({sessions: [session('beta-watch'), session('beta-next')], kill_switch: {}});
    await new Promise(resolve => setTimeout(resolve, 0));
    nextState.resolve(account('beta'));
    await next;
    assert(byId('engine-dialog').dataset.watchId === 'beta-next', 'Old poll invalidated newer detail');
    await cycle;

    // Mirror the global click error handler and keep ordinary current-account errors visible.
    const click = async selector => {
        try { await EngineUI.click(button(selector)); }
        catch (error) { byId('notice').textContent = error.message; }
    };
    const control = '[data-engine-control="pause"]';
    const history = '[data-engine-history-more]';
    const currentError = click(control);
    take('/pause', 'beta').reject(Error('current control error'));
    await currentError;
    assert(byId('notice').textContent === 'current control error', 'Current control error was hidden');
    const currentHistoryError = click(history);
    take('&before=', 'beta').reject(Error('current history error'));
    await currentHistoryError;
    assert(byId('notice').textContent === 'current history error', 'Current history error was hidden');

    const staleHistory = click(history);
    const staleHistoryRequest = take('&before=', 'beta');
    const staleControl = click(control);
    const staleControlRequest = take('/pause', 'beta');
    switchAccount(null);
    switchAccount('alpha');
    byId('notice').textContent = 'alpha notice';
    staleHistoryRequest.reject(Error('private beta history error'));
    await staleHistory;
    assert(byId('notice').textContent === 'alpha notice', 'Stale history error reached global notice');
    staleControlRequest.reject(Error('private beta control error'));
    await staleControl;
    assert(byId('notice').textContent === 'alpha notice', 'Stale control error reached global notice');

    switchAccount('beta');
    // Confirm the ordinary detail entry point still displays the current account's depot.
    const detail = EngineUI.openDetail('beta-watch');
    take('state', 'beta').resolve(account('beta'));
    await detail;
    assert(byId('engine-buy-plan').elements.portfolio_id.value === '22', 'Fresh detail lost beta depot');

    // Dashboard detail without engine root, logout and relogin as same username.
    content.innerHTML='';
    const staleSame=EngineUI.openDetail('beta-prior-session');
    const staleSameState=take('state','beta');
    epoch++; username=null; content.innerHTML='';
    epoch++; username='beta'; content.innerHTML='';
    staleSameState.resolve(account('beta'));
    await staleSame;
    assert(!byId('engine-dialog'),'Prior same-user session opened a dashboard dialog');
    const ack=document.createElement('button');
    ack.dataset.engineAck='beta-watch';ack.dataset.eventId='event';ack.dataset.isTest='false';content.append(ack);
    const delayedAck=EngineUI.click(ack);
    const pendingAck=take('/ack-signal','beta');
    switchAccount('alpha');
    pendingAck.reject(Error('private beta acknowledgement error'));
    await delayedAck;
    assert(!ack.isConnected,'Old acknowledgement remained mounted');

    const failures = [];
    const check = (condition, message) => { if (!condition) failures.push(message); };
    const flush = () => new Promise(resolve => setTimeout(resolve, 0));
    const openHolding = () => EngineUI.openHoldingStatus({key: 'position', ticker: 'ALPHA', label: 'Original'});
    const holding = watch => ({...account('alpha'), dashboard: {positions: [{
        key: 'position', ticker: 'ALPHA', hot_watch: watch
    }]}});
    window.TradeUI = {holdingActions: () => ''};
    window.DashboardUI = {watchLabel: () => 'Updated holding'};

    content.innerHTML = '';
    openHolding();
    const currentHolding = poll();
    take('state', 'alpha').resolve(holding({auto_status: {status: 'VERIFYING'}}));
    await currentHolding;
    assert(byId('engine-dialog').textContent.includes('Updated holding'), 'Current holding poll did not refresh');
    const failedLink = poll();
    take('state', 'alpha').resolve(holding({session: {watch_id: 'alpha-linked'}}));
    await flush();
    take('state', 'alpha').reject(Error('transient detail error'));
    await failedLink;
    assert(byId('engine-dialog').dataset.holdingKey === 'position' &&
        !byId('engine-dialog').dataset.watchId, 'Failed detail replaced holding identity');
    const currentLink = poll();
    take('state', 'alpha').resolve(holding({session: {watch_id: 'alpha-linked'}}));
    await flush();
    take('state', 'alpha').resolve(account('alpha'));
    await currentLink;
    assert(byId('engine-dialog').dataset.watchId === 'alpha-linked' &&
        !byId('engine-dialog').dataset.holdingKey, 'Current holding poll did not open linked detail');
    const externalPoll = poll;
    epoch++;
    const staleExternal = externalPoll();
    const externalState = pending.findIndex(request => request.path === 'state');
    if (externalState >= 0) pending.splice(externalState, 1)[0].resolve(account('alpha'));
    await staleExternal;
    check(externalState < 0, 'Old detail timer started a request during logout');

    for (const watch of [{auto_status: {status: 'VERIFYING'}}, {session: {watch_id: 'alpha-stale'}}]) {
        openHolding();
        const modal = byId('engine-dialog');
        const before = modal.innerHTML;
        const stalePoll = poll();
        const staleState = take('state', 'alpha');
        epoch++; // Logout starts while the dashboard and username are still present.
        staleState.resolve(holding(watch));
        await flush();
        const followUp = pending.findIndex(request => request.path === 'state');
        check(followUp < 0, 'Holding poll requested detail during logout');
        if (followUp >= 0) pending.splice(followUp, 1)[0].resolve(account('alpha'));
        await stalePoll;
        check(modal.innerHTML === before && !modal.dataset.watchId, 'Holding poll wrote to the dialog during logout');
    }

    switchAccount('alpha');
    await flush();
    const more = EngineUI.click(button(history));
    take('&before=', 'alpha').resolve({sessions: [session('alpha-older', 'COMPLETED')]});
    await more;
    const older = '[data-engine-detail="alpha-older"]';
    EngineUI.mount(false);
    await flush();
    assert(button(older), 'Same-session refresh lost paginated history');
    omitHistory = true;
    switchAccount(null);
    switchAccount('alpha');
    await flush();
    check(!button(older) && !button('[data-engine-detail="alpha-closed"]'), 'Relogin reused prior-session history');

    content.innerHTML = '';
    const sameAck = ack.cloneNode();
    sameAck.disabled = false;
    content.append(sameAck);
    const currentAck = click('[data-engine-ack]');
    take('/ack-signal', 'alpha').reject(Error('current acknowledgement error'));
    await currentAck;
    assert(!sameAck.disabled && byId('notice').textContent === 'current acknowledgement error',
        'Current acknowledgement error was hidden');
    const staleAck = click('[data-engine-ack]');
    const staleAckRequest = take('/ack-signal', 'alpha');
    epoch++; username = null; content.innerHTML = '';
    epoch++; username = 'alpha';
    byId('notice').textContent = 'relogin notice';
    staleAckRequest.reject(Error('prior-session acknowledgement error'));
    await staleAck;
    check(byId('notice').textContent === 'relogin notice', 'Prior-session acknowledgement error reached global notice');
    assert(!failures.length, failures.join(' | '));
};
window.testResult = run().then(() => 'PASS', error => String(error) + '\\n' + (error.stack || ''));
</script>
"""


def run_account_isolation():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 390, "height": 844}, is_mobile=True)
            page.route("**/*", lambda route: route.abort())
            page.set_content(browser_fixture())
            result = page.evaluate("window.testResult")
            assert result == "PASS", result
            print("PASS: 390px HOT WATCH account isolation")
        finally:
            browser.close()


if __name__ == "__main__":
    run_account_isolation()
