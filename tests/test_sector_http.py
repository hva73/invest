"""Authenticated UI queue for public ETF holdings; no provider or broker calls."""
import time, unittest
import app
import test_mcp_reports

class SectorHoldingsHttp(unittest.TestCase):
 def setUp(self):
  self.http=test_mcp_reports.McpReports();self.http.setUp()
 def tearDown(self):self.http.tearDown()
 def test_holdings_request_requires_login_csrf_and_known_verified_fund(self):
  path='/api/sector-intelligence/holdings'
  self.assertEqual(self.http.request(path,{'symbol':'XLK.US'})[0],401)
  auth=self.http.login()
  self.assertEqual(self.http.request(path+'?symbol=XLK.US',headers=auth,method='GET')[0],405)
  with app.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM sector_benchmark_holdings').fetchone()[0],0)
  self.assertEqual(self.http.request(path,{'symbol':'XLK.US'},{'Cookie':auth['Cookie']})[0],403)
  self.assertEqual(self.http.request(path,{'symbol':'NOT-ALLOWED.US'},auth)[0],400)
  self.assertEqual(self.http.request(path,{'symbol':'XLK.US'},auth)[1]['status'],'UNVERIFIED_BENCHMARK')
  now=time.time()
  with app.connect() as c:
   c.execute('INSERT INTO sector_benchmarks(symbol,region,sector,status,updated,next_attempt) VALUES(?,?,?,?,?,?)',('XLK.US','USA','Teknologi','VERIFIED',now,now+3600))
   before=c.execute('SELECT COUNT(*) FROM broker_proposals').fetchone()[0]
  status,result,_=self.http.request(path,{'symbol':'XLK.US'},auth)
  self.assertEqual((status,result['status']),(200,'TRY_ISSUER'));self.assertIsInstance(result['updated'],float)
  with app.connect() as c:
   self.assertEqual(c.execute('SELECT symbol FROM sector_benchmark_holdings').fetchone()[0],'XLK.US')
   self.assertEqual(c.execute('SELECT COUNT(*) FROM broker_proposals').fetchone()[0],before)
