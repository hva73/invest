const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync(require.resolve('../static/dashboard-ui.js'), 'utf8');
const window = {};
vm.runInNewContext(source.replace('return {acknowledgeSignal,', 'return {mobileHoldings,acknowledgeSignal,'), {window});
window.DashboardUI.setup({escape: String});

function check(name, update, category, label, market) {
  const session = {
    status: 'ACTIVE', signal: 'SELL', display_status: 'SÆLGSSIGNAL',
    data_stale: false, display_freshness: {state: 'fresh'},
    data_status: {market_status: 'OPEN', price_status: 'FRESH', identity_verification: 'verified'},
    last_action_signal: {state: 'ACTIVE', event_type: 'SELL_SIGNAL'}
  };
  update(session);
  const html = window.DashboardUI.mobileHoldings([{verification: 'broker_snapshot', hot_watch: {session}}]);
  assert.ok(html.includes(`class="mobile-holding-status ${category}">${label}</small>`), name + ' status');
  assert.ok(html.includes(`class="mobile-holding-market">${market}</small>`), name + ' market');
}

check('verified active sale', () => {}, 'action', 'SÆLGSSIGNAL', '● Åbent');
check('unverified identity', s => { s.data_status.identity_verification = 'unverified'; }, 'other', 'Afventer data', '◯ Ukendt');
check('missing identity', s => { delete s.data_status.identity_verification; }, 'other', 'Afventer data', '◯ Ukendt');
check('stale data', s => { s.data_stale = true; }, 'other', 'Afventer data', '◯ Ukendt');
check('historical event', s => { s.last_action_signal.state = 'HISTORICAL'; }, 'other', 'Se status', '● Åbent');
check('mismatched event', s => { s.last_action_signal.event_type = 'BUY_SIGNAL'; }, 'other', 'Se status', '● Åbent');
console.log('PASS mobile holding identity, freshness and action event');
