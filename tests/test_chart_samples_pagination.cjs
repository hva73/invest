const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
let source=fs.readFileSync('static/engine-ui.js','utf8');
source=source.replace('return {openHoldingStatus,','return {testLoadAllSamples:loadAllSamples,openHoldingStatus,');
assert(source.includes('testLoadAllSamples:loadAllSamples'));
const window={DashboardUI:{chartTooltip:()=>''}};
const context={window,document:{getElementById:()=>null},Intl,Date,Number,String,Math,Set,Map,console,setTimeout,clearTimeout};
vm.runInNewContext(source,context);
const make=i=>({id:i,data:{price:String(100+i/100),currency:'USD',event_time:new Date(Date.UTC(2026,10,12,0,0,i)).toISOString(),session_key:'one',interval_s:1}});
const all=Array.from({length:250},(_,i)=>make(250-i));
let calls=0,fail=false;
const api=async url=>{calls++;if(fail)throw Error('network');const after=Number(new URLSearchParams(url.split('?')[1]).get('after'));if(after===151)return {items:all.slice(100,200),next_cursor:51};if(after===51)return {items:all.slice(200),next_cursor:null};throw Error('unexpected '+after)};
context.window.EngineUI.setup({api,escape:x=>String(x??''),formatAmount:x=>String(x.amount)+' '+String(x.currency||''),formatTime:x=>String(x),owner:()=>'owner',editing:()=>false,isAdmin:()=>false,state:()=>({})});
function dialog(){const plot={innerHTML:''},status={textContent:''};return {isConnected:true,open:true,dataset:{watchId:'watch'},plot,status,querySelector(q){return q.includes('chart')?plot:status}}}
(async()=>{
 let d=dialog();await context.window.EngineUI.testLoadAllSamples(d,'watch',{items:all.slice(0,100),next_cursor:151},'owner',false);
 assert.equal(calls,2);assert.equal((d.plot.innerHTML.match(/class="dash-chart-point"/g)||[]).length,250);assert.match(d.status.textContent,/250 observationer hentet/);
 calls=0;fail=true;d=dialog();await context.window.EngineUI.testLoadAllSamples(d,'watch',{items:all.slice(0,100),next_cursor:151},'owner',false);
 assert.equal(calls,1);assert.equal((d.plot.innerHTML.match(/class="dash-chart-point"/g)||[]).length,100);assert.match(d.status.textContent,/ældre historik kunne ikke hentes/);
 console.log('PASS: 250 actual samples across three pages; partial fetch explicitly reported');
})().catch(e=>{console.error(e);process.exitCode=1});
