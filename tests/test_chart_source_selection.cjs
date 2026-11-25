const assert = require('node:assert/strict');

const listeners = {};
const focus = {setAttribute(key, value) { this[key] = value; }, removeAttribute() {}};
const output = {hidden: true};
const svg = {getBoundingClientRect: () => ({left: 10, width: 240}), querySelector: () => focus};
const plot = {
  querySelector: selector => selector === 'svg' ? svg : output,
  addEventListener: (name, listener) => { listeners[name] = listener; },
};
const node = {
  dataset: {marketCandidate: 'example', marketMarkers: '[]', marketTest: 'false'},
  classList: {toggle() {}},
  isConnected: true,
  closest: () => null,
  getBoundingClientRect: () => ({top: 0, bottom: 100}),
  querySelector: () => plot,
};
globalThis.window = {};
globalThis.innerHeight = 600;
globalThis.document = {hidden: false, querySelectorAll: () => [node], addEventListener() {}};
globalThis.setInterval = () => {};
require('../static/market-ui.js');
require('../static/dashboard-ui.js');

const escape = String;
const money = ({amount, currency}) => amount + ' ' + currency;
const age = () => ({tone: 'fresh', minutes: 0});
const ui = window.MarketUI;
const at = clock => '2026-11-06T' + clock + ':00Z';
const point = (clock, price) => ({timestamp: at(clock), epoch: Date.parse(at(clock)) / 1000, price});
let quote;
ui.setup({api: async () => quote, escape, formatTime: String, formatAmount: money,
  connected: () => true, owner: () => 'test', now: () => Date.parse(at('18:00')), age});
window.DashboardUI.setup({escape, formatTime: String});
const toX = html => Number([...html.matchAll(/class="market-last" cx="([^"]+)"/g)].at(-1)[1]);
const session = (start, end, phase, asOf) => ({kind: 'market_session', start: at(start), end: at(end),
  phase, as_of: at(asOf), session_source: 'EODHD exchange calendar', session_source_time: at('07:00')});

async function render(assetType, domain, series, holding = false, demo = false) {
  window.ESCAPE_DEMO = demo;
  node.dataset.marketHoldingPortfolio = holding ? '7' : '';
  node.dataset.marketHoldingAsset = holding ? 'example' : '';
  node.dataset.marketMarkers = JSON.stringify([{kind: 'entry', value: '80', currency: 'EUR'}]);
  quote = {ticker: 'TEST', asset_type: assetType, currency: 'EUR', price: '100',
    fetched_at: at('12:00'), series, chart_domain: domain};
  await ui.refreshVisible();
  return node.innerHTML;
}

(async () => {
  const europe = session('08:00', '16:30', 'regular', '11:45');
  const samples = [point('07:00', 900), point('08:30', 120), point('11:30', 100), point('13:00', 990)];
  const html = await render('CS', europe, samples, true);
  assert.match(html, /09\.00<\/span><span>17\.30/);
  assert.match(html, /Marked åbent · 2 punkter/);
  assert.match(html, /Top 120 EUR/);
  assert.match(html, /market-marker-entry[^>]*><title>Gns\. købskurs 80 EUR/);
  assert.match(html, /class="market-line" d="M[^"]+ M[^"]+"/);
  const x = toX(html);
  assert.ok(Math.abs((x - 5) / 230 - 3.5 / 8.5) < 0.001);
  listeners.pointermove({clientX: x + 10});
  assert.equal(focus.cx, x);
  assert.match(output.textContent, /12\.30 · 100 EUR/);
  listeners.pointermove({clientX: 225});
  assert.equal(output.hidden, true);

  const pre = {...session('09:00', '23:59', 'pre', '12:00'), end: '2026-11-07T01:00:00Z'};
  const preHtml = await render('ETF', pre, [point('11:00', 100)]);
  assert.match(preHtml, /Pre-market · ét punkt/);
  assert.ok(toX(preHtml) < 45);
  assert.doesNotMatch(preHtml, /market-marker-entry|Gns\. købskurs/);
  for (const [phase, label] of [['after', 'Eftermarked'], ['closed', 'Marked lukket']]) {
    const markup = await render('ETF', {...pre, phase}, [point('11:00', 100)]);
    assert.ok(markup.includes(label));
  }
  const unknown = await render('ETF', {...pre, session_source: null}, [point('11:00', 100)]);
  assert.match(unknown, /Markedsstatus ukendt/);
  assert.equal(toX(unknown), 120);

  const cryptoSeries = [point('00:00', 100), point('11:00', 101), point('13:00', 999)];
  const cryptoDomain = {kind: 'calendar_day', phase: 'continuous', as_of: at('12:00'),
    start: '2026-11-05T23:00:00Z', end: at('23:00')};
  const crypto = await render('CRYPTO', cryptoDomain, cryptoSeries);
  assert.match(crypto, /00\.00<\/span><span>24\.00/);
  assert.match(crypto, /24\/7 · 2 punkter/);
  assert.equal(toX(crypto), 120);
  const demo = await render('CRYPTO', undefined, cryptoSeries, false, true);
  assert.equal(toX(demo), toX(crypto));
  for (const [date, hours] of [['2026-03-29', 23], ['2026-10-25', 25]]) {
    const bounds = ui.localDay(date + 'T12:00:00Z');
    assert.equal((bounds.end - bounds.start) / 3600000, hours);
  }

  const result = (clock, amount) => ({at: at(clock), reported_result: amount, currency: 'DKK'});
  window.ESCAPE_DEMO = false;
  const portfolio = window.DashboardUI.portfolioChart({portfolio_value_history: {
    chart_domain: {...cryptoDomain, phase: 'not_applicable', as_of: at('10:45')},
    periods: {day: [result('11:00', 999), result('09:00', 10), result('10:40', 20)]},
  }});
  const xs = [...portfolio.matchAll(/class="dash-chart-point" cx="([^"]+)"/g)].map(m => Number(m[1]));
  assert.equal(xs.length, 2);
  assert.ok(Math.abs(xs[1] / 600 - 700 / 1440) < 0.001);
  assert.match(portfolio, /00\.00<\/span><span>24\.00/);
  window.ESCAPE_DEMO = true;
  const demoPortfolio = window.DashboardUI.portfolioChart({portfolio_value_history: {
    periods: {day: [result('09:00', 10), result('10:40', 20)]},
  }});
  assert.deepEqual([...demoPortfolio.matchAll(/class="dash-chart-point" cx="([^"]+)"/g)].map(m => Number(m[1])), xs);
  console.log('PASS: verified session and phase, chart gaps, tooltips, holding marker, crypto day and 11:40 portfolio');
})().catch(error => { console.error(error); process.exitCode = 1; });
