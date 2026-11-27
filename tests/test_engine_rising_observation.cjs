'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');

const source = fs.readFileSync(path.join(__dirname, '../static/engine-ui.js'), 'utf8');
const window = {};
vm.runInNewContext(source.replace('return {openHoldingStatus,', 'return {sessionRow,openHoldingStatus,'), {window});
window.EngineUI.setup({escape: String, state: () => ({})});

function row(change_pct, window_minutes = 5, kind = 'RISING') {
  return window.EngineUI.sessionRow({
    request: {ticker: 'TEST'}, status: 'ACTIVE', signal: 'WAIT',
    data_status: {market_observation: {kind, change_pct, window_minutes}}
  });
}

test('positive decimal evidence renders an observation without a trade action', () => {
  for (const value of [1.25, '1.25']) {
    const html = row(value);
    assert.match(html, /Stiger <span class="signed-positive">\+1,25 %<\/span> på 5 min\. · observation, ikke købssignal/);
    assert.doesNotMatch(html, /data-trade-watch/);
  }
});

test('absent, nonpositive or nondecimal evidence cannot render a rise', () => {
  for (const value of [null, undefined, true, false, 0, '0', -1, '-0.5', '', ' ', 'abc', '1.2%', '0x10', [1], Infinity, NaN]) {
    assert.doesNotMatch(row(value), /market-observation|Stiger/, String(value));
  }
});

test('only rising observations with positive integer windows render', () => {
  for (const minutes of [0, -1, 2.5, '5', null]) {
    assert.doesNotMatch(row(1, minutes), /market-observation|Stiger/, String(minutes));
  }
  assert.doesNotMatch(row(1, 5, 'FALLING'), /market-observation|Stiger/);
});
