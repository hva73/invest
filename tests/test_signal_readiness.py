"""Actual sparse observations, independent evidence and shared broker context."""
import copy,json,os,threading,time,unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import patch,Mock
import app,hotwatch_engine as engine,hotwatch_adapters as adapters,hotwatch_service as service
import test_sparse_feed_recovery as setup
import test_hotwatch_engine as fixture
from hotwatch_features import features
from hotwatch_strategy import BASELINE,calculate
from hotwatch_contract import EngineError

class SignalReadiness(unittest.TestCase):
 setUp=setup.SparseFeedRecovery.setUp
 tearDown=setup.SparseFeedRecovery.tearDown
 sample=setup.SparseFeedRecovery.sample
 def test_gap_keeps_period_history_but_not_fictitious_minute_returns(self):
  rows=[fixture.tick(self.now-timedelta(minutes=40-i),i,price=str(100+i)) for i in range(40)]
  rows=[r for i,r in enumerate(rows) if i not in (8,36)]
  m=features(rows,BASELINE['parameters'])
  self.assertEqual(m['sample_count'],38)
  for k in ('rsi','ema_long','macd_histogram','atr'):self.assertIsNotNone(m[k])
  self.assertIsNone(m['return_3_pct']);self.assertIsNotNone(m['return_1_pct'])
  rows[-1]['event_time']=self.now.isoformat()
  m=features(rows,BASELINE['parameters'])
  self.assertEqual(m['sample_count'],38);self.assertIsNone(m['return_1_pct']);self.assertIsNone(m['acceleration_pct_s2'])
 def test_fast_observations_are_not_relabelled_as_minutes(self):
  rows=[fixture.tick(self.now-timedelta(seconds=150-i*15),i,price=str(100+i)) for i in range(11)]
  for r in rows:r.update(source='eodhd',price_time_kind='trade',feed_type='EODHD trades',interval_s=15)
  m=features(rows,BASELINE['parameters'])
  self.assertEqual(m['sample_count'],11);self.assertIsNone(m['return_3_pct'])
  self.assertEqual(m['return_1_pct'],features([rows[6],rows[10]],BASELINE['parameters'])['return_1_pct'])
 def test_cumulative_volume_gap_is_not_one_interval(self):
  rows=[fixture.tick(self.now-timedelta(minutes=12-i),i) for i in range(13)]
  for i,r in enumerate(rows):r.update(volume=str(1000+i*100),volume_type='cumulative')
  rows[-1]['event_time']=(self.now+timedelta(minutes=2)).isoformat()
  m=features(rows,BASELINE['parameters']);self.assertEqual(m['sample_count'],13)
  self.assertIsNone(m['interval_volume']);self.assertIsNone(m['relative_volume'])
 def test_available_indicators_replace_global_count_but_not_confirmations(self):
  metrics=fixture.good_metrics();metrics['sample_count']=2
  s=fixture.tick(self.now);state={}
  for n in range(3):
   result,state=calculate(s,metrics,BASELINE,self.f.req['risk'],state,self.now+timedelta(seconds=10*n))
   self.assertEqual(result['signal'],'BUY' if n==2 else 'WAIT')
  missing=dict(metrics,macd_histogram=None)
  result,_=calculate(s,missing,BASELINE,self.req['risk'],{},self.now)
  self.assertEqual(result['signal'],'NO_DATA')
  # A known false condition is enough for WAIT, even without unrelated MACD.
  result,_=calculate(s,dict(missing,breakout=False),BASELINE,self.req['risk'],{},self.now)
  self.assertEqual(result['signal'],'WAIT')
 def test_quote_expiry_does_not_block_verified_price_exit_or_enable_buy(self):
  s=self.sample(held=True);s['bid_at']=s['ask_at']=(self.now-timedelta(seconds=121)).isoformat()
  with app.connect() as c:
   req=json.loads(engine.row_for(c,1,self.req['watch_id'],True)['request']);req['risk']['stop_price']='101'
   c.execute('UPDATE hw_sessions SET request=? WHERE watch_id=?',(json.dumps(req),self.req['watch_id']))
  out=engine.ingest(app.connect,1,self.req['watch_id'],True,s,self.now)
  self.assertEqual(out['calculation']['signal'],'SELL');self.assertEqual(out['session']['signal'],'SELL')
  self.assertEqual(out['session']['data_status']['quote_status'],'STALE')
  s['context'].update(position='none',quantity='0')
  result,_=calculate(s,fixture.good_metrics(),BASELINE,self.req['risk'],{},self.now)
  self.assertNotEqual(result['signal'],'BUY');self.assertIn('SPREAD_UNKNOWN',result['reason_codes'])
 def test_same_trade_accepts_new_quotes_without_new_confirmation_or_source_time(self):
  s=self.sample(held=True);first=engine.ingest(app.connect,1,self.req['watch_id'],True,s,self.now)
  later=self.now+timedelta(seconds=10);new=copy.deepcopy(s)
  new.update(bid='99.94',ask='100.04',bid_at=later.isoformat(),ask_at=later.isoformat(),status_at=later.isoformat())
  new['bar_evidence']['schedule_received_at']=later.isoformat()
  result=engine.ingest(app.connect,1,self.req['watch_id'],True,new,later)
  self.assertFalse(result['duplicate']);self.assertFalse(result['calculation']['new_market_observation'])
  self.assertEqual(result['session']['last_data_at'],s['event_time'])
  self.assertEqual(result['session']['data_status']['bid'],'99.94')
  self.assertTrue(engine.ingest(app.connect,1,self.req['watch_id'],True,new,later)['duplicate'])
  old=engine.ingest(app.connect,1,self.req['watch_id'],True,s,later+timedelta(seconds=1))
  self.assertTrue(old['duplicate']);self.assertEqual(old['session']['data_status']['bid'],'99.94')
  with app.connect() as c:
   self.assertEqual(c.execute('SELECT count(*) FROM hw_samples WHERE watch_row_id=(SELECT id FROM hw_sessions WHERE watch_id=?)',(self.req['watch_id'],)).fetchone()[0],1)
   self.assertEqual(c.execute('SELECT count(*) FROM broker_proposals').fetchone()[0],0)
  conflict=copy.deepcopy(new);conflict.update(price='101',close='101',high='101.1')
  with self.assertRaisesRegex(EngineError,'sample_id_conflict') as rejected:engine.ingest(app.connect,1,self.req['watch_id'],True,conflict,later)
  detail=rejected.exception.market_conflict
  self.assertIn('price',detail['fields']);self.assertEqual(detail['previous']['price'],'100');self.assertEqual(detail['incoming']['price'],'101')
  self.assertNotIn('context',detail['fields']);self.assertNotIn('asset_id',detail['previous'])
  self.assertEqual(detail['observations']['previous']['event_time'],s['event_time'])
  self.assertEqual(detail['observations']['incoming']['event_time'],s['event_time'])
  self.assertEqual(detail['observations']['previous']['sample_ref'],detail['observations']['incoming']['sample_ref'])
  self.assertIn('previous_journal_received_at',detail);self.assertEqual(detail['ingest_attempt_at'],later.isoformat())
 def test_conflict_diagnostics_reach_existing_scan_log_without_broker_context(self):
  previous=self.sample(held=True);incoming=copy.deepcopy(previous);incoming['price']='101';incoming['context']['diagnostic']='private-broker-detail'
  error=engine.sample_conflict(previous,incoming,{'price','context','asset_id','feed_type'})
  runner=service.Runner(app.connect);runner.health=Mock();runner.log=Mock()
  with app.connect() as c:job=dict(engine.row_for(c,1,self.req['watch_id'],True))
  job.update(request_data=self.req,lease_owner='synthetic-lease')
  adapter=Mock();adapter.poll.return_value=incoming;adapter.capture_metrics=[];adapter.last_partial_observations=[]
  runner.adapters[(1,'eodhd')]=adapter
  with patch.object(engine,'claim',return_value=job),patch.object(engine,'ingest',side_effect=error),patch.object(engine,'fault') as fault:
   self.assertTrue(runner.once(self.now))
  detail=runner.log.call_args.args[3]['market_conflict']
  self.assertEqual(detail['previous'],{'price':'100'});self.assertEqual(detail['incoming'],{'price':'101'})
  self.assertNotIn('private-broker-detail',json.dumps(detail))
  self.assertEqual(runner.log.call_args.args[2],'sample_id_conflict');self.assertEqual(fault.call_args.args[4],'sample_id_conflict')
 def test_earliest_required_evidence_schedules_refresh_without_extending_freshness(self):
  s=self.sample();env={'ESCAPE_HW_EODHD_WS_TRADES_ENABLED':'1','ESCAPE_HW_EODHD_FUSE_ENABLED':'1'}
  with patch.dict(os.environ,env,clear=True),app.connect() as c:
   for key in ('context','calendar','bar','quote'):
    changed=copy.deepcopy(s)
    if key=='context':changed['context']['as_of']=(self.now-timedelta(seconds=280)).isoformat()
    elif key=='calendar':changed['bar_evidence']['schedule_received_at']=(self.now-timedelta(seconds=100)).isoformat()
    elif key=='quote':changed['bid_at']=changed['ask_at']=(self.now-timedelta(seconds=100)).isoformat()
    else:changed['bar_history']=changed['bar_history'][:-1]
    self.assertEqual(engine.observation_poll_interval(c,self.req,'NORMAL',self.now,changed),15,key)
 def test_expired_source_in_new_cache_is_refetched(self):
  import hashlib
  request=dict(self.req,is_test=False);session={'id':123,'request_data':request,'state':'{}'}
  adapter=adapters.EODHDAdapter(app.connect,1);client=Mock()
  old={'symbol':'MERC','event_time':(self.now-timedelta(seconds=121)).isoformat(),'received_at':self.now.isoformat(),'price':'99'}
  new=dict(old,event_time=self.now.isoformat(),price='100')
  client.capture.return_value={'status':'OK','messages':[new]}
  with patch.dict(os.environ,{'ESCAPE_EODHD_API_KEY':'test-source-cache'}),patch('hotwatch_adapters.utc',return_value=self.now):
   credential=hashlib.sha256(b'test-source-cache').digest();adapters._ws_batch_cache[(1,credential,'us_trades','MERC')]=(time.monotonic(),{'status':'OK','messages':[old]})
   out=adapter.capture(client,'us_trades','MERC',session)
  self.assertEqual(out['messages'][0]['price'],'100');client.capture.assert_called_once()
 def test_shared_broker_serializes_refresh_without_holding_database_lock(self):
  broker=adapters.PlutoAdapter(app.connect,1);active=0;high=0;lock=threading.Lock()
  def work(*args):
   nonlocal active,high
   with lock:active+=1;high=max(high,active)
   with app.connect() as c:c.execute('SELECT 1')
   time.sleep(.015)
   with lock:active-=1
   return {'status':'verified'}
  with patch.object(broker,'_context',side_effect=work),ThreadPoolExecutor(max_workers=2) as pool:
   results=list(pool.map(lambda _:broker.context(self.req,'USD'),range(2)))
  self.assertEqual(high,1);self.assertEqual(len(results),2)
 def test_account_cache_keeps_original_permission_time_and_scope(self):
  broker=adapters.PlutoAdapter(app.connect,1);checked=self.now.timestamp()-240
  client=Mock();client.read_cache={'list_portfolios':(checked,{})}
  portfolio={'id':123,'kind':'portfolio','external_id':'portfolios:a','parent_external_id':None}
  raw={'asset':{'id':self.req['asset_id'],'ticker':'MERC','exchange':'NASDAQ','currency':'USD'},'buyBy':{'shares':True}}
  with patch('hotwatch_adapters.utc',return_value=self.now),patch('trade_service.client',return_value=(client,{})),patch('trade_service.call',return_value=raw) as call,patch('trade_service.fresh_permission'):
   self.assertEqual(broker.tradability(self.req,'USD',[portfolio]),('available',checked))
   self.assertEqual(broker.tradability(self.req,'USD',[portfolio]),('available',checked));self.assertEqual(call.call_count,1)
   broker.tradability(self.req,'USD',[dict(portfolio,external_id='portfolios:b')]);self.assertEqual(call.call_count,2)
 def test_two_workers_share_one_strict_portfolio_refresh(self):
  import portfolios,portfolio_data
  with app.connect() as c:
   portfolios.replace_pluto(c,1,[{'id':'portfolios:root','name':'Synthetic','kind':'portfolio'}])
   pid=portfolios.list_owned(c,1)[0]['id']
   c.execute('UPDATE hw_sessions SET status=\'PAUSED\'')
  for n in range(2):
   req=dict(self.req,watch_id='shared-broker-'+str(n),purpose='shared broker '+str(n),portfolio_ids=[pid],watch_mode='exit')
   engine.create(app.connect,1,req,self.now)
  payload={'source':'Pluto Markets','observed':self.now.isoformat(),'kind':'portfolio','currency':'USD','positions':[],'pending_orders':[],'accounts':[],'value':None,'errors':[],'complete':True,'positions_complete':True,'positions_strict_verified':True}
  barrier=threading.Barrier(2);seen=[]
  def poll(adapter,job):
   barrier.wait(timeout=5);seen.append(adapter.pluto)
   s=self.sample();s['context']=adapter.pluto.context(job['request_data'],'USD');return s
  runner=service.Runner(app.connect)
  with patch('hotwatch_engine.utc',return_value=self.now),patch('hotwatch_adapters.utc',return_value=self.now),patch('portfolio_data.read',return_value=payload) as read,patch.object(adapters.PlutoAdapter,'inactive_orders',return_value=[]),patch.object(adapters.EODHDAdapter,'poll',poll),patch('hotwatch_warmup.refresh'),patch.dict(os.environ,{'ESCAPE_HW_PARALLEL_SCANS':'2','ESCAPE_HW_CONCURRENCY':'2'}):
   self.assertEqual(runner.drain(),2)
  self.assertEqual(read.call_count,1);self.assertIs(seen[0],seen[1])
  self.assertIs(runner.brokers,runner._workers[0].brokers)
  self.assertIsNot(service.Runner(app.connect).brokers,runner.brokers)
 def test_account_read_cache_expires_and_does_not_cross_credentials(self):
  from mcp_client import MCP
  broker=adapters.PlutoAdapter(app.connect,1);client=broker.factory('synthetic-token-a')
  client.catalog=[{'name':'list_portfolios','annotations':{'readOnlyHint':True}}]
  with patch.object(MCP,'request',return_value={'content':[]}) as request,patch('hotwatch_adapters.reserve'),patch('hotwatch_adapters.utc',return_value=self.now):
   one=client.request('tools/call',{'name':'list_portfolios','arguments':{}})
   one['content'].append('caller mutation')
   self.assertEqual(client.request('tools/call',{'name':'list_portfolios','arguments':{}}),{'content':[]})
   self.assertEqual(request.call_count,1)
   with patch('hotwatch_adapters.utc',return_value=self.now+timedelta(seconds=300)):
    client.request('tools/call',{'name':'list_portfolios','arguments':{}});self.assertEqual(request.call_count,2)
   replacement=broker.factory('synthetic-token-b');replacement.catalog=client.catalog
   replacement.request('tools/call',{'name':'list_portfolios','arguments':{}});self.assertEqual(request.call_count,3)
 def test_missing_old_ohlc_does_not_block_atr_from_complete_recent_bars(self):
  rows=[fixture.tick(self.now-timedelta(minutes=30-i),i) for i in range(30)]
  rows[0].update(high=None,low=None,close=None)
  self.assertIsNotNone(features(rows,BASELINE['parameters'])['atr'])
  rows[-1]['high']=None
  self.assertIsNone(features(rows,BASELINE['parameters'])['atr'])

 def test_late_quote_processing_cannot_roll_back_newer_broker_context(self):
  original=self.sample(held=True);engine.ingest(app.connect,1,self.req['watch_id'],True,original,self.now)
  newer=copy.deepcopy(original);newer['context'].update(as_of=(self.now+timedelta(seconds=5)).isoformat(),quantity='12')
  engine.ingest(app.connect,1,self.req['watch_id'],True,newer,self.now+timedelta(seconds=5))
  late=copy.deepcopy(original);late.update(bid='99.94',ask='100.04',bid_at=(self.now+timedelta(seconds=7)).isoformat(),ask_at=(self.now+timedelta(seconds=7)).isoformat())
  result=engine.ingest(app.connect,1,self.req['watch_id'],True,late,self.now+timedelta(seconds=8))
  self.assertEqual(result['calculation']['position_context']['quantity'],'12')
  self.assertEqual(result['session']['latest_context']['as_of'],newer['context']['as_of'])
  self.assertFalse(result['calculation']['new_market_observation'])
