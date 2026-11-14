import ast
import unittest
from pathlib import Path


def load_functions(path):
 tree=ast.parse(Path(path).read_text())
 selected=[node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name in ('structural','call')]
 expected={'type':'object','properties':{'portfolioId':{'type':'string'}}}
 class TradeError(ValueError):pass
 env={'CONTRACT':{'get_accounts':{'readOnlyHint':True,'inputSchema':expected},'other':{'readOnlyHint':True,'inputSchema':expected}},'TradeError':TradeError,'decode_result':lambda result,name:result}
 exec(compile(ast.Module(body=selected,type_ignores=[]),str(path),'exec'),env)
 return env,expected


class TestGetAccountsSchema(unittest.TestCase):
 def test_only_empty_required_is_normalized_for_accounts(self):
  path=Path('trade_service.py') if Path('trade_service.py').exists() else Path('trade_candidate.py')
  e,expected=load_functions(path)
  class Client:
   def __init__(self):self.calls=[]
   def request(self,*args):self.calls.append(args);return {'ok':True}
  client=Client();tool=lambda schema,readonly=True:{'annotations':{'readOnlyHint':readonly},'inputSchema':schema}
  compatible={**expected,'required':[]}
  self.assertEqual(e['call'](client,{'get_accounts':tool(compatible)},'get_accounts',{'portfolioId':'fixture'}),{'ok':True})
  for bad in ({**expected,'required':['other']},{**expected,'properties':{'portfolioId':{'type':'number'}}},{**expected,'extra':'unexpected'}):
   with self.assertRaises(e['TradeError']):e['call'](client,{'get_accounts':tool(bad)},'get_accounts',{'portfolioId':'fixture'})
  with self.assertRaises(e['TradeError']):e['call'](client,{'get_accounts':tool(compatible,False)},'get_accounts',{'portfolioId':'fixture'})
  with self.assertRaises(e['TradeError']):e['call'](client,{'other':tool(compatible)},'other',{'portfolioId':'fixture'})
  self.assertEqual(len(client.calls),1)

if __name__=='__main__':unittest.main()
