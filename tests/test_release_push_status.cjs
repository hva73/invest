'use strict';
const assert=require('assert'),fs=require('fs'),vm=require('vm');
const code=fs.readFileSync('static/app.js','utf8');
const start=code.indexOf('async function openReleaseApproval(){');
assert(start>=0);
async function run(notification,expected){
 const button={},close={},status={};
 const dialog={open:false,innerHTML:'',showModal(){this.open=true},close(){this.open=false},querySelector(s){return s.includes('confirm')?button:s.includes('close')?close:status}};
 const c={state:{user:{role:'admin',username:'owner'}},document:{getElementById:()=>dialog},api:async()=>({candidate:{id:'1',sha:'a'.repeat(40),summary:'Test'},notification}),escape:String,notice(){},setTimeout(){}};
 vm.runInNewContext(code.slice(start),c);await c.openReleaseApproval();
 assert(dialog.innerHTML.includes(expected),dialog.innerHTML);
}
Promise.all([run({sent:2,failed:0},'Levering er ikke bekræftet.'),run({sent:0,failed:1},'Notifikationen kunne ikke sendes.'),run({sent:0,failed:0},'Ingen enheder kunne modtage')]).then(()=>console.log('Release push status PASS')).catch(e=>{console.error(e);process.exit(1)});
