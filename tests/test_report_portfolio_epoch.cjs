'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');

const source = fs.readFileSync(path.join(__dirname, '../static/report-ui.js'), 'utf8');

function fixture() {
  const opened = [];
  const pending = [];
  const session = {owner: 'owner'};
  const window = {PositionUI: {openPortfolio: (...args) => opened.push(args)}};
  vm.runInNewContext(source, {window});
  window.ReportUI.setup({
    owner: () => session.owner,
    api: url => new Promise((resolve, reject) => pending.push({url, resolve, reject}))
  });
  function start(portfolio, mode = 'false') {
    const control = {isConnected: true, dataset: {
      reportPortfolio: portfolio, portfolioReport: 'report/1', portfolioTest: mode
    }};
    const done = window.ReportUI.click(control);
    const request = pending.shift();
    assert.equal(request.url, 'reports/item?report_id=report%2F1&is_test=' + mode);
    return {control, done, ...request};
  }
  return {start, opened, session};
}

test('only the latest connected portfolio control opens its report', async () => {
  const {start, opened} = fixture();
  const older = start('A');
  const latest = start('B');
  const report = {data: {report_id: 'report/1', is_test: false}};
  latest.resolve({report});
  assert.equal(await latest.done, true);
  older.resolve({report});
  assert.equal(await older.done, true);
  assert.deepEqual(opened, [[report, 'B']]);
});

test('a repeated interaction suppresses the older error and preserves the latest error', async () => {
  const {start, opened} = fixture();
  const older = start('A', 'true');
  const latest = start('A', 'true');
  older.reject(new Error('older read'));
  assert.equal(await older.done, true);
  const error = new Error('latest read');
  latest.reject(error);
  await assert.rejects(latest.done, actual => actual === error);
  assert.deepEqual(opened, []);
});

for (const [name, invalidate] of Object.entries({
  owner: (_, session) => { session.owner = 'other'; },
  disconnected: control => { control.isConnected = false; },
  portfolio: control => { control.dataset.reportPortfolio = 'B'; },
  report: control => { control.dataset.portfolioReport = 'other'; },
  mode: control => { control.dataset.portfolioTest = 'true'; }
})) {
  test('discard a read after a change to ' + name, async () => {
    const {start, opened, session} = fixture();
    const read = start('A');
    invalidate(read.control, session);
    read.resolve({report: {data: {report_id: 'report/1', is_test: false}}});
    assert.equal(await read.done, true);
    assert.deepEqual(opened, []);
  });
}
