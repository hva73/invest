// Exercise production formatters without running browser/network startup code.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const code=fs.readFileSync('static/app.js','utf8');
const start=code.indexOf('function isUnderflow('),end=code.indexOf('function portfolioPreview(',start);
const context=vm.createContext({Intl,Number,String,Math,escape:s=>String(s).replace(/[&<>"']/g,'')});
vm.runInContext(code.slice(start,end),context);
assert.match(context.formatAmount({amount:'0.000005123456',currency:'USD'}),/0,000005123/);
assert.match(context.formatAmount({amount:'-0.00000000123',currency:'USD'}),/0,00000000123/);
assert.equal(context.formatAmount({amount:null,currency:'USD'}),'—');
assert.match(context.formatAmount({amount:'0',currency:'USD'}),/0,00/);
assert.match(context.formatAmount({amount:'1E-400',currency:'USD'}),/1E-400/);
assert.match(context.formatQuantity('3025474.45'),/3\.025\.474,45/);
assert.equal(context.formatQuantity('0.00019026'),'0,00019026');
console.log('PASS: small crypto prices stay nonzero, null differs from zero, Danish quantity formatting');
