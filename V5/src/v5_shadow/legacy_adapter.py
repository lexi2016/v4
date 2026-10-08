"""Wrap a pinned reader, preserving its full result and research-only status."""
import copy
import importlib
import importlib.util
import json
import platform
import re
import sys
import types
import uuid
from datetime import datetime
from pathlib import Path
from .contracts import Binding,RuntimeIdentity,SafetyFlags,ShadowRequest,ShadowResult,SourceEntry
from .digests import canonical_bytes
from .source_capsule import inspect_capsule,verify_capsule

SCHEMA='v4.manager_research.rebound_v3_screen.v1'
RULE='20260923_REBOUND_TWO_GATE_V1'


def build_shadow_result(request:ShadowRequest,runtime:RuntimeIdentity,legacy:dict,started_at:datetime,finished_at:datetime) -> ShadowResult:
    for clock in (started_at,finished_at):
        if clock.tzinfo is None or clock.utcoffset() is None:raise ValueError('EXECUTION_TIMEZONE_REQUIRED')
    if finished_at<started_at:raise ValueError('EXECUTION_CLOCK_REVERSED')
    canonical_bytes(legacy)
    legacy=copy.deepcopy(legacy)
    if legacy.get('target_trade_date')!=request.target_trade_date:raise ValueError('LEGACY_TARGET_DATE_MISMATCH')
    if legacy.get('schema_version')!=SCHEMA or legacy.get('rule_version')!=RULE:raise ValueError('LEGACY_CONTRACT_MISMATCH')
    if legacy.get('RESEARCH_ONLY',True) is not True or any(legacy.get(k,False) is not False for k in ('production_allowed','buy_gate_updated','orders_sent')):
        raise ValueError('LEGACY_SAFETY_INVALID')
    status=legacy.get('status')
    business='FAILED' if status not in ('READY','READY_WITH_GAPS','CANNOT_CONFIRM') else 'CANNOT_CONFIRM'
    evaluated=None
    coverage=legacy.get('coverage',{})
    count=coverage.get('input_candidate_count')
    ready=(legacy.get('main_screen_ready') is True and isinstance(legacy.get('input_identity'),str)
           and re.fullmatch('[0-9a-f]{64}',legacy['input_identity']) is not None
           and isinstance(legacy.get('authority'),dict) and bool(legacy['authority'])
           and type(count) is int and count>0)
    groups=('strict','near','excluded','pending','screen_unresolved')
    rows=[legacy.get(g) for g in groups]
    if ready and all(isinstance(r,list) for r in rows):
        codes=[r.get('code') for group in rows for r in group if isinstance(r,dict)]
        accounted=sum(map(len,rows))
        valid_codes=(len(codes)==accounted and all(isinstance(c,str) and re.fullmatch(r'HK\.[0-9]{5}',c) for c in codes) and len(set(codes))==accounted)
        valid_counts=(coverage.get('row_accounted_count')==count==accounted and valid_codes
                      and coverage.get('strict_count')==len(rows[0]) and coverage.get('near_count')==len(rows[1])
                      and coverage.get('excluded_count')==len(rows[2])
                      and coverage.get('history_pending_count')==len(rows[3])
                      and coverage.get('screen_unresolved_count')==len(rows[4]))
        if valid_counts:
            evaluated=len(rows[0])+len(rows[1])+len(rows[2])
            if status=='READY' and not legacy.get('gaps') and not rows[3] and not rows[4]:
                business='COMPLETED' if rows[0] or rows[1] else 'VALID_EMPTY'
            elif status=='READY_WITH_GAPS':business='PARTIAL'
    return ShadowResult('v5.rebound_shadow.v1',uuid.uuid4().hex,request,runtime,legacy,business,evaluated,'UNVERIFIED',False,started_at,finished_at,SafetyFlags())


def load_pinned_reader(binding:Binding):
    """Load only the byte-verified capsule in a fresh disposable process.

    Static provenance permits attempting the import; successful loading is
    observed here rather than asserted by a pre-written runtime status flag.
    This does not admit real inputs or prove the complete business flow.
    """
    base=Path(__file__).resolve().parents[2]
    root=base/'vendor'/'rebound_baseline'
    descriptor=base/'contracts'/'rebound_source_manifest.json'
    if not descriptor.is_file():raise ValueError('SOURCE_CLOSURE_INCOMPLETE')
    value=json.loads(descriptor.read_text())
    if value.get('schema_version')!='v5.rebound_source_capsule.v1' or value.get('source_closure_status')!='STATIC_VERIFIED':
        raise ValueError('SOURCE_CLOSURE_INCOMPLETE')
    if tuple(map(int,platform.python_version_tuple()[:2]))<(3,14):raise ValueError('LEGACY_PYTHON_REQUIRES_3_14')
    if importlib.util.find_spec('pandas') is None or importlib.util.find_spec('pyarrow') is None:
        raise ValueError('LEGACY_PARQUET_DEPENDENCY_MISSING')
    entries=tuple(SourceEntry(**item) for item in value['entries'])
    capsule=inspect_capsule(root,entries)
    errors=verify_capsule(capsule,root)
    if errors:raise ValueError(errors[0])
    if capsule.manifest_sha256!=binding.source_capsule_sha256:raise ValueError('SOURCE_CAPSULE_BINDING_MISMATCH')
    if any(name in sys.modules for name in ('v4','contracts','infrastructure','v3_shared_data')):
        raise ValueError('LEGACY_REQUIRES_FRESH_PROCESS')
    # Deliberately skip the broad manager __init__, which starts unrelated imports.
    # Original source files remain byte-identical. Namespace isolation is V5 adapter code.
    sys.path.insert(0,str(root))
    for name,relative in [('v4','v4'),('v4.manager_research','v4/manager_research'),('v3_shared_data','v3_shared_data')]:
        module=types.ModuleType(name);module.__path__=[str(root/relative)];module.__package__=name
        sys.modules[name]=module
    original=importlib.import_module('v4.manager_research.workspace_plan')
    return original


def run_legacy_screen(request:ShadowRequest,binding:Binding) -> dict:
    """Called only in the dedicated worker; user requests cannot select code."""
    original=load_pinned_reader(binding)
    context=original.plan_context(request.target_trade_date,now=request.research_cutoff)
    if context['calendar_sha256']!=binding.calendar_sha256:raise ValueError('CALENDAR_IDENTITY_MISMATCH')
    if request.data_kind=='OWNER_VERIFIED':
        # Byte checks alone do not prove an immutable owner snapshot/read lease.
        # No real source-admission protocol was supplied with this first baseline.
        raise ValueError('OWNER_INPUT_STABILITY_UNVERIFIED')
    legacy=original.read_rebound_screen(binding.authority_root,context)
    if legacy.get('main_screen_ready') is True:
        capture=legacy.get('authority',{}).get('security_master',{}).get('captured_at')
        try:
            when=datetime.fromisoformat(capture)
            if when.tzinfo is None or when.utcoffset() is None:raise ValueError()
        except (TypeError,ValueError):
            raise ValueError('MASTER_CAPTURE_UNVERIFIED') from None
        if when>request.research_cutoff:raise ValueError('MASTER_AFTER_CUTOFF')
    return legacy
