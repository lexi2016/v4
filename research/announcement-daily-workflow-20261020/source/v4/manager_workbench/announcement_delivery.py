"""Immutable per-article result snapshots behind one atomic per-job index."""
from __future__ import annotations
from copy import deepcopy
import json
from typing import Any
from infrastructure.owned_io import SafeRoot
from .announcement_preprocessing import encoded, digest

SCHEMA='v4.manager_workbench.announcement_delivery.v1'

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
