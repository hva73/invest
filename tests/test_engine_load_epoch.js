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
      if (session.settings && (url.endsWith('/strategies') || url.includes('/providers?'))) return session.settings(url);
      if (body && session.control) return session.control(url, body);
      if (session.detail && (url.includes('/sessions/') || url === 'state')) return session.detail(url);
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
  return {root, historyGroup, session, context, requests, click: ui.click, mount(mode = false) { ui.mount(mode); return requests.shift(); }};
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

async function checkControl(change, stage, fail, action = 'pause') {
  const {session, context, requests, click, mount} = fixture();
  const wid = 'watch/1';
  const dialog = {
    open: change !== 'list', dataset: {watchId: wid}, innerHTML: '',
    querySelector: selector => selector === 'h2' ? {focus() {}} : null
  };
  const records = [];
  context.MutationObserver = class {
    observe() {}
    takeRecords() { return records.splice(0); }
  };
  const lookup = context.document.getElementById;
  context.document.getElementById = id => id === 'engine-dialog' ? dialog : lookup(id);
  const testMode = action === 'resume';
  mount(testMode).succeed();
  await settle();

  let resolve, reject;
  session.control = (url, body) => {
    assert.equal(url, 'v1/hotwatch/sessions/watch%2F1/' + action);
    assert.deepEqual({...body}, {is_test: testMode});
    return new Promise((yes, no) => { resolve = yes; reject = no; });
  };
  const detailReads = [];
  session.detail = url => {
    detailReads.push(url);
    if (url.includes('/samples?') || url.includes('/events?')) return {items: []};
    if (url === 'state') return {portfolios: []};
    assert.equal(url, 'v1/hotwatch/sessions/watch%2F1?is_test=' + testMode);
    return {session: {request: {ticker: 'TEST'}, status: 'PAUSED'}};
  };
  const pending = click({dataset: {engineControl: action, engineId: wid}, hasAttribute: () => false});
  const error = new Error('control flow offline');
  let reload;
  if (stage === 'reload') {
    resolve({});
    await settle();
    assert.equal(requests.length, 1);
    reload = requests.shift();
  }
  if (change === 'epoch') session.epoch++;
  if (change === 'owner') session.owner = 'other-owner';
  if (change === 'mode') mount(!testMode).succeed();
  if (change === 'dialog') {
    dialog.open = false;
    records.push({type: 'attributes', target: {matches: selector => selector === 'dialog'}});
  }

  if (change === 'notice') {
    const notice = {watch_id: wid, last_action_signal: {event_id: 'alert', state: 'ACTIVE', signal: 'SELL'}};
    await click({dataset: {engineNotice: JSON.stringify(notice)}});
    assert.equal(dialog.open, true);
    assert.match(dialog.innerHTML, /Signaladvarsel/);
    assert.equal(dialog.dataset.watchId, undefined);
  }
  const previousHtml = dialog.innerHTML;
  const current = !change || change === 'list';
  const outcome = current && fail ? assert.rejects(pending, e => e === error) : pending;
  if (reload) {
    if (fail) reload.reject(error);
    else reload.succeed();
  } else if (fail) reject(error);
  else resolve({});
  await settle();
  const success = current && !fail;
  assert.equal(requests.length, Number(success && stage === 'control'), 'unexpected reload: ' + change);
  if (requests.length) requests.shift().succeed();
  if (current && fail) await outcome;
  else assert.equal(await outcome, true);
  const showDetail = success && change !== 'list';
  assert.equal(detailReads.length, showDetail ? 4 : 0);
  if (showDetail) assert.match(dialog.innerHTML, /TEST · motorforløb/);
  else assert.equal(dialog.innerHTML, previousHtml);
}

function settingsFixture() {
  const engine = fixture();
  const {context} = engine;
  const dialog = {
    dataset: {}, innerHTML: '', open: false,
    showModal() { this.open = true; }, querySelector: () => ({focus() {}})
  };
  const lookup = context.document.getElementById;
  context.document.getElementById = id => id === 'engine-dialog' ? dialog : lookup(id);
  const records = [];
  context.MutationObserver = class {
    observe() {}
    takeRecords() { return records.splice(0); }
  };
  const button = {dataset: {}, isConnected: true, hasAttribute: name => name === 'data-engine-strategies'};
  return {...engine, button, dialog, records};
}

async function checkKillWhileOpeningSettings(fail) {
  const {session, context, requests, click, button, dialog} = settingsFixture();
  context.confirm = () => true;
  let resolve, reject;
  session.control = (url, body) => {
    assert.equal(url, 'v1/hotwatch/kill-switch');
    assert.equal(body.enabled, true);
    return new Promise((yes, no) => { resolve = yes; reject = no; });
  };
  const pending = click({dataset: {engineKill: 'on'}, hasAttribute: () => false});
  session.settings = url => url.endsWith('/strategies') ? {strategies: []} : {providers: {}};
  assert.equal(await click(button), true);
  assert.equal(dialog.open, true);
  if (fail) {
    const error = new Error('kill switch offline');
    reject(error);
    await assert.rejects(pending, e => e === error);
    assert.equal(requests.length, 0);
  } else {
    resolve({});
    await settle();
    assert.equal(requests.length, 1, 'confirmed kill switch must reload status');
    requests.shift().succeed();
    assert.equal(await pending, true);
  }
}

async function checkSettings(change, fail) {
  const {session, click, mount, button, dialog, records} = settingsFixture();
  const strategy = {strategies: [{strategy_id: 'baseline', version: '1'}]};
  const provider = {providers: {example: {known_limits: ['Testgrænse']}}};
  let resolve, reject;
  session.settings = url => {
    if (url === 'v1/hotwatch/strategies') return strategy;
    assert.equal(url, 'v1/hotwatch/providers?is_test=false');
    return new Promise((yes, no) => { resolve = yes; reject = no; });
  };
  const pending = click(button);
  if (change === 'epoch') session.epoch++;
  if (change === 'owner') session.owner = 'other-owner';
  if (change === 'mode') mount(true).succeed();
  if (change === 'detached') button.isConnected = false;
  if (change === 'dialog') {
    dialog.open = true;
    dialog.innerHTML = 'En anden dialog';
    records.push({type: 'attributes', target: {matches: selector => selector === 'dialog'}});
  }
  if (change === 'newer') {
    session.settings = url => url.endsWith('/strategies') ? {strategies: []} : provider;
    assert.equal(await click(button), true);
    assert.match(dialog.innerHTML, /Strategier og datakilder/);
  }
  const before = [dialog.open, dialog.innerHTML];
  const error = new Error('provider offline');
  if (fail) reject(error);
  else resolve(provider);
  if (!change && fail) await assert.rejects(pending, e => e === error);
  else assert.equal(await pending, true);
  if (change || fail) assert.deepEqual([dialog.open, dialog.innerHTML], before, String(change));
  else {
    assert.equal(dialog.open, true);
    assert.match(dialog.innerHTML, /Strategier og datakilder/);
    assert.match(dialog.innerHTML, /baseline v1/);
    assert.match(dialog.innerHTML, /Testgrænse/);
  }
}

async function checkValidation(change, outcome) {
  const {session, click, mount, dialog} = settingsFixture();
  dialog.open = true;
  const label = 'Kontrollér deklarationen';
  const button = {
    dataset: {engineValidate: 'early/catalyst', engineVersion: '1+2'},
    isConnected: true, hasAttribute: () => false, textContent: label
  };
  let resolve, reject;
  session.control = (url, body) => {
    assert.equal(url, 'v1/hotwatch/strategies/early%2Fcatalyst/1%2B2/validate');
    assert.deepEqual({...body}, {});
    return new Promise((yes, no) => { resolve = yes; reject = no; });
  };
  const pending = click(button);
  if (change === 'epoch') session.epoch++;
  if (change === 'owner') session.owner = 'other-owner';
  if (change === 'mode') mount(true).succeed();
  if (change === 'detached') button.isConnected = false;
  const error = new Error('validation offline');
  if (outcome === 'error') reject(error);
  else resolve({valid: outcome === 'valid'});
  if (!change && outcome === 'error') await assert.rejects(pending, e => e === error);
  else assert.equal(await pending, true);
  const expected = {valid: 'Deklarationen er gyldig', invalid: 'Deklarationen er ugyldig', error: label};
  assert.equal(button.textContent, change ? label : expected[outcome], String(change));
}

async function main() {
  for (const change of ['epoch', 'owner', 'mode', 'detached', null]) {
    await checkValidation(change, 'valid');
    await checkValidation(change, 'error');
  }
  await checkValidation(null, 'invalid');
  await checkKillWhileOpeningSettings(true);
  await checkKillWhileOpeningSettings(false);
  for (const change of ['epoch', 'owner', 'mode', 'dialog', 'newer', 'detached', null]) {
    await checkSettings(change, false);
    await checkSettings(change, true);
  }
  for (const change of ['epoch', 'owner', 'mode', 'dialog', 'notice', 'list', null]) {
    for (const stage of ['control', 'reload']) {
      await checkControl(change, stage, false);
      await checkControl(change, stage, true);
    }
  }
  for (const action of ['resume', 'stop']) await checkControl(null, 'control', false, action);
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
