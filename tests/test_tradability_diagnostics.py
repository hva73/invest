"""Synthetic, read-only broker failures; no live credentials or orders."""
import tempfile,unittest
from unittest.mock import patch
import app,portfolios,portfolio_data,hotwatch_engine as engine,trade_service
from hotwatch_adapters import DataUnavailable,PlutoAdapter

class TradabilityDiagnostics(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.previous=app.DB;app.DB=self.tmp.name+'/data.db';app.init();app.create_user('test-password-long')
  with app.connect() as c:
   portfolios.replace_pluto(c,1,[{'id':'portfolios:test','name':'Synthetic','kind':'portfolio'}])
   pid=c.execute("SELECT id FROM portfolios WHERE external_id='portfolios:test'").fetchone()['id']
   portfolio_data.save(c,1,pid,{'observed':engine.utc().isoformat(),'positions':[],'positions_complete':True,'positions_strict_verified':True,'positions_scope':'DIRECT','complete':True,'value':{'value':{'amount':'1000','currency':'DKK'}},'pending_orders':[]})
  self.request={'portfolio_ids':[pid],'asset_id':'synthetic-id','ticker':'SYN','exchange':'NASDAQ','watch_mode':'entry','is_test':True,'risk':{}}
  self.asset={'asset':{'id':'synthetic-id','ticker':'SYN','exchange':'NASDAQ','currency':'USD'},'buyBy':{'shares':True}}
  self.adapter=PlutoAdapter(app.connect,1)
 def tearDown(self):app.DB=self.previous;self.tmp.cleanup()
 def test_budget_and_permission_failures_reach_verified_context_without_secrets(self):
  for error,expected in [(DataUnavailable('PROVIDER_RATE_BUDGET',429),'TRADABILITY_PROVIDER_RATE_BUDGET'),(trade_service.TradeError('secret provider content'),'TRADABILITY_PERMISSION_OR_CONTRACT_ERROR'),(TimeoutError('secret network content'),'TRADABILITY_NETWORK_ERROR'),(ValueError('secret unknown content'),'TRADABILITY_READ_UNAVAILABLE')]:
   with self.subTest(expected=expected),patch('trade_service.client',side_effect=error),patch.object(self.adapter,'inactive_orders',return_value=[]):
    result=self.adapter.safe_context(self.request,'USD')
    self.assertEqual((result['status'],result['position'],result['tradability'],result['diagnostic']),('verified','none','unknown',expected))
    self.assertNotIn('secret',str(result))
 def test_invalid_instrument_or_sizing_stays_unknown(self):
  for asset,expected in [(dict(self.asset,asset={'id':'wrong','ticker':'SYN','currency':'USD'}),'TRADABILITY_INSTRUMENT_UNVERIFIED'),(dict(self.asset,buyBy={}),'TRADABILITY_SIZING_UNVERIFIED')]:
   with self.subTest(expected=expected),patch('trade_service.client',return_value=(object(),{})),patch('trade_service.call',return_value=asset),patch.object(self.adapter,'inactive_orders',return_value=[]):
    result=self.adapter.safe_context(self.request,'USD');self.assertEqual((result['tradability'],result['diagnostic']),('unknown',expected))
 def test_budget_in_instrument_and_permission_calls_is_distinguished(self):
  for stage in ('instrument','permission'):
   with self.subTest(stage=stage),patch('trade_service.client',return_value=(object(),{})),patch('trade_service.call',side_effect=DataUnavailable('PROVIDER_RATE_BUDGET',429) if stage=='instrument' else None,return_value=self.asset),patch('trade_service.fresh_permission',side_effect=DataUnavailable('PROVIDER_RATE_BUDGET',429) if stage=='permission' else None),patch.object(self.adapter,'inactive_orders',return_value=[]):
    result=self.adapter.safe_context(self.request,'USD');self.assertEqual((result['status'],result['tradability'],result['diagnostic']),('verified','unknown','TRADABILITY_PROVIDER_RATE_BUDGET'))
 def test_success_and_exit_do_not_claim_a_failure(self):
  with patch('trade_service.client',return_value=(object(),{})),patch('trade_service.call',return_value=self.asset),patch('trade_service.fresh_permission'),patch.object(self.adapter,'inactive_orders',return_value=[]):
   result=self.adapter.safe_context(self.request,'USD');self.assertEqual(result['tradability'],'available');self.assertNotIn('diagnostic',result)
  with patch.object(self.adapter,'tradability',side_effect=AssertionError('exit must not query buy permission')),patch.object(self.adapter,'inactive_orders',return_value=[]):
   result=self.adapter.safe_context(dict(self.request,watch_mode='exit'),'USD');self.assertEqual(result['tradability'],'unknown');self.assertNotIn('diagnostic',result)
