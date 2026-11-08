import unittest
from tasks.pluto_readonly_risk_probe import shape

class ProbeOutput(unittest.TestCase):
 def test_only_allowlisted_names_and_types_leave_probe(self):
  result=shape({'accountId':'private','commission':{'amount':'0.2','currency':'DKK'},'assetBankFx':{'base':'USD','quote':'DKK','rate':'6.7'},'orders':[{'orderId':'private','status':'FILLED','filledQuantity':'5','unknown':'private'}]})
  self.assertEqual(result,{'commission':{'amount':'str','currency':'DKK'},'assetBankFx':{'base':'USD','quote':'DKK','rate':'str'},'orders':[{'orderId':'str','status':'str','filledQuantity':'str','_ovrige_felter_typer':['str']}],'_ovrige_felter_typer':['str']})
  self.assertNotIn('private',str(result))
 def test_unknown_envelopes_do_not_hide_estimate_or_reveal_values(self):
  result=shape({'unknownEnvelope':[{'anotherWrapper':{'commission':{'amount':'3','currency':'USD'},'secret':'sensitive'}}]})
  self.assertIn('commission',str(result));self.assertIn('USD',str(result));self.assertNotIn('sensitive',str(result));self.assertNotIn('unknownEnvelope',str(result))
