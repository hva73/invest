// Account data is never cached. Push only announces a change; the app checks the current signal.
self.addEventListener('install',()=>self.skipWaiting());
self.addEventListener('activate',event=>event.waitUntil(self.clients.claim()));
self.addEventListener('push',event=>{
 let data={};try{data=event.data?.json()||{}}catch{}
 const title=typeof data.title==='string'?data.title.slice(0,80):'ESCAPE';
 const body=typeof data.body==='string'?data.body.slice(0,160):'Åbn ESCAPE for at se den aktuelle status.';
 const watch=typeof data.watch_id==='string'&&/^[A-Za-z0-9_.:-]{1,100}$/.test(data.watch_id)?data.watch_id:'';
 const tag=typeof data.tag==='string'&&/^escape-[A-Za-z0-9-]{1,48}$/.test(data.tag)?data.tag:'escape-signal';
 event.waitUntil(self.registration.showNotification(title,{body,tag,renotify:false,data:{watch},icon:'/icon.svg'}));
});
self.addEventListener('notificationclick',event=>{
 event.notification.close();const watch=event.notification.data?.watch||'';
 const url=new URL('/',self.location.origin);if(watch)url.searchParams.set('watch_id',watch);
 event.waitUntil((async()=>{const windows=await self.clients.matchAll({type:'window',includeUncontrolled:true});const target=windows.find(w=>new URL(w.url).origin===self.location.origin);if(target){await target.navigate(url.href);return target.focus()}return self.clients.openWindow(url.href)})());
});
