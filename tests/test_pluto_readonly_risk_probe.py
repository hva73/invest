import unittest
from tasks.pluto_readonly_risk_probe import shape

class ProbeOutput(unittest.TestCase):
 def test_only_allowlisted_names_and_types_leave_probe(self):
  result=shape({'accountId':'private','commission':{'amount':'0.2','currency':'DKK'},'assetBankFx':{'base':'USD','quote':'DKK','rate':'6.7'},'orders':[{'orderId':'private','status':'FILLED','filledQuantity':'5','unknown':'private'}]})
  self.assertEqual(result,{'commission':{'amount':'str','currency':'DKK'},'assetBankFx':{'base':'USD','quote':'DKK','rate':'str'},'orders':[{'orderId':'str','status':'str','filledQuantity':'str'}]})
  self.assertNotIn('private',str(result))
