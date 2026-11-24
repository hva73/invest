"""Trusted queue from a dedicated GitHub branch, with no AI polling."""
import json
import subprocess
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError

URL = "https://raw.githubusercontent.com/hva73/invest/codex/development-controller-pilot/development/controller_tasks.json"

def fetch_queue():
    req = Request(URL, headers={"Accept":"application/json", "User-Agent":"ESCAPE-Controller"})
    with urlopen(req, timeout=10) as response:
        raw = response.read(131073)
    if len(raw)>131072:
        raise ValueError("queue too large")
    rows = json.loads(raw)
    if not isinstance(rows,list) or len(rows)>100:
        raise ValueError("invalid queue")
    return rows

def issue_open(issue):
    req = Request("https://api.github.com/repos/hva73/invest/issues/"+str(issue),
                  headers={"Accept":"application/vnd.github+json","User-Agent":"ESCAPE-Controller"})
    with urlopen(req,timeout=10) as response:
        data=json.load(response)
    return data.get("state")=="open" and "pull_request" not in data

def refresh(root, path):
    rows=fetch_queue()
    from controller_queue import plan
    plan(rows)
    for row in rows:
        if row["status"]=="ready" and not issue_open(row["issue"]):
            row["status"]="blocked"
    temp=path.with_suffix(".tmp")
    temp.write_text(json.dumps(rows,indent=2))
    temp.replace(path)
