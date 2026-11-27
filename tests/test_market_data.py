"""Contract-shaped synthetic quotes. No provider requests or production seeding."""
import copy,json,unittest
from unittest.mock import patch
from datetime import datetime,timezone,timedelta
from pathlib import Path
import test_trade_service as fixtures
import app,market_data,report_ingest,trade_service

SAMPLE=Path(__file__).parent/'fixtures/pluto-series-synthetic.json'
class TimestampNormalization(unittest.TestCase):
 def setUp(self):
  self.raw=json.loads(SAMPLE.read_text())
  self.fixed=datetime(2026,11,2,12,tzinfo=timezone.utc)
 def test_unrepresentable_utc_history_preserves_quote(self):
  self.raw['price']['timestamp']=self.fixed.isoformat()
  for timestamp in ('0001-01-01T00:00:00+00:01','9999-12-31T23:59:59-00:01'):
   with self.subTest(timestamp=timestamp,operation='stamp'):
    with self.assertRaises(market_data.MarketError):
     market_data.stamp(timestamp)
   with self.subTest(timestamp=timestamp,operation='normalized'):
    self.raw['performance']['series'][-1]['timestamp']=timestamp
    result=market_data.normalized(self.raw,'synthetic-chart-asset',self.fixed)
    self.assertEqual(result['series'],[])
    self.assertEqual(result['series_error'],'Kurshistorikken indeholder et ukendt tidspunkt.')
    self.assertEqual(result['price'],'18.636')
    self.assertEqual(result['price_time'],self.fixed.isoformat(timespec='milliseconds'))
 def test_offset_with_nanoseconds_preserves_chart_precision_and_source(self):
  timestamp='2026-10-26T10:30:00.123456789+02:30'
  self.assertEqual(market_data.stamp(timestamp).isoformat(),'2026-10-26T08:00:00.123456+00:00')
  self.raw['performance']['series'][0]['timestamp']=timestamp
  result=market_data.normalized(self.raw,'synthetic-chart-asset',self.fixed)
  self.assertIsNone(result['series_error'])
  self.assertEqual(result['series'][0]['timestamp'],'2026-10-26T08:00:00.123Z')
  self.assertEqual(result['series'][0]['source_timestamp'],timestamp)

class Quotes(unittest.TestCase):
 def setUp(self):
  self.case=fixtures.Trading();self.case.setUp();self.raw=json.loads(SAMPLE.read_text());self.fixed=datetime(2026,11,2,12,tzinfo=timezone.utc);self.calls=[];self.fail_read=False;self.multiple=False
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
     if case.fail_read:raise TimeoutError('Synthetic read outage')
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
  self.assertEqual(two['series'],one['series'])
  self.assertEqual(two['chart_domain']['history_latest_at'],one['series'][-1]['timestamp'])
  self.assertEqual(two['chart_domain']['quote_freshness']['state'],'unknown')
  with app.connect() as c:
   self.assertEqual(c.execute('SELECT count(*) FROM broker_proposals').fetchone()[0],0)
   cached=c.execute('SELECT payload FROM market_asset_cache').fetchall()
   self.assertEqual(len(cached),1)
   self.assertNotIn('chart_domain',json.loads(cached[0]['payload']))
 def domain(self,now,ticker,venue,kind,calendar=None):
  raw=copy.deepcopy(self.raw)
  raw['asset'].update(ticker=ticker,exchange=venue,type=kind)
  result=market_data.normalized(raw,'synthetic-chart-asset',now)
  with app.connect() as c:
   if calendar:
    exchange,zone,received,schedule=calendar
    c.execute('INSERT OR REPLACE INTO hw_exchange_calendar VALUES(?,?,?,?)',
              (exchange,received.isoformat(),zone,json.dumps(schedule)))
   return market_data.chart_response(result,now,c)['chart_domain']
 def test_market_domains_at_1140_use_verified_venue_and_full_us_window(self):
  now=datetime(2026,11,10,10,40,tzinfo=timezone.utc)
  for ticker,venue,exchange,zone,opening,closing,start,end,phase in [
   ('NOVOB','XCSE','CO','Europe/Copenhagen','09:00','17:00',8,16,'regular'),
   ('ASMDEE','XAMS','AS','Europe/Amsterdam','09:00','17:30',8,16.5,'regular'),
   ('ORCL','NYSE','US','America/New_York','09:30','16:00',9,25,'pre'),
   ('JDZG','NASDAQ','US','America/New_York','09:30','16:00',9,25,'pre'),
  ]:
   with self.subTest(ticker=ticker):
    schedule={'working_days':['Mon','Tue','Wed','Thu','Fri'],'excluded_dates':[],
              'open':opening,'close':closing}
    domain=self.domain(now,ticker,venue,'CS',(exchange,zone,now,schedule))
    midnight=now.replace(hour=0,minute=0)
    self.assertEqual(domain['start'],(midnight+timedelta(hours=start)).isoformat())
    self.assertEqual(domain['end'],(midnight+timedelta(hours=end)).isoformat())
    self.assertEqual(domain['phase'],phase)
    self.assertEqual(domain['session_source_time'],now.isoformat())
  self.assertEqual(self.domain(now,'ASMDEE','CHIX','CS')['phase'],'unknown')
 def test_hype_uses_copenhagen_calendar_on_weekend_and_both_dst_transitions(self):
  for month,day,hours in [(3,29,23),(10,25,25),(11,14,24)]:
   now=datetime(2026,month,day,10,40,tzinfo=timezone.utc)
   domain=self.domain(now,'HYPE','CRYPTO','CRYPTO')
   start,end=(datetime.fromisoformat(domain[key]) for key in ('start','end'))
   self.assertEqual(end-start,timedelta(hours=hours))
   self.assertEqual(domain['phase'],'continuous')
 def test_calendar_does_not_guess_holiday_early_close_or_stale_schedule(self):
  holiday=datetime(2026,11,26,10,40,tzinfo=timezone.utc)
  days=['Mon','Tue','Wed','Thu','Fri']
  for date,received,excluded,expected in [
   (26,26,['2026-11-26'],'unknown'),(27,27,['2026-11-27'],'unknown'),
   (28,28,[],'closed'),(30,27,[],'unknown'),(26,27,[],'unknown'),
  ]:
   with self.subTest(date=date,received=received):
    now=holiday.replace(day=date)
    schedule={'working_days':days,'excluded_dates':excluded,'open':'09:30','close':'16:00'}
    domain=self.domain(now,'ORCL','NYSE','CS',('US','America/New_York',holiday.replace(day=received),schedule))
    self.assertEqual(domain['phase'],expected)
    self.assertIsNone(domain['start']);self.assertIsNone(domain['end'])
 def test_future_history_point_inside_clock_skew_window_is_rejected(self):
  raw=copy.deepcopy(self.raw)
  future=(self.fixed+timedelta(seconds=1)).isoformat()
  raw['performance']['to']=future
  raw['performance']['series'].append({'timestamp':future,'close':'100'})
  result=market_data.normalized(raw,'synthetic-chart-asset',self.fixed)
  self.assertEqual(result['series'],[])
  self.assertIn('fremtidige',result['series_error'])
 def test_cached_response_recomputes_phase_and_filters_legacy_future_point(self):
  now=datetime(2026,11,10,14,30,tzinfo=timezone.utc)
  self.raw['price']['timestamp']=(now-timedelta(seconds=35)).isoformat()
  schedule={'working_days':['Mon','Tue','Wed','Thu','Fri'],'excluded_dates':[],
            'open':'09:30','close':'16:00'}
  with app.connect() as c:
   c.execute('INSERT INTO hw_exchange_calendar VALUES(?,?,?,?)',
             ('US',(now-timedelta(seconds=25)).isoformat(),'America/New_York',json.dumps(schedule)))
  with patch('market_data.datetime',wraps=datetime) as clock:
   clock.now.return_value=now-timedelta(seconds=20)
   first=market_data.quote(app.connect,1,self.request,self.factory)
   with app.connect() as c:
    old=json.loads(c.execute('SELECT payload FROM market_asset_cache').fetchone()['payload'])
    old['series'].append(dict(old['series'][-1],epoch=(now+timedelta(seconds=1)).timestamp()))
    c.execute('UPDATE market_asset_cache SET payload=?',(json.dumps(old),))
   clock.now.return_value=now
   second=market_data.quote(app.connect,1,self.request,self.factory)
  self.assertEqual((first['chart_domain']['phase'],second['chart_domain']['phase']),('pre','regular'))
  self.assertEqual(second['chart_domain']['quote_freshness']['age_s'],35)
  self.assertEqual(second['series'],first['series'])
  self.assertEqual([call['name'] for call in self.calls],['search_assets','get_asset'])
 def test_ambiguous_asset_requires_explicit_selection(self):
  self.multiple=True;result=market_data.quote(app.connect,1,self.request,self.factory)
  self.assertTrue(result['selection_required']);self.assertEqual(len(result['choices']),2);self.assertNotIn('get_asset',[c['name'] for c in self.calls])
  result=market_data.quote(app.connect,1,dict(self.request,asset_id='synthetic-chart-asset'),self.factory);self.assertEqual(result['ticker'],'CHART')
  with self.assertRaises(market_data.MarketError):market_data.quote(app.connect,1,dict(self.request,asset_id='not-in-search'),self.factory)
 def test_error_preserves_old_data_and_old_fetch_time(self):
  one=market_data.quote(app.connect,1,self.request,self.factory);self.fail_read=True
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
