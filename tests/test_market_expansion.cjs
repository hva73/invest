const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
let dialog=null,actions=null;
const source={dataset:{marketReport:'',marketCandidate:'',marketPortfolio:'',marketPosition:'',marketTest:'false',marketHoldingPortfolio:'42',marketHoldingAsset:'asset-a',marketMarkers:JSON.stringify([{kind:'entry',value:12,currency:'DKK'}])},querySelectorAll:()=>[button]};
const button={hasAttribute:name=>name==='data-market-expand',closest:()=>source};
const document={hidden:false,querySelector:s=>s==='#market-chart-dialog'?dialog:s==='#content'?{append(n){dialog=n}}:null,querySelectorAll:()=>[],createElement:()=>({setAttribute(){},addEventListener(){},showModal(){this.open=true}}),addEventListener(){}};
const escape=v=>String(v??'').replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;');
const ctx={document,window:{TradeUI:{assetActions(v){actions=v;return ''}}},setInterval(){},Intl,Date,Map,JSON,innerHeight:900,console};
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../static/market-ui.js'),'utf8'),ctx);
const ui=ctx.window.MarketUI;ui.setup({api(){throw Error('unexpected request')},escape,formatAmount:String,formatTime:String,owner:()=> 'owner',connected:()=>false,now:()=>Date.now(),age:()=>({tone:'fresh'})});
(async()=>{await ui.click(button);assert(dialog.open);assert.match(dialog.innerHTML,/data-market-holding-portfolio="42"/);assert.match(dialog.innerHTML,/data-market-holding-asset="asset-a"/);assert.match(dialog.innerHTML,/&quot;kind&quot;:&quot;entry&quot;/);assert.equal(actions.portfolioId,'42');assert.equal(actions.position,true);console.log('PASS: expanded chart retains portfolio, asset and verified markers');})().catch(e=>{console.error(e);process.exitCode=1});

function quoteFixture() {
  let account = 'A', paints = 0;
  const timers = [], reads = [];
  const node = {
    dataset: {...source.dataset, marketTest: 'true', marketLayout: 'quote'},
    isConnected: true,
    classList: {toggle() {}},
    set innerHTML(html) { this.html = html; paints++; },
    getBoundingClientRect: () => ({top: 0, bottom: 100})
  };
  const context = {
    window: {}, document: {...document, querySelectorAll: () => [node]}, innerHeight: 900,
    setInterval() {}, setTimeout(callback, delay) { timers.push({callback, delay}); }
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../static/market-ui.js'),'utf8'), context);
  const market = context.window.MarketUI;
  market.setup({
    owner: () => account, connected: () => true, now: () => 1000, escape,
    age: () => ({tone: 'fresh'}), formatAmount: v => String(v.amount), formatTime: String,
    api: (route, payload) => new Promise((resolve, reject) => {
      assert.equal(route, 'market/quote');
      reads.push({resolve, reject, period: payload.period});
    })
  });
  market.mount();
  return {
    node, timers, reads, paints: () => paints,
    select: period => market.click({dataset: {marketPeriod: period}, closest: () => node, hasAttribute: () => false}),
    remount() { for (account of ['B', 'A']) market.mount(); },
    fire(delay) {
      assert.deepStrictEqual(timers.map(timer => timer.delay), [delay]);
      timers.shift().callback();
    }
  };
}

async function checkQuoteCallbacks() {
  const quote = {price: 42, fetched_at: '2026-11-27T10:00:00Z', ticker: 'CURRENT'};
  const settled = () => new Promise(resolve => setImmediate(resolve));
  for (const kind of ['retry', 'period']) {
    for (const stale of [true, false]) {
      const f = quoteFixture();
      await f.select('day');
      if (kind === 'period') await f.select('month');
      f.reads[0].resolve(kind === 'retry' ? {pending: true} : quote);
      await settled();
      if (stale) f.remount();
      const paints = f.paints();
      f.fire(kind === 'retry' ? 2000 : 0);
      if (stale) {
        assert.equal(f.reads.length, 1, 'obsolete ' + kind + ' started a read');
        assert.equal(f.paints(), paints, 'obsolete ' + kind + ' painted replacement');
      } else {
        assert.equal(f.reads.length, 2);
        assert.equal(f.reads[1].period, kind === 'retry' ? 'ONE_WEEK' : 'ONE_MONTH');
        f.reads[1].resolve(quote);
        await settled();
        assert.match(f.node.html, /CURRENT/);
      }
    }
  }
  for (const outcome of ['pending', 'error', 'success']) {
    const f = quoteFixture();
    await f.select('day');
    await f.select('month');
    f.remount();
    await f.select('day');
    f.reads[1].resolve(quote);
    await settled();
    const paints = f.paints();
    if (outcome === 'error') f.reads[0].reject(new Error('obsolete'));
    else f.reads[0].resolve(outcome === 'pending' ? {pending: true} : {...quote, ticker: 'OLD'});
    await settled();
    assert.equal(f.paints(), paints, outcome + ' repainted replacement');
    assert.equal(f.timers.length, 0, outcome + ' scheduled a continuation');
    assert.equal(f.reads.length, 2);
    assert.match(f.node.html, /CURRENT/);
  }
  console.log('PASS: stale quote completions and timers are isolated across A→B→A; current retries and period changes complete');
}
checkQuoteCallbacks().catch(error => { console.error(error); process.exitCode = 1; });
