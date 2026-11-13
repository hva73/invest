"""Recover one verified pre-backup failure and prepare one existing approval.

The caller must load this and the recovery/approval modules from reviewed,
commit-pinned sources. It does not deploy or restore a database.
"""
import json
import os
from pathlib import Path

import nordicway_recover_a708_prebackup as recovery
import nordicway_owner_approval as approval

ROOT=Path('/home/nordicr4')
REPO=ROOT/'escape_deploy/invest'
BRIDGE=ROOT/'.escape_deploy_bridge'
APP=ROOT/'escape_app'

def prepare(repo,bridge,app,*,recover=recovery.prepare):
    repo,bridge,app=Path(repo),Path(bridge),Path(app)
    outcome=recover(repo,bridge,app)
    if not isinstance(outcome,dict) or outcome.get('status')!='ready' or \
       outcome.get('release')!=recovery.RELEASE or outcome.get('bundle')!=recovery.BUNDLE:
        raise ValueError('recovery_unverified')
    lock=app/'var/escape-deploy.lock'
    with approval.deployment_lock(lock):
        if any(os.path.lexists(bridge/name) for name in
               ('deployment-incomplete.json','first-release-setup-incomplete.json','approval-ticket.json')):
            raise ValueError('pending_work')
        if recovery._private_file(bridge/'deploy-enabled',4)!=b'1\n': raise ValueError('gate_unavailable')
        if recovery._private_file(bridge/'approved-sha',41)!=(recovery.RELEASE+'\n').encode():
            raise ValueError('approval_changed')
        recovery._verify_bridge_modules(repo,bridge)
        key=recovery._private_file(bridge/'owner-approval-key',32)
        if len(key)!=32: raise ValueError('unsafe_key')
        proof=approval.create_proof(recovery.RELEASE,key,lifetime=approval.MAX_LIFETIME)
        response=approval.approve(bridge,lock,recovery.RELEASE,proof,already_locked=True)
        if response!={'status':'ok','operation':'approve','sha':recovery.RELEASE}:
            raise ValueError('approval_unverified')
        ticket=json.loads(recovery._private_file(bridge/'approval-ticket.json',512))
        if ticket!={'sha':recovery.RELEASE,'nonce':proof['nonce'],'expires':proof['expires']}:
            raise ValueError('ticket_unverified')
        return {'status':'prepared','release':recovery.RELEASE,'expires':proof['expires']}

def main():
    try:
        print(json.dumps(prepare(REPO,BRIDGE,APP),sort_keys=True)); return 0
    except Exception as exc:
        reason=str(exc) if isinstance(exc,ValueError) and str(exc).replace('_','').isalnum() else 'preparation_failed'
        print(json.dumps({'status':'stopped','reason':reason,
            'gate_present':os.path.lexists(BRIDGE/'deploy-enabled'),
            'recovery_present':os.path.lexists(BRIDGE/'deployment-incomplete.json'),
            'ticket_present':os.path.lexists(BRIDGE/'approval-ticket.json')},sort_keys=True))
        return 1

if __name__=='__main__': raise SystemExit(main())
