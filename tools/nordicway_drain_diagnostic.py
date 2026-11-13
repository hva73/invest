"""Diagnostic-only stop/drain coordinator; no update or marker mutation.

The caller must provide reviewed, situation-specific validation of the
current recovery marker, bridge, installed files and healthy runtime. The
same deployment lock is held across stop, inspection and verified restart.
"""
def diagnose(adapter, validate, stopped_motor, wait_for_quiescence, classify):
    result={'status':'stopped','selector_started_again':False,'health_verified':False}
    try:
        with adapter.lock():
            if validate() is not True: raise ValueError('validation_unverified')
            if adapter.service_status()!='started':
                return {'status':'baseline_unavailable','selector_started_again':False,'health_verified':False}
            stop_attempted=True
            try:
                adapter.stop_service()
                with stopped_motor(adapter.target/'var'):
                    reason=wait_for_quiescence(adapter.target/'var'/'escape.db')
                    allowed={'passenger_active','database_in_use','cron_unverified',
                             'database_unavailable','process_inspection_unavailable',None}
                    if reason not in allowed: reason='unavailable'
                    result['drain_reason']=reason
                    if reason=='passenger_active':
                        if adapter.service.status()!='stopped': raise ValueError('selector_not_stopped')
                        result['classification']=classify(adapter.target)
                        if adapter.service.status()!='stopped': raise ValueError('selector_not_stopped')
                result['status']='observed'
            except Exception:
                result['status']='observation_unavailable'
            finally:
                if stop_attempted:
                    try:
                        adapter.start_service()
                        result['selector_started_again']=True
                        adapter.verify_recovery_health()
                        result['health_verified']=True
                    except Exception:
                        result['status']='recovery_unverified'
            return result
    except Exception:
        return {'status':'validation_or_lock_failed','selector_started_again':False,'health_verified':False}
