const fs=require('fs'),vm=require('vm'),assert=require('assert');
const handlers={},shown=[],opened=[];
const self={location:{origin:'https://escape.example'},registration:{showNotification:async(title,options)=>shown.push({title,options})},clients:{claim:async()=>{},matchAll:async()=>[],openWindow:async url=>opened.push(url)},skipWaiting:async()=>{},addEventListener:(name,fn)=>handlers[name]=fn};
vm.runInNewContext(fs.readFileSync('static/sw.js','utf8'),{self,URL});
(async()=>{
 let pending;handlers.push({data:{json:()=>({title:'ESCAPE · købssignal',body:'Åbn ESCAPE',watch_id:'hw-test-1',tag:'escape-watch-1'})},waitUntil:p=>pending=p});await pending;
 assert.equal(shown[0].options.data.watch,'hw-test-1');assert.equal(shown[0].options.tag,'escape-watch-1');assert.equal(shown[0].options.renotify,false);
 let closed=false;handlers.notificationclick({notification:{data:shown[0].options.data,close:()=>closed=true},waitUntil:p=>pending=p});await pending;
 assert(closed);assert.equal(opened[0],'https://escape.example/?watch_id=hw-test-1');
 handlers.push({data:{json:()=>({watch_id:'https://evil.example',tag:'bad'})},waitUntil:p=>pending=p});await pending;
 assert.equal(shown[1].options.data.watch,'');assert.equal(shown[1].options.tag,'escape-signal');
 console.log('PASS: push notification, replacement tag and same-origin current-status link');
})().catch(e=>{console.error(e);process.exitCode=1});
