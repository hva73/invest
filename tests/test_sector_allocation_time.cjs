const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../static/sector-ui.js'), 'utf8');
const now = '2026-11-27T12:00:00Z';
const future = '2026-11-27T07:00:00.001-05:00';
const earlier = '2026-11-27T14:30:00+03:00';
const unknown = 'Tidspunktet for fordelingen er ukendt.';
const partial = ' · tidspunkt mangler for dele af fordelingen';
const updated = 'Fordelingens datagrundlag: opdateret 27.11.2026, 13.00.00';
const range = 'Fordelingens datagrundlag: ældste 27.11.2026, 12.30.00 · seneste 27.11.2026, 13.00.00';

for (const [name, cashTime, positionTimes, expected] of [
  ['future cash and position', future, [future], unknown],
  ['future fractional second', '2026-11-27T12:00:00.000001Z', [future], unknown],
  ['missing evidence', undefined, [null], unknown],
  ['malformed evidence', '0', ['invalid', '2026-02-30T09:00:00Z'], unknown],
  ['one valid instant and future cash', future, [now], updated + partial + '.'],
  ['mixed evidence', now, ['2026-11-28T12:00:00Z', undefined, earlier, 'invalid'], range + partial + '.'],
  ['valid offsets in chronological order', earlier, ['2026-11-27T07:00:00-05:00'], range + '.'],
  ['equivalent instants at the clock boundary', now, ['2026-11-27T13:00:00.000000+01:00'], updated + '.'],
]) {
  test(name, async () => {
    const context = {window: {}, document: {addEventListener() {}},
      Date: class extends Date { static now() { return Date.parse(now); } }};
    vm.runInNewContext(source, context);
    const money = amount => ({amount, currency: 'DKK'});
    const dashboard = {
      accounts: [{id: 1, cash_status: 'available', cash_accounts: [money(50)], snapshot_at: cashTime}],
      positions: positionTimes.map(snapshot_at => ({portfolio_id: 1, value: money(100), snapshot_at})),
    };
    const ui = context.window.SectorUI;
    const loaded = new Promise(refresh => ui.setup({api: async () => ({dashboard, regions: ['USA'], markets: []}), escape: String, refresh}));
    const state = {user: {username: 'fixture'}};
    ui.render(state);
    await loaded;
    const html = ui.render(state);
    const allocation = html.split('class="panel sector-panel si-allocation"')[1].split('class="si-winners"')[0];
    assert.equal(allocation.match(/<p class="si-chart-note">([^<]*)<\/p>/)?.[1], expected);
    const total = money(50 + 100 * positionTimes.length);
    const formatted = new Intl.NumberFormat('da-DK', {style: 'currency', currency: total.currency}).format(total.amount);
    assert.ok(allocation.includes('<strong>' + formatted + '</strong>'));
  });
}
