"""Receipt-time history remains separate from unknown market event time."""
import json,sqlite3,unittest
import dashboard_projection as dashboard

class SnapshotHistory(unittest.TestCase):
 def setUp(self):
  self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row;dashboard.init(self.db)
 def tearDown(self):self.db.close()
 def test_snapshot_comparison_does_not_invent_market_timestamp(self):
  old={'asset_id':'asset-a','source':'pluto','currency':'USD','price_type':'latestPrice','price':'10','event_time':None,'received_at':'2026-11-03T10:00:00+00:00'}
  new={**old,'price':'11','received_at':'2026-11-03T10:05:00+00:00'}
  result=dashboard.snapshot_comparison(new,old)
  self.assertEqual(float(result['percent']),10.0);self.assertEqual(result['basis'],'pluto_snapshot_received_at');self.assertFalse(result['price_event_time_known']);self.assertIsNone(new['event_time'])
 def test_comparison_refuses_other_asset_currency_or_feed_field(self):
  old={'asset_id':'asset-a','source':'pluto','currency':'USD','price_type':'latestPrice','price':'10','received_at':'2026-11-03T10:00:00Z'}
  for key,value in [('asset_id','asset-b'),('currency','EUR'),('price_type','close')]:
   with self.subTest(key=key):self.assertIsNone(dashboard.snapshot_comparison({**old,key:value,'price':'11','received_at':'2026-11-03T10:05:00Z'},old))
 def test_observation_is_persisted_without_event_time(self):
  dashboard.remember(self.db,1,7,{'positions_complete':True,'observed':'2026-11-03T10:05:00Z','positions':[{'kind':'holding','asset_id':'asset-a','price':{'amount':'11','currency':'USD'},'price_type':'latestPrice','price_time':None}]})
  row=self.db.execute('SELECT event_time,received_at,payload FROM display_price_observations').fetchone()
  self.assertIsNone(row['event_time']);self.assertEqual(row['received_at'],'2026-11-03T10:05:00Z');self.assertIsNone(json.loads(row['payload'])['event_time'])
 def test_legacy_event_times_migrate_without_guessing_receipt_time(self):
  self.db.execute('DROP TABLE display_price_observations')
  self.db.execute('CREATE TABLE display_price_observations(id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL,portfolio_id INTEGER NOT NULL,asset_id TEXT NOT NULL,event_time TEXT NOT NULL,payload TEXT NOT NULL,digest TEXT NOT NULL,UNIQUE(user_id,portfolio_id,digest))')
  self.db.execute('INSERT INTO display_price_observations VALUES(1,1,7,"asset-a","2026-11-03T10:00:00Z","{}","old")')
  dashboard.init(self.db)
  row=self.db.execute('SELECT event_time,received_at FROM display_price_observations').fetchone()
  self.assertEqual(row['event_time'],'2026-11-03T10:00:00Z');self.assertEqual(row['received_at'],'')

if __name__=='__main__':unittest.main()
