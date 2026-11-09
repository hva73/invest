const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const esc=v=>String(v).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
const nodes=[{dataset:{engineAck:'synthetic-watch',eventId:'hw-'+'a'.repeat(24),isTest:'false'},disabled:false,textContent:''},{disabled:false,textContent:''}],calls=[];
const ctx={window:{},document:{getElementById:()=>null,querySelectorAll:()=>nodes},Intl,Date,Number,String,console};
vm.runInNewContext(fs.readFileSync('static/engine-ui.js','utf8'),ctx);
ctx.window.EngineUI.setup({escape:esc,formatTime:String,owner:()=>1,api:async(path,body)=>{calls.push([path,body]);return {ok:true}}});
vm.runInNewContext(fs.readFileSync('static/dashboard-ui.js','utf8'),ctx);
const s={watch_id:'synthetic-watch',is_test:false,status:'ACTIVE',signal:'SELL',display_status:'SÆLGSSIGNAL',last_calculation_at:'2026-11-09T18:32:39Z',last_action_signal:{event_id:'hw-'+'a'.repeat(24),event_type:'SELL_SIGNAL',created:'2026-11-09T18:32:39Z',reason:'TRAILING_EXIT <unsafe>',state:'ACTIVE',acknowledged_at:null}};
const row={key:'one',portfolio_id:1,portfolio_name:'Test',ticker:'JDZG',name:'SYNTHETIC',quantity:'10',price:{amount:'0.3',currency:'USD'},value:{amount:'3',currency:'USD'},conflicts:[],hot_watch:{session:s}};
const state={dashboard:{positions:[row],accounts:[],totals:[],issues:[],warnings:[],orders:[],critical_sessions:[]},portfolios:[],test_trade_signal:null};
ctx.window.DashboardUI.setup({escape:esc,formatTime:String,formatQuantity:String,state:()=>state});
for(const [signal,label,phase] of [['SELL','SÆLGSSIGNAL','ACTIVE'],['WAIT','AFVENT','WITHDRAWN'],['NO_DATA','DATA FOR GAMLE','DATA_MISSING']]){
 s.signal=signal;s.display_status=label;s.status=signal==='NO_DATA'?'DEGRADED':'ACTIVE';s.last_action_signal.state=phase;
 const html=ctx.window.DashboardUI.render(state),attention=html.match(/<section class="panel dash-attention">[\s\S]*?<\/section>/)[0];
 assert.match(attention,/TRAILING_EXIT &lt;unsafe>/);assert.match(attention,/18:32:39/);assert.match(attention,/data-engine-ack/);
 assert.ok(attention.includes({ACTIVE:'AKTIVT',WITHDRAWN:'BORTFALDET',DATA_MISSING:'DATA MANGLER'}[phase]));
 if(phase!=='ACTIVE'){assert.doesNotMatch(attention,/data-trade-watch/);assert.match(attention,/ikke et aktuelt handelssignal/)}
}
s.last_action_signal.acknowledged_at='2026-11-09T18:40:00Z';
const html=ctx.window.DashboardUI.render(state),attention=html.match(/<section class="panel dash-attention">[\s\S]*?<\/section>/)[0];assert.doesNotMatch(attention,/signal-notice/);assert.match(html,/Kvitteret/);
(async()=>{await ctx.window.EngineUI.click(nodes[0]);assert.equal(calls.length,1);assert.equal(calls[0][0],'v1/hotwatch/sessions/synthetic-watch/ack-signal');assert.equal(calls[0][1].event_id,'hw-'+'a'.repeat(24));assert.equal(calls[0][1].is_test,false);assert.ok(nodes.every(n=>n.disabled&&n.textContent==='Kvitteret'));console.log('PASS: shared warning rendering, active/withdrawn/missing separation, escaped reason, exact-event acknowledgement, no trade action')})().catch(e=>{console.error(e);process.exitCode=1});
