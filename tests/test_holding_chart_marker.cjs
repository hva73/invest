const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
let metadata,dialog;
const document={querySelector(){return null},getElementById(id){if(id==='dashboard-detail')return dialog;if(id==='content')return {append(x){dialog=x}};return null},createElement(){return {showModal(){},querySelector(){return {focus(){}}}}}};
const window={MarketUI:{slot(data){metadata=data;return ''},mount(){}},TradeUI:{assetActions(){return ''}}};
const row={key:'p',ticker:'TEST',name:'Test',portfolio_id:7,portfolio_name:'Test depot',asset_id:'test-id',average_entry:{amount:'10',currency:'DKK'},price:{amount:'11',currency:'DKK'},quantity:'2',conflicts:[],missing:{},raw:{},hot_watch:{},analysis_freshness:{},verification:'broker_snapshot'};
const state={user:{username:'test'},dashboard:{positions:[row],accounts:[],totals:[],warnings:[],orders:[],critical_sessions:[]}};
const ctx={window,document,Intl,Number,String,Date,console};vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../static/dashboard-ui.js'),'utf8'),ctx);
const ui=window.DashboardUI;ui.setup({api(){},escape:v=>String(v),formatTime:v=>v||'Ukendt',formatQuantity:String,state:()=>state});
const validStamp='2026-07-01T23:45:00Z';
for(const [price_time,snapshot_at,expected] of [
  ['invalid',validStamp,'—'],
  [null,'invalid','Hentet —'],
  [validStamp,null,'02.07.2026, 01.45'],
  [null,validStamp,'Hentet 02.07.2026, 01.45'],
  [null,null,'Kurstid ukendt'],
]){
  const dashboard={...state.dashboard,positions:[{...row,price_time,snapshot_at}]};
  const markup=ui.render({...state,dashboard});
  assert.equal(markup.match(/<td class="dash-price">.*?<small title="[^"]*">([^<]*)<\/small>/)?.[1],expected);
}
function testObservationNote(session){
  function render(change_pct, window_minutes, kind='RISING'){
    session.market_observation={kind,change_pct,window_minutes};
    return ui.render(state);
  }
  for(const change of [null,undefined,'','  ',false,true,0,'0',-1,'-0.5',NaN,Infinity,-Infinity,'Infinity','abc',[1]]){
    assert.doesNotMatch(render(change,5),/Stiger /,`invalid change: ${String(change)}`);
  }
  for(const minutes of [null,0,-1,1.5,'5',true,Infinity]){
    assert.doesNotMatch(render(1,minutes),/Stiger /,`invalid window: ${String(minutes)}`);
  }
  assert.doesNotMatch(render(1,5,'FLAT'),/Stiger /);
  for(const change of [1.25,'1.25']){
    const markup=render(change,5);
    assert.match(markup,/Stiger \+1,25 % på 5 min\. · observation/);
    assert.match(markup,/data-dashboard-watch="w"/);
    assert.doesNotMatch(markup,/data-trade-watch="w"/);
  }
  session.display_status='SÆLGSSIGNAL';
  assert.match(render(1.25,5),/data-trade-watch="w" data-trade-signal="SELL"/);
  session.display_status='AFVENT';
  delete session.market_observation;
}
(async()=>{ui.render(state);await ui.click({dataset:{dashboardOpen:'0'},hasAttribute(){return false}});assert.equal(metadata.holding_portfolio_id,7);assert.equal(metadata.holding_asset_id,'test-id');assert.equal(metadata.markers.length,1);assert.equal(metadata.markers[0].value,'10');assert.equal(metadata.markers[0].currency,'DKK');row.average_entry=null;row.hot_watch.session={status:'ACTIVE',signal:'SELL',display_status:'AFVENT',watch_id:'w'};ui.render(state);await ui.click({dataset:{dashboardOpen:'0'},hasAttribute(){return false}});assert.equal(metadata.markers.length,0);assert.match(dialog.innerHTML,/Aktuel HOT WATCH-status<\/dt><dd>AFVENT/);assert.doesNotMatch(dialog.innerHTML,/Motorens seneste signal<\/dt><dd>SELL/);testObservationNote(row.hot_watch.session);state.dashboard.positions.push({...row,key:'b',ticker:'AAA',name:'Zulu',hot_watch:{}});row.name='Alpha';row.ticker='ZZZ';ui.changeSort({target:{id:'dashboard-sort',value:'name'}});const markup=ui.render(state);assert(markup.indexOf('>ZZZ</strong>')<markup.indexOf('>AAA</strong>'));console.log('PASS: entry marker, current signal status and name sorting');})().catch(e=>{console.error(e);process.exitCode=1});
