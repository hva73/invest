const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { test } = require('node:test');

const source = fs.readFileSync(require.resolve('../static/dashboard-ui.js'), 'utf8');
const invalid = [' \t', true, false, '0x10', '0b11', '0o10', [], [2], {}, '2x', '1e999', Infinity, NaN, '', null, undefined];
const samples = [
  ['usd', ' 1e1 ', 'USD'],
  ...invalid.map((value, index) => ['missing' + index, value, index % 2 ? 'USD' : 'DKK']),
  ['zero', 0, 'DKK'],
  ['negative', '-.5', 'USD'],
  ['tie', '+10.0', 'USD'],
  ['high', 20, 'DKK'],
];
const missingKeys = invalid.map((_, index) => 'missing' + index);

for (const key of ['price', 'value', 'pnl', 'since', 'daily']) {
  test(key + ' keeps invalid evidence last in both directions', async () => {
    const positions = samples.map(([id, sample, currency]) => {
      const money = { amount: sample, currency };
      const row = { key: id, ticker: id, portfolio_id: 1, unrealized: { amount: 1, currency } };
      if (key === 'price' || key === 'value') row[key] = money;
      else if (key === 'pnl') row.unrealized_percent = sample;
      else row[key === 'since' ? 'since_last' : 'daily'] = { percent: sample };
      return row;
    });
    const panel = { dataset: { dashboardPortfolio: '1' } };
    const context = { window: {}, document: { querySelector: s => s === '.dash-holdings' ? panel : null } };
    vm.runInNewContext(source, context);
    const ui = context.window.DashboardUI;
    ui.setup({ state: () => ({ dashboard: { positions } }), escape: String, formatTime: String, formatQuantity: String });
    const grouped = key === 'price' || key === 'value';
    const descending = grouped ? ['high', 'zero', 'usd', 'tie', 'negative'] : ['high', 'usd', 'tie', 'zero', 'negative'];
    const ascending = grouped ? ['zero', 'high', 'negative', 'usd', 'tie'] : ['negative', 'zero', 'usd', 'tie', 'high'];
    const renderedKeys = () => Array.from(panel.outerHTML.matchAll(/data-dashboard-key="([^"]+)"/g), m => m[1]);
    ui.changeSort({ target: { id: 'dashboard-sort', value: key } });
    assert.deepEqual(renderedKeys(), descending.concat(missingKeys));
    await ui.click({ dataset: { dashboardSort: key } });
    assert.deepEqual(renderedKeys(), ascending.concat(missingKeys));
  });
}
