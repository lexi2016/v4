"""Run-local SDK evidence for the existing HK Futu producer; no acquisition."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import os
import tempfile
from decimal import Decimal
from pathlib import Path
from typing import Mapping

SAFETY = dict(production_allowed=False, buy_gate_updated=False, orders_sent=False)
SCHEMA = 'hk_provider_sdk_capture.v1'


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec='microseconds')


def encode(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def sdk_value(value):
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else {'$float':repr(value)}
    if isinstance(value, Decimal):return {'$decimal':str(value)}
    if isinstance(value, (dt.datetime, dt.date, dt.time)):return {'$datetime':value.isoformat()}
    if isinstance(value, bytes):return {'$bytes_hex':value.hex()}
    if isinstance(value, Mapping):
        if any(not isinstance(k,str) for k in value):raise TypeError('SDK mapping key is not a string')
        return {k:sdk_value(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [sdk_value(v) for v in value]
    if type(value).__name__ in ('NAType','NaTType'):return {'$missing_scalar':type(value).__name__}
    item=getattr(value,'item',None)
    if callable(item):
        scalar=item()
        if scalar is not value:return sdk_value(scalar)
    raise TypeError('unsupported SDK value: '+type(value).__name__)


def frame_material(frame):
    """Keep SDK columns/order/index/dtypes and every row, before dict projection."""
    if callable(getattr(frame,'itertuples',None)):
        columns=list(frame.columns)
        values=list(frame.itertuples(index=False,name=None))
        material=dict(kind='SDK_DATAFRAME_STRUCTURED',columns=sdk_value(columns),
            row_values=sdk_value(values),index=sdk_value(list(frame.index)),
            dtypes=[str(v) for v in frame.dtypes])
        if any(not isinstance(c,str) for c in columns) or len(set(columns))!=len(columns):
            return material, None
        return material,[dict(zip(columns,row)) for row in values]
    if isinstance(frame,(list,tuple)) and all(isinstance(row,Mapping) for row in frame):
        rows=[dict(row) for row in frame]
        return dict(kind='SDK_RECORD_SEQUENCE_STRUCTURED',rows=sdk_value(rows)),rows
    # Retain an SDK error scalar, if serializable, without pretending it is rows.
    return dict(kind='SDK_NON_FRAME_RESPONSE',value=sdk_value(frame)),None


def _write(path,raw,*,immutable):
    if path.is_symlink():raise ValueError('HK_CAPTURE_SYMLINK_DENIED')
    if immutable and path.exists():
        if path.read_bytes()!=raw:raise ValueError('HK_CAPTURE_IMMUTABLE_CONFLICT')
        return
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix='.'+path.name,dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as output:
            output.write(raw);output.flush();os.fsync(output.fileno())
        if immutable:
            try:os.link(name,path)
            except FileExistsError:
                if path.read_bytes()!=raw:raise ValueError('HK_CAPTURE_IMMUTABLE_CONFLICT')
        else:os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)


class CaptureFailure(ValueError):
    def __init__(self,message,refs):
        super().__init__(message)
        self.capture_refs=refs


class ProviderCapture:
    def __init__(self,path,target,*,source_path):
        if path is None:raise CaptureFailure('HK_CAPTURE_PATH_REQUIRED',{})
        self.path=Path(path)
        if not self.path.is_absolute():raise CaptureFailure('HK_CAPTURE_PATH_MUST_BE_ABSOLUTE',{})
        if self.path.exists() or self.path.is_symlink():raise CaptureFailure('HK_CAPTURE_RUN_ALREADY_EXISTS',{})
        self.target=target;self.responses=[];self.rows=[];self.codes=[];self.code_states={};self.requested=set()
        self.context_error=None;self.started=now();self.closed=False
        self.source=dict(path=str(source_path),sha256=digest(Path(source_path).read_bytes()),helper_sha256=digest(Path(__file__).read_bytes()))
        self._save('PENDING')  # storage must work before the first SDK call

    def _artifact(self,name,payload):
        path=self.path.with_name(self.path.stem+'.'+name+'.json');raw=encode(payload)
        _write(path,raw,immutable=True)
        return dict(relative=path.name,sha256=digest(raw),bytes=len(raw))

    def refs(self):
        raw=self.path.read_bytes()
        # A failed progress write must not label an older durable manifest with
        # a newer in-memory status. Incomplete retention is flagged separately.
        durable=json.loads(raw)
        return dict(schema_version=SCHEMA,capture_run_id=self.path.stem,manifest_path=str(self.path),manifest_sha256=digest(raw),status=durable['status'])

    def _save(self,status,*,error=None):
        self.status=status
        payload=dict(schema_version=SCHEMA,status=status,target_date=self.target,capture_run_id=self.path.stem,started_at=self.started,
            recorded_at=now(),source=self.source,provider_identity='FUTU_OPEND_SDK',
            container_identity='SDK_STRUCTURED_RESPONSE_NOT_WIRE_BYTES',responses=self.responses,
            requested_union_codes=self.codes,requested_union_complete=bool(self.codes),
            response_row_count=len(self.rows),context_error=self.context_error,error=error,**SAFETY)
        if hasattr(self,'row_ref'):payload.update(row_dispositions=self.row_ref,code_dispositions=self.code_ref)
        _write(self.path,encode(payload),immutable=False)

    def request(self,kind,arguments):
        if kind=='get_market_snapshot':self.requested.update(arguments['codes'])
        return dict(batch=len(self.responses),method=kind,arguments=arguments,requested_at=now())

    def response(self,request,ret,frame,*,completed_at=None,error=None):
        completed_at=completed_at or now()
        converted=None;serialization_error=None
        try:
            if error is not None:
                # The SDK raised: there is no returned frame to validate. Keep
                # the original exception material, then let its caller rethrow.
                material=dict(kind='SDK_EXCEPTION_NO_RESPONSE')
            else:
                material,converted=frame_material(frame)
            return_value=sdk_value(ret)
        except (TypeError,ValueError,OverflowError) as failure:
            serialization_error=type(failure).__name__+':'+str(failure)
            material=dict(kind='SDK_SERIALIZATION_UNSUPPORTED',frame_type=type(frame).__name__)
            return_value=dict(type=type(ret).__name__)
        row_values=material.get('row_values',material.get('rows',[]))
        payload=dict(schema_version=SCHEMA,**request,completed_at=completed_at,available_at_observed=completed_at,
            return_code=return_value,return_code_type=type(ret).__name__,sdk_response=material,
            serialization_complete=serialization_error is None,serialization_error=serialization_error,
            outcome='SDK_EXCEPTION' if error is not None else 'SDK_RETURNED',error=error,**SAFETY)
        ref=self._artifact('response-'+str(request['batch']).zfill(4),payload)
        response=dict(**request,completed_at=completed_at,return_code_type=type(ret).__name__,return_code=return_value,
            row_count=len(row_values),artifact=ref,serialization_complete=serialization_error is None,error=error)
        self.responses.append(response)
        observations=[]
        for ordinal,_ in enumerate(row_values):
            original=converted[ordinal] if converted is not None else None
            row=dict(batch=request['batch'],method=request['method'],ordinal=ordinal,response_sha256=ref['sha256'],
                response_relative=ref['relative'],disposition='NOT_EVALUATED_CAPTURE_ABORTED',reasons=[],code=None)
            self.rows.append(row);observations.append((original,row))
        # Establish ALL physical references before inspecting any SDK code.
        # Missing pandas scalars must never be coerced through boolean truth.
        for original,row in observations:
            if original is not None:
                value=original.get('code')
                if isinstance(value,str) and value.strip():
                    row['code']=value.strip().upper()
                else:
                    row.update(disposition='INVALID_CODE',reasons=['missing_or_malformed_code'])
        self._save('PENDING')
        if error is not None:return observations
        if serialization_error:raise ValueError('HK_CAPTURE_SERIALIZATION_UNSUPPORTED')
        if converted is None:raise ValueError('HK_CAPTURE_FRAME_SCHEMA_UNUSABLE')
        return observations

    def set_codes(self,codes):
        self.codes=list(codes);self._save('PENDING')

    def snapshots(self,observations,universe):
        groups={}
        for original,ref in observations:
            code=ref['code']
            if ref['disposition']=='INVALID_CODE':
                continue
            if code not in universe:
                ref.update(disposition='UNMATCHED_CODE',reasons=['not_in_requested_union'])
            else:groups.setdefault(code,[]).append((original,ref))
        selected={}
        for code,items in groups.items():
            signatures={encode(sdk_value(raw)) for raw,_ in items}
            if len(signatures)!=1:
                for _,ref in items:ref.update(disposition='CONFLICTING_SNAPSHOT',reasons=['conflicting_same_code_facts'])
                self.code_states[code]=dict(code=code,disposition='PENDING_CONFLICT',reasons=['conflicting_same_code_facts'])
            else:
                selected[code]=items[0][0]
                for index,(_,ref) in enumerate(items):
                    if index:ref.update(disposition='DUPLICATE_IDENTICAL',representative=dict(batch=items[0][1]['batch'],ordinal=items[0][1]['ordinal']),reasons=['identical_retained_reference'])
        return selected

    def disposition(self,code,*,accepted=None,reasons=()):
        state='ACCEPTED' if accepted is not None else ('MISSING_RESPONSE' if not any(row['method']=='get_market_snapshot' and row['code']==code for row in self.rows) else 'EXCLUDED')
        self.code_states[code]=dict(code=code,disposition=state,reasons=list(reasons))
        for ref in self.rows:
            if ref['method']=='get_market_snapshot' and ref['code']==code:
                if ref['disposition']!='DUPLICATE_IDENTICAL':ref.update(disposition=state,reasons=list(reasons))
                else:ref['representative_disposition']=state
                if accepted is not None:ref.update(normalized_row=sdk_value(accepted),expected_packed_relative='vipdoc/ds/lday/71#'+code[3:]+'.day')

    def finish(self,status,*,error=None):
        if self.closed:return self.refs()
        for code in self.codes:
            if code not in self.code_states:
                self.code_states[code]=dict(code=code,disposition='NOT_EVALUATED_AFTER_ABORT' if code in self.requested else 'NOT_REQUESTED_AFTER_ABORT',reasons=['capture_aborted'])
        self.row_ref=self._artifact('row-dispositions',dict(rows=self.rows,row_count=len(self.rows),**SAFETY))
        states=[self.code_states[code] for code in self.codes]
        self.code_ref=self._artifact('code-dispositions',dict(codes=states,requested_union_count=len(self.codes),**SAFETY))
        self._save(status,error=error);self.closed=True
        return self.refs()

    def fail(self,error):
        try:refs=self.finish('FAILED',error=type(error).__name__+':'+str(error))
        except Exception as storage:
            # The dated lane can still reference previously durable progress.
            refs=self.refs() if self.path.is_file() else {}
            refs=dict(refs,retention_status='INCOMPLETE_STORAGE_FAILURE',storage_error=type(storage).__name__)
        return CaptureFailure(str(error),refs)


def lane_receipt(refs,*,packed=None,authority=None,error=None):
    """Immutable link from the collected SDK/ledger evidence to the old pipeline."""
    if not refs:return {}
    path=Path(refs['manifest_path']);raw=path.read_bytes()
    if digest(raw)!=refs['manifest_sha256']:raise ValueError('HK_CAPTURE_MANIFEST_CHANGED')
    manifest=json.loads(raw)
    payload=dict(schema_version='hk_provider_capture_lane.v1',status='FAILED' if error else 'READY',
        target_date=manifest['target_date'],capture=refs,provider_identity='FUTU_OPEND_SDK',
        container_identity='VIPDOC_71_DAY',packed=packed,authority=authority,error=error,**SAFETY)
    target=path.with_name(path.stem+'.lane.json');encoded=encode(payload);_write(target,encoded,immutable=True)
    return dict(**refs,lane_receipt_path=str(target),lane_receipt_sha256=digest(encoded),lane_status=payload['status'])
