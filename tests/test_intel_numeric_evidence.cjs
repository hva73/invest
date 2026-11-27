'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../static/intel-ui.js'), 'utf8');
const cash = amount => ({amount, currency: 'DKK'});

async function render(value) {
  const node = {isConnected: true};
  const window = {EngineUI: {mount() {}}};
  vm.runInNewContext(source, {window, document: {getElementById: () => node}});
  const observation = {
    data: {observed_at: '2026-11-03T10:00:00Z', instrument: {ticker: 'TEST'},
      market: {intraday_percent: value}, recent_trades: [], sources: []},
    changes: {volume: value, price: cash(value), spread: cash(value)}
  };
  const group = {active: true, observations: [observation], positions: [], orders: [{
    status: 'FILLED', lifecycle: 'filled', requested_quantity: '2', filled_quantity: '2',
    confirmation: 'pluto', realized_pnl: cash(value)
  }]};
  window.IntelUI.setup({escape: String, formatTime: String, owner: () => 'test',
    formatAmount: money => money.amount + ' ' + money.currency, api: async () => ({groups: [group]})});
  await window.IntelUI.load();
  return node.innerHTML;
}

function checkFacts(html, signed, movement) {
  for (const label of ['Intradag %', 'Volumenændring']) {
    assert.ok(html.includes('<dt>' + label + '</dt><dd>' + signed + '</dd>'), label);
  }
  for (const label of ['Kursændring siden måling', 'Spreadændring', 'Realiseret resultat']) {
    assert.ok(html.includes('<dt>' + label + '</dt><dd>' + movement + '</dd>'), label);
  }
}

test('invalid numeric evidence is unknown in observation and order facts', async () => {
  for (const value of ['', ' \t', true, false, null, undefined, NaN, Infinity, -Infinity,
    'NaN', 'Infinity', '9'.repeat(400), '1x', '-1.2.3', '0x10', '1e3', ' 1 ', [], [1], {}]) {
    checkFacts(await render(value), 'Ukendt', 'Ukendt');
  }
});

test('valid numeric evidence retains its text, direction and confirmed order status', async () => {
  for (const [value, tone, arrow] of [
    ['9007199254740993.1200', 'positive', '↑'], ['-0.000000000000000001', 'negative', '↓'],
    ['0.000000000000000001', 'positive', '↑'], ['-0.' + '0'.repeat(324) + '1', 'negative', '↓'],
    ['-0.000', 'neutral', '→'],
    [0, 'neutral', '→'], [2.5, 'positive', '↑'], [-1e-10, 'negative', '↓']
  ]) {
    const html = await render(value);
    const prefix = tone === 'positive' ? '+' : '';
    checkFacts(html, '<span class="signed-' + tone + '">' + prefix + value + '</span>',
      '<span class="market-' + tone + '">' + arrow + ' ' + value + ' DKK</span>');
    assert.ok(html.includes('<strong>Fuldt udført</strong>'));
  }
});
