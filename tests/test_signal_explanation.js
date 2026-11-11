const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('static/app.js','utf8');
let current={request:{ticker:'SYNTHETIC'},status:'ACTIVE',signal:'SELL',display_status:'SÆLGSSIGNAL',latest_calculation:{signal:'SELL',reason_codes:['TRAILING_EXIT'],supporting_metrics:{distance_high_pct:'-3'}}};
const calls=[],dialog={innerHTML:'',showModal(){},querySelector(){return null}};
const ctx={Intl,Number,Array,String,state:{user:{username:'synthetic'}},api:async path=>{calls.push(path);return {session:current}},escape:v=>String(v).replace(/</g,'&lt;'),formatTime:v=>v,document:{getElementById:()=>dialog}};
vm.createContext(ctx);vm.runInContext(source.slice(source.indexOf('const signalReasons='),source.indexOf("document.addEventListener('click',async e=>{const close=e.target.closest('[data-explanation-close]')")),ctx);
(async()=>{
 for(let i=0;i<2;i++){
  await ctx.explainSignal({dataset:{explainWatch:'synthetic-watch'},isConnected:true,hasAttribute:()=>false});
  assert.match(dialog.innerHTML,/Aktuel status: SÆLGSSIGNAL/);
  assert.match(dialog.innerHTML,/ikke afkast siden dit køb/);
 }
 current={...current,signal:'NO_DATA',display_status:'DATA FOR GAMLE',display_reason_codes:['DATA_STALE']};
 await ctx.explainSignal({dataset:{explainWatch:'synthetic-watch'},isConnected:true,hasAttribute:()=>false});
 assert.match(dialog.innerHTML,/Aktuel status: DATA FOR GAMLE/);
 assert.match(dialog.innerHTML,/Den seneste beregning er ikke det aktuelle signal/);
 current={...current,display_status:'AFVENTER SIGNALDATA',display_reason_codes:['POSITION_CONTEXT_CHANGED']};
 await ctx.explainSignal({dataset:{explainWatch:'synthetic-watch'},isConnected:true,hasAttribute:()=>false});
 assert.match(dialog.innerHTML,/Beholdningen er ændret/);
 assert.match(dialog.innerHTML,/Den seneste beregning er ikke det aktuelle signal/);
 assert.equal(calls.length,4);
 assert.ok(calls.every(p=>p==='v1/hotwatch/sessions/synthetic-watch?is_test=false'));
 console.log('PASS: both help buttons fetch current session; stale SELL is explicitly historical; no trade request');
})().catch(e=>{console.error(e);process.exitCode=1});
