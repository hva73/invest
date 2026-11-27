const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { runInNewContext } = require('node:vm');

const window = {};
runInNewContext(readFileSync(require.resolve('../static/dashboard-ui.js'), 'utf8'), { window });
const { amount, profit, setup } = window.DashboardUI;
setup({ escape: String });
const money = (amount, currency = 'DKK') => ({ amount, currency });
const unknown = '<span class="dash-neutral">—</span>';

for (const value of ['0x10', '0b11', '0o10', true, [1], ' ', '1e999', null, undefined]) {
  assert.equal(amount(money(value)), '—');
  assert.equal(profit(money(value), 5), unknown);
  if (value == null) assert.doesNotMatch(profit(money(1), value), /<small/);
  else assert.match(profit(money(1), value), /<small class="dash-profit-percent neutral">—<\/small>$/);
}
for (const value of [null, {}, money(10, ''), money(-5, 'DK')]) {
  assert.equal(profit(value, -1), unknown);
}

for (const [raw, tone, prefix, pct, label] of [
  [0, 'neutral', '', 0, '0,00 %'],
  [' +.5e1 ', 'positive', '+', '+1.25', '+1,25 %'],
  ['-1.', 'negative', '', '-.25', '-0,25 %'],
]) {
  const formatted = new Intl.NumberFormat('da-DK', { style: 'currency', currency: 'DKK' }).format(Number(raw));
  assert.equal(profit(money(raw), pct),
    `<span class="dash-change ${tone}">${prefix}${formatted}</span><small class="dash-profit-percent ${tone}">${label}</small>`);
}
assert.equal(amount(money('1e-400')), '1e-400 DKK');
assert.equal(profit(money('-1e-400'), null), '<span class="dash-change neutral">-1e-400 DKK</span>');
