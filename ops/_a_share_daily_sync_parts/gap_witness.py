"""Bounded date-only witness through the original daily SDK transport."""
from __future__ import annotations


def obtain(scope, package, target, last_date, *, api_factory, hosts, deadline,
           request_deadline, timeout, run_id, recorded_at):
    # Reuse the accepted original TDX host before the general SDK host list.
    candidates = list(dict.fromkeys([('180.153.18.170',7709), *hosts]))[:3]
    if api_factory is scope.get('_runtime_api_factory'):
        from .tdx_mac_adapter import MacDailyHqAPI
        api_factory = lambda host, port: MacDailyHqAPI(auto_retry=False,raise_exception=True)
    snapshots, attempts = [], []
    for ordinal, (host, port) in enumerate(candidates, 1):
        remaining = deadline - scope['time'].monotonic()
        if remaining <= 0:
            error=scope['SyncTimeoutError']('SYMBOL', request_deadline, request_deadline)
            error.witness_snapshots=snapshots;error.witness_attempts=attempts
            raise error
        api = None
        request = dict(code=str(target.code), market=int(target.market), kline=9, start=0,
                       count=32, target_date=str(package.target), source_kind='TDX_MAC_DATE_WITNESS')
        started = scope['time'].monotonic()
        dispatched=0
        try:
            with scope['_deadline_guard'](min(request_deadline,remaining), scope='REQUEST'):
                api = api_factory(host,port)
                if getattr(api,'response_ref',None) is not None:
                    request['cached_original_response'] = api.response_ref
                if not api.connect(host,port,time_out=timeout):
                    raise ValueError('G4DAY_WITNESS_CONNECT_FALSE')
                dispatched=1
                response = api.get_security_bars(9,int(target.market),str(target.code),0,32)
            ref = scope['_write_raw_response_snapshot'](target_date=package.target,target=target,
                request=request,host=scope['_host_label'](host,port),host_ordinal=ordinal,
                attempt_ordinal=ordinal,response_rows=response,run_id=run_id,observed_at=recorded_at)
            snapshots.append(ref)
            attempts.append(dict(host=scope['_host_label'](host,port),requests=1,
                                 request_budget_seconds=min(request_deadline,remaining),
                                 elapsed_seconds=scope['time'].monotonic()-started))
            bars, reason = package.witnessed_lookup(int(target.market),str(target.code),last_date,response,ref)
            return bars, reason, snapshots, attempts
        except Exception as error:
            attempts.append(dict(host=scope['_host_label'](host,port),error=repr(error),
                                 requests=dispatched,request_budget_seconds=min(request_deadline,remaining),
                                 elapsed_seconds=scope['time'].monotonic()-started))
            snapshots.append(scope['_write_raw_response_snapshot'](target_date=package.target,
                target=target,request=request,host=scope['_host_label'](host,port),
                host_ordinal=ordinal,attempt_ordinal=ordinal,response_error=repr(error),
                run_id=run_id,observed_at=recorded_at))
            if isinstance(error,scope['SyncTimeoutError']):
                error.witness_snapshots=snapshots;error.witness_attempts=attempts
                raise
        finally:
            scope['_disconnect_session'](api)
    return [], 'G4DAY_WITNESS_SOURCE_UNAVAILABLE', snapshots, attempts
