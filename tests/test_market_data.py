"""Contract-shaped synthetic quotes. No provider requests or production seeding."""
import copy,json,unittest
from datetime import datetime,timezone
from pathlib import Path
import test_trade_service as fixtures
import app,market_data,report_ingest,trade_service

SAMPLE=Path(__file__).parent/'fixtures/pluto-series-synthetic.json'
class Quotes(unittest.TestCase):
 def setUp(self):
  self.case=fixtures.Trading();self.case.setUp();self.raw=json.loads(SAMPLE.read_text());self.fixed=datetime(2026,11,2,12,tzinfo=timezone.utc);self.calls=[];self.fail=False;self.multiple=False
  report=copy.deepcopy(self.case.report);report.update(report_id='market-report',generated_at='2027-01-01T00:00:00Z');report['candidates'][0].update(ticker='CHART',signal='AFVENT');report_ingest.save(app.connect,1,report);self.cid=report['candidates'][0]['candidate_id'];self.request={'report_id':'market-report','candidate_id':self.cid,'is_test':False}
  case=self
  class Client:
   def __init__(self,token):assert token=='synthetic'
   def tools(self):return [{'name':name,'inputSchema':copy.deepcopy(trade_service.CONTRACT[name]['inputSchema']),'annotations':{'readOnlyHint':True}} for name in ['search_assets','get_asset']]
   def request(self,method,params):
    case.calls.append(params);name=params['name']
    if name=='search_assets':
     rows=[{'id':'synthetic-chart-asset','name':'Synthetic chart asset','ticker':'CHART','exchange':'NASDAQ','currency':'USD'}]
     if case.multiple:rows.append({'id':'other-exchange','name':'Synthetic alternate exchange','ticker':'CHART','exchange':'OTHER','currency':'EUR'})
     return {'structuredContent':{'assets':rows}}
    if name=='get_asset':
     assert params['arguments']=={'assetId':'synthetic-chart-asset','period':'ONE_WEEK'}
     if case.fail:raise TimeoutError('Synthetic read outage')
     return {'structuredContent':case.raw}
    raise AssertionError('Only market reads are permitted')
  self.factory=Client
 def tearDown(self):self.case.tearDown()
 def test_actual_shape_missing_quote_time_and_daily_not_week(self):
  q=market_data.normalized(self.raw,'synthetic-chart-asset',self.fixed)
  self.assertEqual(q['price'],'18.636');self.assertEqual(q['daily_change'],'0.225');self.assertGreater(float(q['daily_change_percent']),0);self.assertLess(float(q['week_change_percent']),0)
  self.assertIsNone(q['price_time']);self.assertIsNone(q['previous_close']);self.assertEqual(len(q['series']),82)
  today=[p for p in q['series'] if p['date']=='2026-11-02'];self.assertEqual(len(today),2);self.assertGreater(float(today[0]['price']),float(today[1]['price']))
  self.assertEqual(today[0]['timestamp'],'2026-11-02T09:00:00.000Z');self.assertEqual(today[0]['source_timestamp'],'2026-11-02T09:00:00.000000000Z')
 def test_cache_preserves_fetch_time_and_reads_only_once(self):
  one=market_data.quote(app.connect,1,self.request,self.factory);two=market_data.quote(app.connect,1,self.request,self.factory)
  self.assertEqual(one['fetched_at'],two['fetched_at']);self.assertTrue(two['cached']);self.assertEqual([c['name'] for c in self.calls],['search_assets','get_asset'])
  with app.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM broker_proposals').fetchone()[0],0)
 def test_ambiguous_asset_requires_explicit_selection(self):
  self.multiple=True;result=market_data.quote(app.connect,1,self.request,self.factory)
  self.assertTrue(result['selection_required']);self.assertEqual(len(result['choices']),2);self.assertNotIn('get_asset',[c['name'] for c in self.calls])
  result=market_data.quote(app.connect,1,dict(self.request,asset_id='synthetic-chart-asset'),self.factory);self.assertEqual(result['ticker'],'CHART')
  with self.assertRaises(market_data.MarketError):market_data.quote(app.connect,1,dict(self.request,asset_id='not-in-search'),self.factory)
 def test_error_preserves_old_data_and_old_fetch_time(self):
  one=market_data.quote(app.connect,1,self.request,self.factory);self.fail=True
  with app.connect() as c:c.execute('UPDATE market_asset_cache SET attempted=0')
  old=market_data.quote(app.connect,1,self.request,self.factory);self.assertEqual(old['fetched_at'],one['fetched_at']);self.assertIn('fejlede',old['last_error'])
 def test_owner_and_test_partition_before_network(self):
  for user,data in [(2,self.request),(1,dict(self.request,is_test=True)),(1,dict(self.request,candidate_id='unknown'))]:
   with self.assertRaises((market_data.MarketError,ValueError,KeyError)):market_data.quote(app.connect,user,data,self.factory)
  self.assertEqual(self.calls,[])
 def test_bad_series_does_not_invent_chart_or_remove_valid_quote(self):
  for change in ['timezone','currency','conflict','future','period']:
   raw=copy.deepcopy(self.raw)
   if change=='timezone':raw['performance']['series'][0]['timestamp']='2026-10-26T08:00:00'
   if change=='currency':raw['performance']['currency']='EUR'
   if change=='conflict':raw['performance']['series'].append(dict(raw['performance']['series'][0],close='999'))
   if change=='future':raw['performance']['series'][-1]['timestamp']='2099-01-01T00:00:00Z'
   if change=='period':raw['performance']['period']='ONE_MONTH'
   q=market_data.normalized(raw,'synthetic-chart-asset',self.fixed);self.assertEqual(q['series'],[]);self.assertTrue(q['series_error']);self.assertEqual(q['price'],'18.636')
 def test_negative_zero_unknown_and_conflicting_changes(self):
  for delta,pct in [('-0.225','-1.22'),('0','0'),(None,None)]:
   raw=copy.deepcopy(self.raw);raw['price'].update(dailyChange=delta,dailyChangePercent=pct);q=market_data.normalized(raw,'synthetic-chart-asset',self.fixed);self.assertEqual(q['daily_change'],delta);self.assertEqual(q['daily_change_percent'],pct)
  raw=copy.deepcopy(self.raw);raw['price']['dailyChangePercent']=-1;q=market_data.normalized(raw,'synthetic-chart-asset',self.fixed);self.assertIsNone(q['daily_change']);self.assertIsNone(q['daily_change_percent']);self.assertTrue(q['daily_note'])
 def test_wrong_asset_is_rejected(self):
  with self.assertRaises((market_data.MarketError,ValueError)):market_data.normalized(self.raw,'different-asset',self.fixed)
