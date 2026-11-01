"""Read-only Pluto holdings snapshots. Preserve uncertainty and source currency."""
import json,math,time
from datetime import datetime,timezone
from decimal import Decimal,InvalidOperation
import oauth
from mcp_client import MCP,decode_result,PortfolioFormatError,shape

READ_TOOLS={'get_accounts':'portfolioId','get_positions':'portfolioId','get_portfolio_value':'portfolioId','get_collection':'collectionId'}

def init(c):
    c.execute('CREATE TABLE IF NOT EXISTS portfolio_snapshots(portfolio_id INTEGER PRIMARY KEY REFERENCES portfolios(id),user_id INTEGER NOT NULL REFERENCES users(id),observed TEXT NOT NULL,payload TEXT NOT NULL,last_error TEXT,last_attempt TEXT NOT NULL)')

def number(value):
    if value is None:return None
    if isinstance(value,bool):raise PortfolioFormatError('Ugyldigt tal i Pluto-data')
    try:
        parsed=Decimal(str(value))
        if not parsed.is_finite() or abs(parsed)>Decimal('1e30'):raise ValueError('invalid amount')
        return str(parsed)
    except (InvalidOperation,ValueError,TypeError):raise PortfolioFormatError('Ugyldigt talformat i Pluto-data')

def currency(value):
    if value is None:return None
    if not isinstance(value,str) or len(value)!=3 or not value.isascii() or not value.isalpha():raise PortfolioFormatError('Ugyldig valuta i Pluto-data')
    return value.upper()

def field(obj,names):
    values=[obj[name] for name in names if name in obj and obj[name] is not None]
    if not values:return None
    if any(value!=values[0] for value in values):raise PortfolioFormatError('Pluto returnerede modstridende beløbsfelter')
    return values[0]

def date_field(obj,names):
    value=field(obj,names)
    if value is None:return None
    try:
        stamp=datetime.fromisoformat(value.replace('Z','+00:00'))
        if stamp.tzinfo is None:raise ValueError('timezone missing')
        return stamp.isoformat()
    except (ValueError,TypeError,AttributeError):raise PortfolioFormatError('Ugyldigt eller tidszoneukendt kildetidspunkt')

def money(obj,names,default_currency=None):
    value=field(obj,names);code=default_currency
    if isinstance(value,dict):
        if value and not any(key in value for key in ['amount','value']):raise PortfolioFormatError('Ukendt beløbsstruktur; felter og typer: '+shape(value))
        explicit=currency(value.get('currency'))
        code=explicit or code;value=field(value,['amount','value'])
    return {'amount':number(value),'currency':code}

def nested_shape(data,depth=0):
    if not isinstance(data,dict):return type(data).__name__
    allowed={'holdings','positions','rows','items','data','totalCount','nextToken','nextCursor','hasMore','collection','metadata','value','amount','equity','currency','localCurrency','accountCurrency','timestamp','asOf'}
    parts=[]
    for key in sorted(allowed.intersection(data)):
        value=data[key]
        detail=nested_shape(value,depth+1) if depth<2 and isinstance(value,dict) else type(value).__name__
        parts.append(key+':'+detail)
    unknown=len(set(data)-allowed)
    if unknown:parts.append(str(unknown)+' øvrige felter (navne skjult)')
    return '{'+', '.join(parts)+'}'

def list_data(data,keys,depth=0):
    if isinstance(data,list):return data
    if isinstance(data,dict) and depth<3:
        candidates=[data[k] for k in keys if isinstance(data.get(k),(list,dict))]
        if len(candidates)==1:return list_data(candidates[0],keys,depth+1)
    raise PortfolioFormatError('Ukendt/uklart listeformat; struktur uden private værdier: '+nested_shape(data))

def complete_list(data,keys):
    node=data;counts=[]
    for _ in range(4):
        if not isinstance(node,dict):break
        if 'totalCount' in node:counts.append(node['totalCount'])
        if node.get('nextToken') or node.get('nextCursor') or node.get('hasMore') is True:
            raise PortfolioFormatError('Collection-beholdninger er delvise; ingen delvis liste vises')
        candidates=[node[k] for k in keys if isinstance(node.get(k),(list,dict))]
        if len(candidates)!=1:break
        node=candidates[0]
    records=list_data(data,keys)
    if any(isinstance(count,bool) or not isinstance(count,int) or count!=len(records) for count in counts):raise PortfolioFormatError('Collection-beholdningernes antal stemmer ikke; ingen delvis liste vises')
    return records

def normalize_value(data,default_currency=None):
    if not isinstance(data,dict):raise PortfolioFormatError('Ukendt værdisvar; felter og typer: '+shape(data))
    # A named envelope, if present, must itself be a monetary observation.
    if isinstance(data.get('portfolioValue'),dict):data=data['portfolioValue']
    if not any(k in data for k in ['totalValue','value','equity']):raise PortfolioFormatError('Ukendte værdifelter og typer: '+shape(data))
    code=currency(field(data,['currency','portfolioCurrency'])) or default_currency
    return {'value':money(data,['totalValue','value','equity'],code),'source_time':date_field(data,['asOf','recordedAt','timestamp','valuationTime']),'label':'Senest registrerede værdi — ikke livekurs'}

def normalize_accounts(data):
    records=list_data(data,['accounts','cashAccounts','items','data']);result=[]
    for item in records:
        if not isinstance(item,dict):raise PortfolioFormatError('Ugyldig kontopost')
        code=currency(item.get('currency'))
        if not any(key in item for key in ['balance','cashBalance','cash','reservedForOrders','reservedCash','reservedForOpenOrders','buyingPower','withdrawalPower']):raise PortfolioFormatError('Ukendte kontofelter og typer: '+shape(item))
        account={'currency':code,'balance':money(item,['balance','cashBalance','cash'],code),'reserved':money(item,['reservedForOrders','reservedCash','reservedForOpenOrders'],code),'withdrawal_power':money(item,['withdrawalPower'],code),'buying_power':money(item,['buyingPower'],code),'source_time':date_field(item,['asOf','balanceAsOf'])}
        if code and any(account[key]['currency'] not in (None,code) for key in ['balance','reserved','buying_power','withdrawal_power']):raise PortfolioFormatError('Kontobeløbets valuta stemmer ikke med kontoens valuta')
        if account['balance']['amount'] is None or (account['buying_power']['amount'] is None and account['withdrawal_power']['amount'] is None):
            account['diagnostic']='Kontofelter og typer (ingen private værdier): '+shape(item)
        result.append(account)
    return result

def normalize_positions(data,collection_currency=None):
    records=list_data(data,['positions','holdings','rows','items','data']);result=[]
    for item in records:
        if not isinstance(item,dict):raise PortfolioFormatError('Ugyldig beholdningspost')
        wrapper=item
        if isinstance(item.get('holding'),dict):item=item['holding']
        elif isinstance(item.get('collection'),dict):item=item['collection']
        asset=item.get('asset') if isinstance(item.get('asset'),dict) else {}
        marker=str(field(wrapper,['type','kind']) or '').lower()
        is_collection=bool(item.get('collectionId')) or marker=='collection' or isinstance(wrapper.get('collection'),dict)
        code=currency(field(item,['currency','assetCurrency'])) or currency(asset.get('currency'))
        name=field(item,['name','assetName']) or asset.get('name')
        ticker=item.get('ticker') or asset.get('ticker')
        if not isinstance(name,(str,type(None))) or not isinstance(ticker,(str,type(None))):raise PortfolioFormatError('Ugyldigt instrumentnavn')
        if name is None and ticker is None:raise PortfolioFormatError('Ukendte beholdningsfelter og typer: '+shape(item))
        price=money(item,['latestPrice','price'],code)
        result.append({'kind':'collection' if is_collection else 'holding','name':name,'ticker':ticker,'quantity':number(item.get('quantity')),'currency':code,'price':price,'price_time':date_field(item,['priceAsOf','priceTimestamp','quotedAt']),'value':money(item,['value','marketValue'],code),'cost_basis':money(item,['costBasis'],code),'average_entry':money(item,['averageEntryPrice'],code),'unrealized':money(item,['unrealisedPnL','unrealizedPnL'],code),'value_in_portfolio_currency':money(item,['valueInPortfolioCurrency'],collection_currency),'unrealized_in_portfolio_currency':money(item,['unrealisedPnLInPortfolioCurrency','unrealizedPnLInPortfolioCurrency'],collection_currency)})
    return result

def supported(tools,name):
    tool=next((tool for tool in tools if tool.get('name')==name),None)
    if not tool or tool.get('annotations',{}).get('readOnlyHint') is not True:return False
    schema=tool.get('inputSchema',{});key=READ_TOOLS.get(name)
    props=schema.get('properties',{})
    return bool(key and schema.get('type')=='object' and props.get(key,{}).get('type')=='string' and set(schema.get('required',[])).issubset({key}))

def read(connect,user_id,portfolio_id,client_factory=None):
    with connect() as c:
        owned=c.execute("SELECT * FROM portfolios WHERE id=? AND user_id=? AND source='pluto' AND active=1",(portfolio_id,user_id)).fetchone()
        token=c.execute('SELECT payload,expires FROM oauth_tokens WHERE user_id=?',(user_id,)).fetchone()
    if not owned:raise PortfolioFormatError('Porteføljen findes ikke på din aktive Pluto-liste')
    if not token or token['expires']<=time.time():raise oauth.SetupRequired('Log ind hos Pluto igen før dataopslag')
    portfolio=dict(owned);namespace,identifier=portfolio['external_id'].split(':',1)
    client=(client_factory or MCP)(oauth.unseal(user_id,token['payload'])['token']['access_token']);tools=client.tools()
    def call(name,args):
        if name not in READ_TOOLS or not supported(tools,name):raise PortfolioFormatError('Pluto annoncerer ikke den forventede læsekontrakt for '+name)
        return decode_result(client.request('tools/call',{'name':name,'arguments':args}),name)
    observed=datetime.now(timezone.utc).isoformat()
    payload={'source':'Pluto Markets','observed':observed,'kind':portfolio['kind'],'positions':[],'accounts':[],'value':None,'errors':[],'complete':False}
    if namespace=='collections':
        data=call('get_collection',{'collectionId':identifier})
        if not isinstance(data,dict):raise PortfolioFormatError('Ukendt Collection-format: '+shape(data))
        if set(data)=={'collection'} and isinstance(data['collection'],dict):data=data['collection']
        metadata=data.get('metadata') if isinstance(data.get('metadata'),dict) else (data.get('collection') if isinstance(data.get('collection'),dict) else {})
        # Pluto explicitly documents localCurrency for collection valuation,
        # accountCurrency must never be substituted for it.
        local=currency(data.get('localCurrency')) or currency(metadata.get('localCurrency'))
        payload['currency']=local
        successful=0
        try:
            value=field(data,['value','totalValue'])
            if isinstance(value,dict) and any(key in value for key in ['totalValue','equity','value']):
                payload['value']=normalize_value(value,local)
            else:
                payload['value']=normalize_value({'value':value,'currency':local,'asOf':field(data,['asOf','valuationTime'])})
            if local and payload['value']['value']['currency'] not in (None,local):raise PortfolioFormatError('Collection-værdiens valuta stemmer ikke med localCurrency')
            successful+=1
        except PortfolioFormatError as error:
            payload['value']=None;payload['errors'].append('Collection-værdi: '+str(error))
        try:
            if data.get('nextToken') or data.get('nextCursor') or data.get('hasMore') is True:raise PortfolioFormatError('Collection-svaret er ufuldstændigt')
            rows=complete_list(data,['positions','holdings','rows','items','data'])
            payload['positions']=normalize_positions(rows,local)
            payload['positions_complete']=True;successful+=1
        except PortfolioFormatError as error:payload['errors'].append('Collection-beholdninger: '+str(error))
        try:
            accounts=field(data,['cashAccounts','accounts'])
            if accounts is None:raise PortfolioFormatError('Kontofelt mangler')
            payload['accounts']=normalize_accounts(accounts);successful+=1
        except PortfolioFormatError as error:payload['errors'].append('Collection-kontanter: '+str(error))
        if not successful:raise PortfolioFormatError('Ingen Collection-sektion kunne læses. '+'; '.join(payload['errors']))
        for account in payload['accounts']:
            if account.get('diagnostic'):payload['errors'].append((account['currency'] or 'Ukendt valuta')+': '+account['diagnostic'])
        payload['complete']=not payload['errors']
    elif namespace=='portfolios':
        # Keep independently successful sections while reporting failures explicitly.
        successful=0
        for section,name in [('value','get_portfolio_value'),('accounts','get_accounts')]:
            try:
                data=call(name,{'portfolioId':identifier})
                payload[section]=normalize_value(data) if section=='value' else normalize_accounts(data)
                successful+=1
                if section=='value':payload['currency']=payload['value']['value']['currency']
            except PortfolioFormatError as error:payload['errors'].append(section+': '+str(error))
            except Exception:payload['errors'].append(section+': Pluto-opslaget fejlede; ingen gamle værdier vises som nye')
        try:
            rows=[];cursor=None;seen=set();total=None
            for _ in range(30):
                args={'portfolioId':identifier,'limit':200}
                if cursor:args['nextToken']=cursor
                page=call('get_positions',args)
                batch=list_data(page,['positions','holdings','rows','items','data']);rows.extend(batch)
                if isinstance(page,dict):
                    if page.get('hasMore') is True and not page.get('nextToken'):raise PortfolioFormatError('Ufuldstændig beholdningsliste')
                    if page.get('nextCursor'):raise PortfolioFormatError('Ukendt beholdningspagination')
                    total=page.get('totalCount',total);cursor=page.get('nextToken')
                else:cursor=None
                if not cursor:break
                if not isinstance(cursor,str) or cursor in seen:raise PortfolioFormatError('Gentaget/ugyldig beholdningspagination')
                seen.add(cursor)
            else:raise PortfolioFormatError('Beholdningslisten overstiger sidegrænsen')
            if total is not None and (isinstance(total,bool) or not isinstance(total,int) or total<0 or len(rows)>total):raise PortfolioFormatError('Beholdningslistens antal er ugyldigt')
            payload['positions']=normalize_positions(rows,payload.get('currency'))
            payload['positions_complete']=True
            successful+=1
        except PortfolioFormatError as error:payload['errors'].append('positions: '+str(error))
        except Exception:payload['errors'].append('positions: Pluto-opslaget fejlede eller kunne ikke fuldføres')
        if not successful:raise PortfolioFormatError('Ingen datasektion kunne læses. '+'; '.join(payload['errors']))
        for account in payload['accounts']:
            if account.get('diagnostic'):payload['errors'].append((account['currency'] or 'Ukendt valuta')+': '+account['diagnostic'])
        payload['complete']=not payload['errors']
    else:raise PortfolioFormatError('Ukendt Pluto-porteføljetype')
    return payload

def save(c,user_id,portfolio_id,payload):
    if not c.execute("SELECT 1 FROM portfolios WHERE id=? AND user_id=? AND source='pluto'",(portfolio_id,user_id)).fetchone():raise ValueError('invalid owner')
    c.execute('INSERT INTO portfolio_snapshots VALUES(?,?,?,?,NULL,?) ON CONFLICT(portfolio_id) DO UPDATE SET observed=excluded.observed,payload=excluded.payload,last_error=NULL,last_attempt=excluded.last_attempt WHERE excluded.observed>=portfolio_snapshots.observed',(portfolio_id,user_id,payload['observed'],json.dumps(payload),payload['observed']))

def snapshots(c,user_id):
    return {str(row['portfolio_id']):{'data':json.loads(row['payload']),'last_error':row['last_error'],'last_attempt':row['last_attempt']} for row in c.execute('SELECT * FROM portfolio_snapshots WHERE user_id=?',(user_id,))}

def summaries(portfolios,snapshots):
    # Parent portfolio valuations already contain collections. Never add children.
    groups={};roots=[p for p in portfolios if p['source']=='pluto' and p['active'] and p['kind']=='portfolio']
    missing=0
    for portfolio in roots:
        snapshot=snapshots.get(str(portfolio['id']))
        value=snapshot['data'].get('value') if snapshot else None
        amount=value.get('value') if value else None
        if not amount or amount['amount'] is None or not amount['currency'] or snapshot['last_error']:
            missing+=1;continue
        code=amount['currency'];groups[code]=groups.get(code,Decimal(0))+Decimal(amount['amount'])
    return {'by_currency':{key:str(value) for key,value in groups.items()},'missing_portfolios':missing,'portfolio_count':len(roots),'label':'Sum af senest registrerede porteføljeværdier; Collections er inkluderet via deres portefølje. Valutaer summeres hver for sig.'}

def mark_failed(c,user_id,portfolio_id,message):
    # The caller supplies only a sanitized operational message.
    at=datetime.now(timezone.utc).isoformat()
    c.execute('UPDATE portfolio_snapshots SET last_error=?,last_attempt=? WHERE portfolio_id=? AND user_id=?',(message,at,portfolio_id,user_id))
