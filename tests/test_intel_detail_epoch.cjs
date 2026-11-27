'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');

const source = fs.readFileSync(path.join(__dirname, '../static/intel-ui.js'), 'utf8');
function fixture() {
  const pending = [];
  const dialog = {
    showModal() { this.open = true; },
    close() { this.open = false; },
    querySelector() { return {focus() {}}; }
  };
  let mounted;
  const document = {
    getElementById(id) { return id === 'content' ? {append(node) { mounted = node; }} : mounted; },
    createElement() { return dialog; }
  };
  const window = {CandidateUI: {history: marker => marker}};
  vm.runInNewContext(source, {document, window});
  const ui = window.IntelUI;
  ui.setup({
    owner: () => 'owner', escape: String,
    api: url => new Promise((resolve, reject) => pending.push({url, resolve, reject}))
  });
  function start(kind, id) {
    const done = ui.click({dataset: {[kind]: id}, isConnected: true, hasAttribute: () => false});
    const requests = pending.splice(0);
    const history = kind === 'intelHistory';
    assert.deepEqual(requests.map(r => r.url), history ? [
      'reports/candidate-history?candidate_id=' + id + '&is_test=false',
      'reports/hot-watch?candidate_id=' + id + '&is_test=false'
    ] : ['reports/item?report_id=' + id + '&is_test=false']);
    return {
      done,
      succeed(marker) {
        if (history) {
          requests[0].resolve({lifecycle_history: marker, events: []});
          requests[1].resolve({groups: []});
        } else {
          requests[0].resolve({report: {data: {consolidation: {note: marker}, portfolios: []}}});
        }
      },
      fail(error) {
        requests.at(-1).reject(error);
        if (history) requests[0].resolve({});
      }
    };
  }
  return {start, dialog, close: () => ui.click({dataset: {}, hasAttribute: n => n === 'data-intel-close'})};
}

const kinds = ['intelConsolidation', 'intelHistory'];
for (const first of kinds) {
  for (const last of kinds) {
    for (const sameId of [false, true]) {
      test(first + ' followed by ' + last + ', same ID = ' + sameId, async () => {
        const {start, dialog} = fixture();
        const older = start(first, 'A');
        const newer = start(last, sameId ? 'A' : 'B');
        newer.succeed('current payload');
        assert.equal(await newer.done, true);
        assert.equal(dialog.open, true);
        assert.match(dialog.innerHTML, /current payload/);
        const current = dialog.innerHTML;
        older.succeed('old payload');
        assert.equal(await older.done, true);
        assert.equal(dialog.innerHTML, current);
      });
    }
  }

  test(first + ' pending at close', async () => {
    const {start, close, dialog} = fixture();
    const initial = start(first, 'A');
    initial.succeed('initial');
    await initial.done;
    const pending = start(first, 'B');
    assert.equal(await close(), true);
    pending.succeed('late');
    assert.equal(await pending.done, true);
    assert.equal(dialog.open, false);
    assert.doesNotMatch(dialog.innerHTML, /late/);
    const next = start(first, 'C');
    next.succeed('reopened');
    await next.done;
    assert.equal(dialog.open, true);
    assert.match(dialog.innerHTML, /reopened/);
  });

  test(first + ' pending when the dialog closes natively', async () => {
    const {start, dialog} = fixture();
    const initial = start(first, 'A');
    initial.succeed('initial');
    await initial.done;
    const pending = start(first, 'B');
    dialog.close();
    pending.succeed('late');
    assert.equal(await pending.done, true);
    assert.equal(dialog.open, false);
    assert.doesNotMatch(dialog.innerHTML, /late/);
  });

  test(first + ' suppresses stale errors and propagates the current error', async () => {
    const {start} = fixture();
    const older = start(first, 'A');
    const current = start(first, 'B');
    older.fail(new Error('old'));
    assert.equal(await older.done, true);
    const error = new Error('current');
    current.fail(error);
    await assert.rejects(current.done, err => err === error);
  });
}
