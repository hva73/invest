"""Federated read-only timeline. Critical unresolved evidence is never expired by age."""
import json,math
from datetime import datetime,timezone
import display_policy as policy
SOURCES={'Pluto','Trading Radar','HOT WATCH Engine','App/system'}

def read(connect,uid,now=None,days=7,source='all',kind='all',before=None,limit=100):
 now=now or datetime.now(timezone.utc)
 if days not in [1,7,30,36500] or source not in SOURCES|{'all'} or kind not in ['all','order','analysis','risk','system'] or type(limit) is not int or not 1<=limit<=200:raise ValueError('Invalid journal filter')
 events=[];truncated=False
 def add(key,at,origin,typ,title,details=None,severity='info',resolved=False):
  if not policy.stamp(at):return
  events.append({'id':key,'timestamp':at,'source':origin,'kind':typ,'title':title,'details':details,'severity':severity,'resolved':resolved})
 with connect() as c:
  for r in c.execute('SELECT id,report_id,payload FROM ingested_reports WHERE user_id=? AND is_test=0 ORDER BY generated_epoch DESC LIMIT 1000',(uid,)):
   d=json.loads(r['payload'])
   for entry in d.get('journal',[]):add('report:'+str(r['id'])+':'+entry['entry_id'],entry.get('occurred_at') or d['generated_at'],'Trading Radar','analysis',entry['text'],{'report_id':r['report_id'],'reported':True})
  for r in c.execute('SELECT * FROM candidate_execution_events WHERE user_id=? AND is_test=0 ORDER BY id DESC LIMIT 2000',(uid,)):
   if r['verification']!='pluto':continue
   payload=json.loads(r['payload']);status_time=payload.get('status_time');known=bool(policy.stamp(status_time));payload['time_basis']='provider_status_time' if known else 'observed_not_execution';payload['observed_at']=r['occurred_at']
   add('execution:'+str(r['id']),status_time if known else r['occurred_at'],'Pluto','order',r['status'] if known else 'Observeret ordrestatus: '+r['status'],payload)
  for r in c.execute('SELECT * FROM candidate_lifecycle_events WHERE user_id=? AND is_test=0 ORDER BY id DESC LIMIT 2000',(uid,)):
   add('lifecycle:'+str(r['id']),r['occurred_at'],'Pluto' if r['evidence'] in ['pluto','pluto_snapshot'] else 'Trading Radar','analysis',r['status'],{'candidate_id':r['candidate_id'],'reason':r['reason'],'origin':r['origin'],'evidence':r['evidence']})
  for r in c.execute("SELECT e.* FROM hw_events e JOIN hw_sessions s ON s.id=e.watch_row_id WHERE s.user_id=? AND s.is_test=0 AND (e.severity='critical' OR e.created>=?) ORDER BY e.id DESC",(uid,(now.replace(tzinfo=timezone.utc)).isoformat()[:10] if days==1 else '0000')):
   add('engine:'+str(r['id']),r['created'],'HOT WATCH Engine','risk' if r['severity'] in ['critical','warning'] else 'system',r['event_type'],json.loads(r['payload']),r['severity'])
  for r in c.execute('SELECT j.* FROM journal j JOIN proposals p ON p.id=j.proposal_id WHERE p.user_id=? ORDER BY j.id DESC LIMIT 2000',(uid,)):
   add('app:'+str(r['id']),r['created'],'App/system','system',r['event'],{'proposal_id':r['proposal_id']})
  for r in c.execute('SELECT id,status,created,report_id,response,error FROM broker_proposals WHERE user_id=? ORDER BY id DESC LIMIT 1000',(uid,)):
   try:response=json.loads(r['response']) if r['response'] else {};provider_status=response.get('status') if isinstance(response,dict) else None
   except (ValueError,TypeError):provider_status=None
   title={'accepted':'Godkendt i Pluto · udførelse ikke bekræftet','waiting':'Afventer godkendelse i Pluto','declined':'Afvist i Pluto','cancelled':'Annulleret forslag i Pluto','expired':'Udløbet forslag i Pluto'}.get(str(provider_status).lower(),r['status'])
   add('proposal:'+str(r['id']),datetime.fromtimestamp(r['created'],timezone.utc).isoformat(),'App/system','order',title,{'report_id':r['report_id'],'provider_status':provider_status,'error':r['error'],'proposal_not_fill':True})
 # Different source events remain separate; never fuse a report claim into a broker fill.
 events.sort(key=lambda e:(policy.stamp(e['timestamp']),e['id']),reverse=True)
 critical=[e for e in events if e['severity']=='critical' and not e['resolved']]
 filtered=[e for e in events if policy.journal_visible(e,now,days) and (source=='all' or e['source']==source) and (kind=='all' or e['kind']==kind)]
 if before:
  try:epoch,key=before.split('|',1);bound=(float(epoch),key)
  except (ValueError,TypeError):raise ValueError('Invalid journal cursor')
  if not math.isfinite(bound[0]) or len(bound[1])>200:raise ValueError('Invalid journal cursor')
  filtered=[e for e in filtered if (policy.stamp(e['timestamp']).timestamp(),e['id'])<bound]
 page=filtered[:limit];cursor=str(policy.stamp(page[-1]['timestamp']).timestamp())+'|'+page[-1]['id'] if len(filtered)>limit and page else None
 return {'events':page,'critical':critical,'next_cursor':cursor,'days':days,'source':source,'kind':kind,'coverage_note':'Rapport- og ordrehistorik har afgrænsede kildelister; originalrapporter er bevaret. Motorens kritiske hændelser bevares synlige uden automatisk afklaring.','as_of':now.isoformat()}
