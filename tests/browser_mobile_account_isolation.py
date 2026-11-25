"""Synthetic HOT WATCH races at 390px. Run with python3 tests/browser_mobile_account_isolation.py."""
from pathlib import Path


def browser_fixture():
    source = (Path(__file__).resolve().parents[1] / "static/engine-ui.js").read_text()
    # Exercise the retained report-candidate form without adding a production entry point.
    source = source.replace("return {openHoldingStatus,", "return {legacyCreation,openHoldingStatus,", 1)
    return """<!doctype html><meta name="viewport" content="width=device-width, initial-scale=1">
<div id="content"></div>
<script>""" + source + """
const content = document.getElementById('content');
const pending = [];
const userIds = {alpha: 11, beta: 22};
let username;
const assert = (condition, message) => { if (!condition) throw Error(message); };
const byId = id => document.getElementById(id);
const api = (path, args) => {
    const user = username;
    if (path === 'market/quote' || path === 'state' || /manual-search/.test(path)) {
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
    EngineUI.setup({api, owner: () => username, isAdmin: () => false, editing: () => false,
        escape: value => String(value ?? ''), formatTime: String});
    switchAccount('alpha');
    const alpha = await create('alpha');
    const staleDetail = EngineUI.openDetail('alpha-watch');
    const alphaDetail = take('state', 'alpha');
    const staleError = EngineUI.openDetail('alpha-error-watch');
    const alphaError = take('state', 'alpha');
    switchAccount(null);
    switchAccount('beta');

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

    // Confirm the ordinary detail entry point still displays the current account's depot.
    const detail = EngineUI.openDetail('beta-watch');
    take('state', 'beta').resolve(account('beta'));
    await detail;
    assert(byId('engine-buy-plan').elements.portfolio_id.value === '22', 'Fresh detail lost beta depot');
};
window.testResult = run().then(() => 'PASS', error => String(error) + '\\n' + (error.stack || ''));
</script>
"""


if __name__ == "__main__":
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
