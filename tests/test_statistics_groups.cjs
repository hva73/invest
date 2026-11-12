const assert=require('assert');
const ui=require('../static/statistics-ui.js');
const data={portfolios:[{portfolio_id:'1',name:'Depot',items:[{ticker:'WIN',name:'Winner',currency:'DKK',gross:'1200.00',gross_percent:'8.00',quantity:'12',sell_price:'1350',basis:'15000',proceeds:'16200',note:'Foreløbigt',buy_origin:'unknown',sell_origin:'unknown'},{ticker:'LOSS',name:'Loser',currency:'DKK',gross:'-300.00',gross_percent:'-5.00',quantity:'1',sell_price:'5700',note:'Foreløbigt'}]}]};
const closed=ui.render(data), wins=ui.render(data,{group:'wins'}), losses=ui.render(data,{group:'losses'});
assert(!closed.includes('statistics-trade')); assert(closed.includes('aria-expanded="false"')); assert(closed.includes('↑ +1.200,00 DKK')); assert(closed.includes('↓ −300,00 DKK'));
assert(wins.includes('WIN') && !wins.includes('LOSS')); assert(wins.includes('15.000') || wins.includes('15000')); assert(wins.includes('16200')); assert(wins.includes('Ikke afklaret'));
assert(losses.includes('LOSS') && !losses.includes('WIN')); assert(losses.includes('Kostpris for solgte andele</span><strong>Ikke oplyst')); assert(losses.includes('Gns. købspris pr. stk.</span><strong>Ikke oplyst'));
assert(!ui.render({portfolios:[]}).includes('NaN'));
console.log('PASS: skjult liste, gevinst/tab, delsalgsbeløb og ukendte oplysninger');
