(async()=>{
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
let dialog=null,trades=[],state;
const document={getElementById:id=>id==='dashboard-detail'?dialog:id==='content'?{append:n=>{dialog=n}}:null,createElement:()=>({innerHTML:'',showModal(){},querySelector:()=>({focus(){}})})};
const ctx={window:{MarketUI:{slot:()=>'',mount(){}},TradeUI:{assetActions:a=>{trades.push(a);return '<div>Scoped trade actions</div>'}}},document,Intl,Number,String,Date,console};
vm.runInNewContext(fs.readFileSync('static/dashboard-ui.js','utf8'),ctx);const ui=ctx.window.DashboardUI;
const money=n=>({amount:String(n),currency:'USD'}),row=(id)=>({key:'scope-'+id,portfolio_id:id,portfolio_name:'Depot '+id,portfolio_kind:id===1?'portfolio':'collection',ticker:'TEST',name:'Synthetic asset',asset_id:'same',quantity:'1',price:money(30),value:money(30),average_entry:money(20),cost_basis:money(20),unrealized:money(10),unrealized_percent:'50',hot_watch:{},verification:'broker_snapshot',conflicts:[],missing:{},raw:{},snapshot_at:'2026-11-09T20:00:00Z'});
const one=row(1),two=row(2),group={...one,key:'asset:same',portfolio_id:null,portfolio_kind:'combined',portfolio_name:'Samlet · 2 depoter',member_keys:[one.key,two.key],quantity:'2',value:money(60),cost_basis:money(40),unrealized:money(20)};
state={dashboard:{positions:[one,two],overview_positions:[group],accounts:[],totals:[],warnings:[],orders:[],critical_sessions:[]}};
ui.setup({api:()=>{throw Error('UI grouping must not call the broker')},escape:v=>String(v),formatTime:v=>v||'Ukendt',formatQuantity:String,state:()=>state});
let html=ui.render(state),holdings=html.slice(html.indexOf('dash-holdings'));
assert.equal((holdings.match(/data-dashboard-key=/g)||[]).length,1);assert.match(holdings,/Antal 2 · Gns/);assert.match(holdings,/2 depoter · se signaler/);assert.match(holdings,/data-dashboard-open="2"/);
await ui.click({hasAttribute:()=>false,dataset:{dashboardOpen:'2'}});assert.match(dialog.innerHTML,/samlet beholdning/);assert.match(dialog.innerHTML,/Vægtet gennemsnitskurs/);assert.match(dialog.innerHTML,/Depot 1/);assert.match(dialog.innerHTML,/Depot 2/);assert.equal(trades.length,0);
assert.match(dialog.innerHTML,/data-dashboard-member="scope-2"/);await ui.click({hasAttribute:()=>false,dataset:{dashboardMember:'scope-2'}});assert.equal(trades.length,1);assert.equal(trades[0].portfolioId,2);assert.equal(trades[0].assetId,'same');
html=ui.portfolioHoldings(1);assert.match(html,/data-dashboard-key="scope-1"/);assert.doesNotMatch(html,/asset:same|scope-2|samlet beholdning/);
html=ui.portfolioHoldings(2);assert.match(html,/data-dashboard-key="scope-2"/);assert.doesNotMatch(html,/scope-1/);
// The attention row still opens the exact lot, even after holdings resets its
// index registry to include the aggregated overview row.
one.action='SÆLG';html=ui.render(state);assert.match(html,/Vurdering: SÆLG/);await ui.click({hasAttribute:()=>false,dataset:{dashboardOpen:'0'}});assert.equal(trades.at(-1).portfolioId,1);
console.log('PASS: combined overview, per-account drill-down and unchanged scoped trade selection');

})().catch(e=>{console.error(e);process.exitCode=1});
