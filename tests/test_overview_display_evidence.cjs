const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');

const filename = path.join(__dirname, '../static/overview-ui.js');
const context = {window: {}};
vm.runInNewContext(fs.readFileSync(filename, 'utf8'), context, {filename});
const overview = context.window.OverviewUI;
overview.setup({escape: String, formatAmount: v => v.amount + ' ' + v.currency});

const change = {amount: '25', currency: 'DKK'};
const result = {amount: '-9', currency: 'DKK'};
const figure = delta => overview.figure('125 DKK', delta, '', 'Portefølje', result, 'DKK');

test('dated change retains the amount and Copenhagen local date and time', () => {
  const html = figure({...change, from: '2026-07-01T22:05:00Z'});
  assert.match(html, /market-positive">↑ \+25 DKK<span>Værdiændring siden 02\.07\.2026,? 00\.05<\/span>/);
  assert.doesNotMatch(html, /Oplyst resultat/);
});

for (const [name, period] of Object.entries({
  omitted: {}, null: {from: null}, empty: {from: ''}, invalid: {from: 'ugyldig'},
  boolean: {from: false}
})) {
  test(name + ' timestamp retains the change with an unknown period', () => {
    const html = figure({...change, ...period});
    assert.match(html, /market-positive">↑ \+25 DKK<span>Værdiændring · periode ikke oplyst<\/span>/);
    assert.doesNotMatch(html, /Oplyst resultat|1970|siden/);
  });
}

test('reported result keeps its own label when there is no change', () => {
  const html = figure(null);
  assert.match(html, /market-negative">↓ -9 DKK<span>Oplyst resultat · periode ikke oplyst<\/span>/);
  assert.doesNotMatch(html, /Værdiændring/);
});
