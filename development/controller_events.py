"""Read bounded Codex JSONL events without logging model/tool content."""
import json
import os
import re
import selectors
import signal
import subprocess
import tempfile
import time
from types import SimpleNamespace

TEST_COMMAND=re.compile(r"(?:^|[\s;&|])(?:pytest\b|(?:python(?:3(?:\.\d+)?)?\s+(?:-B\s+)?-m\s+(?:unittest|pytest)\b)|(?:npm|pnpm|yarn)\s+(?:run\s+)?test\b|node\s+tests/)")
KEEP={"thread.started","turn.completed","turn.failed","error"}
LIMIT=262144

def consume(event,phase):
    if not isinstance(event,dict):
        return None,None
    kind=event.get("type")
    if kind in KEEP:
        # Retain only bounded structured events, not arbitrary tool output.
        line=json.dumps(event)
        return (line if len(line)<=8192 else None),None
    item=event.get("item")
    if not isinstance(item,dict):
        return None,None
    if kind=="item.started" and item.get("type")=="command_execution":
        command=item.get("command","")
        if isinstance(command,str) and TEST_COMMAND.search(command[:10000]):
            phase("TESTING")
    if kind=="item.completed" and item.get("type")=="agent_message":
        body=item.get("text","")
        lines=body.rstrip().splitlines() if isinstance(body,str) else []
        return None,bool(lines and lines[-1].strip()=="ESCAPE_DRAFT_READY")
    return None,None

def run(command,prompt,env,timeout,phase=lambda _:None):
    if timeout<=0:
        raise subprocess.TimeoutExpired(command,timeout)
    deadline=time.monotonic()+timeout
    events=[]
    ready=False
    pending=b""
    dropping=False
    with tempfile.TemporaryFile() as input_file:
        input_file.write(prompt.encode("utf-8"));input_file.seek(0)
        proc=subprocess.Popen(command,stdin=input_file,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                              env=env,start_new_session=True)
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(proc.stdout,selectors.EVENT_READ)
                while True:
                    remain=deadline-time.monotonic()
                    if remain<=0 or not selector.select(remain):
                        raise subprocess.TimeoutExpired(command,timeout)
                    chunk=os.read(proc.stdout.fileno(),65536)
                    if not chunk:
                        break
                    parts=chunk.split(b"\n")
                    for i,part in enumerate(parts):
                        end=i<len(parts)-1
                        if not dropping:
                            pending+=part
                            if len(pending)>LIMIT:
                                pending=b"";dropping=True
                        if end:
                            if not dropping:
                                try:
                                    line,flag=consume(json.loads(pending),phase)
                                    if line:
                                        events.append(line)
                                        if len(events)>1000:
                                            raise ValueError("too_many_control_events")
                                    if flag is not None:ready=flag
                                except (UnicodeError,json.JSONDecodeError):
                                    pass
                            pending=b"";dropping=False
                if pending and not dropping:
                    try:
                        line,flag=consume(json.loads(pending),phase)
                        if line:events.append(line)
                        if flag is not None:ready=flag
                    except (UnicodeError,json.JSONDecodeError):
                        pass
            remaining=deadline-time.monotonic()
            if remaining<=0:raise subprocess.TimeoutExpired(command,timeout)
            rc=proc.wait(timeout=remaining)
            return SimpleNamespace(returncode=rc,stdout="\n".join(events),draft_ready=ready)
        finally:
            if proc.poll() is None:
                try:os.killpg(proc.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                proc.wait()
            proc.stdout.close()
