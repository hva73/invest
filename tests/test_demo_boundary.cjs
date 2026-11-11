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
 assert(state.dashboard.portfolio_value_history.periods.day.length>1);
 const sectors=await (await window.fetch('/api/sector-intelligence')).json();
 assert(sectors.dashboard.positions.some(p=>p.sector_intelligence.sector==='Teknologi'));
 assert.equal((await window.fetch('https://other.invalid/api/state')).status,403);
 assert.equal((await window.fetch('/api/user/profile')).status,403);
 const order=await (await window.fetch('/api/trade/send',{method:'POST',body:'{}'})).json();
 assert.equal(order.proposal.response.status,'SIMULERET');assert.equal(realCalls,0);
 console.log('PASS: fixture-only demo, blocked unknown routes and simulated order without network');
})().catch(e=>{console.error(e);process.exitCode=1});
