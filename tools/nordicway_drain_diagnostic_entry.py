"""Explicit, state-bound pre-backup drain diagnostic. Never deploys a release.

This executable must be loaded from reviewed, commit-pinned source alongside
the reviewed recovery, coordinator and classification modules. It briefly
stops the app and motor, observes only aggregate process properties and then
attempts to restart and verify the original runtime. A hard crash can leave
the original recovery marker and require operator intervention.
"""
import json
import os
import sys
from pathlib import Path

import nordicway_recover_a708_prebackup as recovery
import nordicway_drain_diagnostic as coordinator
import nordicway_passenger_classification as classification

ROOT=Path('/home/nordicr4')
REPO=ROOT/'escape_deploy/invest'
BRIDGE=ROOT/'.escape_deploy_bridge'
APP=ROOT/'escape_app'

def validate():
    expected={'format':1,'sha':recovery.RELEASE,'state':'started',
              'motor_enabled':True,'motor_disabled':False}
    if recovery._private_file(BRIDGE/'approved-sha')!=(recovery.RELEASE+'\n').encode():
        raise ValueError('approval_changed')
    if recovery._private_file(BRIDGE/'deploy-enabled')!=b'1\n':
        raise ValueError('gate_changed')
    if any(os.path.lexists(BRIDGE/name) for name in ('first-release-setup-incomplete.json','approval-ticket.json')):
        raise ValueError('pending_work')
    record=json.loads(recovery._private_file(BRIDGE/'deployment-incomplete.json',1024))
    if record!=expected or type(record.get('format')) is not int or \
       type(record.get('motor_enabled')) is not bool or type(record.get('motor_disabled')) is not bool:
        raise ValueError('unexpected_recovery')
    recovery._verify_bridge_modules(REPO,BRIDGE)
    recovery._verify_files(REPO,APP)
    recovery._verify_runtime(APP,BRIDGE)
    return True

def main():
    # Check code before importing executable bridge modules; repeat all state
    # checks while holding the adapter's existing deployment lock.
    recovery._verify_bridge_modules(REPO,BRIDGE)
    sys.path.insert(0,str(BRIDGE))
    import nordicway_deploy_adapter
    import nordicway_quiescence
    import nordicway_writer_check
    adapter=nordicway_deploy_adapter.Adapter(REPO,APP,recovery.RELEASE,1,None,None)
    result=coordinator.diagnose(adapter,validate,nordicway_quiescence.stopped_motor,
        nordicway_writer_check.wait_for_quiescence,classification.classify)
    print(json.dumps(result,sort_keys=True))
    return 0 if result.get('status')=='observed' and result.get('health_verified') is True else 1

if __name__=='__main__':
    try: raise SystemExit(main())
    except Exception:
        print(json.dumps({'status':'validation_unavailable'})); raise SystemExit(1) from None
