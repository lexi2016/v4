#!/usr/bin/env python3
"""Read existing target-date authority via its original SHA-pinned reader.

No capture, producer invocation, chain completion, API call, or service change.
Writes only a NEW evidence directory outside the inspected roots. A successful
readback does NOT prove a currently authorized publisher or permit activation.
Run this script with the existing interpreter's -I option in a fresh process.
"""
from __future__ import annotations
import argparse
from datetime import datetime
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import re
import socket
import stat
import sys
from typing import Any
from zoneinfo import ZoneInfo

READER_REL='domains/manager_research_evidence.py'
READER_SHA='22ccd133851afa0fd7927ae7c40370ce1130ccd77055b0044e91d863ac1da8d9'
OWNER_REL='stage_center/hk_universe_preflight.py'
OWNER_SHA='f527db45d4ec3720845606dd38e76bf6e93e973063b43f1cadb44a8e12407e5c'
FLAGS=dict(RESEARCH_ONLY=True,production_allowed=False,buy_gate_updated=False,orders_sent=False)
LIMIT=8*1024*1024


def exact_path(value: str | Path) -> Path:
    p=Path(value)
    if not p.is_absolute() or '..' in p.parts or p.resolve()!=p:
        raise ValueError('EXACT_ABSOLUTE_PATH_REQUIRED')
    return p


def read_bytes(path: Path) -> bytes:
    path=exact_path(path)
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        st=os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size>LIMIT:
            raise ValueError('BOUNDED_REGULAR_FILE_REQUIRED')
        with os.fdopen(fd,'rb',closefd=False) as stream:
            raw=stream.read(LIMIT+1)
        if len(raw)>LIMIT:raise ValueError('READ_BYTE_LIMIT')
        return raw
    finally:os.close(fd)


def fingerprint(path: Path) -> dict:
    try:raw=read_bytes(path)
    except FileNotFoundError:return dict(path=str(path),status='MISSING')
    return dict(path=str(path),status='PRESENT',bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())


def load_reader(app: Path,expected_sha: str=READER_SHA):
    app=exact_path(app);source=app/READER_REL
    if hashlib.sha256(read_bytes(source)).hexdigest()!=expected_sha:
        raise ValueError('READER_SOURCE_SHA_MISMATCH')
    # Native dependency, from this exact app only; no copied replacement.
    sys.path.insert(0,str(app))
    dep=importlib.import_module('infrastructure.manager_input_attestation')
    if Path(dep.__file__).resolve()!=app/'infrastructure/manager_input_attestation.py':
        raise ValueError('READER_DEPENDENCY_ROOT_MISMATCH')
    name='_bounded_original_membership_reader_'+expected_sha
    spec=importlib.util.spec_from_file_location(name,source)
    if spec is None or spec.loader is None:raise ValueError('READER_LOAD_FAILED')
    module=importlib.util.module_from_spec(spec);sys.modules[name]=module
    spec.loader.exec_module(module)
    if hashlib.sha256(read_bytes(source)).hexdigest()!=expected_sha:
        raise ValueError('READER_SOURCE_CHANGED_DURING_LOAD')
    return module


def inspect_authority(reader: Any,root: Path,date: str,owner_root: Path,owner_sha: str,cutoff: str) -> dict:
    root=exact_path(root);owner_root=exact_path(owner_root)
    parsed=datetime.strptime(date,'%Y%m%d')
    if parsed.strftime('%Y%m%d')!=date:raise ValueError('TARGET_DATE_INVALID')
    limit=datetime.fromisoformat(cutoff.replace('Z','+00:00'))
    if limit.tzinfo is None:raise ValueError('CUTOFF_MUST_BE_AWARE')
    result=dict(data_root=str(root),target_trade_date=date,research_cutoff=cutoff,
        status='CANNOT_CONFIRM',membership_count=None,source=None,files=[],
        producer_activity_verified=False,raw_acquisition_receipt_verified=False,
        activation_allowed=False,network_requests=0,data_writes=0,**FLAGS)
    before={}
    try:
        owner=reader.load_universe_owner(owner_root,owner_sha)
        artifact=root/f'universes/{date}/HK_CONNECT_FULL_MARKET.json'
        before[str(artifact)]=fingerprint(artifact)
        if before[str(artifact)]['status']=='PRESENT':
            run=owner.authority_run_id(date,before[str(artifact)]['sha256'])
            paths=owner._authority_relative_paths(date,run)
            for key in ('current_relative','manifest_relative','receipt_relative'):
                p=owner._resolve_under(root,paths[key]);before[str(p)]=fingerprint(p)
        # NEVER call ensure_hk_connect_universe, _complete_authority_chain,
        # persist_snapshot, or set the clock/as_of to the historical cutoff.
        value=reader.read_universe_evidence(root,date,
            authority_owner_root=owner_root,authority_owner_sha256=owner_sha)
        source=dict(value.source)
        observed=datetime.fromisoformat(source['observed_at'])
        if observed>limit:raise ValueError('HK_CONNECT_TARGET_AUTHORITY_AFTER_CUTOFF')
        after={name:fingerprint(Path(name)) for name in before}
        if before!=after:raise ValueError('AUTHORITY_CHANGED_DURING_READ')
        result.update(status='READBACK_VERIFIED',membership_count=len(value.codes),source=source,
            consumer_scope='PRESENT_TIME_TARGET_DATE_AUTHORITY_READBACK_NOT_HISTORICAL_SELECTION',
            acquisition_semantics='observed_at is native captured_at; available_at is native read witness')
    except (ImportError,OSError,ValueError,KeyError,TypeError,RuntimeError) as exc:
        text=str(exc)
        if not re.fullmatch(r'[A-Z0-9_: .-]{1,180}',text):text=type(exc).__name__
        diag=getattr(exc,'diagnostic',None)
        result['diagnostic']=dict(diag) if isinstance(diag,dict) else dict(code=text,kind='INVALID_OR_MISSING')
    result['files']=list(before.values())
    return result


def binding_proposal(results: list[dict],selected: Path,owner_root: Path,owner_sha: str) -> dict:
    value=dict(status='CANNOT_CONFIRM',activation_allowed=False,environment=None,
        reason='SELECTED_ROOT_NOT_READBACK_VERIFIED',
        required_before_adoption=['CURRENT_SINGLE_PUBLISHER_ASSIGNMENT_AND_SOURCE_RECEIPTS',
            'INDEPENDENT_REVIEW_OF_ROOT_SOURCE_SHA_TIME_AND_CURRENT_DATA',
            'R1_PLUS_R2_CANDIDATE_RUNTIME_IDENTITY_AND_API_UI_ACCEPTANCE'])
    verified=[r for r in results if r['status']=='READBACK_VERIFIED']
    if len({r['source']['sha256'] for r in verified})>1:
        value['reason']='CONFLICTING_AUTHORITY_ROOTS_REQUIRE_ORIGINAL_OWNER_RECONCILIATION';return value
    match=[r for r in verified if r['data_root']==str(selected)]
    if len(match)!=1:return value
    value.update(status='READBACK_VERIFIED_PROPOSAL_ONLY',
        reason='READBACK_IS_NOT_ACTIVE_PRODUCER_OR_DEPLOYMENT_EVIDENCE',environment={
            'V4_MANAGER_UNIVERSE_ROOT':str(selected),
            'V4_MANAGER_UNIVERSE_OWNER_ROOT':str(owner_root),
            'V4_MANAGER_UNIVERSE_OWNER_SHA256':owner_sha})
    return value


def check_destination(output: Path,protected: list[Path]) -> None:
    output=exact_path(output)
    for root in protected:
        root=exact_path(root)
        if output==root or root in output.parents or output in root.parents:
            raise ValueError('EVIDENCE_PATH_OVERLAPS_PROTECTED_ROOT')
    if output.exists():raise ValueError('EVIDENCE_DIRECTORY_MUST_BE_NEW')


def _deny_network(*args,**kwargs):
    raise RuntimeError('NETWORK_FORBIDDEN_IN_AUTHORITY_READBACK')


def main(argv=None) -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app-root',required=True,type=exact_path)
    parser.add_argument('--owner-root',required=True,type=exact_path)
    parser.add_argument('--owner-sha256',default=OWNER_SHA)
    parser.add_argument('--data-root',action='append',required=True,type=exact_path)
    parser.add_argument('--selected-data-root',required=True,type=exact_path)
    parser.add_argument('--date',required=True)
    parser.add_argument('--cutoff',required=True)
    parser.add_argument('--output-dir',required=True,type=exact_path)
    args=parser.parse_args(argv)
    if not 1<=len(args.data_root)<=2 or len(set(args.data_root))!=len(args.data_root):
        parser.error('Supply one or two DISTINCT explicit data roots, never a recursive search.')
    if args.selected_data_root not in args.data_root:parser.error('Selected root must be explicitly inspected.')
    if args.owner_sha256!=OWNER_SHA:
        parser.error('This handoff pins one supplied owner. Source drift needs a new review, not a CLI override.')
    check_destination(args.output_dir,[args.app_root,args.owner_root,*args.data_root])
    sys.dont_write_bytecode=True
    socket.create_connection=_deny_network
    socket.socket.connect=_deny_network
    socket.socket.connect_ex=_deny_network
    started=datetime.now(ZoneInfo('Asia/Hong_Kong')).isoformat()
    code_paths=[args.app_root/READER_REL,
        args.app_root/'infrastructure/manager_input_attestation.py',args.owner_root/OWNER_REL]
    code_before=[fingerprint(path) for path in code_paths]
    reader=load_reader(args.app_root)
    results=[inspect_authority(reader,root,args.date,args.owner_root,args.owner_sha256,args.cutoff)
             for root in args.data_root]
    code_after=[fingerprint(path) for path in code_paths]
    if code_before!=code_after:
        for result in results:
            result.update(status='CANNOT_CONFIRM',membership_count=None,
                diagnostic=dict(code='SOURCE_CHANGED_DURING_AUDIT',kind='CONFLICT'))
    proposal=binding_proposal(results,args.selected_data_root,args.owner_root,args.owner_sha256)
    report=dict(schema_version='v4.manager_membership.readonly_intake.v1',
        status=proposal['status'],started_at=started,
        finished_at=datetime.now(ZoneInfo('Asia/Hong_Kong')).isoformat(),
        inspected_reader=code_after[0],inspected_dependency=code_after[1],inspected_owner=code_after[2],
        sources_unchanged_during_audit=code_before==code_after,results=results,binding_proposal=proposal,
        active_producer_identified=False,real_api_verified=False,real_ui_verified=False,
        independent_review_verified=False,activation_allowed=False,**FLAGS)
    args.output_dir.mkdir(parents=True,exist_ok=False)
    raw=(json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode()
    with (args.output_dir/'authority_readback.json').open('xb') as stream:stream.write(raw)
    print(json.dumps(dict(status=report['status'],evidence_path=str(args.output_dir/'authority_readback.json'),
                         evidence_sha256=hashlib.sha256(raw).hexdigest(),activation_allowed=False),ensure_ascii=False))
    return 0 if proposal['environment'] is not None else 2


if __name__=='__main__':
    try:raise SystemExit(main())
    except (OSError,ValueError,ImportError,RuntimeError) as exc:
        code=str(exc)
        if not re.fullmatch(r'[A-Z0-9_: .-]{1,180}',code):code=type(exc).__name__
        print(json.dumps(dict(status='CANNOT_CONFIRM',reason=code,activation_allowed=False,**FLAGS)))
        raise SystemExit(2)
