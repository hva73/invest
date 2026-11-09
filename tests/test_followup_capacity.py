"""Synthetic regressions for shared status, denied scans and position scope."""
import copy,json,unittest,time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import patch
import app,eodhd_feeds,hotwatch_engine as engine,report_ingest
from eodhd_feeds import EODHDFeeds
import test_hotwatch_engine as hwfixtures
from test_hotwatch_engine import tick,good_metrics
from hotwatch_strategy import BASELINE,calculate

class SharedStatus(unittest.TestCase):
 def setUp(self):eodhd_feeds._status_cache.clear()
 def tearDown(self):eodhd_feeds._status_cache.clear()
 def test_five_parallel_symbols_share_one_exchange_request(self):
  calls=[]
  def fetch(client,exchange):
   calls.append(exchange);client._reserve();time.sleep(.02)
   return {'status':'OK','received_at':'2026-11-09T15:00:00Z','exchange_open':True,'calendar':{'open':'09:30:00'}}
  reservations=[]
  with patch.object(EODHDFeeds,'_market_status_uncached',fetch),ThreadPoolExecutor(max_workers=5) as pool:
   results=list(pool.map(lambda _:EODHDFeeds('synthetic',reserve=lambda:reservations.append(1)).market_status('US'),range(5)))
  self.assertEqual(calls,['US']);self.assertEqual(len(reservations),1)
  self.assertEqual(len({x['received_at'] for x in results}),1)
  results[0]['calendar']['open']='changed'
  self.assertEqual(results[1]['calendar']['open'],'09:30:00')
 def test_expiry_credentials_errors_and_source_time(self):
  calls=[]
  def fetch(client,exchange):
   calls.append((client._key,exchange))
   return {'status':'OK','received_at':'original','exchange_open':True}
  with patch.object(EODHDFeeds,'_market_status_uncached',fetch),patch('eodhd_feeds.time.monotonic',return_value=10):
   first=EODHDFeeds('one').market_status('US');self.assertEqual(EODHDFeeds('one').market_status('US'),first)
   EODHDFeeds('two').market_status('US');EODHDFeeds('one').market_status('CO')
  with patch.object(EODHDFeeds,'_market_status_uncached',side_effect=AssertionError('same minute')),patch('eodhd_feeds.time.monotonic',return_value=69):
   self.assertEqual(EODHDFeeds('one').market_status('US'),first)
  with patch.object(EODHDFeeds,'_market_status_uncached',return_value={'status':'RATE_LIMIT'}) as failed,patch('eodhd_feeds.time.monotonic',return_value=71):
   self.assertEqual(EODHDFeeds('one').market_status('US')['status'],'RATE_LIMIT')
   self.assertEqual(EODHDFeeds('one').market_status('US')['status'],'RATE_LIMIT');self.assertEqual(failed.call_count,2)
  self.assertEqual(len(calls),3);self.assertEqual(first['received_at'],'original')
 def test_real_adapter_enables_shared_status_with_its_default_opener(self):
  from hotwatch_adapters import EODHDAdapter
  self.assertTrue(EODHDAdapter(None,1).feeds()._shared_status)
  self.assertFalse(EODHDAdapter(None,1,opener=object()).feeds()._shared_status)

class FollowupIntegration(unittest.TestCase):
 def setUp(self):
  self.fixture=hwfixtures.HotWatch();self.fixture.setUp();self.now=self.fixture.now
 def tearDown(self):self.fixture.tearDown()
 def test_dashboard_and_engine_share_current_status_not_analysis_warmup(self):
  import dashboard_projection
  self.fixture.put(tick(self.now))
  with app.connect() as c:c.execute('UPDATE hw_sessions SET is_test=0')
  analysis={'count':0,'required':34,'remaining':34,'state':'WARMUP','freshness':'FRESH'}
  with patch('hotwatch_warmup.status',return_value=analysis),patch('hotwatch_engine.utc',return_value=self.now):
   with app.connect() as c:
    raw=engine.view(c,c.execute('SELECT * FROM hw_sessions').fetchone())
    projected=dashboard_projection.position_hotwatch(c,1,123,self.fixture.req['asset_id'],None)['session']
   self.assertEqual(raw['display_status'],'WARMUP')
   self.assertEqual(projected['display_status'],raw['display_status'])
   self.assertEqual(projected['warmup']['count'],1) # actual calculation, not cache's zero
  with patch('hotwatch_engine.utc',return_value=self.now+timedelta(seconds=121)):
   with app.connect() as c:
    raw=engine.view(c,c.execute('SELECT * FROM hw_sessions').fetchone())
    projected=dashboard_projection.position_hotwatch(c,1,123,self.fixture.req['asset_id'],None)['session']
   self.assertEqual(projected['display_status'],raw['display_status'])
   self.assertNotEqual(raw['display_status'],'WARMUP')
 def test_projection_does_not_rewrite_current_decisions_or_blockers(self):
  import dashboard_projection
  with app.connect() as c:c.execute('UPDATE hw_sessions SET is_test=0')
  for signal,label in [('BUY','KØBSSIGNAL'),('SELL','SÆLGSSIGNAL'),('WAIT','AFVENT'),('WAIT','RISIKODATA MANGLER'),('NO_DATA','EARLY WATCH'),('NO_DATA','DATA FOR GAMLE'),('NO_DATA','KURS MODTAGET · MARKEDSSTATUS UKENDT'),('NO_DATA','HANDEL STANDSET')]:
   current={'watch_id':self.fixture.req['watch_id'],'status':'ACTIVE','signal':signal,'display_status':label,'last_data_at':self.now.isoformat(),'data_status':{'analysis_warmup':{'count':1,'required':34,'remaining':33,'state':'WARMUP','freshness':'FRESH'}}}
   with patch.object(engine,'view',return_value=current),app.connect() as c:
    projected=dashboard_projection.position_hotwatch(c,1,123,self.fixture.req['asset_id'],None)['session']
   self.assertEqual(projected['display_status'],label);self.assertEqual(projected['signal'],signal)
 def test_terminal_and_paused_states_are_explicit_in_readback(self):
  self.fixture.put(tick(self.now))
  for status,label in [('PAUSED','PAUSERET'),('COMPLETED','AFSLUTTET'),('EXPIRED','UDLØBET'),('ERROR','FEJL')]:
   with app.connect() as c:
    c.execute('UPDATE hw_sessions SET status=?',(status,))
    view=engine.view(c,c.execute('SELECT * FROM hw_sessions').fetchone(),self.now)
   self.assertEqual(view['display_status'],label)
 def test_denied_eodhd_scan_retries_next_budget_window_without_buy_or_extra_budget(self):
  req=copy.deepcopy(self.fixture.req);req.update(provider='eodhd',provider_symbol='MERC.US')
  at=self.now.replace(second=47)
  with app.connect() as c:c.execute('UPDATE hw_sessions SET request=?',(json.dumps(req),))
  with patch.object(engine,'effective_poll_interval',return_value=238):
   engine.fault(app.connect,1,req['watch_id'],True,'PROVIDER_RATE_BUDGET',at)
  with app.connect() as c:
   row=c.execute('SELECT * FROM hw_sessions').fetchone()
   self.assertEqual(row['next_due'],(int(at.timestamp()//60)+1)*60+1)
   self.assertEqual(json.loads(row['state'])['signal'],'NO_DATA')
   self.assertEqual(c.execute('SELECT count(*) FROM hw_request_budget').fetchone()[0],0)
  self.assertIsNone(engine.claim(app.connect,at+timedelta(seconds=5)))
  self.assertIsNotNone(engine.claim(app.connect,at+timedelta(seconds=14)))
  self.assertEqual(engine.provider_request_limit('eodhd'),800)
 def test_recent_holding_can_exit_on_market_weakness_without_inventing_profit(self):
  metrics=good_metrics();metrics.update(return_3_pct='-3',breakdown=True,distance_high_pct='-10')
  risk=copy.deepcopy(self.fixture.req['risk']);risk['stop_price']=None
  state={}
  for i in range(3):
   at=self.now+timedelta(seconds=i*10);sample=tick(at,held=True)
   sample['context']['cost_price']='120'
   result,state=calculate(sample,metrics,BASELINE,risk,state,at)
  self.assertEqual(result['signal'],'SELL');self.assertFalse(result['critical_override'])
  self.assertIn('ikke afkast siden køb',result['human_readable_explanation'])
  sample['context']['position']='none'
  result,_=calculate(sample,metrics,BASELINE,risk,state,at)
  self.assertNotIn(result['signal'],('SELL','REDUCE'))
 def test_trailing_exit_can_be_confirmed_before_all_indicators_warm_up(self):
  metrics=good_metrics();metrics.update(sample_count=5,distance_high_pct='-3')
  risk=copy.deepcopy(self.fixture.req['risk']);risk['stop_price']=None;state={}
  for i in range(3):
   at=self.now+timedelta(seconds=i*10)
   result,state=calculate(tick(at,held=True),metrics,BASELINE,risk,state,at)
  self.assertEqual(result['signal'],'SELL')
  self.assertNotIn('WARMUP',result['reason_codes']);self.assertIn('TRAILING_EXIT',result['reason_codes'])
  self.assertIn('toppen i det analyserede kursvindue',result['human_readable_explanation'])
 def test_smaller_report_preserves_archived_candidate_sources_and_session(self):
  original=self.fixture.r;compact=copy.deepcopy(original)
  compact.update(report_id='synthetic-compact-history',candidates=[],journal=[])
  refs=set()
  def collect(value):
   if isinstance(value,list):
    for child in value:collect(child)
   elif isinstance(value,dict):
    refs.update(value.get('source_ids',[]))
    for child in value.values():collect(child)
  collect({k:v for k,v in compact.items() if k!='sources'})
  compact['sources']=[s for s in compact['sources'] if s['source_id'] in refs]
  self.assertTrue(report_ingest.validation(app.connect,1,compact)['valid'])
  report_ingest.save(app.connect,1,compact)
  with app.connect() as c:
   saved=json.loads(c.execute('SELECT payload FROM ingested_reports WHERE report_id=?',(original['report_id'],)).fetchone()[0])
   self.assertEqual(saved,original)
   self.assertEqual(c.execute('SELECT count(*) FROM report_candidate_links').fetchone()[0],len(original['candidates']))
   self.assertEqual(c.execute('SELECT status FROM hw_sessions').fetchone()[0],'CREATED')
   self.assertEqual(c.execute('SELECT count(*) FROM broker_proposals').fetchone()[0],0)

class HoldingQuantityChanges(unittest.TestCase):
 def setUp(self):
  import test_hotwatch_holdings_auto as holding_fixtures
  self.fixture=holding_fixtures.HoldingAutowatch();self.fixture.setUp()
 def tearDown(self):self.fixture.tearDown()
 def test_partial_sale_and_additional_purchase_keep_the_owned_exit_scope(self):
  import hotwatch_service as service
  f=self.fixture
  self.assertEqual(f.tick(verify=f.verify,lookup=f.lookup),'LINKED')
  with app.connect() as c:original=c.execute('SELECT watch_id FROM hw_sessions').fetchone()[0]
  for quantity in ('0.5','2'):
   data={'positions_complete':True,'observed':f.now.isoformat(),'positions':[dict(f.holding,quantity=quantity)]}
   with app.connect() as c:c.execute('UPDATE portfolio_snapshots SET payload=?',(json.dumps(data),))
   self.assertEqual(service.reconcile_closed_holdings(app.connect,f.now),0)
   f.tick(verify=lambda *_:self.fail('existing watch must be reused'),lookup=f.lookup)
   with app.connect() as c:
    rows=c.execute('SELECT watch_id,request FROM hw_sessions').fetchall()
    self.assertEqual(len(rows),1);self.assertEqual(rows[0]['watch_id'],original)
    self.assertEqual(json.loads(rows[0]['request'])['portfolio_ids'],[f.pid])
 def test_accepted_unfilled_order_without_a_holding_does_not_start_exit_watch(self):
  f=self.fixture
  with app.connect() as c:
   c.execute('UPDATE portfolio_snapshots SET payload=?',(json.dumps({'positions_complete':True,'observed':f.now.isoformat(),'positions':[],'orders':[{'asset_id':f.holding['asset_id'],'status':'ACCEPTED','filled_quantity':'0'}]}),))
  self.assertIsNone(f.tick(verify=lambda *_:self.fail('no actual holding'),lookup=f.lookup))
  with app.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM hw_sessions').fetchone()[0],0)
