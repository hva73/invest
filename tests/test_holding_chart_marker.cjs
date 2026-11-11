const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
let metadata,dialog;
const document={getElementById(id){if(id==='dashboard-detail')return dialog;if(id==='content')return {append(x){dialog=x}};return null},createElement(){return {showModal(){},querySelector(){return {focus(){}}}}}};
const window={MarketUI:{slot(data){metadata=data;return ''},mount(){}},TradeUI:{assetActions(){return ''}}};
const row={key:'p',ticker:'TEST',name:'Test',portfolio_id:7,portfolio_name:'Test depot',asset_id:'test-id',average_entry:{amount:'10',currency:'DKK'},price:{amount:'11',currency:'DKK'},quantity:'2',conflicts:[],missing:{},raw:{},hot_watch:{},analysis_freshness:{},verification:'broker_snapshot'};
const state={user:{username:'test'},dashboard:{positions:[row],accounts:[],totals:[],warnings:[],orders:[],critical_sessions:[]}};
const ctx={window,document,Intl,Number,String,Date,console};vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../static/dashboard-ui.js'),'utf8'),ctx);
const ui=window.DashboardUI;ui.setup({api(){},escape:v=>String(v),formatTime:v=>v||'Ukendt',formatQuantity:String,state:()=>state});
(async()=>{ui.render(state);await ui.click({dataset:{dashboardOpen:'0'},hasAttribute(){return false}});assert.equal(metadata.holding_portfolio_id,7);assert.equal(metadata.holding_asset_id,'test-id');assert.equal(metadata.markers.length,1);assert.equal(metadata.markers[0].value,'10');assert.equal(metadata.markers[0].currency,'DKK');row.average_entry=null;ui.render(state);await ui.click({dataset:{dashboardOpen:'0'},hasAttribute(){return false}});assert.equal(metadata.markers.length,0);console.log('PASS: holding entry marker uses actual broker value and currency');})().catch(e=>{console.error(e);process.exitCode=1});
