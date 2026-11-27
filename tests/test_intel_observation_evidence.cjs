'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');

const source = fs.readFileSync(path.join(__dirname, '../static/intel-ui.js'), 'utf8');
const options = {day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit',
  minute: '2-digit', second: '2-digit', hourCycle: 'h23'};
const danish = new Intl.DateTimeFormat('da-DK', {...options, timeZone: 'Europe/Copenhagen'});
const utc = new Intl.DateTimeFormat('da-DK', {...options, timeZone: 'UTC'});

async function openObservation(fields) {
  const dialog = {showModal() { this.open = true; }, querySelector: () => ({focus() {}})};
  const document = {getElementById: id => id === 'intel-detail-dialog' ? dialog : null};
  const window = {CandidateUI: {history: () => ''}};
  vm.runInNewContext(source, {document, window});
  const data = {observation_id: 'old-evidence', market: {}, sources: [], recent_trades: [],
    note: 'Bevaret observation', fetched_at: '2026-11-26T01:23:45Z', ...fields};
  window.IntelUI.setup({
    owner: () => 'owner', escape: String,
    formatTime: value => danish.format(new Date(value)) + ' · dansk tid',
    api: url => url.startsWith('reports/candidate-history?') ? {events: []}
      : {groups: [{observations: [{data, changes: {}}]}]}
  });
  await window.IntelUI.click({dataset: {intelHistory: 'A'}, isConnected: true, hasAttribute: () => false});
  assert.equal(dialog.open, true);
  assert.match(dialog.innerHTML, /Bevaret observation/);
  return dialog.innerHTML;
}

for (const [name, fields] of [
  ['malformed', {observed_at: 'broken-date'}], ['missing', {}], ['null', {observed_at: null}]
]) {
  test(name + ' observation time leaves readable evidence', async () => {
    const html = await openObservation(fields);
    assert.ok(html.includes('<summary><strong>Ukendt</strong>'));
    assert.ok(html.includes('UTC: Ukendt · dansk tid: Ukendt</p>'));
  });
}

const instant = new Date('2026-07-04T22:15:30Z');
for (const value of ['2026-07-04T22:15:30Z', '2026-07-05T01:15:30+03:00']) {
  test('observation detail preserves the instant ' + value, async () => {
    const html = await openObservation({observed_at: value});
    const local = danish.format(instant) + ' · dansk tid';
    assert.ok(html.includes('<summary><strong>' + local + '</strong>'));
    assert.ok(html.includes('UTC: ' + utc.format(instant) + ' · dansk tid: ' + local + '</p>'));
  });
}
