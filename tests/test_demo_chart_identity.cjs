const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const location=new URL('https://demo.invalid/demo'),window={};
const context={window,location,URL,Response,console};
vm.runInNewContext(fs.readFileSync('static/demo-data.js','utf8'),context);
async function call(payload){return window.fetch('/api/market/quote',{method:'POST',body:JSON.stringify(payload)});}
(async()=>{
 const d=window.ESCAPE_DEMO_DATA.state.dashboard,h=d.portfolio_value_history;
 assert.equal(h.day_start,'2026-11-05T23:00:00.000Z');assert.equal(h.day_end,'2026-11-06T23:00:00.000Z');assert.equal(h.as_of,'2026-11-06T21:00:00.000Z');
 assert(h.periods.day.length>1);assert(h.periods.day.every(p=>Date.parse(p.at)>=Date.parse(h.day_start)&&Date.parse(p.at)<=Date.parse(h.as_of)));
 for(const [portfolio,ticker] of [[2,'NOVOB'],[1,'TSLA'],[1,'BTC'],[2,'BTC']]){
  const r=await call({holding_portfolio_id:portfolio,holding_asset_id:'synthetic-asset-'+ticker,period:'ONE_WEEK'});
  assert.equal(r.status,200);const q=await r.json();assert.equal(q.ticker,ticker);assert.equal(q.asset_id,'synthetic-asset-'+ticker);assert(q.series.length>1);
 }
 const report_id='design-acceptance-report';
 const r=await call({report_id,candidate_id:'synthetic-candidate-PLTR',period:'ONE_WEEK'});
 assert.equal(r.status,200);const q=await r.json();assert.equal(q.ticker,'PLTR');assert.equal(q.asset_id,'synthetic-asset-PLTR');assert.equal(q.price,'900');assert(q.series.length>1);
 const held=await call({report_id,candidate_id:'synthetic-candidate-FCX'});assert.equal((await held.json()).ticker,'FCX');
 const reported=await call({report_id,portfolio_id:'test-main',position_id:'test-main.TSLA'});assert.equal((await reported.json()).ticker,'TSLA');
 for(const bad of [
  {holding_portfolio_id:1,holding_asset_id:'synthetic-asset-NOVOB'},
  {holding_portfolio_id:1,holding_asset_id:'synthetic-asset-TSLA',asset_id:'synthetic-asset-NOVOB'},
  {report_id,candidate_id:'unknown'},
  {report_id:'wrong',candidate_id:'synthetic-candidate-PLTR'},
  {report_id,portfolio_id:'test-child',position_id:'test-main.TSLA'},
  {asset_id:'synthetic-asset-TSLA'},{}
 ])assert.equal((await call(bad)).status,404,JSON.stringify(bad));
 assert.equal((await window.fetch('https://external.invalid/api/market/quote')).status,403);
 console.log('PASS: demo calendar-day fixture, holding/position/candidate identity and no fallback to unrelated asset');
})().catch(e=>{console.error(e);process.exitCode=1});
