/* Demo fetches use local fixtures, never the original browser fetch. */
const fs=require('fs'),vm=require('vm'),assert=require('assert');
let realCalls=0;
const window={fetch(){realCalls++;throw Error('Unexpected network request')}};
const ctx={window,location:{href:'https://demo.invalid/demo',origin:'https://demo.invalid'},URL,Response,JSON,Date,Math,Number,String,Array,Object,console};
vm.runInNewContext(fs.readFileSync('static/demo-data.js','utf8'),ctx);
(async()=>{
 const session=await (await window.fetch('/api/session')).json();
 assert.equal(session.authenticated,true);assert.equal(session.user.username,'demo');
 const state=await (await window.fetch('/api/state')).json();
 assert.equal(state.connection.trade_access,false);
 assert(state.dashboard.positions.every(p=>p.asset_id.startsWith('synthetic-')));
 const positions=state.dashboard.positions;
 assert.equal(positions.reduce((n,p)=>n+Number(p.cost_basis.amount),0),50000);
 assert.equal(positions.reduce((n,p)=>n+Number(p.value.amount),0),52080);
 assert.equal(Number(state.dashboard.totals[0].amount),52080);
 assert.equal(Number(state.dashboard.portfolio_value_history.reported_result.amount),2080);
 assert(positions.some(p=>p.hot_watch.session?.display_status==='KØBSSIGNAL'));
 assert(positions.some(p=>p.hot_watch.session?.display_status==='SÆLGSSIGNAL'));
 assert(positions.some(p=>Number(p.unrealized.amount)<0)&&positions.some(p=>Number(p.unrealized.amount)>0));
 for(const p of positions){
  assert(Math.abs(Number(p.quantity)*Number(p.price.amount)-Number(p.value.amount))<.01,p.ticker);
  assert(Math.abs(Number(p.value.amount)-Number(p.cost_basis.amount)-Number(p.unrealized.amount))<.01,p.ticker);
  assert(Math.abs(Number(p.unrealized_percent)-100*Number(p.unrealized.amount)/Number(p.cost_basis.amount))<1e-8);
  const series=['ONE_WEEK','ONE_MONTH','ONE_YEAR'].map(period=>window.ESCAPE_DEMO_HISTORY.period(p,period));
  const day=series[0].filter(x=>x.epoch>series[0].at(-1).epoch-86400);
  assert(day.length>=100&&day.length<=300,`${p.ticker} day ${day.length}`);
  for(const [i,rows] of series.entries()){
   assert(rows.length>=100&&rows.length<=365,`${p.ticker} period ${i}: ${rows.length}`);
   assert(rows.every((x,j)=>j===0||x.epoch>rows[j-1].epoch));
   assert.equal(Number(rows.at(-1).price),Number(p.price.amount));
   const diffs=rows.slice(1).map((x,j)=>Number(x.price)-Number(rows[j].price));
   assert(diffs.some(x=>x>0)&&diffs.some(x=>x<0));
   if(!['BTC','PEPE'].includes(p.ticker)){
    const zone=['ASML'].includes(p.ticker)?'Europe/Amsterdam':['NOVOB','GMAB'].includes(p.ticker)?'Europe/Copenhagen':'America/New_York';
    const fmt=new Intl.DateTimeFormat('en-US',{timeZone:zone,weekday:'short',hour:'2-digit',minute:'2-digit',hourCycle:'h23'});
    for(const x of rows){const parts=Object.fromEntries(fmt.formatToParts(new Date(x.timestamp)).map(v=>[v.type,v.value]));const minute=Number(parts.hour)*60+Number(parts.minute);assert(!['Sat','Sun'].includes(parts.weekday));assert(minute>=(zone==='America/New_York'?570:540)&&minute<=(zone==='America/New_York'?960:1020));}
   }
  }
  const common=new Map(series[0].map(x=>[x.epoch,x.price]));
  for(const rows of series.slice(1))for(const x of rows)if(common.has(x.epoch))assert.equal(x.price,common.get(x.epoch));
 }
 const points=state.dashboard.portfolio_value_history.periods.day;
 assert(points.length>=20);assert(new Set(points.map(p=>p.reported_result)).size>10);
 const deltas=points.slice(1).map((p,i)=>Number(p.reported_result)-Number(points[i].reported_result));
 assert(deltas.some(x=>x<0)&&deltas.some(x=>x>0));
 for(const key of ['day','week','month','year']){const chart=state.dashboard.portfolio_value_history.periods[key];assert(chart.length>=100);assert.equal(Number(chart.at(-1).amount),52080);assert.equal(Number(chart.at(-1).reported_result),2080);}
 assert(Math.abs(positions.reduce((n,p)=>n+Number(p.daily.amount),0)-Number(state.dashboard.daily_result.amount))<.01);
 for(const ticker of ['NOVOB','TSLA']){const p=positions.find(x=>x.ticker===ticker),response=await (await window.fetch('/api/v1/hotwatch/sessions/demo-'+ticker+'/samples')).json(),samples=response.items;assert.equal(samples.length,100);assert.equal(Number(samples[0].data.price),Number(p.price.amount));assert(samples.every((x,i)=>!i||Date.parse(x.data.event_time)<Date.parse(samples[i-1].data.event_time)));const movement=Number(samples[0].data.price)/Number(samples[3].data.price)-1;assert(ticker==='NOVOB'?movement>0:movement<0);assert(Math.abs(Number(p.hot_watch.session.latest_calculation.supporting_metrics.return_3_pct)-movement*100)<.0001);}
 const sectors=await (await window.fetch('/api/sector-intelligence')).json();
 assert(sectors.dashboard.positions.some(p=>p.sector_intelligence.sector==='Teknologi'));
 assert.equal((await window.fetch('https://other.invalid/api/state')).status,403);
 assert.equal((await window.fetch('/api/user/profile')).status,403);
 const order=await (await window.fetch('/api/trade/send',{method:'POST',body:'{}'})).json();
 assert.equal(order.proposal.response.status,'SIMULERET');assert.equal(realCalls,0);
 console.log('PASS: fixture-only demo, blocked unknown routes and simulated order without network');
})().catch(e=>{console.error(e);process.exitCode=1});
