"""Read-only GitHub Actions run-status lookup for the existing ESCAPE deploy workflow.

No deployments, approvals, comments, or credentials are written or printed.
"""
import json
import os
import re
import urllib.parse
import urllib.request

def main():
    token = os.environ.get("GITHUB_TOKEN", "")
    if not isinstance(token, str) or not token.strip():
        raise ValueError("token_unavailable")
    base = "https://api.github.com/repos/hva73/invest/actions/workflows/escape-deploy-ping.yml/runs"
    url = base + "?" + urllib.parse.urlencode({"event": "issue_comment", "per_page": 25})
    req = urllib.request.Request(url, headers={
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    with urllib.request.urlopen(req, timeout=20) as response:
        body = response.read(400_001)
    if len(body) > 400_000:
        raise ValueError("response_too_large")
    payload = json.loads(body)
    rows = payload.get("workflow_runs")
    if not isinstance(rows, list):
        raise ValueError("invalid_response")
    output = []
    for r in rows[:20]:
        if not isinstance(r, dict):
            continue
        output.append({k: r.get(k) for k in ("id", "status", "conclusion", "created_at", "updated_at", "event", "head_sha")})
    print(json.dumps({"status": "ok", "scope": "ESCAPE deploy issue_comment run metadata",
                      "runs": output, "changes": "none"}, sort_keys=True))

if __name__ == "__main__":
    main()
