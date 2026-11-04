const fs=require('fs'),vm=require('vm'),assert=require('assert');
let source=fs.readFileSync('static/engine-ui.js','utf8');
source=source.replace('return {setup(d){','return {testSet(c,p,a){candidates=c;portfolios=[];portfolioSnapshots={};mode=false;api=a;esc=String},testItems(){return batchCandidates},addBatchCandidate,resolveInstrument,setup(d){');
const form={elements:{candidate:{value:'0'},provider:{value:'eodhd'},provider_symbol:{value:'AMD.US'},exchange:{},asset_id:{},quote_currency:{},portfolios:{options:[]},watch_mode:{value:'entry'}}};
const nodes={'engine-create':form,'engine-form-status':{},'engine-batch-list':{}};
const context={window:{},document:{getElementById:id=>nodes[id]},FormData:class{constructor(f){this.f=f}get(k){return this.f.elements[k]?.value}},console};
vm.runInNewContext(source,context);const ui=context.window.EngineUI;
(async()=>{
const candidates=[{candidate:{candidate_id:'amd',ticker:'AMD'},instrument:{asset_id:'a',currency:'USD',exchange:'NASDAQ'}},{candidate:{candidate_id:'pltr',ticker:'PLTR'},instrument:{asset_id:'p',currency:'USD',exchange:'NASDAQ'}}];
ui.testSet(candidates,[],()=>{throw Error('Unexpected network call')});
await ui.addBatchCandidate();form.elements.candidate.value='1';form.elements.provider_symbol.value='PLTR.US';await ui.addBatchCandidate();
assert.equal(ui.testItems()[0].instrument.provider_symbol,'AMD.US');assert.equal(ui.testItems()[1].instrument.provider_symbol,'PLTR.US');
let complete;ui.testSet(candidates,[],()=>new Promise(r=>complete=r));form.elements.candidate.value='0';form.elements.provider_symbol.value='';const pending=ui.resolveInstrument(0);form.elements.provider_symbol.value='AMD.US';complete({asset_id:'a',currency:'USD',exchange:'NASDAQ'});await pending;assert.equal(form.elements.provider_symbol.value,'AMD.US');
console.log('PASS: separate batch symbols; manual symbol survives asynchronous instrument lookup');
})().catch(e=>{console.error(e);process.exit(1)});
