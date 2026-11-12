const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const esc=v=>String(v).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
const decode=v=>v.replaceAll('&quot;','"').replaceAll('&lt;','<').replaceAll('&amp;','&');
const calls=[],icons=[],dialog={dataset:{},innerHTML:'',open:false,showModal(){this.open=true},querySelector(){return {focus(){}}}},nodes=[];
const ctx={window:{},document:{getElementById:id=>id==='engine-dialog'?dialog:null,querySelectorAll:()=>icons},Intl,Date,Number,String,console};
vm.runInNewContext(fs.readFileSync('static/engine-ui.js','utf8'),ctx);
let fail=false;
ctx.window.EngineUI.setup({escape:esc,formatTime:String,owner:()=>1,api:async(path,body)=>{calls.push([path,body]);if(fail)throw Error('offline');return {ok:true}}});
vm.runInNewContext(fs.readFileSync('static/dashboard-ui.js','utf8'),ctx);
const s={watch_id:'synthetic-watch',is_test:false,status:'ACTIVE',signal:'SELL',display_status:'SÆLGSSIGNAL',last_calculation_at:'2026-11-09T18:32:39Z',last_action_signal:{event_id:'hw-'+'a'.repeat(24),event_type:'SELL_SIGNAL',created:'2026-11-09T18:32:39Z',reason:'TRAILING_EXIT <unsafe>',state:'ACTIVE',acknowledged_at:null}};
const row={key:'one',portfolio_id:1,portfolio_name:'Test',ticker:'JDZG',name:'SYNTHETIC',quantity:'10',price:{amount:'0.3',currency:'USD'},value:{amount:'3',currency:'USD'},conflicts:[],hot_watch:{session:s}};
const state={dashboard:{positions:[row],accounts:[],totals:[],issues:[],warnings:[],orders:[],critical_sessions:[]},portfolios:[],test_trade_signal:null};
ctx.window.DashboardUI.setup({escape:esc,formatTime:String,formatQuantity:String,state:()=>state});
const iconOf=html=>({dataset:{engineNotice:decode(html.match(/data-engine-notice="([^"]+)"/)[1])},className:'signal-alert signal-alert--unread',setAttribute(k,v){this[k]=v}});
(async()=>{
 for(const [signal,label,phase] of [['SELL','SÆLGSSIGNAL','ACTIVE'],['WAIT','AFVENT','WITHDRAWN'],['NO_DATA','DATA FOR GAMLE','DATA_MISSING']]){
  s.signal=signal;s.display_status=label;s.status=signal==='NO_DATA'?'DEGRADED':'ACTIVE';s.last_action_signal.state=phase;
  const html=ctx.window.DashboardUI.render(state),attention=(html.match(/<section class="panel dash-attention[^"]*">[\s\S]*?<\/section>/)||[''])[0];
  assert.doesNotMatch(html,/<aside class="signal-notice"|signal-notice-details|data-engine-ack/);
  const source=phase==='ACTIVE'?attention:html;
  if(phase!=='ACTIVE')assert.doesNotMatch(attention,/signal-alert--unread/);
  assert.match(source,/signal-alert--unread/);assert.match(source,/aria-haspopup="dialog"/);
  await ctx.window.EngineUI.click(iconOf(source));
  assert.equal(dialog.open,true);assert.match(dialog.innerHTML,/TRAILING_EXIT &lt;unsafe>/);assert.match(dialog.innerHTML,/18:32:39/);assert.match(dialog.innerHTML,/data-engine-ack/);
  assert.ok(dialog.innerHTML.includes({ACTIVE:'AKTIVT',WITHDRAWN:'BORTFALDET',DATA_MISSING:'DATA MANGLER'}[phase]));
  if(phase!=='ACTIVE'){assert.doesNotMatch(attention,/data-trade-watch/);assert.match(dialog.innerHTML,/ikke et aktuelt handelssignal/)}
 }
 assert.equal(calls.length,0,'Opening the warning is not an acknowledgement or order');
 const icon=iconOf(ctx.window.EngineUI.actionNotice(s));icons.push(icon,iconOf(ctx.window.EngineUI.actionNotice(s)));
 const other=JSON.parse(JSON.stringify(s));other.last_action_signal.event_id='hw-'+'b'.repeat(24);icons.push(iconOf(ctx.window.EngineUI.actionNotice(other)));
 const b={dataset:{engineAck:s.watch_id,eventId:s.last_action_signal.event_id,isTest:'false'},disabled:false,setAttribute(k,v){this[k]=v}};
 fail=true;await assert.rejects(()=>ctx.window.EngineUI.click(b),/offline/);assert.equal(b.disabled,false);assert.match(icon.className,/--unread/);
 fail=false;await ctx.window.EngineUI.click(b);
 assert.equal(calls.at(-1)[0],'v1/hotwatch/sessions/synthetic-watch/ack-signal');assert.equal(calls.at(-1)[1].event_id,'hw-'+'a'.repeat(24));assert.equal(calls.at(-1)[1].is_test,false);
 assert.equal(b.textContent,'Kvitteret');assert.equal(b.disabled,true);
 assert.ok(icons.slice(0,2).every(n=>n.className==='signal-alert signal-alert--read'));assert.match(icons[2].className,/--unread/);
 assert.equal(s.last_action_signal.acknowledged,true);
 const html=ctx.window.DashboardUI.render(state);assert.doesNotMatch(html,/signal-alert--unread/);assert.match(html,/signal-alert--read/);
 await ctx.window.EngineUI.click(icon);assert.match(dialog.innerHTML,/Kvitteret/);assert.doesNotMatch(dialog.innerHTML,/data-engine-ack/);
 const css=fs.readFileSync('static/style.css','utf8');assert.match(css,/@media\(prefers-reduced-motion:reduce\)\{\.signal-alert--unread\{animation:none\}/);
 assert.ok(calls.every(([path])=>path.endsWith('/ack-signal')));
 console.log('PASS: compact icons, modal details, exact-event ack, both copies stop pulsing, failed ack stays unread, history retained, no trade actions');
})().catch(e=>{console.error(e);process.exitCode=1});
