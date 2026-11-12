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
 for(const [ticker,side] of [['TSLA','SELL'],['NOVOB','BUY']]){const p=positions.find(p=>p.ticker===ticker),s=p.hot_watch.session;assert.equal(s.last_action_signal.event_type,side+'_SIGNAL');assert.equal(s.last_action_signal.state,'ACTIVE');assert.equal(s.data_status.market_status,'OPEN');assert.equal(s.data_status.price_status,'FRESH');assert.equal(s.latest_context.status,'verified');assert.equal(s.latest_context.tradability,'available');assert.equal(s.request.portfolio_ids.length,1);assert(state.portfolios.some(a=>a.kind==='portfolio'&&String(a.id)===String(s.request.portfolio_ids[0])&&a.can_trade))}
 const tsla=positions.find(p=>p.ticker==='TSLA');
 for(const pct of [50,100]){const body=JSON.stringify({asset_id:tsla.asset_id,portfolio_id:tsla.portfolio_id,size_mode:'percent',size:String(pct),currency:'DKK'});const estimate=await (await window.fetch('/api/trade/estimate',{method:'POST',body})).json();assert.equal(Number(estimate.proposal.sell_basis.quantity),Number(tsla.quantity));assert.equal(Number(estimate.proposal.sell_basis.shares),Number(tsla.quantity)*pct/100);assert.equal(Number(estimate.proposal.payload.orders[0].shares),Number(tsla.quantity)*pct/100)}
 const points=state.dashboard.portfolio_value_history.periods.day;
 assert(points.length>=20);assert(new Set(points.map(p=>p.reported_result)).size>10);
 const deltas=points.slice(1).map((p,i)=>Number(p.reported_result)-Number(points[i].reported_result));
 assert(deltas.some(x=>x<0)&&deltas.some(x=>x>0));
 for(const key of ['day','week','month','year']){const chart=state.dashboard.portfolio_value_history.periods[key];assert(chart.length>=100);assert.equal(Number(chart.at(-1).amount),52080);assert.equal(Number(chart.at(-1).reported_result),2080);}
 assert(Math.abs(positions.reduce((n,p)=>n+Number(p.daily.amount),0)-Number(state.dashboard.daily_result.amount))<.01);
 for(const ticker of ['BTC','TSLA']){const p=positions.find(x=>x.ticker===ticker),q=await (await window.fetch('/api/market/quote',{method:'POST',body:JSON.stringify({holding_asset_id:p.asset_id,period:'ONE_WEEK'})})).json();assert.equal(q.asset_type,ticker==='BTC'?'CRYPTO':'CS');assert.equal(Number(q.price),Number(q.series.at(-1).price));assert.equal(Number(q.daily_change_percent),Number(p.daily.percent));assert(Math.abs(Number(q.week_change_percent)-(Number(q.series.at(-1).price)/Number(q.series[0].price)-1)*100)<1e-9);}
 for(const ticker of ['NOVOB','TSLA']){const p=positions.find(x=>x.ticker===ticker),response=await (await window.fetch('/api/v1/hotwatch/sessions/demo-'+ticker+'/samples')).json(),samples=response.items;assert.equal(samples.length,100);assert.equal(Number(samples[0].data.price),Number(p.price.amount));assert(samples.every((x,i)=>!i||Date.parse(x.data.event_time)<Date.parse(samples[i-1].data.event_time)));const movement=Number(samples[0].data.price)/Number(samples[3].data.price)-1;assert(ticker==='NOVOB'?movement>0:movement<0);assert(Math.abs(Number(p.hot_watch.session.latest_calculation.supporting_metrics.return_3_pct)-movement*100)<.0001);}
 const closed={TSLA:['2025-11-27','2025-12-25','2026-01-01','2026-01-19','2026-02-16','2026-04-03','2026-05-25','2026-06-19','2026-07-03','2026-09-07'],NOVOB:['2025-12-24','2025-12-25','2025-12-26','2025-12-31','2026-01-01','2026-04-02','2026-04-03','2026-04-06','2026-05-14','2026-05-15','2026-05-25','2026-06-05'],ASML:['2025-12-25','2025-12-26','2026-01-01','2026-04-03','2026-04-06','2026-05-01']};
 for(const [ticker,holidays] of Object.entries(closed)){const p=positions.find(x=>x.ticker===ticker),zone=ticker==='TSLA'?'America/New_York':ticker==='NOVOB'?'Europe/Copenhagen':'Europe/Amsterdam',formatter=new Intl.DateTimeFormat('en-CA',{timeZone:zone,year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'});for(const x of window.ESCAPE_DEMO_HISTORY.history(p)){const date=Object.fromEntries(formatter.formatToParts(new Date(x.timestamp)).map(v=>[v.type,v.value])),day=`${date.year}-${date.month}-${date.day}`,minute=Number(date.hour)*60+Number(date.minute);assert(!holidays.includes(day),`${ticker} traded on ${day}`);if(ticker==='TSLA'&&['2025-11-28','2025-12-24'].includes(day))assert(minute<=780);if(ticker==='ASML'&&['2025-12-24','2025-12-31'].includes(day))assert(minute<=845);}}
 const sectors=await (await window.fetch('/api/sector-intelligence')).json();
 assert(sectors.dashboard.positions.some(p=>p.sector_intelligence.sector==='Teknologi'));
 assert(sectors.markets.every(m=>m.benchmark_currency==='USD'&&m.price_basis==='close'&&m.source==='Fiktive demodata'));
 assert(sectors.dashboard.accounts.every(a=>a.cash_status==='available'&&a.cash_accounts.length===0));
 assert.equal((await window.fetch('https://other.invalid/api/state')).status,403);
 assert.equal((await window.fetch('/api/user/profile')).status,403);
 const order=await (await window.fetch('/api/trade/send',{method:'POST',body:'{}'})).json();
 assert.equal(order.proposal.response.status,'SIMULERET');assert.equal(realCalls,0);
 console.log('PASS: fixture-only demo, blocked unknown routes and simulated order without network');
})().catch(e=>{console.error(e);process.exitCode=1});
