'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../static/app.js'), 'utf8');
const start = source.indexOf('async function loadPushSettings(');
const end = source.indexOf('\nfunction pushPublicKey(', start);
assert.ok(start >= 0 && end > start);

function fixture() {
  const box = {isConnected: true, innerHTML: '', textContent: ''};
  const config = {available: true};
  const subscription = {endpoint: 'current'};
  const device = {subscribed: true, buy: false, sell: true};
  const context = {
    $: selector => selector === '#push-settings-content' ? box : null,
    sessionEpoch: 1, state: {user: {username: 'owner'}},
    pushConfig: null, pushSubscription: null,
    navigator: {serviceWorker: {}}, window: {PushManager: {}, Notification: {}},
    Notification: {permission: 'granted'}, isSecureContext: true,
    api(route, data) {
      if (route === 'push/config') return config;
      assert.equal(route, 'push/device');
      assert.equal(data.endpoint, subscription.endpoint);
      return device;
    },
    pushWorkerReady: () => ({pushManager: {getSubscription: () => subscription}})
  };
  vm.runInNewContext(source.slice(start, end), context);
  return {context, box, config, subscription};
}

for (const stage of ['config', 'subscription', 'device']) {
  test('same-user relogin during ' + stage, async () => {
    const {context, box, config, subscription} = fixture();
    const currentApi = context.api;
    const currentWorker = context.pushWorkerReady;
    let finish;
    const pending = new Promise(resolve => { finish = resolve; });
    context.api = route => {
      if (route === 'push/config') return stage === 'config' ? pending : {available: false};
      return stage === 'device' ? pending : {subscribed: false};
    };
    context.pushWorkerReady = () => ({pushManager: {
      getSubscription: () => stage === 'subscription' ? pending : {endpoint: 'old'}
    }});
    const older = context.loadPushSettings();
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(context.pushConfig, null);
    assert.equal(context.pushSubscription, null);

    context.sessionEpoch++;
    context.state = {user: {username: 'owner'}};
    context.api = currentApi;
    context.pushWorkerReady = currentWorker;
    await context.loadPushSettings();
    assert.match(box.innerHTML, /Gem valg/);
    assert.match(box.innerHTML, /id="push-sell" checked/);
    assert.doesNotMatch(box.innerHTML, /id="push-buy" checked/);
    const currentHtml = box.innerHTML;
    finish({available: false, endpoint: 'old', subscribed: false});
    await older;
    assert.equal(context.pushConfig, config);
    assert.equal(context.pushSubscription, subscription);
    assert.equal(box.innerHTML, currentHtml);
    assert.equal(box.textContent, '');
  });
}

for (const change of ['none', 'epoch', 'owner', 'detached']) {
  test('config error with ' + change + ' change', async () => {
    const {context, box} = fixture();
    let fail;
    context.api = () => new Promise((_, reject) => { fail = reject; });
    const done = context.loadPushSettings();
    if (change === 'epoch') context.sessionEpoch++;
    if (change === 'owner') context.state.user.username = 'other';
    if (change === 'detached') box.isConnected = false;
    fail(Error('offline'));
    await done;
    assert.equal(box.textContent, change === 'none' ? 'Notifikationer kunne ikke kontrolleres: offline' : '');
  });
}
