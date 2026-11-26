"""Synthetic HOT WATCH races at 390px. Run with python3 tests/browser_mobile_account_isolation.py."""
from pathlib import Path


def browser_fixture():
    source = (Path(__file__).resolve().parents[1] / "static/engine-ui.js").read_text()
    # Exercise the retained report-candidate form without adding a production entry point.
    source = source.replace("return {openHoldingStatus,", "return {legacyCreation,openHoldingStatus,", 1)
    return """<!doctype html><meta name="viewport" content="width=device-width, initial-scale=1">
<button id="logout">Log ud</button><p id="notice"></p><div id="content"></div>
<script>""" + source + """
const content = document.getElementById('content');
const pending = [];
const userIds = {alpha: 11, beta: 22};
let username,epoch=0,failLogout;
let holdCurrentLoad=false,omitHistory=false,poll,pollSchedules=0,archiveFixture;
let archiveReads=0,clock=Date.now();
Date.now=()=>clock;
const logout = document.getElementById('logout');
// app.js advances the epoch synchronously and leaves the view mounted on failure.
logout.onclick = async () => {
    epoch++;
    await new Promise(resolve => { failLogout = resolve; });
};
const beginLogout = () => logout.onclick();
const finishFailedLogout = async transition => { failLogout(); await transition; };
// Run polling deterministically even when the browser fixture has no focused window.
Object.defineProperty(document, 'hidden', {value: false});
const realTimeout = window.setTimeout;
window.setTimeout = (callback, delay) => {
    if (delay === 15000) { poll = () => { clock += delay; return callback(); }; pollSchedules++; return null; }
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
    if (archiveFixture?.autoHistory && path.includes('view=history')) {
        if (path.includes('&before=')) archiveReads++;
        return Promise.resolve(archiveFixture.autoHistory(new URLSearchParams(path.split('?')[1])));
    }
    if (path === 'market/quote' || path === 'market/eodhd-symbols' || path === 'state' || path.includes('&before=') || path.endsWith('/pause') || path.endsWith('/ack-signal') || path.includes('/buy-plan?') || /manual-(search|start)/.test(path) || /sessions\/notification-/.test(path) || (holdCurrentLoad&&path.includes('view=current'))) {
        return new Promise((resolve, reject) => pending.push({path, args, user, resolve, reject}));
    }
    if (path.includes('/start-candidates')) return Promise.resolve({candidates: [0, 1].map(i => ({
        report_id: user + '-report',
        candidate: {candidate_id: user + '-' + i, ticker: user + i}
    }))});
    if (/\\/(samples|events)\\?/.test(path)) return Promise.resolve({items: []});
    if (/\\/sessions\\//.test(path)) return Promise.resolve({session: {
        watch_id: path.slice(path.lastIndexOf('/') + 1).split('?')[0],
        status: 'ACTIVE', signal: 'WAIT', request: {ticker: user, watch_mode: 'entry', portfolio_ids: []}
    }});
    if (archiveFixture && path.includes('view=current')) return Promise.resolve({
        sessions: archiveFixture.current.slice(0, 100), truncated: archiveFixture.current.length > 100, kill_switch: {}
    });
    if (archiveFixture && path.includes('view=history')) return Promise.resolve(archiveFixture.page());
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
    EngineUI.setup({api, owner: () => username, session: () => epoch, isAdmin: () => false, editing: () => false,
        escape: value => String(value ?? '').replace(/[&<>"']/g, ch => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
        })[ch]), formatTime: String});
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

    const findEodhd = () => EngineUI.click(form.querySelector('[data-engine-eodhd-search]'));
    const takeEodhd = () => take('market/eodhd-symbols', 'beta');
    const noEodhdPending = () => !pending.some(request => request.path === 'market/eodhd-symbols');
    const symbol = name => ({choices: [{symbol: name, name, isin: 'DK0000000001', currency: 'DKK'}]});
    form.elements.provider_symbol.value = 'OLD.CO';
    await EngineUI.change({target: form.elements.provider_symbol});
    const assetChoice = document.createElement('select');
    assetChoice.id = 'engine-asset-choice';
    assetChoice.add(new Option('Alternate listing', 'beta-alternate'));
    form.append(assetChoice);
    const oldListing = findEodhd();
    const oldListingRequest = takeEodhd();
    const newListing = EngineUI.change({target: assetChoice});
    const listingQuote = take('market/quote', 'beta');
    const duringVerification = findEodhd();
    const premature = pending.findIndex(request => request.path === 'market/eodhd-symbols');
    const prematureRequest = premature < 0 ? null : pending.splice(premature, 1)[0];
    listingQuote.resolve({asset_id: 'beta-alternate', currency: 'USD', exchange: 'XNYS', isin: 'US0000000001'});
    await newListing;
    const verifiedStatus = byId('engine-form-status').textContent;
    oldListingRequest.resolve(symbol('OLD.CO'));
    prematureRequest?.resolve(symbol('WRONG.CO'));
    await Promise.all([oldListing, duringVerification]);
    assert(!prematureRequest && !byId('engine-eodhd-select') && !form.elements.provider_symbol.value &&
        byId('engine-form-status').textContent === verifiedStatus && form.elements.asset_id.value === 'beta-alternate',
        'An EODHD lookup for the previous Pluto listing changed the verified form');
    const newSymbols = findEodhd();
    const newSymbolRequest = takeEodhd();
    assert(newSymbolRequest.args.quote_currency === 'USD', 'EODHD retried with the previous listing currency');
    newSymbolRequest.resolve({choices: [{symbol: 'FRESH.US', name: 'Alternate listing', isin: 'US0000000001', currency: 'USD'}]});
    await newSymbols;
    assert(byId('engine-eodhd-select').value === 'FRESH.US', 'The verified listing could not select its EODHD symbol');
    for (const [index, interrupt, outcome] of [
        [0, 'logout', 'success'], [1, 'logout', 'error'], [0, 'mode', 'success']
    ]) {
        const selection = select(index);
        take('market/quote', 'beta').resolve({...quote(), isin: 'DK0000000001'});
        await selection;
        const providerSymbol = form.elements.provider_symbol;
        providerSymbol.value = '';
        await EngineUI.change({target: providerSymbol});
        const obsolete = findEodhd();
        const oldRequest = takeEodhd();
        if (interrupt === 'logout') {
            const transition = beginLogout();
            await findEodhd();
            assert(noEodhdPending(), 'EODHD lookup started during logout');
            await finishFailedLogout(transition);
        } else {
            EngineUI.mount(true);
            EngineUI.mount(false);
        }
        assert(byId('engine-create') === form && form.closest('dialog').open, 'Candidate form was replaced');

        const retry = findEodhd();
        const currentRequest = takeEodhd();
        assert(currentRequest.args.candidate_id === oldRequest.args.candidate_id, 'Retry used a different candidate');
        const slot = byId('engine-eodhd-choice');
        if (outcome === 'success') {
            oldRequest.resolve(symbol('OBSOLETE.CO'));
            await obsolete;
            assert(slot.textContent === 'Søger hos EODHD …' && !form.elements.provider_symbol.value,
                'Obsolete EODHD response changed the pending retry');
        }
        const concurrent = findEodhd();
        assert(noEodhdPending(), 'Concurrent lookups sent duplicate requests for the current selection');
        currentRequest.resolve(symbol('FRESH.CO'));
        await Promise.all([retry, concurrent]);
        if (outcome === 'error') {
            oldRequest.reject(Error('Prior-session EODHD error'));
            await obsolete;
        }
        assert(byId('engine-eodhd-select').value === 'FRESH.CO' && form.elements.provider_symbol.value === 'FRESH.CO' &&
            byId('engine-form-status').textContent.includes('FRESH.CO'), 'Current EODHD result was lost or overwritten');
    }

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

    const searchManual = ticker => {
        const form = byId('engine-manual-search');
        form.elements.query.value = ticker;
        return EngineUI.submit({target: form, preventDefault(){}});
    };
    const resolveSearch = ticker => take('manual-search','beta').resolve({
        assets: [{asset_id: ticker, ticker, name: ticker + ' asset'}]
    });
    const manualResult = () => byId('engine-manual-results').querySelector('[data-engine-manual]');
    const manualStatus = () => byId('engine-manual-status').textContent;
    const sameForm = byId('engine-manual-search');
    const multipleResults = searchManual('Two listings');
    take('manual-search', 'beta').resolve({assets: [
        {asset_id: 'first-listing', ticker: 'FIRST'}, {asset_id: 'second-listing', ticker: 'SECOND'}
    ]});
    await multipleResults;
    const [firstResult, secondResult] = byId('engine-manual-results').querySelectorAll('[data-engine-manual]');
    const firstStart = EngineUI.click(firstResult);
    const firstRequest = take('manual-start', 'beta');
    const secondStart = EngineUI.click(secondResult);
    const duplicateStart = pending.some(request => request.path.includes('manual-start'));
    if (duplicateStart) take('manual-start', 'beta').reject(Error('Unexpected concurrent start'));
    await secondStart;
    firstRequest.reject(Error('First listing unavailable'));
    await firstStart;
    assert(!duplicateStart && firstRequest.args.asset_id === 'first-listing' &&
        manualStatus() === 'First listing unavailable', 'Two results started concurrently or lost the first result status');
    const alternateStart = EngineUI.click(secondResult);
    const alternateRequest = take('manual-start', 'beta');
    assert(alternateRequest.args.asset_id === 'second-listing', 'Another listing could not start after failure');
    alternateRequest.reject(Error('Second listing unavailable'));
    await alternateStart;

    for (const outcome of ['success', 'error']) {
        const searchA = searchManual('AAA');
        resolveSearch('AAA');
        await searchA;
        const startA = EngineUI.click(manualResult());
        const pendingA = take('manual-start','beta');
        assert(pendingA.args.asset_id === 'AAA', 'Wrong instrument sent to manual start');
        const searchB = searchManual('BBB');
        if (outcome === 'error') {
            pendingA.reject(Error('Old start failed'));
            await startA;
            assert(manualStatus() === 'Søger hos Pluto …', 'Old start error replaced pending search status');
        }
        resolveSearch('BBB');
        await searchB;
        const resultB = manualResult(), statusB = manualStatus();
        if (outcome === 'success') {
            const overlappingStart = EngineUI.click(resultB);
            const duplicate = pending.some(request => request.path.includes('manual-start'));
            if (duplicate) take('manual-start', 'beta').reject(Error('Unexpected start from a new search'));
            await overlappingStart;
            assert(!duplicate, 'Searching again bypassed the form start lock');
            pendingA.resolve({session:{watch_id:'aaa-watch'}});
            await new Promise(resolve=>setTimeout(resolve,0));
            assert(!pending.some(request => request.path === 'state'), 'Old start fetched instrument detail');
            await startA;
        }
        assert(byId('engine-manual-search') === sameForm && byId('engine-dialog').open,
            'Old start closed or replaced the same search form');
        assert(manualResult() === resultB && resultB.textContent.includes('BBB') &&
            !resultB.disabled && manualStatus() === statusB, 'Old start changed current search results');
    }
    const failedStart = EngineUI.click(manualResult());
    take('manual-start','beta').reject(Error('Current start failed'));
    await failedStart;
    assert(!manualResult().disabled && manualStatus() === 'Current start failed',
        'Current manual start failure cannot be retried');
    const startB = EngineUI.click(manualResult());
    const pendingB = take('manual-start','beta');
    assert(pendingB.args.asset_id === 'BBB', 'New search result did not start the selected instrument');
    pendingB.resolve({session:{watch_id:'bbb-watch'}});
    await new Promise(resolve=>setTimeout(resolve,0));
    take('state','beta').resolve(account('beta'));
    await startB;
    assert(byId('engine-dialog').dataset.watchId === 'bbb-watch', 'Current start did not open its detail');

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

    // Overview and Settings both render into content without an engine root.
    const overview = '<section class="dashboard-v1">Overview</section>';
    const settings = '<section class="push-settings">Settings</section>';
    const openDashboardDetail = async () => {
        try { await EngineUI.openDetail('beta-holding'); }
        catch (error) { byId('notice').textContent = error.message; }
    };
    for (const destination of ['Settings', 'Overview again']) {
        for (const rejected of [false, true]) {
            content.innerHTML = overview;
            const opening = openDashboardDetail();
            const stateRequest = take('state', 'beta');
            content.innerHTML = settings;
            if (destination === 'Overview again') content.innerHTML = overview;
            const destinationView = content.innerHTML;
            byId('notice').textContent = 'Destination notice';
            if (rejected) stateRequest.reject(Error('Late detail error'));
            else stateRequest.resolve(account('beta'));
            await opening;
            assert(content.innerHTML === destinationView && byId('notice').textContent === 'Destination notice',
                'Delayed detail ' + (rejected ? 'error' : 'success') + ' changed ' + destination);
        }
    }
    const currentDashboardError = openDashboardDetail();
    take('state', 'beta').reject(Error('Current detail error'));
    await currentDashboardError;
    assert(byId('notice').textContent === 'Current detail error', 'Current dashboard detail error was hidden');
    const currentDashboardDetail = openDashboardDetail();
    take('state', 'beta').resolve(account('beta'));
    await currentDashboardDetail;
    assert(byId('engine-dialog')?.dataset.watchId === 'beta-holding', 'Current dashboard detail did not open');

    // app.js replaces #content on every stored-data render and keeps the page title.
    const title = document.createElement('h1');
    title.id = 'title';
    content.before(title);
    const renderView = (name, html = overview) => {
        title.textContent = name;
        content.innerHTML = html;
    };
    window.MarketUI = {mount() {}};
    for (const requestType of ['detail', 'signal']) {
        const opening = () => requestType === 'detail'
            ? openDashboardDetail() : EngineUI.openNotification('notification-repaint');
        const settle = () => {
            if (requestType === 'signal') take('/sessions/notification-repaint', 'beta').resolve({
                session: session('notification-repaint')
            });
            return take('state', 'beta');
        };
        for (const destination of ['same view', 'Settings', 'Overview again']) {
            renderView('Dit overblik');
            if (destination === 'same view') {
                // A previously closed dialog is also removed by the repaint.
                await EngineUI.click({dataset: {engineNotice: JSON.stringify({
                    watch_id: 'other', last_action_signal: {event_id: 'other', event_type: 'BUY_SIGNAL'}
                })}});
                byId('engine-dialog').close();
            }
            const pendingOpen = opening();
            if (destination !== 'same view') renderView('Setup og forbindelser', settings);
            if (destination !== 'Settings') renderView('Dit overblik', overview.replace('Overview', 'Changed data'));
            settle().resolve(account('beta'));
            await pendingOpen;
            if (destination === 'same view') {
                assert(byId('engine-dialog')?.open, 'Dashboard ' + requestType + ' was lost after a same-view repaint');
            } else {
                assert(!byId('engine-dialog'), 'Dashboard ' + requestType + ' survived navigation to ' + destination);
            }
        }
    }
    title.remove();
    content.innerHTML = '';

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
    const dismiss = modal => {
        // requestClose follows the native cancel path used by Escape.
        if (modal.requestClose) {
            let cancelled = false;
            modal.addEventListener('cancel', () => { cancelled = true; }, {once: true});
            modal.requestClose();
            assert(cancelled, 'The browser did not dispatch cancel');
        } else modal.close();
        assert(!modal.open, 'The browser did not dismiss the dialog');
    };

    const signal = (event = 'event', is_test = false) => ({...session('alpha-watch'), is_test,
        last_action_signal: {event_id: event, event_type: 'BUY_SIGNAL', state: 'ACTIVE'}});
    const showSignals = (...sessions) => {
        content.innerHTML = sessions.map(EngineUI.actionNotice).join('');
        return [...content.querySelectorAll('[data-engine-notice]')];
    };
    const startAcknowledgement = async () => {
        const engine = byId('engine-root');
        const event = document.createElement('div');
        event.innerHTML = EngineUI.actionNotice(signal());
        engine.append(event);
        await EngineUI.click(event.firstElementChild);
        const confirmation = click('[data-engine-ack]');
        const request = take('/ack-signal', 'alpha');
        dismiss(byId('engine-dialog'));
        return {confirmation, request};
    };
    const unread = icon => icon.classList.contains('signal-alert--unread');
    switchAccount('alpha');
    const [firstNotice, secondNotice] = showSignals(signal('first-ack'), signal('second-ack'));
    await EngineUI.click(firstNotice);
    const firstButton = button('[data-engine-ack]');
    const confirmFirst = click('[data-engine-ack]');
    take('/ack-signal', 'alpha').resolve({acknowledged: true});
    await confirmFirst;
    await EngineUI.click(secondNotice);
    const secondButton = button('[data-engine-ack]');
    check(secondButton.isConnected && secondButton !== firstButton && !secondButton.disabled,
        'Opening another warning did not mount a fresh acknowledgement button');
    const confirmSecond = click('[data-engine-ack]');
    const duplicateAck = EngineUI.click(secondButton);
    take('/ack-signal', 'alpha').reject(Error('Current signal acknowledgement failed'));
    assert(!pending.some(request => request.path.endsWith('/ack-signal')), 'Concurrent acknowledgement issued a duplicate request');
    await Promise.all([confirmSecond, duplicateAck]);
    check(byId('engine-dialog').open && !secondButton.disabled && unread(secondNotice) &&
        byId('notice').textContent === 'Current signal acknowledgement failed', 'Current failure did not keep the alert open and retryable');
    const retrySecond = click('[data-engine-ack]');
    take('/ack-signal', 'alpha').resolve({acknowledged: true});
    await retrySecond;
    check(!byId('engine-dialog').open && !unread(secondNotice), 'Acknowledgement retry did not clear the alert');

    switchAccount('alpha');
    await flush();
    const obsoleteAcknowledgement = await startAcknowledgement();
    switchAccount(null);
    switchAccount('alpha');
    const [newSessionIcon] = showSignals(signal());
    obsoleteAcknowledgement.request.resolve({acknowledged: true});
    await obsoleteAcknowledgement.confirmation;
    check(unread(newSessionIcon), 'Acknowledgement crossed a same-user session change');

    switchAccount('alpha');
    await flush();
    const navigatingAcknowledgement = await startAcknowledgement();
    const [matchingIcon, newerIcon, testIcon] = showSignals(signal(), signal('newer-event'), signal('event', true));
    await EngineUI.click(newerIcon);
    navigatingAcknowledgement.request.resolve({acknowledged: true});
    await navigatingAcknowledgement.confirmation;
    check(!unread(matchingIcon) && unread(newerIcon) && unread(testIcon),
        'Acknowledgement after navigation did not update only the matching Overview event');
    check(byId('engine-dialog').open && byId('engine-dialog').querySelector('[data-event-id="newer-event"]'),
        'Acknowledgement after navigation closed a newer dialog');
    await EngineUI.click(matchingIcon);
    check(byId('engine-dialog').querySelector('[role=status]')?.textContent === 'Kvitteret',
        'Reopened Overview warning did not show confirmation');
    const [repaintedIcon] = showSignals(signal());
    check(!unread(repaintedIcon), 'An overlapping unread snapshot restored a confirmed acknowledgement');
    switchAccount('alpha');
    const [reloginIcon] = showSignals(signal());
    check(unread(reloginIcon), 'Same-user relogin reused the prior acknowledgement');

    for (const entry of ['HOT WATCH', 'dashboard']) {
        switchAccount('alpha');
        await flush();
        if (entry === 'dashboard') content.innerHTML = '';
        const opening = entry === 'dashboard' ? EngineUI.openDetail('alpha-watch') : open('alpha-watch');
        take('state', 'alpha').resolve(account('alpha'));
        await opening;
        const refreshing = poll();
        await flush();
        const delayedRefresh = take('state', 'alpha');
        const draft = byId('engine-buy-plan');
        const editor = draft.closest('details');
        editor.querySelector('summary').click();
        draft.elements.budget_dkk.value = '1250';
        delayedRefresh.resolve(account('alpha'));
        await refreshing;
        check(byId('engine-buy-plan') === draft && editor.open && draft.elements.budget_dkk.value === '1250',
            entry + ' detail poll erased the draft opened during its request');

        const activeForm = byId('engine-buy-plan');
        activeForm.closest('details').open = false;
        const afterEditing = poll();
        await flush();
        take('state', 'alpha').resolve(account('alpha'));
        await afterEditing;
        check(byId('engine-buy-plan') !== activeForm, entry + ' detail did not resume refreshing after editing');
    }

    for (const outcome of ['success', 'error']) {
        switchAccount('alpha');
        await flush();
        const opening = open('alpha-watch');
        take('state', 'alpha').resolve(account('alpha'));
        await opening;
        const modal = byId('engine-dialog');
        const next = click('[data-engine-detail="alpha-next"]');
        const delayed = take('state', 'alpha');
        dismiss(modal);
        byId('notice').textContent = 'Dismissed';
        if (outcome === 'success') delayed.resolve(account('alpha'));
        else delayed.reject(Error('Dismissed detail error'));
        await next;
        check(!modal.open && byId('notice').textContent === 'Dismissed',
            'Dismissed detail ' + outcome + ' updated the UI');

        const reopening = open('alpha-next');
        take('state', 'alpha').resolve(account('alpha'));
        await reopening;
        check(modal.open && modal.dataset.watchId === 'alpha-next', 'Fresh detail did not open after dismissal');
    }

    window.MarketUI = {mount() {}};
    for (const entry of ['notification', 'candidate form']) {
        await EngineUI.click(newButton());
        const modal = byId('engine-dialog');
        const opening = entry === 'notification' ? EngineUI.openNotification('notification-dismissed') : EngineUI.legacyCreation();
        const delayed = take('state', 'alpha');
        if (entry === 'notification') take('/sessions/notification-dismissed', 'alpha').resolve({session: session('dismissed')});
        dismiss(modal);
        delayed.resolve(account('alpha'));
        await flush();
        const quoteIndex = pending.findIndex(request => request.path === 'market/quote');
        if (quoteIndex >= 0) pending.splice(quoteIndex, 1)[0].resolve(quote());
        await opening;
        check(!modal.open && quoteIndex < 0, 'Dismissed ' + entry + ' reopened the dialog');
    }

    for (const outcome of ['current-error', 'current-success', 'stale-error', 'stale-success', 'closed-form', 'replaced-form']) {
        switchAccount('alpha');
        await flush();
        const opening = open('alpha-watch');
        take('state', 'alpha').resolve(account('alpha'));
        await opening;
        const form = byId('engine-buy-plan');
        const details = form.closest('details');
        details.open = true;
        const saving = EngineUI.submit({target: form, preventDefault() {}});
        const request = take('/buy-plan?', 'alpha');
        const before = details.innerHTML;
        const stale = !outcome.startsWith('current');
        const transition = outcome.startsWith('stale') ? beginLogout() : null;
        if (outcome === 'closed-form') await EngineUI.click(button('[data-engine-close]'));
        if (outcome === 'replaced-form') {
            const replacement = open('alpha-next');
            take('state', 'alpha').resolve(account('alpha'));
            await replacement;
        }
        if (outcome.endsWith('error')) request.reject(Error('Buy plan rejected'));
        else request.resolve({note: 'Buy plan saved'});
        await flush();
        const followUp = pending.findIndex(request => request.path === 'state');
        check((followUp >= 0) === (outcome === 'current-success'), outcome + ' unexpected buy-plan detail refresh');
        if (followUp >= 0) pending.splice(followUp, 1)[0].resolve(account('alpha'));
        await saving;
        if (stale) check(details.open && details.innerHTML === before, outcome + ' rewrote the old buy-plan form');
        else if (outcome.endsWith('error')) check(
            form.textContent.includes('Buy plan rejected') && !form.querySelector('button').disabled,
            'Current buy-plan error did not allow retry');
        else check(!details.open && byId('engine-buy-plan') !== form, 'Current buy plan did not refresh detail');
        if (transition) await finishFailedLogout(transition);
    }

    for (const phase of ['scheduled', 'in flight']) {
        switchAccount('alpha');
        await flush();
        const engine = byId('engine-root');
        const before = engine.innerHTML;
        const oldPoll = poll;
        holdCurrentLoad = true;
        const cycle = phase === 'in flight' ? oldPoll() : null;
        const transition = beginLogout();
        const pendingCycle = cycle || oldPoll();
        const requestIndex = pending.findIndex(request => request.path.includes('view=current'));
        check((requestIndex >= 0) === (phase === 'in flight'), 'Previously scheduled HOT WATCH poll sent a request during logout');
        if (requestIndex >= 0) pending.splice(requestIndex, 1)[0].resolve({
            sessions: [session('logout-poll')], kill_switch: {}
        });
        holdCurrentLoad = false;
        await pendingCycle;
        check(engine.innerHTML === before, phase + ' HOT WATCH poll repainted during logout');
        await finishFailedLogout(transition);
    }

    switchAccount('alpha');
    await flush();
    const oldPoll = poll;
    holdCurrentLoad = true;
    const oldCycle = oldPoll();
    const oldLoad = take('view=current', 'alpha');
    holdCurrentLoad = false;
    EngineUI.mount(false);
    await flush();
    const freshPoll = poll;
    oldLoad.resolve({sessions: [session('old-mount')], kill_switch: {}});
    await oldCycle;
    check(poll === freshPoll && !button('[data-engine-detail="old-mount"]'),
        'Old poll interfered with a fresh mount on the same root');
    await poll();
    check(button('[data-engine-detail="alpha-watch"]'), 'Fresh mount did not continue polling');

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
    const externalLogout = beginLogout();
    const staleExternal = externalPoll();
    const externalState = pending.findIndex(request => request.path === 'state');
    if (externalState >= 0) pending.splice(externalState, 1)[0].resolve(account('alpha'));
    await staleExternal;
    check(externalState < 0, 'Old detail timer started a request during logout');
    await finishFailedLogout(externalLogout);

    for (const watch of [{auto_status: {status: 'VERIFYING'}}, {session: {watch_id: 'alpha-stale'}}]) {
        openHolding();
        const modal = byId('engine-dialog');
        const before = modal.innerHTML;
        const stalePoll = poll();
        const staleState = take('state', 'alpha');
        const transition = beginLogout();
        staleState.resolve(holding(watch));
        await flush();
        const followUp = pending.findIndex(request => request.path === 'state');
        check(followUp < 0, 'Holding poll requested detail during logout');
        if (followUp >= 0) pending.splice(followUp, 1)[0].resolve(account('alpha'));
        await stalePoll;
        check(modal.innerHTML === before && !modal.dataset.watchId, 'Holding poll wrote to the dialog during logout');
        await finishFailedLogout(transition);
    }

    for (const interrupt of ['close', 'logout', 'replace']) {
        openHolding();
        const modal = byId('engine-dialog');
        const linking = poll();
        take('state', 'alpha').resolve(holding({session: {watch_id: 'alpha-linked'}}));
        await flush();
        const linkedState = take('state', 'alpha');
        if (interrupt === 'close') modal.close();
        const transition = interrupt === 'logout' ? beginLogout() : null;
        if (interrupt === 'replace') {
            EngineUI.openHoldingStatus({key: 'other', ticker: 'OTHER', label: 'Other holding'});
        }
        const before = modal.innerHTML;
        linkedState.resolve(account('alpha'));
        await linking;
        check(modal.open === (interrupt !== 'close') && modal.innerHTML === before && !modal.dataset.watchId,
            'Delayed linked detail rewrote holding after ' + interrupt);
        if (transition) await finishFailedLogout(transition);
    }

    switchAccount('alpha');
    await flush();
    for (const interrupt of ['mode', 'epoch']) {
        const stalePage = EngineUI.click(button(history));
        const stalePageRequest = take('&before=alpha-cursor', 'alpha');
        if (interrupt === 'mode') EngineUI.mount(true);
        if (interrupt === 'epoch') epoch++;
        EngineUI.mount(false);
        await flush();
        stalePageRequest.resolve({sessions: [session('alpha-stale-page', 'COMPLETED')]});
        await stalePage;
        check(!button('[data-engine-detail="alpha-stale-page"]') && button(history),
            'Stale history page survived a change of ' + interrupt);
    }
    const originalButton = button(history);
    const more = EngineUI.click(originalButton);
    const pageRequest = take('&before=alpha-cursor', 'alpha');
    await poll();
    assert(!originalButton.isConnected && button(history), 'Regular poll did not replace history button');
    const concurrent = EngineUI.click(button(history));
    const duplicate = pending.findIndex(request => request.path.includes('&before='));
    check(duplicate < 0, 'Repaint started duplicate history request');
    if (duplicate >= 0) pending.splice(duplicate, 1)[0].resolve({sessions: []});
    await concurrent;
    pageRequest.resolve({sessions: [session('alpha-older', 'COMPLETED')], next_cursor: 'older-cursor'});
    await more;
    const older = '[data-engine-detail="alpha-older"]';
    check(button(older) && document.querySelector('[data-engine-group="history"]').open,
        'Same-session repaint dropped the pending history page');
    await poll();
    check(button(older), 'Same-session refresh lost paginated history');
    const lastPage = EngineUI.click(button(history));
    const lastRequest = take('&before=', 'alpha');
    check(lastRequest.path.endsWith('&before=older-cursor'), 'Refresh reset the advanced history cursor');
    lastRequest.resolve({sessions: [], next_cursor: null});
    await lastPage;
    await poll();
    check(!button(history), 'Refresh restored pagination after the last page');

    const initialHistory = [];
    archiveFixture = {
        current: [],
        autoHistory: () => new Promise((resolve, reject) => initialHistory.push({resolve, reject}))
    };
    const historyError = () => byId('engine-root').textContent.includes('Historikken kunne ikke hentes');
    const emptyList = () => Boolean(button('.engine-no-sessions'));
    switchAccount('alpha');
    await flush();
    assert(initialHistory.length === 1, 'The initial archive request was not started');
    check(!emptyList(), 'The list reported no watches while initial history was pending');
    initialHistory.shift().reject(Error('Synthetic initial archive failure'));
    await flush();
    check(historyError() && !emptyList(), 'An initial archive failure was reported as an empty watch list');

    const currentDuringArchiveFailure = '[data-engine-detail="current-during-archive-failure"]';
    archiveFixture.current = [session('current-during-archive-failure')];
    await poll();
    check(button(currentDuringArchiveFailure) && historyError() && initialHistory.length === 0,
        'Archive failure blocked current watches or retried before backoff');
    await poll();
    assert(initialHistory.length === 1, 'The initial archive request was not retried');
    initialHistory.shift().resolve({sessions: [session('recovered-archive', 'COMPLETED')]});
    await flush();
    check(!historyError() && button(currentDuringArchiveFailure) && button('[data-engine-detail="recovered-archive"]'),
        'A successful archive retry did not restore history alongside current watches');

    archiveFixture.current = [];
    switchAccount('beta');
    await flush();
    assert(initialHistory.length === 1, 'The new account did not request its own archive');
    const staleInitialHistory = initialHistory.shift();
    switchAccount('alpha');
    await flush();
    staleInitialHistory.reject(Error('Obsolete beta archive failure'));
    await flush();
    check(!historyError() && !emptyList(), 'An archive failure from the previous account changed the new account');
    assert(initialHistory.length === 1, 'The archive request did not restart after switching accounts');
    initialHistory.shift().resolve({sessions: []});
    await flush();
    check(!historyError() && emptyList(), 'Empty current and archive results did not show the empty state');

    const newest = session('alpha-loaded-41');
    const loaded = Array.from({length: 40}, (_, index) => session('alpha-loaded-' + (40 - index), 'COMPLETED'));
    const orderedArchive = [...loaded];
    const pageCursors = [];
    archiveFixture = {
        current: [newest],
        autoHistory(params) {
            const before = Number(params.get('before'));
            const limit = Number(params.get('limit'));
            if (before) pageCursors.push(before);
            const remaining = orderedArchive.filter(s => !before || Number(s.watch_id.split('-').at(-1)) < before);
            const rows = remaining.slice(0, limit);
            return {sessions: rows, next_cursor: remaining.length > limit ? Number(rows.at(-1).watch_id.split('-').at(-1)) : null};
        }
    };
    switchAccount('alpha');
    await flush();
    await click(history);
    const historyGroup = '[data-engine-group="history"]';
    const archivedIds = () => [...document.querySelectorAll(historyGroup + ' .engine-list-identity')]
        .map(row => row.dataset.engineDetail);
    assert(archivedIds().length === 40 && !button(history), 'Fixture did not load all 40 archived watches');
    archiveFixture.current = [];
    orderedArchive.unshift({...newest, status: 'EXPIRED'});
    await poll();
    const retained = archivedIds();
    check(retained.length === 41 && retained[0] === newest.watch_id && loaded.every(s => retained.includes(s.watch_id)) &&
        document.querySelector(historyGroup).open, 'A new archive cursor discarded loaded rows or collapsed history');
    check(button(history), 'History did not expose the refreshed first-page cursor');
    if (button(history)) {
        await click(history);
        check(pageCursors.join(',') === '21,22' && archivedIds().length === 41,
            'Pagination used the obsolete cursor or duplicated loaded rows');
        if (button(history)) await click(history);
        check(archivedIds().length === 41 && !button(history), 'Refreshed pagination did not reach the end');
    }
    archiveFixture = null;
    EngineUI.mount(true);
    await flush();
    check(!archivedIds().some(id => id.startsWith('alpha-loaded-')), 'Changing mode reused loaded live archive rows');

    const oldest = session('alpha-oldest');
    const secondOldest = session('alpha-older-active');
    const closed = Array.from({length: 21}, (_, index) => session('alpha-archive-' + (22 - index), 'COMPLETED'));
    archiveFixture = {
        current: [oldest, secondOldest],
        page(offset = 0) {
            const next = offset + 20;
            return {sessions: closed.slice(offset, next), next_cursor: next < closed.length ? 3 - offset : null};
        }
    };
    switchAccount('alpha');
    await flush();
    const readArchivePage = async () => {
        const paging = click(history);
        take('&before=3', 'alpha').resolve(archiveFixture.page(20));
        await paging;
    };
    await readArchivePage();
    await poll();
    check(!button(history), 'Unchanged archive exposed an exhausted cursor');
    archiveFixture.current = [secondOldest];
    closed.push({...oldest, status: 'COMPLETED'});
    await poll();
    check(button(history), 'Archiving an older watch did not restore history pagination');
    check(button('[data-engine-group=history] [data-engine-detail="alpha-archive-2"]'),
        'Reopening pagination discarded the already loaded last page');
    if (button(history)) {
        const obsoletePage = click(history);
        const obsoleteRequest = take('&before=3', 'alpha');
        const obsoleteResult = archiveFixture.page(20);
        archiveFixture.current = [];
        closed.splice(-1, 0, {...secondOldest, status: 'EXPIRED'});
        await poll();
        obsoleteRequest.resolve(obsoleteResult);
        await obsoletePage;
        check(button(history), 'An in-flight page restored the exhausted cursor after a new archive');
        if (button(history)) await readArchivePage();
        const archived = '[data-engine-group=history] [data-engine-detail="alpha-oldest"]';
        check(button(archived) && button('[data-engine-group=history] [data-engine-detail="alpha-older-active"]') &&
            !button(history), 'Newly archived watches were missing from the last page');
        await poll();
        check(button(archived) && !button(history), 'Poll lost the newly archived watch or reset pagination');
    }
    archiveFixture = null;

    const cappedCurrent = Array.from({length: 101}, (_, index) => session('current-' + index));
    const stableArchive = Array.from({length: 21}, (_, index) => session('archived-' + index, 'COMPLETED'));
    archiveFixture = {
        current: cappedCurrent,
        autoHistory: params => params.has('before')
            ? {sessions: stableArchive.slice(20), next_cursor: null, truncated: false}
            : {sessions: stableArchive.slice(0, 20), next_cursor: 150, truncated: true}
    };
    switchAccount('alpha');
    await flush();
    await click(history);
    const loadedArchiveRow = '[data-engine-detail="archived-20"]';
    const readsAfterPaging = archiveReads;
    await poll();
    check(archiveReads === readsAfterPaging, 'An unchanged capped poll refetched the loaded archive tail');
    cappedCurrent.unshift(session('new-current'));
    await poll();
    check(button('[data-engine-detail="new-current"]') && !button('[data-engine-detail="current-99"]'),
        'The capped fixture did not displace an open watch');
    check(button(loadedArchiveRow) && !button(history), 'A cap displacement reset unchanged archive pagination');
    const readsAfterDisplacement = archiveReads;
    await poll();
    check(archiveReads === readsAfterDisplacement && button(loadedArchiveRow),
        'Regular polling did not reuse the paginated archive');

    const stableHistory = archiveFixture.autoHistory;
    let failArchive, tailReads = 0;
    archiveFixture.autoHistory = params => {
        if (params.has('before') && ++tailReads === 1) {
            return new Promise((_, reject) => { failArchive = reject; });
        }
        return stableHistory(params);
    };
    clock += 30000;
    cappedCurrent[0] = {...cappedCurrent[0], signal: 'SELL', display_status: 'SÆLGSSIGNAL'};
    const archivePoll = poll();
    await flush();
    const freshSignal = '[data-engine-signal=SELL] [data-engine-detail="new-current"]';
    check(failArchive && button(freshSignal), 'A pending archive tail blocked fresh current signals');
    check(button(loadedArchiveRow) && !button(history), 'A pending archive tail discarded loaded history');
    cappedCurrent[0] = {...cappedCurrent[0], signal: 'BUY', display_status: 'KØBSSIGNAL'};
    await poll();
    check(button('[data-engine-signal=BUY] [data-engine-detail="new-current"]'),
        'A pending archive tail blocked the next current poll');
    failArchive?.(Error('Synthetic archive read failure'));
    await archivePoll;
    await flush();
    await poll();
    check(tailReads === 1 && button(loadedArchiveRow) && !button(history),
        'Archive tail failure discarded history or was retried on the next tick');
    await poll();
    check(tailReads === 2 && button(loadedArchiveRow), 'Archive tail did not recover on the next scheduled retry');

    let failHead;
    archiveFixture.autoHistory = params => params.has('before') ? stableHistory(params)
        : new Promise((_, reject) => { failHead = reject; });
    cappedCurrent[0] = {...cappedCurrent[0], signal: 'WAIT', display_status: 'AFVENT'};
    await poll();
    check(failHead && button('[data-engine-signal=WAIT] [data-engine-detail="new-current"]') &&
        button(loadedArchiveRow), 'A pending first archive page blocked current signals or hid loaded history');
    failHead?.(Error('Synthetic first-page failure'));
    await flush();
    check(button(loadedArchiveRow) && !button(history), 'A failed first archive page discarded cached pagination');

    let releaseHead;
    archiveFixture.autoHistory = () => new Promise(resolve => { releaseHead = resolve; });
    clock += 30000;
    await poll();
    assert(releaseHead, 'The archive head was not retried after backoff');
    archiveFixture = null;
    switchAccount('beta');
    await flush();
    check(button('[data-engine-detail="beta-closed"]'), 'A delayed alpha archive blocked beta history');
    releaseHead({sessions: [session('alpha-obsolete-archive', 'COMPLETED')]});
    await flush();
    check(!button('[data-engine-detail="alpha-obsolete-archive"]') && button('[data-engine-detail="beta-closed"]'),
        'A delayed alpha archive changed beta history');

    for (const [currentCount, archiveCount, delayPage, delayProbe] of [
        [101, 21, false, false], [102, 141, false, false], [101, 21, true, false], [101, 21, false, true]
    ]) {
        const current = Array.from({length: currentCount}, (_, index) => ({
            id: 500 - index, ...session('capped-current-' + index)
        }));
        const expired = current.at(-1);
        const archived = Array.from({length: archiveCount}, (_, index) => ({
            id: 300 - 2 * index, ...session('capped-archive-' + index, 'COMPLETED')
        }));
        // Insert outside the first page and, for deep history, inside the last loaded page.
        const insertion = archiveCount === 21 ? 21 : 130;
        expired.id = 301 - 2 * insertion;
        let finishPage, finishProbe, holdProbe = false;
        archiveFixture = {
            current,
            autoHistory(params) {
                const before = Number(params.get('before')) || Infinity;
                const limit = Number(params.get('limit'));
                const rows = archived.filter(row => row.id < before).slice(0, limit + 1);
                const truncated = rows.length > limit;
                const result = {
                    sessions: rows.slice(0, limit).map(({id, ...row}) => row),
                    next_cursor: truncated ? rows[limit - 1].id : null, truncated
                };
                if (delayPage && before !== Infinity && !finishPage) {
                    return new Promise(resolve => { finishPage = () => resolve(result); });
                }
                if (holdProbe && before !== Infinity) {
                    return new Promise(resolve => { finishProbe = () => resolve(result); });
                }
                return result;
            }
        };
        switchAccount('alpha');
        await flush();
        const expiredButton = '[data-engine-detail="' + expired.watch_id + '"]';
        assert(!button(expiredButton), 'Capped fixture exposed the oldest current watch');
        const pages = Math.ceil(archiveCount / 20) - 1;
        const readPages = async () => {
            for (let i = 0; i < pages; ++i) await click(history);
        };
        const firstPage = delayPage && click(history);
        if (!delayPage) {
            await readPages();
            assert(!button(history), 'Capped fixture did not exhaust history');
            await poll();
            check(!button(history), 'Unchanged capped current list reopened exhausted history');
        }
        if (delayProbe) {
            holdProbe = true;
            clock += 30000;
            await poll();
            assert(finishProbe, 'No pending background archive check');
            holdProbe = false;
        }
        current.pop();
        archived.splice(insertion, 0, {...expired, status: 'EXPIRED'});
        if (delayPage) {
            await poll();
            finishPage();
            await firstPage;
        }
        if (delayProbe) {
            await poll();
            finishProbe();
            await flush();
        }
        await poll();
        await flush();
        check(button(history), 'An unseen watch expiring with ' + currentCount + ' current watches did not restore pagination');
        check(button('[data-engine-group=history] [data-engine-detail="capped-archive-20"]'),
            'Revalidating a capped archive discarded loaded rows');
        if (button(history)) await readPages();
        check(button('[data-engine-group=history] ' + expiredButton) && !button(history),
            'An unseen expired watch was missing from the reopened last page');
        await poll();
        check(button(expiredButton) && !button(history), 'Capped refresh lost the expired watch after pagination');
    }
    archiveFixture = null;

    const largeCurrent = Array.from({length: 101}, (_, i) => session('large-current-' + i));
    const largeArchive = Array.from({length: 520}, (_, i) => ({
        id: 2000 - 2 * i, ...session('large-archive-' + i, 'COMPLETED')
    }));
    const archiveRequests = [];
    archiveFixture = {
        current: largeCurrent,
        autoHistory(params) {
            const before = Number(params.get('before')) || Infinity;
            const limit = Number(params.get('limit'));
            archiveRequests.push({before, limit});
            const rows = largeArchive.filter(row => row.id < before).slice(0, limit + 1);
            return {sessions: rows.slice(0, limit), next_cursor: rows.length > limit ? rows[limit - 1].id : null};
        }
    };
    switchAccount('alpha');
    await flush();
    for (let i = 1; i < 26; ++i) await click(history);
    assert(archivedIds().length === 520 && !button(history), 'Large archive fixture did not exhaust history');
    archiveRequests.length = 0;
    for (let tick = 0; tick < 4; ++tick) {
        const previousReads = archiveRequests.length;
        await poll();
        await flush();
        const reads = archiveRequests.slice(previousReads);
        check(reads.length === 1 && reads[0].limit === 20,
            'Capped background poll exceeded the original 20-row archive read');
        check(archivedIds().length === 520 && !button(history), 'Unchanged capped poll disturbed the loaded archive');
    }
    const probeCursors = archiveRequests.filter(request => Number.isFinite(request.before)).map(request => request.before);
    check(new Set(probeCursors).size >= 2, 'Background checks never progressed beyond one archive page');
    archiveFixture = null;

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
    for (const phase of ['scheduled', 'in flight']) {
        switchAccount('alpha');
        await flush();
        const engine = byId('engine-root');
        const before = engine.innerHTML;
        holdCurrentLoad = true;
        const oldSchedule = pollSchedules;
        const oldCycle = phase === 'in flight' ? poll() : null;
        const oldList = oldCycle && take('view=current', 'alpha');
        if (oldCycle) {
            await poll();
            assert(!pending.some(request => request.path.includes('view=current')),
                'HOT WATCH started a duplicate poll in the same epoch');
        }
        const transition = beginLogout();
        if (oldCycle) {
            await flush();
            assert(pollSchedules > oldSchedule, 'Polling waited for the obsolete request to settle');
        }
        const waiting = poll();
        assert(!pending.some(request => request.path.includes('view=current')), 'HOT WATCH read during pending logout');
        await waiting;
        check(!pending.some(request => request.path.includes('view=current')) && engine.innerHTML === before,
            'HOT WATCH read or wrote while logout was pending');
        await finishFailedLogout(transition);
        const recovered = poll();
        take('view=current', 'alpha').resolve({sessions: [session('recovered')], kill_switch: {}});
        await recovered;
        oldList?.resolve({sessions: [session('obsolete')], kill_switch: {}});
        await oldCycle;
        holdCurrentLoad = false;
        check(button('[data-engine-detail="recovered"]') && !button('[data-engine-detail="obsolete"]'),
            'HOT WATCH polling did not recover cleanly after failed logout');
    }

    for (const [operation, outcome] of [
        ['buy plan', 'error while pending'], ['buy plan', 'error after retry'],
        ['manual start', 'error while pending'], ['manual start', 'success after retry']
    ]) {
        switchAccount('alpha');
        await flush();
        let form, start, path;
        if (operation === 'buy plan') {
            const opening = open('alpha-watch');
            take('state', 'alpha').resolve(account('alpha'));
            await opening;
            form = byId('engine-buy-plan');
            form.closest('details').open = true;
            start = () => EngineUI.submit({target: form, preventDefault() {}});
            path = '/buy-plan?';
        } else {
            await EngineUI.click(newButton());
            form = byId('engine-manual-search');
            form.elements.query.value = 'ALPHA';
            const search = EngineUI.submit({target: form, preventDefault() {}});
            take('manual-search', 'alpha').resolve({assets: [{asset_id: 'alpha-id', ticker: 'ALPHA'}]});
            await search;
            start = () => EngineUI.click(manualResult());
            path = 'manual-start';
        }
        const actionButton = operation === 'buy plan' ? form.querySelector('button') : manualResult();
        const status = operation === 'buy plan' ? form.querySelector('[role=status]') : byId('engine-manual-status');
        const previousStatus = status.textContent;
        const obsolete = start();
        const old = take(path, 'alpha');
        const pendingStatus = status.textContent;
        const transition = beginLogout();
        if (outcome === 'error while pending') {
            old.reject(Error('Obsolete ' + operation + ' error'));
            await obsolete;
            check(actionButton.disabled && status.textContent === pendingStatus,
                'Obsolete ' + operation + ' error changed the pending form');
        }
        await finishFailedLogout(transition);
        check(actionButton.isConnected && !actionButton.disabled && status.textContent === previousStatus,
            'Failed logout left ' + operation + ' stuck');
        const retry = start();
        const current = take(path, 'alpha');
        const retryStatus = status.textContent;
        if (outcome === 'error after retry') old.reject(Error('Obsolete ' + operation + ' error'));
        if (outcome === 'success after retry') old.resolve({session: {watch_id: 'obsolete-start'}});
        await obsolete;
        check(byId('engine-dialog').open && actionButton.disabled && status.textContent === retryStatus &&
            !pending.some(request => request.path === 'state'), 'Obsolete ' + operation + ' disturbed its retry');
        current.reject(Error('Current ' + operation + ' error'));
        await retry;
        check(!actionButton.disabled && status.textContent === 'Current ' + operation + ' error',
            'Current ' + operation + ' retry did not report its error');
    }

    content.innerHTML = '';
    openHolding();
    const obsoleteHolding = poll();
    const obsoleteHoldingState = take('state', 'alpha');
    const holdingLogout = beginLogout();
    await finishFailedLogout(holdingLogout);
    obsoleteHoldingState.resolve(holding({session: {watch_id: 'obsolete-holding'}}));
    await obsoleteHolding;
    assert(!pending.some(request => request.path === 'state'), 'Obsolete holding poll started a detail read');
    check(byId('engine-dialog').textContent.includes('Original'), 'Obsolete holding poll wrote after failed logout');

    const linked = poll();
    take('state', 'alpha').resolve(holding({session: {watch_id: 'alpha-recovered'}}));
    await flush();
    take('state', 'alpha').resolve(account('alpha'));
    await linked;
    const dialog = byId('engine-dialog');
    assert(dialog.dataset.watchId === 'alpha-recovered', 'Holding polling did not recover after failed logout');

    const ackButton = sameAck.cloneNode();
    ackButton.disabled = false;
    dialog.append(ackButton);
    const beforeLogoutAck = click('[data-engine-ack]');
    const obsoleteAck = take('/ack-signal', 'alpha');
    const ackLogout = beginLogout();
    const waitingAck = EngineUI.click(ackButton);
    assert(!pending.some(request => request.path.endsWith('/ack-signal')), 'Acknowledgement posted during logout');
    await waitingAck;
    await poll();
    check(!pending.some(request => request.path === 'state'), 'External detail polled during logout');
    await finishFailedLogout(ackLogout);
    assert(!ackButton.disabled, 'Failed logout kept acknowledgement disabled until its old request settled');
    const retry = click('[data-engine-ack]');
    const retryAck = take('/ack-signal', 'alpha');
    obsoleteAck.reject(Error('obsolete acknowledgement error'));
    await beforeLogoutAck;
    check(ackButton.disabled && byId('notice').textContent === 'relogin notice',
        'Obsolete acknowledgement disturbed the retry');
    retryAck.reject(Error('retry acknowledgement error'));
    await retry;
    check(!ackButton.disabled && byId('notice').textContent === 'retry acknowledgement error',
        'Current retry could not report its error');

    const external = poll();
    take('state', 'alpha').resolve(account('alpha'));
    await external;
    check(dialog.open && !ackButton.isConnected && dialog.dataset.watchId === 'alpha-recovered',
        'External detail polling did not recover after failed logout');

    const modeSignal = is_test => ({
        ...session(is_test ? 'test-alert' : 'live-alert'), is_test,
        last_action_signal: {event_id: 'mode-event', event_type: 'SELL_SIGNAL', state: 'ACTIVE'}
    });
    archiveFixture = {current: [modeSignal(false)], page: () => ({sessions: []})};
    switchAccount('alpha');
    await flush();
    const alert = () => button('#engine-root [data-engine-notice]');
    const liveAlert = alert();
    assert(liveAlert, 'Missing the live alert before switching modes');
    holdCurrentLoad = true;
    EngineUI.mount(true);
    const testLoad = take('is_test=true', 'alpha');
    check(!alert(), 'Switching to Testdata left a live alert visible while the test list loaded');
    await EngineUI.click(liveAlert);
    check(!document.querySelector('#engine-dialog[open]'), 'An obsolete live alert opened in Testdata');
    holdCurrentLoad = false;
    testLoad.resolve({sessions: [modeSignal(true)], kill_switch: {}});
    await flush();
    await EngineUI.click(alert());
    const testAcknowledgement = EngineUI.click(button('[data-engine-ack]'));
    const testAck = take('/ack-signal', 'alpha');
    check(testAck.path.includes('/test-alert/') && testAck.args.is_test === true,
        'The new mode did not acknowledge its own alert');
    testAck.resolve({});
    await testAcknowledgement;
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
