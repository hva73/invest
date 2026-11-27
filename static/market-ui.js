/* Read-only Pluto quote widgets. Report signals and market return stay separate. */
window.MarketUI=(()=>{
 let api,esc,money,stamp,owner,connected,now,age;let activeOwner=null,running=0;const records=new Map(),queue=[];
 const $=s=>document.querySelector(s);
 const clock=v=>new Intl.DateTimeFormat('da-DK',{timeZone:'Europe/Copenhagen',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(new Date(v));
 const dayDate=v=>new Intl.DateTimeFormat('da-DK',{timeZone:'Europe/Copenhagen',day:'2-digit',month:'2-digit',year:'numeric'}).format(new Date(v));
 const dateKey=v=>{const parts=new Intl.DateTimeFormat('en-CA',{timeZone:'Europe/Copenhagen',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date(v));return ['year','month','day'].map(k=>parts.find(p=>p.type===k).value).join('-')};
 const tone=v=>v===null||v===undefined||!Number.isFinite(Number(v))?'neutral':Number(v)>0?'positive':Number(v)<0?'negative':/[1-9]/.test(String(v).split(/[eE]/)[0])?(String(v).startsWith('-')?'negative':'positive'):'neutral';
 const percent=v=>{if(v===null||v===undefined)return '—';const n=Number(v);if(!Number.isFinite(n)||n===0&&/[1-9]/.test(String(v)))return esc(v)+' %';return (n>0?'+':'')+new Intl.NumberFormat('da-DK',n!==0&&Math.abs(n)<.01?{maximumSignificantDigits:2}:{maximumFractionDigits:2}).format(n)+' %'};
 const delta=(v,c)=>v===null||v===undefined?'Ikke oplyst':(tone(v)==='positive'?'+':'')+money({amount:v,currency:c});
 function key(node){return JSON.stringify([owner(),node.dataset.marketReport,node.dataset.marketCandidate,node.dataset.marketPortfolio||'',node.dataset.marketPosition||'',node.dataset.marketTest,node.dataset.marketHoldingPortfolio||'',node.dataset.marketHoldingAsset||''])}
 function record(node){const k=key(node);if(!records.has(k))records.set(k,{key:k,period:'day',data:null,byPeriod:{},choices:null,error:null,busy:false,queued:false,attempted:0});return records.get(k)}
 function slot(meta){const compact=['quote','position'].includes(meta.layout);return `<section class="market-slot ${compact?'market-quote-only':''} ${meta.layout==='position'?'market-position':''}" data-market-layout="${compact?'quote':'chart'}" data-market-report="${esc(meta.report_id)}" data-market-candidate="${esc(meta.candidate_id||'')}" data-market-portfolio="${esc(meta.portfolio_id||'')}" data-market-position="${esc(meta.position_id||'')}" data-market-test="${meta.is_test?'true':'false'}" data-market-holding-portfolio="${esc(meta.holding_portfolio_id||'')}" data-market-holding-asset="${esc(meta.holding_asset_id||'')}" data-market-markers="${esc(JSON.stringify(meta.markers||[]))}" aria-label="${meta.layout==='quote'?'Pluto-kurs og dagsændring':'Pluto-kurs og kursgraf'}"><div class="market-placeholder"><span>Kurs og dagsgraf</span><button type="button" data-market-load>${window.ESCAPE_DEMO?'Hent demograf':'Hent fra Pluto'}</button></div></section>`}
 function periodKey(period){return period==='month'?'ONE_MONTH':period==='year'?'ONE_YEAR':'ONE_WEEK'}
 // Calendar days use Copenhagen midnight, including 23- and 25-hour days.
 function localDay(at){
  const time=typeof at==='number'?at:Date.parse(at);
  if(!Number.isFinite(time))return null;
  const midnight=Date.parse(dateKey(time)+'T00:00:00Z');
  const offset=new Intl.DateTimeFormat('en',{timeZone:'Europe/Copenhagen',timeZoneName:'longOffset'});
  const boundary=ms=>ms-Number(offset.formatToParts(new Date(ms)).find(p=>p.type==='timeZoneName').value.slice(3,6))*3600000;
  return {start:boundary(midnight),end:boundary(midnight+86400000)};
 }
 function domainBounds(domain){
  const start=Date.parse(domain?.start),end=Date.parse(domain?.end);
  return Number.isFinite(start)&&end>start?{start,end}:null;
 }
 function dayDomain(data){
  const domain=data.chart_domain;
  const crypto=['CRYPTO','CRYPTOCURRENCY'].includes(data.asset_type?.toUpperCase());
  const asOf=Date.parse(domain?.as_of||data.fetched_at);
  const calendar=domain?.kind==='calendar_day'||(!domain&&crypto);
  const bounds=domainBounds(domain)||(!domain&&crypto?localDay(asOf):null);
  const labels={regular:'Marked åbent',pre:'Pre-market',after:'Eftermarked',closed:'Marked lukket',continuous:'24/7'};
  const verified=calendar?crypto:Boolean(domain?.session_source&&Number.isFinite(Date.parse(domain.session_source_time)));
  return {bounds:calendar||verified?bounds:null,asOf,calendar,
   label:(verified?labels[domain?.phase||(crypto?'continuous':'unknown')]:null)||'Markedsstatus ukendt'};
 }
 function validPrice(value){
  return (typeof value==='number'||typeof value==='string')&&Number.isFinite(Number(value))&&Number(value)>0;
 }
 function chart(data,period,markers){
  const day=period==='day'?dayDomain(data):null;
  const rows=(data.series||[]).filter(p=>{
   const ms=Date.parse(p.timestamp),epoch=Number(p.epoch);
   // Pluto's normalized timestamp truncates to milliseconds; epoch retains microseconds.
   return p.epoch!=null&&epoch>=ms/1000&&epoch<(ms+1)/1000&&
    validPrice(p.price)&&(!Number.isFinite(day?.asOf)||epoch*1000<=day.asOf);
  }).sort((a,b)=>a.epoch-b.epoch);
  const bounds=day?.bounds;
  if(bounds){
   const {start,end}=bounds;
   return geometry(rows.filter(p=>p.epoch*1000>=start&&(day.calendar?p.epoch*1000<end:p.epoch*1000<=end)),
    day,start/1000,end/1000,markers,data.currency);
  }
  const last=Number(rows.at(-1)?.epoch);
  const visible=day?rows.filter(p=>p.epoch>last-86400):rows;
  return geometry(visible,day,Number(visible[0]?.epoch),last,markers,data.currency);
 }
 function geometry(rows,day,start,end,markers,currency){
  const values=rows.map(p=>Number(p.price));
  const entries=markers.filter(m=>m?.kind==='entry'&&m.currency===currency&&validPrice(m.value));
  const levels=[...values,...entries.map(m=>Number(m.value))];
  const min=Math.min(...levels),max=Math.max(...levels),mid=min+(max-min)/2,range=Math.max((max-min)*1.2,mid*.01);
  const lo=mid-range/2,hi=mid+range/2;
  const x=epoch=>end===start?120:5+(epoch-start)/(end-start)*230;
  const y=value=>57-(value-lo)/range*52;
  const label=day?clock:dayDate;
  const axis=day?.bounds?(day.calendar?['00.00','24.00']:[clock(start*1000),clock(end*1000)]):
   rows.length?[label(rows[0].timestamp),label(rows.at(-1).timestamp)]:[];
  // Padding can overflow near MAX_VALUE or collapse for subnormal prices.
  if(!(hi>lo&&Number.isFinite(hi-lo)&&Number.isFinite(range))){
   return {rows:[],values:[],day,axis};
  }
  return {rows,day,values,lo,hi,x,y,axis,entries};
 }
 function plot(data,markers,g){
  const {rows,day,values,lo,hi,x,y,axis,entries}=g;
  const axisMarkup=axis.length?`<div class="market-axis">${axis.map(label=>`<span>${esc(label)}</span>`).join('')}</div>`:'';
  if(!rows.length)return `<div class="market-no-series">${esc(data.series_error||'Ingen kurspunkter leveret.')}</div>${axisMarkup}`;
  // Pluto's intraday ONE_WEEK observations are hourly. Break the line when an hour is missing.
  const joinsPrevious=rows.map((p,i)=>i>0&&(!day||p.epoch-rows[i-1].epoch<=5400));
  const path=rows.map((p,i)=>(joinsPrevious[i]?'L':'M')+
   x(p.epoch).toFixed(3)+','+y(values[i]).toFixed(3)).join(' ');
  const isolated=day?rows.slice(0,-1).map((p,i)=>joinsPrevious[i]||joinsPrevious[i+1]?'':`<circle class="market-last" cx="${x(p.epoch)}" cy="${y(values[i])}" r="1.6"/>`).join(''):'';
  const last=rows.at(-1),high=Math.max(...values),top=rows[values.indexOf(high)];
  const levels=[...entries,...markers.filter(m=>m?.kind==='stop'&&m.currency===data.currency&&validPrice(m.value))];
  const signal=markers.find(m=>m?.kind==='signal'&&Date.parse(m.at)/1000>=rows[0].epoch&&Date.parse(m.at)/1000<=last.epoch&&last.epoch>rows[0].epoch);
  const signalX=signal?x(Date.parse(signal.at)/1000):null;
  const change=values.length>1?(values.at(-1)/values[0]-1)*100:null,color=tone(change);
  const axisPrice=v=>new Intl.NumberFormat('da-DK',{maximumSignificantDigits:5}).format(v);
  const levelLabel=m=>`${m.kind==='stop'?'Analytisk stop':'Gns. købskurs'} ${esc(m.value)} ${esc(m.currency)}`;
  return `<div class="market-plot market-${color}" data-market-plot><div class="market-sample-change">Udsnit: ${change===null?'ét punkt':Number.isFinite(change)?percent(change):'—'}</div><div class="market-scale">Skala ${axisPrice(lo)}–${axisPrice(hi)} ${esc(data.currency)}</div><svg viewBox="0 0 240 62" preserveAspectRatio="none" role="img" aria-label="${esc('Kursudsnit fra '+stamp(rows[0].timestamp)+' til '+stamp(last.timestamp)+', '+rows.length+' observerede punkter')}"><path class="market-guide" d="M5,57 L235,57"/>${levels.filter(m=>Number(m.value)>=lo&&Number(m.value)<=hi).map(m=>`<line class="market-marker market-marker-${m.kind}" x1="5" x2="235" y1="${y(m.value)}" y2="${y(m.value)}"><title>${levelLabel(m)}</title></line>`).join('')}${signalX===null?'':`<line class="market-marker-signal" x1="${signalX}" x2="${signalX}" y1="5" y2="57"><title>Signalets datatid · ikke signalpris</title></line>`}<path class="market-line" d="${path}"/>${isolated}<circle class="market-last" cx="${x(last.epoch)}" cy="${y(values.at(-1))}" r="2.8"/><text x="${x(top.epoch)}" y="${Math.max(9,y(high)-4)}" text-anchor="${x(top.epoch)>215?'end':x(top.epoch)<25?'start':'middle'}" fill="currentColor" font-size="8"><title>Top ${esc(top.price)} ${esc(data.currency)}</title>Top</text><circle class="market-focus" r="3" hidden/></svg>${levels.length||signal?`<div class="market-marker-legend">${levels.map(m=>levelLabel(m)+(Number(m.value)<lo||Number(m.value)>hi?' · uden for skala':'')).join(' · ')}${signal?' · Signalets datatid (ikke kurs)':''}</div>`:''}<output class="market-hover" hidden></output>${axisMarkup}</div>`;
 }
 function sync(k){document.querySelectorAll('.market-slot').forEach(node=>{if(key(node)===k)paint(node,record(node))})}
 function paint(node,r){
  if(!node.isConnected)return;
  if(!connected()){node.innerHTML='<div class="market-placeholder"><span>Kurs og dagsændring kræver Pluto-login</span><button type="button" data-view="settings">Se forbindelse</button></div>';return}
  if(r.choices){node.innerHTML=`<div class="market-selection"><label>Vælg det korrekte Pluto-aktiv<select data-market-asset><option value="">Vælg aktiv og børs</option>${r.choices.map(a=>`<option value="${esc(a.asset_id)}">${esc([a.name,a.ticker,a.exchange,a.currency,a.isin].filter(Boolean).join(' · '))}</option>`).join('')}</select></label><button type="button" data-market-select ${r.busy?'disabled':''}>${r.busy?'Henter…':'Vis kursgraf'}</button>${r.data?'<button type="button" data-market-cancel>Tilbage til graf</button>':''}${r.error?`<small>${esc(r.error)}</small>`:''}</div>`;return}
  const activeKey=periodKey(r.period),d=r.byPeriod[activeKey]||(r.data?{...r.data,series:[],series_error:r.busy?'Henter valgt periode…':'Historik for perioden er ikke modtaget.'}:null);
  if(!d){node.innerHTML=`<div class="market-placeholder"><span>${esc(r.error|| (r.busy?'Henter kurs og graf…':node.dataset.marketTest==='true'?'Testkort · intet automatisk kursopslag':'Kurs og dagsgraf'))}</span><button type="button" data-market-load ${r.busy?'disabled':''}>${r.busy?'Henter…':window.ESCAPE_DEMO?'Hent demograf':'Hent fra Pluto'}</button></div>`;return}
  const dayComparison=d.daily_comparison?.basis==='official_close'?d.daily_comparison:d.daily_change_percent!==null&&d.daily_change_percent!==undefined&&!d.daily_note?{percent:d.daily_change_percent,amount:d.daily_change,basis:'pluto_reported_daily_change'}:null,dailyTone=tone(dayComparison?.percent),arrow=!dayComparison?'—':dailyTone==='positive'?'↑':dailyTone==='negative'?'↓':'→';
  const warning=r.error||d.last_error,quality=age(d.price_time,d.fetched_at,Boolean(warning));node.classList.toggle('market-stale',quality.tone==='stale');
  if(node.dataset.marketLayout==='quote'){
   node.innerHTML=`<small class="market-mini-title">Dagens kurs · Pluto</small><div class="market-mini-quote"><button type="button" class="market-number-link" data-market-expand aria-label="Åbn kursgraf for ${esc(d.ticker||d.name)}"><strong class="market-price">${money({amount:d.price,currency:d.currency})}</strong><span aria-hidden="true">→</span></button><button type="button" class="market-number-link market-change market-${dailyTone}" data-market-expand aria-label="Se dagsændring og kursgraf">${dayComparison?arrow+' '+percent(dayComparison.percent):'—'}<small>${dayComparison?delta(dayComparison.amount,d.currency):'Dagsreference mangler'}</small></button></div><small class="market-origin ${d.price_time?'':'market-time-unknown'}">${esc(d.ticker||'')} · ${d.price_time?'kurs '+clock(d.price_time):'kurstid ukendt'} · hentet ${clock(d.fetched_at)}</small><button type="button" class="market-mini-refresh" data-market-refresh ${r.busy?'disabled':''} aria-label="Opdatér dagskurs">${r.busy?'Henter…':'Opdatér kurs ↻'}</button>${warning||quality.tone==='stale'?`<small class="market-warning">${esc(warning||quality.label)}</small>`:''}`;return
  }
  let markers=[];try{const parsed=JSON.parse(node.dataset.marketMarkers||'[]');if(Array.isArray(parsed))markers=parsed}catch{}
  if(!node.dataset.marketHoldingPortfolio&&!node.dataset.marketPosition)markers=markers.filter(m=>m?.kind!=='entry');
  const graph=chart(d,r.period,markers),{rows,day,values,x,y}=graph,end=rows.at(-1);
  const dayLabel=day?.bounds?'Dag':end?'Kursudsnit · '+dayDate(end.timestamp):'Dag';
  const fromPeak=end?(values.at(-1)/Math.max(...values)-1)*100:null;
  node.innerHTML=`<div class="market-quote"><strong class="market-price">${money({amount:d.price,currency:d.currency})}</strong><span class="market-change market-${dailyTone}">${dayComparison?arrow+' '+delta(dayComparison.amount,d.currency):'—'}<br><span>${dayComparison?percent(dayComparison.percent):'Dagsreference mangler'} <small>dag · ${window.ESCAPE_DEMO?'demo':'Pluto'}</small></span></span><small class="market-origin ${d.price_time?'':'market-time-unknown'}">${esc([d.ticker,d.exchange].filter(Boolean).join(' · ')||'Pluto')} · ${d.price_time?'kurs '+clock(d.price_time):'kurstid ukendt'}</small><small class="market-fetch">Hentet ${clock(d.fetched_at)}${quality.minutes!==null&&quality.minutes>=10?' · '+quality.minutes+' min':''}</small></div><div class="market-chart"><div class="market-period-title">${r.period==='day'?esc(dayLabel):r.period==='week'?'Uge'+(d.week_change_percent!==null&&d.week_change_percent!==undefined?` · <span class="signed-${tone(d.week_change_percent)}">${percent(d.week_change_percent)}</span>`:''):r.period==='month'?'Måned':'År'}</div>${plot(d,markers,graph)}${node.closest('.signal-overview')?`<div class="signal-chart-peak"><small>Seneste grafpunkt fra højeste viste punkt</small><strong>${fromPeak===null?'—':percent(fromPeak)}</strong><small>Observeret Pluto-serie · ${end?stamp(end.timestamp):'tid mangler'}</small></div>`:''}<small class="market-session">${esc(r.period==='day'?day.label+' · '+(rows.length===1?'ét punkt':rows.length+' punkter'):(window.ESCAPE_DEMO?'Fiktive kurspunkter':'Plutos observerede kurspunkter'))}</small></div><div class="market-controls"><div class="market-period-buttons" aria-label="Grafperiode"><button type="button" data-market-period="day" aria-pressed="${r.period==='day'}">Dag</button><button type="button" data-market-period="week" aria-pressed="${r.period==='week'}">Uge</button><button type="button" data-market-period="month" aria-pressed="${r.period==='month'}">Måned</button><button type="button" data-market-period="year" aria-pressed="${r.period==='year'}">År</button></div><button type="button" data-market-refresh aria-label="Opdatér Pluto-kurs og graf" ${r.busy?'disabled':''}>${r.busy?'…':'↻'}</button><details class="market-about"><summary aria-label="Om kurser og datakilde">ⓘ</summary><div><strong>${esc(d.name)}</strong><p>${esc(d.ticker||'')} · ${esc(d.exchange||'Børs ikke oplyst')} · ${esc(d.currency||'Valuta ukendt')}</p><p>${window.ESCAPE_DEMO?'Kilde: fiktiv demohistorik. Ingen livekurser.':'Kilde: Pluto Markets. Aktuelt opslag, adskilt fra rapportens tidspunkt og handelssignal.'}</p><p>Kurstid: ${d.price_time?stamp(d.price_time):'Ikke oplyst af Pluto.'}<br>Hentet: ${stamp(d.fetched_at)}<br>Seneste grafpunkt: ${end?stamp(end.timestamp):'Ikke oplyst'}</p><p>Dagsændring er Plutos oplyste tal. Kilden har ikke altid dokumenteret referencen eller kurstidspunktet; derfor betegnes tallet ikke som verificeret officiel lukkekurs. Ugeserien bruges ikke til at beregne dagsændringen. Grafens farve og Udsnit viser ændringen fra første til sidste viste punkt, som kan falde, selv om dagen samlet er positiv. Dagsgrafen viser observationer inden for den oplyste handelsperiode eller det lokale kalenderdøgn for krypto. Ved ukendt handelsperiode vises et observeret kursudsnit. Timer uden observationer kan mangle. Graf og akse vises i dansk tid.</p>${d.daily_note?`<p>${esc(d.daily_note)}</p>`:''}${d.series_error?`<p>${esc(d.series_error)}</p>`:''}${node.dataset.marketHoldingPortfolio?'':'<button type="button" data-market-choose>Skift Pluto-aktiv</button>'}</div></details></div>${node.dataset.marketTest==='true'?'<small class="market-test-note">Aktuelle Pluto-kurser · rapporten er testdata</small>':''}${warning||quality.tone==='stale'?`<small class="market-warning">${esc(warning||quality.label)}</small>`:''}`;
  const plotNode=node.querySelector('[data-market-plot]');
  if(plotNode){
   const svg=plotNode.querySelector('svg'),focus=svg.querySelector('.market-focus'),output=plotNode.querySelector('output');
   const hide=()=>{focus.setAttribute('hidden','');output.hidden=true};
   plotNode.addEventListener('pointermove',event=>{
    const box=svg.getBoundingClientRect(),pointer=(event.clientX-box.left)/box.width*240;
    if(day?.bounds&&(pointer<x(rows[0].epoch)||pointer>x(end.epoch)+3)){hide();return}
    let i=0;
    rows.forEach((p,n)=>{if(Math.abs(x(p.epoch)-pointer)<Math.abs(x(rows[i].epoch)-pointer))i=n});
    focus.setAttribute('cx',x(rows[i].epoch));focus.setAttribute('cy',y(values[i]));focus.removeAttribute('hidden');
    output.textContent=clock(rows[i].timestamp)+' · '+new Intl.NumberFormat('da-DK',{maximumSignificantDigits:8}).format(values[i])+' '+d.currency;output.hidden=false;
   },{passive:true});
   plotNode.addEventListener('pointerleave',hide);
  }
 }
 async function run(node,r,refresh,asset,choose){r.queued=false;const requestOwner=owner(),requestPeriod=periodKey(r.period);
  const isCurrent=()=>owner()===requestOwner&&records.get(r.key)===r;
  if(!node.isConnected)node=[...document.querySelectorAll('.market-slot')].find(n=>key(n)===r.key);if(!node||!requestOwner||!connected())return;r.busy=true;r.error=null;r.attempted=now();sync(r.key);try{const result=await api('market/quote',{...(node.dataset.marketHoldingPortfolio?{holding_portfolio_id:Number(node.dataset.marketHoldingPortfolio),holding_asset_id:node.dataset.marketHoldingAsset}:{report_id:node.dataset.marketReport,...(node.dataset.marketPosition?{portfolio_id:node.dataset.marketPortfolio,position_id:node.dataset.marketPosition}:{candidate_id:node.dataset.marketCandidate})}),is_test:node.dataset.marketTest==='true',period:requestPeriod,refresh,choose,...(asset?{asset_id:asset}:{})});
   if(!isCurrent())return;
   if(result.pending){
    r.pendingRetries=(r.pendingRetries||0)+1;r.error='Pluto henter kursen · delt opslag';
    if(r.pendingRetries<=15){
     r.attempted=0;
     setTimeout(()=>{
      if(!isCurrent()||document.hidden)return;
      const active=[...document.querySelectorAll('.market-slot')].find(n=>key(n)===r.key);
      if(active){const box=active.getBoundingClientRect();if(box.bottom>0&&box.top<innerHeight+120)schedule(active,false)}
     },2000)
    }
   }else if(result.selection_required){r.choices=result.choices}else{r.pendingRetries=0;r.data=result;r.byPeriod[requestPeriod]=result;r.choices=null}
  }catch(error){if(isCurrent())r.error=error.message}finally{
   if(isCurrent()){
    r.busy=false;sync(r.key);
    if(!r.error&&periodKey(r.period)!==requestPeriod&&!r.byPeriod[periodKey(r.period)])setTimeout(()=>{
     if(!isCurrent())return;
     const active=[...document.querySelectorAll('.market-slot')].find(n=>key(n)===r.key);
     if(active)schedule(active,true)
    },0)
   }
  }
 }
 function drain(){while(running<2&&queue.length){const task=queue.shift();running++;const done=task.pop();run(...task).finally(()=>{done();running--;drain()})}}
 function schedule(node,refresh=false,asset=null,choose=false){const r=record(node);if(r.busy||r.queued)return r.promise;if(!refresh&&(r.choices||r.attempted&&now()-r.attempted<300000))return Promise.resolve();r.queued=true;r.promise=new Promise(done=>queue.push([node,r,refresh,asset,choose,done]));drain();return r.promise}
 const observer=typeof IntersectionObserver==='undefined'?null:new IntersectionObserver(entries=>{entries.forEach(e=>{if(e.isIntersecting&&e.target.dataset.marketTest!=='true'&&!document.hidden&&connected())schedule(e.target)})},{rootMargin:'120px'});
 function mount(){if(observer)observer.disconnect();if(activeOwner!==owner()){activeOwner=owner();records.clear();queue.splice(0).forEach(task=>task[task.length-1]())}document.querySelectorAll('.market-slot').forEach(node=>{paint(node,record(node));if(observer)observer.observe(node);else if(connected()&&node.dataset.marketTest!=='true'&&!document.hidden)schedule(node)})}
 function tick(){if(document.hidden||!owner()||!connected())return;document.querySelectorAll('.market-slot').forEach(node=>{const box=node.getBoundingClientRect();if(node.dataset.marketTest!=='true'&&box.bottom>0&&box.top<innerHeight)schedule(node)})}
 async function click(b){if(b.hasAttribute('data-market-close')){document.querySelector('#market-chart-dialog')?.close();return true}const node=b.closest('.market-slot');if(!node)return false;const r=record(node);if(b.hasAttribute('data-market-expand')){r.period='day';let dialog=document.querySelector('#market-chart-dialog');if(!dialog){dialog=document.createElement('dialog');dialog.id='market-chart-dialog';dialog.className='market-chart-dialog';document.querySelector('#content').append(dialog)}dialog.setAttribute('aria-labelledby','market-chart-title');dialog.innerHTML=`<div class="overview-detail-header"><h2 id="market-chart-title">${esc(r.data?.ticker||'Kursgraf')}</h2><button data-market-close aria-label="Luk kursgraf">✕</button></div>${slot({report_id:node.dataset.marketReport,...(node.dataset.marketPosition?{portfolio_id:node.dataset.marketPortfolio,position_id:node.dataset.marketPosition}:{candidate_id:node.dataset.marketCandidate}),is_test:node.dataset.marketTest==='true',holding_portfolio_id:node.dataset.marketHoldingPortfolio,holding_asset_id:node.dataset.marketHoldingAsset,markers:(()=>{try{return JSON.parse(node.dataset.marketMarkers||'[]')}catch{return []}})()})}${node.dataset.marketTest==='true'?'':window.TradeUI.assetActions({ticker:r.data?.ticker,assetId:r.data?.asset_id,portfolioId:node.dataset.marketHoldingPortfolio||null,position:Boolean(node.dataset.marketPosition||node.dataset.marketHoldingPortfolio)})}`;const originIndex=[...node.querySelectorAll('[data-market-expand]')].indexOf(b);dialog.addEventListener('close',()=>{const origin=[...document.querySelectorAll('.market-quote-only')].find(n=>key(n)===r.key);origin?.querySelectorAll('[data-market-expand]')[Math.max(0,originIndex)]?.focus({preventScroll:true})},{once:true});dialog.showModal();mount();return true}if(b.dataset.marketPeriod){if(!['day','week','month','year'].includes(b.dataset.marketPeriod))return true;r.period=b.dataset.marketPeriod;paint(node,r);if(!r.byPeriod[periodKey(r.period)])schedule(node,true);return true}if(b.hasAttribute('data-market-load')||b.hasAttribute('data-market-refresh')){schedule(node,true);return true}if(b.hasAttribute('data-market-cancel')){r.choices=null;r.error=null;paint(node,r);return true}if(b.hasAttribute('data-market-choose')){schedule(node,true,null,true);return true}if(b.hasAttribute('data-market-select')){const value=node.querySelector('[data-market-asset]').value;if(!value){r.error='Vælg et aktiv først.';paint(node,r)}else schedule(node,true,value);return true}return false}
 setInterval(tick,30000);document.addEventListener('visibilitychange',()=>{if(!document.hidden)tick()});
 async function refreshVisible(){if(document.hidden||!connected())return;const jobs=[];document.querySelectorAll('.market-slot').forEach(node=>{const box=node.getBoundingClientRect(),r=record(node);if(box.bottom>0&&box.top<innerHeight+120&&!r.choices&&(node.dataset.marketTest!=='true'||r.data))jobs.push(schedule(node,true))});await Promise.all(jobs)}
 return {slot,mount,click,refreshVisible,localDay,domainBounds,setup(deps){({api,escape:esc,formatAmount:money,formatTime:stamp,owner,connected,now,age}=deps)}};
})();
