const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../static/market-ui.js'), 'utf8');
const timestamp = '2026-11-27T08:00:00Z';

async function check(times, priceClock, fetchClock) {
  const nodes = ['quote', 'chart'].map(marketLayout => ({
    dataset: {marketLayout}, isConnected: true, classList: {toggle() {}},
    getBoundingClientRect: () => ({top: 0, bottom: 100}),
    closest: () => null, querySelector: () => null
  }));
  const context = {
    window: {}, document: {querySelectorAll: () => nodes, addEventListener() {}},
    innerHeight: 900, setInterval() {}
  };
  vm.runInNewContext(source, context);
  const market = context.window.MarketUI;
  market.setup({
    owner: () => 'test', connected: () => true, now: () => 1, escape: String,
    formatAmount: v => v.amount + ' ' + v.currency, formatTime: v => new Date(v).toISOString(),
    age: () => ({minutes: 20}),
    api: async () => ({
      ticker: 'TEST', price: 42, currency: 'DKK', ...times,
      series: [{timestamp, epoch: Date.parse(timestamp) / 1000, price: 40}]
    })
  });
  await market.refreshVisible();
  for (const node of nodes) {
    const html = node.innerHTML;
    assert.match(html, /class="market-price">42 DKK</);
    const compact = node.dataset.marketLayout === 'quote';
    const origin = 'TEST · ' + (priceClock ? 'kurs ' + priceClock : 'kurstid ukendt');
    const fetch = fetchClock || 'ukendt';
    assert.ok(html.includes(origin + (compact ? ' · hentet ' + fetch : '') + '</small>'));
    assert.equal(html.includes('market-time-unknown'), !priceClock);
    if (!compact) {
      assert.ok(html.includes('class="market-fetch">Hentet ' + fetch + (fetchClock ? ' · 20 min' : '') + '</small>'));
      assert.match(html, /class="market-line"/);
      const priceDetail = priceClock ? new Date(times.price_time).toISOString() : 'Ikke oplyst af Pluto.';
      const fetchDetail = fetchClock ? new Date(times.fetched_at).toISOString() : 'Ikke oplyst';
      assert.ok(html.includes('Kurstid: ' + priceDetail + '<br>Hentet: ' + fetchDetail + '<br>'));
    }
  }
}

(async () => {
  const price = '2026-11-27T12:04:00+02:00', fetched = '2026-11-27T10:35:00Z';
  await check({price_time: 'invalid', fetched_at: fetched}, null, '11.35');
  await check({price_time: price}, '11.04', null);
  await check({price_time: null, fetched_at: null}, null, null);
  await check({fetched_at: 'invalid'}, null, null);
  await check({price_time: price, fetched_at: fetched}, '11.04', '11.35');
  console.log('PASS MarketUI timestamp evidence in compact quotes and charts (5 cases)');
})().catch(error => { console.error(error); process.exitCode = 1; });
