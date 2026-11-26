'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../static/engine-ui.js'), 'utf8');
const settle = () => new Promise(resolve => setImmediate(resolve));

function fixture() {
  const root = {isConnected: true, innerHTML: '', textContent: '', querySelector: () => null, querySelectorAll: () => []};
  const context = {window: {}, document: {getElementById: id => id === 'engine-root' ? root : null},
    setTimeout() {}, clearTimeout() {}};
  vm.runInNewContext(source, context);
  const requests = [];
  const session = {epoch: 1};
  const ui = context.window.EngineUI;
  ui.setup({
    api(url) {
      if (url.includes('view=current')) {
        return new Promise((resolve, reject) => requests.push({
          succeed: () => resolve({sessions: [], kill_switch: {}}), reject
        }));
      }
      if (url.includes('view=history')) return {sessions: [], next_cursor: 'older'};
      assert.match(url, /^reports\/candidate-registry\?/);
      return {candidates: []};
    },
    escape: String, isAdmin: () => false, owner: () => 'same-owner', sessionEpoch: () => session.epoch
  });
  return {root, session, mount(mode = false) { ui.mount(mode); return requests.shift(); }};
}

async function main() {
  const {root, session, mount} = fixture();
  const oldSession = mount();
  session.epoch++;
  oldSession.succeed();
  await settle();
  assert.equal(root.innerHTML.length, 0, 'a previous login painted the same owner’s root');
  assert.equal(root.textContent, '');

  const superseded = mount();
  mount().succeed();
  await settle();
  assert.match(root.innerHTML, /Driftsdata/);
  assert.match(root.innerHTML, /data-engine-history-more/);
  const currentHtml = root.innerHTML;
  superseded.reject(new Error('obsolete'));
  await settle();
  assert.equal(root.textContent, '', 'a superseded request displayed its error');
  assert.equal(root.innerHTML, currentHtml);

  mount(true).reject(new Error('offline'));
  await settle();
  assert.equal(root.textContent, 'Motorstatus kunne ikke hentes: offline');
}

main().catch(error => { console.error(error); process.exitCode = 1; });
