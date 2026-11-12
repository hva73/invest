"""Conservative cross-provider identity checks; inputs are provider metadata."""
import re

# Explicitly authorized by the account owner for price monitoring. The PEPE
# entry is a candidate only; ticker/name/price similarity is not token proof.
BTC_PLUTO_ASSET_ID='54368e0b-2d53-401e-bf68-1033a5b84b08'
PEPE_PLUTO_ASSET_ID='4cde5f75-df03-4abc-9063-cfc588e31c11'
CRYPTO_REFERENCES={
 BTC_PLUTO_ASSET_ID:{'ticker':'BTC','name':'Bitcoin','currency':'USD','symbol':'BTC-USD.CC','provider':'WINTERMUTE','approved':True},
 PEPE_PLUTO_ASSET_ID:{'ticker':'PEPE','name':'Pepe','currency':'USD','symbol':'PEPE24478-USD.CC','provider':None,'approved':False},
}

def crypto_reference(instrument):
 if not isinstance(instrument,dict):return None
 ref=CRYPTO_REFERENCES.get(instrument.get('asset_id'))
 if not ref or str(instrument.get('type','')).upper()!='CRYPTO':return None
 if any(str(instrument.get(key,'')).casefold()!=ref[key].casefold() for key in ('ticker','name','currency')):return None
 if ref['provider'] and str(instrument.get('exchange','')).upper()!=ref['provider']:return None
 return dict(ref)

def _value(row, *keys):
 for key in keys:
  value=row.get(key)
  if isinstance(value,str) and value.strip():return value.strip()
 return None

def _norm(value):
 return re.sub(r'[^A-Z0-9]','',value.upper()) if isinstance(value,str) else None

def same_us_class_ticker(left,right):
 """Accept only an exact ticker or dot/hyphen spelling of the same class."""
 if not isinstance(left,str) or not isinstance(right,str):return False
 left=left.upper();right=right.upper()
 if left==right:return True
 a=re.fullmatch(r'([A-Z0-9]+)[.\-]([A-Z0-9]+)',left)
 b=re.fullmatch(r'([A-Z0-9]+)[.\-]([A-Z0-9]+)',right)
 return bool(a and b and a.groups()==b.groups())

def _issuer(value):
 import unicodedata
 if not isinstance(value,str):return None
 words=re.findall(r'[A-Z0-9]+',unicodedata.normalize('NFKD',value).upper())
 # Pluto can append the generic security type to the issuer name, while
 # EODHD puts that type in a separate field. Preserve class identifiers.
 if len(words)>=2 and words[-2:]==['COMMON','STOCK']:words=words[:-2]
 while words and words[-1] in ('INC','INCORPORATED','LTD','LIMITED','CO','COMPANY','CORP','CORPORATION','PLC'):words.pop()
 # A short legal issuer (e.g. KKR) is still a name. Identity also requires
 # the unique ticker, venue, currency, instrument type and catalog ISIN.
 return tuple(words) if words else None

def _us_issuer(value):
 """Separate generic share descriptions and retain any explicit class."""
 import unicodedata
 if not isinstance(value,str):return None,None
 words=re.findall(r'[A-Z0-9]+',unicodedata.normalize('NFKD',value).upper())
 for suffix in (['COMMON','STOCK'],['COMMON','SHARES'],['ORDINARY','SHARES'],['ORDINARY','SHARE']):
  if words[-len(suffix):]==suffix:
   words=words[:-len(suffix)];break
 share_class=None
 if len(words)>=2 and words[-2]=='CLASS' and re.fullmatch(r'[A-Z0-9]{1,3}',words[-1]):
  share_class=words[-1];words=words[:-2]
 return _issuer(' '.join(words)),share_class

def resolve_us(pluto, eodhd_choices, us_rows, cxe_rows=None):
 """Verify a unique US security using the broker and exact exchange listing."""
 if not isinstance(pluto,dict) or not pluto.get('asset_id'):return {'status':'UNVERIFIED','reason':'PLUTO_ASSET_ID_MISSING'}
 ticker=pluto.get('ticker');exchange=_norm(pluto.get('exchange'));issuer,share_class=_us_issuer(pluto.get('name'));kind=_norm(pluto.get('type'))
 if not isinstance(ticker,str) or not re.fullmatch(r'[A-Z0-9.\-]{1,20}',ticker) or exchange not in ('NYSE','NASDAQ') or _norm(pluto.get('currency'))!='USD' or kind not in ('CS','ADRC') or not issuer:return {'status':'UNVERIFIED','reason':'PLUTO_METADATA_INCOMPLETE'}
 def same_issuer(row):
  other,other_class=_us_issuer(row.get('Name'))
  if other==issuer and not (share_class and other_class and share_class!=other_class):return True
  # EODHD truncates HRTX to "Heron Therapeuti". Independently checked
  # 2026-11-09: Endavu HRTX / XNAS / USD / stock / US4277461020,
  # asset f8452852-f7eb-44d6-940b-1ed7ce68636f, full Heron Therapeutics.
  # Pin the observed alias to this broker asset and security; never permit
  # arbitrary prefixes or infer a match for another share class.
  if (pluto.get('asset_id')=='da14edd7-64b5-4932-9dd5-62b4136a2387' and ticker=='HRTX' and exchange=='NASDAQ' and kind=='CS' and issuer==('HERON','THERAPEUTICS') and share_class is None and other==('HERON','THERAPEUTI') and other_class is None and row.get('Isin')=='US4277461020'):
   return any(x.get('symbol')=='HRTX.US' and x.get('isin')=='US4277461020' for x in eodhd_choices if isinstance(x,dict))
  # Independently checked 2026-11-09 via Endavu: Ferguson Enterprises,
  # FERG / XNYS / USD / stock / US31488V1070, asset
  # 21cf0d88-2b9b-466c-8acb-639bed1f663b. EODHD retains the old issuer name.
  if (pluto.get('asset_id')=='13ba8af0-fa33-442a-9610-47fe67b70f1d' and ticker=='FERG' and exchange=='NYSE' and kind=='CS' and issuer==('FERGUSON','ENTERPRISES') and share_class is None and other==('FERGUSON',) and other_class is None and row.get('Isin')=='US31488V1070'):
   return any(x.get('symbol')=='FERG.US' and x.get('isin')=='US31488V1070' for x in eodhd_choices if isinstance(x,dict))
  # Pluto says Rocket Lab Corporation, EODHD retains Rocket Lab USA.
  # Endavu independently confirmed RKLB / XNAS / USD / US7731211089.
  if (pluto.get('asset_id')=='004180fa-1876-448e-889e-04b231119149' and ticker=='RKLB' and exchange=='NASDAQ' and kind=='CS' and issuer==('ROCKET','LAB') and share_class is None and other==('ROCKET','LAB','USA') and other_class is None and row.get('Isin')=='US7731211089'):
   return any(x.get('symbol')=='RKLB.US' and x.get('isin')=='US7731211089' and x.get('exchange')=='US' and x.get('currency')=='USD' for x in eodhd_choices if isinstance(x,dict))
  # Pluto uses "The Trade Desk"; EODHD omits "The". Endavu independently
  # confirms the Class A Nasdaq security and ISIN (2026-11-10).
  if (pluto.get('asset_id')=='1f080b56-b5ac-4639-9649-904634000230' and ticker=='TTD' and exchange=='NASDAQ' and kind=='CS' and issuer==('THE','TRADE','DESK') and share_class=='A' and other==('TRADE','DESK') and other_class is None and row.get('Isin')=='US88339J1051'):
   return any(x.get('symbol')=='TTD.US' and x.get('isin')=='US88339J1051' and x.get('exchange')=='US' and x.get('currency')=='USD' for x in eodhd_choices if isinstance(x,dict))
  # These provider names were observed for this exact Pluto asset and listing.
  return bool(pluto.get('asset_id')=='bea4a183-d3aa-4893-8071-87b85385e281' and ticker=='FCX' and kind=='CS' and issuer==('FREEPORT','MCMORAN') and share_class is None and other==('FREEPORT','MCMORAN','COPPER','GOLD') and other_class is None and row.get('Isin')=='US35671D8570')
 matches=[row for row in us_rows if isinstance(row,dict) and same_us_class_ticker(row.get('Code'),ticker) and _norm(row.get('Exchange'))==exchange and _norm(row.get('Currency'))=='USD' and _norm(row.get('Country'))=='USA' and _norm(row.get('Type'))=='COMMONSTOCK' and same_issuer(row) and isinstance(row.get('Isin'),str) and re.fullmatch('[A-Z]{2}[A-Z0-9]{9}[0-9]',row['Isin'])]
 if len(matches)!=1:return {'status':'AMBIGUOUS' if len(matches)>1 else 'UNVERIFIED','reason':'US_LISTING_NOT_UNIQUE'}
 listing=matches[0];isin=listing['Isin']
 catalog_ticker=listing['Code'];alias=catalog_ticker!=ticker
 if alias:
  ticker_class=re.fullmatch(r'[A-Z0-9]+[.\-]([A-Z0-9]+)',ticker).group(1)
  catalog_class=_us_issuer(listing.get('Name'))[1]
  if (share_class and share_class!=ticker_class) or (catalog_class and catalog_class!=ticker_class):return {'status':'UNVERIFIED','reason':'SHARE_CLASS_CONFLICT'}
 if pluto.get('isin') and _norm(pluto['isin'])!=isin:return {'status':'UNVERIFIED','reason':'PLUTO_ISIN_CONFLICT'}
 choices=[row for row in eodhd_choices if isinstance(row,dict) and row.get('symbol')==catalog_ticker+'.US' and _norm(row.get('exchange'))=='US' and (not row.get('currency') or _norm(row['currency'])=='USD') and ((bool(row.get('isin')) and _norm(row['isin'])==isin) if alias else (not row.get('isin') or _norm(row['isin'])==isin))]
 if len(choices)!=1:return {'status':'AMBIGUOUS' if len(choices)>1 else 'UNVERIFIED','reason':'EODHD_SYMBOL_NOT_UNIQUE'}
 result={'status':'VERIFIED','symbol':catalog_ticker+'.US','isin':isin,'currency':'USD','currency_basis':'us_catalog_and_pluto','basis':'pluto_asset_us_listing','catalog_exchange':exchange,'catalog_ticker':catalog_ticker,'catalog_type':listing['Type'],'pluto_type':pluto['type'],'type_note':'Pluto angiver ADR; EODHD bruger den brede betegnelse Common Stock.' if kind=='ADRC' else 'Begge kilder angiver en almindelig aktie.'}
 if _us_issuer(listing.get('Name'))[0]!=issuer:
  result['type_note']=ticker+': Pluto og EODHD bruger forskellige observerede selskabsnavne; Pluto oplyser ikke ISIN.'
  if ticker=='HRTX':result['type_note']+=' EODHD-navnet er forkortet; HRTX/XNAS/USD og ISIN US4277461020 er også kontrolleret hos Endavu 2026-11-09.'
  if ticker=='FERG':result['type_note']+=' EODHD bruger Ferguson Plc; FERG/XNYS/USD og ISIN US31488V1070 er også kontrolleret hos Endavu 2026-11-09.'
  if ticker=='RKLB':result['type_note']+=' EODHD bruger Rocket Lab USA; RKLB/XNAS/USD og ISIN US7731211089 er også kontrolleret hos Endavu 2026-11-10.'
  if ticker=='TTD':result['type_note']+=' EODHD udelader The; TTD klasse A/XNAS/USD og ISIN US88339J1051 er også kontrolleret hos Endavu 2026-11-10.'
 if cxe_rows is not None:
  corroborating=[row for row in cxe_rows if isinstance(row,dict) and row.get('isin')==isin and _norm(row.get('instrument_type'))=='EQTY']
  if not corroborating or any(_issuer(row.get('name'))!=issuer for row in corroborating):return {'status':'UNVERIFIED','reason':'CXE_ISIN_NOT_CORROBORATED'}
  result.update(basis='pluto_asset_us_catalog_cxe_security_isin',cxe_symbols=sorted({row['symbol'] for row in corroborating if row.get('symbol')}),cxe_references=[{'symbol':row.get('symbol'),'primary_mic':row.get('mic'),'currency':row.get('currency')} for row in corroborating])
 return result

def resolve_cxe(pluto, eodhd_choices, reference_rows):
 """Cross-check a CHIX common share against normalized official CXE rows.

 The caller must validate the CXE source, column schema and freshness before
 supplying rows. A symbol or company name alone never identifies the share.
 """
 if not isinstance(pluto,dict) or not pluto.get('asset_id'):
  return {'status':'UNVERIFIED','reason':'PLUTO_ASSET_ID_MISSING'}
 ticker=_norm(pluto.get('ticker'));name=_norm(pluto.get('name'))
 if not ticker or not name or _norm(pluto.get('exchange'))!='CHIX' or _norm(pluto.get('type'))!='CS' or not _norm(pluto.get('currency')):
  return {'status':'UNVERIFIED','reason':'PLUTO_METADATA_INCOMPLETE'}
 candidates=[]
 for row in reference_rows:
  if not isinstance(row,dict):continue
  symbol=row.get('symbol');primary=row.get('primary_ticker');isin=row.get('isin')
  if not isinstance(symbol,str) or not isinstance(primary,str) or not isinstance(isin,str):continue
  if not re.fullmatch('[A-Z]{2}[A-Z0-9]{9}[0-9]',isin):continue
  # Primary ticker and CXE symbol are both explicit fields of the same row.
  if _norm(primary)!=ticker or not _norm(symbol).startswith(ticker) or len(_norm(symbol))!=len(ticker)+1:continue
  if _norm(row.get('name'))!=name or _norm(row.get('currency'))!=_norm(pluto.get('currency')) or _norm(row.get('instrument_type'))!='EQTY':continue
  if pluto.get('isin') and _norm(pluto['isin'])!=isin:continue
  candidates.append(row)
 if len(candidates)!=1:return {'status':'AMBIGUOUS' if len(candidates)>1 else 'UNVERIFIED','reason':'CXE_IDENTITY_NOT_UNIQUE'}
 row=candidates[0]
 # Match the actual primary market from the reference, not merely an ISIN
 # available on another venue in the same currency.
 primary_markets={'XCSE':'CO','XSTO':'ST','XOSL':'OL','XAMS':'AS','XETR':'XETRA','XFRA':'F','XPAR':'PA','XMIL':'MI'}
 market=primary_markets.get(_norm(row.get('mic')))
 if not market:return {'status':'UNVERIFIED','reason':'PRIMARY_MARKET_UNSUPPORTED'}
 matches=[x for x in eodhd_choices if isinstance(x,dict) and x.get('isin')==row['isin'] and (not x.get('currency') or _norm(x.get('currency'))==_norm(pluto['currency'])) and _norm(x.get('exchange'))==market and isinstance(x.get('symbol'),str) and x['symbol'].upper().endswith('.'+market)]
 if len(matches)!=1:return {'status':'AMBIGUOUS' if len(matches)>1 else 'UNVERIFIED','reason':'EODHD_IDENTITY_NOT_UNIQUE'}
 return {'status':'VERIFIED','symbol':matches[0]['symbol'],'isin':row['isin'],'cxe_symbol':row['symbol'],'primary_ticker':row['primary_ticker'],'primary_mic':row['mic'],'cxe_asset_class':row['instrument_type'],'currency':pluto['currency'],'currency_basis':'eodhd_and_cxe' if matches[0].get('currency') else 'cxe_primary_listing','basis':'pluto_asset_cxe_security_reference_eodhd_isin'}

def resolve_instrument(pluto, candidates):
 """Return evidence, never infer a security identity from a ticker alone."""
 if not isinstance(pluto,dict) or not pluto.get('asset_id'):
  return {'status':'UNVERIFIED','symbol':None,'reason':'PLUTO_ASSET_ID_MISSING','candidates':[]}
 outcomes=[]
 for item in candidates:
  if not isinstance(item,dict) or not isinstance(item.get('symbol'),str):continue
  matches=[];missing=[];conflicts=[]
  for field,keys in (('isin',('isin','ISIN')),('figi',('figi','FIGI')),('currency',('currency','Currency')),('share_class',('share_class','shareClass')),('instrument_type',('instrument_type','type','Type'))):
   a=_norm(_value(pluto,*keys));b=_norm(_value(item,*keys))
   if a and b:
    (matches if a==b else conflicts).append(field)
   else:missing.append(field)
  for field,keys in (('issuer',('name','Name')),('ticker',('ticker','code','Code')),('venue',('exchange','Exchange')),('mic',('mic','MIC'))):
   a=_value(pluto,*keys);b=_value(item,*keys)
   if a and b:
    (matches if _norm(a)==_norm(b) else conflicts).append(field)
   else:missing.append(field)
  # Venue, ticker and issuer names vary across venues and provider spelling.
  # They are evidence, not contradictions to a shared security identifier.
  fatal=set(conflicts)&{'isin','figi','currency','share_class','instrument_type'}
  same_id='isin' in matches or ('isin' in missing and 'figi' in matches)
  status='VERIFIED' if same_id and 'currency' in matches and not fatal else 'CONFLICT' if fatal else 'UNVERIFIED'
  outcomes.append({'symbol':item['symbol'],'status':status,'matches':matches,'missing':missing,'conflicts':conflicts})
 verified=[x for x in outcomes if x['status']=='VERIFIED']
 if len(verified)==1:return {'status':'VERIFIED','symbol':verified[0]['symbol'],'reason':None,'candidates':outcomes}
 return {'status':'AMBIGUOUS' if len(verified)>1 else 'UNVERIFIED','symbol':None,'reason':'MULTIPLE_MATCHES' if len(verified)>1 else 'INSUFFICIENT_EVIDENCE','candidates':outcomes}
