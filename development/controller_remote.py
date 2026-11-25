"""Authenticated, bounded queue retrieval; no model calls."""
import json
import re
import subprocess
try:
    from .controller_queue import plan
except ImportError:
    from controller_queue import plan

REPO="hva73/invest"
REF="codex/development-controller-pilot"

def api(endpoint):
    raw=subprocess.check_output(["gh","api",endpoint],timeout=30)
    if len(raw)>262144:
        raise ValueError("response too large")
    return json.loads(raw)

def fetch_queue():
    import base64
    data=api("repos/"+REPO+"/contents/development/controller_tasks.json?ref="+REF)
    if data.get("encoding")!="base64":
        raise ValueError("invalid queue encoding")
    rows=json.loads(base64.b64decode(data["content"]))
    if not isinstance(rows,list) or len(rows)>100:
        raise ValueError("invalid queue")
    plan(rows)
    for row in rows:
        if row["status"]!="ready":
            continue
        if not re.fullmatch(r"[0-9a-f]{40}",row.get("base_sha","")) or not isinstance(row.get("task"),str) or not 0<len(row["task"])<=20000:
            raise ValueError("invalid task")
        generation=row.get("generation",1)
        if type(generation) is not int or generation<1:
            raise ValueError("invalid generation")
    return rows

def issue_open(issue):
    data=api("repos/"+REPO+"/issues/"+str(issue))
    return data.get("state")=="open" and "pull_request" not in data

def refresh(root,path):
    rows=fetch_queue()
    # A failed lookup of one issue must not starve independent work.
    # Fail closed for that issue for this snapshot, then retry on the next poll.
    checks={}
    for row in rows:
        if row["status"]!="ready":
            continue
        issue=row["issue"]
        if issue not in checks:
            try:
                checks[issue]=issue_open(issue)
            except (OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError) as exc:
                checks[issue]=False
                print("ISSUE_LOOKUP_UNAVAILABLE:",issue,type(exc).__name__,flush=True)
        if not checks[issue]:
            row["status"]="blocked"
    temp=path.with_suffix(".tmp")
    temp.write_text(json.dumps(rows,indent=2))
    temp.replace(path)
