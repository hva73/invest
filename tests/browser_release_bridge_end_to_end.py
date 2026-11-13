"""Synthetic real browser -> fixed transport/guard -> real proof/runner; no deploy."""
import io,json,os,sys,tempfile,threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests'),str(ROOT/'_bridge'/'tools')]
import app,release_approval
from test_portfolio_value_chart import PortfolioValueChart
import nordicway_app_release as bridge
import nordicway_deploy_request as request
import nordicway_deploy_client as client
import nordicway_deploy_guard as guard
import nordicway_deploy_runner as runner
import nordicway_owner_approval as owner
from nordicway_deploy_sequence import Outcome

SHA='a'*40;TOKEN='synthetic_token_12345';SUMMARY='Test: mobil og data'
case=PortfolioValueChart();case.setUp()
tmp=tempfile.TemporaryDirectory();bridge_dir=Path(tmp.name);bridge_dir.chmod(0o700)
key=bridge_dir/'owner-approval-key';key.write_bytes(b'k'*32);key.chmod(0o600)
ready=threading.Event();calls=[];results=[];failures=[]
event={'action':'created','sender':{'id':request.OWNER},'issue':{'number':16},
       'comment':{'user':{'id':request.OWNER},'author_association':'OWNER',
                  'body':request.PREFIX+json.dumps({'operation':'app-deploy','sha':SHA,'summary':SUMMARY})}}
parsed=request.parse(event,'issue_comment',request.BRANCH,str(request.OWNER));assert parsed

def deploy(sha,token,owner_request):
 calls.append(sha)
 return runner.run(sha,token,bridge=bridge_dir,authorization_lock=bridge_dir/'lock',owner_request=owner_request,
                   adapter_factory=Mock(),deploy=lambda *_:Outcome('ok','complete',True),prepare=lambda *_:None)

def transport(command,**kwargs):
 assert command[-1]=='escape-deploy-v1 app-deploy '+SHA
 def app_run(sha):
  return bridge.run_request(sha,io.BytesIO(kwargs['input']),app.connect,bridge_dir,
                            runner=deploy,create_proof=owner.create_proof,notify=lambda uid:ready.set(),lifetime=60)
 result=guard.dispatch(command[-1],app_runner=app_run)
 return SimpleNamespace(returncode=guard.exit_code(result),stdout=json.dumps(result).encode())

def worker():
 try:
  env={'ESCAPE_RELEASE_SHA':SHA,'ESCAPE_CPANEL_API_TOKEN':TOKEN,'ESCAPE_DEPLOY_OPERATION':'app-deploy',
       'ESCAPE_RELEASE_SUMMARY':parsed['summary'],'ESCAPE_DEPLOY_AUTHORIZED':'1','SSH_AUTH_SOCK':'/tmp/agent',
       'NORDICWAY_KNOWN_HOST':'synthetic','NORDICWAY_VERIFIED_FINGERPRINT':'synthetic'}
  with patch.object(client,'verify',return_value='host key\n'):
   results.append(client.run(env,transport))
 except Exception as exc:failures.append(type(exc).__name__);ready.set()
thread=threading.Thread(target=worker,daemon=True);thread.start();assert ready.wait(5) and not failures
server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
try:
 with sync_playwright() as p:
  browser=p.chromium.launch(headless=True);page=browser.new_page(viewport={'width':390,'height':844})
  page.goto(f'http://127.0.0.1:{server.server_port}/?release_approval=1')
  page.locator('#login-form [name=password]').fill('test-password-long-enough');page.locator('#login-form button').click()
  dialog=page.locator('#release-approval-dialog');expect(dialog).to_be_visible();expect(dialog).to_contain_text(SHA);assert calls==[]
  dialog.locator('[data-release-confirm]').click()
  expect(dialog).not_to_be_visible()
  thread.join(timeout=5);assert not thread.is_alive() and not failures
  assert calls==[SHA] and results==[{'operation':'app-deploy','status':'ok','sha':SHA}]
  assert not (bridge_dir/'deployment-incomplete.json').exists()
  page.locator('#release-approval-open').click()
  expect(dialog.locator('[data-release-status]')).to_have_text('Installationen er gennemført. Kontrol af app og data følger.')
  browser.close()
 print('PASS: synthetic owner browser -> fixed client/guard -> authenticated proof/runner once; no SSH or real installation')
finally:
 server.shutdown();server.server_close();thread.join(timeout=1);tmp.cleanup();case.tearDown()
