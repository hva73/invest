"""Deterministic queue planning; generations are independent approved work items."""
from dataclasses import dataclass
import json
import sys

ROLES=("release","mobile","motor","data","desktop")

@dataclass(frozen=True)
class Task:
    issue:int
    role:str
    priority:int
    status:str
    dependencies:tuple
    paths:tuple
    generation:int=1

    @property
    def key(self):
        return (self.issue,self.generation)

def dependency_key(value):
    if type(value) is int and value>0:
        return (value,1)
    if isinstance(value,str):
        a=value.split(":")
        if len(a)==2 and all(x.isascii() and x.isdigit() and 0<int(x)<1000000000 for x in a):
            return tuple(map(int,a))
    raise ValueError("invalid dependency")

def plan(rows,max_parallel=2):
    if type(max_parallel) is not int or not 1<=max_parallel<=len(ROLES):
        raise ValueError("invalid parallel limit")
    tasks={}
    for row in rows:
        t=Task(row["issue"],row["role"],row["priority"],row["status"],
               tuple(dependency_key(d) for d in row.get("dependencies",[])),tuple(row["paths"]),row.get("generation",1))
        if (type(t.issue) is not int or t.issue<1 or type(t.generation) is not int or t.generation<1
                or t.key in tasks or t.role not in ROLES or type(t.priority) is not int
                or t.status not in ("ready","active","done","blocked") or not t.paths
                or any(not isinstance(p,str) or not p or p.startswith("/") or ".." in p.split("/") for p in t.paths)
                or t.key in t.dependencies):
            raise ValueError("invalid or duplicate task")
        tasks[t.key]=t
    def overlap(a,b):
        a,b=a.rstrip("/"),b.rstrip("/")
        return a==b or a.startswith(b+"/") or b.startswith(a+"/")
    active=[t for t in tasks.values() if t.status=="active"]
    result=[]
    for t in sorted(tasks.values(),key=lambda t:(t.priority,t.issue,t.generation)):
        if len(active)+len(result)>=max_parallel:
            break
        if t.status!="ready" or any(d not in tasks or tasks[d].status!="done" for d in t.dependencies):
            continue
        if any(t.role==o.role or t.issue==o.issue or any(overlap(a,b) for a in t.paths for b in o.paths) for o in active+result):
            continue
        result.append(t)
    return result

if __name__=="__main__":
    with open(sys.argv[1]) as f:
        print(json.dumps([t.issue for t in plan(json.load(f))]))
