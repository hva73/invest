const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');

test('sector detail plots only complete DKK observations for the selected holdings', async () => {
  const listeners = {};
  const context = {window: {}, document: {addEventListener(type, fn) { listeners[type] = fn; }}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../static/sector-ui.js'), 'utf8'), context);
  const row = (asset_id, amount, currency = 'DKK') => ({asset_id, value: {amount, currency}});
  const positions = [row('a', 50), row('b', 50)].map(r => ({
    ...r, portfolio_id: 1, sector_intelligence: {sector: 'Teknologi'}
  }));
  const payload = {dashboard: {positions, accounts: [{id: 1, kind: 'portfolio'}]}, regions: [], markets: []};
  const ui = context.window.SectorUI;
  ui.setup({api: async () => payload, escape: String, refresh() {}});
  const state = {user: {username: 'fixture'}};
  ui.render(state);
  await new Promise(resolve => setImmediate(resolve));
  for (const dataset of [{sectorScope: '1'}, {sectorPeriod: 'all'}, {sectorSelect: 'Teknologi'}]) {
    listeners.click({target: {closest: () => ({dataset})}});
  }

  const snap = (day, ...positions) => ({portfolio_id: 1, observed: '2025-10-' + day + 'T12:00:00Z', positions});
  const a = row('a', 20), b = row('b', 30);
  const incomplete = [
    snap('02', a), snap('03', a, a), snap('04', a, b, a),
    snap('05', a, row('b', ' ')), snap('06', a, row('b', '1e999')),
    snap('07', a, row('b', 30, 'USD')),
    snap('08', row('a', 1e308), row('b', 1e308)),
    {...snap('09', a, b), observed: 'invalid'},
    {...snap('10', a, b), observed: null},
    {...snap('11', a, b), portfolio_id: 2}
  ];
  const zero = snap('01', row('a', 0), row('b', '0'));
  payload.history = [zero, ...incomplete];
  function historyPanel() {
    const html = ui.render(state);
    return html.split('<h3>Registreret sektorværdi</h3>')[1].split('</section>')[0];
  }
  assert.match(historyPanel(), /ikke nok faktiske observationer/);
  assert.doesNotMatch(historyPanel(), /<polyline/);

  payload.history.push(snap('12', b, row('unselected', 900), a));
  const foreign = row('a', 1, 'USD');
  foreign.value_in_portfolio_currency = {currency: 'DKK', amount: '70'};
  payload.history.push(snap('13', foreign, b));
  const html = historyPanel();
  assert.match(html, /points="0\.00,90\.00 50\.00,50\.00 100\.00,10\.00"/); // 0, 50, 100 DKK
  assert.match(html, /01\.10\.2025 12:00 til 13\.10\.2025 12:00/);
  assert.match(html, /udvalg følger de nuværende positioner\. Ændringer kan skyldes handler og er ikke afkast\./);
});
