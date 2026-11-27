'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../static/intel-ui.js'), 'utf8');

function fixture() {
  const node = {innerHTML: 'initial', isConnected: true};
  const state = {owner: 'first'};
  const requests = [];
  const window = {EngineUI: {mount() {}}};
  const document = {getElementById: id => id === 'watch-content' ? node : null};
  vm.runInNewContext(source, {window, document});
  const ui = window.IntelUI;
  ui.setup({
    owner: () => state.owner,
    api: url => new Promise((resolve, reject) => requests.push({url, resolve, reject}))
  });
  return {ui, node, state, requests};
}

test('late rejection after a connected mode switch preserves the current result', async () => {
  const {ui, node, requests} = fixture();
  const first = ui.load();
  const second = ui.change({target: {id: 'watch-mode', value: 'true', closest: () => null}});
  assert.deepEqual(requests.map(r => r.url), [
    'reports/hot-watch?is_test=false', 'reports/hot-watch?is_test=true'
  ]);
  requests[1].resolve({groups: []});
  assert.equal(await second, true);
  assert.match(node.innerHTML, /TESTDATA/);
  const rendered = node.innerHTML;
  requests[0].reject(new Error('obsolete request'));
  await first;
  assert.equal(node.innerHTML, rendered);
});

for (const change of ['owner changed', 'node disconnected']) {
  test('rejection is suppressed when ' + change, async () => {
    const {ui, node, state, requests} = fixture();
    const done = ui.load();
    if (change === 'owner changed') state.owner = 'second';
    else node.isConnected = false;
    requests[0].reject(new Error(change));
    await done;
    assert.equal(node.innerHTML, 'initial');
  });
}

test('current rejection reaches the caller unchanged', async () => {
  const {ui, node, requests} = fixture();
  const done = ui.load();
  const error = new Error('current request failed');
  requests[0].reject(error);
  await assert.rejects(done, caught => caught === error);
  assert.equal(node.innerHTML, 'initial');
});
