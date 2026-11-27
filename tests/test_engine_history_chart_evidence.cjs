const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

const source = fs.readFileSync(path.join(__dirname, '../static/engine-ui.js'), 'utf8');
const start = source.indexOf(' function chart(items)');
const end = source.indexOf('\n function ', start + 1);
assert.ok(start >= 0 && end > start);
const chart = vm.runInNewContext(source.slice(start, end) + '\nchart', {
  window: {}, date: String, text: String, esc: String,
});

const first = '2026-11-27T10:00:00Z';
const sample = (price, event_time = first, session_key = 'a') => ({
  data: { price, event_time, session_key, interval_s: 60, currency: 'DKK' },
});
const valid = [
  sample(104, '2026-11-27T10:02:00Z', 'b'),
  sample('102', '2026-11-27T10:01:00Z'),
  sample(100),
];
const invalid = [
  ...[undefined, NaN, Infinity, true, false, null, '', ' ', 'oops', '0x10', '1e999', 0, -3, [7], {}].map(p => sample(p)),
  ...[null, '', 'invalid', true, 1, [first]].map(t => sample(90, t)),
  { data: { price: 90 } }, { data: null }, {}, null,
];

test('genuine observations retain chronological geometry, session gap and caption', () => {
  const html = chart(valid);
  assert.match(html, /d="M10,160 L300,90 M590,20"/);
  assert.match(html, /stroke="#8ddbc8"/);
  assert.ok(html.includes(first + ' → 2026-11-27T10:02:00Z · interval 100–104 DKK'));
  assert.equal(chart([invalid[0], valid[0], ...invalid.slice(1), ...valid.slice(1)]), html);
});

test('fewer than two genuine observations use the existing insufficient-data message', () => {
  const message = '<p>Grafen kræver mindst to faktiske observationer.</p>';
  assert.equal(chart([]), message);
  assert.equal(chart(invalid), message);
  for (const row of invalid) assert.equal(chart([row, valid[0]]), message);
});
