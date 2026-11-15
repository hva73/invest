import os, sqlite3, unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from hotwatch_adapters import EODHDAdapter, crypto_session, unknown_context
from instrument_resolver import BTC_PLUTO_ASSET_ID
from test_eodhd_feeds import Opener, SECRET
from test_hotwatch_engine import request


class BTCMarketSessionTest(unittest.TestCase):
 def setUp(self):
  self.now=datetime(2026,11,15,10,0,tzinfo=timezone.utc)
  self.schedule={'status':'OK','exchange':'CC','exchange_open':True,'received_at':self.now.isoformat(),'timezone':'UTC','calendar':{'open':'00:00:00','close':'23:59:00','working_days':['Mon','Tue','Wed','Thu','Fri','Sat','Sun'],'excluded_dates':[]}}

 def test_only_fresh_matching_open_session_is_used(self):
  self.assertEqual(crypto_session(self.schedule,self.now.isoformat(),self.now,120)['market_status'],'REGULAR')
  for change in ({'exchange_open':False},{'exchange':'US'},{'status':'ERROR'},{'received_at':(self.now-timedelta(seconds=121)).isoformat()},{'received_at':(self.now+timedelta(seconds=1)).isoformat()},{'calendar':None}):
   with self.subTest(change=change):self.assertIsNone(crypto_session(dict(self.schedule,**change),self.now.isoformat(),self.now,120))
  self.assertIsNone(crypto_session(self.schedule,(self.now-timedelta(seconds=121)).isoformat(),self.now,120))

 def test_btc_rest_uses_separate_cc_evidence_and_preserves_unknowns(self):
  req=request();req.update(provider='eodhd',provider_symbol='BTC-USD.CC',asset_id=BTC_PLUTO_ASSET_ID,ticker='BTC',quote_currency='USD')
  opener=Opener({'code':'BTC-USD.CC','timestamp':int(self.now.timestamp()),'close':'65000','currency':'USD'})
  adapter=EODHDAdapter(lambda:sqlite3.connect(':memory:'),1,opener)
  env={'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':SECRET,'ESCAPE_HW_EODHD_WS_TRADES_ENABLED':'0','ESCAPE_HW_EODHD_BARS_ENABLED':'0'}
  with patch.dict(os.environ,env),patch('hotwatch_adapters.utc',return_value=self.now),patch('hotwatch_adapters.valid_cxe_evidence',return_value=True),patch('eodhd_capacity.Capacity.observe'),patch('eodhd_capacity.Capacity.reserve'),patch.object(adapter,'interval',return_value=60),patch.object(adapter.pluto,'safe_context',return_value=unknown_context()),patch.object(adapter,'market_status',return_value=self.schedule):
   sample=adapter.poll({'request_data':req})
  self.assertEqual(sample['market_status'],'REGULAR');self.assertEqual(sample['status_feed'],'eodhd_cc_exchange_details')
  self.assertIsNone(sample['bid']);self.assertIsNone(sample['ask']);self.assertEqual(sample['context']['tradability'],'unknown')
  from hotwatch_strategy import _risk_gate
  risk=dict(req['risk'],entry_allowed=True,exit_allowed=True)
  signal,codes,_=_risk_gate(sample,{},risk,self.now,'BUY')
  self.assertNotEqual(signal,'BUY');self.assertIn('POSITION_CONTEXT_UNKNOWN',codes)

 def test_bad_schedule_remains_unknown(self):
  self.assertIsNone(crypto_session(None,self.now.isoformat(),self.now,120))

if __name__=='__main__':unittest.main()
