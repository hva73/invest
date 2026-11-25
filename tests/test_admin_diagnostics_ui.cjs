const fs=require('fs'),vm=require('vm'),assert=require('assert');
let html={innerHTML:'',textContent:''};let fetches=0;const fixture={as_of:'2026-11-10T05:00:00Z',worker:{status:'running',updated:'2026-11-10T04:59:59Z'},session_count:50,due_count:2,states:{ACTIVE:50},errors:{DATA_STALE:1},provider_capacity:{http_used_this_minute:2,http_effective_limit_per_minute:960,http_429:0},storage:{database_bytes:1024,free_bytes:1048576},windows:{'5m':{completed:2,deferred:1,queue:{p50_ms:1000,p90_ms:3000,max_ms:3000,count:2}},'1h':{},'24h':{}},timeline:[],recent:[{at:'2026-11-10T04:59:00Z',ticker:'<x>',status:'degraded',code:'DATA_STALE',metrics:{queue_ms:3000,worker_busy_ms:11000,warmup_ms:1000}}],providers:[],supervisor_events:[],push:{last_24h:{}},scheduled_jobs:{last_24h:{}},log_retention:'bounded',unavailable:'not measured'};
const escape=x=>String(x).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const context={view:'diagnostics',state:{user:{role:'admin',username:'owner'}},document:{hidden:false},$:()=>html,escape,formatTime:x=>x,api:async()=>{fetches++;return fixture},setInterval(){},setTimeout,Intl,Date,Number,JSON,URL,Blob};vm.createContext(context);
const source=fs.readFileSync('static/app.js','utf8');vm.runInContext(source.slice(source.indexOf('let diagnosticsData=null'),source.indexOf('// The mobile menu')),context);vm.runInContext('updateDiagnosticsContent=(el,markup)=>{el.innerHTML=markup}',context);
(async()=>{await vm.runInContext('loadAdminDiagnostics()',context);for(const s of ['FORFALDNE SCANNINGER','90-percentil','DATA_STALE','&lt;x&gt;','Køens udvikling','historik'])assert(html.innerHTML.toLowerCase().includes(s.toLowerCase()),s);assert(!html.innerHTML.includes('<x>'));assert(html.innerHTML.includes('diag-within'));assert(html.innerHTML.includes('diag-over'));assert(html.innerHTML.includes('Vejledende mål'));assert.equal(vm.runInContext("diagnosticsDuration(null,'queue')",context),'—');assert(vm.runInContext("diagnosticsDuration(5000,'queue')",context).includes('diag-within'));assert(vm.runInContext("diagnosticsDuration(5001,'queue')",context).includes('diag-over'));assert(!vm.runInContext("diagnosticsDuration(100,'unknown')",context).includes('diag-'));
 const load=()=>vm.runInContext('loadAdminDiagnostics()',context);
 const noUsage={covered_s:0,cpu_s:null,average_cores:null,rss_samples:0,peak_sampled_rss_bytes:null};
 const workerUsage={covered_s:60,cpu_s:15,average_cores:0.25,rss_samples:1,peak_sampled_rss_bytes:8388608};
 const emptyWindow={supervisor:noUsage,worker:noUsage};
 fixture.resources={
  status:'fresh',sampled_at:'2026-11-10T04:59:59Z',age_s:1,
  sample:{at:'2026-11-10T04:59:59Z',elapsed_s:60,
   supervisor_cpu_s:0,supervisor_average_cores:0,supervisor_rss_bytes:null,
   worker_cpu_s:15,worker_average_cores:0.25,worker_rss_bytes:4194304,
   cgroup_cpu_ceiling_cores:0.5,cgroup_cpu_quota_cores:0.5,cgroup_cpuset_cpus:2,
   cgroup_memory_limit_bytes:null,host_logical_cpus:32},
  windows:{'5m':{...emptyWindow,worker:workerUsage},'1h':emptyWindow,'24h':emptyWindow},
  scope:{usage:'supervisor_and_owned_worker_only',limits:'supervisor_visible_cgroup_v2',
   host_logical_cpus:'system_capacity_only',account_entitlement:null}
 };
 await load();
 const includes=(...values)=>values.forEach(value=>assert(html.innerHTML.includes(value),value));
 includes('Aktuel måling','Alder 1 sek.','Aktuel · 60 sek.</th><td>0 kerner / —</td><td>0,25 kerner / 4 MB',
  '5 minutter','1 time','24 timer','0,25 kerner / 8 MB','CPU-dækning: 60 sek. · RSS-målinger: 1',
  'Worker startet af supervisor','cgroup v2-grænser for supervisor','CPU-loft 0,5 kerner','hukommelse —',
  "Værtens logiske CPU'er: 32",'Kontotildeling: ukendt');

 Object.assign(fixture.resources,{status:'stale',age_s:121,sample:null});
 await load();
 includes('Forældet måling','Alder 121 sek.','Aktuel · —</th><td>— / —</td><td>— / —','0,25 kerner / 8 MB');
 assert(!html.innerHTML.includes('0,25 kerner / 4 MB'));

 Object.assign(fixture.resources,{status:'unavailable',sampled_at:null,age_s:null,
  windows:{'5m':emptyWindow,'1h':emptyWindow,'24h':emptyWindow}});
 await load();
 includes('Måling utilgængelig','Senest målt Ikke registreret','CPU-dækning: ingen · RSS-målinger: 0','CPU-loft —');
 assert(!html.innerHTML.includes('0,25 kerner'));
 const adminMarkup=html.innerHTML;
 fixture.resources.status='fresh';
 context.state.user.role='member';await vm.runInContext('loadAdminDiagnostics()',context);assert.equal(fetches,4);assert.equal(html.innerHTML,adminMarkup);console.log('PASS administrator dashboard rendering and escaping')})().catch(e=>{console.error(e);process.exit(1)});
