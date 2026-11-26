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

async function checkManualStart(change, stage, fail) {
  const {context, session, requests, click, mount, dialog, records, root} = settingsFixture();
  const status = {}, results = {};
  const button = {dataset: {engineManual: '0'}, isConnected: true, closest: () => dialog};
  let activeDialog = dialog;
  const lookup = context.document.getElementById;
  let activeRoot = root;
  context.document.getElementById = id => {
    if (id === 'engine-root') return activeRoot;
    if (id === 'engine-dialog') return activeDialog;
    if (id === 'content') return {append(node) { activeDialog = node; }};
    return {'engine-manual-results': results, 'engine-manual-status': status}[id] || lookup(id);
  };
  context.document.createElement = tag => {
    assert.equal(tag, 'dialog');
    return {dataset: {}, open: false, querySelector: query, showModal: dialog.showModal};
  };
  dialog.contains = node => node === button;
  const query = dialog.querySelector;
  dialog.querySelector = selector => selector === '#engine-manual-status' ? status : query(selector);
  const toggle = open => {
    dialog.open = open;
    records.push({type: 'attributes', target: {matches: selector => selector === 'dialog'}});
  };
  let closes = 0;
  dialog.close = () => { closes++; toggle(false); };
  dialog.open = true;
  context.FormData = class { get() { return 'TEST'; } };
  const calls = [];
  let resolve, reject;
  session.control = (url, body) => {
    calls.push([url, {...body}]);
    if (url.includes('/manual-search?')) return {assets: [{asset_id: 'asset/1', ticker: 'TEST'}]};
    return new Promise((yes, no) => { resolve = yes; reject = no; });
  };
  await context.window.EngineUI.submit({target: {id: 'engine-manual-search', isConnected: true}, preventDefault() {}});
  assert.match(results.innerHTML, /data-engine-manual="0"/);
  const detailReads = [];
  session.detail = url => {
    detailReads.push(url);
    if (url.includes('/samples?') || url.includes('/events?')) return {items: []};
    if (url === 'state') return {portfolios: []};
    if (stage === 'detail' && fail) throw new Error('manual offline');
    return {session: {request: {ticker: 'TEST'}, status: 'ACTIVE'}};
  };
  const pending = click(button);
  assert.deepEqual(calls, [
    ['v1/hotwatch/manual-search?is_test=false', {query: 'TEST'}],
    ['v1/hotwatch/manual-start?is_test=false', {asset_id: 'asset/1', ticker: 'TEST'}]
  ]);
  assert.equal(button.disabled, true);
  const busy = status.textContent;
  const response = {session: {watch_id: 'manual/1'}};
  const replaceView = () => {
    assert.equal(dialog.open, false);
    button.isConnected = false;
    activeDialog = null;
    root.isConnected = false;
    activeRoot = change === 'navigate' ? null : {...root, isConnected: true};
    if (activeRoot) mount().succeed();
  };
  const queuedRender = ['remount', 'remount-login', 'navigate'].includes(change) ? replaceView : null;
  let reload;
  if (stage !== 'start') {
    resolve(response);
    await settle();
    assert.equal(closes, 1);
    assert.equal(requests.length, 1);
    reload = requests.shift();
  }
  if (queuedRender) queuedRender();
  if (change === 'remount-login') session.epoch++;
  if (change === 'epoch') session.epoch++;
  if (change === 'owner') session.owner = 'other-owner';
  if (change === 'mode') mount(true).succeed();
  if (change === 'detached') button.isConnected = false;
  if (change === 'replaced') activeDialog = {open: true};
  if (change === 'dialog') toggle(!dialog.open);
  const error = new Error('manual offline');
  if (reload) {
    if (stage === 'reload' && fail) reload.reject(error);
    else reload.succeed();
  } else if (fail) reject(error);
  else resolve(response);
  await settle();
  const success = (!change || change === 'remount') && !fail;
  assert.equal(requests.length, Number(success && stage === 'start'));
  if (requests.length) requests.shift().succeed();
  assert.equal(await pending, true);
  assert.equal(closes, Number(stage !== 'start' || success));
  assert.equal(status.textContent, !change && fail ? error.message : busy);
  assert.equal(button.disabled, Boolean(change) || !fail);
  assert.equal(detailReads.length, stage === 'detail' && fail ? 1 : success ? 4 : 0);
  if (success) {
    assert.equal(detailReads[0], 'v1/hotwatch/sessions/manual%2F1?is_test=false');
    assert.match(activeDialog.innerHTML, /TEST · motorforløb/);
    assert.equal(activeDialog.open, true);
  }
}

async function checkPlanClick(newerWatch, planClick = true) {
  const {session, click, context, dialog} = settingsFixture();
  const effects = [];
  const details = {
    open: false,
    scrollIntoView(options) { effects.push(options.block); },
    querySelector: selector => selector === 'summary' ? {
      focus(options) { effects.push(options.preventScroll); }
    } : null
  };
  const plan = {closest: selector => selector === 'details' ? details : null};
  const renderedPlan = () => dialog.innerHTML.includes('id="engine-buy-plan"') ? plan : null;
  const lookup = context.document.getElementById;
  context.document.getElementById = id => id === 'engine-buy-plan' ? renderedPlan() : lookup(id);
  const query = dialog.querySelector;
  dialog.querySelector = selector => selector === '#engine-buy-plan' ? renderedPlan() : query(selector);
  const row = wid => ({session: {watch_id: wid, status: 'ACTIVE', request: {ticker: wid, watch_mode: 'entry'}}});
  let finish;
  session.detail = url => {
    if (url.includes('/samples?') || url.includes('/events?')) return {items: []};
    if (url === 'state') return {portfolios: []};
    const wid = url.split('/').pop().split('?')[0];
    if (!finish) return new Promise(resolve => { finish = () => resolve(row(wid)); });
    return row(wid);
  };
  const open = (wid, expand) => click({
    dataset: {engineDetail: wid}, hasAttribute: name => expand && name === 'data-engine-plan'
  });
  const pending = open('first', planClick);
  if (newerWatch) assert.equal(await open(newerWatch, false), true);
  finish();
  assert.equal(await pending, true);
  assert.equal(dialog.dataset.watchId, newerWatch || 'first');
  assert.ok(renderedPlan());
  const expanded = !newerWatch && planClick;
  assert.equal(details.open, expanded);
  assert.deepEqual(effects, expanded ? ['nearest', true] : []);
}

async function checkPolling(change) {
  const {context, session, dialog, requests, mount, records} = settingsFixture();
  let tick;
  context.setTimeout = (callback, delay) => {
    assert.equal(delay, 15000);
    tick = callback;
  };
  const wid = 'poll/1';
  Object.assign(dialog, {id: 'engine-dialog', open: true});
  dialog.dataset.watchId = wid;
  let active = dialog;
  const lookup = context.document.getElementById;
  context.document.getElementById = id => id === 'engine-dialog' ? active : lookup(id);
  context.document.querySelector = selector => {
    assert.equal(selector, 'dialog[open]');
    return active.open ? active : null;
  };
  const reads = [];
  session.detail = url => {
    reads.push(url);
    if (url === 'state') return {portfolios: []};
    if (url.includes('/samples?') || url.includes('/events?')) return {items: []};
    return {session: {request: {ticker: 'POLL'}, status: 'ACTIVE'}};
  };
  mount().succeed();
  await settle();
  const pending = tick();
  assert.equal(requests.length, 1);
  const reload = requests.shift();
  if (change === 'epoch') session.epoch++;
  if (change === 'owner') session.owner = 'new-owner';
  if (change === 'mode') mount(true).succeed();
  if (change === 'closed') dialog.open = false;
  if (change === 'reopened') records.push({type: 'attributes', target: {matches: s => s === 'dialog'}});
  if (change === 'replaced') active = {...dialog};
  if (change === 'watch') dialog.dataset.watchId = 'poll/2';
  tick = null;
  reload.succeed();
  await pending;
  assert.equal(typeof tick, 'function', 'polling must continue');
  assert.equal(requests.length, 0);
  const endpoint = 'v1/hotwatch/sessions/poll%2F1';
  assert.deepEqual(reads, change ? [] : [
    endpoint + '?is_test=false', endpoint + '/samples?is_test=false&limit=100&order=desc',
    endpoint + '/events?is_test=false&limit=50&order=desc', 'state'
  ], change);
  if (!change) assert.match(dialog.innerHTML, /POLL · motorforløb/);
}

async function main() {
  for (const change of ['epoch', 'owner', 'mode', 'closed', 'reopened', 'replaced', 'watch', null]) {
    await checkPolling(change);
  }
  await checkPlanClick('second');
  await checkPlanClick('first');
  await checkPlanClick(null);
  await checkPlanClick(null, false);
  for (const change of ['remount', 'remount-login', 'navigate']) await checkManualStart(change, 'reload', false);
  await checkManualStart(null, 'detail', true);
  for (const stage of ['start', 'reload']) {
    for (const change of ['epoch', 'owner', 'mode', 'dialog', 'replaced', 'detached', null]) {
      await checkManualStart(change, stage, false);
      await checkManualStart(change, stage, true);
    }
  }
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
