"""Regression target for issue 13; no live data access or side effects."""
import copy
import unittest
import json
from datetime import datetime, timedelta, timezone

from hotwatch_strategy import BASELINE, calculate
from test_hotwatch_engine import good_metrics, request, tick


class EntryBasis(unittest.TestCase):
 def test_rskd_logged_analysis_high_is_not_position_trailing_evidence(self):
  # Production readback: four SELL calculations all used a $10.69 analysis
  # high; no fill-history completeness was attested. The observations do not
  # establish when that high occurred or prove uninterrupted ownership.
  cases=(('18:20:08.718558','18:19:22.894000','18:18:05.005620','9.945','-6.969130028063610851262862490'),
         ('18:23:53.359959','18:23:25.060000','18:23:07.270566','9.9','-7.390084190832553788587464920'),
         ('18:35:31.766297','18:35:13.584000','18:34:06.940099','9.83','-8.044901777362020579981290930'),
         ('18:41:41.312438','18:41:33.899000','18:40:01.095649','9.86','-7.764265668849391955098222640'))
  risk=copy.deepcopy(request()['risk']);risk.update(stop_price=None,_position_scope='rskd-root');state={}
  def dt(value):return datetime.fromisoformat('2026-11-11T'+value+'+00:00')
  for calculated,event,observed,price,distance in cases:
   now=dt(calculated);sample=tick(dt(event),price=price,held=True)
   sample['context'].update(status='verified',position='held',quantity='3.739393939',cost_price='9.9',as_of=dt(observed).isoformat(),orders_complete=False)
   metrics=good_metrics();metrics.update(price=price,distance_high_pct=distance)
   result,state=calculate(sample,metrics,BASELINE,risk,state,now)
   self.assertNotIn('TRAILING_EXIT',result['reason_codes'])
   self.assertEqual(result['position_trailing']['status'],'WAITING_FOR_VERIFIED_POSITION_HISTORY')

 def test_historical_market_high_is_not_a_verified_position_high(self):
  # The instrument reached 10.50 before the position was bought at 9.90.
  # There is no verified entry time or position high in the broker context.
  at=datetime(2026,11,11,15,0,tzinfo=timezone.utc)
  metrics=good_metrics();metrics.update(price='9.90',distance_high_pct=str((9.90/10.50-1)*100))
  risk=copy.deepcopy(request()['risk']);risk['stop_price']=None
  state={}
  for seconds in (0,10,20):
   now=at+timedelta(seconds=seconds)
   sample=tick(now,price='9.90',held=True);sample['context']['cost_price']='9.90'
   result,state=calculate(sample,metrics,BASELINE,risk,state,now)
  self.assertNotIn('TRAILING_EXIT',result['reason_codes'])
  self.assertNotEqual(result['signal'],'SELL')
  self.assertEqual(result['position_trailing']['status'],'WAITING_FOR_VERIFIED_POSITION_HISTORY')

 def test_independent_verified_stop_still_sells(self):
  at=datetime(2026,11,11,15,0,tzinfo=timezone.utc)
  risk=copy.deepcopy(request()['risk']);risk['stop_price']='9.95'
  result,_=calculate(tick(at,price='9.90',held=True),good_metrics(),BASELINE,risk,{},at)
  self.assertEqual(result['signal'],'SELL')
  self.assertIn('STOP_BREACHED',result['reason_codes'])

 def test_verified_post_observation_peak_and_restart(self):
  at=datetime(2026,11,11,15,0,tzinfo=timezone.utc)
  risk=copy.deepcopy(request()['risk']);risk.update(stop_price=None,_position_scope='depot-one-cycle-one')
  state={};metrics=good_metrics();metrics['distance_high_pct']='-25'
  for seconds,price in ((0,'100'),(10,'105'),(20,'102'),(30,'102'),(40,'102')):
   now=at+timedelta(seconds=seconds);sample=tick(now,seconds,price=price,held=True)
   sample['context'].update(orders_complete=True,position_history_complete=True,position_history_from=(at-timedelta(days=1)).isoformat(),position_history_through=sample['context']['as_of'])
   result,state=calculate(sample,metrics,BASELINE,risk,state,now)
   state=json.loads(json.dumps(state)) # persisted state across restart
  self.assertEqual(result['signal'],'SELL')
  self.assertIn('TRAILING_EXIT',result['reason_codes'])
  self.assertEqual(result['signal_basis'],'verified_position_high')
  self.assertEqual(result['position_trailing']['high'],'105')
  self.assertEqual(result['position_trailing']['high_time'],(at+timedelta(seconds=10)).isoformat())
  duplicate,state=calculate(sample,metrics,BASELINE,risk,state,now,new_market_event=False)
  self.assertEqual(duplicate['signal'],'SELL')
  self.assertEqual(duplicate['position_trailing']['status'],'VERIFIED')

 def test_position_changes_and_unknown_evidence_reset_high(self):
  at=datetime(2026,11,11,15,0,tzinfo=timezone.utc)
  risk=copy.deepcopy(request()['risk']);risk.update(stop_price=None,_position_scope='depot-one-cycle-one')
  metrics=good_metrics();state={}
  def run(second,price='100',change=None,scope=None):
   nonlocal state
   now=at+timedelta(seconds=second);sample=tick(now,second,price=price,held=True)
   sample['context'].update(orders_complete=True,position_history_complete=True,position_history_from=(at-timedelta(days=1)).isoformat(),position_history_through=sample['context']['as_of'])
   if change:sample['context'].update(change)
   r=dict(risk)
   if scope is not None:r['_position_scope']=scope
   result,state=calculate(sample,metrics,BASELINE,r,state,now)
   return result
  run(0);run(10,'105')
  # Additional buy / partial sale invalidates the old high.
  for seconds,change in ((20,{'quantity':'11'}),(30,{'quantity':'9'})):
   result=run(seconds,'100',change);self.assertNotIn('TRAILING_EXIT',result['reason_codes']);self.assertIsNone(result['position_trailing']['high'])
  run(40);run(50,'105')
  # An intervening complete sale and rebuy can restore the same quantity;
  # changed fill evidence still invalidates the previous high.
  orders=[{'order_id':'sell','status':'FILLED','requested_quantity':'10','filled_quantity':'10','side':'SELL'},{'order_id':'buy','status':'FILLED','requested_quantity':'10','filled_quantity':'10','side':'BUY'}]
  result=run(60,'100',{'orders':orders});self.assertNotIn('TRAILING_EXIT',result['reason_codes']);self.assertIsNone(result['position_trailing']['high'])
  result=run(70,'100',{'position_history_complete':False});self.assertEqual(result['position_trailing']['status'],'WAITING_FOR_VERIFIED_POSITION_HISTORY');self.assertNotIn('position_trailing',state)
  run(80);run(90,'105');result=run(100,'100',scope='depot-two-cycle-two');self.assertNotIn('TRAILING_EXIT',result['reason_codes']);self.assertIsNone(result['position_trailing']['high'])

 def test_unfilled_order_does_not_create_a_new_position(self):
  at=datetime(2026,11,11,15,0,tzinfo=timezone.utc);risk=copy.deepcopy(request()['risk']);risk.update(stop_price=None,_position_scope='same-depot')
  state={};metrics=good_metrics()
  for seconds,price in ((0,'100'),(10,'105'),(20,'104')):
   now=at+timedelta(seconds=seconds);sample=tick(now,seconds,price=price,held=True)
   sample['context'].update(orders_complete=True,position_history_complete=True,position_history_from=(at-timedelta(days=1)).isoformat(),position_history_through=sample['context']['as_of'])
   if seconds==20:sample['context']['orders']=[{'order_id':'not-filled','status':'OPEN','requested_quantity':'1','filled_quantity':'0','side':'BUY'}]
   result,state=calculate(sample,metrics,BASELINE,risk,state,now)
  self.assertEqual(result['position_trailing']['high'],'105')

 def test_long_observation_gap_cannot_reuse_the_old_high(self):
  at=datetime(2026,11,11,15,0,tzinfo=timezone.utc);risk=copy.deepcopy(request()['risk']);risk.update(stop_price=None,_position_scope='same-depot')
  state={};metrics=good_metrics()
  for seconds,price in ((0,'100'),(10,'105'),(311,'100')):
   now=at+timedelta(seconds=seconds);sample=tick(now,seconds,price=price,held=True)
   sample['context'].update(orders_complete=True,position_history_complete=True,position_history_from=(at-timedelta(days=1)).isoformat(),position_history_through=sample['context']['as_of'])
   result,state=calculate(sample,metrics,BASELINE,risk,state,now)
  self.assertIsNone(result['position_trailing']['high'])
  self.assertNotIn('TRAILING_EXIT',result['reason_codes'])

 def test_history_must_cover_whole_observation_interval(self):
  at=datetime(2026,11,11,15,0,tzinfo=timezone.utc);risk=copy.deepcopy(request()['risk']);risk.update(stop_price=None,_position_scope='same-depot')
  metrics=good_metrics();state={}
  for seconds,price in ((0,'100'),(10,'105')):
   now=at+timedelta(seconds=seconds);sample=tick(now,seconds,price=price,held=True)
   sample['context'].update(orders_complete=True,position_history_complete=True,position_history_from=at.isoformat(),position_history_through=now.isoformat())
   result,state=calculate(sample,metrics,BASELINE,risk,state,now)
  self.assertEqual(result['position_trailing']['high'],'105')
  now=at+timedelta(seconds=20);sample=tick(now,20,price='100',held=True)
  sample['context'].update(orders_complete=True,position_history_complete=True,position_history_from=(at+timedelta(seconds=15)).isoformat(),position_history_through=now.isoformat())
  result,state=calculate(sample,metrics,BASELINE,risk,state,now)
  self.assertIsNone(result['position_trailing']['high']);self.assertNotIn('TRAILING_EXIT',result['reason_codes'])
  sample['context']['position_history_through']=(now-timedelta(seconds=1)).isoformat()
  result,state=calculate(sample,metrics,BASELINE,risk,state,now)
  self.assertNotIn('position_trailing',state);self.assertNotIn('TRAILING_EXIT',result['reason_codes'])
  sample['context']['position_history_through']=(now+timedelta(seconds=1)).isoformat()
  result,state=calculate(sample,metrics,BASELINE,risk,state,now)
  self.assertNotIn('position_trailing',state);self.assertNotIn('TRAILING_EXIT',result['reason_codes'])

 def test_open_orders_and_ambiguous_depot_do_not_prove_fill_history(self):
  at=datetime(2026,11,11,15,0,tzinfo=timezone.utc);metrics=good_metrics();risk=copy.deepcopy(request()['risk']);risk.update(stop_price=None,_position_scope='depot-one')
  for change,scope in (({'orders_complete':True},'depot-one'),({'orders_complete':True,'position_history_complete':True},'depot-one'),({'orders_complete':True,'position_history_complete':True},None)):
   state={};r=dict(risk);r['_position_scope']=scope
   for seconds,price in ((0,'100'),(10,'105'),(20,'100'),(30,'100'),(40,'100')):
    now=at+timedelta(seconds=seconds);sample=tick(now,seconds,price=price,held=True);sample['context'].update(change)
    result,state=calculate(sample,metrics,BASELINE,r,state,now)
   self.assertNotIn('TRAILING_EXIT',result['reason_codes'])
   self.assertNotIn('position_trailing',state)

 def test_market_observation_before_position_proof_cannot_be_the_high(self):
  at=datetime(2026,11,11,15,0,tzinfo=timezone.utc);metrics=good_metrics();risk=copy.deepcopy(request()['risk']);risk.update(stop_price=None,_position_scope='depot-one');state={}
  for seconds,price in ((0,'150'),(10,'100'),(20,'99'),(30,'99'),(40,'99')):
   now=at+timedelta(seconds=seconds);sample=tick(now,seconds,price=price,held=True)
   sample['context'].update(orders_complete=True,position_history_complete=True,position_history_from=(at-timedelta(days=1)).isoformat(),position_history_through=sample['context']['as_of'])
   result,state=calculate(sample,metrics,BASELINE,risk,state,now)
  self.assertEqual(result['position_trailing']['high'],'100')
  self.assertNotIn('TRAILING_EXIT',result['reason_codes'])

 def test_complete_sale_and_new_position_discard_previous_high(self):
  at=datetime(2026,11,11,15,0,tzinfo=timezone.utc);metrics=good_metrics();risk=copy.deepcopy(request()['risk']);risk.update(stop_price=None,_position_scope='depot-one');state={}
  for seconds,price,held in ((0,'100',True),(10,'105',True),(20,'100',False),(30,'100',True)):
   now=at+timedelta(seconds=seconds);sample=tick(now,seconds,price=price,held=held)
   sample['context'].update(orders_complete=True,position_history_complete=True,position_history_from=(at-timedelta(days=1)).isoformat(),position_history_through=sample['context']['as_of'])
   result,state=calculate(sample,metrics,BASELINE,risk,state,now)
   if not held:self.assertNotIn('position_trailing',state)
  self.assertIsNone(result['position_trailing']['high'])
  self.assertNotIn('TRAILING_EXIT',result['reason_codes'])

 def test_changed_position_does_not_reuse_old_sell_confirmations(self):
  at=datetime(2026,11,11,15,0,tzinfo=timezone.utc);metrics=good_metrics();risk=copy.deepcopy(request()['risk']);risk.update(stop_price=None,_position_scope='depot-one');state={}
  for seconds,price in ((0,'100'),(10,'105'),(20,'102'),(30,'102')):
   now=at+timedelta(seconds=seconds);sample=tick(now,seconds,price=price,held=True);sample['context'].update(orders_complete=True,position_history_complete=True,position_history_from=(at-timedelta(days=1)).isoformat(),position_history_through=sample['context']['as_of'])
   result,state=calculate(sample,metrics,BASELINE,risk,state,now)
  self.assertEqual(state['confirmations'],2)
  now=at+timedelta(seconds=40);sample=tick(now,40,price='102',held=True);sample['context'].update(orders_complete=True,position_history_complete=True,position_history_from=(at-timedelta(days=1)).isoformat(),position_history_through=sample['context']['as_of'],quantity='11')
  metrics.update(return_3_pct='-3',breakdown=True)
  result,state=calculate(sample,metrics,BASELINE,risk,state,now)
  self.assertEqual(result['signal'],'WAIT')
  self.assertIn('CONFIRMATION_PENDING',result['reason_codes'])
  self.assertEqual(state['confirmations'],1)

 def test_independent_exit_confirmations_reset_on_observed_quantity_change_without_fill_history(self):
  at=datetime(2026,11,11,15,0,tzinfo=timezone.utc);metrics=good_metrics();metrics.update(return_3_pct='-3',breakdown=True)
  risk=copy.deepcopy(request()['risk']);risk.update(stop_price=None,_position_scope='depot-one');state={}
  for seconds in (0,10):
   now=at+timedelta(seconds=seconds);sample=tick(now,seconds,price='100',held=True)
   result,state=calculate(sample,metrics,BASELINE,risk,state,now)
  self.assertEqual(state['confirmations'],2)
  now=at+timedelta(seconds=20);sample=tick(now,20,price='100',held=True);sample['context']['quantity']='11'
  result,state=calculate(sample,metrics,BASELINE,risk,state,now)
  self.assertEqual(result['signal'],'WAIT')
  self.assertEqual(state['confirmations'],1)


if __name__=='__main__':unittest.main()
