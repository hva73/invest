"""Public issuer-format fixtures; no external network calls."""
import unittest
from unittest.mock import patch
import ishares_holdings as h

DIRECTORY=b'''<table><tr><td><a href="/us/products/239744/ishares-global-healthcare-etf">IXJ</a></td><td><a href="/us/products/239744/ishares-global-healthcare-etf">iShares Global Healthcare ETF</a></td></tr><tr><td><a href="/us/products/239745/ishares-global-industrials-etf">EXI</a></td><td><a href="/us/products/239745/ishares-global-industrials-etf">iShares Global Industrials ETF</a></td></tr></table>'''
CSV=b'''iShares Global Industrials ETF\nFund Holdings as of,"Nov 05, 2026"\nInception Date,"Sep 12, 2006"\n\nTicker,Name,Sector,Asset Class,Market Value,Weight (%),Notional Value,Quantity,Price,Location,Exchange,Currency,FX Rate,Market Currency,Accrual Date\n"GE","GE AEROSPACE","Industrials","Equity","47,023,809.30","3.45","47,023,809.30","149,410.00","314.73","United States","NYSE","USD","1.00","USD","-"\n"RTX","RTX","Industrials","Equity","37,277,103.24","2.74","37,277,103.24","194,273.00","191.88","United States","NYSE","USD","1.00","USD","-"\n"USD","USD CASH","Cash","Cash","1","0.01","1","1","1","United States","-","USD","1","USD","-"\n'''
class IShareHoldings(unittest.TestCase):
 def test_discovery_requires_exact_ticker_and_official_unique_path(self):
  self.assertEqual(h.discover(DIRECTORY,'IXJ'),('/us/products/239744/ishares-global-healthcare-etf','iShares Global Healthcare ETF'))
  with self.assertRaises(h.HoldingsUnavailable):h.discover(DIRECTORY,'IXN')
  duplicate=DIRECTORY+b'<a href="/us/products/999999/other-etf">IXJ</a>'
  with self.assertRaises(h.HoldingsUnavailable):h.discover(duplicate,'IXJ')
 def test_real_shape_and_equities_only(self):
  result=h.parse(CSV,'iShares Global Industrials ETF')
  self.assertEqual(result['as_of'],'2026-11-05');self.assertEqual([r['ticker'] for r in result['rows']],['GE','RTX']);self.assertEqual(result['rows'][0]['weight'],3.45)
  with self.assertRaises(h.HoldingsUnavailable):h.parse(CSV,'iShares Global Healthcare ETF')
  with self.assertRaises(h.HoldingsUnavailable):h.parse(CSV.replace(b'Fund Holdings as of',b'Unknown'), 'iShares Global Industrials ETF')
 def test_fetch_verifies_directory_and_csv_identity(self):
  with patch('ishares_holdings._get',side_effect=[DIRECTORY,CSV]) as get:
   result=h.fetch('EXI.US')
  self.assertEqual(result['rows'][0]['ticker'],'GE')
  self.assertEqual(get.call_args_list[1].args[0],'https://www.ishares.com/us/products/239745/ishares-global-industrials-etf/latest-holdings.csv')
  with patch('ishares_holdings._get',side_effect=[DIRECTORY,CSV]):
   with self.assertRaises(h.HoldingsUnavailable):h.fetch('IXJ.US')
 def test_url_injection_rejected(self):
  with self.assertRaises(h.HoldingsUnavailable):h.fetch('IXJ.US/../../bad')
if __name__=='__main__':unittest.main()
