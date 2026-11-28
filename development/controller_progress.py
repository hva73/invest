"""Bounded, non-model progress notifications. No arbitrary agent text is published."""
import json
import re
import subprocess
import threading

FLUSH_LOCK=threading.Lock()
from datetime import datetime, timezone

REPO = "hva73/invest"
PHASES = {"STARTED","WORKING","TESTING","CONTINUING","HANDOVER","COMPLETED","BLOCKED","REVIEW_REQUIRED"}

def record(root, issue, generation, phase):
    if type(issue) is not int or issue<1 or type(generation) is not int or generation<1 or phase not in PHASES:
        raise ValueError("invalid progress")
    folder=root/"progress"
    folder.mkdir(mode=0o700,exist_ok=True)
    path=folder/f"{issue}-{generation}-{phase}.json"
    if path.exists():
        return
    tmp=path.with_suffix(".tmp")
    tmp.write_text(json.dumps(dict(issue=issue,generation=generation,phase=phase,at=datetime.now(timezone.utc).isoformat(),sent=False)))
    tmp.replace(path)

def flush(root):
    if not FLUSH_LOCK.acquire(blocking=False):
        return
    try:
        _flush(root)
    finally:
        FLUSH_LOCK.release()

def _flush(root):
    folder=root/"progress"
    if not folder.exists():
        return
    # Process pending events chronologically, not alphabetically by phase.
    pending=[]
    for path in folder.glob("*.json"):
        try:
            item=json.loads(path.read_text())
            if not item["sent"]:
                pending.append((item["at"],path))
        except (OSError,ValueError,KeyError,TypeError):
            print("PROGRESS_PENDING:",path.name,flush=True)
    for _,path in sorted(pending)[:20]:
        try:
            item=json.loads(path.read_text())
            if item["sent"]:
                continue
            issue,generation,phase=item["issue"],item["generation"],item["phase"]
            if type(issue) is not int or issue<1 or type(generation) is not int or generation<1 or phase not in PHASES:
                raise ValueError("invalid progress")
            marker=f"<!-- escape-progress:{issue}:{generation}:{phase} -->"
            comments=subprocess.check_output(["gh","api","--paginate",f"repos/{REPO}/issues/{issue}/comments","--jq",".[].body"],text=True,timeout=15)
            if marker not in comments:
                subprocess.check_output(["gh","issue","comment",str(issue),"--repo",REPO,"--body",f"{marker}\nESCAPE Controller: generation {generation} — **{phase}**. Not release approval."],text=True,timeout=15)
            item["sent"]=True
            tmp=path.with_suffix(".tmp")
            tmp.write_text(json.dumps(item))
            tmp.replace(path)
        except (OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError):
            print("PROGRESS_PENDING:",path.name,flush=True)
