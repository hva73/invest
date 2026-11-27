const assert = require('assert').strict;
const fs = require('fs');
const vm = require('vm');

const window = {};
vm.runInNewContext(fs.readFileSync(require.resolve('../static/overview-ui.js'), 'utf8'), {window});
const ui = window.OverviewUI;
ui.setup({escape: String, formatTime: String, formatAmount: v => String(v.amount) + ' DKK'});
const entry = amount => ({amount, currency: 'DKK', from: '2026-01-01T12:00:00Z'});
const figure = (delta, result) => ui.figure('100 DKK', delta, '', 'Saldo', result, 'DKK');
const unknown = 'Ændring ikke oplyst';

function cashButtons(balance, change) {
  const portfolio = {portfolio_id: 'p', name: 'Depot', cash: [balance], earmarked: [balance]};
  const changes = {DKK: change};
  const html = ui.render({main_report: {data: {schema_version: 2, portfolios: [portfolio],
    positions: [], orders: [], summary: {}}}, candidates: [],
    overview_changes: {p: {cash: changes, earmarked: changes}}});
  const buttons = html.match(/<button class="overview-cash-link[^>]*>[\s\S]*?<\/button>/g);
  assert.equal(buttons.length, 2);
  return buttons;
}

for (const amount of ['value7', '-2DKK', '', '  ', true, false, null, undefined,
                      [], [2], {}, NaN, Infinity, -Infinity, '0x10', '1e3', '1.2.3', '9'.repeat(400)]) {
  const bad = entry(amount);
  for (const html of [figure(bad), figure(null, bad), figure(bad, entry('1')),
                      ...cashButtons(entry('100'), bad)]) {
    assert.ok(html.includes(unknown), html);
    assert.doesNotMatch(html, /overview-movement|market-(?:positive|negative)/);
  }
  for (const html of cashButtons(bad, entry('1'))) {
    assert.ok(html.includes('Ikke oplyst'), html);
    assert.doesNotMatch(html, /overview-movement|market-(?:positive|negative)/);
  }
}

const tiny = '0.' + '0'.repeat(340) + '1';
for (const [amount, tone, arrow] of [[0, 'neutral', '→'], ['-0.00', 'neutral', '→'],
    [tiny, 'positive', '↑ +'], ['-' + tiny, 'negative', '↓'],
    ['999999999999999999.123456789012', 'positive', '↑ +'], [-0.25, 'negative', '↓']]) {
  for (const html of [figure(entry(amount)), figure(null, entry(amount)),
                      ...cashButtons(entry('100'), entry(amount))]) {
    assert.ok(html.includes('overview-movement market-' + tone), html);
    assert.ok(html.includes(arrow + (arrow.endsWith('+') ? '' : ' ') + amount + ' DKK'), html);
  }
}
assert.match(figure(entry(0), entry('-1')), /market-negative">↓ -1 DKK<span>Oplyst resultat/);
assert.match(figure(entry(0), entry('bad')), /market-neutral">→ 0 DKK<span>Værdiændring/);
assert.match(figure(entry(0), {...entry('-1'), currency: 'EUR'}), /Værdiændring siden/);
assert.match(figure(entry('2'), entry('-7')), /market-positive">↑ \+2 DKK<span>Værdiændring/);
assert.ok(figure(null, null).includes(unknown));
for (const html of cashButtons(entry('0'), null)) {
  assert.match(html, /overview-cash-link market-neutral/);
  assert.ok(html.includes('>0 DKK '));
  assert.doesNotMatch(html, /overview-movement/);
}
for (const html of cashButtons(entry('100'), entry('-2'))) {
  assert.match(html, /overview-cash-link market-negative/);
}
