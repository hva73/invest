"""Validate a fixed read-only diagnostics request from the project owner."""
import json,os,re
from pathlib import Path

OWNER_ID=351122234
BRANCH='refs/heads/codex/escape-development'
PREFIX='ESCAPE_SERVER_READONLY_V1 '

def validate(event,name,ref,actor_id):
 if actor_id!=str(OWNER_ID) or ref!=BRANCH or not isinstance(event,dict):return False
 sender=event.get('sender')
 if not isinstance(sender,dict) or sender.get('id')!=OWNER_ID:return False
 if name=='workflow_dispatch':return True
 if name!='issue_comment' or event.get('action')!='created':return False
 issue=event.get('issue');comment=event.get('comment')
 if not isinstance(issue,dict) or issue.get('number')!=16 or 'pull_request' in issue or not isinstance(comment,dict):return False
 author=comment.get('user')
 if not isinstance(author,dict) or author.get('id')!=OWNER_ID or comment.get('author_association')!='OWNER':return False
 body=comment.get('body')
 if not isinstance(body,str) or not body.startswith(PREFIX) or len(body)>256:return False
 try:
  def unique(pairs):
   result={}
   for key,value in pairs:
    if key in result:raise ValueError('duplicate_key')
    result[key]=value
   return result
  parsed=json.loads(body[len(PREFIX):],object_pairs_hook=unique)
  return isinstance(parsed,dict) and set(parsed)=={'request_id'} and isinstance(parsed['request_id'],str) and bool(re.fullmatch(r'[0-9a-f]{32}',parsed['request_id']))
 except (ValueError,TypeError):return False

def main():
 try:
  path=Path(os.environ['GITHUB_EVENT_PATH']);raw=path.read_bytes()
  if len(raw)>1048576:raise ValueError('oversized_event')
  event=json.loads(raw)
  allowed=validate(event,os.environ.get('GITHUB_EVENT_NAME'),os.environ.get('GITHUB_REF'),os.environ.get('GITHUB_ACTOR_ID'))
 except (OSError,KeyError,ValueError,TypeError):allowed=False
 if not allowed:raise SystemExit('Diagnostics request rejected.')
 print('Fixed read-only diagnostics request accepted.')
if __name__=='__main__':main()
