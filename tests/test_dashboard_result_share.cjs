const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { runInNewContext } = require('node:vm');

const window = {};
runInNewContext(readFileSync(require.resolve('../static/dashboard-ui.js'), 'utf8'), { window });
const { setup, resultShare } = window.DashboardUI;
setup({ escape: String });
const money = (amount, currency = 'DKK') => ({ amount, currency });

for (const invalid of [' \t\n', true, false, '', null, undefined, 'invalid', NaN, Infinity, [1]]) {
  assert.equal(resultShare(money(invalid), money(20)), '', 'invalid result: ' + invalid);
  assert.equal(resultShare(money(5), money(invalid)), '', 'invalid base: ' + invalid);
}
for (const [result, base] of [[5, 0], [5, -1], [1, Number.MIN_VALUE], [-Number.MAX_VALUE, 1]]) {
  assert.equal(resultShare(money(result), money(base)), '');
}
assert.equal(resultShare(money(5), money(20, 'USD')), '');
assert.equal(resultShare(money(5, ''), money(20, '')), '');

for (const [result, tone, formatted] of [
  [-5, 'negative', '-25,00'],
  [0, 'neutral', '0,00'],
  [' 5 ', 'positive', '+25,00'],
]) {
  assert.equal(resultShare(money(result), money('20')),
    `<span class="dash-result-share ${tone}">${formatted} % <span>af depotværdi</span></span>`);
}
