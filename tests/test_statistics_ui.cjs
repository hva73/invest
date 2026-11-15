'use strict';
const assert=require('node:assert/strict');const {render}=require('../static/statistics-ui.js');
const items=[{ticker:'GAIN',name:'Gain Co',currency:'USD',gross:'3',gross_percent:'10',quantity:'1',buy_price:'30',sell_price:'33',cost_basis:'30',sale_proceeds:'33',sell_time:null},{ticker:'LOSS',name:'Loss Co',currency:'USD',gross:'-1',gross_percent:'-5',quantity:'1',buy_price:'20',sell_price:'19',cost_basis:'20',sale_proceeds:'19',sell_time:null},{ticker:'EU',name:'Euro',currency:'EUR',gross:'100',gross_percent:'20',quantity:'1',buy_price:'500',sell_price:'600'}];
const data={portfolios:[{portfolio_id:1,name:'Depot',items},{portfolio_id:2,name:'Collection',items:[]}],errors:[]};let html=render(data,{portfolio:1,currency:'USD',group:'wins'});assert.match(html,/↑ \+2,00 USD/);assert.match(html,/↑ 1 med gevinst/);assert.match(html,/↓ 1 med tab/);assert.doesNotMatch(html,/EU<small>/);assert.match(html,/Handelstid ikke oplyst/);assert.match(html,/omkostninger/);
html=render(data,{portfolio:2});assert.match(html,/Ingen handler med tilstrækkelige oplysninger/);assert.doesNotMatch(html,/100,00/);
html=render({portfolios:[{portfolio_id:1,name:'<img src=x>',items:[{...items[0],ticker:'<script>',name:'"bad"'}]}],errors:['error']},{group:'wins'});assert.doesNotMatch(html,/<script>|<img/);assert.match(html,/&lt;script&gt;/);assert.match(html,/Nogle depoter kunne ikke læses/);
html=render({portfolios:[{portfolio_id:1,items:[{...items[0],gross:'NaN'}]}]});assert.match(html,/Ingen handler/);
html=render({portfolios:[{portfolio_id:1,items:[{...items[0],gross:'0.104'},{...items[0],gross:'0.101'}]}]});assert.match(html,/\+0,21 USD/);
let tiny={portfolios:[{portfolio_id:1,items:[{...items[0],gross:'0.000000001',gross_percent:'-0.00001'},{...items[1],gross:'-0.000000001',gross_percent:'0.00001'}]}]};html=render(tiny,{group:'wins'});assert.match(html,/\+0,000000001 USD/);assert.match(html,/class="negative">↓ −0,00001 %/);assert.match(html,/0,00 USD/);html=render(tiny,{group:'losses'});assert.match(html,/−0,000000001 USD/);assert.match(html,/class="positive">↑ \+0,00001 %/);
html=render({portfolios:[{portfolio_id:1,items:[{...items[0],gross:'0.'+'0'.repeat(179)+'1'}]}]},{group:'wins'});assert.match(html,/\+&lt;0,000000000001|\+<0,000000000001/);console.log('PASS: currency scope, precision, empty state and escaped details');

const smallPrice = {...items[0], buy_price:'0.000000001', quantity:'1000000000', cost_basis:'1', sale_proceeds:'2', gross:'1', gross_percent:'100', sell_price:'0.000000002'};
html=render({portfolios:[{portfolio_id:1,items:[smallPrice]}]},{group:'wins'});
assert.match(html,/Gns\. købspris pr\. stk\.<\/span><strong>&lt;0,000001 USD/);
assert.match(html,/Kostpris for solgte andele<\/span><strong>1 USD/);
assert.match(html,/Salgsbeløb<\/span><strong>2 USD/);
assert.doesNotMatch(html,/≈ 0,00 USD/);

// Default overview must include every depot and currency, without summing FX.
const multi={portfolios:[{portfolio_id:1,name:'Main',items:[{...items[0],sell_origin:'signal',buy_origin:'own'}]}, {portfolio_id:2,name:'AI collection',items:[{...items[2],sell_origin:'own'}],unresolved_sales:[{ticker:'UNMATCHED',name:'Missing basis',currency:'USD',quantity:'1',sell_price:'4',sale_proceeds:'4',sell_origin:'signal'}]}]};
html=render(multi);
assert.match(html,/Alle depoter<\/option>/);assert.match(html,/Alle valutaer<\/option>/);
assert.match(html,/3 afsluttede salg på tværs af alle depoter/);
assert.match(html,/\+3,00 USD/);assert.match(html,/\+100,00 EUR/);assert.doesNotMatch(html,/\+103,00/);
assert.match(html,/UNMATCHED/);assert.match(html,/Hvem stod bag salgene/);
html=render(multi,{group:'all'});assert.match(html,/Køb: Egen beslutning · Salg: ESCAPE-signal/);
html=render(multi,{portfolio:1,currency:'USD',group:'all'});assert.doesNotMatch(html,/UNMATCHED|Missing basis|Euro<small>/);
console.log('PASS: all depots/currencies by default, explicit origin and no invented FX');
