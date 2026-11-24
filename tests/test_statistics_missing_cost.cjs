const assert=require('node:assert/strict');
const ui=require('../static/statistics-ui.js');
const data={portfolios:[{portfolio_id:1,name:'Test',items:[],unresolved_sales:[{ticker:'NO',name:'Unknown',currency:'USD',quantity:'2',sell_price:'12',sale_proceeds:'24'}],omitted:1}],errors:[]};
const html=ui.render(data);
assert(html.includes('1 salg uden fuldt DKK-resultat'));
assert(html.includes('0 af 1 salg · omregnet til DKK'));
assert.match(html,/class="st-total neutral"[^>]*>—/);
assert.match(html,/data-statistics-list="unresolved"[^>]*>/);
assert(html.includes('0 med gevinst'));
assert(html.includes('0 med tab'));
assert(html.includes('Resultat ikke afklaret'));
assert(html.includes('Detaljer for Unknown'));
assert(!html.includes('Ingen handler med tilstrækkelige oplysninger'));
assert(html.includes('SAMLET RESULTAT')); // compact overview remains visible, but total must be unknown
assert(html.includes('Manglende købshistorik eller valutakurs tæller ikke som nul.'));
console.log('Missing cost UI PASS');
