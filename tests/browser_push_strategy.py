import base64,json,os,secrets,sys,tempfile,threading
from pathlib import Path
from unittest.mock import patch
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
import app,oauth,web_push
from playwright.sync_api import sync_playwright,expect

def b64(b):return base64.urlsafe_b64encode(b).decode().rstrip('=')
previous=app.DB
with tempfile.TemporaryDirectory() as directory:
 app.DB=directory+'/db';env=patch.dict(os.environ,{'ESCAPE_TOKEN_KEY_FILE':directory+'/token.key','ESCAPE_PUSH_KEY_FILE':directory+'/push.pem','ESCAPE_PUBLIC_URL':'https://escape.example'});env.start();app.init();app.create_user('test-password-long-enough');oauth.setup_key();web_push.setup_key()
 public=ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(serialization.Encoding.X962,serialization.PublicFormat.UncompressedPoint)
 sub={'endpoint':'https://fcm.googleapis.com/fcm/send/synthetic-browser','keys':{'p256dh':b64(public),'auth':b64(secrets.token_bytes(16))}}
 server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
 try:
  sent=[]
  with patch('web_push._send',side_effect=lambda sub,payload,topic:sent.append(payload)),sync_playwright() as pw:
   browser=pw.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox']);page=browser.new_page(viewport={'width':390,'height':844});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
   page.add_init_script('''(() => {const raw=SUB;let current=null;const sub={endpoint:raw.endpoint,toJSON:()=>raw,unsubscribe:async()=>{current=null;return true}};Object.defineProperty(window,'PushManager',{value:function(){},configurable:true});Object.defineProperty(window,'Notification',{value:{permission:'default',requestPermission:()=>new Promise(resolve=>{window.finishPermission=()=>{window.Notification.permission='granted';resolve('granted')}})},configurable:true});Object.defineProperty(navigator.serviceWorker,'ready',{value:Promise.resolve({pushManager:{getSubscription:async()=>current,subscribe:async()=>{current=sub;return sub}}}),configurable:true})})()'''.replace('SUB',json.dumps(sub)))
   page.goto(f'http://127.0.0.1:{server.server_port}');page.locator('#login-form [name=password]').fill('test-password-long-enough');page.locator('#login-form button').click();expect(page.locator('#profile-open')).to_be_visible()
   page.locator('nav [data-view=settings]').click();expect(page.locator('[data-push-action=enable]')).to_be_enabled();page.locator('.push-settings').screenshot(path='/tmp/escape-push-settings.png');page.locator('#push-sell').uncheck();page.locator('[data-push-action=enable]').click();expect(page.locator('#push-message')).to_contain_text('Kontrollerer telefonens tilladelse');assert page.evaluate('editingData()');page.evaluate("document.dispatchEvent(new Event('visibilitychange'))");expect(page.locator('#push-message')).to_contain_text('Kontrollerer telefonens tilladelse');page.evaluate('window.finishPermission()');expect(page.locator('#push-message')).to_contain_text('slået til');assert web_push.device_preferences(app.connect,1,sub['endpoint'])=={'subscribed':True,'buy':True,'sell':False}
   page.locator('[data-push-action=test]').click();expect(page.locator('#push-message')).to_contain_text('Testbeskeden');assert len(sent)==1 and sent[0]['title']=='ESCAPE · test'
   page.locator('[data-push-action=disable]').click();expect(page.locator('#push-message')).to_contain_text('slået fra');assert not web_push.device_preferences(app.connect,1,sub['endpoint'])['subscribed']
   page.locator('nav [data-view=hot-watch]').click();page.locator('[data-view=strategy-center]').click();expect(page.locator('#strategy-preferences')).to_be_visible();expect(page.locator('.strategy-library')).to_contain_text('ESCAPE Momentum');page.locator('.strategy-center').screenshot(path='/tmp/escape-strategy-center.png');page.locator('#strategy-preferences [name=mode]').select_option('manual');page.locator('#strategy-preferences button').click();expect(page.locator('#notice')).to_contain_text('gemt');assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1');assert not errors,errors
   browser.close();print('PASS: opt-in, preferences, synthetic test push, unsubscribe and strategy center on mobile')
 finally:server.shutdown();server.server_close();env.stop();app.DB=previous
