"""Conservative cross-provider identity checks; inputs are provider metadata."""
import re

def _value(row, *keys):
 for key in keys:
  value=row.get(key)
  if isinstance(value,str) and value.strip():return value.strip()
 return None

def _norm(value):
 return re.sub(r'[^A-Z0-9]','',value.upper()) if isinstance(value,str) else None

def _issuer(value):
 import unicodedata
 if not isinstance(value,str):return None
 words=re.findall(r'[A-Z0-9]+',unicodedata.normalize('NFKD',value).upper())
 # Pluto can append the generic security type to the issuer name, while
 # EODHD puts that type in a separate field. Preserve class identifiers.
 if len(words)>=2 and words[-2:]==['COMMON','STOCK']:words=words[:-2]
 while words and words[-1] in ('INC','INCORPORATED','LTD','LIMITED','CO','COMPANY','CORP','CORPORATION','PLC'):words.pop()
 return tuple(words) if words and sum(map(len,words))>=4 else None

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
  return other==issuer and not (share_class and other_class and share_class!=other_class)
 matches=[row for row in us_rows if isinstance(row,dict) and row.get('Code')==ticker and _norm(row.get('Exchange'))==exchange and _norm(row.get('Currency'))=='USD' and _norm(row.get('Country'))=='USA' and _norm(row.get('Type'))=='COMMONSTOCK' and same_issuer(row) and isinstance(row.get('Isin'),str) and re.fullmatch('[A-Z]{2}[A-Z0-9]{9}[0-9]',row['Isin'])]
 if len(matches)!=1:return {'status':'AMBIGUOUS' if len(matches)>1 else 'UNVERIFIED','reason':'US_LISTING_NOT_UNIQUE'}
 listing=matches[0];isin=listing['Isin']
 if pluto.get('isin') and _norm(pluto['isin'])!=isin:return {'status':'UNVERIFIED','reason':'PLUTO_ISIN_CONFLICT'}
 choices=[row for row in eodhd_choices if isinstance(row,dict) and row.get('symbol')==ticker+'.US' and _norm(row.get('exchange'))=='US' and (not row.get('currency') or _norm(row['currency'])=='USD') and (not row.get('isin') or _norm(row['isin'])==isin)]
 if len(choices)!=1:return {'status':'AMBIGUOUS' if len(choices)>1 else 'UNVERIFIED','reason':'EODHD_SYMBOL_NOT_UNIQUE'}
 result={'status':'VERIFIED','symbol':ticker+'.US','isin':isin,'currency':'USD','currency_basis':'us_catalog_and_pluto','basis':'pluto_asset_us_listing','catalog_exchange':exchange,'catalog_ticker':ticker,'catalog_type':listing['Type'],'pluto_type':pluto['type'],'type_note':'Pluto angiver ADR; EODHD bruger den brede betegnelse Common Stock.' if kind=='ADRC' else 'Begge kilder angiver en almindelig aktie.'}
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
 primary_markets={'XCSE':'CO','XAMS':'AS','XETR':'XETRA','XFRA':'F','XPAR':'PA','XMIL':'MI'}
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
