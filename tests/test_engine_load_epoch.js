'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../static/engine-ui.js'), 'utf8');
const settle = () => new Promise(resolve => setImmediate(resolve));

function fixture() {
  const historyGroup = {open: false};
  const root = {isConnected: true, innerHTML: '', textContent: '', querySelector: selector => selector === 'details[data-engine-group=history]' ? historyGroup : null, querySelectorAll: () => []};
  const context = {window: {}, document: {getElementById: id => id === 'engine-root' ? root : null},
    setTimeout() {}, clearTimeout() {}};
  vm.runInNewContext(source, context);
  const requests = [];
  const session = {epoch: 1, owner: 'same-owner', history: [], older: []};
  const ui = context.window.EngineUI;
  ui.setup({
    api(url, body) {
      if (url.endsWith('/ack-signal')) return session.ack(url, body);
      if (url.includes('view=current')) {
        return new Promise((resolve, reject) => requests.push({
          succeed: () => resolve({sessions: [], kill_switch: {}}), reject
        }));
      }
      if (url.includes('view=history&before=older')) return session.page ? session.page() : {sessions: session.older, next_cursor: null};
      if (url.includes('view=history')) return {sessions: session.history, next_cursor: 'older'};
      assert.match(url, /^reports\/candidate-registry\?/);
      return {candidates: []};
    },
    escape: String, isAdmin: () => false, owner: () => session.owner, sessionEpoch: () => session.epoch
  });
  return {root, historyGroup, session, context, click: ui.click, mount(mode = false) { ui.mount(mode); return requests.shift(); }};
}

async function checkHistoryScope(change, freshHistory) {
  const {root, session, click, mount} = fixture();
  const row = (watch_id, status) => ({watch_id, status, request: {ticker: watch_id}});
  const button = (dataset, attribute) => ({dataset, isConnected: true, hasAttribute: name => name === attribute});
  const refresh = async (mode = false) => {
    mount(mode).succeed();
    await settle();
    assert.equal(root.textContent, '');
    assert.ok(root.innerHTML.includes(mode ? 'Testdata' : 'Driftsdata'));
  };

  session.history = [row('prior-completed', 'COMPLETED')];
  session.older = [row('prior-expired', 'EXPIRED')];
  await refresh();
  await click(button({}, 'data-engine-history-more'));
  await click(button({engineOwn: 'toggle'}));
  await click(button({engineFilter: 'BUY'}));
  await refresh();
  for (const id of ['prior-completed', 'prior-expired']) {
    assert.ok(root.innerHTML.includes('data-engine-detail="' + id + '"'), 'missing cached ' + id);
  }
  assert.match(root.innerHTML, /data-engine-own="toggle" aria-pressed="true"/);
  assert.match(root.innerHTML, /data-engine-filter="BUY" aria-pressed="true"/);

  if (change === 'epoch') session.epoch++;
  if (change === 'owner') session.owner = 'other-owner';
  session.history = freshHistory ? [row('fresh-completed', 'COMPLETED')] : [];
  await refresh(change === 'mode');
  assert.ok(!root.innerHTML.includes('prior-completed'), change + ' retained completed history');
  assert.ok(!root.innerHTML.includes('prior-expired'), change + ' retained paginated history');
  if (freshHistory) assert.match(root.innerHTML, /data-engine-detail="fresh-completed"/);
  else assert.doesNotMatch(root.innerHTML, /data-engine-group="history"/);
  if (change !== 'mode') {
    assert.match(root.innerHTML, /data-engine-own="toggle" aria-pressed="false"/);
    assert.match(root.innerHTML, /data-engine-filter="all" aria-pressed="true"/);
  }
}

async function checkPagination(change, rejectPage) {
  const {root, session, historyGroup, mount, click} = fixture();
  const row = watch_id => ({watch_id, status: 'COMPLETED', request: {ticker: watch_id}});
  const more = () => click({dataset: {}, isConnected: true, hasAttribute: name => name === 'data-engine-history-more'});
  session.history = [row('first')];
  mount().succeed();
  await settle();

  let resolve, reject;
  session.page = () => new Promise((yes, no) => { resolve = yes; reject = no; });
  const pending = more();
  if (change === 'epoch' || change === 'login') session.epoch++;
  if (change === 'owner') session.owner = 'new-owner';
  if (['login', 'refresh', 'mode'].includes(change)) {
    session.history = [row('fresh')];
    mount(change === 'mode').succeed();
    await settle();
  }
  if (change === 'cursor') {
    session.page = () => ({sessions: [row('winner')], next_cursor: null});
    await more();
    historyGroup.open = false;
  }
  const before = root.innerHTML;
  const error = new Error('page offline');
  if (rejectPage) reject(error);
  else resolve({sessions: [row('first'), row('older-page')], next_cursor: null});

  if (!change && rejectPage) await assert.rejects(pending, e => e === error);
  else assert.equal(await pending, true);
  if (change || rejectPage) {
    assert.equal(root.innerHTML, before, 'unexpected pagination repaint: ' + change);
    assert.equal(historyGroup.open, false);
  } else {
    assert.equal(root.innerHTML.match(/class="engine-list-identity" data-engine-detail="first"/g).length, 1);
    assert.match(root.innerHTML, /data-engine-detail="older-page"/);
    assert.doesNotMatch(root.innerHTML, /data-engine-history-more/);
    assert.equal(historyGroup.open, true);
  }
}

async function checkAcknowledgement(change, rejectAck) {
  const {session, context, click, mount} = fixture();
  const row = (watch_id, event_id, is_test) => ({
    watch_id, is_test, status: 'COMPLETED', request: {ticker: 'TEST'}, last_action_signal: {event_id}
  });
  const wid = 'watch/1', event = 'event-1';
  const rows = [row(wid, event, true), row('other', event, true), row(wid, 'other', true), row(wid, event, false)];
  session.history = rows;
  mount().succeed();
  await settle();

  const icons = rows.map(s => ({
    dataset: {engineNotice: JSON.stringify(s)}, className: 'unread',
    setAttribute(name, value) { this[name] = value; }
  }));
  context.document.querySelectorAll = selector => {
    assert.equal(selector, '[data-engine-notice]');
    return icons;
  };
  const dashboard = [];
  context.window.DashboardUI = {acknowledgeSignal: (...args) => dashboard.push(args)};
  const dialog = {open: true, contains: node => node === button, close() { this.open = false; }};
  const button = {
    dataset: {engineAck: wid, eventId: event, isTest: 'true'}, isConnected: true,
    textContent: 'Kvittér advarsel', closest: () => dialog,
    setAttribute(name, value) { this[name] = value; }
  };
  let resolve, reject;
  session.ack = (url, body) => {
    assert.equal(url, 'v1/hotwatch/sessions/watch%2F1/ack-signal');
    assert.deepEqual({...body}, {event_id: event, is_test: true});
    return new Promise((yes, no) => { resolve = yes; reject = no; });
  };
  const pending = click(button);
  assert.equal(button.disabled, true);
  if (change === 'epoch') session.epoch++;
  if (change === 'owner') session.owner = 'other-owner';
  if (change === 'mode') mount(true);
  const error = new Error('ack offline');
  if (rejectAck) reject(error);
  else resolve({});
  if (!change && rejectAck) await assert.rejects(pending, e => e === error);
  else assert.equal(await pending, true);

  const marked = !change && !rejectAck;
  assert.deepEqual(dashboard, marked ? [[wid, event, true]] : []);
  for (const [i, icon] of icons.entries()) {
    const expected = marked && i === 0;
    assert.equal(Boolean(rows[i].last_action_signal.acknowledged), expected);
    assert.equal(Boolean(JSON.parse(icon.dataset.engineNotice).last_action_signal.acknowledged), expected);
    assert.equal(icon.className, expected ? 'signal-alert signal-alert--read' : 'unread');
  }
  assert.equal(dialog.open, !marked);
  assert.equal(button.textContent, marked ? 'Kvitteret' : 'Kvittér advarsel');
  assert.equal(button['aria-label'], marked ? 'Advarslen er kvitteret' : undefined);
  assert.equal(button.disabled, Boolean(change) || !rejectAck);
}

async function main() {
  for (const change of ['epoch', 'owner', 'mode', null]) {
    await checkAcknowledgement(change, false);
    await checkAcknowledgement(change, true);
  }
  for (const change of ['login', 'epoch', 'owner', 'mode', 'refresh', 'cursor', null]) {
    await checkPagination(change, false);
    await checkPagination(change, true);
  }
  await checkHistoryScope('epoch', false);
  await checkHistoryScope('epoch', true);
  await checkHistoryScope('owner', true);
  await checkHistoryScope('mode', true);

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
