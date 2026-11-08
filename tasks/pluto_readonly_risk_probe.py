"""Read-only Pluto estimate/intent schema probe. Never submits an order.

Run on the application server, where the authenticated Pluto connection lives.
The output intentionally contains no portfolio IDs, amounts or order IDs.
"""
import argparse,json,re,sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app,trade_service

class ProbeError(Exception):pass

def shape(value,depth=0):
 if depth>8:return 'dybdegrænse'
 if isinstance(value,dict):
  allowed={'orders','items','data','holding','asset','amount','value','currency','priceCurrency','orderCurrency','commissionCurrency','feeCurrency','base','quote','rate','commission','notional','accountNotional','filledAccountNotional','assetBankFx','orderId','status','filledQuantity','requestedQuantity','averageFillPrice','statusChangedAt','updatedAt','side','assetId'}
  codes={'currency','priceCurrency','orderCurrency','commissionCurrency','feeCurrency','base','quote'}
  result={str(k):(v if k in codes and isinstance(v,str) and re.fullmatch('[A-Z]{3}',v) else shape(v,depth+1)) for k,v in value.items() if k in allowed}
  # Pluto may wrap the estimate in differently named objects. Search inside
  # them without printing unrecognised names or any of their scalar values.
  nested=[shape(v,depth+1) for k,v in value.items() if k not in allowed and isinstance(v,(dict,list))]
  nested=[v for v in nested if v not in ({},[])]
  if nested:result['_skjulte_omslag']=nested[:20]
  unknown=[type(v).__name__ for k,v in value.items() if k not in allowed and not isinstance(v,(dict,list))]
  if unknown:result['_ovrige_felter_typer']=sorted(set(unknown))
  return result
 if isinstance(value,list):return [shape(value[0],depth+1)] if value else []
 return type(value).__name__

def run(username,ticker):
 with app.connect() as c:
  user=c.execute('SELECT id FROM users WHERE username=? AND active=1',(username,)).fetchone()
  if not user:raise ProbeError('Brugeren blev ikke fundet')
  uid=user['id'];matches=[]
  rows=c.execute("SELECT p.*,s.payload FROM portfolios p JOIN portfolio_snapshots s ON s.portfolio_id=p.id AND s.user_id=p.user_id WHERE p.user_id=? AND p.source='pluto' AND p.kind='portfolio' AND p.active=1 AND s.last_error IS NULL",(uid,)).fetchall()
  for row in rows:
   data=json.loads(row['payload'])
   if not data.get('positions_complete'):continue
   assets={p.get('asset_id') for p in data.get('positions',[]) if str(p.get('ticker') or '').casefold()==ticker.casefold() and p.get('asset_id')}
   for asset in assets:matches.append((row,asset))
 if len(matches)!=1:raise ProbeError('Værdipapiret skal findes entydigt i ét aktivt hoveddepot med komplet Pluto-snapshot')
 portfolio,asset=matches[0];order={'assetId':asset,'side':'BUY','currency':'DKK','orderType':'MARKET','timeInForce':'DAY','extendedHours':False,'amount':'20'}
 payload={'portfolioId':portfolio['external_id'].split(':',1)[1],'orders':[order]}
 estimate,_=trade_service.read_estimate(app.connect,uid,dict(portfolio),payload,'direct',allow_insufficient=True)
 client,tools=trade_service.client(app.connect,uid)
 history=trade_service.call(client,tools,'list_orders',{'portfolioId':payload['portfolioId'],'statusGroup':'INACTIVE','scope':'DIRECT','limit':50})
 quote=estimate.get('quote') or {}
 print(json.dumps({'estimate_order':shape(quote),'list_orders':shape(history),'note':'Kun feltnavne, typer og valutakoder. Ingen ordre eller forslag er oprettet.'},ensure_ascii=False,indent=2))

if __name__=='__main__':
 parser=argparse.ArgumentParser(description='Læs Plutos ordreestimat og ordreformat uden at sende en ordre.')
 parser.add_argument('--user',default='owner');parser.add_argument('--ticker',default='PEPE')
 args=parser.parse_args()
 try:run(args.user,args.ticker)
 except ProbeError as error:print('Kontrollen kunne ikke gennemføres:',str(error));sys.exit(1)
 except Exception as error:print('Kontrollen kunne ikke gennemføres:',type(error).__name__);sys.exit(1)
