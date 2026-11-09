// Offline visual regression: real renderers/CSS, synthetic data, no API calls.
// node tests/render_signal_layout.cjs [/tmp/escape-signal-layout.html] [CSS file]
// Open the output in a browser; each viewport reports its layout assertions.
const fs=require('node:fs'),vm=require('node:vm');
const esc=v=>String(v).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
const ctx={window:{},document:{getElementById:()=>null},Intl,Date,Number,String,console};
let source=fs.readFileSync('static/engine-ui.js','utf8');
source=source.replace('return {openHoldingStatus,','return {sessionRow,openHoldingStatus,');
vm.runInNewContext(source,ctx);
ctx.window.EngineUI.setup({escape:esc,formatTime:String,owner:()=>1});
vm.runInNewContext(fs.readFileSync('static/dashboard-ui.js','utf8'),ctx);
const sessions=['ACTIVE','WITHDRAWN','DATA_MISSING'].map((phase,i)=>({
 watch_id:'synthetic-'+i,is_test:true,status:phase==='DATA_MISSING'?'DEGRADED':'ACTIVE',
 signal:phase==='ACTIVE'?'SELL':phase==='WITHDRAWN'?'WAIT':'NO_DATA',
 display_status:phase==='ACTIVE'?'SÆLGSSIGNAL':phase==='WITHDRAWN'?'AFVENT':'DATA FOR GAMLE',
 last_calculation_at:'2026-11-09T19:06:16Z',
 request:{ticker:['JDZG','AMZN','TEST'][i],exchange:'NASDAQ',provider:'eodhd',quote_currency:'USD'},
 data_status:{price:'0.224'},
 last_action_signal:{event_id:'hw-'+String(i).repeat(24),event_type:'SELL_SIGNAL',created:'2026-11-09T19:06:16Z',state:phase,acknowledged_at:null,
 reason:'Der mangler historik til alle indikatorer; særskilte exitregler kan allerede være opfyldt; Kursen er faldet fra toppen i det analyserede kursvindue; dette er ikke afkast siden køb eller et broker-stop'}
}));
const state={dashboard:{positions:sessions.map((s,i)=>({key:'row-'+i,portfolio_id:1,portfolio_name:'Test',ticker:s.request.ticker,name:'Syntetisk testposition',price:{amount:'0.224',currency:'USD'},value:{amount:'119.55',currency:'DKK'},unrealized:{amount:'-31.53',currency:'DKK'},unrealized_percent:'-20.67',daily:'6.57',since_last:'15.16',conflicts:[],hot_watch:{session:s}})),accounts:[],totals:[],issues:[],warnings:[],orders:[],critical_sessions:[]},portfolios:[]};
ctx.window.DashboardUI.setup({escape:esc,formatTime:String,formatQuantity:String,state:()=>state});
const sidebar=fs.readFileSync('static/index.html','utf8').match(/<aside>[\s\S]*?<\/aside>/)[0];
const css=fs.readFileSync(process.argv[3]||'static/style.css','utf8');
const views=[['Overblik',ctx.window.DashboardUI.render(state)],['HOT WATCH',`<section class="panel engine-overview"><div class="engine-list">${sessions.map(s=>ctx.window.EngineUI.sessionRow(s)).join('')}</div></section>`]];
const cases=views.flatMap(([title,content])=>[390,1280].map(width=>({title,width,html:`<!doctype html><html lang="da"><head><meta charset="utf-8"><style>${css}</style></head><body>${sidebar}<main><header><h1>${title} · syntetiske data</h1></header>${content}</main></body></html>`})));
const script=`
const cases=${JSON.stringify(cases).replaceAll('<','\\u003c')};
let complete=0;
for(const c of cases){
 const row=document.createElement('section'),h=document.createElement('h2'),frame=document.createElement('iframe');
 h.textContent=c.title+' '+c.width+'px · afventer';row.append(h,frame);document.body.append(row);
 frame.width=c.width;frame.height=900;frame.title=c.title+' '+c.width;frame.srcdoc=c.html;
 frame.onload=()=>{
  requestAnimationFrame(()=>requestAnimationFrame(()=>{
   const d=frame.contentDocument,w=frame.contentWindow,fail=[];
   const menu=d.querySelector('body > aside');
   if(!menu||!menu.querySelector('nav'))fail.push('Navigation mangler');
   if(d.querySelector('.signal-notice-details'))fail.push('Udvidet advarsel i oversigt');
   for(const n of d.querySelectorAll('.signal-alert')){
    const b=n.getBoundingClientRect();
    if(b.width>44||b.height>44)fail.push('For stort advarselsikon');
   }
   if(d.documentElement.scrollWidth>w.innerWidth+1)fail.push('Vandret side-overflow');
   for(const button of menu.querySelectorAll('nav button')){
    const b=button.getBoundingClientRect();
    if(b.top>=0&&b.bottom<=900&&!button.contains(d.elementFromPoint(b.left+b.width/2,b.top+b.height/2)))fail.push('Menu dækket af advarsel');
   }
   h.textContent=(fail.length?'FAIL: '+[...new Set(fail)].join(', '):'PASS')+' · '+c.title+' '+c.width+'px';
   h.style.color=fail.length?'#a00':'#075';h.dataset.result=fail.length?'FAIL':'PASS';
   if(++complete===cases.length)document.title=[...document.querySelectorAll('[data-result]')].every(x=>x.dataset.result==='PASS')?'PASS · Signal-layout':'FAIL · Signal-layout';
  }));
 };
}
`;
fs.writeFileSync(process.argv[2]||'/tmp/escape-signal-layout.html',`<!doctype html><html lang="da"><head><meta charset="utf-8"><title>Signal-layout test</title><style>body{font:16px system-ui;margin:16px}iframe{display:block;border:1px solid #ddd}section{margin-bottom:24px}</style></head><body><h1>Signal-layout · offline regression</h1><p>Kun syntetiske data. Ingen netværkskald eller handler.</p><script>${script}</script></body></html>`);
console.log('Created offline layout test: '+(process.argv[2]||'/tmp/escape-signal-layout.html'));
