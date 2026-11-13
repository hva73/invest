"""Observe a coordinated selector stop and recovery, without altering either."""
import time

def observe(service, classify, *, timeout=600, interval=1, clock=time.monotonic, sleep=time.sleep):
    try:
        if service.status()!='started': return {'status':'baseline_not_running'}
        deadline=clock()+timeout; first=None; last=None
        while clock()<deadline:
            current=service.status()
            if current=='stopped':
                snapshot=classify()
                if first is None: first=snapshot
                last=snapshot
            elif current=='started' and first is not None:
                return {'status':'observed','selector_started_again':True,'first':first,'last':last}
            elif current!='started':
                return {'status':'selector_unavailable'}
            sleep(interval)
        return {'status':'timeout','stop_observed':first is not None}
    except (OSError,ValueError,TimeoutError):
        return {'status':'observation_unavailable'}
