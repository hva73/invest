"""Root-cause regressions: sparse provider bars, queue progress and source age."""
import copy,json,os,threading,unittest
from datetime import datetime,timedelta,timezone
from unittest.mock import Mock,patch
import app,hotwatch_engine as engine,hotwatch_service as service,hotwatch_adapters as adapters
import test_hotwatch_engine as fixture
from hotwatch_features import features,verified_bar_samples
from hotwatch_strategy import BASELINE,calculate

class SparseFeedRecovery(unittest.TestCase):
 def setUp(self):
  self.f=fixture.HotWatch();self.f.setUp();self.now=datetime(2026,11,9,19,0,30,tzinfo=timezone.utc)
  self.req=copy.deepcopy(self.f.req);self.req.update(watch_id='sparse-history',purpose='synthetic sparse history',provider='eodhd',provider_symbol='MERC.US')
  self.req['risk']['stop_price']=None
  engine.create(app.connect,1,self.req,self.now)
  adapters._ws_batch_cache.clear()
 def tearDown(self):adapters._ws_batch_cache.clear();self.f.tearDown()
 def sample(self,held=False):
  s=fixture.tick(self.now,held=held)
  s.update(source='eodhd',price_time_kind='trade',status_at=self.now.isoformat(),status_feed='us_trades',bid_at=self.now.isoformat(),ask_at=self.now.isoformat(),quote_feed='us_quotes')
  # Forty actual bars with several omitted minutes, including one near the
  # tail. Do not synthesize zero-volume candles for any absent minute.
  offsets=[i for i in range(1,48) if i not in (3,8,13,20,27,34,41)]
  s['bar_history']=[{'bar_open_at':(self.now.replace(second=0)-timedelta(minutes=i)).isoformat(),'open':'100','high':'100.1','low':'99.9','close':'100','volume':'100'} for i in reversed(offsets)]
  s['bar_evidence']={'provider_symbol':'MERC.US','market':'us','exchange':'US','timezone':'America/New_York','session_date':'2026-11-09','open':'09:30:00','close':'16:00:00','working_days':['Mon','Tue','Wed','Thu','Fri'],'excluded_dates':[],'schedule_received_at':self.now.isoformat(),'exchange_open':True,'feed':'eodhd_realtime_history'}
  return s
 def test_sparse_bars_support_period_indicators_without_inventing_minutes(self):
  s=self.sample();rows=verified_bar_samples(s,self.req,self.now);m=features(rows,BASELINE['parameters'])
  self.assertEqual(len(rows),40);self.assertEqual(m['sample_count'],40)
  for name in ('rsi','macd_histogram','ema_long','atr','relative_volume','return_3_pct'):self.assertIsNotNone(m[name],name)
  # Remove the actual three-minute reference: period indicators survive,
  # but neither the 3m return nor the 3m entry momentum may be guessed.
  rows=[r for r in rows if r['event_time']!=(self.now.replace(second=0)-timedelta(minutes=4)).isoformat()]
  m=features(rows,BASELINE['parameters']);self.assertIsNone(m['return_3_pct']);self.assertIsNone(m['return_window_pct']);self.assertIsNotNone(m['rsi'])
  self.assertIsNone(m['acceleration_pct_s2']);self.assertIsNone(m['volume_acceleration'])
  r,_=calculate(s,m,BASELINE,self.req['risk'],{},self.now)
  self.assertNotEqual(r['signal'],'BUY')
 def test_sparse_history_reaches_real_exit_evaluation_without_entry_warmup(self):
  s=self.sample(held=True)
  result=engine.ingest(app.connect,1,self.req['watch_id'],True,s,self.now,include_session=False)['calculation']
  self.assertEqual(result['signal'],'WAIT');self.assertNotIn('WARMUP',result['reason_codes'])
  self.assertEqual(result['supporting_metrics']['sample_count'],40)
  # Unknown broker context and stale prices still prevent an exit signal.
  for change in ('context','age'):
   invalid=copy.deepcopy(s);m=result['supporting_metrics'].copy();m['distance_high_pct']='-10'
   if change=='context':invalid['context']['status']='unknown'
   else:invalid['event_time']=(self.now-timedelta(seconds=121)).isoformat()
   self.assertEqual(calculate(invalid,m,BASELINE,self.req['risk'],{},self.now)[0]['signal'],'NO_DATA')
  with app.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM broker_proposals').fetchone()[0],0)
 def test_aging_trade_rechecks_early_but_honours_provider_floor_and_closed_market(self):
  s=self.sample();s['event_time']=(self.now-timedelta(seconds=80)).isoformat()
  live={'ESCAPE_HW_EODHD_WS_TRADES_ENABLED':'1','ESCAPE_HW_EODHD_FUSE_ENABLED':'1'}
  with patch.dict(os.environ,live,clear=True),app.connect() as c:
   self.assertEqual(engine.observation_poll_interval(c,self.req,'NORMAL',self.now,s),15)
   self.assertEqual(engine.observation_poll_interval(c,self.req,'NORMAL',self.now,dict(s,event_time=self.now.isoformat())),60)
   self.assertEqual(engine.observation_poll_interval(c,self.req,'IDLE',self.now,dict(s,market_status='CLOSED')),300)
  with patch.dict(os.environ,dict(live,ESCAPE_HW_EODHD_FAST_POLL_ENABLED='1',ESCAPE_HW_EODHD_MIN_POLL_S='60'),clear=True),app.connect() as c:
   self.assertEqual(engine.observation_poll_interval(c,self.req,'NORMAL',self.now,s),60)
 def test_newer_broker_read_is_not_discarded_when_same_trade_is_reused(self):
  s=self.sample(held=True);s['context']['as_of']=(self.now-timedelta(seconds=290)).isoformat()
  first=engine.ingest(app.connect,1,self.req['watch_id'],True,s,self.now,include_session=False)
  newer=copy.deepcopy(s);newer['context']['as_of']=self.now.isoformat()
  out=engine.ingest(app.connect,1,self.req['watch_id'],True,newer,self.now+timedelta(seconds=1),include_session=False)
  self.assertFalse(out['duplicate']);self.assertFalse(out['calculation']['new_market_observation'])
  self.assertEqual(out['calculation']['position_context']['as_of'],self.now.isoformat())
  again=engine.ingest(app.connect,1,self.req['watch_id'],True,newer,self.now+timedelta(seconds=2),include_session=False)
  self.assertTrue(again['duplicate'])
  with app.connect() as c:
   row=engine.row_for(c,1,self.req['watch_id'],True);view=engine.view(c,row,self.now+timedelta(seconds=11))
   self.assertNotIn('POSITION_CONTEXT_UNKNOWN',view['display_reason_codes'])
   self.assertTrue(view['data_status']['holding_verified'])
   self.assertEqual(c.execute('SELECT count(*) FROM hw_samples WHERE watch_row_id=?',(row['id'],)).fetchone()[0],1)
 def test_duplicate_trade_keeps_critical_exit_polling_profile(self):
  with app.connect() as c:c.execute('UPDATE hw_sessions SET state=? WHERE watch_id=?',(json.dumps({'adaptive_profile':'CRITICAL'}),self.req['watch_id']))
  job=engine.claim(app.connect,self.now,self.req['watch_id'])
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_WS_TRADES_ENABLED':'1','ESCAPE_HW_EODHD_FUSE_ENABLED':'1'},clear=True):
   engine.release(app.connect,job,self.now,sample=self.sample(held=True))
  with app.connect() as c:
   row=engine.row_for(c,1,self.req['watch_id'],True)
   self.assertEqual(row['next_due'],self.now.timestamp()+5)
   self.assertEqual(json.loads(row['state'])['scheduled_interval_s'],5)
 def test_idle_worker_claims_more_jobs_while_other_provider_is_blocked(self):
  runner=service.Runner(app.connect);slow_started=threading.Event();fast_advanced=threading.Event();release=threading.Event();calls={}
  def once(worker):
   calls[worker]=calls.get(worker,0)+1
   if worker is runner and calls[worker]==1:
    slow_started.set();release.wait(3);return True
   if worker is not runner and calls[worker]<=2:
    if calls[worker]==2:fast_advanced.set()
    return True
   return False
  result=[]
  with patch.dict(os.environ,{'ESCAPE_HW_PARALLEL_SCANS':'2','ESCAPE_HW_CONCURRENCY':'2'}),patch.object(service.Runner,'once',once):
   thread=threading.Thread(target=lambda:result.append(runner.drain()));thread.start()
   try:
    self.assertTrue(slow_started.wait(1));self.assertTrue(fast_advanced.wait(1),'free worker stalled behind slow provider')
   finally:release.set();thread.join(3)
  self.assertFalse(thread.is_alive());self.assertEqual(result,[3])
 def test_used_realtime_history_skips_redundant_rest_warmup(self):
  runner=service.Runner(app.connect);s=self.sample(held=True)
  with app.connect() as c:job=dict(engine.row_for(c,1,self.req['watch_id'],True))
  job.update(is_test=0,lease_owner='synthetic-lease',request_data=self.req)
  adapter=Mock();adapter.poll.return_value=s;adapter.last_telemetry=None;adapter.last_feed_diagnostics=None;adapter.capture_metrics=[];adapter.last_partial_observations=[]
  runner.adapters[(1,'eodhd')]=adapter;runner.health=Mock();runner.log=Mock()
  result={'calculation':{'signal':'WAIT','analysis_uses_bars':True,'supporting_metrics':{'sample_count':40}}}
  with patch.object(engine,'claim',return_value=job),patch.object(engine,'ingest',return_value=result),patch('hotwatch_warmup.refresh') as refresh:
   self.assertTrue(runner.once(self.now));refresh.assert_not_called()
   result['calculation']['supporting_metrics']['sample_count']=2
   self.assertTrue(runner.once(self.now));refresh.assert_not_called()
   result['calculation']['analysis_uses_bars']=False
   self.assertTrue(runner.once(self.now));self.assertEqual(refresh.call_count,1)
 def test_quiet_or_older_ws_batch_keeps_fresh_observation_without_renewing_time(self):
  adapter=adapters.EODHDAdapter(app.connect,1);req=dict(self.req,is_test=False,profile='ACTIVE');job={'id':999,'request_data':req}
  message={'symbol':'MERC','event_time':self.now.isoformat(),'received_at':self.now.isoformat(),'price':'100'}
  client=Mock();client.capture.return_value={'status':'OK','messages':[message]}
  with patch.dict(os.environ,{'ESCAPE_EODHD_API_KEY':'test-only'}),patch.object(adapters,'utc',return_value=self.now),patch.object(adapters.time,'monotonic',return_value=100):
   adapter.capture(client,'us_trades','MERC',job)
  for seconds in (21,42,123):
   older=dict(message,event_time=(self.now-timedelta(seconds=5)).isoformat(),price='99')
   client.capture.return_value={'status':'OK','messages':[older]} if seconds==42 else {'status':'NO_MESSAGES','messages':[]}
   with patch.dict(os.environ,{'ESCAPE_EODHD_API_KEY':'test-only'}),patch.object(adapters,'utc',return_value=self.now+timedelta(seconds=seconds)),patch.object(adapters.time,'monotonic',return_value=100+seconds):
    r=adapter.capture(client,'us_trades','MERC',job)
   self.assertEqual(r['messages'],[message] if seconds<=120 else [])
  # Freshness is always the provider event time, never the new capture time.
  self.assertEqual(client.capture.call_count,4)

if __name__=='__main__':unittest.main()
