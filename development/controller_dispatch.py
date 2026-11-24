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
from datetime import datetime, timezone
try:
    from .controller_queue import plan
    from . import controller_remote
except ImportError:
    from controller_queue import plan
    import controller_remote

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
    if state["reserved"] + amount > budget:
        return False
    state["reserved"] += amount
    return True

def run_task(root, script, row, allowance):
    issue = row["issue"]
    folder = root / ("issue-" + str(issue))
    # Never overwrite an existing checkout or retry an unchanged task blindly.
    if folder.exists():
        return "existing_checkout"
    branch = "controller/local-" + str(issue) + "-" + str(int(time.time()))
    base = row["base_sha"]
    import re
    if not re.fullmatch(r"[0-9a-f]{40}", base):
        return "invalid_base"
    subprocess.run(["git", "worktree", "add", "-b", branch, str(folder), base],
                   cwd=script.parent.parent, check=True)
    taskfile = root / ("task-" + str(issue) + ".txt")
    taskfile.write_text(row["task"])
    log = root / ("issue-" + str(issue) + ".log")
    with log.open("a") as out:
        rc = subprocess.run([sys.executable, str(script), "--role", row["role"],
            "--issue", str(issue), "--task-file", str(taskfile), "--max-tokens",
            str(allowance), "--rounds", "3", "--minutes", "20", "--execute"],
            cwd=folder, stdout=out, stderr=subprocess.STDOUT).returncode
    if rc != 0:
        return "blocked"
    changed = subprocess.check_output(["git", "status", "--porcelain"], cwd=folder)
    if not changed:
        return "no_changes"
    # Export a reviewable patch locally. No automatic push to protected branches.
    subprocess.run(["git", "add", "-N", "--", "."], cwd=folder, check=True)
    patch = subprocess.check_output(["git", "diff", "--binary", "HEAD"], cwd=folder)
    (root / ("issue-" + str(issue) + ".patch")).write_bytes(patch)
    return "review_required"

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--queue", required=True, type=Path)
    p.add_argument("--root", required=True, type=Path)
    p.add_argument("--daily-reservation", type=int, default=120000)
    p.add_argument("--per-task", type=int, default=60000)
    p.add_argument("--parallel", type=int, default=2, choices=(1,2))
    p.add_argument("--execute", action="store_true")
    p.add_argument("--remote", action="store_true")
    a = p.parse_args()
    if not 0 < a.per_task <= a.daily_reservation:
        p.error("invalid budget")
    if not a.execute:
        print([t.issue for t in plan(load(a.queue, []), max_parallel=a.parallel)])
        return
    root = a.root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    script = Path(__file__).resolve().with_name("controller_pilot.py")
    with (root / "dispatcher.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        statefile = root / "budget.json"
        donefile = root / "results.json"
        state = load(statefile, {})
        results = load(donefile, {})
        while not (root / "STOP").exists():
            if a.remote:
                try:
                    controller_remote.refresh(root, a.queue)
                except (OSError, ValueError) as exc:
                    print("QUEUE_UNAVAILABLE:", type(exc).__name__, flush=True)
                    time.sleep(60)
                    continue
            rows = load(a.queue, [])
            # A completed local run is awaiting human/CI review, NOT a done dependency.
            rows = [dict(r, status="blocked") if str(r["issue"]) in results and r["status"] != "done" else r for r in rows]
            selected = plan(rows, max_parallel=a.parallel)
            ready = []
            day = datetime.now(timezone.utc).date().isoformat()
            for task in selected:
                row = next(r for r in rows if r["issue"] == task.issue)
                if not reserve(state, day, a.daily_reservation, a.per_task):
                    break
                save(statefile, state)
                ready.append(row)
                results[str(task.issue)] = "reserved"
                save(donefile, results)
            if not ready:
                time.sleep(30)
                continue
            with concurrent.futures.ThreadPoolExecutor(max_workers=a.parallel) as pool:
                futures = {pool.submit(run_task, root, script, row, a.per_task): row for row in ready}
                for future in concurrent.futures.as_completed(futures):
                    row = futures[future]
                    try:
                        status = future.result()
                    except Exception as exc:
                        status = "blocked:" + type(exc).__name__
                    results[str(row["issue"])] = status
                    save(donefile, results)

if __name__ == "__main__":
    main()
