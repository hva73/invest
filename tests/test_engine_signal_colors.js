const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const ctx={window:{},document:{},console};
const source=fs.readFileSync('static/engine-ui.js','utf8').replace('return {openHoldingStatus,','return {tone,openHoldingStatus,');
vm.runInNewContext(source,ctx);
const tone=ctx.window.EngineUI.tone;
assert.equal(tone('BUY'),'green');assert.equal(tone('SELL'),'red');assert.equal(tone('REDUCE'),'red');assert.equal(tone('WAIT'),'yellow');assert.equal(tone('NO_DATA'),'missing');assert.equal(tone('PAUSE'),'missing');
console.log('PASS: HOT WATCH signal colors follow buy, sell and wait');
