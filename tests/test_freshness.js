const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const code=fs.readFileSync('static/app.js','utf8');const start=code.indexOf('function freshness('),end=code.indexOf('function ageMarkup(',start);
const context=vm.createContext({Date,Math,Number,formatTime:s=>s,serverClockOffset:0});vm.runInContext(code.slice(start,end),context);
const now=Date.parse('2026-11-02T12:00:00Z'),ago=minutes=>new Date(now-minutes*60000).toISOString();
const check=(source,fetched,failed=false,unknown=false)=>context.freshness(source,fetched,failed,unknown,now);
assert.equal(check(ago(9),ago(1)).tone,'recent');assert.equal(check(ago(10),ago(1)).tone,'warning');assert.equal(check(ago(30),ago(1)).tone,'stale');
assert.equal(check(ago(60),ago(0)).tone,'stale'); // A fresh fetch must not refresh an old source.
assert.equal(check(null,ago(0)).tone,'unknown');assert.equal(check(null,ago(31)).tone,'stale');
assert.equal(check(null,null).tone,'unknown');assert.equal(check(ago(-10),ago(0)).tone,'unknown');
assert.equal(check(ago(1),ago(1),true).tone,'stale');assert.equal(check(ago(1),ago(1),false,true).tone,'unknown');
assert.equal(check(ago(1),ago(31)).tone,'stale');assert.equal(check(ago(9),ago(1),false,false).label,'Kildedata er 9 min gamle');
assert.match(check(ago(40),ago(1),false,true).detail,/Hentet for 1 min siden/);
console.log('PASS: 10/30-minute boundaries, old source after fresh fetch, unknown/future timestamps, failures and mixed source coverage');
