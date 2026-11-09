"""Synthetic regressions for live-route budgeting and independent positions."""
import copy,json,os,unittest
from datetime import timedelta
from unittest.mock import patch
import app,hotwatch_engine as engine,hotwatch_adapters as adapters
import test_hotwatch_engine as fixtures
from hotwatch_contract import GLOBAL_RISK

ENV={'ESCAPE_HW_EODHD_REQUESTS_PER_MINUTE':'30','ESCAPE_HW_EODHD_WS_TRADES_ENABLED':'1','ESCAPE_HW_EODHD_FUSE_ENABLED':'1','ESCAPE_HW_EODHD_BARS_ENABLED':'1','ESCAPE_HW_EODHD_WS_EU_EXCHANGES':''}

class LiveCapacity(unittest.TestCase):
 def setUp(self):
  self.f=fixtures.HotWatch();self.f.setUp();self.now=self.f.now
 def tearDown(self):self.f.tearDown()
 def add(self,symbol,number,user=1,due=0,btc=False):
  from instrument_resolver import BTC_PLUTO_ASSET_ID
  with app.connect() as c:
   row=dict(engine.row_for(c,1,self.f.req['watch_id'],True));row.pop('id')
   req=json.loads(row['request']);req.update(watch_id='capacity-'+str(number),candidate_id='capacity-candidate-'+str(number),provider='eodhd',provider_symbol=symbol,is_test=False,profile='ACTIVE')
   if btc:req.update(purpose='automatic holding watch',asset_id=BTC_PLUTO_ASSET_ID,ticker='BTC',watch_mode='exit')
   row.update(watch_id=req['watch_id'],candidate_id=req['candidate_id'],user_id=user,is_test=0,request=json.dumps(req),next_due=due)
   cols=list(row);c.execute('INSERT INTO hw_sessions('+','.join(cols)+') VALUES('+','.join('?' for _ in cols)+')',[row[k] for k in cols])
   job=dict(c.execute('SELECT * FROM hw_sessions WHERE watch_id=?',(req['watch_id'],)).fetchone());job['request_data']=req
  return job
 def test_thirty_sessions_use_configured_routes_without_extending_freshness(self):
  for n in range(23):stock=self.add('US'+str(n)+'.US',n)
  for n in range(23,28):self.add('EU'+str(n)+'.XETRA',n)
  for n in range(28,30):btc=self.add('BTC-USD.CC',n,btc=True)
  with patch.dict(os.environ,ENV,clear=True),app.connect() as c:
   self.assertEqual(engine.effective_poll_interval(c,stock['request_data']),116)
   self.assertEqual(engine.effective_poll_interval(c,btc['request_data']),60)
   self.assertEqual(engine.provider_request_limit('eodhd'),30)
   self.assertEqual(GLOBAL_RISK['max_quote_age_s'],120)
  # 23 individual bar histories, 3 streams + 1 schedule for each of 5 US
  # batches, 5 REST-only markets, plus 2 BTC requests/minute: under 27/min.
  self.assertLessEqual(48*60/116+2,27)
 def test_exchange_schedules_do_not_share_across_different_markets(self):
  for n,symbol in enumerate(['A.CO','B.CO','C.CO','D.XETRA','E.XETRA']):job=self.add(symbol,n)
  settings={**ENV,'ESCAPE_HW_EODHD_WS_EU_EXCHANGES':'CO,XETRA','ESCAPE_HW_EODHD_REQUESTS_PER_MINUTE':'10','ESCAPE_HW_EODHD_FAST_POLL_ENABLED':'1','ESCAPE_HW_EODHD_MIN_POLL_S':'5'}
  with patch.dict(os.environ,settings,clear=True),app.connect() as c:
   self.assertEqual(engine.effective_poll_interval(c,job['request_data']),86) # 3 streams + 5 histories + 2 schedules
  with patch.dict(os.environ,{**settings,'ESCAPE_HW_EODHD_MIN_POLL_S':'300'},clear=True),app.connect() as c:
   self.assertEqual(engine.effective_poll_interval(c,job['request_data']),300)
 def test_upcoming_five_watches_share_feed_without_moving_due_time(self):
  jobs=[self.add('SHARE'+str(n)+'.US',n,due=self.now.timestamp()+n*3) for n in range(5)]
  adapter=adapters.EODHDAdapter(app.connect,1);calls=[]
  class Feeds:
   def capture(_,feed,symbols,**kw):
    calls.append((feed,symbols));symbols=[symbols] if isinstance(symbols,str) else symbols
    return {'status':'OK','messages':[{'symbol':s,'event_time':self.now.isoformat(),'price':'100'} for s in symbols]}
  with patch.dict(os.environ,ENV,clear=True),patch('hotwatch_adapters.utc',return_value=self.now),patch('hotwatch_engine.verified_automatic_feed',return_value=True):
   for job in jobs:
    result=adapter.capture(Feeds(),'us_trades',job['request_data']['provider_symbol'][:-3],job)
    self.assertEqual(len(result['messages']),1);self.assertEqual(result['messages'][0]['event_time'],self.now.isoformat())
  self.assertEqual(len(calls),1);self.assertEqual(len(calls[0][1]),5)
  with app.connect() as c:
   for job in jobs:self.assertEqual(c.execute('SELECT next_due FROM hw_sessions WHERE id=?',(job['id'],)).fetchone()[0],job['next_due'])
 def test_shared_planning_does_not_bypass_actual_request_limit(self):
  with patch.dict(os.environ,ENV,clear=True):
   for n in range(30):adapters.reserve(app.connect,1,'eodhd',self.now)
   with self.assertRaisesRegex(adapters.DataUnavailable,'PROVIDER_RATE_BUDGET'):adapters.reserve(app.connect,2,'eodhd',self.now)
 def test_partial_snapshot_can_prove_absence_but_cannot_authorize_buy(self):
  import portfolios,portfolio_data
  from hotwatch_strategy import calculate,BASELINE
  with app.connect() as c:
   portfolios.replace_pluto(c,1,[{'id':'portfolios:synthetic','name':'Synthetic','kind':'portfolio'}]);pid=portfolios.list_owned(c,1)[0]['id']
   payload={'observed':self.now.isoformat(),'positions':[],'positions_complete':True,'positions_strict_verified':True,'complete':False,'value':None,'pending_orders':[],'errors':['accounts unavailable']}
   portfolio_data.save(c,1,pid,payload)
  adapter=adapters.PlutoAdapter(app.connect,1);req=dict(self.f.req,portfolio_ids=[pid],watch_mode='entry')
  with patch('hotwatch_adapters.utc',return_value=self.now),patch.object(adapter,'tradability',return_value=('unknown',None)),patch.object(adapter,'inactive_orders',return_value=[]),patch('portfolio_data.read',side_effect=AssertionError('reuse independently verified positions')):
   context=adapter.context(req,'USD')
  self.assertEqual((context['status'],context['position']),('verified','none'))
  self.assertIsNone(context['portfolio_equity_dkk']);self.assertIsNone(context['fx_to_dkk']);self.assertIsNone(context['fees_dkk'])
  sample=fixtures.tick(self.now);sample['context']=context
  result,_=calculate(sample,fixtures.good_metrics(),BASELINE,req['risk'],{},self.now)
  self.assertNotEqual(result['signal'],'BUY');self.assertIn('RISK_INPUTS_UNKNOWN',result['reason_codes'])
  payload['positions_complete']=False
  with app.connect() as c:c.execute('UPDATE portfolio_snapshots SET payload=?',(json.dumps(payload),))
  with patch('hotwatch_adapters.utc',return_value=self.now):self.assertEqual(adapter.context(req,'USD')['status'],'unknown')
 def test_status_readback_separates_current_signal_from_last_calculation(self):
  self.f.put(fixtures.tick(self.now))
  with patch('hotwatch_engine.utc',return_value=self.now):
   data=engine.sync(app.connect,1,True,summary_only=True,session_limit=1)['open_sessions'][0]
  self.assertEqual(data['signal'],'NO_DATA');self.assertEqual(data['display_status'],'WARMUP')
  self.assertIn('context_diagnostic',data)
  at=self.now+timedelta(seconds=1)
  self.f.put(fixtures.tick(at,index=1,price='90',held=True),at)
  with patch('hotwatch_engine.utc',return_value=at):
   fresh=engine.sync(app.connect,1,True,summary_only=True,session_limit=1)['open_sessions'][0]
  self.assertEqual(fresh['signal'],'SELL');self.assertEqual(fresh['display_status'],'SÆLGSSIGNAL')
  with patch('hotwatch_engine.utc',return_value=at+timedelta(seconds=121)):
   stale=engine.sync(app.connect,1,True,summary_only=True,session_limit=1)['open_sessions'][0]
  self.assertEqual(stale['last_computed_signal'],'SELL');self.assertEqual(stale['signal'],'NO_DATA')
  self.assertEqual(stale['display_status'],'DATA FOR GAMLE');self.assertIn('DATA_STALE',stale['display_reason_codes'])
