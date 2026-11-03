"""Read-only position views and history over immutable report snapshots.
No candidate-derived recommendations, broker writes or inferred fills.
"""
import json
from decimal import Decimal,localcontext
from report_validation import stamp,issue


def init(c):
    c.execute('CREATE TABLE IF NOT EXISTS report_position_links(user_id INTEGER NOT NULL REFERENCES users(id),is_test INTEGER NOT NULL,portfolio_id TEXT NOT NULL,position_id TEXT NOT NULL,report_row_id INTEGER NOT NULL REFERENCES ingested_reports(id),generated REAL NOT NULL,PRIMARY KEY(user_id,is_test,portfolio_id,position_id,report_row_id))')
    c.execute('CREATE INDEX IF NOT EXISTS report_position_history ON report_position_links(user_id,is_test,portfolio_id,position_id,generated)')
    for row in c.execute('SELECT r.id,r.user_id,r.payload FROM ingested_reports r WHERE NOT EXISTS(SELECT 1 FROM report_position_links l WHERE l.report_row_id=r.id)').fetchall():
        data=json.loads(row['payload'])
        if data.get('schema_version')==2:index(c,row['user_id'],row['id'],data)


def index(c,user_id,row_id,data):
    if data.get('schema_version')!=2:return
    at=stamp(data['generated_at']).timestamp()
    for p in data['positions']:
        c.execute('INSERT OR IGNORE INTO report_position_links VALUES(?,?,?,?,?,?)',(user_id,int(data['is_test']),p['portfolio_id'],p['position_id'],row_id,at))


def key(p):return (p['portfolio_id'],p['position_id'])
def closed(p):return p.get('position_status')=='closed' or p['quantity'] is not None and Decimal(p['quantity'])==0

def same_asset(a,b):
    if a.get('asset_id') and b.get('asset_id'):return a['asset_id']==b['asset_id']
    return bool(a.get('ticker') and b.get('ticker') and a['ticker'].upper()==b['ticker'].upper())


def order_matches(p,o):
    if p['portfolio_id']!=o['portfolio_id']:return False
    if p.get('asset_id') and o.get('asset_id'):return p['asset_id']==o['asset_id']
    if p.get('candidate_id') and o.get('candidate_id'):return p['candidate_id']==o['candidate_id']
    return bool(p.get('ticker') and o.get('ticker') and p['ticker'].upper()==o['ticker'].upper())


def assessment_state(p):
    a=p.get('assessment')
    if not a:return 'DATA MANGLER'
    if a['data_quality']['status'] in ['unknown','unverified','historical']:return 'IKKE VURDERET'
    return a['action']


def semantic(data,errors,warnings,connection=None,user_id=None):
    # Called even when other fields have structural errors; never index unsafe values.
    positions=data.get('positions');positions=positions if isinstance(positions,list) else []
    sources={s['source_id']:s for s in data.get('sources',[]) if isinstance(s,dict) and isinstance(s.get('source_id'),str)} if isinstance(data.get('sources'),list) else {}
    def evidence(ids):return isinstance(ids,list) and bool(ids) and all(isinstance(x,str) and sources.get(x,{}).get('verification')=='verified' and sources.get(x,{}).get('verified_at') is not None for x in ids)
    for i,p in enumerate(positions):
        if not isinstance(p,dict):continue
        base=f'positions[{i}]';a=p.get('assessment');m=p.get('market')
        if isinstance(a,dict):
            q=a.get('data_quality')
            if isinstance(q,dict) and q.get('status')=='verified' and not evidence(a.get('source_ids')):errors.append(issue(base+'.assessment.source_ids','required_evidence','Verified position analysis requires verified sources'))
            try:
                if stamp(a['assessed_at'])>stamp(data['generated_at']):errors.append(issue(base+'.assessment.assessed_at','future_assessment','Assessment cannot be newer than its report'))
            except (KeyError,TypeError,ValueError):pass
        if isinstance(m,dict):
            if m.get('verification')=='verified' and not evidence(m.get('source_ids')):errors.append(issue(base+'.market.source_ids','required_evidence','Verified position prices require verified sources'))
            if any(m.get(x) is not None for x in ['daily_change','daily_change_percent']) and m.get('change_as_of') is None:errors.append(issue(base+'.market.change_as_of','required_evidence','Daily change requires its observation timestamp'))
            if isinstance(m.get('price'),dict) and isinstance(m.get('daily_change'),dict) and m['price'].get('currency')!=m['daily_change'].get('currency'):errors.append(issue(base+'.market.daily_change.currency','currency_mismatch','Expected the same currency as market.price'))
            try:
                delta=m.get('daily_change');pct=m.get('daily_change_percent')
                if isinstance(delta,dict) and delta.get('amount') is not None and pct is not None and Decimal(delta['amount'])*Decimal(pct)<0:errors.append(issue(base+'.market.daily_change_percent','contradictory_change','Daily change amount and percent must have the same sign'))
            except (TypeError,ArithmeticError):pass
            for field in ['price_as_of','change_as_of']:
                try:
                    if m.get(field) and stamp(m[field])>stamp(data['generated_at']):errors.append(issue(base+'.market.'+field,'future_market_data','Market observation cannot be newer than its report'))
                except (KeyError,TypeError,ValueError):pass
        if p.get('position_status')=='closed' and isinstance(p.get('quantity'),str):
            try:
                if Decimal(p['quantity'])>0:errors.append(issue(base+'.position_status','position_status_conflict','A closed position cannot have positive quantity'))
            except ArithmeticError:pass
        if connection is not None and user_id is not None and type(data.get('is_test')) is bool and isinstance(p.get('position_id'),str) and isinstance(p.get('portfolio_id'),str) and isinstance(p.get('asset_id'),str):
            old=connection.execute('SELECT r.payload FROM report_position_links l JOIN ingested_reports r ON r.id=l.report_row_id WHERE l.user_id=? AND l.is_test=? AND l.portfolio_id=? AND l.position_id=? ORDER BY l.generated DESC,l.report_row_id DESC LIMIT 1',(user_id,int(data['is_test']),p['portfolio_id'],p['position_id'])).fetchone()
            if old:
                before=next(x for x in json.loads(old['payload'])['positions'] if key(x)==key(p))
                if before.get('asset_id') and before['asset_id']!=p['asset_id']:errors.append(issue(base+'.asset_id','position_identity_conflict','Existing portfolio/position identity belongs to another asset; use a new position_id'))


def changes(main,previous,assessment_before=None):
    if not main or main['data']['schema_version']!=2 or not previous or previous['data']['schema_version']!=2:return []
    data=main['data'];old=previous['data'];before={key(p):p for p in old['positions']};after={key(p):p for p in data['positions']};events=[]
    def add(kind,p,message):events.append({'kind':kind,'portfolio_id':p['portfolio_id'],'position_id':p['position_id'],'ticker':p.get('ticker'),'message':message,'report_id':data['report_id']})
    for k,p in after.items():
        prior=before.get(k)
        if closed(p):
            if prior and not closed(prior):add('closed',p,'Position oplyst lukket; se rapportens ordre- og positionshistorik')
            continue
        if not prior or closed(prior):add('new_position',p,'Ny rapporteret beholdning; en udført købshandel er ikke automatisk dokumenteret')
        elif same_asset(p,prior):
            a=p.get('assessment');b=(assessment_before or {}).get(k,prior.get('assessment'))
            if a and not b:add('new_assessment',p,'Ny individuel vurdering: '+a['action'])
            if a and b and a['action']!=b['action']:add('assessment_changed',p,b['action']+' → '+a['action'])
            if a and b and a['risk_level']!=b['risk_level']:add('risk_changed',p,'Risikoniveau ændret: '+b['risk_level']+' → '+a['risk_level'])
            x=p.get('market');y=prior.get('market')
            if x and y and x['verification']==y['verification']=='verified' and x['price'] and y['price'] and x['price']['currency']==y['price']['currency'] and stamp(x['price_as_of'])>stamp(y['price_as_of']):
                with localcontext() as ctx:
                    ctx.prec=60;v=Decimal(y['price']['amount']);change=(Decimal(x['price']['amount'])/v-1)*100 if v>0 else None
                if change is not None and abs(change)>=5:add('price_changed',p,'Rapporteret kurs ændret '+format(change,'.2f')+' % siden sammenligningsrapporten')
    for k,p in before.items():
        if k not in after and not closed(p):add('not_reported',p,'Ikke længere med i den seneste positionsliste; et salg er ikke bekræftet')
    old_orders={o['order_id']:o for o in old['orders']}
    for o in data['orders']:
        prior=old_orders.get(o['order_id']);filled=o['filled_quantity']
        if o.get('order_type') not in ['STOP','STOP_LIMIT'] or o['lifecycle'] not in ['filled','partial'] or filled is None or Decimal(filled)<=0:continue
        if prior and prior['lifecycle']==o['lifecycle'] and prior['filled_quantity'] is not None and Decimal(prior['filled_quantity'])==Decimal(filled):continue
        p=next((p for p in data['positions'] if order_matches(p,o)),None)
        if p:add('stop_fill_reported',p,'STOP-ordre oplyst '+('delvist udført' if o['lifecycle']=='partial' else 'udført')+' · antal '+filled)
    old_candidates={c['candidate_id']:c for c in old['candidates']}
    for c in data['candidates']:
        prior=old_candidates.get(c['candidate_id'])
        if prior and c['signal']=='KØB' and prior['signal']!='KØB':events.append({'kind':'candidate_upgraded','candidate_id':c['candidate_id'],'ticker':c['ticker'],'message':prior['signal']+' → KØB','report_id':data['report_id']})
    return events


def projection(c,user_id,main,previous=None,overlay_assessments=True):
    if not main or main['data']['schema_version']!=2:return {'groups':[],'count':0,'missing':0,'changes':[],'report_id':main['data']['report_id'] if main else None}
    data=main['data'];groups={p['portfolio_id']:{'portfolio':p,'positions':[]} for p in data['portfolios']};current=[]
    cache={}
    for p in data['positions']:
        if closed(p):continue
        item={'position':p,'assessment':p.get('assessment'),'assessment_report_id':data['report_id'],'assessment_generated_at':data['generated_at'],'sources':[s for s in data['sources'] if s['source_id'] in p['source_ids']+(p.get('market') or {}).get('source_ids',[])],'assessment_sources':[s for s in data['sources'] if s['source_id'] in (p.get('assessment') or {}).get('source_ids',[])],'orders':[o for o in data['orders'] if order_matches(p,o)]}
        # Only a later deep analysis can replace the assessment of a current holding.
        deep=c.execute("SELECT r.id,r.payload FROM report_position_links l JOIN ingested_reports r ON r.id=l.report_row_id WHERE l.user_id=? AND l.is_test=? AND l.portfolio_id=? AND l.position_id=? AND r.report_type='deep_analysis' AND l.generated>=? ORDER BY l.generated DESC,r.id DESC LIMIT 1",(user_id,int(data['is_test']),p['portfolio_id'],p['position_id'],stamp(data['generated_at']).timestamp())).fetchone() if overlay_assessments else None
        if deep:
            if deep['id'] not in cache:cache[deep['id']]=json.loads(deep['payload'])
            detail=cache[deep['id']];observed=next(x for x in detail['positions'] if key(x)==key(p));a=observed.get('assessment')
            if a and same_asset(p,observed) and (not item['assessment'] or stamp(a['assessed_at'])>=stamp(item['assessment']['assessed_at'])):item.update(assessment=a,assessment_report_id=detail['report_id'],assessment_generated_at=detail['generated_at'],assessment_sources=[s for s in detail['sources'] if s['source_id'] in a['source_ids']])
        item['assessment_status']=assessment_state({'assessment':item['assessment']});groups[p['portfolio_id']]['positions'].append(item);current.append(item)
    assessment_before={}
    for p in data['positions']:
        refs=c.execute('SELECT r.payload FROM report_position_links l JOIN ingested_reports r ON r.id=l.report_row_id WHERE l.user_id=? AND l.is_test=? AND l.portfolio_id=? AND l.position_id=? AND l.generated<? ORDER BY l.generated DESC,l.report_row_id DESC LIMIT 20',(user_id,int(data['is_test']),p['portfolio_id'],p['position_id'],stamp(data['generated_at']).timestamp())).fetchall()
        for ref in refs:
            prior=next(x for x in json.loads(ref['payload'])['positions'] if key(x)==key(p))
            if prior.get('assessment') and same_asset(p,prior):assessment_before[key(p)]=prior['assessment'];break
    events=changes(main,previous,assessment_before)
    for item in current:
        original=item['position'].get('assessment');updated=item['assessment']
        if original and updated and item['assessment_report_id']!=data['report_id'] and original['action']!=updated['action']:
            events=[e for e in events if not(e.get('position_id')==item['position']['position_id'] and e.get('portfolio_id')==item['position']['portfolio_id'] and e['kind']=='assessment_changed')]
            events.append({'kind':'assessment_changed','portfolio_id':item['position']['portfolio_id'],'position_id':item['position']['position_id'],'ticker':item['position'].get('ticker'),'message':original['action']+' → '+updated['action'],'report_id':item['assessment_report_id']})
    present={key(x['position']) for x in current};past=[]
    refs=c.execute('SELECT portfolio_id,position_id,MAX(generated) AS at FROM report_position_links WHERE user_id=? AND is_test=? AND generated<=? GROUP BY portfolio_id,position_id ORDER BY at DESC LIMIT 151',(user_id,int(data['is_test']),stamp(data['generated_at']).timestamp())).fetchall()
    for ref in refs[:150]:
        k=(ref['portfolio_id'],ref['position_id'])
        if k in present:continue
        saved=c.execute('SELECT r.id,r.payload FROM report_position_links l JOIN ingested_reports r ON r.id=l.report_row_id WHERE l.user_id=? AND l.is_test=? AND l.portfolio_id=? AND l.position_id=? AND l.generated<=? ORDER BY l.generated DESC,r.id DESC LIMIT 1',(user_id,int(data['is_test']),*k,stamp(data['generated_at']).timestamp())).fetchone()
        d=json.loads(saved['payload']);p=next(p for p in d['positions'] if key(p)==k)
        past.append({'position':p,'report_id':d['report_id'],'generated_at':d['generated_at'],'status':'Lukket' if closed(p) else 'Ikke længere rapporteret'})
    return {'groups':[g for g in groups.values() if g['positions']],'past':past,'past_truncated':len(refs)>150,'count':len(current),'missing':sum(i['assessment_status'] in ['DATA MANGLER','IKKE VURDERET'] for i in current),'changes':events,'report_id':data['report_id'],'generated_at':data['generated_at'],'is_test':data['is_test']}


def history(connect,user_id,portfolio_id,position_id,is_test=False):
    with connect() as c:rows=c.execute('SELECT r.id,r.payload,r.received FROM report_position_links l JOIN ingested_reports r ON r.id=l.report_row_id WHERE l.user_id=? AND l.is_test=? AND l.portfolio_id=? AND l.position_id=? ORDER BY l.generated DESC,r.id DESC LIMIT 51',(user_id,int(is_test),portfolio_id,position_id)).fetchall()
    return {'portfolio_id':portfolio_id,'position_id':position_id,'history_truncated':len(rows)>50,'events':[{'report_id':(d:=json.loads(r['payload']))['report_id'],'generated_at':d['generated_at'],'received':r['received'],'position':next(p for p in d['positions'] if key(p)==(portfolio_id,position_id))} for r in rows[:50]]}
