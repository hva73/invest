"""Latest-known Pluto asset quotes for held assets, never a live-price claim."""
from datetime import datetime,timezone
from decimal import Decimal,localcontext
from portfolio_data import currency,number,money,date_field,field,PortfolioFormatError,shape

def advertised(tools):
    tool=next((t for t in tools if t.get('name')=='get_asset'),None)
    if not tool or tool.get('annotations',{}).get('readOnlyHint') is not True:return False
    schema=tool.get('inputSchema',{})
    return schema.get('type')=='object' and schema.get('properties',{}).get('assetId',{}).get('type')=='string' and set(schema.get('required',[])).issubset({'assetId'})

def parse(data,asset_id):
    if not isinstance(data,dict):raise PortfolioFormatError('Ukendt get_asset-svar: '+shape(data))
    metadata=data.get('asset') if isinstance(data.get('asset'),dict) else data
    for obj in [data,metadata]:
        returned=field(obj,['assetId','id'])
        if returned is not None and returned!=asset_id:raise PortfolioFormatError('Prisopslag returnerede et andet aktiv; ingen beregning udført')
    codes=[currency(obj.get('currency')) for obj in [data,metadata] if obj.get('currency') is not None]
    if len(set(codes))>1:raise PortfolioFormatError('Modstridende valuta i prisopslag')
    code=codes[0] if codes else None
    candidates=[]
    for obj in ([data] if metadata is data else [data,metadata]):
        for key in ['latestPrice','price']:
            if obj.get(key) is not None:candidates.append(obj[key])
    if not candidates:raise PortfolioFormatError('Pris mangler i get_asset; felter og typer: '+shape(data))
    if any(value!=candidates[0] for value in candidates):raise PortfolioFormatError('Modstridende priser i get_asset')
    raw=candidates[0];quote=money({'price':raw},['price'],code)
    if quote['amount'] is None or Decimal(quote['amount'])<=0:raise PortfolioFormatError('Ingen positiv, anvendelig pris i get_asset')
    if code and quote['currency']!=code:raise PortfolioFormatError('Prisens valuta stemmer ikke med aktivet')
    stamp=date_field(data,['priceAsOf','priceTimestamp','quotedAt'])
    if not stamp:stamp=date_field(metadata,['priceAsOf','priceTimestamp','quotedAt'])
    if not stamp and isinstance(raw,dict):stamp=date_field(raw,['timestamp','asOf','quotedAt'])
    return {'price':quote,'price_time':stamp,'observed':datetime.now(timezone.utc).isoformat(),'source':'Pluto get_asset · senest kendte pris'}

def calculate(row):
    price=row['price'];quantity=row['quantity'];code=row['currency']
    if quantity is None or not code or price['currency']!=code or price['amount'] is None:return
    with localcontext() as ctx:
        ctx.prec=60
        q=Decimal(quantity);p=Decimal(price['amount'])
        if q<=0 or p<=0:return
        if row['value']['amount'] is None:
            row['value']={'amount':number(q*p),'currency':code};row['value_basis']='calculated_quantity_price'
        if row.get('value_basis')=='calculated_quantity_price' and row['unrealized']['amount'] is None:
            cost=row['cost_basis']
            if cost['amount'] is not None and cost['currency']==code and Decimal(cost['amount'])>=0:
                row['unrealized']={'amount':number(Decimal(row['value']['amount'])-Decimal(cost['amount'])),'currency':code};row['unrealized_basis']='calculated_value_cost'

def enrich(client,tools,payload,decode):
    cache={};queries=0
    for index,row in enumerate(payload['positions']):
        if row['kind']!='holding':continue
        if row['price']['amount'] is None:
            aid=row.get('asset_id')
            try:
                if not aid:raise PortfolioFormatError('Aktiv-ID mangler; der søges ikke på ticker')
                if not advertised(tools):raise PortfolioFormatError('get_asset-læsekontrakten mangler')
                if aid not in cache:
                    if queries>=20:raise PortfolioFormatError('Grænse på 20 unikke prisopslag pr. opdatering nået')
                    queries+=1
                    try:cache[aid]=parse(decode(client.request('tools/call',{'name':'get_asset','arguments':{'assetId':aid}}),'get_asset'),aid)
                    except PortfolioFormatError as error:cache[aid]=error
                    except Exception:cache[aid]=PortfolioFormatError('Prisopslaget kunne ikke gennemføres')
                quote=cache[aid]
                if isinstance(quote,Exception):raise quote
                if not row['currency'] or quote['price']['currency']!=row['currency']:raise PortfolioFormatError('Prisvaluta kan ikke matches med beholdningens valuta')
                row['price']=quote['price'];row['price_time']=quote['price_time'];row['price_source']=quote['source'];row['price_observed']=quote['observed']
            except PortfolioFormatError as error:
                payload['errors'].append('Prisopslag post '+str(index+1)+': '+str(error));continue
        try:calculate(row)
        except PortfolioFormatError as error:payload['errors'].append('Beregning post '+str(index+1)+': '+str(error))
    payload['complete']=payload['complete'] and not payload['errors']
