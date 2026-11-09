import unittest
from datetime import datetime,timezone,timedelta
from instrument_resolver import resolve_instrument,resolve_cxe,resolve_us,crypto_reference
from cxe_reference import parse_reference,ReferenceUnavailable

class InstrumentResolver(unittest.TestCase):
 def test_ferguson_old_name_requires_exact_independently_checked_us_security(self):
  pluto={'asset_id':'13ba8af0-fa33-442a-9610-47fe67b70f1d','ticker':'FERG','name':'Ferguson Enterprises Inc.','exchange':'NYSE','currency':'USD','type':'CS'}
  listing={'Code':'FERG','Name':'Ferguson Plc','Country':'USA','Exchange':'NYSE','Currency':'USD','Type':'Common Stock','Isin':'US31488V1070'}
  choice={'symbol':'FERG.US','exchange':'US','currency':'USD','isin':'US31488V1070'}
  result=resolve_us(pluto,[choice],[listing]);self.assertEqual(result['status'],'VERIFIED');self.assertIn('Endavu',result['type_note'])
  for fields in ({'asset_id':'other'},{'name':'Ferguson Enterprises Class A Common Stock'},{'exchange':'NASDAQ'},{'type':'ADRC'},{'currency':'GBP'},{'isin':'JE00BJVNSS43'}):
   with self.subTest(fields=fields):self.assertNotEqual(resolve_us(dict(pluto,**fields),[choice],[listing])['status'],'VERIFIED')
  for fields in ({'Name':'Ferguson Holdings Plc'},{'Isin':'JE00BJVNSS43'},{'Exchange':'NASDAQ'},{'Type':'Preferred Stock'}):
   with self.subTest(fields=fields):self.assertNotEqual(resolve_us(pluto,[choice],[dict(listing,**fields)])['status'],'VERIFIED')
  self.assertNotEqual(resolve_us(pluto,[dict(choice,isin=None)],[listing])['status'],'VERIFIED')
  self.assertNotEqual(resolve_us(pluto,[dict(choice,isin='JE00BJVNSS43')],[listing])['status'],'VERIFIED')
  self.assertEqual(resolve_us(pluto,[choice],[listing,listing])['status'],'AMBIGUOUS')
 def test_short_issuer_is_not_rejected_but_all_listing_checks_remain(self):
  pluto={'asset_id':'synthetic-kkr','ticker':'KKR','name':'KKR & Co. Inc.','exchange':'NYSE','currency':'USD','type':'CS'}
  listing={'Code':'KKR','Name':'KKR & Co. Inc.','Country':'USA','Exchange':'NYSE','Currency':'USD','Type':'Common Stock','Isin':'US48251W1045'}
  choice={'symbol':'KKR.US','exchange':'US','currency':'USD','isin':'US48251W1045'}
  self.assertEqual(resolve_us(pluto,[choice],[listing])['status'],'VERIFIED')
  for fields in ({'name':'ABC & Co. Inc.'},{'name':'Co. Inc.'},{'name':''},{'exchange':'NASDAQ'},{'currency':'CAD'},{'isin':'US0000000001'}):
   with self.subTest(fields=fields):self.assertNotEqual(resolve_us(dict(pluto,**fields),[choice],[listing])['status'],'VERIFIED')
  for fields in ({'Isin':None},{'Type':'Preferred Stock'},{'Currency':'CAD'},{'Country':'Canada'},{'Code':'KKR-PD'}):
   with self.subTest(fields=fields):self.assertNotEqual(resolve_us(pluto,[choice],[dict(listing,**fields)])['status'],'VERIFIED')
  self.assertEqual(resolve_us(pluto,[choice],[listing,listing])['status'],'AMBIGUOUS')
 def test_observed_hrtx_truncation_is_pinned_to_independently_checked_security(self):
  pluto={'asset_id':'da14edd7-64b5-4932-9dd5-62b4136a2387','ticker':'HRTX','name':'Heron Therapeutics, Inc. Common Stock','exchange':'NASDAQ','currency':'USD','type':'CS'}
  listing={'Code':'HRTX','Name':'Heron Therapeuti','Country':'USA','Exchange':'NASDAQ','Currency':'USD','Type':'Common Stock','Isin':'US4277461020'}
  choice={'symbol':'HRTX.US','exchange':'US','currency':'USD','isin':'US4277461020'}
  result=resolve_us(pluto,[choice],[listing]);self.assertEqual(result['status'],'VERIFIED');self.assertIn('Endavu',result['type_note'])
  self.assertNotEqual(resolve_us(dict(pluto,exchange='NYSE'),[choice],[dict(listing,Exchange='NYSE')])['status'],'VERIFIED')
  for fields in ({'asset_id':'other'},{'ticker':'OTHER'},{'name':'Heron Therapeutics Class A Common Stock'},{'exchange':'NYSE'},{'currency':'EUR'},{'type':'ADRC'},{'isin':'US0000000001'}):
   with self.subTest(fields=fields):self.assertNotEqual(resolve_us(dict(pluto,**fields),[choice],[listing])['status'],'VERIFIED')
  for fields in ({'Isin':'US0000000001'},{'Name':'Heron Therapeu'},{'Name':'Heron Therapeuti Class B'},{'Exchange':'NYSE'},{'Type':'Preferred Stock'}):
   with self.subTest(fields=fields):self.assertNotEqual(resolve_us(pluto,[choice],[dict(listing,**fields)])['status'],'VERIFIED')
  for fields in ({'isin':None},{'isin':'US0000000001'},{'currency':'EUR'},{'symbol':'HRTX.F'}):
   with self.subTest(fields=fields):self.assertNotEqual(resolve_us(pluto,[dict(choice,**fields)],[listing])['status'],'VERIFIED')
  self.assertEqual(resolve_us(pluto,[choice],[listing,listing])['status'],'AMBIGUOUS')
  self.assertEqual(resolve_us(pluto,[choice,choice],[listing])['status'],'AMBIGUOUS')
 def test_us_share_class_alias_requires_same_class_and_matching_isin(self):
  pluto={'asset_id':'synthetic-berkshire','ticker':'BRK.B','name':'Berkshire Hathaway Class B','exchange':'NYSE','currency':'USD','type':'CS'}
  listing={'Code':'BRK-B','Name':'Berkshire Hathaway Inc','Country':'USA','Exchange':'NYSE','Currency':'USD','Type':'Common Stock','Isin':'US0846707026'}
  choice={'symbol':'BRK-B.US','exchange':'US','currency':'USD','isin':'US0846707026'}
  result=resolve_us(pluto,[choice],[listing]);self.assertEqual(result['status'],'VERIFIED');self.assertEqual(result['symbol'],'BRK-B.US')
  self.assertNotEqual(resolve_us(pluto,[choice],[dict(listing,Code='BRK-A')])['status'],'VERIFIED')
  self.assertNotEqual(resolve_us(pluto,[dict(choice,isin='US0846701086')],[listing])['status'],'VERIFIED')
  self.assertNotEqual(resolve_us(pluto,[dict(choice,isin=None)],[listing])['status'],'VERIFIED')
  self.assertEqual(resolve_us(pluto,[choice],[listing,listing])['status'],'AMBIGUOUS')
  self.assertNotEqual(resolve_us(dict(pluto,name='Berkshire Hathaway Class A'),[choice],[dict(listing,Name='Berkshire Hathaway Class B')])['status'],'VERIFIED')
 def test_owner_authorized_crypto_reference_is_pinned_to_broker_asset_and_currency(self):
  btc={'asset_id':'54368e0b-2d53-401e-bf68-1033a5b84b08','ticker':'BTC','name':'Bitcoin','type':'CRYPTO','currency':'USD','exchange':'WINTERMUTE'}
  pepe={'asset_id':'4cde5f75-df03-4abc-9063-cfc588e31c11','ticker':'PEPE','name':'Pepe','type':'CRYPTO','currency':'USD','exchange':'UKENDT'}
  self.assertEqual(crypto_reference(btc)['symbol'],'BTC-USD.CC');self.assertTrue(crypto_reference(btc)['approved'])
  self.assertEqual(crypto_reference(pepe)['symbol'],'PEPE24478-USD.CC');self.assertFalse(crypto_reference(pepe)['approved'])
  for field,value in [('asset_id','other'),('ticker','WBTC'),('name','Wrapped Bitcoin'),('currency','EUR'),('type','STOCK'),('exchange','OTHER')]:
   with self.subTest(field=field):self.assertIsNone(crypto_reference(dict(btc,**{field:value})))
  self.assertIsNone(crypto_reference(dict(pepe,asset_id='unrelated-pepe')))
 def test_observed_novob_and_tsm_without_broker_identifier_stay_unverified(self):
  cases=[({'asset_id':'novo','ticker':'NOVOB','name':'Novo Nordisk A/S','exchange':'CHIX','currency':'DKK'}, {'symbol':'NOVO-B.CO','ticker':'NOVO-B','name':'Novo Nordisk A/S','exchange':'CO','currency':'DKK','isin':'DK0062498333'}),({'asset_id':'tsm','ticker':'TSM','name':'Taiwan Semiconductor Manufacturing Company Ltd.','exchange':'NYSE','currency':'USD'}, {'symbol':'TSM.US','ticker':'TSM','name':'Taiwan Semiconductor Manufacturing','exchange':'US','currency':'USD','isin':'US8740391003'})]
  for pluto,eodhd in cases:
   with self.subTest(ticker=pluto['ticker']):
    result=resolve_instrument(pluto,[eodhd]);self.assertEqual(result['status'],'UNVERIFIED');self.assertIsNone(result['symbol']);self.assertIn('isin',result['candidates'][0]['missing']);self.assertIn('currency',result['candidates'][0]['matches'])
 def test_scho_and_tsla_missing_metadata_cannot_be_guessed(self):
  for ticker,currency in [('SCHO','DKK'),('TSLA','USD')]:
   with self.subTest(ticker=ticker):
    result=resolve_instrument({'asset_id':'asset-'+ticker,'ticker':ticker,'currency':currency},[{'symbol':ticker+'.TEST','currency':currency}])
    self.assertEqual(result['status'],'UNVERIFIED');self.assertIn('isin',result['candidates'][0]['missing'])
 def test_common_isin_or_figi_requires_currency_and_no_conflicting_class(self):
  broker={'asset_id':'x','isin':'US0000000001','currency':'USD','share_class':'A'}
  feed={'symbol':'X.US','isin':'US0000000001','currency':'USD','share_class':'A'}
  self.assertEqual(resolve_instrument(broker,[feed])['status'],'VERIFIED')
  self.assertEqual(resolve_instrument(broker,[dict(feed,share_class='B')])['status'],'UNVERIFIED')
  self.assertEqual(resolve_instrument(broker,[dict(feed,isin='US0000000002')])['status'],'UNVERIFIED')
  self.assertEqual(resolve_instrument({'asset_id':'x','figi':'BBG000000001','currency':'USD'},[{'symbol':'X.US','figi':'BBG000000001','currency':'USD'}])['status'],'VERIFIED')
  self.assertEqual(resolve_instrument(broker,[feed,dict(feed,symbol='X.ALT')])['status'],'AMBIGUOUS')
 def test_cxe_confirms_novo_and_schouw_without_pluto_isin(self):
  for ticker,name,isin,eodhd in [('NOVOB','Novo Nordisk A/S','DK0062498333','NOVO-B.CO'),('SCHO','Schouw & Co A/S','DK0010253921','SCHO.CO')]:
   with self.subTest(ticker=ticker):
    pluto={'asset_id':'synthetic-'+ticker,'ticker':ticker,'name':name,'currency':'DKK','exchange':'CHIX','type':'CS'}
    row={'symbol':ticker+'c','primary_ticker':ticker,'name':name,'isin':isin,'currency':'DKK','instrument_type':'EQTY','mic':'XCSE'}
    feed={'symbol':eodhd,'isin':isin,'currency':'DKK','exchange':'CO'}
    self.assertEqual(resolve_cxe(pluto,[feed],[row])['symbol'],eodhd)
    self.assertEqual(resolve_cxe(pluto,[feed],[row,dict(row)])['status'],'AMBIGUOUS')
    self.assertEqual(resolve_cxe(pluto,[feed],[dict(row,primary_ticker=ticker+'A')])['status'],'UNVERIFIED')
    self.assertEqual(resolve_cxe(dict(pluto,type='ADRC'),[feed],[row])['status'],'UNVERIFIED')
    self.assertEqual(resolve_cxe(dict(pluto,isin='DK0000000001'),[feed],[row])['status'],'UNVERIFIED')
    self.assertEqual(resolve_cxe(pluto,[dict(feed,currency='USD')],[row])['status'],'UNVERIFIED')
 def test_asml_selects_amsterdam_listing_not_milan_or_leveraged_product(self):
  pluto={'asset_id':'asset-asml','ticker':'ASML','name':'ASML Holding NV','currency':'EUR','exchange':'CHIX','type':'CS'}
  rows=[{'symbol':'ASMLa','primary_ticker':'ASML','name':'ASML Holding NV','isin':'NL0010273215','currency':'EUR','instrument_type':'EQTY','mic':'XAMS'}, {'symbol':'1ASMLm','primary_ticker':'1ASML','name':'ASML Holding NV','isin':'NL0010273215','currency':'EUR','instrument_type':'EQTY','mic':'MTAA'}, {'symbol':'3ASML','primary_ticker':'ASML','name':'Leverage Shares 3x Long ASML ETP','isin':'XS3068790065','currency':'EUR','instrument_type':'ETN','mic':'XLON'}]
  choices=[{'symbol':'ASML.AS','exchange':'AS','currency':'EUR','isin':'NL0010273215'},{'symbol':'ASML.F','exchange':'F','currency':'EUR','isin':'NL0010273215'}]
  self.assertEqual(resolve_cxe(pluto,choices,rows)['symbol'],'ASML.AS')
  no_currency=dict(choices[0],currency=None)
  self.assertEqual(resolve_cxe(pluto,[no_currency],rows)['currency_basis'],'cxe_primary_listing')
  self.assertEqual(resolve_cxe(pluto,[dict(choices[0],currency='USD')],rows)['status'],'UNVERIFIED')
  us_adr=dict(pluto,asset_id='synthetic-us-adr',name='ASML Holding N.V. New York Registry Shares',exchange='NASDAQ',currency='USD',type='ADRC')
  self.assertEqual(resolve_cxe(us_adr,choices,rows)['status'],'UNVERIFIED')
 def test_known_primary_market_mapping_does_not_merge_euro_venues(self):
  pluto={'asset_id':'synthetic','ticker':'EXMP','name':'Example Corporation','currency':'EUR','exchange':'CHIX','type':'CS'}
  row={'symbol':'EXMPd','primary_ticker':'EXMP','name':'Example Corporation','isin':'DE0000000001','currency':'EUR','instrument_type':'EQTY','mic':'XETR'}
  choices=[{'symbol':'EXMP.XETRA','exchange':'XETRA','currency':'EUR','isin':row['isin']},{'symbol':'EXMP.F','exchange':'F','currency':'EUR','isin':row['isin']}]
  self.assertEqual(resolve_cxe(pluto,choices,[row])['symbol'],'EXMP.XETRA')
  self.assertEqual(resolve_cxe(pluto,choices,[dict(row,mic='UNKNOWN')])['status'],'UNVERIFIED')
 def test_cxe_parser_checks_production_schema_and_freshness(self):
  now=datetime(2026,11,6,18,30,tzinfo=timezone.utc)
  content=('environment=PROD,created=2026-11-06,time=18:25Z,warning=\n'
           'company_name,bats_name,isin,currency,mic,bloomberg_primary,asset_class,live,corporate_action_status\n'
           'ASML Holding NV,ASMLa,NL0010273215,EUR,XAMS,ASML NA Equity,EQTY,t,\n').encode()
  parsed=parse_reference(content,now);self.assertEqual(parsed['rows'][0]['primary_ticker'],'ASML')
  with self.assertRaises(ReferenceUnavailable):parse_reference(content,now+timedelta(days=4))
  with self.assertRaises(ReferenceUnavailable):parse_reference(content.replace(b'environment=PROD',b'environment=TEST'),now)
  with self.assertRaises(ReferenceUnavailable):parse_reference(content.replace(b'asset_class',b'unknown'),now)
  with self.assertRaises(ReferenceUnavailable):parse_reference(content.replace(b'EQTY,t,\n',b'EQTY,t,PENDING\n'),now)
 def test_empty_early_cxe_file_reuses_only_recent_valid_persisted_reference(self):
  import io, sqlite3, tempfile
  from unittest.mock import patch
  from cxe_reference import get_reference
  now=datetime(2026,11,6,18,30,tzinfo=timezone.utc)
  valid=('environment=PROD,created=2026-11-06,time=18:25Z,warning=\n'
         'company_name,bats_name,isin,currency,mic,bloomberg_primary,asset_class,live,corporate_action_status\n'
         'ASML Holding NV,ASMLa,NL0010273215,EUR,XAMS,ASML NA Equity,EQTY,t,\n').encode()
  morning=b'environment=PROD,created=2026-11-07,time=01:26Z,warning=T:Downloaded prior to 7am Europe/London\ncompany_name,bats_name\n'
  class Opener:
   def __init__(self,data):self.data=data
   def open(self,*a,**kw):return io.BytesIO(self.data)
  with tempfile.TemporaryDirectory() as tmp:
   def connect():return sqlite3.connect(tmp+'/test.db')
   with connect() as c:c.execute('CREATE TABLE hw_reference_cache(id INTEGER PRIMARY KEY,raw BLOB NOT NULL)')
   with patch('cxe_reference._cache',None):
    self.assertEqual(get_reference(now,Opener(valid),connect)['rows'][0]['isin'],'NL0010273215')
    later=now+timedelta(hours=7)
    self.assertEqual(get_reference(later,Opener(morning),connect)['rows'][0]['isin'],'NL0010273215')
    with self.assertRaisesRegex(ReferenceUnavailable,'CXE_REFERENCE_NOT_READY'):
     get_reference(now+timedelta(days=4),Opener(morning),connect)
    with connect() as c:c.execute('DELETE FROM hw_reference_cache')
    with self.assertRaisesRegex(ReferenceUnavailable,'CXE_REFERENCE_NOT_READY'):
     get_reference(later,Opener(morning),connect)
 def test_observed_cxe_rows_resolve_novo_scho_and_asml(self):
  now=datetime(2026,11,6,18,30,tzinfo=timezone.utc)
  content=('environment=PROD,created=2026-11-06,time=18:25Z,warning=\n'
           'company_name,bats_name,isin,currency,mic,reuters_exchange_code,lis_local,live,tick_type,reference_price,bats_prev_close,live_date,bloomberg_primary,bloomberg_bats,mifid_share,asset_class,corporate_action_status\n'
           'Novo Nordisk A/S,NOVOBc,DK0062498333,DKK,XCSE,CO,4854785,t,mifid_6,271.1,271.1,2008-12-05,NOVOB DC Equity,NOVOBC IX Equity,t,EQTY,\n'
           'Schouw & Co A/S,SCHOc,DK0010253921,DKK,XCSE,CO,746890,t,mifid_3,839,781,2013-10-14,SCHO DC Equity,SCHOC IX Equity,t,EQTY,\n'
           'ASML Holding NV,ASMLa,NL0010273215,EUR,XAMS,AS,650000,t,mifid_6,1244,1244,2008-11-14,ASML NA Equity,ASMLA IX Equity,t,EQTY,\n').encode()
  rows=parse_reference(content,now)['rows']
  cases=[('NOVOB','Novo Nordisk A/S','DKK','DK0062498333','NOVO-B.CO','CO'),('SCHO','Schouw & Co A/S','DKK','DK0010253921','SCHO.CO','CO'),('ASML','ASML Holding NV','EUR','NL0010273215','ASML.AS','AS')]
  for ticker,name,currency,isin,symbol,exchange in cases:
   with self.subTest(ticker=ticker):
    pluto={'asset_id':'synthetic-'+ticker,'ticker':ticker,'name':name,'exchange':'CHIX','currency':currency,'type':'CS'}
    self.assertEqual(resolve_cxe(pluto,[{'symbol':symbol,'exchange':exchange,'currency':None,'isin':isin}],rows)['symbol'],symbol)
 def test_us_catalog_distinguishes_tsm_adr_and_tesla_common(self):
  cases=[('TSM','Taiwan Semiconductor Manufacturing Company Ltd.','Taiwan Semiconductor Manufacturing','Taiwan Semiconductor Manufacturing Co Ltd','NYSE','ADRC','US8740391003','TSFAd'),('TSLA','Tesla Inc.','Tesla Inc','Tesla Inc','NASDAQ','CS','US88160R1014','TL0d')]
  for ticker,name,catalog_name,cxe_name,venue,kind,isin,cxe_symbol in cases:
   with self.subTest(ticker=ticker):
    pluto={'asset_id':'synthetic-'+ticker,'ticker':ticker,'name':name,'exchange':venue,'currency':'USD','type':kind}
    catalog={'Code':ticker,'Name':catalog_name,'Country':'USA','Exchange':venue,'Currency':'USD','Type':'Common Stock','Isin':isin}
    choice={'symbol':ticker+'.US','exchange':'US','currency':'USD','isin':isin}
    cxe={'symbol':cxe_symbol,'name':cxe_name,'isin':isin,'currency':'EUR','instrument_type':'EQTY'}
    result=resolve_us(pluto,[choice],[catalog],[cxe]);self.assertEqual(result['status'],'VERIFIED');self.assertEqual(result['pluto_type'],kind)
    self.assertEqual(resolve_us(dict(pluto,exchange='NASDAQ' if venue=='NYSE' else 'NYSE'),[choice],[catalog],[cxe])['status'],'UNVERIFIED')
    self.assertEqual(resolve_us(pluto,[dict(choice,isin='US0000000001')],[catalog],[cxe])['status'],'UNVERIFIED')
    self.assertEqual(resolve_us(pluto,[choice],[catalog],[dict(cxe,name='Other Company')])['status'],'UNVERIFIED')
    self.assertEqual(resolve_us(pluto,[choice],[catalog,catalog],[cxe])['status'],'AMBIGUOUS')
    if kind=='ADRC':self.assertIn('ADR',result['type_note'])
 def test_observed_msft_name_matches_without_erasing_share_class(self):
  pluto={'asset_id':'synthetic-msft','ticker':'MSFT','name':'Microsoft Corporation Common Stock','exchange':'NASDAQ','currency':'USD','type':'CS','isin':None}
  catalog={'Code':'MSFT','Name':'Microsoft Corporation','Country':'USA','Exchange':'NASDAQ','Currency':'USD','Type':'Common Stock','Isin':'US5949181045'}
  choice={'symbol':'MSFT.US','name':'Microsoft Corporation','exchange':'US','currency':'USD','isin':'US5949181045'}
  self.assertEqual(resolve_us(pluto,[choice],[catalog])['status'],'VERIFIED')
  self.assertEqual(resolve_us(dict(pluto,name='Microsoft Corporation Class A Common Stock'),[choice],[dict(catalog,Name='Microsoft Corporation Class B')])['status'],'UNVERIFIED')
  self.assertEqual(resolve_us(pluto,[choice],[dict(catalog,Exchange='NYSE')])['status'],'UNVERIFIED')
  self.assertEqual(resolve_us(pluto,[dict(choice,isin='US0000000001')],[catalog])['status'],'UNVERIFIED')
  self.assertEqual(resolve_us(dict(pluto,name='Microsoft Corporation Class A Common Stock'),[choice],[catalog])['status'],'VERIFIED')
  self.assertEqual(resolve_us(dict(pluto,name='Microsoft Corporation Ordinary Shares'),[choice],[catalog])['status'],'VERIFIED')
  self.assertEqual(resolve_us(dict(pluto,name='Microsoft Corporation Class A Common Stock'),[choice],[dict(catalog,Name='Microsoft Corporation Class B Common Stock')])['status'],'UNVERIFIED')
  self.assertEqual(resolve_us(dict(pluto,name='Different Corporation Class A Common Stock'),[choice],[catalog])['status'],'UNVERIFIED')
 def test_observed_fcx_names_only_match_the_specific_asset_and_listing(self):
  pluto={'asset_id':'bea4a183-d3aa-4893-8071-87b85385e281','ticker':'FCX','name':'Freeport-McMoran Inc.','exchange':'NYSE','currency':'USD','type':'CS','isin':None}
  catalog={'Code':'FCX','Name':'Freeport-McMoran Copper & Gold Inc','Country':'USA','Exchange':'NYSE','Currency':'USD','Type':'Common Stock','Isin':'US35671D8570'}
  choice={'symbol':'FCX.US','exchange':'US','currency':'USD','isin':'US35671D8570'}
  result=resolve_us(pluto,[choice],[catalog]);self.assertEqual(result['symbol'],'FCX.US');self.assertIn('Pluto oplyser ikke ISIN',result['type_note'])
  for changed in (dict(pluto,asset_id='another'),dict(pluto,exchange='NASDAQ'),dict(pluto,currency='EUR'),dict(pluto,type='ADRC'),dict(pluto,name='Freeport-McMoran Class A Common Stock')):
   self.assertNotEqual(resolve_us(changed,[choice],[catalog])['status'],'VERIFIED')
  for changed in (dict(catalog,Isin='US0000000001'),dict(catalog,Name='Freeport-McMoran Copper Inc'),dict(catalog,Exchange='NASDAQ')):
   self.assertNotEqual(resolve_us(pluto,[choice],[changed])['status'],'VERIFIED')
  self.assertEqual(resolve_us(pluto,[choice],[catalog,catalog])['status'],'AMBIGUOUS')
  self.assertNotEqual(resolve_us(pluto,[dict(choice,isin='US0000000001')],[catalog])['status'],'VERIFIED')
