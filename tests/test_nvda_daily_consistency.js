const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const ctx={window:{},document:{getElementById:()=>null},Intl,Date,Number,String,console};
vm.runInNewContext(fs.readFileSync('static/dashboard-ui.js','utf8'),ctx);
const ui=ctx.window.DashboardUI;
ui.setup({api:()=>{},escape:String,formatTime:v=>v||'—',formatQuantity:String,state:()=>({})});
const now=new Date().toISOString();
const position={
 key:'nvda',ticker:'NVDA',name:'NVIDIA',portfolio_id:1,portfolio_name:'Hoveddepot',
 quantity:'0.191014966',critical:false,verification:'broker_snapshot',
 price:{amount:'151.81',currency:'USD'},price_time:now,price_freshness:{state:'fresh'},
 snapshot_at:now,value:{amount:'197.54',currency:'DKK'},
 average_entry:{amount:'156.90',currency:'USD'},
 unrealized:{amount:'-6.10',currency:'DKK'},unrealized_percent:'-3.00',
 daily:{percent:'-2.35',amount:'-3.664',currency:'USD',basis:'pluto_reported_daily_change',to:now},
 hot_watch:{},conflicts:[],analysis_freshness:{}
};
const state={dashboard:{positions:[position],accounts:[],totals:[],warnings:[],orders:[],critical_sessions:[]}};
const desktop=()=>ui.render(state).match(/<span class="dash-day-desktop">([\s\S]*?)<\/span><\/button>/)?.[1]||'';
let html=ui.render(state),day=desktop();
assert.match(day,/-0,70/);assert.match(day,/-2,35 %/);
assert.doesNotMatch(day,/estimat/,'Pluto-supplied per-share daily amount is not an estimate');
assert.match(html,/mobile-holding-daily negative/);
assert.match(html,/Siden køb/);
position.daily.amount=null;
day=desktop();assert.match(day,/estimat/,'derived daily amount must be labelled estimate');
position.daily.amount='-3.664';
position.price_freshness={state:'stale'};
html=ui.render(state);assert.match(desktop(),/dash-neutral/);
assert.match(html,/mobile-holding-daily neutral/);
assert.doesNotMatch(html,/<span class="dash-day-original"><span class="dash-change negative"/,'stale daily percent must not leak into alternate table markup');
position.price_freshness={state:'fresh'};
position.daily.to=new Date(Date.now()-86400000).toISOString();
assert.match(desktop(),/dash-neutral/,'previous-day percent must be suppressed even when price is fresh');
console.log('PASS: NVDA daily amount/percent provenance and date eligibility are consistent');
