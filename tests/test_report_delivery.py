"""Authorized synthetic test/production deliveries in disposable databases only."""
import copy,hashlib,io,json,os,secrets,unittest
from unittest.mock import patch
import app,mcp_reports,report_ingest
import test_mcp_reports as http_fixture
from test_report_validation import full_report

def synthetic(mode=False):
    data=full_report(12)
    data.update(report_id='SYNTHETIC-DELIVERY-DO-NOT-USE',is_test=mode,source='SYNTHETISK INTEGRATIONSTEST – ingen investeringsrapport')
    data['summary']['overview']='KUN SYNTETISK TEST I MIDLERTIDIG DATABASE. Ingen reelle råd, handler eller markedsverifikation.'
    data['data_quality'].update(status='historical',note='Syntetiske tal til integrationstest, ikke til investering.')
    for i,c in enumerate(data['candidates']):
        c.update(ticker='SYNTH-'+str(i),company_name='SYNTHETISK TEST '+str(i),assessment='Syntetisk testvurdering',signal='OVERVÅG',next_action='Ingen reel handling; kun integrationstest')
    return data

class Delivery(unittest.TestCase):
    def setUp(self):
        self.http=http_fixture.McpReports();self.http.setUp()
    def tearDown(self):self.http.tearDown()
    def protected(self):
        with app.connect() as c:
            names=[r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            return {n:[tuple(r) for r in c.execute('SELECT * FROM "'+n+'"')] for n in names if n not in ['ingested_reports','report_candidate_links','report_position_links','report_delivery_evidence','candidate_decision_events','candidate_lifecycle_events','candidate_trade_cycles','candidate_execution_events','mcp_limits']}
    def exercise(self,mode):
        _,tokens,_=self.http.granted();data=synthetic(mode);events=[];before=self.protected()
        with patch('mcp_reports.audit_write',side_effect=lambda sink,e:events.append(e)),patch('mcp_client.MCP',side_effect=AssertionError('No Pluto calls')):
            valid=self.http.call(tokens['access_token'],'validate_report',data)[1]['result']['structuredContent']
            self.assertTrue(valid['valid']);self.assertEqual(valid['errors'],[]);self.assertEqual(valid['warnings'],[])
            status,response,headers=self.http.call(tokens['access_token'],'send_report',data)
            self.assertEqual(status,200);self.assertFalse(response['result']['isError']);receipt=response['result']['structuredContent']
            self.assertTrue(receipt['ok']);self.assertEqual(receipt['counts'],{'portfolios':2,'positions':11,'orders':15,'candidates':12,'sources':11,'regions':4})
            self.assertEqual(headers['X-ESCAPE-Request-Id'],receipt['delivery_trace_id'])
            read=self.http.call(tokens['access_token'],'get_latest_report',{'is_test':mode})[1]['result']['structuredContent']['report']['data'];self.assertEqual(read,data)
            other=self.http.call(tokens['access_token'],'get_latest_report',{'is_test':not mode})[1]['result']['structuredContent']['report'];self.assertIsNone(other)
            duplicate=self.http.call(tokens['access_token'],'send_report',data)[1]['result']['structuredContent'];self.assertTrue(duplicate['duplicate'])
        self.assertEqual([e.get('outcome') for e in events if e['phase']=='processed'],['stored','duplicate'])
        self.assertTrue(all(e['is_test']==mode for e in events));self.assertTrue(all(e['report_ref']==hashlib.sha256(data['report_id'].encode()).hexdigest()[:16] for e in events))
        logged=json.dumps(events);self.assertNotIn(tokens['access_token'],logged);self.assertNotIn(tokens['refresh_token'],logged);self.assertNotIn(data['source'],logged);self.assertNotIn(data['report_id'],logged);self.assertEqual(before,self.protected())
    def test_complete_test_category(self):self.exercise(True)
    def test_complete_production_category(self):self.exercise(False)
    def test_existing_test_id_cannot_be_promoted_and_original_stays_immutable(self):
        _,tokens,_=self.http.granted();test=synthetic(True);events=[]
        with patch('mcp_reports.audit_write',side_effect=lambda sink,e:events.append(e)):
            self.http.call(tokens['access_token'],'send_report',test)
            with app.connect() as c:before=[tuple(r) for r in c.execute('SELECT payload,digest FROM ingested_reports')]
            production=dict(test,is_test=False)
            validation=self.http.call(tokens['access_token'],'validate_report',production)[1]['result']['structuredContent'];self.assertFalse(validation['valid']);self.assertIn('report_id_conflict',{e['code'] for e in validation['errors']})
            rejected=self.http.call(tokens['access_token'],'send_report',production)[1]['result'];self.assertTrue(rejected['isError']);self.assertEqual(events[-1]['outcome'],'conflict')
            with app.connect() as c:self.assertEqual(before,[tuple(r) for r in c.execute('SELECT payload,digest FROM ingested_reports')])
            production['report_id']='SYNTHETIC-PRODUCTION-NEW-ID'
            self.assertFalse(self.http.call(tokens['access_token'],'send_report',production)[1]['result']['isError'])
    def test_normal_authorized_import_and_bearer_ingest_production(self):
        data=synthetic(False);headers=self.http.login();before=self.protected()
        self.assertEqual(self.http.request('/api/reports/import',data)[0],401)
        self.assertEqual(self.http.request('/api/reports/import',data,{'Cookie':headers['Cookie']})[0],403)
        status,receipt,_=self.http.request('/api/reports/import',data,headers);self.assertEqual(status,201);self.assertEqual(receipt['counts']['candidates'],12)
        with patch.dict(os.environ,{'ESCAPE_REPORT_INGEST_KEY':secrets.token_urlsafe(48),'ESCAPE_REPORT_INGEST_USER':'owner'}):
            self.assertEqual(self.http.request('/api/reports/ingest',data)[0],401)
            status,receipt,_=self.http.request('/api/reports/ingest',data,{'Authorization':'Bearer '+os.environ['ESCAPE_REPORT_INGEST_KEY']});self.assertEqual(status,200);self.assertTrue(receipt['duplicate'])
        self.assertEqual(report_ingest.latest(app.connect,1,False)['report']['data'],data);self.assertEqual(before,self.protected())
    def test_diagnostics_distinguish_validation_and_server_failures(self):
        _,tokens,_=self.http.granted();events=[];bad=synthetic(False);del bad['candidates'][0]['market']['fees']
        with patch('mcp_reports.audit_write',side_effect=lambda sink,e:events.append(e)):
            result=self.http.call(tokens['access_token'],'send_report',bad)[1]['result'];self.assertTrue(result['isError']);self.assertEqual(events[-1]['outcome'],'rejected');self.assertIn('required',events[-1]['error_codes'])
            with patch('report_ingest.save',side_effect=RuntimeError('PRIVATE-ERROR-NOT-FOR-LOGS')):
                status,result,headers=self.http.call(tokens['access_token'],'send_report',synthetic(False))
            self.assertEqual(status,500);self.assertEqual(events[-1]['outcome'],'server_error');self.assertIn('X-ESCAPE-Request-Id',headers)
        self.assertNotIn('PRIVATE-ERROR-NOT-FOR-LOGS',json.dumps(events))
    def test_passenger_writes_to_wsgi_error_stream(self):
        _,tokens,_=self.http.granted()
        import passenger_wsgi
        body=json.dumps({'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'send_report','arguments':synthetic(False)}}).encode();sink=io.StringIO();response=[]
        environ={'REQUEST_METHOD':'POST','PATH_INFO':'/mcp','CONTENT_TYPE':'application/json','CONTENT_LENGTH':str(len(body)),'HTTP_AUTHORIZATION':'Bearer '+tokens['access_token'],'REMOTE_ADDR':'127.0.0.1','wsgi.input':io.BytesIO(body),'wsgi.errors':sink}
        data=json.loads(b''.join(passenger_wsgi.application(environ,lambda status,headers:response.append((status,dict(headers))))))
        self.assertTrue(data['result']['structuredContent']['ok']);events=[json.loads(line) for line in sink.getvalue().splitlines()]
        self.assertEqual([e['phase'] for e in events],['received','processed']);self.assertEqual(events[-1]['outcome'],'stored');self.assertEqual(response[0][1]['X-ESCAPE-Request-Id'],events[-1]['trace_id'])
    def test_metadata_truthfully_keeps_write_classification(self):
        tools={t['name']:t for t in mcp_reports.tools('reports:read reports:write')};send=tools['send_report']
        self.assertEqual(send['annotations'],{'readOnlyHint':False,'destructiveHint':False,'idempotentHint':True,'openWorldHint':False});self.assertTrue(tools['validate_report']['annotations']['readOnlyHint']);self.assertIn('is_test=false',send['description']);self.assertIn('driftsoversigten',send['description'])
    def test_audit_does_not_log_private_content_and_can_fail_without_affecting_delivery(self):
        sink=io.StringIO();meta=mcp_reports.delivery_context({'method':'tools/call','params':{'name':'send_report','arguments':{'report_id':'DO-NOT-LOG','source':'secret-report-body','is_test':False,'schema_version':2}}},{'user_id':1})
        mcp_reports.audit_write(sink,{**meta,'phase':'received'});event=json.loads(sink.getvalue());self.assertEqual(event['event'],'escape_report_delivery');self.assertNotIn('DO-NOT-LOG',sink.getvalue());self.assertNotIn('secret-report-body',sink.getvalue())
        class Broken:
            def write(self,*args):raise OSError('disk full')
        mcp_reports.audit_write(Broken(),meta)
        _,tokens,_=self.http.granted()
        with patch('mcp_reports.sys.stderr',Broken()):
            self.assertFalse(self.http.call(tokens['access_token'],'send_report',synthetic(False))[1]['result']['isError'])
