"""Overview-only aggregation of leaf holdings; no broker scope is merged."""
import copy,unittest
from decimal import Decimal
from unittest.mock import patch
import app,dashboard_projection as dashboard
import test_hotwatch_engine as fixture

def money(n,c='USD'):return {'amount':str(n),'currency':c}
def holding(pid,qty,entry,value,pnl,aid='same-asset',kind='portfolio'):
 return {'key':f'pluto:{pid}:{aid}','portfolio_id':pid,'portfolio_name':f'Depot {pid}','portfolio_kind':kind,'external_id':f'portfolios:{pid}','asset_id':aid,'ticker':'TEST','name':'Synthetic','quantity':str(qty),'price':money(30),'price_time':None,'value':money(value),'original_value':money(value),'cost_basis':money(Decimal(str(qty))*Decimal(str(entry))),'average_entry':money(entry),'unrealized':money(pnl),'original_unrealized':money(pnl),'unrealized_estimated':False,'daily':None,'since_last':None,'hot_watch':{'session':{'watch_id':f'watch-{pid}'}},'assessment':{},'conflicts':[],'missing':{},'snapshot_at':'2026-11-09T20:00:00Z','verification':'broker_snapshot','raw':{'kind':'holding'}}

class CombinedHoldings(unittest.TestCase):
 def test_quantity_weighted_price_and_sum_results_without_mixing_trade_scope(self):
  rows=[holding(1,2,10,60,40),holding(2,1,40,30,-10,kind='collection')];before=copy.deepcopy(rows)
  out=dashboard.overview_positions(rows);self.assertEqual(len(out),1);r=out[0]
  self.assertEqual(Decimal(r['quantity']),3);self.assertEqual(Decimal(r['value']['amount']),90)
  self.assertEqual(Decimal(r['cost_basis']['amount']),60);self.assertEqual(Decimal(r['average_entry']['amount']),20)
  self.assertEqual(Decimal(r['unrealized']['amount']),30);self.assertEqual(Decimal(r['unrealized_percent']),50)
  self.assertIsNone(r['portfolio_id']);self.assertEqual(r['hot_watch'],{});self.assertEqual(len(r['member_keys']),2)
  self.assertEqual(rows,before)
 def test_general_asset_id_grouping_does_not_merge_tickers_or_missing_ids(self):
  rows=[holding(1,1,10,30,20,'a'),holding(2,1,10,30,20,'b'),holding(3,1,10,30,20,None),holding(4,1,10,30,20,None)]
  self.assertEqual(len(dashboard.overview_positions(rows)),4)
  rows.append(holding(5,1,10,30,20,'a'));result=dashboard.overview_positions(rows)
  self.assertEqual(len(result),4);self.assertEqual(len(next(r for r in result if r.get('asset_id')=='a')['member_keys']),2)
 def test_fractional_positions_keep_precision(self):
  rows=[holding(1,'0.1',100,30,20),holding(2,'0.2',250,60,10)]
  r=dashboard.overview_positions(rows)[0]
  self.assertEqual(Decimal(r['quantity']),Decimal('0.3'));self.assertEqual(Decimal(r['average_entry']['amount']),200)
 def test_common_original_currency_fallback_never_sums_dkk_and_usd(self):
  rows=[holding(1,1,10,15,5),holding(2,1,20,25,5)];rows[0].update(value=money(105,'DKK'),unrealized=money(35,'DKK'))
  r=dashboard.overview_positions(rows)[0]
  self.assertEqual(r['value'],money(40));self.assertEqual(r['unrealized'],money(10))
  rows[1]['original_value']=money(25,'EUR');r=dashboard.overview_positions(rows)[0]
  self.assertIsNone(r['value']);self.assertTrue(r['missing']['aggregate_value'])
 def test_missing_member_values_never_become_complete_totals(self):
  rows=[holding(1,1,10,15,5),holding(2,1,20,25,5)]
  rows[1].update(value=None,original_value=None,unrealized=None,original_unrealized=None,average_entry=None,quantity=None,verification='last_known')
  r=dashboard.overview_positions(rows)[0]
  for name in ('value','unrealized','average_entry','quantity'):self.assertIsNone(r[name],name)
  self.assertEqual(r['verification'],'last_known')
 def test_collection_summary_is_not_counted_as_leaf(self):
  rows=[holding(1,2,10,60,40),holding(2,1,40,30,-10,kind='collection')]
  summary=holding(1,1,100,100,0);summary['raw']['kind']='collection'
  r=dashboard.overview_positions(rows+[summary])[0];self.assertEqual(r['quantity'],'3');self.assertEqual(r['value'],money(90))
 def test_build_keeps_parent_total_and_individual_positions_unchanged(self):
  f=fixture.HotWatch();f.setUp()
  try:
   owned=[{'id':1,'name':'Root','kind':'portfolio','source':'pluto','active':1,'external_id':'portfolios:root'}, {'id':2,'name':'Child','kind':'collection','source':'pluto','active':1,'external_id':'collections:child','parent_external_id':'portfolios:root'}]
   rows=[holding(1,2,10,60,40),holding(2,1,40,30,-10,kind='collection')]
   snapshots={str(i+1):{'data':{'positions_complete':True,'observed':f.now.isoformat(),'positions':[dict(r['raw'],**{k:r[k] for k in ('asset_id','ticker','name','quantity','price','value','cost_basis','average_entry','unrealized')})],'value':{'value':money(100 if i==0 else 30,'DKK')}}} for i,r in enumerate(rows)}
   snapshots['1']['data']['positions'].append({'kind':'collection','asset_id':'same-asset','quantity':'99','value':money(30,'DKK')})
   with patch('dashboard_projection.position_hotwatch',return_value={'candidate_id':None}):out=dashboard.build(app.connect,1,owned,snapshots,f.now)
   self.assertEqual(out['totals'],[money(100,'DKK')]);self.assertEqual(len(out['positions']),2)
   self.assertEqual(len(out['overview_positions']),1);self.assertEqual(out['overview_positions'][0]['quantity'],'3')
   self.assertCountEqual([r['portfolio_id'] for r in out['positions']],[1,2])
   with app.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM broker_proposals').fetchone()[0],0)
  finally:f.tearDown()
