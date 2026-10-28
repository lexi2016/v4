"""Immutable per-article result snapshots behind one atomic per-job index."""
from __future__ import annotations
from copy import deepcopy
import hashlib
import json
import re
from typing import Any
from infrastructure.owned_io import SafeRoot
from .announcement_preprocessing import encoded, digest

SCHEMA='v4.manager_workbench.announcement_delivery.v1'
ANALYSIS_SCHEMA='v4.manager_workbench.announcement_analysis_projection.v1'
_EVIDENCE_FIELDS=('facts','changes','impact','confirmation_conditions','counter_evidence')
_DECISION_FIELDS=('disposition','direction','selection_basis','evidence_sufficiency','reason')


def read_analysis(io: SafeRoot, delivery: dict[str, Any], binding: dict[str, Any]) -> dict[str, Any]:
    """Read full saved final results without modifying their published summary.

    The delivery SHA binds which result to read. A bad article reference stays
    unavailable; it never becomes an empty but apparently complete analysis.
    """
    delivery_sha=binding.get('sha256')
    bound=(binding.get('schema')==SCHEMA and binding.get('job_id')==delivery.get('job_id')
           and isinstance(delivery_sha,str) and re.fullmatch('[0-9a-f]{64}',delivery_sha)
           and binding.get('artifact_ref')==f"announcement_flash/jobs/{delivery.get('job_id')}/deliveries/{delivery_sha}.json"
           and hashlib.sha256(encoded(delivery)+b'\n').hexdigest()==delivery_sha)
    articles=[]
    for entry in delivery.get('articles',[]):
        if entry.get('state')!='SUCCEEDED':
            continue
        projected={key:entry.get(key) for key in ('article_id','source_sha256','body_sha256','result_sha256')}
        try:
            if not bound:
                raise ValueError('ANALYSIS_DELIVERY_BINDING_INVALID')
            if entry.get('source_coverage') not in {'COMPLETE_ARTICLE','COMPLETE_SYNTHESIS'}:
                raise ValueError('ANALYSIS_FINAL_COVERAGE_REQUIRED')
            key=entry.get('queue_key');ref=entry.get('result_ref');result_sha=entry.get('result_sha256')
            if (not isinstance(key,str) or not re.fullmatch('[0-9a-f]{64}',key)
                    or not isinstance(ref,str) or not re.fullmatch(r'jobs/'+key+r'/attempt-[0-9]{4}\.validated\.json',ref)
                    or not isinstance(result_sha,str) or not re.fullmatch('[0-9a-f]{64}',result_sha)):
                raise ValueError('ANALYSIS_RESULT_REFERENCE_INVALID')
            raw=io.read_bytes('announcement_flash/queue/'+ref,max_bytes=64*1024*1024)
            if hashlib.sha256(raw).hexdigest()!=result_sha:
                raise ValueError('ANALYSIS_RESULT_SHA_CHANGED')
            result=json.loads(raw);rows=result.get('results') if isinstance(result,dict) else None
            if (not isinstance(rows,list) or len(rows)!=1 or not isinstance(rows[0],dict)
                    or rows[0].get('article_id')!=entry.get('article_id')):
                raise ValueError('ANALYSIS_ARTICLE_IDENTITY_INVALID')
            reader=rows[0].get('reader_output')
            if (not isinstance(reader,dict) or any(reader.get(field)!=entry.get(field)
                    for field in ('source_sha256','body_sha256','disposition','direction','selection_basis','reason'))
                    or any(not isinstance(entry.get(field),str) or not re.fullmatch('[0-9a-f]{64}',entry[field])
                           for field in ('source_sha256','body_sha256'))):
                raise ValueError('ANALYSIS_SOURCE_DECISION_BINDING_INVALID')
            if (any(not isinstance(reader.get(field),str) for field in _DECISION_FIELDS)
                    or not isinstance(reader.get('risk_notes'),list)
                    or any(not isinstance(note,str) for note in reader['risk_notes'])
                    or any(not isinstance(reader.get(field),list) for field in _EVIDENCE_FIELDS)
                    or any(not isinstance(evidence,dict) or any(not isinstance(evidence.get(field),str)
                           for field in ('claim','quote','locator'))
                           for field in _EVIDENCE_FIELDS for evidence in reader[field])):
                raise ValueError('ANALYSIS_SAVED_FIELDS_INVALID')
            # Preserve every saved citation property, not only its claim text.
            fields=(*_DECISION_FIELDS,*_EVIDENCE_FIELDS,'risk_notes','source_sha256','body_sha256')
            projected.update(analysis_state='AVAILABLE',reader_output={field:deepcopy(reader[field]) for field in fields})
        except (OSError,ValueError,KeyError,TypeError) as exc:
            code=str(exc) if str(exc).startswith('ANALYSIS_') else 'ANALYSIS_RESULT_UNAVAILABLE'
            projected.update(analysis_state='UNAVAILABLE',failure_code=code)
        articles.append(projected)
    return {'schema':ANALYSIS_SCHEMA,'delivery_sha256':delivery_sha,'articles':articles}

def publish(io: SafeRoot, job_id: str, snapshot: dict[str, Any]) -> dict[str, Any]:
    raw=encoded(snapshot)+b'\n';import hashlib
    sha=hashlib.sha256(raw).hexdigest();prefix=f'announcement_flash/jobs/{job_id}/deliveries'
    ref=f'{prefix}/{sha}.json'
    try:
        old=io.read_bytes(ref,max_bytes=64*1024*1024)
    except FileNotFoundError:
        io.write_bytes(ref,raw,require_absent=True)
    else:
        if old!=raw:raise ValueError('DELIVERY_IMMUTABLE_CONFLICT')
    # SafeRoot performs an atomic replace; no published snapshot is overwritten.
    binding={'schema':SCHEMA,'job_id':job_id,'artifact_ref':ref,'sha256':sha}
    io.write_bytes(f'{prefix}/latest.json',encoded(binding)+b'\n')
    return binding

def read(io: SafeRoot, job_id: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    import hashlib
    try:
        binding=json.loads(io.read_bytes(f'announcement_flash/jobs/{job_id}/deliveries/latest.json',max_bytes=4096))
    except FileNotFoundError:return None,None
    ref=binding.get('artifact_ref');sha=binding.get('sha256')
    if (binding.get('schema')!=SCHEMA or binding.get('job_id')!=job_id
        or not isinstance(sha,str) or len(sha)!=64
        or ref!=f'announcement_flash/jobs/{job_id}/deliveries/{sha}.json'):
        raise ValueError('DELIVERY_BINDING_INVALID')
    raw=io.read_bytes(ref,max_bytes=64*1024*1024)
    if hashlib.sha256(raw).hexdigest()!=sha:raise ValueError('DELIVERY_SHA_CHANGED')
    value=json.loads(raw)
    if value.get('schema')!=SCHEMA or value.get('job_id')!=job_id:
        raise ValueError('DELIVERY_IDENTITY_INVALID')
    return value,binding
