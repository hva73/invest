import copy,json,tempfile,unittest
from pathlib import Path
import app,report_ingest,report_v2,mcp_reports

EXAMPLE=Path(__file__).resolve().parents[1]/'examples/report-v2-test.json'
class ReportsV2(unittest.TestCase):
 def setUp(self):
  self.previous=app.DB;self.tmp=tempfile.TemporaryDirectory();app.DB=self.tmp.name+'/db';app.init();app.create_user('test-password-long-enough');self.data=json.loads(EXAMPLE.read_text())
 def tearDown(self):app.DB=self.previous;self.tmp.cleanup()
 def save(self,data=None):return report_ingest.save(app.connect,1,data or self.data)
 def test_contract_unknowns_and_duplicate_ids(self):
  self.assertEqual(self.save()[0],201);self.assertTrue(self.save()[1]['duplicate'])
  modified=copy.deepcopy(self.data);modified['summary']['overview']='Changed';self.assertEqual(self.save(modified)[0],409)
  for change in [{'is_test':'true'},{'surprise':1},{'schema_version':True}]:
   with self.assertRaises(ValueError):report_ingest.validate(dict(self.data,**change))
  bad=copy.deepcopy(self.data);bad['candidates'].append(copy.deepcopy(bad['candidates'][0]))
  with self.assertRaises(ValueError):report_ingest.validate(bad)
 def test_unverified_market_values_rejected(self):
  for key,value in [('price',{'amount':'12','currency':'DKK'}),('volume','50')]:
   d=copy.deepcopy(self.data);d['candidates'][0]['market'][key]=value
   with self.assertRaises(ValueError):report_ingest.validate(d)
  d=copy.deepcopy(self.data);d['sources'][0].update(verification='verified',verified_at=d['generated_at']);market=d['candidates'][0]['market'];market.update(price={'amount':'12','currency':'DKK'},currency='DKK',verification='verified',as_of=d['generated_at'],source_ids=['synthetic-source']);report_ingest.validate(d)
  market['currency']='USD'
  with self.assertRaises(ValueError):report_ingest.validate(d)
 def test_overlap_cannot_be_added_or_claimed_without_sources(self):
  d=copy.deepcopy(self.data);d['consolidation']['value']={'amount':'1500','currency':'DKK'}
  with self.assertRaises(ValueError):report_ingest.validate(d)
  d['sources'][0].update(verification='verified',verified_at=d['generated_at']);con=d['consolidation'];con.update(status='documented',portfolio_ids=['test-main','test-child'],method='root_totals_including_collections',source_ids=['synthetic-source'])
  with self.assertRaises(ValueError):report_ingest.validate(d)
  con.update(portfolio_ids=['test-main'],value={'amount':'1000','currency':'DKK'});report_ingest.validate(d)
  con['value']['amount']='1001'
  with self.assertRaises(ValueError):report_ingest.validate(d)
 def test_sources_types_and_urls(self):
  for url in ['javascript:alert(1)','http://example.com','https://user:secret@example.com']:
   d=copy.deepcopy(self.data);d['sources'][0]['url']=url
   with self.assertRaises(ValueError):report_ingest.validate(d)
  d=copy.deepcopy(self.data);d['candidates'][0]['source_ids']=['missing']
  with self.assertRaises(ValueError):report_ingest.validate(d)
 def test_candidate_history_material_changes_and_deep_return(self):
  self.save();d=copy.deepcopy(self.data);d.update(report_id='second',generated_at='2026-01-03T12:00:00Z');self.save(d)
  d=copy.deepcopy(d);d.update(report_id='third',generated_at='2026-01-04T12:00:00Z',report_type='deep_analysis',analysis_for={'candidate_id':'test-candidate-alpha','report_id':self.data['report_id']});d['candidates'][0]['signal']='AFVENT';self.save(d)
  history=report_ingest.candidate_history(app.connect,1,'test-candidate-alpha',True)['events']
  self.assertEqual(history[0]['changes'],['signal']);self.assertEqual(history[1]['changes'],[])
  self.assertEqual(len(history),3)
  package=report_ingest.analysis_package(app.connect,1,{'report_id':self.data['report_id'],'candidate_id':'test-candidate-alpha','is_test':True})
  self.assertEqual(package['package']['latest_observation']['candidate']['signal'],'AFVENT');self.assertEqual(package['package']['candidate_id'],'test-candidate-alpha');self.assertEqual(package['chatgpt_url'],'https://chatgpt.com/')
  with self.assertRaises(ValueError):report_ingest.analysis_package(app.connect,999,{'report_id':self.data['report_id'],'candidate_id':'test-candidate-alpha','is_test':True})
  d.update(report_id='bad-mode',is_test=False)
  with self.assertRaises(ValueError):self.save(d)
 def test_legacy_report_preserved_byte_for_byte(self):
  v1=json.loads((EXAMPLE.parent/'report-ingest-test.json').read_text());v1.update(report_id='escape-historical-20261101-2200-v1',is_test=False)
  status,saved=self.save(v1)
  with app.connect() as c:before=tuple(c.execute('SELECT payload,digest FROM ingested_reports WHERE id=?',(saved['id'],)).fetchone())
  self.save();app.init()
  with app.connect() as c:after=tuple(c.execute('SELECT payload,digest FROM ingested_reports WHERE id=?',(saved['id'],)).fetchone())
  self.assertEqual(before,after);self.assertEqual(report_ingest.latest(app.connect,1)['report']['data'],v1)
 def test_mcp_accepts_both_versions_with_same_identity(self):
  identity={'user_id':1,'scope':'reports:read reports:write'}
  result=mcp_reports.rpc(app.connect,identity,{'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'send_report','arguments':self.data}})[1]['result']
  self.assertFalse(result['isError'])
  result=mcp_reports.rpc(app.connect,identity,{'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':'get_latest_report','arguments':{'is_test':True}}})[1]['result']
  self.assertEqual(result['structuredContent']['report']['data']['schema_version'],2)
 def test_many_candidates_large_risks_and_size_limit(self):
  d=copy.deepcopy(self.data);d['candidates']=[]
  for i in range(30):
   row=copy.deepcopy(self.data['candidates'][0]);row['candidate_id']='test-candidate-alpha' if i==0 else 'candidate-'+str(i);row['risks']=['Long synthetic risk. '*200];d['candidates'].append(row)
  for i in range(80):d['sources'].append(dict(d['sources'][0],source_id='source-'+str(i)))
  self.assertEqual(self.save(d)[0],201)
  for c in d['candidates']:c['risks']=['Too large. '*1000]*10
  with self.assertRaises(ValueError):self.save(dict(d,report_id='over-limit'))
 def test_authenticated_http_import_history_package_and_large_ingest(self):
  import http.client,threading,os,secrets
  from unittest.mock import patch
  server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
  def request(path,data=None,headers=None):
   c=http.client.HTTPConnection('127.0.0.1',server.server_port);body=json.dumps(data).encode() if data is not None else None
   c.request('POST' if data is not None else 'GET',path,body,{'Content-Type':'application/json',**(headers or {})});r=c.getresponse();result=(r.status,json.loads(r.read()),dict(r.getheaders()));c.close();return result
  try:
   self.assertEqual(request('/api/reports/schema')[0],401)
   _,_,login=request('/api/login',{'username':'owner','password':'test-password-long-enough'});cookie=login['Set-Cookie'].split(';')[0]
   _,session,_=request('/api/session',headers={'Cookie':cookie});headers={'Cookie':cookie,'X-CSRF-Token':session['csrf']}
   self.assertEqual(request('/api/reports/schema',headers=headers)[1],report_v2.SCHEMA)
   self.assertEqual(request('/api/reports/import',self.data,{'Cookie':cookie})[0],403)
   self.assertEqual(request('/api/reports/import',self.data,headers)[0],201)
   self.assertEqual(len(request('/api/reports/history?is_test=true',headers=headers)[1]['reports']),1)
   package={'report_id':self.data['report_id'],'candidate_id':'test-candidate-alpha','is_test':True}
   self.assertEqual(request('/api/reports/analysis-package',package,headers)[0],200)
   self.assertEqual(request('/api/reports/analysis-package',dict(package,is_test=False),headers)[0],400)
   large=copy.deepcopy(self.data);large['report_id']='large-http';large['candidates'][0]['risks']=['Synthetic long risk. '*500]*3
   self.assertGreater(len(json.dumps(large)),16384)
   with patch.dict(os.environ,{'ESCAPE_REPORT_INGEST_KEY':secrets.token_urlsafe(48),'ESCAPE_REPORT_INGEST_USER':'owner'}):
    auth={'Authorization':'Bearer '+os.environ['ESCAPE_REPORT_INGEST_KEY']}
    self.assertEqual(request('/api/reports/ingest',large,auth)[0],201)
  finally:server.shutdown();server.server_close()

 def test_consolidation_normalizes_timezone_but_not_currency(self):
  d=copy.deepcopy(self.data);d['sources'][0].update(verification='verified',verified_at=d['generated_at'])
  second=copy.deepcopy(d['portfolios'][0]);second.update(portfolio_id='second-root',role='other',as_of='2026-01-02T13:00:00+01:00',value={'amount':'200','currency':'DKK'});d['portfolios'].append(second)
  d['consolidation'].update(status='documented',portfolio_ids=['test-main','second-root'],method='root_totals_including_collections',value={'amount':'1200','currency':'DKK'},source_ids=['synthetic-source'])
  report_ingest.validate(d)
  second['value']['currency']='USD'
  with self.assertRaises(ValueError):report_ingest.validate(d)
 def test_desk_journal_chronology_deduplication_and_isolation(self):
  first=copy.deepcopy(self.data);first.update(report_id='journal-first',is_test=False,generated_at='2026-02-01T12:00:00Z')
  first['journal'][0].update(text='First observation',occurred_at='2026-02-01T12:00:00Z')
  self.assertEqual(self.save(first)[0],201)
  second=copy.deepcopy(first);second.update(report_id='journal-second',generated_at='2026-02-02T12:00:00Z')
  event=copy.deepcopy(second['journal'][0]);event.update(entry_id='new-event',text='Second observation',occurred_at='2026-02-02T12:00:00Z');second['journal'].append(event)
  self.assertEqual(self.save(second)[0],201)
  test=copy.deepcopy(second);test.update(report_id='journal-test-hidden',is_test=True);test['journal'][0]['text']='Hidden test';self.save(test)
  result=report_ingest.desk(app.connect,1)['journal_events']
  self.assertEqual([e['entry']['text'] for e in result],['Second observation','First observation'])
  self.assertEqual(result[0]['report_id'],'journal-second');self.assertEqual(report_ingest.desk(app.connect,999)['journal_events'],[])
 def test_desk_excludes_test_and_older_imports_and_overlays_deep(self):
  self.save();self.assertIsNone(report_ingest.desk(app.connect,1)['report'])
  base=copy.deepcopy(self.data);base.update(report_id='desk-main',is_test=False,generated_at='2026-02-01T12:00:00Z');self.save(base)
  old=copy.deepcopy(base);old.update(report_id='late-historical',generated_at='2026-01-01T12:00:00Z');self.save(old)
  deep=copy.deepcopy(base);deep.update(report_id='desk-deep',report_type='deep_analysis',generated_at='2026-02-02T12:00:00Z',analysis_for={'candidate_id':'test-candidate-alpha','report_id':'desk-main'});deep['candidates'][0]['signal']='AFVENT';self.save(deep)
  result=report_ingest.desk(app.connect,1)
  self.assertEqual(result['report']['data']['report_id'],'desk-deep');self.assertEqual(result['main_report']['data']['report_id'],'desk-main')
  self.assertEqual(result['candidates'][0]['candidate']['signal'],'AFVENT');self.assertEqual(result['candidates'][0]['report_id'],'desk-deep')
  self.assertEqual(result['portfolio_report']['data']['report_id'],'desk-main')
  self.assertIsNone(report_ingest.desk(app.connect,999)['report'])
 def test_advertised_tool_schema_exposes_both_versions(self):
  schema=mcp_reports.report_schema()
  try:import jsonschema
  except ImportError:self.skipTest('Optional development dependency jsonschema is unavailable')
  self.assertEqual(schema['properties']['schema_version']['enum'],[1,2]);self.assertNotIn('oneOf',schema)
  jsonschema.Draft202012Validator.check_schema(schema)
  jsonschema.validate(self.data,schema)
  v1=json.loads((EXAMPLE.parent/'report-ingest-test.json').read_text());jsonschema.validate(v1,schema)
  with self.assertRaises(jsonschema.ValidationError):jsonschema.validate(dict(v1,schema_version=3),schema)
