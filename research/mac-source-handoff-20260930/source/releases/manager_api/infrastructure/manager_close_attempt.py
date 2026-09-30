"""Non-data attempt receipt shared by the existing owner and its child.

This module cannot publish candidates, a successful scan, or production flags.
It is used when a child cannot import/start, so the read-only workbench does not
silently confuse execution failure with a successful empty scan.
"""
from __future__ import annotations
from datetime import datetime
import json
import os
from pathlib import Path
import re
import tempfile
from infrastructure.owned_path import resolve_owned_path

ALLOWED={'FAILED','INPUT_MISSING','PENDING_SLOT','NOT_APPLICABLE'}


def validate_failure_diagnostic(value: object) -> dict:
    """Allow only bounded codes, relative source identities and hashes to the UI."""
    fields = {'schema_version', 'layer', 'kind', 'code', 'field', 'artifact_ref',
              'source_owner', 'source_code_ref', 'source_code_sha256'}
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError('MANAGER_DIAGNOSTIC_FIELDS_INVALID')
    if (value['schema_version'] != 'v4.manager_close_failure.v1'
        or value['layer'] not in {'CONFIGURATION', 'CAPTURE_WINDOW', 'UNIVERSE_OWNER',
                                  'UNIVERSE_ARTIFACT', 'UNIVERSE_AUTHORITY', 'SNAPSHOT'}
        or value['kind'] not in {'MISSING', 'INVALID', 'CONFLICT', 'PIT_UNSAFE', 'EXECUTION_FAILED', 'EXPIRED'}):
        raise ValueError('MANAGER_DIAGNOSTIC_ENUM_INVALID')
    for key, pattern in [('code', r'[A-Z0-9_:.-]{1,160}'), ('field', r'[a-zA-Z0-9_.]{1,100}')]:
        if not isinstance(value[key], str) or not re.fullmatch(pattern, value[key]):
            raise ValueError('MANAGER_DIAGNOSTIC_CODE_INVALID')
    if value['source_owner'] not in {None, 'stage_center.hk_universe_preflight.ensure_hk_connect_universe',
                                   'shared_data.hk_auction_0920.fetch_futu_snapshot'}:
        raise ValueError('MANAGER_DIAGNOSTIC_OWNER_INVALID')
    if value['source_code_ref'] not in {None, 'stage_center/hk_universe_preflight.py',
                                      'upstreams/v3_shared_data/shared_data/hk_auction_0920.py'}:
        raise ValueError('MANAGER_DIAGNOSTIC_SOURCE_INVALID')
    sha = value['source_code_sha256']
    if sha is not None and (not isinstance(sha, str) or not re.fullmatch(r'[0-9a-f]{64}', sha)):
        raise ValueError('MANAGER_DIAGNOSTIC_SHA_INVALID')
    ref = value['artifact_ref']
    if ref is not None:
        from pathlib import PurePosixPath
        if (not isinstance(ref, str) or not re.fullmatch(r'[A-Za-z0-9_/.-]{1,240}', ref)
            or PurePosixPath(ref).is_absolute() or '..' in PurePosixPath(ref).parts
            or PurePosixPath(ref).as_posix() != ref
            or not ref.startswith(('universes/', 'workbench_research/'))):
            raise ValueError('MANAGER_DIAGNOSTIC_REF_INVALID')
    return dict(value)


def write_attempt(root: Path, date: str, status: str, reason: str, at: datetime,
                  *, diagnostic: dict | None = None) -> None:
    if (not Path(root).is_absolute() or not re.fullmatch(r'\d{8}',date)
        or status not in ALLOWED or at.tzinfo is None or not re.fullmatch(r'[A-Z0-9_:.-]{1,160}',reason)):
        raise ValueError('MANAGER_ATTEMPT_CONTRACT_INVALID')
    datetime.strptime(date,'%Y%m%d')
    payload={'schema_version':'v4.manager_workbench.research.v1','market':'HK_CONNECT','trade_date':date,'slot':'1530',
        'as_of':at.isoformat(),'generated_at':at.isoformat(),'run_id':None,'status':status,
        'rule_version':'manager-workbench-b1-contract-v1','cache_key':f'{date}|HK_CONNECT|1530|manager-workbench-b1-contract-v1',
        'universe':None,'coverage':{'eligible_count':None,'covered_count':None,'missing_count':None,'missing_reasons':[reason]},
        'cannot_confirm':[reason],'priority_summary':{'focus':[],'theme_changes':[],'risk_upgrades':[]},'candidates':[],
        'RESEARCH_ONLY':True,'production_allowed':False,'buy_gate_updated':False,'orders_sent':False}
    if diagnostic is not None:
        payload['failure_diagnostic'] = validate_failure_diagnostic(diagnostic)
        if payload['failure_diagnostic']['code'] != reason:
            raise ValueError('MANAGER_DIAGNOSTIC_REASON_MISMATCH')
    path=resolve_owned_path(root,f'workbench_research/{date}/1530.status.json')
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix='.manager-attempt-',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as stream:
            json.dump(payload,stream,ensure_ascii=False,sort_keys=True,allow_nan=False)
            stream.write('\n');stream.flush();os.fsync(stream.fileno())
        os.replace(name,path)
    finally:
        try: os.unlink(name)
        except FileNotFoundError: pass
