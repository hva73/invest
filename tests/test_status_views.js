const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const ctx={window:{},document:{},Intl,Date,Number,String,console};
vm.runInNewContext(fs.readFileSync('static/engine-ui.js','utf8').replace('return {openHoldingStatus,','return {card,sessionRow,openHoldingStatus,'),ctx);
const ui=ctx.window.EngineUI;
ui.setup({escape:String,formatTime:String,formatAmount:String,owner:()=>1});
for(const [status,signal,label] of [
 ['ACTIVE','BUY','KØBSSIGNAL'],['ACTIVE','SELL','SÆLGSSIGNAL'],['ACTIVE','REDUCE','EXIT WATCH'],['ACTIVE','WAIT','AFVENT'],
 ['DEGRADED','WAIT','RISIKODATA MANGLER'],['DEGRADED','NO_DATA','EARLY WATCH'],['DEGRADED','NO_DATA','DATA FOR GAMLE'],
 ['DEGRADED','NO_DATA','HANDEL STANDSET'],['DEGRADED','NO_DATA','KURSKILDE IKKE BEKRÆFTET'],['PAUSED','PAUSE','PAUSERET'],
 ['COMPLETED','NO_DATA','AFSLUTTET'],['EXPIRED','NO_DATA','UDLØBET'],['ERROR','NO_DATA','FEJL']]){
 const s={watch_id:'synthetic',request:{ticker:'SYNTHETIC'},status,signal,display_status:label,minimum_required_samples:34,
  latest_calculation:{reason_codes:['WARMUP'],supporting_metrics:{sample_count:1}},data_status:{price:'10'}};
 for(const render of [ui.card,ui.sessionRow]){
  const html=render(s);assert.ok(html.includes(label),label);assert.doesNotMatch(html,/engine-warmup|>WARMUP(?: |<)/);
  if(status!=='ACTIVE'||!['BUY','SELL','REDUCE'].includes(signal))assert.doesNotMatch(html,/data-trade-watch/);
 }
}
console.log('PASS: engine cards and rows keep current signal, data/risk blockers and lifecycle ahead of old warmup');
