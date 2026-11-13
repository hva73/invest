"""Contract-shaped synthetic quotes. No provider requests or production seeding."""
import copy,json,unittest
from unittest.mock import patch
from datetime import datetime,timezone,timedelta
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
 def test_local_budget_denial_remains_retryable_and_is_not_a_provider_outage(self):
  from hotwatch_adapters import DataUnavailable
  with app.connect() as c:
   payload={'positions_complete':True,'positions':[{'kind':'holding','asset_id':'synthetic-chart-asset','ticker':'CHART'}]}
   c.execute('INSERT INTO portfolio_snapshots VALUES(?,?,?,?,NULL,?)',(self.case.root,1,'2026-11-05T12:00:00+00:00',json.dumps(payload),'2026-11-05T12:00:00+00:00'))
  request={'holding_portfolio_id':self.case.root,'holding_asset_id':'synthetic-chart-asset'}
  with patch('trade_service.client',side_effect=DataUnavailable('PROVIDER_RATE_BUDGET',429)):
   with self.assertRaisesRegex(DataUnavailable,'PROVIDER_RATE_BUDGET'):market_data.quote(app.connect,1,request,self.factory)
  with app.connect() as c:
   row=c.execute('SELECT attempted,last_error FROM market_asset_cache').fetchone()
   self.assertEqual(row['attempted'],0);self.assertIsNone(row['last_error'])
  self.assertEqual(market_data.quote(app.connect,1,request,self.factory)['asset_id'],'synthetic-chart-asset')
 def test_holding_chart_requires_an_owned_active_portfolio_and_asset(self):
  with app.connect() as c:
   payload={'positions_complete':True,'positions':[{'kind':'holding','asset_id':'synthetic-chart-asset','ticker':'CHART'}]}
   c.execute('INSERT INTO portfolio_snapshots VALUES(?,?,?,?,NULL,?)',(self.case.root,1,'2026-11-05T12:00:00+00:00',json.dumps(payload),'2026-11-05T12:00:00+00:00'))
  request={'holding_portfolio_id':self.case.root,'holding_asset_id':'synthetic-chart-asset'}
  for user,params in [(2,request),(1,dict(request,holding_asset_id='other')),(1,dict(request,asset_id='other'))]:
   with self.assertRaises(market_data.MarketError):market_data.quote(app.connect,user,params,self.factory)
  self.assertEqual(self.calls,[])
  result=market_data.quote(app.connect,1,request,self.factory)
  self.assertEqual(result['asset_id'],'synthetic-chart-asset');self.assertEqual(len(result['series']),82)
  self.assertEqual([c['name'] for c in self.calls],['get_asset'])
 def test_month_and_year_use_separate_cached_pluto_periods(self):
  case=self
  class Extended(self.factory):
   def request(self,method,params):
    if params['name']=='get_asset' and params['arguments']['period'] in ('ONE_MONTH','ONE_YEAR'):
     case.calls.append(params);raw=copy.deepcopy(case.raw);raw['performance']['period']=params['arguments']['period'];return {'structuredContent':raw}
    return super().request(method,params)
  week=market_data.quote(app.connect,1,self.request,Extended)
  month=market_data.quote(app.connect,1,{**self.request,'period':'ONE_MONTH'},Extended)
  year=market_data.quote(app.connect,1,{**self.request,'period':'ONE_YEAR'},Extended)
  cached=market_data.quote(app.connect,1,{**self.request,'period':'ONE_MONTH'},Extended)
  self.assertEqual((week['series_period'],month['series_period'],year['series_period']),('ONE_WEEK','ONE_MONTH','ONE_YEAR'))
  self.assertTrue(cached['cached']);self.assertEqual([c['arguments']['period'] for c in self.calls if c['name']=='get_asset'],['ONE_WEEK','ONE_MONTH','ONE_YEAR'])
  with self.assertRaises(market_data.MarketError):market_data.quote(app.connect,1,{**self.request,'period':'INVALID'},Extended)
 def test_actual_shape_missing_quote_time_and_daily_not_week(self):
  q=market_data.normalized(self.raw,'synthetic-chart-asset',self.fixed)
  self.assertEqual(q['price'],'18.636');self.assertEqual(q['daily_change'],'0.225');self.assertGreater(float(q['daily_change_percent']),0);self.assertLess(float(q['week_change_percent']),0)
  self.assertIsNone(q['price_time']);self.assertIsNone(q['previous_close']);self.assertEqual(len(q['series']),82)
  raw=copy.deepcopy(self.raw);raw['asset']['isin']='US1234567890';self.assertEqual(market_data.normalized(raw,'synthetic-chart-asset',self.fixed)['isin'],'US1234567890')
  today=[p for p in q['series'] if p['date']=='2026-11-02'];self.assertEqual(len(today),2);self.assertGreater(float(today[0]['price']),float(today[1]['price']))
  self.assertEqual(today[0]['timestamp'],'2026-11-02T09:00:00.000Z');self.assertEqual(today[0]['source_timestamp'],'2026-11-02T09:00:00.000000000Z')
 def test_future_quote_time_is_rejected_but_missing_and_current_are_allowed(self):
  raw=copy.deepcopy(self.raw);raw['price']['timestamp']=(self.fixed+timedelta(seconds=1)).isoformat()
  with self.assertRaisesRegex(market_data.MarketError,'fremtid'):market_data.normalized(raw,'synthetic-chart-asset',self.fixed)
  raw['price']['timestamp']=self.fixed.isoformat();self.assertEqual(market_data.normalized(raw,'synthetic-chart-asset',self.fixed)['price_time'],self.fixed.isoformat(timespec='milliseconds'))
  del raw['price']['timestamp'];self.assertIsNone(market_data.normalized(raw,'synthetic-chart-asset',self.fixed)['price_time'])
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
 def test_future_quote_does_not_overwrite_last_known_cache(self):
  one=market_data.quote(app.connect,1,self.request,self.factory)
  self.raw['price']['timestamp']='2099-01-01T00:00:00Z'
  with app.connect() as c:c.execute('UPDATE market_asset_cache SET attempted=0')
  old=market_data.quote(app.connect,1,self.request,self.factory)
  self.assertEqual(old['fetched_at'],one['fetched_at']);self.assertEqual(old['price'],one['price']);self.assertIn('fejlede',old['last_error'])
 def test_owner_and_test_partition_before_network(self):
  for user,data in [(2,self.request),(1,dict(self.request,is_test=True)),(1,dict(self.request,candidate_id='unknown'))]:
   with self.assertRaises((market_data.MarketError,ValueError,KeyError)):market_data.quote(app.connect,user,data,self.factory)
  self.assertEqual(self.calls,[])
 def test_intraday_requires_verified_identity_and_keeps_only_actual_completed_bars(self):
  now=self.fixed;calls=[]
  class Feed:
   def intraday(self,symbol,**kwargs):
    calls.append((symbol,kwargs))
    return {'status':'OK','bars':[
     {'bar_open_at':(now-timedelta(seconds=120)).isoformat(),'close':'10'},
     {'bar_open_at':(now-timedelta(seconds=60)).isoformat(),'close':'11'},
     {'bar_open_at':(now-timedelta(seconds=10)).isoformat(),'close':'12'}]}
  result={'asset_id':'synthetic-chart-asset','ticker':'CHART','exchange':'NASDAQ','currency':'USD','series':[{'epoch':(now-timedelta(hours=1)).timestamp()}]}
  with patch.dict('os.environ',{'ESCAPE_EODHD_API_KEY':'synthetic','ESCAPE_HW_EODHD_REST_ENABLED':'1'}):
   with patch('hotwatch_service.verified_existing_feed',return_value=None):
    out=market_data.enrich_intraday(app.connect,1,result,now,lambda:Feed())
    self.assertEqual(out['intraday_status'],'IDENTITY_UNVERIFIED');self.assertNotIn('intraday_series',out);self.assertEqual(calls,[])
   with patch('hotwatch_service.verified_existing_feed',return_value={'provider_symbol':'CHART.US'}):
    out=market_data.enrich_intraday(app.connect,1,result,now,lambda:Feed())
    self.assertEqual(out['intraday_status'],'OK');self.assertEqual([p['price'] for p in out['intraday_series']],['10','11'])
    self.assertEqual(len(calls),1);self.assertIsNone(calls[0][1]['max_points'])
    cached=market_data.enrich_intraday(app.connect,1,out,now,lambda:Feed());self.assertEqual(len(calls),1);self.assertEqual(cached['intraday_series'],out['intraday_series'])
   with patch('hotwatch_service.verified_existing_feed',return_value=None):
    revoked=market_data.enrich_intraday(app.connect,1,cached,now,lambda:Feed());self.assertEqual(revoked['intraday_status'],'IDENTITY_UNVERIFIED');self.assertNotIn('intraday_series',revoked)
 def test_intraday_does_not_replace_a_more_detailed_pluto_series(self):
  now=self.fixed
  class Feed:
   def intraday(self,*args,**kwargs):
    return {'status':'OK','bars':[{'bar_open_at':(now-timedelta(seconds=120)).isoformat(),'close':'10'}]}
  result={'asset_id':'synthetic-chart-asset','ticker':'CHART','exchange':'NASDAQ','currency':'USD','series':[{'epoch':(now-timedelta(seconds=i)).timestamp()} for i in (120,180,240)]}
  with patch.dict('os.environ',{'ESCAPE_EODHD_API_KEY':'synthetic','ESCAPE_HW_EODHD_REST_ENABLED':'1'}),patch('hotwatch_service.verified_existing_feed',return_value={'provider_symbol':'CHART.US'}):
   out=market_data.enrich_intraday(app.connect,1,result,now,lambda:Feed())
   self.assertEqual(out['intraday_status'],'PLUTO_AS_DETAILED');self.assertNotIn('intraday_series',out)
 def test_intraday_unavailable_never_invents_a_series(self):
  class Feed:
   def intraday(self,*args,**kwargs):return {'status':'RATE_LIMIT'}
  result={'asset_id':'synthetic-chart-asset','ticker':'CHART','exchange':'NASDAQ','currency':'USD','series':[]}
  with patch.dict('os.environ',{'ESCAPE_EODHD_API_KEY':'synthetic','ESCAPE_HW_EODHD_REST_ENABLED':'1'}),patch('hotwatch_service.verified_existing_feed',return_value={'provider_symbol':'CHART.US'}):
   out=market_data.enrich_intraday(app.connect,1,result,self.fixed,lambda:Feed())
   self.assertEqual(out['intraday_status'],'SOURCE_UNAVAILABLE');self.assertNotIn('intraday_series',out)
 def test_more_than_ten_thousand_real_source_points_are_not_discarded(self):
  raw=copy.deepcopy(self.raw);end=self.fixed;start=end-timedelta(seconds=10000)
  raw['performance']['from']=start.isoformat();raw['performance']['to']=end.isoformat()
  raw['performance']['series']=[{'timestamp':(start+timedelta(seconds=i)).isoformat(),'close':str(10+i/10000)} for i in range(10001)]
  result=market_data.normalized(raw,'synthetic-chart-asset',self.fixed)
  self.assertIsNone(result['series_error']);self.assertEqual(len(result['series']),10001)
  self.assertEqual(result['series'][0]['source_timestamp'],raw['performance']['series'][0]['timestamp'])
  self.assertEqual(result['series'][-1]['source_timestamp'],raw['performance']['series'][-1]['timestamp'])
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
