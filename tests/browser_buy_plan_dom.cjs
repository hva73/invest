/* Deterministic DOM interaction test; jsdom is a development-only dependency.
 * Usage: NODE_PATH=/path/to/jsdom/node_modules node tests/browser_buy_plan_dom.cjs fixture.json
 * fixture.json is produced from a disposable BuyPlan test session. No network.
 */
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {JSDOM}=require('jsdom');
const fixture=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
const dom=new JSDOM('<!doctype html><html><body><main id="content"></main></body></html>',{url:'http://synthetic.invalid',runScripts:'outside-only'});
const w=dom.window;
w.HTMLDialogElement.prototype.showModal=function(){this.open=true};
w.HTMLDialogElement.prototype.close=function(){this.open=false};
w.HTMLElement.prototype.scrollIntoView=function(){};
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const session=fixture.session,calls=[],pid=fixture.portfolios.find(p=>p.kind==='portfolio').id;
const plan={portfolio_id:pid,budget_dkk:'701',limit_price:'100',stop_price:'95',quantity:'1.00000000',fresh:true,verified_at:new Date().toISOString()};
const state={...fixture,dashboard:{positions:[]},portfolio_snapshots:{}};
async function api(route,data){
 calls.push([route,data]);
 if(route==='state')return state;
 if(route.includes('/buy-plan')){session.buy_plan=plan;return {ok:true,read_only:true,plan,note:'Afventer nye markedsobservationer og risikokontrol.'}}
 if(route.includes('/samples'))return {items:[]};
 if(route.includes('/events'))return {items:[]};
 if(route.startsWith('v1/hotwatch/sessions/'))return {session};
 if(route==='trade/estimate')return {proposal:{id:1,status:'estimated',review_token:'synthetic',estimate:{}}};
 if(route==='trade/send')return {proposal:{id:1,status:'sent'}};
 throw Error('Unexpected or unmocked API: '+route);
}
for(const file of ['trade-ui.js','engine-ui.js'])w.eval(fs.readFileSync(path.join(__dirname,'../static',file),'utf8'));
w.TradeUI.setup({api,escape:esc,formatTime:v=>v,updated(){},getState:()=>state});
w.EngineUI.setup({api,escape:esc,formatTime:v=>v,formatAmount:v=>String(v?.amount||v||''),owner:()=>fixture.user.username,isAdmin:()=>true,editing:()=>false});
(async()=>{
 await w.EngineUI.openDetail(session.watch_id);
 assert.equal(w.document.querySelectorAll('#engine-buy-plan').length,1);
 let form=w.document.getElementById('engine-buy-plan');
 assert.equal(form.elements.budget_dkk.value,'');
 form.closest('details').open=true;
 for(const [k,v] of Object.entries({portfolio_id:String(pid),budget_dkk:'701',limit_price:'100',stop_price:'95'}))form.elements[k].value=v;
 await w.EngineUI.submit({target:form,preventDefault(){}});
 const saved=calls.find(([route])=>route.includes('/buy-plan'));
 assert.deepEqual(JSON.parse(JSON.stringify(saved[1])),{portfolio_id:pid,budget_dkk:'701',limit_price:'100',stop_price:'95'});
 assert.equal(w.document.querySelectorAll('#engine-buy-plan').length,1);
 assert.equal(calls.filter(([r])=>r.startsWith('trade/')).length,0);
 w.TradeUI.openQuick({report_id:'@hotwatch',candidate_id:session.watch_id,asset_id:session.request.asset_id,ticker:session.request.ticker,signal:'BUY',risk_plan:plan});
 form=w.document.getElementById('quick-trade-form');
 for(const name of ['portfolio_id','currency','size'])assert.equal(form.elements[name].disabled,true);
 assert.match(form.textContent,/LIMIT 100/);
 await w.TradeUI.submit({target:form,preventDefault(){}});
 const estimate=calls.find(([route])=>route==='trade/estimate')[1];
 assert.equal(estimate.size,'1.00000000');assert.equal(estimate.size_mode,'shares');assert.equal(estimate.order_type,'LIMIT');assert.equal(estimate.limit_price,'100');assert.equal(estimate.currency,'DKK');assert.equal(String(estimate.portfolio_id),String(pid));
 assert.equal(calls.filter(([r])=>r==='trade/send').length,1);
 assert.match(w.document.getElementById('quick-trade-review').textContent,/Åbn Pluto/);
 console.log('PASS: DOM buy-plan form, read-only preparation, fixed LIMIT proposal and explicit send (all APIs mocked)');
 w.close();
})().catch(e=>{console.error(e);w.close();process.exitCode=1});
