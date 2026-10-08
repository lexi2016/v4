"""Record the existing owner's snapshot calls without adding calls or retries.

This callable is installed only by an explicitly configured owner. It retains
complete SDK reference fields and real per-call clocks. It does not admit its
own evidence, publish a master, assert membership, or certify provider origin.
"""
import copy
from datetime import datetime, timezone
import numbers
import re
import threading

from .contracts import aware, sha
from .digests import canonical_bytes, sha256_json
from .provider_evidence import encode_sdk_value


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


class SnapshotRecorder:
    """Serial observer for an existing get_market_snapshot-compatible callable.

    Returned SDK objects and raised provider exceptions are passed through.
    Recording failures prevent seal, but never replace an SDK success with a
    recording exception. Only the owner may choose to retry a failed call.
    """
    def __init__(self,owner_call,*,producer_code_sha256):
        if not callable(owner_call):raise ValueError('OWNER_CALL_REQUIRED')
        self._owner=owner_call;self._producer_sha=sha(producer_code_sha256)
        self._lock=threading.RLock();self._records=[];self._batches=[]
        self._attempts=[];self._requested=set();self._successful=set()
        self._invalid=False;self._sealed=None

    def __call__(self,*args,**kwargs):
        with self._lock:
            if self._sealed is not None:raise ValueError('RECORDER_SEALED')
            if len(self._attempts)>=10000:
                self._invalid=True
                return self._owner(*args,**kwargs)
            try:
                codes=args[0] if args else kwargs.get('code_list',kwargs.get('codes'))
                requested=_now();aware(requested)
                if not isinstance(codes,(list,tuple)):raise ValueError('REQUEST_CODES_INVALID')
                expected=list(codes)
                if (not expected or len(expected)>10000
                    or any(not isinstance(c,str) or not re.fullmatch(r'HK\.[0-9]{5}',c) for c in expected)
                    or len(expected)!=len(set(expected))):raise ValueError('REQUEST_CODES_INVALID')
                if self._successful.intersection(expected):self._invalid=True
                self._requested.update(expected)
            except Exception:
                requested=None;expected=[];self._invalid=True
            attempt=dict(requested_at=requested,codes=expected,status='REQUESTED')
            self._attempts.append(attempt)
            try:
                response=self._owner(*args,**kwargs)
            except BaseException as error:
                try:
                    attempt['completed_at']=_now()
                    if requested is None or aware(attempt['completed_at'])<aware(requested):
                        raise ValueError('CAPTURE_CLOCK_INVALID')
                except Exception:
                    attempt['completed_at']=None;self._invalid=True
                attempt.update(status='PROVIDER_EXCEPTION',error_type=type(error).__name__)
                raise
            try:
                completed=_now();attempt['completed_at']=completed
                if requested is None or aware(completed)<aware(requested):raise ValueError('CAPTURE_CLOCK_INVALID')
                if not isinstance(response,tuple) or len(response)!=2:raise ValueError('SDK_RESPONSE_INVALID')
                ret,frame=response
                if isinstance(ret,bool) or not isinstance(ret,numbers.Integral):raise ValueError('SDK_STATUS_INVALID')
                attempt['ret']=int(ret)
                if ret!=0:
                    attempt['status']='PROVIDER_ERROR'
                    return response
                records=copy.deepcopy(frame.to_dict('records'))
                if (not isinstance(records,list) or any(not isinstance(row,dict) for row in records)
                    or len(records)!=len(expected)):raise ValueError('SDK_ROWS_INVALID')
                returned=[row.get('code') for row in records]
                if (any(not isinstance(c,str) for c in returned) or len(set(returned))!=len(returned)
                    or set(returned)!=set(expected) or self._successful.intersection(returned)):
                    raise ValueError('SDK_CODES_MISMATCH')
                if len(self._records)+len(records)>10000:raise ValueError('SDK_ROW_LIMIT')
                lookup={row['code']:row for row in records}
                ordered=[lookup[code] for code in expected]
                encoded=encode_sdk_value(ordered);canonical_bytes(encoded)
                batch=dict(requested_at=requested,completed_at=completed,codes=expected,
                           provider_returned_codes=returned,raw_records_sha256=sha256_json(encoded))
                self._records.extend(ordered);self._batches.append(batch);self._successful.update(returned)
                attempt['status']='RECORDED'
            except Exception as error:
                self._invalid=True
                attempt.update(status='RECORDING_FAILED',error_type=type(error).__name__)
            return response

    def seal(self):
        """Return detached in-process SDK records plus a serializable receipt.

        No durable file, trust binding or operator approval is created here.
        Failed provider attempts remain visible; an owner-chosen successful
        retry can complete their coverage without this wrapper retrying itself.
        """
        with self._lock:
            if self._sealed is not None:return copy.deepcopy(self._sealed)
            if self._invalid or not self._records or self._requested!=self._successful:
                raise ValueError('CAPTURE_INCOMPLETE')
            available=_now()
            if any(aware(attempt['completed_at'])>aware(available) for attempt in self._attempts):
                raise ValueError('CAPTURE_CLOCK_INVALID')
            receipt=dict(schema_version='v5.futu_snapshot_receipt.v1',
                         source_kind='FUTU_OPEND_MARKET_SNAPSHOT',producer_code_sha256=self._producer_sha,
                         available_at=available,batches=copy.deepcopy(self._batches),
                         attempts=copy.deepcopy(self._attempts),observation_kind='SDK_CALL_RECORDING',
                         raw_records_sha256=sha256_json(encode_sdk_value(self._records)),
                         membership_verified=False,natural_verified=False,production_allowed=False,
                         buy_gate_updated=False,orders_sent=False)
            canonical_bytes(receipt)
            self._sealed=(copy.deepcopy(self._records),receipt)
            return copy.deepcopy(self._sealed)
