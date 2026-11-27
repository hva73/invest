const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

const source = fs.readFileSync(path.join(__dirname, '../static/market-ui.js'), 'utf8');
const window = {};
// Expose the widget's chart and plot functions only inside the test VM.
vm.runInNewContext(source.replace('return {slot,mount,click', 'return {chart,plot,slot,mount,click'), {
  window, document: { addEventListener() {} }, setInterval() {}
});
const ui = window.MarketUI;
ui.setup({ escape: String, formatTime: String });

function render(prices, markers = [], period = 'week') {
  const start = Date.parse('2026-11-27T00:00:00Z');
  const series = prices.map((price, i) => {
    const ms = start + i * 60000;
    return { price, epoch: ms / 1000, timestamp: new Date(ms).toISOString() };
  });
  const data = { series, currency: 'DKK', asset_type: 'CRYPTO', fetched_at: '2026-11-27T18:00:00Z' };
  return ui.plot(data, markers, ui.chart(data, period, markers));
}

const marker = (kind, value, currency = 'DKK') => ({ kind, value, currency });

test('extreme ranges, padded endpoints and underflow render finite output or the empty state', () => {
  for (const [prices, markers] of [
    [[1, 1.7e308], []], [[Number.MAX_VALUE], []], [[Number.MIN_VALUE], []],
    [[100], [marker('entry', Number.MAX_VALUE)]],
    [[1e307, 1.598077612385263e308], [marker('stop', 1.7478853736237895e308)]]
  ]) {
    const html = render(prices, markers, 'day');
    assert.doesNotMatch(html, /NaN|Infinity|∞/);
    assert.match(html, /market-line|market-no-series/);
    assert.match(html, /00\.00<\/span><span>24\.00/);
  }
});

test('invalid prices cannot create observations or marker levels', () => {
  const invalid = [true, false, [1], {}, null, '', '  ', 0, -1, Infinity, '1e309', 'abc'];
  assert.match(render(invalid), /market-no-series/);
  const markers = invalid.flatMap(value => [marker('entry', value), marker('stop', value)]);
  assert.equal(render([...invalid, '10'], markers), render([...invalid.map(() => null), '10']));
});

test('normal numeric prices and markers retain the scale, Top, line and observed dates', () => {
  const html = render(['100', 110], [
    marker('entry', '90'), marker('stop', 95), marker('stop', 75), marker('entry', 200, 'USD')
  ]);
  assert.match(html, /Skala 88–112 DKK/);
  assert.match(html, /market-line" d="M5\.000,31\.000 L235\.000,9\.333"/);
  assert.match(html, /<title>Top 110 DKK<\/title>Top/);
  assert.match(html, /market-marker-entry/);
  assert.match(html, /market-marker-stop/);
  assert.match(html, /Analytisk stop 75 DKK · uden for skala/);
  assert.doesNotMatch(html, /200 USD/);
  assert.match(html, /market-axis"><span>27\.11\.2026<\/span><span>27\.11\.2026/);
});

test('representable prices still draw when the sample percentage overflows', () => {
  const html = render([1, 1e307]);
  assert.match(html, /market-line/);
  assert.match(html, /Udsnit: —/);
  assert.doesNotMatch(html, /NaN|Infinity|∞/);
});
