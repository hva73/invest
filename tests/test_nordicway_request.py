import copy,importlib.util,unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('nordicway_request',Path(__file__).resolve().parents[1]/'tools/nordicway_request.py')
request=importlib.util.module_from_spec(spec);spec.loader.exec_module(request)

class Request(unittest.TestCase):
 def setUp(self):
  self.event={'action':'created','sender':{'id':request.OWNER_ID},'issue':{'number':16},'comment':{'user':{'id':request.OWNER_ID},'author_association':'OWNER','body':request.PREFIX+'{"request_id":"'+'a'*32+'"}'}}
 def test_owner_fixed_issue_and_strict_body(self):
  self.assertTrue(request.validate(self.event,'issue_comment',request.BRANCH,str(request.OWNER_ID)))
  for mutation in ('other_actor','other_sender','other_author','other_issue','edited','pr','extra','command','duplicate'):
   e=copy.deepcopy(self.event);actor=str(request.OWNER_ID)
   if mutation=='other_actor':actor='3'
   if mutation=='other_sender':e['sender']['id']=3
   if mutation=='other_author':e['comment']['user']['id']=3
   if mutation=='other_issue':e['issue']['number']=4
   if mutation=='edited':e['action']='edited'
   if mutation=='pr':e['issue']['pull_request']={}
   if mutation=='extra':e['comment']['body']=request.PREFIX+'{"request_id":"'+'a'*32+'","command":"id"}'
   if mutation=='command':e['comment']['body']=request.PREFIX+'$(id)'
   if mutation=='duplicate':e['comment']['body']=request.PREFIX+'{"request_id":"'+'a'*32+'","request_id":"'+'a'*32+'"}'
   with self.subTest(mutation=mutation):self.assertFalse(request.validate(e,'issue_comment',request.BRANCH,actor))
 def test_manual_dispatch_only_owner_on_fixed_branch(self):
  e={'sender':{'id':request.OWNER_ID}}
  self.assertTrue(request.validate(e,'workflow_dispatch',request.BRANCH,str(request.OWNER_ID)))
  self.assertFalse(request.validate(e,'workflow_dispatch','refs/heads/untrusted',str(request.OWNER_ID)))
 def test_release_preflight_is_a_fixed_read_only_operation_with_exact_sha(self):
  event=copy.deepcopy(self.event);event['comment']['body']=request.PREFIX+'{"request_id":"'+'a'*32+'","operation":"release_preflight","sha":"'+'b'*40+'"}'
  result=request.parse(event,'issue_comment',request.BRANCH,str(request.OWNER_ID));self.assertEqual(result,{'operation':'release_preflight','sha':'b'*40})
  for payload in ['$(id)','b'*39,'B'*40,'b'*40+';id']:
   event['comment']['body']=request.PREFIX+__import__('json').dumps({'request_id':'a'*32,'operation':'release_preflight','sha':payload})
   self.assertIsNone(request.parse(event,'issue_comment',request.BRANCH,str(request.OWNER_ID)))
if __name__=='__main__':unittest.main()
