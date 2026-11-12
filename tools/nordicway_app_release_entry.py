"""Fixed app-release entry used only by the restricted SSH guard."""
import json
import sys

BRIDGE='/home/nordicr4/.escape_deploy_bridge'
APP='/home/nordicr4/escape_app'


def main():
    try:
        if len(sys.argv)!=2:
            raise ValueError('invalid_request')
        sys.path.insert(0,APP)
        sys.path.insert(0,BRIDGE)
        import app,web_push,nordicway_app_release,nordicway_owner_approval,nordicway_deploy_runner
        result=nordicway_app_release.run_request(
            sys.argv[1],sys.stdin.buffer,app.connect,BRIDGE,
            runner=nordicway_deploy_runner.run,create_proof=nordicway_owner_approval.create_proof,
            notify=lambda uid:web_push.notify_release_ready(app.connect,uid))
    except Exception:
        # Never emit payload, secret, file contents or exception details.
        result={'operation':'app-deploy','status':'recovery','sha':sys.argv[1] if len(sys.argv)==2 else ''}
    print(json.dumps(result,separators=(',',':'),sort_keys=True))
    return 0 if result.get('status')=='completed' else 1


if __name__=='__main__':
    raise SystemExit(main())
