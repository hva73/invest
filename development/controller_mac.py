"""Install a user-level launchd service, with explicit opt-in for draft PRs."""
import argparse
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys

LABEL = "dk.escape.development-controller"

def configuration(repo, root, python, path, publish=False):
    args=[str(python), str(repo/"development/controller_dispatch.py"),
          "--queue",str(root/"queue.json"),"--root",str(root),"--remote","--execute"]
    if publish:
        args.append("--publish")
    return {"Label":LABEL,"ProgramArguments":args,"WorkingDirectory":str(repo),
            "EnvironmentVariables":{"PATH":path,"HOME":str(Path.home())},
            "RunAtLoad":True,"KeepAlive":{"SuccessfulExit":False},
            "ThrottleInterval":120,"StandardOutPath":str(root/"service.log"),
            "StandardErrorPath":str(root/"service-error.log")}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("action",choices=("install","stop","status"))
    p.add_argument("--publish",action="store_true")
    a=p.parse_args()
    if sys.platform!="darwin":
        p.error("macOS required")
    repo=Path(__file__).resolve().parent.parent
    root=Path.home()/"ESCAPE-Development"/"runtime"
    plist=Path.home()/"Library/LaunchAgents"/(LABEL+".plist")
    domain="gui/"+str(os.getuid())
    target=domain+"/"+LABEL
    if a.action=="status":
        subprocess.run(["launchctl","print",target],check=True)
        return
    if a.action=="stop":
        root.mkdir(parents=True,exist_ok=True)
        (root/"STOP").touch()
        subprocess.run(["launchctl","bootout",target],check=False)
        return
    if not shutil.which("codex"):
        p.error("Codex CLI missing")
    subprocess.run(["codex","login","status"],check=True,timeout=30)
    if a.publish:
        if not shutil.which("gh"):
            p.error("GitHub CLI missing")
        subprocess.run(["gh","auth","status","--hostname","github.com"],check=True,timeout=30)
    subprocess.run([sys.executable,"-m","unittest","discover","-s","tests","-p","test_controller_*.py"],cwd=repo,check=True)
    root.mkdir(parents=True,exist_ok=True,mode=0o700)
    plist.parent.mkdir(parents=True,exist_ok=True)
    subprocess.run(["launchctl","bootout",target],check=False)
    (root/"STOP").unlink(missing_ok=True)
    with plist.open("wb") as out:
        plistlib.dump(configuration(repo,root,sys.executable,os.environ["PATH"],a.publish),out)
    subprocess.run(["launchctl","bootstrap",domain,str(plist)],check=True)
    subprocess.run(["launchctl","print",target],check=True)

if __name__=="__main__":
    main()
