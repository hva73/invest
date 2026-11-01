"""Read-only pending-buy observations. Never changes cash or portfolio totals."""
from portfolio_data import field,money,currency,number,PortfolioFormatError,list_data,shape

FINAL={'FILLED','COMPLETED','EXECUTED','CANCELLED','CANCELED','REJECTED','EXPIRED'}

def status_of(row):
    if not isinstance(row,dict):raise PortfolioFormatError('Ugyldig ordrestatuspost')
    lifecycle=[row.get(key) for key in ['status','state','orderStatus']]
    final=[value.upper() for value in lifecycle if isinstance(value,str) and value.upper() in FINAL]
    if final:return final[0]
    for obj in [row,row.get('holding',{}),row.get('collection',{})]:
        if isinstance(obj,dict):
            for key in ['status','state','orderStatus','type','kind']:
                value=obj.get(key)
                if isinstance(value,str) and value.upper()=='ACTIVE_BUY':return 'ACTIVE_BUY'
    value=field(row,['status','orderStatus','state'])
    return value.upper() if isinstance(value,str) else None

def active_buy(row):return isinstance(row,dict) and status_of(row)=='ACTIVE_BUY'

def normalize(row,source,active_group=False,index=0):
    if not isinstance(row,dict):raise PortfolioFormatError('Ugyldig aktiv ordrepost')
    status=status_of(row)
    side=row.get('side')
    if side is not None and not isinstance(side,str):raise PortfolioFormatError('Ugyldig ordreretning')
    side=side.upper() if side else None
    if status in FINAL:return None
    if not active_group and status!='ACTIVE_BUY':return None
    body=row.get('holding') if isinstance(row.get('holding'),dict) else row
    asset=body.get('asset') if isinstance(body.get('asset'),dict) else {}
    name=field(body,['name','assetName']) or asset.get('name');ticker=body.get('ticker') or asset.get('ticker')
    if not isinstance(name,(str,type(None))) or not isinstance(ticker,(str,type(None))):raise PortfolioFormatError('Ugyldigt ordreinstrument')
    code=currency(row.get('currency'))
    # Only explicit provider identifiers may merge observations across endpoints.
    order_id=row.get('orderId');trade_id=row.get('tradeId')
    for value in [order_id,trade_id]:
        if value is not None and (not isinstance(value,str) or not value):raise PortfolioFormatError('Ugyldig ordreference')
    key='order:'+order_id if order_id else 'trade:'+trade_id if trade_id else source+':observation:'+str(index)
    return {'key':key,'verified_id':bool(order_id or trade_id),'sources':[source],'status':status or 'ACTIVE (status ikke oplyst)','pending_buy':status=='ACTIVE_BUY' or (active_group and side=='BUY'),'side':side or ('BUY' if status=='ACTIVE_BUY' else None),'name':name,'ticker':ticker,'allocated':money(row,['allocatedAmount','reservedAmount'],currency(row.get('allocationCurrency'))),'order_amount':money(row,['orderAmount','amount'],code),'requested_quantity':number(field(body,['requestedQuantity','quantity'])),'filled_quantity':number(row.get('filledQuantity')),'collection_id':row.get('collectionId'),'portfolio_id':row.get('portfolioId')}

def from_positions(rows,source):
    return [normalize(row,source,index=index) for index,row in enumerate(rows) if active_buy(row)]

def merge(records):
    from copy import deepcopy
    records=deepcopy(records)
    result=[];known={}
    for row in records:
        if not row:continue
        if not row['verified_id'] or row['key'] not in known:
            result.append(row)
            if row['verified_id']:known[row['key']]=row
            continue
        current=known[row['key']]
        for field_name in ['allocated','order_amount','requested_quantity','filled_quantity','collection_id','portfolio_id']:
            existing=current[field_name];incoming=row[field_name]
            if isinstance(existing,dict):
                if existing['amount'] is None:current[field_name]=incoming
                elif incoming['amount'] is not None and existing!=incoming:raise PortfolioFormatError('Modstridende ordreobservationer; allokering summeres ikke')
            elif existing is None:current[field_name]=incoming
            elif incoming is not None and existing!=incoming:raise PortfolioFormatError('Modstridende ordreobservationer')
        current['sources']=sorted(set(current['sources']+row['sources']))
    return result

def allowed(tools,name,key):
    tool=next((t for t in tools if t.get('name')==name),None)
    if not tool or tool.get('annotations',{}).get('readOnlyHint') is not True:return False
    schema=tool.get('inputSchema',{});props=schema.get('properties',{})
    return schema.get('type')=='object' and props.get(key,{}).get('type')=='string' and set(schema.get('required',[])).issubset({key})

def enrich(client,tools,portfolio,payload,connect,user_id,decode):
    records=list(payload.get('pending_orders',[]));errors=[];all_complete=True
    parent=portfolio.get('parent_external_id')
    if portfolio['kind']=='portfolio':parent=portfolio['external_id']
    if parent:
        with connect() as c:owned_parent=c.execute("SELECT 1 FROM portfolios WHERE user_id=? AND source='pluto' AND external_id=? AND kind='portfolio' AND active=1",(user_id,parent)).fetchone()
        if not owned_parent:parent=None
    if parent and allowed(tools,'list_orders','portfolioId'):
        try:
            args={'portfolioId':parent.split(':',1)[1],'statusGroup':'ACTIVE','limit':50}
            if portfolio['kind']=='collection':args['scope']='COLLECTION'
            data=decode(client.request('tools/call',{'name':'list_orders','arguments':args}),'list_orders')
            rows=list_data(data,['orders','items','data']);unlinked=0
            if len(rows)>=50 and not (isinstance(data,dict) and (data.get('totalCount')==len(rows) or data.get('hasMore') is False)):
                errors.append('Ordrelisten kan være begrænset til de seneste 50 poster');all_complete=False
            if isinstance(data,dict) and (data.get('nextToken') or data.get('nextCursor') or data.get('hasMore') is True):errors.append('Ordrelisten er delvis');all_complete=False
            for index,row in enumerate(rows):
                if not isinstance(row,dict):raise PortfolioFormatError('Ugyldig ordrepost')
                if portfolio['kind']=='collection':
                    cid=row.get('collectionId')
                    if cid is None and isinstance(row.get('collection'),dict):cid=row['collection'].get('id')
                    if cid is None:unlinked+=1;continue
                    if cid!=portfolio['external_id'].split(':',1)[1]:continue
                record=normalize(row,'list_orders',True,index)
                if record:records.append(record)
            if unlinked:errors.append('Nogle Collection-ordrer mangler entydig Collection-tilknytning og vises ikke her');all_complete=False
        except PortfolioFormatError as error:errors.append('Aktive ordrer: '+str(error));all_complete=False
        except Exception:errors.append('Aktive ordrer kunne ikke læses');all_complete=False
    else:errors.append('Aktive ordrer er ikke fuldt kontrolleret: læseværktøj eller entydig porteføljetilknytning mangler');all_complete=False
    if portfolio['kind']=='collection':
        if allowed(tools,'get_collection_activity','collectionId'):
            try:
                cursor=None;seen=set()
                for page in range(20):
                    args={'collectionId':portfolio['external_id'].split(':',1)[1],'limit':100}
                    if cursor:args['nextToken']=cursor
                    data=decode(client.request('tools/call',{'name':'get_collection_activity','arguments':args}),'get_collection_activity')
                    rows=list_data(data,['activity','activities','trades','items','data'])
                    for index,row in enumerate(rows):
                        record=normalize(row,'get_collection_activity',False,page*100+index)
                        if record:records.append(record)
                    cursor=data.get('nextToken') if isinstance(data,dict) else None
                    if isinstance(data,dict) and (data.get('nextCursor') or (data.get('hasMore') is True and not cursor)):raise PortfolioFormatError('Ukendt aktivitets-pagination')
                    if not cursor:break
                    if not isinstance(cursor,str) or cursor in seen:raise PortfolioFormatError('Ugyldig aktivitets-pagination')
                    seen.add(cursor)
                else:raise PortfolioFormatError('Aktivitetslisten overstiger sidegrænsen')
            except PortfolioFormatError as error:errors.append('Collection-aktivitet: '+str(error));all_complete=False
            except Exception:errors.append('Collection-aktivitet kunne ikke læses');all_complete=False
        else:errors.append('Collection-aktivitet er ikke kontrolleret: læseværktøj mangler');all_complete=False
    try:records=merge(records)
    except PortfolioFormatError as error:
        records=payload.get('pending_orders',[]);errors.append(str(error));all_complete=False
    payload['pending_orders']=records;payload['order_errors']=errors;payload['orders_complete']=all_complete
    payload['reservation_note']='reservedForOrders vises én gang pr. konto. Ordrebeløb og ACTIVE_BUY-poster lægges ikke oveni reservationen og trækkes ikke fra saldoen igen. Afstemning af dækning mellem ordrer og reservationer er endnu ikke verificeret; frit investerbart beløb beregnes ikke.'
