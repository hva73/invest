"""Deterministic queue planning; no model calls, network or publishing."""
from dataclasses import dataclass
import json
import sys

ROLES = ("release", "mobile", "motor", "data", "desktop")

@dataclass(frozen=True)
class Task:
    issue: int
    role: str
    priority: int
    status: str
    dependencies: tuple
    paths: tuple

def plan(rows):
    tasks = {}
    for row in rows:
        t = Task(row["issue"], row["role"], row["priority"], row["status"],
                 tuple(row.get("dependencies", [])), tuple(row["paths"]))
        if (type(t.issue) is not int or t.issue < 1 or t.issue in tasks
                or t.role not in ROLES or type(t.priority) is not int
                or t.status not in ("ready", "active", "done", "blocked")
                or not t.paths or any(not isinstance(p,str) or not p or
                    p.startswith("/") or ".." in p.split("/") for p in t.paths)):
            raise ValueError("invalid or duplicate task")
        tasks[t.issue] = t
    def overlap(a,b):
        a,b=a.rstrip("/"),b.rstrip("/")
        return a==b or a.startswith(b+"/") or b.startswith(a+"/")
    active = [t for t in tasks.values() if t.status == "active"]
    result = []
    for t in sorted(tasks.values(), key=lambda t:(t.priority,t.issue)):
        if t.status != "ready" or any(d not in tasks or tasks[d].status != "done" for d in t.dependencies):
            continue
        if any(t.role == other.role or any(overlap(a,b) for a in t.paths for b in other.paths)
               for other in active + result):
            continue
        result.append(t)
    return result

if __name__ == "__main__":
    with open(sys.argv[1]) as f:
        print(json.dumps([t.issue for t in plan(json.load(f))]))
