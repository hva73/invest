const assert=require('node:assert/strict');
const ui=require('../static/statistics-ui.js');
const data={portfolios:[{portfolio_id:1,name:'Test',items:[],unresolved_sales:[{ticker:'NO',name:'Unknown',currency:'USD',quantity:'2',sell_price:'12',sale_proceeds:'24'}],omitted:1}],errors:[]};
const html=ui.render(data);
for(const value of ['1 salg uden fuldt DKK-resultat','Resultat ikke afklaret','Detaljer for Unknown','0 af 1 salg','st-no-result','data-statistics-show-group="unresolved"','data-statistics-list="unresolved"','Kostpris, solgte andele</span><strong>Ikke oplyst','Salgsbeløb</span><strong>+24,00 USD','st-total neutral'])assert.ok(html.includes(value),value);
assert.ok(!html.includes('data-statistics-currency'));console.log('Missing cost UI PASS');
