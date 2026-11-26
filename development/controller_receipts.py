"""Durable local completion outbox; GitHub issue notification is retryable.
A receipt means delivered for review, never approved, merged or deployed.
"""
import json
import re
import subprocess
from datetime import datetime, timezone

REPO="hva73/invest"
KEY=re.compile(r"([1-9][0-9]*):([1-9][0-9]*)")
PR=re.compile(r"https://github\.com/hva73/invest/pull/([1-9][0-9]*)")
STATUS=re.compile(r"(?:draft_pr|review_required|no_changes|blocked(?::[A-Za-z_]+)?|existing_checkout|invalid_base|invalid_target|stale_base)")

def atomic(path,data):
    temp=path.with_suffix(".tmp")
    temp.write_text(json.dumps(data,indent=2)+"\n")
    temp.replace(path)

def record(root,key,status):
    m=KEY.fullmatch(key)
    if not m or not STATUS.fullmatch(status):
        raise ValueError("invalid completion")
    issue,generation=map(int,m.groups())
    folder=root/"receipts"
    folder.mkdir(mode=0o700,exist_ok=True)
    path=folder/(f"{issue}-{generation}.json")
    if path.exists():
        return
    url=None
    if status=="draft_pr":
        url=(root/f"issue-{issue}-{generation}.pr").read_text().strip()
        if not PR.fullmatch(url):
            raise ValueError("invalid PR receipt")
    atomic(path,{"issue":issue,"generation":generation,"status":status,"pr":url,
                 "created_at":datetime.now(timezone.utc).isoformat(),"notified":False})

def promote_local_delivery(root,key):
    """Keep the previous receipt, replace it only with a verified draft URL."""
    m=KEY.fullmatch(key)
    if not m:
        raise ValueError("invalid completion")
    issue,generation=map(int,m.groups())
    folder=root/"receipts"
    path=folder/(f"{issue}-{generation}.json")
    if not path.exists():
        return
    item=json.loads(path.read_text())
    url=(root/f"issue-{issue}-{generation}.pr").read_text().strip()
    if item.get("status")=="draft_pr" and item.get("pr")==url:
        return
    if item.get("status") not in ("review_required","blocked:incomplete") or item.get("issue")!=issue or item.get("generation")!=generation or not PR.fullmatch(url):
        raise ValueError("invalid local delivery promotion")
    archive=folder/(f"{issue}-{generation}.local-only.history")
    if not archive.exists():
        atomic(archive,item)
    atomic(path,dict(item,status="draft_pr",pr=url,notified=False))

def gh(*args):
    return subprocess.check_output(["gh",*args],text=True,timeout=30)

def deliver(path):
    item=json.loads(path.read_text())
    if item["notified"]:
        return False
    issue,generation=item["issue"],item["generation"]
    status=item["status"]
    url=item["pr"]
    if (type(issue) is not int or type(generation) is not int or issue<1 or generation<1
            or not STATUS.fullmatch(status)
            or (status=="draft_pr" and (not isinstance(url,str) or not PR.fullmatch(url)))
            or (status!="draft_pr" and url is not None)):
        raise ValueError("invalid receipt")
    marker=f"<!-- escape-controller:{issue}:{generation} -->"
    # Check for the exact marker before retrying a possibly successful POST.
    existing=gh("api","--paginate",f"repos/{REPO}/issues/{issue}/comments",
                "--jq",".[].body")
    if marker not in existing or (status=="draft_pr" and url not in existing):
        msg=(f"{marker}\nESCAPE Controller: #{issue}, generation {generation} — **{status}**."
             + (f"\nDraft PR: {url}" if url else "")
             + "\nAwaiting independent review. Not release approval or production deployment.")
        gh("issue","comment",str(issue),"--repo",REPO,"--body",msg)
    item["notified"]=True
    atomic(path,item)
    return True

def flush(root):
    folder=root/"receipts"
    if not folder.exists():
        return
    # One bad receipt or outage must never repeat model execution.
    for path in sorted(folder.glob("*.json"))[:100]:
        try:
            deliver(path)
        except (OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError) as exc:
            print("NOTIFICATION_PENDING:",path.name,type(exc).__name__,flush=True)
