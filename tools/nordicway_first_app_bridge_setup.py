"""Owner-only first setup of app approval and one release; no deploy is run.

The caller must explicitly approve the exact release and reviewed bridge SHA.
The separate existing GitHub client performs the deployment afterwards.
"""
import argparse
import fcntl
import json
import os
import re
import sys
import types
from pathlib import Path

import nordicway_prepare_first_release as base


def sync_dir(path):
    fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try: os.fsync(fd)
    finally: os.close(fd)


def claim(path, release):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w',encoding='ascii') as out:
        json.dump({'format':1,'sha':release},out,separators=(',',':'))
        out.write('\n');out.flush();os.fsync(out.fileno())
    sync_dir(path.parent)


def load_module(name, source):
    module=types.ModuleType(name)
    exec(compile(source,name,'exec'),module.__dict__)
    return module


def prepare(root, release, bridge_sha, updater_blob, release_updater, bridge_updater,
            requirements, old_modules, installer, approval, repo, *, inspect=base.no_guard_process):
    if any(not isinstance(x,str) or not re.fullmatch('[0-9a-f]{40}',x) for x in (release,bridge_sha,updater_blob)):
        raise ValueError('invalid_revision')
    root=Path(root);bridge=root/'.escape_deploy_bridge';app=root/'escape_app';var=app/'var'
    for path in (bridge,app,var):
        if path.is_symlink() or not path.is_dir(): raise ValueError('unsafe_path')
    info=bridge.stat()
    if info.st_uid!=os.getuid() or info.st_mode & 0o077: raise ValueError('unsafe_bridge')
    build=app/'BUILD_COMMIT';req=app/'requirements.txt'
    if build.is_symlink() or build.read_text().strip()!=base.INSTALLED: raise ValueError('installed_version_changed')
    if req.is_symlink() or not req.is_file() or req.read_bytes()!=requirements: raise ValueError('requirements_changed')
    if base.blob(release_updater)!=updater_blob or bridge_updater!=release_updater: raise ValueError('candidate_mismatch')
    if set(old_modules)!=set(base.MODULES)|{'apply_update.py'}: raise ValueError('source_unavailable')
    for name,expected in old_modules.items():
        if base.private_file(bridge/name)!=expected: raise ValueError('bridge_changed')
    if base.private_file(bridge/'deploy-enabled',4)!=b'1\n': raise ValueError('gate_not_enabled')
    base.private_file(bridge/'approved-sha',41)
    marker=bridge/'deployment-incomplete.json';setup=bridge/'first-release-setup-incomplete.json'
    ticket=bridge/'approval-ticket.json'
    if any(os.path.lexists(p) for p in (marker,setup,ticket)): raise ValueError('existing_pending_work')
    if not inspect(bridge/'nordicway_deploy_guard.py'): raise ValueError('guard_in_flight')
    lock=os.open(var/'escape-deploy.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    try:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if any(os.path.lexists(p) for p in (marker,setup,ticket)): raise ValueError('existing_pending_work')
        claim(setup,release)
        claim(marker,release)
        os.unlink(bridge/'deploy-enabled');sync_dir(bridge)
        if not inspect(bridge/'nordicway_deploy_guard.py'): raise ValueError('guard_in_flight')
        if build.read_text().strip()!=base.INSTALLED or req.read_bytes()!=requirements: raise ValueError('installed_version_changed')
        for name,expected in old_modules.items():
            if base.private_file(bridge/name)!=expected: raise ValueError('bridge_changed')
        result=installer.install(repo,bridge,bridge_sha)
        if result.get('status')!='installed_disabled' or base.private_file(bridge/'apply_update.py')!=release_updater:
            raise ValueError('bridge_install_unverified')
        # The gate stays closed. The second scan excludes an already-admitted
        # old guard before temporarily removing our claim for the existing
        # approve() API. A private setup marker survives any interruption.
        if not inspect(bridge/'nordicway_deploy_guard.py'): raise ValueError('guard_in_flight')
        os.unlink(marker);sync_dir(bridge)
        key=base.private_file(bridge/'owner-approval-key',32)
        if len(key)!=32: raise ValueError('unsafe_owner_key')
        proof=approval.create_proof(release,key,lifetime=approval.MAX_LIFETIME)
        approval.approve(bridge,var/'escape-deploy.lock',release,proof,already_locked=True)
        if base.private_file(bridge/'approved-sha',41).strip()!=release.encode(): raise ValueError('approval_readback_failed')
        data=json.loads(base.private_file(ticket,512))
        if data!={'sha':release,'nonce':proof['nonce'],'expires':proof['expires']}: raise ValueError('approval_readback_failed')
        # Open while claimed: an overlapping deploy request cannot take claim.
        claim(marker,release)
        base.atomic(bridge,'deploy-enabled',b'1\n')
        if base.private_file(bridge/'deploy-enabled',4)!=b'1\n': raise ValueError('gate_readback_failed')
        os.unlink(marker);sync_dir(bridge)
        try:
            os.unlink(setup);sync_dir(bridge)
        except BaseException:
            # If unlink succeeded but its durability check failed, recreate
            # the blocking setup marker before the deploy lock is released.
            try:
                if not os.path.lexists(setup): claim(setup,release)
            except BaseException:
                # When a marker cannot be restored, close the gate instead.
                try: os.unlink(bridge/'deploy-enabled')
                except FileNotFoundError: pass
                sync_dir(bridge)
            raise
        return {'status':'prepared','release':release,'bridge':bridge_sha,'expires':proof['expires']}
    finally:
        os.close(lock)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--release',required=True);parser.add_argument('--bridge',required=True)
    parser.add_argument('--updater-blob',required=True)
    args=parser.parse_args()
    for value in (args.release,args.bridge,args.updater_blob):
        if not re.fullmatch('[0-9a-f]{40}',value): raise ValueError('invalid_revision')
    repo=base.ROOT/'escape_deploy/invest'
    if repo.is_symlink() or not repo.is_dir(): raise ValueError('checkout_unavailable')
    modules={name:base.git_file(repo,base.OLD_BRIDGE,'apply_update.py' if name=='apply_update.py' else 'tools/'+name)
             for name in (*base.MODULES,'apply_update.py')}
    # Both executable modules and installer source are retrieved from the
    # immutable, reviewed bridge commit and evaluated before any server write.
    installer=load_module('pinned_bridge_installer',base.git_file(repo,args.bridge,'tools/nordicway_install_bridge.py'))
    approval=load_module('pinned_owner_approval',base.git_file(repo,args.bridge,'tools/nordicway_owner_approval.py'))
    result=prepare(base.ROOT,args.release,args.bridge,args.updater_blob,
                   base.git_file(repo,args.release,'apply_update.py'),base.git_file(repo,args.bridge,'apply_update.py'),
                   base.git_file(repo,args.release,'requirements.txt'),modules,installer,approval,repo)
    print(json.dumps(result,sort_keys=True))


if __name__=='__main__':
    try: main()
    except Exception as exc:
        reason=str(exc) if isinstance(exc,ValueError) and str(exc).replace('_','').isalnum() else 'preparation_failed'
        bridge=base.ROOT/'.escape_deploy_bridge'
        print(json.dumps({'status':'stopped','reason':reason,
                          'gate_present':os.path.lexists(bridge/'deploy-enabled'),
                          'recovery_present':os.path.lexists(bridge/'deployment-incomplete.json'),
                          'setup_present':os.path.lexists(bridge/'first-release-setup-incomplete.json')},sort_keys=True))
        raise SystemExit(1) from None
