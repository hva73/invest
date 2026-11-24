"""Synthetic acceptance harness: public-data boundary -> MCP -> report -> engine.
Issuer and Pluto evidence are fixtures, NOT actual radar or live-source verification.
All writes go to a disposable local test database; never sends an order.
"""
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, patch
import app, mcp_reports, polymarket_intelligence as poly
from test_mcp_reports import McpReports
from test_intel_workflows import merc_report
from test_hotwatch_engine import request, tick
import hotwatch_engine as engine

class PolymarketRadarChain(unittest.TestCase):
    def setUp(self):
        self.http = McpReports()
        self.http.setUp()
        self.addCleanup(self.http.tearDown)
        _, tokens, _ = self.http.granted('reports:read reports:write hotwatch:read hotwatch:manage')
        self.token = tokens['access_token']
        self.now = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(minutes=5)

    def call(self, name, args):
        status, body, _ = self.http.call(self.token, name, args)
        self.assertEqual(status, 200, body)
        self.assertIn('result', body, body)
        self.assertFalse(body['result']['isError'], body)
        return body['result']['structuredContent']

    def counts(self):
        with app.connect() as c:
            return tuple(c.execute('SELECT count(*) FROM '+table).fetchone()[0]
                         for table in ('ingested_reports', 'hw_sessions', 'broker_proposals', 'proposals'))

    def research(self):
        raw = {
            'id':'123', 'question':'SYNTHETIC: Will the FDA approve a fictional product?',
            'slug':'synthetic-market', 'active':True, 'closed':False,
            'outcomes':['Yes','No'], 'outcomePrices':['0.72','0.28'],
            'clobTokenIds':['123456','789012'], 'liquidityNum':'25000',
            'volume24hr':'9000', 'updatedAt':self.now.isoformat(),
            'endDate':(self.now+timedelta(days=1)).isoformat(),
            'events':[{'id':'55','slug':'synthetic-event'}],
            'conditionId':'0x'+'a'*64, 'description':'SYNTHETIC resolution rules',
            'resolutionSource':'https://issuer.example/fictional-resolution',
        }
        bars = {'history':[
            {'t':int((self.now-timedelta(minutes=45)).timestamp()), 'p':.45},
            {'t':int(self.now.timestamp()), 'p':.72},
        ]}
        before = self.counts()
        with patch.object(poly, '_get', side_effect=[[raw],bars]) as get:
            result = self.call('get_polymarket_intelligence', {})
        self.assertEqual(get.call_count,2)
        self.assertEqual(get.call_args_list[0].args[:2],(poly.GAMMA,'/markets'))
        self.assertEqual(get.call_args_list[1].args[:2],(poly.CLOB,'/prices-history'))
        self.assertEqual(get.call_args_list[1].args[2]['market'],'123456')
        self.assertEqual(result['status'],'RETRIEVED')
        self.assertEqual((result['handoffs'],result['orders']),(0,0))
        self.assertEqual(before,self.counts())
        item = result['observations'][0]
        self.assertTrue(item['identity_complete'])
        self.assertEqual((item['event_id'],item['market_id'],item['yes_token_id']),('55','123','123456'))
        self.assertEqual(item['research_priority'],'REVIEW')
        self.assertEqual(item['change_percentage_points'],27.0)
        self.assertFalse(item['candidate_eligible'])
        self.assertFalse(item['allowed_in_escape_candidate_payload'])
        return item

    def test_prediction_only_has_no_report_or_session_side_effect(self):
        self.research()
        self.assertEqual(self.counts(),(0,0,0,0))
        self.assertIsNone(self.call('get_latest_report',{'is_test':True})['report'])
        self.assertEqual(self.call('sync_hot_watch',{'is_test':True})['open_sessions'],[])

    def test_unavailable_does_not_prevent_ordinary_report(self):
        with patch.object(poly,'_get',side_effect=poly.PolymarketUnavailable('synthetic network failure')):
            result=self.call('get_polymarket_intelligence',{})
        self.assertEqual(result['status'],'SOURCE_UNAVAILABLE')
        self.assertEqual(self.counts(),(0,0,0,0))
        self.assertTrue(self.call('send_report',self.http.sample)['ok'])
        self.assertEqual(self.call('get_latest_report',{'is_test':True})['report']['data'],self.http.sample)
        self.assertEqual(self.counts(),(1,0,0,0))

    def test_independent_synthetic_evidence_then_real_report_engine_readback(self):
        observation=self.research()
        # Test-harness orchestration, not a claim about the hosted Radar agent.
        issuer={'ticker':'MERC','exchange':'NASDAQ','asset_id':'synthetic-MERC',
                'instrument_class':'EQUITY','currency':'USD',
                'url':'https://issuer.example/fictional-announcement','verified':True}
        identity={k:issuer[k] for k in ('ticker','exchange','asset_id','instrument_class','currency')}
        search_assets=Mock(return_value=[identity])
        get_asset=Mock(return_value=identity)
        self.assertTrue(issuer['verified'])
        self.assertNotEqual(issuer['url'],observation['url'])
        found=search_assets(issuer['ticker'])
        self.assertEqual(len(found),1)
        actual=get_asset(found[0]['asset_id'])
        self.assertEqual(actual,identity)
        search_assets.assert_called_once_with('MERC')
        get_asset.assert_called_once_with('synthetic-MERC')
        self.assertNotIn(actual['asset_id'],(observation['market_id'],observation['yes_token_id']))
        report=merc_report(True)
        report['generated_at']=self.now.isoformat()
        report['source']='SYNTHETIC POLYMARKET CHAIN – NO REAL MARKET EVIDENCE'
        report['summary']['overview']='SYNTHETIC external prediction context; independent fictional issuer evidence is required.'
        report['sources'][0].update(url=issuer['url'],publisher='SYNTHETIC independent issuer fixture')
        req=request()
        req['trade_cycle_id']='synthetic-radar-cycle'
        report['candidates'][0]['lifecycle']={'status':'HOT_WATCH','changed_at':report['generated_at'],
            'reason':'SYNTHETIC independent issuer and instrument fixture','source_ids':['synthetic-source'],
            'trade_cycle_id':req['trade_cycle_id']}
        self.assertEqual(req['asset_id'],actual['asset_id'])
        self.assertEqual(req['exchange'],actual['exchange'])
        self.assertEqual(req['quote_currency'],actual['currency'])
        self.assertTrue(self.call('validate_report',report)['valid'])
        self.assertTrue(self.call('send_report',report)['ok'])
        saved=self.call('get_latest_report',{'is_test':True})['report']
        self.assertEqual(saved['data'],report)
        with patch('hotwatch_engine.utc',return_value=self.now):
            self.call('start_hot_watch',req)
            engine.ingest(app.connect,1,req['watch_id'],True,tick(self.now),self.now)
        synced=self.call('sync_hot_watch',{'is_test':True})
        self.assertTrue(synced['open_sessions_complete'])
        watch=next(x for x in synced['open_sessions'] if x['watch_id']==req['watch_id'])
        self.assertEqual(watch['candidate_id'],req['candidate_id'])
        self.assertIn(watch['status'],('ACTIVE','DEGRADED'))
        self.assertEqual(self.counts(),(1,1,0,0))
        self.assertIsNone(self.call('get_latest_report',{'is_test':False})['report'])
        self.assertEqual(self.call('sync_hot_watch',{'is_test':False})['open_sessions'],[])
        self.call('control_hot_watch',{'watch_id':req['watch_id'],'is_test':True,'action':'stop'})

if __name__=='__main__':
    unittest.main()
