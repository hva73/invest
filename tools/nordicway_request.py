"""Validate a fixed read-only diagnostics request from the project owner."""
import json,os,re
from pathlib import Path

OWNER_ID=351122234
BRANCH='refs/heads/codex/escape-development'
PREFIX='ESCAPE_SERVER_READONLY_V1 '

def parse(event,name,ref,actor_id):
 if actor_id!=str(OWNER_ID) or ref!=BRANCH or not isinstance(event,dict):return None
 sender=event.get('sender')
 if not isinstance(sender,dict) or sender.get('id')!=OWNER_ID:return None
 if name=='workflow_dispatch':
  inputs=event.get('inputs') or {}
  if not isinstance(inputs,dict):return None
  operation=inputs.get('operation','diagnostics');sha=inputs.get('sha','')
  if operation=='diagnostics' and not sha:return {'operation':'diagnostics','sha':''}
  if operation=='release_preflight' and isinstance(sha,str) and re.fullmatch(r'[0-9a-f]{40}',sha):return {'operation':operation,'sha':sha}
  return None
 if name!='issue_comment' or event.get('action')!='created':return None
 issue=event.get('issue');comment=event.get('comment')
 if not isinstance(issue,dict) or issue.get('number')!=16 or 'pull_request' in issue or not isinstance(comment,dict):return None
 author=comment.get('user')
 if not isinstance(author,dict) or author.get('id')!=OWNER_ID or comment.get('author_association')!='OWNER':return None
 body=comment.get('body')
 if not isinstance(body,str) or not body.startswith(PREFIX) or len(body)>256:return None
 try:
  def unique(pairs):
   result={}
   for key,value in pairs:
    if key in result:raise ValueError('duplicate_key')
    result[key]=value
   return result
  parsed=json.loads(body[len(PREFIX):],object_pairs_hook=unique)
  if not isinstance(parsed,dict) or not isinstance(parsed.get('request_id'),str) or not re.fullmatch(r'[0-9a-f]{32}',parsed['request_id']):return None
  if set(parsed)=={'request_id'}:return {'operation':'diagnostics','sha':''}
  if set(parsed)=={'request_id','operation','sha'} and parsed['operation']=='release_preflight' and isinstance(parsed['sha'],str) and re.fullmatch(r'[0-9a-f]{40}',parsed['sha']):return {'operation':'release_preflight','sha':parsed['sha']}
  return None
 except (ValueError,TypeError):return None

def validate(event,name,ref,actor_id):return parse(event,name,ref,actor_id) is not None

def main():
 try:
  path=Path(os.environ['GITHUB_EVENT_PATH']);raw=path.read_bytes()
  if len(raw)>1048576:raise ValueError('oversized_event')
  event=json.loads(raw)
  request=parse(event,os.environ.get('GITHUB_EVENT_NAME'),os.environ.get('GITHUB_REF'),os.environ.get('GITHUB_ACTOR_ID'))
 except (OSError,KeyError,ValueError,TypeError,AttributeError):request=None
 if request is None:raise SystemExit('Diagnostics request rejected.')
 try:
  with Path(os.environ['GITHUB_OUTPUT']).open('a',encoding='utf-8') as output:
   output.write('operation='+request['operation']+'\nsha='+request['sha']+'\n')
 except (OSError,KeyError):raise SystemExit('Diagnostics request output unavailable.') from None
 print('Fixed read-only diagnostics request accepted.')
if __name__=='__main__':main()
