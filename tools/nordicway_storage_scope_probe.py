"""Read-only, bounded metadata scan of fixed ESCAPE account maintenance paths.

Never prints secrets or file content; never deletes, compresses, or modifies files.
"""
import json
import os
import re
import urllib.parse
import urllib.request
from nordicway_storage_inventory import NoRedirect

PATHS = (
    "/home/nordicr4/logs",
    "/home/nordicr4/tmp",
    "/home/nordicr4/.trash",
    "/home/nordicr4/escape_app/logs",
    "/home/nordicr4/escape_app/data",
    "/home/nordicr4/escape_app",
    "/home/nordicr4/escape_deploy",
)
CANDIDATE = re.compile(r"^[A-Za-z0-9_.-]{1,140}(?:\\.log(?:\\.[0-9]+)?|\\.gz|\\.bak|\\.old|\\.zip|\\.tar)(?:\\.gz)?$", re.I)
SENSITIVE = re.compile(r"token|key|secret|pass|credential|vapid|private|auth", re.I)

def inspect(path, token):
    query = urllib.parse.urlencode({"dir": path, "show_hidden": 1})
    url = "https://cp14.nordicway.dk:2083/execute/Fileman/list_files?" + query
    req = urllib.request.Request(url, headers={
        "Authorization": "cpanel nordicr4:" + token,
        "Accept": "application/json",
    })
    with urllib.request.build_opener(NoRedirect()).open(req, timeout=20) as response:
        raw = response.read(2_000_001)
    if len(raw) > 2_000_000:
        raise ValueError("reply_too_large")
    data = json.loads(raw)
    obj = data.get("result", data)
    if not isinstance(obj, dict) or obj.get("status") not in (1, "1"):
        return {"scope": path, "status": "not_available"}
    rows = obj.get("data")
    if not isinstance(rows, list) or len(rows) > 500:
        raise ValueError("inventory_invalid")
    total = 0
    candidates = []
    largest = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        name = r.get("file", r.get("name"))
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,160}", name):
            continue
        if r.get("type") != "file":
            continue
        size = r.get("size")
        if not isinstance(size, (int, str)) or not str(size).isdigit():
            continue
        size = int(size)
        if size < 0 or size > 100_000_000_000:
            continue
        total += size
        if CANDIDATE.fullmatch(name) and not SENSITIVE.search(name) and size >= 5_000_000:
            candidates.append({"name": name, "size_bytes": size, "mtime": r.get("mtime") if isinstance(r.get("mtime"), int) else None})
        if size > 50_000_000:
            largest.append(size)
    return {
        "scope": path,
        "status": "ok",
        "visible_file_count": sum(1 for r in rows if isinstance(r, dict) and r.get("type") == "file"),
        "sum_regular_file_bytes": total,
        "large_regular_file_bytes": sorted(largest, reverse=True)[:6],
        "cleanup_candidates": sorted(candidates, key=lambda c: -c["size_bytes"])[:15],
        "changes": "none",
    }

def main():
    token = os.environ.get("ESCAPE_CPANEL_API_TOKEN", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{10,256}", token):
        raise ValueError("credential_unavailable")
    for path in PATHS:
        try:
            result = inspect(path, token)
        except Exception as ex:
            result = {"scope": path, "status": "unavailable", "reason": type(ex).__name__}
        print(json.dumps(result, sort_keys=True), flush=True)

if __name__ == "__main__":
    main()
