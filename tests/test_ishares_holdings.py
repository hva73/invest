"""Public issuer-format fixtures; no external network calls."""
import unittest,urllib.error
from unittest.mock import patch
import ishares_holdings as h

DIRECTORY=b'''<table><tr><td><a href="/us/products/239744/ishares-global-healthcare-etf">IXJ</a></td><td><a href="/us/products/239744/ishares-global-healthcare-etf">iShares Global Healthcare ETF</a></td></tr><tr><td><a href="/us/products/239745/ishares-global-industrials-etf">EXI</a></td><td><a href="/us/products/239745/ishares-global-industrials-etf">iShares Global Industrials ETF</a></td></tr></table>'''
CSV=b'''iShares Global Industrials ETF\nFund Holdings as of,"Nov 05, 2026"\nInception Date,"Sep 12, 2006"\n\nTicker,Name,Sector,Asset Class,Market Value,Weight (%),Notional Value,Quantity,Price,Location,Exchange,Currency,FX Rate,Market Currency,Accrual Date\n"GE","GE AEROSPACE","Industrials","Equity","47,023,809.30","3.45","47,023,809.30","149,410.00","314.73","United States","NYSE","USD","1.00","USD","-"\n"RTX","RTX","Industrials","Equity","37,277,103.24","2.74","37,277,103.24","194,273.00","191.88","United States","NYSE","USD","1.00","USD","-"\n"USD","USD CASH","Cash","Cash","1","0.01","1","1","1","United States","-","USD","1","USD","-"\n'''
EU_PATH='/de/privatanleger/de/produkte/251959/ishares-stoxx-europe-600-retail-ucits-etf-de-fund'
EU_NAME='iShares STOXX Europe 600 Retail UCITS ETF (DE)'
EU_SITEMAP=('<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://www.ishares.com'+EU_PATH+'</loc></url></urlset>').encode()
EU_PAGE=b'''<html><title>iShares STOXX Europe 600 Retail UCITS ETF (DE) | EXH8 | iShares</title><script>{"contentUrl":"http://www.ishares.com/de/privatanleger/de/produkte/251959/ishares-stoxx-europe-600-retail-ucits-etf-de/latest-holdings.csv"}</script></html>'''
EU_CSV='''Fondsposition per,"05.Nov.2026"\n\nEmittententicker,Name,Sektor,Anlageklasse,Marktwert,Gewichtung (%),Nominalwert,Nominale,Kurs,Standort,Börse,Marktwährung\n"ITX","INDUSTRIA DE DISENO TEXTIL SA","Konsumgüter","Aktien","4.128.704,58","27,95","4.128.704,58","68.743,00","60,06","Spanien","Bolsa De Madrid","EUR"\n"HM B","HENNES & MAURITZ","Konsumgüter","Aktien","1.278.533,02","8,65","1","77.228,00","16,56","Schweden","Nasdaq Omx Nordic","SEK"\n'''.encode()
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
 def test_europe_public_sitemap_title_and_german_csv(self):
  self.assertEqual(h.discover_europe(EU_SITEMAP,EU_NAME),EU_PATH)
  url=h.europe_csv_url(EU_PAGE,EU_PATH,'EXH8',EU_NAME)
  self.assertEqual(url,'https://www.ishares.com/de/privatanleger/de/produkte/251959/ishares-stoxx-europe-600-retail-ucits-etf-de/latest-holdings.csv')
  result=h.parse_europe(EU_CSV);self.assertEqual(result['as_of'],'2026-11-05')
  self.assertEqual([(x['ticker'],x['weight']) for x in result['rows']],[('ITX',27.95),('HM B',8.65)])
  with self.assertRaises(h.HoldingsUnavailable):h.europe_csv_url(EU_PAGE,EU_PATH,'EXV9',EU_NAME)
  with self.assertRaises(h.HoldingsUnavailable):h.europe_csv_url(EU_PAGE.replace(b'www.ishares.com',b'bad.example'),EU_PATH,'EXH8',EU_NAME)
  with self.assertRaises(h.HoldingsUnavailable):h.discover_europe(EU_SITEMAP,EU_NAME.replace('Retail','Travel'))
 def test_europe_fetch_binds_product_to_ticker_and_verified_name(self):
  with patch('ishares_holdings._get',side_effect=[EU_SITEMAP,EU_PAGE,EU_CSV]) as get:result=h.fetch_europe('EXH8.XETRA',EU_NAME)
  self.assertEqual(result['rows'][0]['ticker'],'ITX');self.assertEqual(get.call_count,3)
  with patch('ishares_holdings._get',side_effect=[EU_SITEMAP,EU_PAGE]):
   with self.assertRaises(h.HoldingsUnavailable):h.fetch_europe('EXV9.XETRA',EU_NAME)
 def test_redirects_stay_on_https_issuer(self):
  class Response:
   def __enter__(self):return self
   def __exit__(self,*args):pass
   def read(self,n):return b'public'
  class Opener:
   def __init__(self,target):self.target=target;self.calls=0
   def open(self,request,timeout):
    self.calls+=1
    if self.calls==1:raise urllib.error.HTTPError(request.full_url,301,'redirect',{'Location':self.target},None)
    return Response()
  safe=Opener('https://www.ishares.com/de/privatanleger/de/produkte/251959/retail')
  with patch('ishares_holdings.urllib.request.build_opener',return_value=safe):self.assertEqual(h._get('https://www.ishares.com'+EU_PATH,100),b'public')
  bad=Opener('https://attacker.example/latest-holdings.csv')
  with patch('ishares_holdings.urllib.request.build_opener',return_value=bad):
   with self.assertRaises(h.HoldingsUnavailable):h._get('https://www.ishares.com'+EU_PATH,100)
  self.assertEqual(bad.calls,1)
if __name__=='__main__':unittest.main()
