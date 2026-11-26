"""Local bounded dispatcher. Trusted queue is operator-maintained, never model-written."""
import argparse
import concurrent.futures
import fcntl
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import time
import threading

from datetime import datetime, timezone
try:
    from .controller_queue import plan, worker
    from . import controller_remote, controller_publish, controller_receipts, controller_progress, controller_coordinator
except ImportError:
    from controller_queue import plan, worker
    import controller_remote, controller_publish, controller_receipts, controller_progress, controller_coordinator

FETCH_LOCK = controller_coordinator.FETCH_LOCK

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

def boot_id():
    """A changed OS boot proves that old local workers cannot still be alive."""
    try:
        if sys.platform == "darwin":
            value=subprocess.check_output(["sysctl","-n","kern.bootsessionuuid"],text=True,timeout=5).strip()
        else:
            value=Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        return value if re.fullmatch(r"[0-9a-fA-F-]{36}",value) else None
    except (OSError,subprocess.SubprocessError):
        return None

def task_record(root,row):
    return root/("reservation-"+task_key(row).replace(":","-")+".json")

def can_recover(root,row,boot):
    try:
        record=load(task_record(root,row),{})
        key=task_key(row).replace(":","-")
        return bool(boot and record.get("boot") and boot!=record["boot"]
                    and record.get("row")==row and not record.get("recovered")
                    and row["status"]=="ready"
                    and not (root/f"issue-{key}.pr").exists()
                    and not (root/f"receipts/{key}.json").exists()
                    and not load(root/f"checkpoint-{key}.json",{}).get("provider_limit"))
    except (OSError,ValueError,TypeError,AttributeError):
        return False

def can_resume_incomplete(root,repo_dir,row,results):
    """One automatic continuation of a confirmed exited worker with scoped edits."""
    k=task_key(row).replace(":","-")
    if results.get(task_key(row))!="blocked:incomplete" or row["status"]!="ready" or row.get("local_review") is not True or row.get("base_branch") not in controller_coordinator.TARGETS or row["role"]=="release":
        return False
    try:
        record=load(task_record(root,row),{})
        folder=root/("issue-"+k)
        receipt=load(root/("receipts/"+k+".json"),{})
        if record.get("row")!=row or record.get("recovered") or receipt.get("status")!="blocked:incomplete" or receipt.get("issue")!=row["issue"] or receipt.get("generation")!=row.get("generation",1) or receipt.get("pr") is not None or (root/("issue-"+k+".pr")).exists() or load(root/("checkpoint-"+k+".json"),{}).get("provider_limit"):
            return False
        taskfile=root/("task-"+k+".txt")
        if taskfile.is_symlink() or taskfile.read_text()!=row["task"]:
            return False
        branch,head=controller_coordinator.inspect_repair_workspace(repo_dir,row,row["base_sha"],folder)
        if head!=row["base_sha"] or not controller_publish.git(folder,"status","--porcelain"):
            return False
        if controller_coordinator.branch_head(row["base_branch"])!=head:
            return False
        remote=controller_coordinator.gh(controller_coordinator.PREFIX+"/git/matching-refs/heads/"+branch)
        return isinstance(remote,list) and not any(x.get("ref")=="refs/heads/"+branch for x in remote)
    except (OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError):
        return False

def can_resume_delivery(root,row,results):
    """Retry only an explicitly finished local-only delivery once, not a live reservation."""
    k=task_key(row).replace(":","-")
    if results.get(task_key(row))!="review_required" or row["status"]!="ready" or row.get("local_review") is not True or row.get("base_branch") not in controller_coordinator.TARGETS or row["role"]=="release":
        return False
    try:
        record=load(task_record(root,row),{})
        folder=root/("issue-"+k)
        receipt=load(root/("receipts/"+k+".json"),{})
        return (record.get("row")==row and not record.get("delivery_retry")
                and folder.is_dir() and not folder.is_symlink()
                and (root/("issue-"+k+".patch")).is_file()
                and not (root/("issue-"+k+".pr")).exists()
                and receipt.get("status") in (None,"review_required")
                and not load(root/("checkpoint-"+k+".json"),{}).get("provider_limit"))
    except (OSError,ValueError,TypeError,AttributeError):
        return False

def authorize_preserved_delivery(root,repo_dir,row,results):
    """One owner-reset retry of a finished local-only delivery, under dispatcher.lock.
    Do not clear unknown reservations, publish code, or change the approved task.
    """
    k=task_key(row).replace(":","-")
    if results.get(task_key(row))!="review_required" or row["status"]!="ready" or row.get("local_review") is not True or row.get("base_branch") not in controller_coordinator.TARGETS or row["role"]=="release":
        raise ValueError("Ingen afsluttet lokal leverance")
    if can_resume_delivery(root,row,results):
        return False
    reservation=task_record(root,row)
    archive=reservation.with_suffix(".team-reset-history.json")
    folder=root/("issue-"+k)
    patchfile=root/("issue-"+k+".patch")
    receipt=load(root/("receipts/"+k+".json"),{})
    old=load(reservation,{})
    prior=old.get("row")
    # Only a scheduling/permission flag may have been added since the original
    # approved task; identity, base, role, dependencies and code scope stay exact.
    if not isinstance(prior,dict) or any(prior.get(field)!=row.get(field) for field in ("issue","generation","role","base_branch","base_sha","paths","task","dependencies")):
        raise ValueError("Tidligere reservation matcher ikke godkendt opgave")
    if archive.exists() or reservation.is_symlink() or patchfile.is_symlink() or not patchfile.is_file() or (root/("issue-"+k+".pr")).exists():
        raise ValueError("Lokal leverance allerede afstemt eller mulig publicering")
    if receipt and (receipt.get("status")!="review_required" or receipt.get("issue")!=row["issue"] or receipt.get("generation")!=row.get("generation",1) or receipt.get("pr") is not None):
        raise ValueError("Leveringskvittering matcher ikke lokal opgave")
    checkpoint=load(root/("checkpoint-"+k+".json"),{})
    if checkpoint.get("provider_limit"):
        raise ValueError("Afventer faktisk provider-kapacitet")
    taskfile=root/("task-"+k+".txt")
    if not taskfile.is_file() or taskfile.is_symlink() or taskfile.read_text()!=row["task"]:
        raise ValueError("Bevaret opgavetekst matcher ikke")
    branch,head=controller_coordinator.inspect_repair_workspace(repo_dir,row,row["base_sha"],folder)
    if head!=row["base_sha"] or controller_publish.git(folder,"diff","--binary","HEAD")!=patchfile.read_bytes():
        raise ValueError("Bevaret kode matcher ikke lokal patch")
    # An existing remote branch is evidence of possible earlier publication.
    # In that case reconcile the PR instead of creating another one.
    remote=controller_coordinator.gh(controller_coordinator.PREFIX+"/git/matching-refs/heads/"+branch)
    if not isinstance(remote,list) or any(x.get("ref")=="refs/heads/"+branch for x in remote):
        raise ValueError("Eksisterende remote leverance kræver afstemning")
    latest=controller_coordinator.branch_head(row["base_branch"])
    if latest!=row["base_sha"] and (row.get("follow_base") is not True or not controller_coordinator.disjoint_base_changes(controller_coordinator.gh(controller_coordinator.PREFIX+"/compare/"+row["base_sha"]+"..."+latest),row["base_sha"],row["paths"])):
        raise ValueError("Ny basis overlapper bevaret scope")
    controller_coordinator.save(archive,old)
    controller_coordinator.save(reservation,dict(old,row=row,delivery_retry=False))
    return True

def run_task(root, script, row, allowance, publish=False):
    issue = row["issue"]
    generation = row.get("generation", 1)
    folder = root / ("issue-" + str(issue) + "-" + str(generation))
    record=load(task_record(root,row),{})
    recover=bool(record.get("recovered") and record.get("row")==row)
    if folder.exists() and not recover:
        return "existing_checkout"
    branch = "controller/local-" + str(issue) + "-" + str(time.time_ns())
    base = row["base_sha"]
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
            if not (recover and record.get("delivery_retry") and row.get("follow_base") is True and controller_coordinator.disjoint_base_changes(controller_coordinator.gh(controller_coordinator.PREFIX+"/compare/"+base+"..."+actual),base,row["paths"])):
                return "stale_base"
    taskfile = root / ("task-" + str(issue) + "-" + str(generation) + ".txt")
    resume=folder.exists()
    if resume:
        # Never rerun after a publication commit or against another checkout.
        if (folder.is_symlink() or not taskfile.is_file() or taskfile.read_text()!=row["task"]
            or controller_publish.git(folder,"rev-parse","HEAD").decode().strip()!=base
            or Path(controller_publish.git(folder,"rev-parse","--show-toplevel").decode().strip()).resolve()!=folder.resolve()):
            return "blocked:interrupted"
        branch=controller_publish.git(folder,"branch","--show-current").decode().strip()
        if not re.fullmatch(r"controller/local-"+str(issue)+r"-[0-9]+",branch):
            return "blocked:interrupted"
        progress(root,row,"HANDOVER",publish)
    else:
        subprocess.run(["git", "worktree", "add", "-b", branch, str(folder), base],
                       cwd=script.parent.parent, check=True)
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
            "--allowed-paths-json", json.dumps(row["paths"]), "--progress-root", str(root), "--checkpoint", str(root / ("checkpoint-"+str(issue)+"-"+str(generation)+".json")), "--execute"]
            + (["--recover"] if resume else [])
            + (["--require-ready"] if row.get("local_review") is True or record.get("delivery_retry") else []),
            cwd=folder, stdout=out, stderr=subprocess.STDOUT).returncode
    finally:
        finished.set()
        reporter.join()
    if rc == 75:
        return "blocked:provider_limit"
    if rc == 76 or rc == 1:
        # Child has exited. Preserve incomplete scoped code, never publish it.
        try:
            controller_coordinator.inspect_repair_workspace(script.parent.parent,row,base,folder)
            if subprocess.check_output(["git","status","--porcelain"],cwd=folder):
                return "blocked:incomplete"
        except (OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError):
            pass
        return "blocked"
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
        if status=="draft_pr" and load(task_record(root,row),{}).get("recovered"):
            controller_receipts.promote_local_delivery(root,task_key(row))
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

def write_status(root, reason, active, waiting=(), review=(), coordinator_capable=False, coordinator_running=False, coordinator_task=None, capacity=2):
    """One local heartbeat; contains only task IDs and scheduler state."""
    try:
        active=list(active)
        save(root/"status.json", {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "reason": reason,
            "active": sorted(task_key(row) for row in active),
            "waiting": sorted(waiting),
            "awaiting_review": sorted(review),
            "coordinator_protocol": 1 if coordinator_capable else 0,
            "coordinator_running": bool(coordinator_running),
            "coordinator_task": coordinator_task,
            "slots_used": len(active)+int(bool(coordinator_running)),
            "slot_capacity": capacity,
        })
    except OSError as exc:
        print("STATUS_UNAVAILABLE:",type(exc).__name__,flush=True)

def coordinate(root, repo_dir, rows, results, waiting, review, reserve_review=lambda: True, repair_allowance=60000):
    stopped=threading.Event()
    def heartbeat():
        while not stopped.is_set():
            write_status(root,"coordinating",[],waiting,review,True,True)
            stopped.wait(10)
    reporter=threading.Thread(target=heartbeat,daemon=True)
    reporter.start()
    try:
        return controller_coordinator.run_once(root,repo_dir,rows,results,reserve_review=reserve_review,repair_allowance=repair_allowance)
    finally:
        stopped.set(); reporter.join()

def developer_conflict(row, other):
    # Separate draft branches may be edited simultaneously when scopes are
    # independent. Integration, unlike development, changes the base branch.
    if row["issue"]==other["issue"] or worker(row["role"])==worker(other["role"]):
        return True
    return any(controller_coordinator.path_overlap(a,b) for a in row["paths"] for b in other["paths"])

def review_conflict(row, other):
    return row.get("base_branch")==other.get("base_branch") or developer_conflict(row,other)

def draft_actions(root,rows,results,running,review_row=None,probe=None):
    """One mutually exclusive actionable state per draft.
    Remote HEAD metadata is not a review and consumes no model slot.
    Never infer acceptance or erase a rejected exact SHA from a transport error.
    """
    journal=controller_coordinator.read(root/"coordinator-review.json",{})
    for row,number in controller_coordinator.candidates(root,rows,results):
        if any(developer_conflict(row,r) for r in running) or (review_row is not None and review_conflict(row,review_row)):
            continue
        last=journal.get(str(number),{})
        if last.get("state")=="accepted":
            continue
        sha=last.get("sha")
        reason=last.get("repair_reason")
        if last.get("state")=="hold" and isinstance(reason,str) and 1<=len(reason)<=800 and isinstance(sha,str) and re.fullmatch(r"[0-9a-f]{40}",sha):
            # A published successor or external change must be verified before
            # the next review. An unchanged rejected draft is developer work.
            try:
                remote=probe(number) if probe else sha
            except (OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError):
                yield row,number,"metadata_unavailable",sha,reason
                continue
            if remote!=sha:
                yield row,number,"review",remote,None
            elif row.get("local_repair") is True and controller_coordinator.repair_attempt(root,number,sha) is not None:
                yield row,number,"repair",sha,reason
            else:
                yield row,number,"blocked_repair",sha,reason
            continue
        yield row,number,"review",sha,None

def choose_review(root,rows,results,running,now=None,actions=None):
    now=time.time() if now is None else now
    journal=controller_coordinator.read(root/"coordinator-review.json",{})
    requested=controller_coordinator.trigger(root) is not None
    available=list(draft_actions(root,rows,results,running) if actions is None else actions)
    available.sort(key=lambda item:(journal.get(str(item[1]),{}).get("at",0),item[0]["priority"],item[0]["issue"]))
    for row,number,state,sha,reason in available:
        if state!="review" or any(review_conflict(row,r) for r in running):
            continue
        last=journal.get(str(number),{})
        if requested or now-last.get("at",0)>=60:
            return row
    return None

def repair_candidates(root,rows,results,running,review_row=None,actions=None):
    available=draft_actions(root,rows,results,running,review_row) if actions is None else actions
    for row,number,state,sha,reason in available:
        if state=="repair" and not any(developer_conflict(row,r) for r in running) and not (review_row is not None and review_conflict(row,review_row)):
            yield row,number,sha,reason

def remote_draft_head(number,cache,now=None):
    now=time.monotonic() if now is None else now
    if number in cache and now-cache[number][0]<30:
        return cache[number][1]
    p=controller_coordinator.gh(controller_coordinator.PREFIX+"/pulls/"+str(number))
    sha=p["head"]["sha"]
    if not isinstance(sha,str) or not re.fullmatch(r"[0-9a-f]{40}",sha):
        raise ValueError("invalid remote draft head")
    cache[number]=(now,sha)
    return sha

def plan_with_review(rows,review_row,parallel):
    if review_row is None:
        return plan(rows,max_parallel=parallel)
    # A coordinator future uses one model slot; suppress conflicting rows
    # before planning, but retain every row for dependency resolution.
    adjusted=[dict(r,status="blocked") if r["status"]=="ready" and review_conflict(r,review_row) else r for r in rows]
    if parallel==1:
        return []
    return plan(adjusted,max_parallel=parallel-1)

def admission_closed(root):
    """DRAIN lets running workers publish; STOP remains a hard publication guard."""
    return (root/"STOP").exists() or (root/"DRAIN").exists()

def run_queue(a,root,script,statefile,donefile,state,results):
    boot=boot_id()
    # A reservation remains durable until it is either recovered or reported.
    # An in-session process crash cannot prove the old child has exited.
    interrupted={key for key,status in results.items() if status=="reserved"}
    with concurrent.futures.ThreadPoolExecutor(max_workers=a.parallel) as pool:
        active={}
        repair_futures=set()
        repair_cooldown={}
        head_cache={}
        coordination=None
        review_row=None
        budget_lock=threading.Lock()
        def reserve_slot():
            with budget_lock:
                if admission_closed(root) or provider_pause_active(root):
                    return False
                if not reserve(state,datetime.now(timezone.utc).date().isoformat(),a.daily_reservation,a.per_task):
                    return False
                save(statefile,state)
                return True
        while active or coordination is not None or not admission_closed(root):
            if coordination is not None and coordination.done():
                try:
                    coordination.result()
                except Exception as exc:
                    print("COORDINATION_FAILED:",type(exc).__name__,flush=True)
                coordination=None
                review_row=None
            for future,row in list(active.items()):
                if not future.done():
                    continue
                if future in repair_futures:
                    try:
                        future.result()
                    except (OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError) as exc:
                        print("DEVELOPER_REPAIR_PENDING:",task_key(row),type(exc).__name__,flush=True)
                    except Exception as exc:
                        print("DEVELOPER_REPAIR_FAILED:",task_key(row),type(exc).__name__,flush=True)
                    repair_futures.remove(future)
                    repair_cooldown[task_key(row)]=time.time()+60
                    del active[future]
                    # Keep original draft receipt and rejected-SHA journal.
                    # The next coordinator pass verifies the new remote head.
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
            if admission_closed(root):
                write_status(root,"stopping",active.values(),coordinator_running=coordination is not None,coordinator_task=task_key(review_row) if review_row else None,capacity=a.parallel)
                futures=list(active)+([coordination] if coordination is not None else [])
                if futures:
                    concurrent.futures.wait(futures,timeout=15,return_when=concurrent.futures.FIRST_COMPLETED)
                continue
            reason="idle"
            capable=bool(a.remote and a.publish)
            waiting=[]
            review=[]
            try:
                if a.remote:
                    controller_remote.refresh(root,a.queue)
                rows=load(a.queue,[])
                recoverable=set()
                for row in rows:
                    key=task_key(row)
                    if key in interrupted:
                        if can_recover(root,row,boot):
                            recoverable.add(key)
                        else:
                            results[key]="blocked:interrupted"
                            save(donefile,results)
                            notify_result(root,row,"blocked:interrupted",a.publish)
                            interrupted.remove(key)
                delivery_retry={task_key(row) for row in rows if capable and can_resume_delivery(root,row,results)}
                recoverable.update(delivery_retry)
                recoverable.update(task_key(row) for row in rows if capable and can_resume_incomplete(root,script.parent.parent,row,results))
                review=[task_key(row) for row in rows if row["status"]=="ready" and results.get(task_key(row)) in ("draft_pr","review_required","no_changes")]
                rows_before_effective=rows
                rows=effective_rows(rows,{k:v for k,v in results.items() if k not in recoverable},active.values())
                waiting=[task_key(row) for row in rows if row["status"]=="ready"]
                paused=provider_pause_active(root)
                actions=[]
                if capable and not paused:
                    actions=list(draft_actions(root,rows_before_effective,results,list(active.values()),review_row,probe=lambda n: remote_draft_head(n,head_cache)))
                    # Recover an explicitly finished, preserved worktree without
                    # turning the rejected draft into another coordinator review.
                    for index,(row,number,stage,sha,reason_text) in enumerate(actions):
                        if stage!="blocked_repair" or repair_cooldown.get(task_key(row),0)>time.time():
                            continue
                        if controller_coordinator.finished_repair_can_resume(root,row,number,sha):
                            try:
                                controller_coordinator.authorize_repair_resume(root,script.parent.parent,row,number,sha)
                            except (OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError) as exc:
                                repair_cooldown[task_key(row)]=time.time()+60
                                print("REPAIR_RECOVERY_BLOCKED:",task_key(row),str(exc)[:200] if isinstance(exc,controller_coordinator.Hold) else type(exc).__name__,flush=True)
                            else:
                                actions[index]=(row,number,"repair",sha,reason_text)
                    for row,number,sha,reason_text in repair_candidates(root,rows_before_effective,results,list(active.values()),review_row,actions=actions):
                        if len(active)+int(coordination is not None)>=a.parallel:
                            break
                        if repair_cooldown.get(task_key(row),0)>time.time() or any(developer_conflict(row,r) for r in active.values()):
                            continue
                        if not reserve_slot():
                            break
                        future=pool.submit(controller_coordinator.run_developer_repair,root,script.parent.parent,row,number,sha,reason_text,a.per_task)
                        active[future]=row
                        repair_futures.add(future)
                    # Rebuild effective active scopes after allocating repairs.
                    rows=effective_rows(rows_before_effective,{k:v for k,v in results.items() if k not in recoverable},active.values())
                    waiting=[task_key(row) for row in rows if row["status"]=="ready"]
                    review=[task_key(item[0]) for item in actions if item[2]=="review"]
                if capable and coordination is None and len(active)<a.parallel and not paused:
                    candidate=choose_review(root,rows_before_effective,results,list(active.values()),actions=actions)
                    if candidate is not None or (not active and controller_coordinator.trigger(root)):
                        review_row=candidate
                        keys={task_key(candidate)} if candidate else set()
                        coordination=pool.submit(controller_coordinator.run_once,root,script.parent.parent,rows_before_effective,dict(results),reserve_review=reserve_slot,repair_allowance=a.per_task,review_keys=keys,defer_repairs=True)
                if paused:
                    selected=[]
                elif coordination is not None and review_row is None:
                    # A manual receipt-only pass also occupies a slot.
                    selected=plan(rows,max_parallel=a.parallel-1) if a.parallel>1 else []
                else:
                    selected=plan_with_review(rows,review_row,a.parallel)
                if paused:
                    reason="provider_pause"
                elif waiting and not selected:
                    reason="waiting_for_dependency_or_worker"
                elif not waiting and not active:
                    reason=("awaiting_review" if any(item[2]=="review" for item in actions) else "blocked_repair" if any(item[2]=="blocked_repair" for item in actions) else "no_eligible_work")
            except (OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError) as exc:
                print("QUEUE_UNAVAILABLE:",type(exc).__name__,flush=True)
                selected=[]
                rows=[]
                recoverable=set()
                delivery_retry=set()
                reason="queue_unavailable"
            day=datetime.now(timezone.utc).date().isoformat()
            for task in selected:
                if admission_closed(root):
                    break
                row=next(r for r in rows if (r["issue"],r.get("generation",1))==task.key)
                if a.remote and a.publish and row.get("follow_base") is True and task_key(row) not in results:
                    try:
                        row=controller_coordinator.pin_unstarted(root,row,results)
                    except (OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError) as exc:
                        print("BASE_PIN_PENDING:",task_key(row),type(exc).__name__,flush=True)
                        continue
                if provider_pause_active(root) or not reserve_slot():
                    reason="provider_pause" if provider_pause_active(root) else "budget_limit"
                    break
                key=task_key(row)
                recovering=key in recoverable
                if recovering:
                    previous=task_record(root,row)
                    archive=previous.with_suffix(".before-recovery.json")
                    if not archive.exists():
                        save(archive,load(previous,{}))
                save(task_record(root,row),{"row":row,"boot":boot,"recovered":recovering,"delivery_retry":key in delivery_retry})
                results[key]="reserved"
                save(donefile,results)
                interrupted.discard(key)
                active[pool.submit(run_task,root,script,row,a.per_task,a.publish)]=row
            active_keys={task_key(row) for row in active.values()}
            if active and reason not in ("provider_pause","budget_limit","queue_unavailable"):
                reason="working"
            if coordination is not None:
                reason="coordinating" if not active else "working"
            write_status(root,reason,active.values(),[key for key in waiting if key not in active_keys],review,capable,coordination is not None,task_key(review_row) if review_row else None,a.parallel)
            futures=list(active)+([coordination] if coordination is not None else [])
            if futures:
                concurrent.futures.wait(futures,timeout=5,return_when=concurrent.futures.FIRST_COMPLETED)
            elif not admission_closed(root):
                for _ in range(12):
                    if admission_closed(root) or (capable and not provider_pause_active(root) and controller_coordinator.trigger(root)):
                        break
                    time.sleep(5)

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--queue", required=True, type=Path)
    p.add_argument("--root", required=True, type=Path)
    p.add_argument("--daily-reservation", type=int, default=None)
    p.add_argument("--per-task", type=int, default=0, help="Optional token ceiling per turn; zero for ChatGPT subscription")
    p.add_argument("--parallel", type=int, default=2, choices=(1,2))
    p.add_argument("--execute", action="store_true")
    p.add_argument("--remote", action="store_true")
    p.add_argument("--publish", action="store_true")
    a = p.parse_args()
    if a.per_task < 0 or (a.daily_reservation is not None and (a.per_task == 0 or a.daily_reservation < a.per_task)):
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
