"""Full synthetic reports, shared contract and SELECT-only validation."""
import copy,json,sqlite3,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import app,mcp_reports,report_ingest,report_validation as validation,report_v2
ROOT=Path(__file__).resolve().parents[1]

def full_report(total=9):
    d=json.loads((ROOT/'examples/report-v2-test.json').read_text())
    d['report_id']='synthetic-complete-'+str(total)
    d['sources']=[dict(d['sources'][0],source_id='synthetic-source' if i==0 else 'synthetic-source-'+str(i),verification='verified',verified_at=d['generated_at']) for i in range(11)]
    d['summary']['regions']=[{'region':r,'summary':'Synthetic region update','source_ids':['synthetic-source']} for r in ['Europe','USA','Asia','Other']]
    template=d['candidates'][0];d['candidates']=[]
    extra=[('BAVA','Bavarian Nordic A/S'),('MRVL','Marvell Technology'),('LITE','Lumentum Holdings')]
    for i in range(total):
        c=copy.deepcopy(template);ticker,name=('TEST-'+str(i),'Synthetic company '+str(i)) if i<9 else extra[i-9]
        c.update(candidate_id='synthetic-candidate-'+str(i),ticker=ticker,company_name=name)
        d['candidates'].append(c)
    for key,field,count in [('positions','position_id',11),('orders','order_id',15)]:
        template=d[key][0];d[key]=[]
        for i in range(count):
            r=copy.deepcopy(template);r.update({field:'synthetic-'+key+'-'+str(i),'candidate_id':d['candidates'][i%9]['candidate_id'],'ticker':d['candidates'][i%9]['ticker']})
            if key=='orders':r['lifecycle']=['pending','partial','filled','cancelled','rejected','unknown'][i%6]
            d[key].append(r)
    d['journal'][0].update(candidate_id=d['candidates'][0]['candidate_id'],position_id=d['positions'][0]['position_id'],order_id=d['orders'][0]['order_id'])
    return d

class Validation(unittest.TestCase):
    def setUp(self):
        self.previous=app.DB;self.tmp=tempfile.TemporaryDirectory();app.DB=self.tmp.name+'/db';app.init();app.create_user('test-password-long-enough')
    def tearDown(self):app.DB=self.previous;self.tmp.cleanup()
    def rpc(self,name,data,scope='reports:read reports:write',uid=1):
        return mcp_reports.rpc(app.connect,{'user_id':uid,'scope':scope},{'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':name,'arguments':data}})[1]
    def snapshot(self):
        with app.connect() as c:return list(c.iterdump())
    def test_A_nine_and_B_twelve_preserved_in_full(self):
        with patch('mcp_client.MCP',side_effect=AssertionError('No broker calls')):
            for total in [9,12]:
                d=full_report(total);before=self.snapshot();v=self.rpc('validate_report',d)['result']
                self.assertFalse(v['isError']);self.assertTrue(v['structuredContent']['valid']);self.assertEqual(before,self.snapshot())
                self.assertEqual(v['structuredContent']['counts'],{'portfolios':2,'positions':11,'orders':15,'candidates':total,'sources':11,'regions':4})
                sent=self.rpc('send_report',d)['result'];self.assertFalse(sent['isError']);receipt=sent['structuredContent']
                self.assertEqual(receipt['report_id'],d['report_id']);self.assertEqual(receipt['schema_version'],2);self.assertEqual(receipt['counts'],v['structuredContent']['counts'])
                self.assertEqual(report_ingest.item(app.connect,1,d['report_id'],True)['report']['data'],d)
                self.assertTrue(self.rpc('send_report',d)['result']['structuredContent']['duplicate'])
        self.assertEqual([c['ticker'] for c in full_report(12)['candidates'][-3:]],['BAVA','MRVL','LITE'])
    def test_C_unknown_market_and_costs_are_null(self):
        d=full_report(12)
        for c in d['candidates']:
            c['market'].update(price=None,volume=None,fees=None,spread=None,currency=None,as_of=None)
        self.assertTrue(report_ingest.validation(app.connect,1,d)['valid'])
        # Available tradability can coexist with unknown prices; no price is invented.
        d['candidates'][9]['tradability'].update(status='available',checked_at=d['generated_at'],source_ids=['synthetic-source'])
        self.assertTrue(report_ingest.validation(app.connect,1,d)['valid'])
    def test_D_all_errors_and_atomic_rejection(self):
        d=full_report(12);d['candidates'][9]['market']['price']={'amount':'not-money','currency':'DKK'}
        d['candidates'][10]['source_ids']=['missing-source'];del d['candidates'][11]['exit_plan'];d['candidates'][9]['market']['currency']=123
        before=self.snapshot();result=self.rpc('validate_report',d)['result']['structuredContent']
        paths={e['path'] for e in result['errors']}
        self.assertFalse(result['valid']);self.assertIn('candidates[9].market.price.amount',paths);self.assertIn('candidates[10].source_ids[0]',paths);self.assertIn('candidates[11].exit_plan',paths);self.assertIn('candidates[9].market.currency',paths)
        self.assertIn('string or null',next(e['message'] for e in result['errors'] if e['path']=='candidates[9].market.currency'))
        self.assertEqual(before,self.snapshot())
        rejected=self.rpc('send_report',d)['result'];self.assertTrue(rejected['isError']);self.assertEqual(rejected['structuredContent']['errors'],result['errors']);self.assertEqual(before,self.snapshot())
    def test_duplicates_lifecycle_and_references(self):
        d=full_report(12);d['candidates'][11]['candidate_id']=d['candidates'][9]['candidate_id'];d['orders'][2]['portfolio_id']='missing';d['journal'][0]['order_id']='missing';d['orders'][1]['lifecycle']='ACCEPTED';d['summary']['regions'][0]['source_ids']=['missing']
        errors=report_ingest.validation(app.connect,1,d)['errors'];codes={e['code'] for e in errors}
        self.assertTrue({'duplicate_id','unknown_reference','invalid_enum'}<=codes)
        self.assertIn('summary.regions[0].source_ids[0]',{e['path'] for e in errors})
    def test_nullable_does_not_mean_omittable_and_valid_known_market(self):
        d=full_report(12);c=d['candidates'][9]
        c['market'].update(price={'amount':'125.50','currency':'DKK'},volume='12345',currency='DKK',verification='verified',as_of=d['generated_at'],source_ids=['synthetic-source'])
        c['exit_plan']['max_loss']={'amount':'25','currency':'DKK'}
        self.assertTrue(report_ingest.validation(app.connect,1,d)['valid'])
        del c['market']['fees'];self.assertIn('candidates[9].market.fees',{e['path'] for e in report_ingest.validation(app.connect,1,d)['errors']})
    def test_conflict_history_deep_analysis_and_category_boundaries(self):
        d=full_report(9);report_ingest.save(app.connect,1,d)
        changed=copy.deepcopy(d);changed['summary']['overview']='Changed'
        self.assertEqual(report_ingest.validation(app.connect,1,changed)['errors'][0]['code'],'report_id_conflict')
        before=self.snapshot();self.assertEqual(report_ingest.save(app.connect,1,changed)[0],409);self.assertEqual(before,self.snapshot())
        deep=copy.deepcopy(d);deep.update(report_id='deep-test',report_type='deep_analysis',analysis_for={'report_id':d['report_id'],'candidate_id':d['candidates'][0]['candidate_id']})
        deep['candidates']=deep['candidates'][:1]
        self.assertTrue(report_ingest.validation(app.connect,1,deep)['valid'])
        self.assertFalse(report_ingest.validation(app.connect,999,deep)['valid'])
        deep['is_test']=False;self.assertFalse(report_ingest.validation(app.connect,1,deep)['valid'])
        deep['is_test']=True;report_ingest.save(app.connect,1,deep)
    def test_omissions_warn_without_trimming_or_restoring(self):
        report_ingest.save(app.connect,1,full_report(12));d=full_report(9);d['report_id']='later-nine'
        result=report_ingest.validation(app.connect,1,d);self.assertTrue(result['valid']);self.assertIn('candidates_omitted',{w['code'] for w in result['warnings']})
        receipt=report_ingest.save(app.connect,1,d)[1];self.assertEqual(receipt['counts']['candidates'],9);self.assertEqual(len(report_ingest.item(app.connect,1,d['report_id'],True)['report']['data']['candidates']),9)
    def test_stable_identity_warning_and_lowercase_rfc3339_readback(self):
        d=full_report();d['generated_at']='2026-01-02t12:00:00z';d['journal'][0]['occurred_at']='2026-01-02t12:00:00z';d['is_test']=False
        report_ingest.save(app.connect,1,d);self.assertEqual(len(report_ingest.desk(app.connect,1)['candidates']),9)
        changed=copy.deepcopy(d);changed['report_id']='identity-change';changed['candidates'][0]['ticker']='OTHER'
        checked=report_ingest.validation(app.connect,1,changed);self.assertTrue(checked['valid']);self.assertIn('candidate_identity_changed',{w['code'] for w in checked['warnings']})
    def test_limits_and_invalid_timestamp_and_types(self):
        d=full_report(12);d['candidates'][0]['market']['volume']=12.5;d['sources'][0]['verified_at']='2026-01-01T12:00:00';d['orders'][0]['requested_quantity']='NaN';d['candidates'][0]['unknown_field']='x'
        paths={e['path'] for e in report_ingest.validation(app.connect,1,d)['errors']};self.assertTrue({'candidates[0].market.volume','sources[0].verified_at','orders[0].requested_quantity','candidates[0].unknown_field'}<=paths)
        d=full_report(12);d['candidates'][0]['risks']=['a'*12000]*20;d['candidates'][1]['risks']=['b'*12000]*20
        self.assertIn('max_bytes',{e['code'] for e in report_ingest.validation(app.connect,1,d)['errors']})
    def test_read_scope_has_validation_and_cannot_send(self):
        self.assertEqual(self.rpc('send_report',full_report(),scope='reports:read')['error']['message'],'Unknown or unauthorized tool')
        self.assertTrue(self.rpc('validate_report',full_report(),scope='reports:read')['result']['structuredContent']['valid'])
    def test_validator_uses_only_selects(self):
        denied={sqlite3.SQLITE_INSERT,sqlite3.SQLITE_UPDATE,sqlite3.SQLITE_DELETE,sqlite3.SQLITE_CREATE_TABLE,sqlite3.SQLITE_DROP_TABLE,sqlite3.SQLITE_ALTER_TABLE}
        with app.connect() as c:
            c.set_authorizer(lambda action,*args:sqlite3.SQLITE_DENY if action in denied else sqlite3.SQLITE_OK)
            self.assertTrue(validation.validate(full_report(12),c,1)['valid'])
    def test_transport_schema_exact_versions(self):
        import jsonschema
        schema=mcp_reports.report_schema();jsonschema.Draft202012Validator.check_schema(schema)
        checker=jsonschema.FormatChecker()
        @checker.checks('https-url',raises=(ValueError,))
        def https(value):return not validation.schema_errors(value,report_v2.URL)
        standard=jsonschema.Draft202012Validator(schema,format_checker=checker)
        for d in [json.loads((ROOT/'examples/report-ingest-test.json').read_text()),full_report(9),full_report(12)]:
            self.assertFalse(list(standard.iter_errors(d)));self.assertTrue(validation.validate(d)['valid'])
            broken=copy.deepcopy(d);del broken['is_test'];self.assertTrue(list(standard.iter_errors(broken)));self.assertFalse(validation.validate(broken)['valid'])
        broken=full_report();del broken['candidates'][0]['market']['fees'];self.assertTrue(list(standard.iter_errors(broken)))
        broken=full_report();broken['portfolio_values']=[];self.assertTrue(list(standard.iter_errors(broken)))
        for change in ['unverified-price','negative-price','tradability-time','source-time','newline-id']:
            bad=full_report();c=bad['candidates'][0]
            if change=='unverified-price':c['market']['price']={'amount':'1','currency':'DKK'}
            if change=='negative-price':c['market']['price']={'amount':'-1','currency':'DKK'}
            if change=='tradability-time':c['tradability']['status']='available'
            if change=='source-time':bad['sources'][0]['verified_at']=None
            if change=='newline-id':bad['report_id']+='\n'
            self.assertTrue(list(standard.iter_errors(bad)),change);self.assertFalse(validation.validate(bad)['valid'],change)
        advertised={t['name']:t for t in mcp_reports.tools('reports:read reports:write')}
        self.assertEqual(advertised['validate_report']['inputSchema'],advertised['send_report']['inputSchema']);self.assertTrue(advertised['validate_report']['annotations']['readOnlyHint'])
