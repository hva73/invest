'use strict';
const assert = require('assert');
const ui = require('../static/statistics-ui.js');
function container() { return {innerHTML:'',addEventListener(){},querySelectorAll(){return []}}; }
(async()=>{
  let el=container();
  await ui.mount(el,async()=>{const error=new Error('PRIVATE TOKEN');error.details={diagnostic:'BROKER_CATALOG'};throw error;});
  assert(el.innerHTML.includes('(BROKER_CATALOG)'));assert(!el.innerHTML.includes('PRIVATE TOKEN'));
  el=container();
  await ui.mount(el,async()=>{const error=new Error('SECRET');error.details={diagnostic:'<script>SECRET</script>'};throw error;});
  assert(el.innerHTML.includes('(REQUEST)'));assert(!el.innerHTML.includes('SECRET'));
  el=container();
  await ui.mount(el,async()=>({portfolios:[{items:{}}]}));
  assert(el.innerHTML.includes('(DISPLAY)'));
  el=container();
  await ui.mount(el,async()=>({portfolios:[],errors:[]}));
  assert(el.innerHTML.includes('Hvordan står det til'));
  el=container();
  await ui.mount(el,async()=>({portfolios:[],errors:['incomplete'],error_codes:['DIRECT_PERMISSION','<script>SECRET</script>']}));
  assert(el.innerHTML.includes('DIRECT_PERMISSION'));assert(!el.innerHTML.includes('SECRET'));
  console.log('Statistics diagnostics PASS');
})().catch(error=>{console.error(error);process.exitCode=1;});

