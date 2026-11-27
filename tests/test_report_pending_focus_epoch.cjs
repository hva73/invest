'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../static/report-ui.js'), 'utf8');

function fixture() {
  const session = {owner: 'first'};
  const host = {children: [], innerHTML: ''};
  const nodes = {'#report-mode': {value: 'false'}, '#report-history': {}, '#ingested-report': host};
  const items = [];
  const window = {MarketUI: {mount() {}}};
  vm.runInNewContext(source, {window, document: {querySelector: key => nodes[key]}});
  const ui = window.ReportUI;
  ui.setup({
    escape: String,
    owner: () => session.owner,
    api(url) {
      if (url === 'reports/desk') return {report: null};
      if (url === 'reports/history?is_test=false') return {reports: []};
      return new Promise((resolve, reject) => items.push({url, resolve, reject}));
    }
  });
  async function start(id) {
    ui.focus(id);
    const done = ui.load();
    await new Promise(resolve => setImmediate(resolve));
    const item = items.shift();
    assert.equal(item?.url, 'reports/item?is_test=false&report_id=' + encodeURIComponent(id));
    function succeed(report = {data: {schema_version: 1, is_test: false, report_id: id,
        portfolio_values: [], candidates: [], assessments: [], orders: []}}) {
      item.resolve({report});
    }
    return {done, succeed, reject: item.reject};
  }
  return {start, host, nodes, session};
}

for (const outcome of ['success', 'error']) {
  test('newer focus stays selected after stale ' + outcome, async () => {
    const {start, host} = fixture();
    const a = await start('A');
    const b = await start('B');
    b.succeed();
    await b.done;
    assert.match(host.innerHTML, /Rapport: B<br>/);
    const selected = host.innerHTML;
    if (outcome === 'success') a.succeed();
    else a.reject(new Error('old focus'));
    await a.done;
    assert.equal(host.innerHTML, selected);
  });
}

for (const [name, invalidate] of Object.entries({
  owner: f => { f.session.owner = 'next'; },
  selector: f => { f.nodes['#report-mode'] = {value: 'false'}; },
  mode: f => { f.nodes['#report-mode'].value = 'true'; }
})) {
  for (const outcome of ['success', 'error']) {
    test('discard focus ' + outcome + ' after changing ' + name, async () => {
      const f = fixture();
      const a = await f.start('A');
      invalidate(f);
      if (outcome === 'success') a.succeed(null);
      else a.reject(new Error('obsolete read'));
      await a.done;
      assert.equal(f.host.innerHTML, '');
    });
  }
}

test('current focus propagates its read error', async () => {
  const {start} = fixture();
  const a = await start('A');
  const error = new Error('current read');
  a.reject(error);
  await assert.rejects(a.done, actual => actual === error);
});
