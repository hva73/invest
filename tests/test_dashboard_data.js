const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const ctx={window:{},Intl,Number,String,Date,console};vm.runInNewContext(fs.readFileSync('static/dashboard-ui.js','utf8'),ctx);
const ui=ctx.window.DashboardUI;ui.setup({api:()=>{},escape:v=>String(v),formatTime:v=>v||'Ukendt',formatQuantity:v=>String(v),state:()=>({})});
const row={key:'x',ticker:'TEST',name:'Test',portfolio_name:'Test depot',critical:false,verification:'broker_snapshot',price:{amount:'10',currency:'DKK'},value:{amount:'20',currency:'DKK'},unrealized:{amount:'-2',currency:'DKK'},unrealized_percent:'-10',unrealized_estimated:true,conflicts:[],hot_watch:{},analysis_freshness:{}};
const state={dashboard:{positions:[row],accounts:[],totals:[],warnings:[],orders:[],critical_sessions:[]},report_desk:null};
let html=ui.render(state);assert.match(html,/Estimat/);assert.match(html,/dash-change negative/);assert.doesNotMatch(html,/<th scope="col">I dag<\/th>/);assert.doesNotMatch(html,/<th scope="col">Vurdering<\/th>/);
row.daily={percent:'2',amount:'1',currency:'DKK',basis:'pluto_reported_daily_change',from:null,to:'2026-11-05T12:00:00Z'};html=ui.render(state);assert.match(html,/<th scope="col">I dag<\/th>/);assert.match(html,/dash-change positive/);
row.hot_watch={session:{watch_id:'synthetic-watch',signal:'WAIT',display_status:'AFVENT'}};html=ui.render(state);assert.match(html,/data-dashboard-watch="synthetic-watch"/);assert.match(html,/AFVENT/);
console.log('PASS: estimated result is labeled, signed values are colored, empty columns are omitted');
