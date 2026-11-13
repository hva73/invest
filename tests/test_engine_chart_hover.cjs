const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const src=fs.readFileSync('static/engine-ui.js','utf8'),a=src.indexOf(' function chart(items){'),b=src.indexOf(' function instrumentEvidence(',a);assert(a>=0&&b>a);
const ctx={window:{DashboardUI:{chartTooltip:()=>'<div class="dash-chart-tooltip"></div>'}},Intl,Number,String,Date,Math,esc:v=>String(v??''),text:v=>String(v??''),date:v=>String(v??''),money:v=>v.amount+' '+(v.currency||'ukendt')};vm.createContext(ctx);vm.runInContext(src.slice(a,b)+';this.renderChart=chart',ctx);
const older={price:'100',currency:'USD',event_time:'2026-11-12T10:00:00Z',interval_s:60,session_key:'a'},newer={price:'105',currency:'USD',event_time:'2026-11-12T10:01:00Z',interval_s:60,session_key:'a'};
let html=ctx.renderChart([{data:newer},{data:older}]);assert.match(html,/inspect-chart-svg/);assert.match(html,/data-chart-value-label="Kurs"/);assert.match(html,/data-chart-share="\+5,00 %"/);assert.match(html,/data-chart-tone="positive"/);assert.match(html,/data-chart-share-label="ændring fra første punkt"/);
html=ctx.renderChart([{data:{...newer,currency:'DKK'}},{data:older}]);assert.match(html,/data-chart-value="105 DKK"[^>]*data-chart-share=""/);
html=ctx.renderChart([{data:{...newer,event_time:'bad'}},{data:older}]);assert.match(html,/mindst to faktiske observationer/);
console.log('PASS: engine graph hover reflects observed currency, time and comparable samples');
