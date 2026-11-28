import concurrent.futures
import threading
import unittest
import sqlite3
import tempfile
import os
from datetime import datetime, timezone
from unittest.mock import patch

import hotwatch_adapters as adapters
from hotwatch_adapters import PlutoAdapter, DataUnavailable


class GatewayReuse(unittest.TestCase):
 def setUp(self):
  adapters._statistics_gateways.clear()
  self.connect=lambda:None
  self.calls=[]
  self.calls_lock=threading.Lock()
 def request(self,client,method,params=None,notification=False):
  with self.calls_lock:self.calls.append(method)
  if method=='initialize':return {'protocolVersion':'2025-06-18'}
  if method=='tools/list':return {'tools':[{'name':'list_orders','annotations':{'readOnlyHint':True}}]}
  if method=='tools/call':return {'structuredContent':{'orders':[]}}
 def run_read(self,uid=1,token='token',connect=None):
  gateway=PlutoAdapter(connect or self.connect,uid,purpose='statistics').factory(token)
  gateway.tools()
  gateway.request('tools/call',{'name':'list_orders','arguments':{'portfolioId':'synthetic'}})
  return gateway
 def test_repeat_reuses_session_but_still_budgets_every_call(self):
  with patch('hotwatch_adapters.reserve') as budget,patch('mcp_client.MCP.request',lambda client,method,params=None,notification=False:self.request(client,method,params,notification)):
   self.run_read();self.run_read()
  self.assertEqual(self.calls,['initialize','notifications/initialized','tools/list','tools/call','tools/call'])
  self.assertEqual(budget.call_count,5)
 def test_isolated_by_user_token_and_database(self):
  with patch('hotwatch_adapters.reserve'),patch('mcp_client.MCP.request',lambda client,method,params=None,notification=False:self.request(client,method,params,notification)):
   a=self.run_read();self.assertIsNot(a,self.run_read(uid=2));self.assertIsNot(a,self.run_read(token='other'));self.assertIsNot(a,self.run_read(connect=lambda:None))
 def test_network_error_invalidates_session_next_attempt(self):
  def failing(client,method,params=None,notification=False):
   if method=='tools/call':raise ConnectionError()
   return self.request(client,method,params,notification)
  with patch('hotwatch_adapters.reserve'),patch('mcp_client.MCP.request',failing):
   with self.assertRaises(ConnectionError):self.run_read()
  with patch('hotwatch_adapters.reserve'),patch('mcp_client.MCP.request',lambda client,method,params=None,notification=False:self.request(client,method,params,notification)):self.run_read()
  self.assertEqual(self.calls.count('initialize'),2)
 def test_provider_tool_error_invalidates_session_next_attempt(self):
  def failing(client,method,params=None,notification=False):
   if method=='tools/call':return {'isError':True}
   return self.request(client,method,params,notification)
  with patch('hotwatch_adapters.reserve'),patch('mcp_client.MCP.request',failing):
   gateway=self.run_read();self.assertTrue(gateway.broken)
  with patch('hotwatch_adapters.reserve'),patch('mcp_client.MCP.request',lambda client,method,params=None,notification=False:self.request(client,method,params,notification)):
   self.run_read()
  self.assertEqual(self.calls.count('initialize'),2)
 def test_expired_cache_reinitializes(self):
  with patch('hotwatch_adapters.time.monotonic',side_effect=[100,161]),patch('hotwatch_adapters.reserve'),patch('mcp_client.MCP.request',lambda client,method,params=None,notification=False:self.request(client,method,params,notification)):
   self.run_read();self.run_read()
  self.assertEqual(self.calls.count('initialize'),2)
 def test_concurrent_reads_share_single_initialization(self):
  with patch('hotwatch_adapters.reserve') as budget,patch('mcp_client.MCP.request',lambda client,method,params=None,notification=False:self.request(client,method,params,notification)):
   with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:list(pool.map(lambda _:self.run_read(),range(6)))
  self.assertEqual(self.calls.count('initialize'),1);self.assertEqual(self.calls.count('tools/call'),6);self.assertEqual(budget.call_count,9)
 def test_blocked_tools_are_never_sent(self):
  with patch('hotwatch_adapters.reserve'),patch('mcp_client.MCP.request',lambda client,method,params=None,notification=False:self.request(client,method,params,notification)):
   g=self.run_read()
   with self.assertRaises(DataUnavailable):g.request('tools/call',{'name':'propose_orders','arguments':{}})
  self.assertEqual(self.calls.count('tools/call'),1)
 def test_budget_rejection_does_not_make_an_unbudgeted_call(self):
  with patch('hotwatch_adapters.reserve') as reserve,patch('mcp_client.MCP.request',lambda client,method,params=None,notification=False:self.request(client,method,params,notification)):
   self.run_read();before=len(self.calls)
   reserve.side_effect=DataUnavailable('PROVIDER_RATE_BUDGET',429)
   with self.assertRaises(DataUnavailable):self.run_read()
   self.assertEqual(len(self.calls),before)
   reserve.side_effect=None;self.run_read()
  self.assertEqual(self.calls.count('initialize'),1)
  self.assertEqual(self.calls.count('tools/call'),2)

if __name__=='__main__':unittest.main()


class InteractiveBudget(unittest.TestCase):
 def test_full_scan_bucket_does_not_starve_readonly_statistics(self):
  with tempfile.TemporaryDirectory() as root:
   path=os.path.join(root,'budget.sqlite')
   def connect():
    db=sqlite3.connect(path);db.row_factory=sqlite3.Row;return db
   with connect() as db:
    db.execute('CREATE TABLE hw_request_budget(user_id INTEGER, source TEXT, window INTEGER, used INTEGER, PRIMARY KEY(user_id,source,window))')
   now=datetime(2026,11,15,13,0,tzinfo=timezone.utc)
   with patch('hotwatch_adapters.provider_request_limit',return_value=3):
    for _ in range(3):adapters.reserve(connect,1,'pluto',now=now,purpose='scan')
    with self.assertRaises(DataUnavailable):adapters.reserve(connect,1,'pluto',now=now,purpose='scan')
    for _ in range(3):adapters.reserve(connect,1,'pluto',now=now,purpose='statistics')
    with self.assertRaises(DataUnavailable):adapters.reserve(connect,1,'pluto',now=now,purpose='statistics')
    adapters.reserve(connect,2,'pluto',now=now,purpose='statistics')
   with connect() as db:
    self.assertEqual(db.execute("SELECT used FROM hw_request_budget WHERE user_id=1 AND source='pluto'").fetchone()[0],3)
    self.assertEqual(db.execute("SELECT used FROM hw_request_budget WHERE user_id=1 AND source='pluto:statistics'").fetchone()[0],3)
