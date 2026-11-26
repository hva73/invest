import unittest,tempfile,threading,json,http.client,sys,sqlite3
from datetime import datetime, timezone
from unittest.mock import patch
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app
class Workflow(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();app.DB=self.tmp.name+'/test.db';app.init();app.create_user('test-password-long-enough');
  import portfolios
  with app.connect() as c:portfolios.create(c,1,'Testkonto')
  app.SESSIONS.clear();app.LOGIN_FAILURES.clear();self.server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);threading.Thread(target=self.server.serve_forever,daemon=True).start();self.cookie='';self.csrf=''
 def tearDown(self):self.server.shutdown();self.server.server_close();self.tmp.cleanup()
 def request(self,path,data=None,csrf=True):
  c=http.client.HTTPConnection('127.0.0.1',self.server.server_port);headers={'Content-Type':'application/json','Cookie':self.cookie}
  if csrf:headers['X-CSRF-Token']=self.csrf
  c.request('POST' if data is not None else 'GET','/api/'+path,json.dumps(data) if data is not None else None,headers);r=c.getresponse();body=json.loads(r.read());cookie=r.getheader('Set-Cookie')
  if cookie:self.cookie=cookie.split(';')[0]
  status=r.status;c.close();return status,body
 def login(self):
  self.assertEqual(self.request('login',{'password':'test-password-long-enough'})[0],200);self.csrf=self.request('session')[1]['csrf']
 def test_journal_execution_provenance(self):
  import journal_projection
  now=datetime(2025,1,8,12,tzinfo=timezone.utc)
  observed=now.isoformat()
  changed='2025-01-08T11:59:00+00:00'
  filled={'status':'FILLED','status_time':changed,'side':'BUY','requested_quantity':'7.125','filled_quantity':'7.125'}
  partial=dict(filled,status='OPEN',status_time=None,filled_quantity='2.375')
  future=dict(filled,status_time='2025-01-08T12:01:00Z')
  with app.connect() as c:
   def insert(order, cycle, status, evidence, uid=1, is_test=0, verification='pluto'):
    payload=json.dumps(dict(evidence,cycle_id='obsolete-cycle'))
    row=c.execute('''INSERT INTO candidate_execution_events
      (user_id,is_test,candidate_id,cycle_id,order_id,event_key,status,occurred,occurred_at,origin,verification,payload)
      VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',(uid,is_test,'candidate',cycle,order,order,status,now.timestamp(),observed,'watch',verification,payload))
    return row.lastrowid,payload
   linked,_=insert('linked-order','stored-cycle','FILLED',filled)
   unlinked,original=insert('unlinked-order',None,'PARTIALLY_FILLED',partial)
   future_id,_=insert('future-order','stored-cycle','FILLED',future)
   insert('other-owner',None,'FILLED',filled,uid=2)
   insert('test-order',None,'FILLED',filled,is_test=1)
   insert('unverified',None,'FILLED',filled,verification='reported')
   proposal=c.execute('''INSERT INTO broker_proposals
     (user_id,fingerprint,report_id,candidate_id,kind,portfolio_id,payload,status,created,response)
     VALUES (1,'proposal','report','candidate','direct',1,'{}','sent',?,?)''',
     (now.timestamp(),json.dumps({'status':'accepted'}))).lastrowid

  events=journal_projection.read(app.connect,1,now=now,source='Pluto',kind='order')['events']
  self.assertEqual([e['id'] for e in events],[f'execution:{future_id}',f'execution:{unlinked}',f'execution:{linked}'])
  for event,order,cycle,evidence,title,at,basis in [
    (events[0],'future-order','stored-cycle',future,'Observeret ordrestatus: FILLED',observed,'observed_not_execution'),
    (events[1],'unlinked-order',None,partial,'Observeret ordrestatus: PARTIALLY_FILLED',observed,'observed_not_execution'),
    (events[2],'linked-order','stored-cycle',filled,'FILLED',changed,'provider_status_time')]:
   with self.subTest(order=order):
    self.assertEqual(event['timestamp'],at)
    self.assertEqual(event['title'],title)
    self.assertEqual(event['details'],dict(evidence,order_id=order,candidate_id='candidate',cycle_id=cycle,
                                          observed_at=observed,time_basis=basis))
  with app.connect() as c:
   self.assertEqual(c.execute('SELECT payload FROM candidate_execution_events WHERE id=?',(unlinked,)).fetchone()[0],original)

  self.login()
  status,journal=self.request('dashboard/journal?kind=order&days=36500')
  self.assertEqual(status,200)
  entries={e['id']:e for e in journal['events']}
  proposal_key=f'proposal:{proposal}'
  self.assertEqual(set(entries),{f'execution:{linked}',f'execution:{unlinked}',f'execution:{future_id}',proposal_key})
  self.assertEqual(entries[f'execution:{future_id}']['timestamp'],observed)
  self.assertEqual(entries[proposal_key]['source'],'App/system')
  self.assertEqual(entries[proposal_key]['details']['provider_status'],'accepted')
  self.assertIs(entries[proposal_key]['details']['proposal_not_fill'],True)
 def test_state_database_busy_returns_json_and_preserves_fallback_diagnosis(self):
  import hotwatch_supervisor
  self.login();original=app.connect
  def quick():
   c=original();c.execute('PRAGMA busy_timeout=25');return c
  holder=sqlite3.connect(app.DB)
  try:
   holder.execute('BEGIN EXCLUSIVE')
   with patch.object(app,'connect',side_effect=quick):
    status,body=self.request('state')
   self.assertEqual(status,503)
   self.assertIn('midlertidigt optaget',body['error'])
   log=hotwatch_supervisor.application_error_fallback()
   self.assertEqual(log['status'],'AVAILABLE')
   self.assertIn({'event':'site_state','code':1},[{k:r[k] for k in ('event','code')} for r in log['events']])
   self.assertTrue(any(r['event']=='site_sqlite_error' and r['code']==sqlite3.SQLITE_BUSY for r in log['events']))
  finally:holder.rollback();holder.close()
  self.assertEqual(self.request('state')[0],200)
 def test_state_projection_failure_is_logged_without_private_text(self):
  self.login()
  with patch('dashboard_projection.build',side_effect=ValueError('private account token')):
   status,body=self.request('state')
  self.assertEqual(status,500);self.assertNotIn('private',json.dumps(body))
  self.assertTrue(body['error_logged'])
  with app.connect() as c:
   rows=[dict(r) for r in c.execute('SELECT event,code FROM hw_supervisor_events')]
  self.assertIn({'event':'site_state','code':2},rows)
  self.assertNotIn('private',str(rows))
  with patch('dashboard_projection.build',side_effect=ValueError('private')),patch('hotwatch_supervisor.application_error',return_value=False):
   status,body=self.request('state')
  self.assertEqual(status,500);self.assertFalse(body['error_logged'])
  self.assertIn('Fejlloggen kunne heller ikke gemmes',body['error'])
 def test_protected_workflow(self):
  self.assertEqual(self.request('state')[0],401);self.login()
  p={'portfolio_id':1,'ticker':'TEST','quantity':2,'price':100,'stop':90,'target':120,'costs':5,'fx':7}
  self.assertEqual(self.request('proposals',p,False)[0],403)
  self.assertEqual(self.request('proposals',p)[0],201)
  state=self.request('state')[1];self.assertEqual(len(state['proposals']),1);self.assertEqual(state['proposals'][0]['status'],'Forslag')
  self.assertEqual(self.request('approve',{'id':1})[0],200);self.assertEqual(self.request('approve',{'id':1})[0],400)
  state=self.request('state')[1];self.assertEqual(len(state['journal']),2);self.assertEqual(state['proposals'][0]['status'],'Godkendt lokalt');self.assertTrue(all(v=='Ikke tilsluttet' for v in state['integrations'].values()))
  self.assertEqual(self.request('logout',{})[0],200);self.assertEqual(self.request('state')[0],401)
 def test_invalid_values_and_persistence(self):
  self.login();p={'portfolio_id':1,'ticker':'TEST','quantity':1,'price':100,'stop':110,'target':120,'costs':0,'fx':1}
  self.assertEqual(self.request('proposals',p)[0],400);p['stop']=90;p['price']=float('nan');self.assertEqual(self.request('proposals',p)[0],400)
  p['price']=100;self.assertEqual(self.request('proposals',p)[0],201);app.init();self.assertEqual(app.connect().execute('SELECT count(*) FROM proposals').fetchone()[0],1)
 def test_opportunities(self):
  data={'company':'Testfirma','ticker':'TEST','market':'Danmark','asset':'Aktier','headline':'Test af kildehenvisning','source_url':'https://example.com/source','published':'2020-01-01T12:00:00+00:00','classification':'Spekulation','catalyst':'Afventer dokumentation','risk':'Ukendt','next_action':'Læs originalkilden'}
  self.assertEqual(self.request('opportunities',data)[0],401);self.login()
  self.assertEqual(self.request('opportunities',data,False)[0],403)
  self.assertEqual(self.request('opportunities',data)[0],201)
  items=self.request('state')[1]['opportunities'];self.assertEqual(len(items),1);self.assertEqual(items[0]['headline'],data['headline'])
  for invalid in ['javascript:alert(1)','http://example.com','https://user:password@example.com']:
   data['source_url']=invalid;self.assertEqual(self.request('opportunities',data)[0],400)
  data['source_url']='https://example.com';data['published']='2020-01-01T12:00:00';self.assertEqual(self.request('opportunities',data)[0],400)
  app.init();self.assertEqual(len(self.request('state')[1]['opportunities']),1)
 def test_login_rate_limit(self):
  for _ in range(5):self.assertEqual(self.request('login',{'password':'wrong'})[0],401)
  self.assertEqual(self.request('login',{'password':'wrong'})[0],429)
if __name__=='__main__':unittest.main()
