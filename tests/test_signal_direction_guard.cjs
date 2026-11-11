const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync('static/app.js','utf8');
const start=source.indexOf('if(b.dataset.tradeWatch){');
const end=source.indexOf('if(b.dataset.tradeCandidate)',start);
assert(start>0&&end>start);
let opened=[],closed=0,session;
const context={state:{user:{username:'owner'},dashboard:{positions:[]}},api:async()=>({session}),document:{querySelector:()=>({close:()=>closed++})},window:{TradeUI:{openQuick:x=>opened.push(x)}},Error};
vm.createContext(context);vm.runInContext('async function click(b){'+source.slice(start,end)+'}',context);
const make=(signal,display)=>({status:'ACTIVE',signal,display_status:display,request:{asset_id:'asset',ticker:'SYN',quote_currency:'USD'}});
(async()=>{
 for(const [shown,actual,display] of [['SELL','BUY','KØBSSIGNAL'],['BUY','SELL','SÆLGSSIGNAL'],['SELL','WAIT','AFVENT'],['SELL','REDUCE','EXIT WATCH']]){
  session=make(actual,display);await assert.rejects(context.click({dataset:{tradeWatch:'w',tradeSignal:shown}}),/ændret/);assert.equal(opened.length,0);assert.equal(closed,0);
 }
 session=make('SELL','SÆLGSSIGNAL');await assert.rejects(context.click({dataset:{tradeWatch:'w'}}),/ændret/);assert.equal(opened.length,0);
 session=make('SELL','SÆLGSSIGNAL');session.status='DEGRADED';await assert.rejects(context.click({dataset:{tradeWatch:'w',tradeSignal:'SELL'}}),/ikke længere aktuelt/);
 session=make('SELL','SÆLGSSIGNAL');await context.click({dataset:{tradeWatch:'w',tradeSignal:'SELL'}});assert.equal(opened.length,1);assert.equal(opened[0].signal,'SELL');assert.equal(closed,1);
 session=make('BUY','KØBSSIGNAL');await context.click({dataset:{tradeWatch:'w',tradeSignal:'BUY'}});assert.equal(opened[1].signal,'BUY');
 console.log('PASS: displayed direction must match the freshly read active signal; no proposal is sent');
})().catch(e=>{console.error(e);process.exitCode=1});
