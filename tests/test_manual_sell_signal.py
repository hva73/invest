"""No-network tests: one owner-initiated CABA TEST SELL, no HOT WATCH or Pluto order."""
import json
import tempfile
import time
import unittest
from datetime import datetime,timezone,timedelta
from pathlib import Path
from unittest.mock import patch

import app
import trade_service
import portfolios


class ManualSellSignalTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.old=app.DB
        app.DB=str(Path(self.temp.name)/'escape.db')
        app.init()
        app.create_user('test-password-long-enough')
        with app.connect() as c:
            portfolios.replace_pluto(c,1,[{'id':'root-test','name':'Root','kind':'portfolio','can_trade':True}])
            self.pid=c.execute("SELECT id FROM portfolios WHERE user_id=1 AND kind='portfolio'").fetchone()[0]
        self.row={'ticker':'CABA','portfolio_kind':'portfolio','verification':'broker_snapshot',
                  'portfolio_id':self.pid,'asset_id':'caba-asset-id','quantity':'10',
                  'snapshot_at':datetime.now(timezone.utc).isoformat()}

    def tearDown(self):
        app.DB=self.old
        self.temp.cleanup()

    def start(self):
        with patch('portfolio_data.snapshots',return_value={}),patch('dashboard_projection.build',return_value={'positions':[self.row]}):
            return trade_service.start_manual_test_sell(app.connect,1,'CABA')

    def test_one_test_no_order(self):
        result=self.start()
        self.assertEqual((result['ticker'],result['side'],result['quantity']),('CABA','SELL','1'))
        self.assertFalse(result['broker_order_created'])
        with app.connect() as c:
            signal=trade_service.active_test_signal(c,1)
            self.assertEqual((signal['portfolio_id'],signal['ticker'],signal['side']),(self.pid,'CABA','SELL'))
            self.assertEqual(c.execute('SELECT COUNT(*) FROM broker_proposals').fetchone()[0],0)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM hw_events').fetchone()[0],0)

    def test_duplicate_blocked_until_expired(self):
        self.start()
        with self.assertRaisesRegex(trade_service.TradeError,'allerede et aktivt'):
            self.start()
        with app.connect() as c:c.execute('UPDATE manual_test_signals SET expires=0 WHERE user_id=1')
        self.assertEqual(self.start()['side'],'SELL')

    def test_stale_or_unverified_or_ambiguous_position_rejected(self):
        for change in ({'snapshot_at':(datetime.now(timezone.utc)-timedelta(hours=2)).isoformat()},
                       {'verification':'last_known'},{'quantity':'0.5'},{'quantity':'nonsense'},
                       {'portfolio_kind':'collection'},{'asset_id':None}):
            with self.subTest(change=change):
                self.row.update(change)
                with self.assertRaises(trade_service.TradeError):self.start()
                self.row={'ticker':'CABA','portfolio_kind':'portfolio','verification':'broker_snapshot',
                          'portfolio_id':self.pid,'asset_id':'caba-asset-id','quantity':'10',
                          'snapshot_at':datetime.now(timezone.utc).isoformat()}

    def test_recent_escapes_sell_proposal_blocks_duplicate(self):
        with app.connect() as c:
            c.execute("""INSERT INTO broker_proposals(user_id,fingerprint,report_id,candidate_id,kind,
                       portfolio_id,payload,status,created)
                       VALUES(1,'fixture','@manual-sell','','direct',?,?, 'sent', ?)""",
                      (self.pid,json.dumps({'orders':[{'assetId':'caba-asset-id','side':'SELL'}]}),time.time()))
        with self.assertRaisesRegex(trade_service.TradeError,'allerede et nyere'):
            self.start()
        with app.connect() as c:self.assertIsNone(trade_service.active_test_signal(c,1))

    def test_push_is_test_labeled_and_cannot_send_trade(self):
        import web_push
        self.start()
        with app.connect() as c:
            c.execute("INSERT INTO push_devices(user_id,endpoint_hash,payload,buy,sell,created,updated) VALUES(1,'one',X'01',1,1,0,0)")
            c.execute("INSERT INTO push_devices(user_id,endpoint_hash,payload,buy,sell,created,updated) VALUES(1,'two',X'02',1,0,0,0)")
        delivered=[]
        with patch('web_push.unseal',return_value={'endpoint':'synthetic'}):
            result=web_push.notify_manual_test_sell(app.connect,1,'CABA',
                  sender=lambda sub,payload,topic:delivered.append((payload,topic)))
        self.assertEqual(result,{'sent':1,'failed':0})
        self.assertEqual(len(delivered),1)
        payload,topic=delivered[0]
        self.assertEqual((payload['kind'],payload['tag'],topic),
                         ('manual_sell_test','escape-test-sell','escape-test-sell'))
        self.assertIn('Fiktivt',payload['body'])
        self.assertNotIn('watch_id',payload)
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM broker_proposals').fetchone()[0],0)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM hw_events').fetchone()[0],0)

    def test_test_order_provenance_rechecked_and_never_confused_with_hotwatch(self):
        self.start()
        row={'report_id':'@manual-test-sell','candidate_id':'caba-asset-id','kind':'direct',
             'portfolio_id':self.pid,'payload':json.dumps({'orders':[{'assetId':'caba-asset-id','side':'SELL','shares':'1'}]})}
        trade_service.verify_proposal_source(app.connect,1,row)
        bad=dict(row,payload=json.dumps({'orders':[{'assetId':'caba-asset-id','side':'SELL','shares':'2'}]}))
        with self.assertRaises(trade_service.TradeError):
            trade_service.verify_proposal_source(app.connect,1,bad)
        with app.connect() as c:c.execute('UPDATE manual_test_signals SET expires=0 WHERE user_id=1')
        with self.assertRaises(trade_service.TradeError):
            trade_service.verify_proposal_source(app.connect,1,row)

    def test_test_sale_rejects_more_than_one_share_before_broker(self):
        self.start()
        payload={'report_id':'@manual-test-sell','candidate_id':'','portfolio_id':self.pid,
                 'kind':'direct','asset_id':'caba-asset-id','size_mode':'percent','size':'10',
                 'currency':'USD','order_type':'MARKET','time_in_force':'DAY'}
        with patch('trade_service.direct_sell_basis',return_value={'asset_id':'caba-asset-id',
             'quantity':'10','percentage':'10','shares':'2','observed':'synthetic'}):
            with self.assertRaisesRegex(trade_service.TradeError,'præcis 1 aktie'):
                trade_service.estimate(app.connect,1,payload)
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM broker_proposals').fetchone()[0],0)

    def test_other_ticker_is_not_a_supported_live_fixture(self):
        with self.assertRaises(trade_service.TradeError):
            trade_service.start_manual_test_sell(app.connect,1,'OXY')


if __name__=='__main__':
    unittest.main()
