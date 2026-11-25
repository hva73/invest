"""Local bounded dispatcher. Trusted queue is operator-maintained, never model-written."""
import argparse
import concurrent.futures
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import threading

FETCH_LOCK = threading.Lock()
from datetime import datetime, timezone
try:
    from .controller_queue import plan
    from . import controller_remote, controller_publish, controller_receipts, controller_progress
except ImportError:
    from controller_queue import plan
    import controller_remote, controller_publish, controller_receipts, controller_progress

def save(path, value):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, indent=2))
    temp.replace(path)

def load(path, default):
    return json.loads(path.read_text()) if path.exists() else default

def reserve(state, day, budget, amount):
    if state.get("day") != day:
        state.clear()
        state.update(day=day, reserved=0)
    if budget is not None and state["reserved"] + amount > budget:
        return False
    state["reserved"] += amount
    return True

def task_key(row):
    generation = row.get("generation", 1)
    if type(generation) is not int or generation < 1:
        raise ValueError("invalid generation")
    return str(row["issue"]) + ":" + str(generation)

def progress(root, row, phase, publish):
    if publish:
        try:
            controller_progress.record(root,row["issue"],row.get("generation",1),phase)
            controller_progress.flush(root)
        except (OSError,ValueError):
            print("PROGRESS_PENDING:",task_key(row),phase,flush=True)

def run_task(root, script, row, allowance, publish=False):
    issue = row["issue"]
    generation = row.get("generation", 1)
    folder = root / ("issue-" + str(issue) + "-" + str(generation))
    # Never overwrite an existing checkout or retry an unchanged task blindly.
    if folder.exists():
        return "existing_checkout"
    branch = "controller/local-" + str(issue) + "-" + str(time.time_ns())
    base = row["base_sha"]
    import re
    if not re.fullmatch(r"[0-9a-f]{40}", base):
        return "invalid_base"
    if row.get("base_branch"):
        target = row.get("base_branch")
        if target not in controller_publish.BASES or (target=="codex/issue57-combined-release-20261124" and row["role"]!="release"):
            return "invalid_target"
        with FETCH_LOCK:
            subprocess.run(["git", "fetch", "--no-tags", "https://github.com/hva73/invest.git", target], cwd=script.parent.parent, check=True, timeout=90)
            actual = subprocess.check_output(["git", "rev-parse", "FETCH_HEAD"], cwd=script.parent.parent).decode().strip()
        if actual != base:
            return "stale_base"
    subprocess.run(["git", "worktree", "add", "-b", branch, str(folder), base],
                   cwd=script.parent.parent, check=True)
    taskfile = root / ("task-" + str(issue) + "-" + str(generation) + ".txt")
    taskfile.write_text(row["task"])
    log = root / ("issue-" + str(issue) + "-" + str(generation) + ".log")
    progress(root,row,"STARTED",publish)
    finished=threading.Event()
    def report():
        while not finished.wait(15):
            if publish:
                controller_progress.flush(root)
    reporter=threading.Thread(target=report,daemon=True)
    reporter.start()
    try:
        with log.open("a") as out:
            rc = subprocess.run([sys.executable, str(script), "--role", row["role"],
            "--issue", str(issue), "--task-file", str(taskfile), "--max-tokens",
            str(allowance), "--rounds", "3", "--minutes", "20", "--generation", str(generation),
            "--allowed-paths-json", json.dumps(row["paths"]), "--progress-root", str(root), "--checkpoint", str(root / ("checkpoint-"+str(issue)+"-"+str(generation)+".json")), "--execute"],
            cwd=folder, stdout=out, stderr=subprocess.STDOUT).returncode
    finally:
        finished.set()
        reporter.join()
    if rc == 75:
        return "blocked:provider_limit"
    if rc != 0:
        return "blocked"
    changed = subprocess.check_output(["git", "status", "--porcelain"], cwd=folder)
    if not changed:
        return "no_changes"
    # Export a reviewable patch locally. No automatic push to protected branches.
    subprocess.run(["git", "add", "-N", "--", "."], cwd=folder, check=True)
    patch = subprocess.check_output(["git", "diff", "--binary", "HEAD"], cwd=folder)
    (root / ("issue-" + str(issue) + "-" + str(generation) + ".patch")).write_bytes(patch)
    if publish and not (root / "STOP").exists():
        url = controller_publish.publish(folder, row, branch, base)
        (root / ("issue-" + str(issue) + "-" + str(generation) + ".pr")).write_text(url + "\n")
        return "draft_pr"
    return "review_required"

def effective_rows(rows,results,running):
    # Keep the actual running scope reserved even if the remote queue changes.
    active={task_key(row):row for row in running}
    out=[]
    for row in rows:
        key=task_key(row)
        if key in active:
            continue
        out.append(dict(row,status="blocked") if key in results and row["status"]!="done" else row)
    out.extend(dict(row,status="active") for row in active.values())
    return out

def notify_result(root,row,status,publish):
    if not publish:
        return
    try:
        phase="REVIEW_REQUIRED" if status in ("draft_pr","review_required","no_changes") else "BLOCKED"
        progress(root,row,phase,True)
        controller_receipts.record(root,task_key(row),status)
        controller_receipts.flush(root)
    except (OSError,ValueError):
        print("RECEIPT_PENDING:",task_key(row),flush=True)

def provider_pause_active(root,now=None):
    now=time.time() if now is None else now
    path=root/"provider-pause.json"
    if not path.exists():
        return False
    try:
        value=load(path,{})
        stamp=value.get("reset_at")
        return type(stamp) not in (int,float) or not (0<stamp<=now)
    except (OSError,ValueError,TypeError,AttributeError):
        return True

def record_provider_pause(root,row,now=None):
    now=time.time() if now is None else now
    stamp=None
    try:
        checkpoint=load(root/("checkpoint-"+str(row["issue"])+"-"+str(row.get("generation",1))+".json"),{})
        reported=checkpoint.get("provider_reset_at")
        if (checkpoint.get("issue")==row["issue"] and checkpoint.get("generation")==row.get("generation",1)
                and checkpoint.get("provider_limit") is True and type(reported) in (int,float) and now<reported<=now+604800):
            stamp=reported
    except (OSError,ValueError,TypeError,AttributeError):
        pass
    path=root/"provider-pause.json"
    if path.exists() and provider_pause_active(root,now):
        try:
            previous=load(path,{}).get("reset_at")
            stamp=max(previous,stamp) if type(previous) in (int,float) and stamp is not None else None
        except (OSError,ValueError,TypeError,AttributeError):
            stamp=None
    save(path,{"task":task_key(row),"observed_at":now,"reset_at":stamp})
    print("PROVIDER_PAUSE:", "until reported reset" if stamp is not None else "awaiting confirmed reset",flush=True)

def write_status(root, reason, active, waiting=()):
    """One local heartbeat; contains only task IDs and scheduler state."""
    try:
        save(root/"status.json", {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "reason": reason,
            "active": sorted(task_key(row) for row in active),
            "waiting": sorted(waiting),
        })
    except OSError as exc:
        print("STATUS_UNAVAILABLE:",type(exc).__name__,flush=True)

def run_queue(a,root,script,statefile,donefile,state,results):
    # A process restart cannot assume a previously reserved generation is idle.
    # Preserve its checkout and explicitly expose the interrupted state.
    interrupted={key for key,status in results.items() if status=="reserved"}
    for key in interrupted:
        results[key]="blocked:interrupted"
    if interrupted:
        save(donefile,results)
    with concurrent.futures.ThreadPoolExecutor(max_workers=a.parallel) as pool:
        active={}
        while active or not (root/"STOP").exists():
            for future,row in list(active.items()):
                if not future.done():
                    continue
                try:
                    status=future.result()
                except controller_publish.PublicationError as exc:
                    status="blocked:"+str(exc)
                except Exception as exc:
                    status="blocked:"+type(exc).__name__
                if status=="blocked:provider_limit":
                    record_provider_pause(root,row)
                results[task_key(row)]=status
                save(donefile,results)
                del active[future]
                notify_result(root,row,status,a.publish)
            if a.publish:
                controller_receipts.flush(root)
                controller_progress.flush(root)
            if (root/"STOP").exists():
                write_status(root,"stopping",active.values())
                if active:
                    concurrent.futures.wait(active,timeout=15,return_when=concurrent.futures.FIRST_COMPLETED)
                continue
            reason="idle"
            waiting=[]
            try:
                if a.remote:
                    controller_remote.refresh(root,a.queue)
                rows=load(a.queue,[])
                for row in rows:
                    key=task_key(row)
                    if key in interrupted:
                        notify_result(root,row,"blocked:interrupted",a.publish)
                        interrupted.remove(key)
                rows=effective_rows(rows,results,active.values())
                waiting=[task_key(row) for row in rows if row["status"]=="ready"]
                paused=provider_pause_active(root)
                selected=[] if paused else plan(rows,max_parallel=a.parallel)
                if paused:
                    reason="provider_pause"
                elif waiting and not selected:
                    reason="waiting_for_dependency_or_worker"
                elif not waiting and not active:
                    reason="no_eligible_work"
            except (OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError) as exc:
                print("QUEUE_UNAVAILABLE:",type(exc).__name__,flush=True)
                selected=[]
                rows=[]
                reason="queue_unavailable"
            day=datetime.now(timezone.utc).date().isoformat()
            for task in selected:
                if (root/"STOP").exists():
                    break
                row=next(r for r in rows if (r["issue"],r.get("generation",1))==task.key)
                if not reserve(state,day,a.daily_reservation,a.per_task):
                    reason="budget_limit"
                    break
                save(statefile,state)
                results[task_key(row)]="reserved"
                save(donefile,results)
                active[pool.submit(run_task,root,script,row,a.per_task,a.publish)]=row
            active_keys={task_key(row) for row in active.values()}
            if active and reason in ("idle","waiting_for_dependency_or_worker"):
                reason="working"
            write_status(root,reason,active.values(),[key for key in waiting if key not in active_keys])
            if active:
                concurrent.futures.wait(active,timeout=15,return_when=concurrent.futures.FIRST_COMPLETED)
            elif not (root/"STOP").exists():
                time.sleep(120)

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--queue", required=True, type=Path)
    p.add_argument("--root", required=True, type=Path)
    p.add_argument("--daily-reservation", type=int, default=None)
    p.add_argument("--per-task", type=int, default=60000)
    p.add_argument("--parallel", type=int, default=2, choices=(1,2))
    p.add_argument("--execute", action="store_true")
    p.add_argument("--remote", action="store_true")
    p.add_argument("--publish", action="store_true")
    a = p.parse_args()
    if a.per_task <= 0 or (a.daily_reservation is not None and a.daily_reservation < a.per_task):
        p.error("invalid budget")
    if not a.execute:
        print([t.issue for t in plan(load(a.queue, []), max_parallel=a.parallel)])
        return
    if a.publish:
        subprocess.run(["gh", "auth", "status", "--hostname", "github.com"], check=True, timeout=30)
    root = a.root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    script = Path(__file__).resolve().with_name("controller_pilot.py")
    with (root / "dispatcher.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        statefile = root / "budget.json"
        donefile = root / "results.json"
        state = load(statefile, {})
        results = load(donefile, {})
        run_queue(a,root,script,statefile,donefile,state,results)

if __name__ == "__main__":
    main()
