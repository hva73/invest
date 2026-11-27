'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');

const source = fs.readFileSync(path.join(__dirname, '../static/engine-ui.js'), 'utf8');

function fixture() {
  const records = [];
  const dialog = {
    dataset: {}, open: false, matches: selector => selector === 'dialog',
    querySelector: () => ({focus() {}}),
    showModal() { this.open = true; records.push({type: 'attributes', target: this}); },
    close() { this.open = false; records.push({type: 'attributes', target: this}); }
  };
  const timers = new Set();
  const calls = [];
  const session = {owner: 'A', epoch: 1};
  let pending, linked = false;
  const window = {TradeUI: {holdingActions: () => ''}, DashboardUI: {watchLabel: () => 'Updated holding'}};
  vm.runInNewContext(source, {
    window, document: {getElementById: id => id === 'engine-dialog' ? dialog : null},
    MutationObserver: class { observe() {} takeRecords() { return records.splice(0); } },
    setTimeout(callback, delay) { assert.equal(delay, 15000); timers.add(callback); return callback; },
    clearTimeout(callback) { timers.delete(callback); }
  });
  const ui = window.EngineUI;
  ui.setup({
    owner: () => session.owner, sessionEpoch: () => session.epoch, escape: String,
    api(url) {
      calls.push(url);
      let value;
      if (url === 'v1/hotwatch/sessions/W/pause') return {};
      if (url === 'state') {
        value = {dashboard: {positions: [{key: 'H', ticker: 'H', hot_watch: linked ? {session: {watch_id: 'W'}} : {}}]}};
      } else if (/\/(samples|events)\?/.test(url)) {
        value = {items: []};
      } else {
        assert.equal(url, 'v1/hotwatch/sessions/W?is_test=false');
        value = {session: {request: {ticker: 'Current watch'}, display_status: 'Refresh ' + calls.length}};
      }
      if (pending && url === pending.url) {
        const latch = pending;
        pending = null;
        return new Promise((resolve, reject) => { latch.finish = fail => fail ? reject(Error('offline')) : resolve(value); });
      }
      return value;
    }
  });
  function onlyTimer() {
    assert.equal(timers.size, 1);
    return [...timers][0];
  }
  return {
    dialog, calls, timers, session, onlyTimer,
    open(kind) { return kind === 'external' ? ui.openDetail('W') : ui.openHoldingStatus({key: 'H', label: 'New holding'}); },
    pause() { return ui.click({dataset: {engineControl: 'pause', engineId: 'W'}, hasAttribute: () => false}); },
    otherDialogActivity() { records.push({type: 'attributes', target: {matches: selector => selector === 'dialog'}}); },
    start() { const timer = onlyTimer(); timers.delete(timer); return timer(); },
    delay(url) { pending = {url}; return pending; },
    link() { linked = true; }
  };
}

function switchBack(session) {
  for (const owner of ['B', 'A']) { session.owner = owner; session.epoch++; }
}

for (const kind of ['external', 'holding']) {
  for (const change of ['reopen', 'session']) {
    test(kind + ' ignores queued callback after ' + change, async () => {
      const f = fixture();
      await f.open(kind);
      if (change === 'reopen') { f.dialog.close(); f.dialog.showModal(); }
      else switchBack(f.session);
      const count = f.calls.length;
      await f.start();
      assert.equal(f.calls.length, count);
      assert.equal(f.timers.size, 0);
    });

    for (const fail of [false, true]) {
      test(kind + ' preserves newer timer after ' + change + ', rejected=' + fail, async () => {
        const f = fixture();
        await f.open(kind);
        const gate = f.delay('state');
        const running = f.start();
        if (change === 'reopen') f.dialog.close();
        else switchBack(f.session);
        await f.open(kind);
        const fresh = f.onlyTimer(), html = f.dialog.innerHTML;
        gate.finish(fail);
        await running;
        assert.equal(f.dialog.innerHTML, html);
        assert.equal(f.onlyTimer(), fresh);
      });
    }
  }

  test(kind + ' renders and schedules successive current refreshes', async () => {
    const f = fixture();
    await f.open(kind);
    for (let i = 0; i < 2; i++) {
      const count = f.calls.length;
      await f.start();
      assert.equal(f.calls.length - count, kind === 'holding' ? 1 : 4);
      if (kind === 'holding') assert.match(f.dialog.innerHTML, /Updated holding/);
      else assert.ok(f.dialog.innerHTML.includes('Refresh ' + (count + 1) + '<'));
      f.onlyTimer();
    }
  });
}

for (const action of ['pause', 'otherDialogActivity']) {
  test('current external timer continues after ' + action, async () => {
    const f = fixture();
    await f.open('external');
    await f[action]();
    const count = f.calls.length;
    await f.start();
    assert.equal(f.calls.length - count, 4);
    f.onlyTimer();
  });
}

for (const stale of [false, true]) {
  test('linked holding detail handoff, stale=' + stale, async () => {
    const f = fixture();
    await f.open('holding');
    f.link();
    const gate = f.delay('v1/hotwatch/sessions/W?is_test=false');
    const running = f.start();
    await Promise.resolve();
    if (stale) switchBack(f.session);
    gate.finish(false);
    await running;
    if (stale) {
      assert.equal(f.dialog.dataset.holdingKey, 'H');
      assert.equal(f.timers.size, 0);
    } else {
      assert.equal(f.dialog.dataset.holdingKey, undefined);
      assert.match(f.dialog.innerHTML, /Current watch/);
      const count = f.calls.length;
      await f.start();
      assert.equal(f.calls.length - count, 4);
      f.onlyTimer();
    }
  });
}
