'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../static/engine-ui.js'), 'utf8');
const settle = () => new Promise(resolve => setImmediate(resolve));

function fixture(engineSource = source) {
  const historyGroup = {open: false};
  const root = {isConnected: true, innerHTML: '', textContent: '', querySelector: selector => selector === 'details[data-engine-group=history]' ? historyGroup : null, querySelectorAll: () => []};
  const context = {window: {}, document: {getElementById: id => id === 'engine-root' ? root : null},
    setTimeout() {}, clearTimeout() {}};
  vm.runInNewContext(engineSource, context);
  const requests = [];
  const session = {epoch: 1, owner: 'same-owner', history: [], older: []};
  const ui = context.window.EngineUI;
  ui.setup({
    api(url, body) {
      if (session.creation) return session.creation(url, body);
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

async function checkKillWhileOpeningDialog(fail, manualSearch = false) {
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
  if (manualSearch) {
    context.document.querySelector = () => null;
    await click({dataset: {}, hasAttribute: name => name === 'data-engine-new'});
    assert.match(dialog.innerHTML, /id="engine-manual-search"/);
    const form = {id: 'engine-manual-search', isConnected: true};
    const status = {}, results = {};
    const nodes = {[form.id]: form, 'engine-manual-status': status, 'engine-manual-results': results};
    const lookup = context.document.getElementById;
    context.document.getElementById = id => nodes[id] || lookup(id);
    context.FormData = class { get() { return 'TEST'; } };
    session.control = (url, body) => {
      assert.equal(url, 'v1/hotwatch/manual-search?is_test=false');
      assert.deepEqual({...body}, {query: 'TEST'});
      return {assets: []};
    };
    assert.equal(await context.window.EngineUI.submit({target: form, preventDefault() {}}), true);
    assert.match(results.innerHTML, /Ingen resultater/);
  } else {
    assert.equal(await click(button), true);
  }
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

async function checkManualSearch(change, fail) {
  const {context, session, mount, dialog, click} = settingsFixture();
  const form = {id: 'engine-manual-search', isConnected: true, query: 'FIRST'};
  const status = {}, results = {};
  const nodes = {[form.id]: form, 'engine-manual-status': status, 'engine-manual-results': results};
  const lookup = context.document.getElementById;
  context.document.getElementById = id => nodes[id] || lookup(id);
  context.FormData = class {
    constructor(target) { this.target = target; }
    get(key) { assert.equal(key, 'query'); return this.target.query; }
  };
  const calls = [], pending = [];
  session.control = (url, body) => {
    calls.push([url, {...body}]);
    return new Promise((resolve, reject) => pending.push({resolve, reject}));
  };
  const submit = () => context.window.EngineUI.submit({target: form, preventDefault() {}});
  const asset = ticker => ({asset_id: 'asset-' + ticker, ticker});
  const first = submit();
  const endpoint = 'v1/hotwatch/manual-search?is_test=false';
  assert.deepEqual(calls, [[endpoint, {query: 'FIRST'}]]);
  assert.equal(status.textContent, 'Søger hos Pluto …');
  assert.equal(results.innerHTML, '');
  if (change === 'epoch') session.epoch++;
  if (change === 'owner') session.owner = 'other-owner';
  if (change === 'mode') mount(true).succeed();
  if (change === 'detached') form.isConnected = false;
  if (change === 'replaced') nodes[form.id] = {...form};
  if (change === 'newer') {
    form.query = 'SECOND';
    const second = submit();
    assert.deepEqual(calls[1], [endpoint, {query: 'SECOND'}]);
    pending[1].resolve({assets: [asset('SECOND')]});
    assert.equal(await second, true);
    assert.match(results.innerHTML, /<strong>SECOND<\/strong>/);
  }
  const before = [results.innerHTML, status.textContent];
  if (fail) pending[0].reject(new Error('offline'));
  else pending[0].resolve({assets: [asset('FIRST')]});
  assert.equal(await first, true);
  if (change) assert.deepEqual([results.innerHTML, status.textContent], before, change);
  else if (fail) {
    assert.equal(results.innerHTML, '');
    assert.equal(status.textContent, 'Pluto-søgningen kunne ikke gennemføres. Prøv igen.');
  } else {
    assert.match(results.innerHTML, /data-engine-manual="0"><strong>FIRST<\/strong>/);
    assert.equal(status.textContent, 'Vælg det instrument, der skal overvåges.');
  }

  // Exercise the same index lookup as a tap on the first result.
  const selected = [];
  session.control = (url, body) => { selected.push([url, {...body}]); throw new Error('fixture'); };
  dialog.open = true;
  dialog.contains = () => true;
  dialog.querySelector = () => status;
  await click({dataset: {engineManual: '0'}, isConnected: true, closest: () => dialog});
  const ticker = change === 'newer' ? 'SECOND' : !change && !fail ? 'FIRST' : null;
  assert.deepEqual(selected, ticker ? [['v1/hotwatch/manual-start?is_test=false', asset(ticker)]] : []);
}

async function checkManualStart(change, stage, fail) {
  const {context, session, requests, click, mount, dialog, records, root} = settingsFixture();
  const status = {}, results = {};
  const button = {dataset: {engineManual: '0'}, isConnected: true, closest: () => dialog};
  const form = {id: 'engine-manual-search', isConnected: true};
  let activeDialog = dialog;
  const lookup = context.document.getElementById;
  let activeRoot = root;
  context.document.getElementById = id => {
    if (id === 'engine-root') return activeRoot;
    if (id === 'engine-dialog') return activeDialog;
    if (id === 'content') return {append(node) { activeDialog = node; }};
    return {[form.id]: form, 'engine-manual-results': results, 'engine-manual-status': status}[id] || lookup(id);
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
  await context.window.EngineUI.submit({target: form, preventDefault() {}});
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

function instrumentFixture() {
  const seeded = source.replace('return {openHoldingStatus,',
    'return {seed(rows,accounts,snapshots){candidates=rows;portfolios=accounts;portfolioSnapshots=snapshots},openHoldingStatus,');
  const {context, session, mount, requests} = fixture(seeded);
  const ui = context.window.EngineUI;
  const rows = ['FIRST', 'SECOND'].map(ticker => ({report_id: 'report', candidate: {candidate_id: ticker, ticker}}));
  ui.seed(rows, [{id: 1}, {id: 2}], {
    1: {data: {positions_complete: true, positions: []}},
    2: {data: {positions_complete: true, positions: [{kind: 'holding', asset_id: 'asset', quantity: 3}]}}
  });
  const elements = {
    candidate: {name: 'candidate', value: '0'}, provider: {value: 'pluto'}, provider_symbol: {value: ''},
    exchange: {}, asset_id: {}, quote_currency: {}, watch_mode: {value: 'both'},
    portfolios: {options: [{value: '1'}, {value: '2'}]}
  };
  const form = {id: 'engine-create', isConnected: true, elements}, status = {}, slot = {};
  const nodes = {'engine-create': form, 'engine-form-status': status, 'engine-instrument-choice': slot};
  const lookup = context.document.getElementById;
  context.document.getElementById = id => nodes[id] || lookup(id);
  context.FormData = class { constructor(target) { this.target = target; } get(k) { return this.target.elements[k]?.value; } };
  const QuotePromise = vm.runInNewContext('Promise', context);
  return {context, session, mount, requests, ui, rows, elements, form, status, slot, nodes, QuotePromise};
}

async function checkInstrument(change, outcome, afterSettlement = false) {
  const {session, mount, ui, rows, elements, form, status, slot, nodes, QuotePromise} = instrumentFixture();
  if (afterSettlement) elements.provider.value = 'eodhd';
  const calls = [];
  session.control = (url, body) => {
    if (url !== 'market/quote') {
      calls.push({url, body: {...body}});
      if (afterSettlement && !change && url === 'market/eodhd-symbols') return {choices: []};
      throw Error('Unexpected provider request: ' + url);
    }
    return new QuotePromise((resolve, reject) => calls.push({url, body: {...body}, resolve, reject}));
  };
  const pending = ui.change({target: elements.candidate});
  assert.equal(calls[0].url, 'market/quote');
  assert.deepEqual(calls[0].body, {report_id: 'report', candidate_id: 'FIRST', is_test: false});
  const verified = {asset_id: 'asset', ticker: 'FIRST', exchange: 'NASDAQ', currency: 'USD', name: 'First', isin: 'id'};
  const choices = [{...verified}];
  const settleQuote = () => {
    if (outcome === 'error') calls[0].reject(new Error('quote offline'));
    else calls[0].resolve(outcome === 'choices' ? {selection_required: true, choices} : verified);
  };
  if (afterSettlement) {
    settleQuote();
    await Promise.resolve();
    if (outcome === 'verified') assert.equal(rows[0].instrument.asset_id, 'asset');
    if (change === 'replacement-session') {
      session.epoch++;
      form.isConnected = false;
      nodes['engine-create'] = {isConnected: true, elements: {...elements, candidate: {value: '1'}}};
      nodes['engine-form-status'] = {textContent: 'Ny session'};
      nodes['engine-eodhd-choice'] = {textContent: 'Nyt instrument'};
    }
  }
  if (change === 'candidate') elements.candidate.value = '1';
  if (change === 'epoch') session.epoch++;
  if (change === 'owner') session.owner = 'other';
  if (change === 'mode') mount(true).succeed();
  if (change === 'replaced') nodes['engine-create'] = {...form};
  if (change === 'detached') form.isConnected = false;
  if (change === 'newer') {
    const second = ui.change({target: {id: 'engine-asset-choice', value: 'selected'}});
    assert.deepEqual(calls[1].body, {...calls[0].body, asset_id: 'selected'});
    calls[1].resolve({...verified, asset_id: 'selected'});
    await second;
    assert.equal(rows[0].instrument.asset_id, 'selected');
  }
  if (change) elements.provider.value = 'eodhd';
  const snapshot = () => JSON.stringify([rows, elements, nodes]);
  const before = snapshot();
  if (!afterSettlement) settleQuote();
  assert.equal(await pending, true);
  if (afterSettlement && !change) {
    assert.deepEqual(calls.slice(1), [{url: 'market/eodhd-symbols', body: {...calls[0].body,
      quote_currency: outcome === 'verified' ? 'USD' : null}}]);
  } else assert.equal(calls.length, change === 'newer' ? 2 : 1, change + ' / ' + outcome);
  if (change) assert.equal(snapshot(), before, change + ' / ' + outcome);
  else if (outcome === 'error') assert.match(status.textContent, /quote offline/);
  else if (outcome === 'choices') {
    assert.deepEqual(rows[0].resolution_choices, choices);
    assert.match(slot.innerHTML, /<option value="">Vælg instrument<\/option><option value="asset">/);
    assert.equal(rows[0].instrument, undefined);
    assert.equal(elements.asset_id.value, undefined);
  } else {
    assert.deepEqual({...rows[0].instrument}, {asset_id: 'asset', currency: 'USD', exchange: 'NASDAQ',
      name: 'First', isin: 'id', provider_symbol: null});
    assert.deepEqual([...rows[0].portfolio_ids], [2]);
    assert.equal(rows[0].portfolios_verified, true);
    assert.deepEqual(elements.portfolios.options.map(option => option.selected), [false, true]);
    assert.deepEqual([elements.asset_id.value, elements.exchange.value, elements.quote_currency.value,
      elements.watch_mode.value], ['asset', 'NASDAQ', 'USD', 'both']);
    assert.match(status.textContent, /1 matchende depot/);
  }
}

const appSource = fs.readFileSync(path.join(__dirname, '../static/app.js'), 'utf8');

function dispatchInstrumentEvent(context, caller, form) {
  const type = {submit: 'submit', batch: 'click', asset: 'change'}[caller];
  const listener = appSource.split('\n').find(line =>
    line.startsWith(`document.addEventListener('${type}',`) && line.includes(`window.EngineUI.${type}(`));
  let handle;
  context.document.addEventListener = (_, fn) => { handle = fn; };
  vm.runInNewContext(listener, context);
  const pass = () => false;
  Object.assign(context.window, {JournalUI: {click: pass, change: pass}, DashboardUI: {click: pass, changeSort: pass},
    CandidateUI: {click: pass}, TradeUI: {change: pass}});
  context.userRefreshBusy = false;
  form.matches = pass;
  form.classList = {contains: pass};
  const button = {dataset: {}, hasAttribute: key => key === 'data-engine-batch-add'};
  const target = {submit: form, asset: {id: 'engine-asset-choice', value: 'asset'},
    batch: {closest: selector => selector === 'button' ? button : null}}[caller];
  return handle({target, preventDefault() {}});
}

async function checkInstrumentCaller(caller, stale, outcome) {
  const {context, session, requests, rows, form, nodes, QuotePromise} = instrumentFixture();
  const calls = [], button = {};
  let resolveQuote, rejectQuote;
  nodes['engine-batch-list'] = {textContent: ''};
  nodes['engine-dialog'] = {close() { this.closed = true; }};
  context.crypto = {randomUUID: () => 'test-id'};
  form.querySelector = () => button;
  session.creation = (url, body) => {
    calls.push(url);
    switch (url) {
      case 'v1/hotwatch/start-candidates?is_test=false': return {candidates: rows};
      case 'market/quote':
        assert.deepEqual({...body}, {report_id: 'report', candidate_id: 'FIRST', is_test: false,
          ...(caller === 'asset' ? {asset_id: 'asset'} : {})});
        return new QuotePromise((yes, no) => { resolveQuote = yes; rejectQuote = no; });
      case 'strategy-center': return {selection: {strategy_id: 'test', version: '1'}};
      case 'v1/hotwatch/sessions':
        assert.equal(body.candidate_id, 'FIRST');
        assert.equal(body.asset_id, 'asset');
        assert.deepEqual([...body.portfolio_ids], [2]);
        session.creation = null;
        return {};
      default: throw Error('Unexpected request: ' + url);
    }
  };
  const notices = [];
  context.notice = (message, kind) => notices.push([session.epoch, message, kind]);
  const pending = dispatchInstrumentEvent(context, caller, form);
  await settle();
  const error = Object.assign(new Error('quote offline'), {details: {code: 'quote_unavailable'}});
  const initialCalls = caller === 'submit' ? ['v1/hotwatch/start-candidates?is_test=false', 'market/quote'] : ['market/quote'];
  assert.deepEqual(calls, initialCalls);
  if (outcome === 'error') rejectQuote(error);
  else resolveQuote(outcome === 'choices' ? {selection_required: true, choices: []} :
    {asset_id: 'asset', exchange: 'NASDAQ', currency: 'USD'});
  await Promise.resolve(); // resolveInstrument has resumed, its caller is still queued.
  if (outcome === 'verified') assert.equal(rows[0].instrument.asset_id, 'asset');
  if (stale === 'after-caller') await Promise.resolve();
  if (stale) session.epoch++;
  const before = JSON.stringify([nodes, rows]);
  if (caller === 'submit' && outcome === 'verified') {
    await settle();
    assert.equal(requests.length, stale ? 0 : 1);
    if (!stale) requests.shift().succeed();
  }
  await pending;
  const expectedError = outcome === 'error' ? (caller === 'submit' ? error.details.code : error.message) :
    caller === 'submit' && outcome === 'choices' ? 'Pluto kunne ikke verificere alle instrumenter.' : null;
  const expectedNotices = expectedError && stale !== true ? [[1, expectedError, 'error']] : [];
  assert.deepEqual(notices, expectedNotices, caller + ' / ' + stale + ' / ' + outcome);
  const verified = !stale && outcome === 'verified';
  assert.deepEqual(calls, verified && caller === 'submit' ?
    [...initialCalls, 'strategy-center', 'v1/hotwatch/sessions'] : initialCalls);
  assert.equal(nodes['engine-batch-list'].textContent, verified && caller === 'batch' ? '1/40 kandidat(er) klar: FIRST · asset' : '');
  assert.equal(Boolean(nodes['engine-dialog'].closed), verified && caller === 'submit');
  if (stale) assert.equal(JSON.stringify([nodes, rows]), before);
}

async function checkPendingSubmitLookup(sameCandidate, quoteFirst) {
  const {ui, rows, elements, form, status, session, QuotePromise} = instrumentFixture();
  const calls = [];
  session.creation = (url, body) => new QuotePromise(resolve => calls.push({url, body, resolve}));
  const submit = ui.submit({target: form, preventDefault() {}});
  const index = sameCandidate ? 0 : 1;
  elements.candidate.value = String(index);
  const target = sameCandidate ? {id: 'engine-asset-choice', value: 'asset'} : elements.candidate;
  const lookup = ui.change({target});
  assert.deepEqual(calls.map(call => call.url), ['v1/hotwatch/start-candidates?is_test=false', 'market/quote']);
  assert.deepEqual({...calls[1].body}, {report_id: 'report', candidate_id: rows[index].candidate.candidate_id,
    is_test: false, ...(sameCandidate ? {asset_id: 'asset'} : {})});
  const finishLookup = async () => {
    calls[1].resolve({asset_id: 'asset', currency: 'USD', exchange: 'NASDAQ'});
    await lookup;
  };
  if (quoteFirst) await finishLookup();
  calls[0].resolve({candidates: rows});
  await settle();
  assert.equal(calls.length, 2, 'obsolete submit started another request');
  assert.equal(await submit, true);
  if (!quoteFirst) await finishLookup();
  assert.match(status.textContent, /1 matchende depot/);
  assert.deepEqual([elements.asset_id.value, elements.exchange.value, elements.quote_currency.value],
    ['asset', 'NASDAQ', 'USD']);
  assert.deepEqual([...rows[index].portfolio_ids], [2]);
  assert.deepEqual(elements.portfolios.options.map(option => option.selected), [false, true]);
  if (!sameCandidate) assert.equal(rows[0].instrument, undefined);
}

async function checkOverlappingQuotes(callers, verificationFirst, implicitOutcome, {stale, repeat, candidateLookup} = {}) {
  const {context, session, ui, rows, elements, form, status, slot, nodes, requests, QuotePromise} = instrumentFixture();
  const quotes = [], notices = [];
  context.notice = message => notices.push(message);
  nodes['engine-batch-list'] = {textContent: ''};
  const started = [];
  context.crypto = {randomUUID: () => 'test-id'};
  form.querySelector = () => ({});
  nodes['engine-dialog'] = {close() { this.closed = true; }};
  session.creation = (url, body) => {
    if (url === 'strategy-center') return {selection: {strategy_id: 'test', version: '1'}};
    if (url === 'v1/hotwatch/sessions') {
      started.push([body.candidate_id, body.asset_id, [...body.portfolio_ids]]);
      session.creation = null;
      return {};
    }
    if (callers.includes('submit') && url === 'v1/hotwatch/start-candidates?is_test=false') return {candidates: rows};
    assert.equal(url, 'market/quote');
    return new QuotePromise((resolve, reject) => quotes.push({body: {...body}, resolve, reject}));
  };
  const verified = {asset_id: 'asset', currency: 'USD', exchange: 'NASDAQ'};
  const choices = {selection_required: true, choices: [verified]};
  const initial = ui.change({target: elements.candidate});
  let verification = initial;
  if (!candidateLookup) {
    quotes[0].resolve(choices);
    await initial;
    assert.match(slot.innerHTML, /value="asset"/);
    verification = dispatchInstrumentEvent(context, 'asset', form);
    await settle();
  }
  const primary = quotes.at(-1);
  const actions = [];
  for (const action of callers) {
    actions.push(dispatchInstrumentEvent(context, action, form));
    await settle();
  }
  const duplicates = quotes.slice(quotes.indexOf(primary) + 1);
  const args = {report_id: 'report', candidate_id: 'FIRST', is_test: false};
  assert.deepEqual(quotes.map(q => q.body), [args, ...(candidateLookup ? [] : [{...args, asset_id: 'asset'}]),
    ...callers.map(() => args)]);
  let repeated;
  if (repeat) {
    repeated = dispatchInstrumentEvent(context, callers[0], form);
    await settle();
    assert.deepEqual(quotes[3].body, args);
    quotes[3].resolve(choices);
  }
  const finishVerification = async () => {
    primary.resolve(verified);
    await verification;
  };
  if (verificationFirst) {
    await finishVerification();
    assert.match(status.textContent, /1 matchende depot/);
    if (stale) session.epoch++;
  }
  for (const duplicate of duplicates) {
    if (implicitOutcome === 'error') duplicate.reject(Error('implicit lookup failed'));
    else if (implicitOutcome === 'pending') duplicate.resolve({pending: true, retry_after: 2});
    else duplicate.resolve(implicitOutcome === 'choices' ? choices : {...verified, asset_id: 'other'});
  }
  if (!verificationFirst) {
    await settle();
    assert.deepEqual(started, []);
    assert.equal(nodes['engine-batch-list'].textContent, '');
    await finishVerification();
  }
  await settle();
  const submits = callers.includes('submit') && !stale;
  assert.deepEqual(started, submits ? [['FIRST', 'asset', [2]]] : []);
  assert.equal(requests.length, submits ? 1 : 0);
  if (submits) requests.shift().succeed();
  await Promise.all([...actions, repeated]);
  assert.equal(elements.asset_id.value, 'asset');
  assert.equal(elements.exchange.value, 'NASDAQ');
  assert.equal(elements.quote_currency.value, 'USD');
  assert.equal(rows[0].instrument.asset_id, 'asset');
  assert.deepEqual([...rows[0].portfolio_ids], [2]);
  assert.deepEqual(elements.portfolios.options.map(option => option.selected), [false, true]);
  assert.deepEqual(notices, []);
  assert.equal(nodes['engine-batch-list'].textContent, callers.includes('batch') && !stale ? '1/40 kandidat(er) klar: FIRST · asset' : '');
  assert.equal(Boolean(nodes['engine-dialog'].closed), submits);
}

async function main() {
  for (const first of [true, false]) {
    for (const caller of ['batch', 'submit']) await checkOverlappingQuotes([caller], first, 'pending', {candidateLookup: true});
    for (const callers of [['batch', 'submit'], ['submit', 'batch']]) await checkOverlappingQuotes(callers, first, 'verified');
  }
  for (const caller of ['batch', 'submit']) {
    await checkOverlappingQuotes([caller], true, 'choices', {stale: true});
    await checkOverlappingQuotes([caller], false, 'choices', {repeat: true});
    for (const explicitFirst of [true, false]) {
      for (const outcome of ['choices', 'verified', 'error']) await checkOverlappingQuotes([caller], explicitFirst, outcome);
    }
  }
  for (const sameCandidate of [false, true]) {
    for (const quoteFirst of [false, true]) await checkPendingSubmitLookup(sameCandidate, quoteFirst);
  }
  for (const caller of ['batch', 'submit', 'asset']) {
    await checkInstrumentCaller(caller, 'after-caller', 'error');
    if (caller === 'submit') await checkInstrumentCaller(caller, 'after-caller', 'choices');
    for (const stale of [true, false]) {
      for (const outcome of ['verified', 'choices', 'error']) await checkInstrumentCaller(caller, stale, outcome);
    }
  }
  for (const change of ['replacement-session', 'epoch', 'owner', 'mode', 'candidate', 'newer', null]) {
    for (const outcome of ['verified', 'choices', 'error']) await checkInstrument(change, outcome, true);
  }
  for (const change of ['candidate', 'epoch', 'owner', 'mode', 'replaced', 'detached', 'newer', null]) {
    for (const outcome of ['verified', 'choices', 'error']) await checkInstrument(change, outcome);
  }
  for (const change of ['epoch', 'owner', 'mode', 'newer', 'detached', 'replaced', null]) {
    await checkManualSearch(change, false);
    await checkManualSearch(change, true);
  }
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
  for (const fail of [false, true]) {
    await checkKillWhileOpeningDialog(fail);
    await checkKillWhileOpeningDialog(fail, true);
  }
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

const incomplete = () => { throw Error('Engine UI suite ended with a pending test'); };
process.once('beforeExit', incomplete);
main().then(() => console.log('PASS: Engine UI request and session isolation'))
  .catch(error => { console.error(error); process.exitCode = 1; })
  .finally(() => process.removeListener('beforeExit', incomplete));
