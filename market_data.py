"""Read-only candidate quotes and observed chart points from Pluto get_asset."""
import json,time
from datetime import datetime,timezone
from decimal import Decimal,InvalidOperation
from zoneinfo import ZoneInfo
import oauth,report_ingest,trade_service
from asset_quotes import parse as parse_quote

COPENHAGEN=ZoneInfo('Europe/Copenhagen')
class MarketError(ValueError):pass

def init(c):
    c.execute('CREATE TABLE IF NOT EXISTS market_asset_links(user_id INTEGER NOT NULL REFERENCES users(id),candidate_id TEXT NOT NULL,expected_ticker TEXT NOT NULL,asset_id TEXT NOT NULL,PRIMARY KEY(user_id,candidate_id))')
    c.execute('CREATE TABLE IF NOT EXISTS market_asset_cache(user_id INTEGER NOT NULL REFERENCES users(id),asset_id TEXT NOT NULL,payload TEXT,fetched REAL,attempted REAL NOT NULL,last_error TEXT,PRIMARY KEY(user_id,asset_id))')
    c.execute('CREATE TABLE IF NOT EXISTS market_asset_period_cache(user_id INTEGER NOT NULL REFERENCES users(id),asset_id TEXT NOT NULL,period TEXT NOT NULL,payload TEXT,fetched REAL,attempted REAL NOT NULL,last_error TEXT,PRIMARY KEY(user_id,asset_id,period))')

def decimal(value,positive=False):
    if value is None:return None
    if isinstance(value,bool):raise MarketError('Ugyldigt tal i Plutos kursdata.')
    try:
        n=Decimal(str(value))
        if not n.is_finite() or abs(n)>Decimal('1e30') or positive and n<=0:raise ValueError()
        return format(n.normalize(),'f')
    except (InvalidOperation,ValueError,TypeError):raise MarketError('Ugyldigt tal i Plutos kursdata.')

def stamp(value):
    if not isinstance(value,str):raise MarketError('Kurshistorikken mangler et tidsstempel med tidszone.')
    try:
        dt=datetime.fromisoformat(value.replace('Z','+00:00'))
        if dt.tzinfo is None:raise ValueError()
        return dt.astimezone(timezone.utc)
    except ValueError:raise MarketError('Kurshistorikken indeholder et ukendt tidspunkt.')

def normalized(raw,asset_id,now=None,expected_period='ONE_WEEK'):
    now=now or datetime.now(timezone.utc)
    if not isinstance(raw,dict) or not isinstance(raw.get('asset'),dict):raise MarketError('Ukendt Pluto-aktivformat. Ingen kurser gættes.')
    asset=raw['asset']
    if asset.get('id')!=asset_id:raise MarketError('Kursopslaget returnerede et andet aktiv.')
    quote=parse_quote(raw,asset_id)
    if quote['price_time'] and stamp(quote['price_time'])>now:raise MarketError('Plutos kurstid ligger i fremtiden.')
    price=raw.get('price',{})
    if not isinstance(price,dict):raise MarketError('Ukendt Pluto-kursformat.')
    change=decimal(price.get('dailyChange'));pct=decimal(price.get('dailyChangePercent'));change_note=None
    if change is not None and pct is not None and Decimal(change)*Decimal(pct)<0:
        change=None;pct=None;change_note='Modstridende dagsændringer fra Pluto vises ikke.'
    result={'asset_id':asset_id,'name':asset.get('name') if isinstance(asset.get('name'),str) else asset_id,'ticker':asset.get('ticker') if isinstance(asset.get('ticker'),str) else None,'exchange':asset.get('exchange') if isinstance(asset.get('exchange'),str) else None,'currency':quote['price']['currency'],'price':quote['price']['amount'],'price_time':stamp(quote['price_time']).isoformat(timespec='milliseconds') if quote['price_time'] else None,'daily_change':change,'daily_change_percent':pct,'daily_note':change_note,'previous_close':None,'daily_comparison':None,'fetched_at':now.isoformat(timespec='milliseconds'),'source':'Pluto Markets · get_asset','asset_type':asset.get('type') if isinstance(asset.get('type'),str) else None,'display_timezone':'Europe/Copenhagen','series':[],'series_error':None,'week_change_percent':None}
    isin=asset.get('isin')
    if isinstance(isin,str):
        import re
        if re.fullmatch(r'[A-Z]{2}[A-Z0-9]{9}[0-9]',isin):result['isin']=isin
    performance=raw.get('performance')
    if not isinstance(performance,dict) or not isinstance(performance.get('series'),list):
        result['series_error']='Pluto har ikke leveret en kurshistorik.';return result
    try:
        if performance.get('period')!=expected_period:raise MarketError('Den returnerede grafperiode er ikke den anmodede periode.')
        if not result['currency'] or performance.get('currency')!=result['currency']:raise MarketError('Grafens valuta kan ikke matches til aktivets valuta.')
        lower=stamp(performance.get('from'));upper=stamp(performance.get('to'))
        if lower>upper:raise MarketError('Grafens tidsinterval er ugyldigt.')
        points=performance['series']
        if len(points)>10000:raise MarketError('Kurshistorikken overstiger visningens punktgrænse.')
        by_time={}
        for p in points:
            if not isinstance(p,dict):raise MarketError('Ukendt kurspunkt i historikken.')
            at=stamp(p.get('timestamp'));value=decimal(p.get('close'),positive=True)
            if value is None:raise MarketError('Kurspunktet mangler sin pris.')
            if at<lower or at>upper:raise MarketError('Et kurspunkt ligger uden for Plutos oplyste tidsinterval.')
            if at.timestamp()>now.timestamp()+60:raise MarketError('Kurshistorikken indeholder fremtidige punkter.')
            key=at.isoformat(timespec='milliseconds').replace('+00:00','Z')
            if key in by_time and by_time[key]['price']!=value:raise MarketError('Samme tidspunkt har modstridende kurser.')
            by_time[key]={'timestamp':key,'source_timestamp':p['timestamp'],'epoch':at.timestamp(),'price':value,'date':at.astimezone(COPENHAGEN).date().isoformat()}
        result['series']=sorted(by_time.values(),key=lambda p:p['epoch'])
        result['week_change_percent']=decimal(performance.get('returnPct')) if expected_period=='ONE_WEEK' else None
        result['series_period']=expected_period
    except MarketError as error:result['series']=[];result['series_error']=str(error)
    return result

def candidate(connect,user_id,data):
    if type(data.get('is_test',False)) is not bool:raise MarketError('Ukendt rapportkategori.')
    result=report_ingest.item(connect,user_id,str(data.get('report_id','')),data.get('is_test',False),include_views=False)
    report=result['report']
    if not report or report['data']['schema_version']!=2:raise MarketError('Vælg en kandidat fra en tilgængelig v2-rapport.')
    if data.get('position_id') is not None:
        p=next((p for p in report['data']['positions'] if p['position_id']==data.get('position_id') and p['portfolio_id']==data.get('portfolio_id')),None)
        if not p:raise MarketError('Positionen findes ikke i din rapport og portefølje.')
        if data.get('candidate_id'):raise MarketError('Vælg enten position eller kandidat.')
        return {'candidate_id':'@position/'+json.dumps([data.get('is_test',False),p['portfolio_id'],p['position_id']],separators=(',',':')),'ticker':p.get('ticker') or p.get('asset_id') or '', 'asset_id':p.get('asset_id')}
    c=next((c for c in report['data']['candidates'] if c['candidate_id']==data.get('candidate_id')),None)
    if not c:raise MarketError('Kandidaten findes ikke i din rapport.')
    return c

def choices(raw):
    if isinstance(raw,list):rows=raw
    elif isinstance(raw,dict):
        arrays=[raw[k] for k in ['assets','results','items'] if isinstance(raw.get(k),list)];rows=arrays[0] if len(arrays)==1 else []
    else:rows=[]
    result=[];seen=set()
    for item in rows:
        if not isinstance(item,dict):continue
        ids=[item[k] for k in ['id','assetId'] if isinstance(item.get(k),str) and item[k]]
        if not ids or len(set(ids))!=1 or ids[0] in seen:continue
        seen.add(ids[0]);result.append({'asset_id':ids[0],'name':str(item.get('name') or item.get('ticker') or ids[0]),'ticker':str(item.get('ticker') or ''),'exchange':str(item.get('exchange') or ''),'currency':str(item.get('currency') or ''),'isin':str(item.get('isin') or '')})
    return result

def holding_candidate(connect,user_id,data):
    """Resolve only an asset in this user's own active Pluto snapshot."""
    pid=data.get('holding_portfolio_id');aid=data.get('holding_asset_id')
    if type(pid) is not int or not isinstance(aid,str) or not 1<=len(aid)<=200:
        raise MarketError('Beholdningen mangler et gyldigt aktiv eller depot.')
    with connect() as db:
        row=db.execute("SELECT s.payload FROM portfolios p JOIN portfolio_snapshots s ON s.portfolio_id=p.id AND s.user_id=p.user_id WHERE p.id=? AND p.user_id=? AND p.source='pluto' AND p.active=1",(pid,user_id)).fetchone()
        if not row:raise MarketError('Beholdningen findes ikke i et aktivt Pluto-depot.')
        snapshot=json.loads(row['payload'])
        if not snapshot.get('positions_complete'):
            old=db.execute('SELECT payload FROM display_holdings_cache WHERE user_id=? AND portfolio_id=?',(user_id,pid)).fetchone()
            if old:snapshot=json.loads(old['payload'])
        matches=[x for x in snapshot.get('positions',[]) if x.get('kind')=='holding' and x.get('asset_id')==aid]
    if not matches:raise MarketError('Aktivet findes ikke i depotets gemte beholdninger.')
    if data.get('choose') is True or data.get('asset_id') not in (None,aid):raise MarketError('Kursgrafen skal bruge beholdningens Pluto-aktiv.')
    return {'candidate_id':f'holding:{pid}:{aid}','ticker':matches[0].get('ticker') or '', 'company_name':matches[0].get('name') or '', 'asset_id':aid}

def quote(connect,user_id,data,factory=None):
    requested_period=data.get('period','ONE_WEEK')
    if requested_period not in ('ONE_WEEK','ONE_MONTH','ONE_YEAR'):raise MarketError('Ukendt grafperiode.')
    c=holding_candidate(connect,user_id,data) if 'holding_portfolio_id' in data else candidate(connect,user_id,data);ticker=c['ticker'].strip().upper();selected=data.get('asset_id')
    if selected is not None and (not isinstance(selected,str) or not 1<=len(selected)<=200):raise MarketError('Vælg et gyldigt aktiv fra Pluto-søgningen.')
    with connect() as db:link=db.execute('SELECT * FROM market_asset_links WHERE user_id=? AND candidate_id=?',(user_id,c['candidate_id'])).fetchone()
    aid=link['asset_id'] if link and link['expected_ticker']==ticker and not selected and data.get('choose') is not True else None
    if c.get('asset_id'):
        if data.get('choose') is True or selected and selected!=c['asset_id']:raise MarketError('Aktivet er fastlagt med asset_id i positionsrapporten. Ret rapporten ved en forkert aktividentitet.')
        aid=c['asset_id']
    if not ticker and not aid:raise MarketError('Positionen mangler asset_id og ticker til kursopslag.')
    cl=None;tools=None
    if not aid:
        cl,tools=trade_service.client(connect,user_id,factory)
        options=choices(trade_service.call(cl,tools,'search_assets',{'query':c['ticker'],'assetType':'ALL','limit':10}))
        if not options:raise MarketError('Ingen genkendelige aktivfund hos Pluto.')
        if data.get('choose') is True and not selected:return {'selection_required':True,'choices':options,'candidate_ticker':c['ticker']}
        if selected:
            match=next((r for r in options if r['asset_id']==selected),None)
            if not match:raise MarketError('Aktivet findes ikke i den aktuelle Pluto-søgning.')
        else:
            exact=[r for r in options if r['ticker'].strip().upper()==ticker]
            match=exact[0] if len(exact)==1 else None
            if not match:
                if not options:raise MarketError('Ingen genkendelige aktivfund hos Pluto.')
                return {'selection_required':True,'choices':options,'candidate_ticker':c['ticker']}
        aid=match['asset_id']
    period_cache=requested_period!='ONE_WEEK'
    table='market_asset_period_cache' if period_cache else 'market_asset_cache'
    where='user_id=? AND asset_id=? AND period=?' if period_cache else 'user_id=? AND asset_id=?'
    cache_key=(user_id,aid,requested_period) if period_cache else (user_id,aid)
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        cached=db.execute('SELECT * FROM '+table+' WHERE '+where,cache_key).fetchone()
        wait=30 if data.get('refresh') is True else 300
        if cached and cached['attempted']>time.time()-wait:
            if cached['payload']:
                response=json.loads(cached['payload']);response['cached']=True;response['last_error']=cached['last_error'];db.execute('INSERT INTO market_asset_links VALUES(?,?,?,?) ON CONFLICT(user_id,candidate_id) DO UPDATE SET expected_ticker=excluded.expected_ticker,asset_id=excluded.asset_id',(user_id,c['candidate_id'],ticker,aid));return response
            if not cached['last_error'] and cached['attempted']>time.time()-30:return {'pending':True,'retry_after':2}
            raise MarketError(cached['last_error'] or 'Kursopslaget er allerede i gang. Prøv igen om lidt.')
        if period_cache:db.execute('INSERT INTO market_asset_period_cache(user_id,asset_id,period,attempted) VALUES(?,?,?,?) ON CONFLICT(user_id,asset_id,period) DO UPDATE SET attempted=excluded.attempted',(*cache_key,time.time()))
        else:db.execute('INSERT INTO market_asset_cache(user_id,asset_id,attempted) VALUES(?,?,?) ON CONFLICT(user_id,asset_id) DO UPDATE SET attempted=excluded.attempted',(user_id,aid,time.time()))
    try:
        if cl is None:cl,tools=trade_service.client(connect,user_id,factory)
        raw=trade_service.call(cl,tools,'get_asset',{'assetId':aid,'period':requested_period})
        result=normalized(raw,aid,expected_period=requested_period)
        with connect() as db:
            db.execute('INSERT INTO market_asset_links VALUES(?,?,?,?) ON CONFLICT(user_id,candidate_id) DO UPDATE SET expected_ticker=excluded.expected_ticker,asset_id=excluded.asset_id',(user_id,c['candidate_id'],ticker,aid))
            db.execute('UPDATE '+table+' SET payload=?,fetched=?,last_error=NULL WHERE '+where,(json.dumps(result),time.time(),*cache_key))
        return result
    except Exception as error:
        # A local budget denial is not a failed Pluto response. Preserve the
        # typed error and do not cache it as an outage for the next five minutes.
        from hotwatch_contract import EngineError
        if isinstance(error, EngineError) and error.code == 'PROVIDER_RATE_BUDGET':
            with connect() as db:
                db.execute('UPDATE '+table+' SET attempted=?,last_error=? WHERE '+where,
                           (cached['attempted'] if cached else 0, cached['last_error'] if cached else None, *cache_key))
            raise
        message='Pluto-kursopslaget fejlede. Tidligere data kan være forældede.'
        with connect() as db:db.execute('UPDATE '+table+' SET last_error=? WHERE '+where,(message,*cache_key))
        if cached and cached['payload']:
            response=json.loads(cached['payload']);response['cached']=True;response['last_error']=message;return response
        raise MarketError(message)
