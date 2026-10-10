"""Versioned current-cutoff US research for a current/future HK target.

Reuses original US and manager owners. No source acquisition, historical input
substitution, scheduled execution or API activation. Outputs must be new roots.
"""
import sys
from pathlib import Path
if __package__ in (None,''):sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import argparse
import copy
from datetime import datetime,timezone,timedelta
import hashlib
import json
import os
import re
import subprocess
from v5_shadow.contracts import exact_keys,trade_date,aware
from v5_shadow.digests import canonical_bytes,MAX_JSON_BYTES
from v5_shadow.composition import no_symlinks
from v5_shadow.module_api import _open_directory,_read_at
from v5_shadow.us_mapping_daily import run_us_mapping
from v5_shadow.manager_plan import run_manager_plan

SCHEMA='v5.current_us_research.v1'


def _context_at(target,now):
    trade_date(target);instant=aware(now)
    today=instant.astimezone(timezone(timedelta(hours=8))).strftime('%Y%m%d')
    if target<today:raise ValueError('CURRENT_RESEARCH_HISTORICAL_TARGET_FORBIDDEN')
    child=subprocess.run([sys.executable,'-I','-B',str(Path(__file__).resolve()),'--context-worker'],
        input=canonical_bytes(dict(target_date=target,now=now)),stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30)
    if child.returncode:raise ValueError('CURRENT_RESEARCH_ORIGINAL_CONTEXT:'+child.stderr.decode(errors='replace')[-1000:])
    if len(child.stdout)>MAX_JSON_BYTES:raise ValueError('CURRENT_RESEARCH_CONTEXT_LIMIT')
    return json.loads(child.stdout)


def inspect_target(target):
    return _context_at(target,datetime.now(timezone.utc).isoformat())


def _new_output(root,marker,expected):
    path=no_symlinks(root)
    fd=_open_directory(root)
    try:
        if _read_at(fd,None,marker)!=expected or set(os.listdir(fd))!={marker}:
            raise ValueError('CURRENT_RESEARCH_FRESH_MARKED_OUTPUT_REQUIRED')
    finally:os.close(fd)
    return path


def _raw_file(root,relative):
    from v5_shadow.a_preselection import _relative
    path=_relative(no_symlinks(root),relative);fd=_open_directory(path.parent)
    try:return _read_at(fd,None,path.name)
    finally:os.close(fd)



def coverage_paths(workspace):
    """Transport the original three scopes without creating relations or counts."""
    market = workspace.get('us_market_attention') or {}
    diagnostics = market.get('mapping_diagnostics') or {}
    seed = workspace.get('us_mapping_research') or {}
    daily = seed.get('daily_run') or {}
    return dict(schema_version='v5.us_coverage_paths.v1',
        combined_material_assessment_state=diagnostics.get('assessment_state'),
        material_input=copy.deepcopy(market.get('research_material_input')),
        material_assessment_reasons=copy.deepcopy(diagnostics.get('assessment_reasons')),
        industry_material=dict(scope='RISING_INDUSTRY_AND_VERIFIED_HK_BUSINESS_THEME',
            explicit_us_ticker_required=False,
            raw_movers=copy.deepcopy(market.get('raw_industry_up')),
            original_diagnostics=copy.deepcopy(diagnostics.get('industry'))),
        individual_material=dict(scope='RISING_US_SYMBOL_AND_VERIFIED_EXPLICIT_HK_RELATION',
            explicit_us_ticker_required=True,
            raw_movers=copy.deepcopy(market.get('raw_individual_up')),
            original_diagnostics=copy.deepcopy(diagnostics.get('individual'))),
        reviewed_seed=dict(scope='PINNED_DAILY_MATCH_SYMBOLS_ONLY',
            status=daily.get('status'),run_id=daily.get('run_id'),artifact_sha256=daily.get('artifact_sha256'),
            coverage_diagnostics=copy.deepcopy(seed.get('coverage_diagnostics'))),
        formal_eligible=False,natural_verified=False,full_market_coverage=False)


def run_current_research(request):
    exact_keys(request,('target_date','us_data_root','us_files','us_output_root','manager_output_root','materials','native_master')+
        tuple(key for key in ('archives','archive_import') if key in request))
    if 'archives' in request and 'archive_import' in request:
        raise ValueError('CURRENT_RESEARCH_ARCHIVE_INPUT_EXCLUSIVE')
    # Caller cannot override wall clock or relabel an old target as current.
    context=inspect_target(request['target_date'])
    target=context['target_date']
    expected={'research/peripherals/manifest.json',
        'research/peripherals/'+context['us_session_date']+'/external_finance.json',
        'receipts/research/peripherals/'+context['us_session_date']+'/external_finance.json'}
    if set(request['us_files'])!=expected:raise ValueError('CURRENT_RESEARCH_EXACT_US_SESSION_REQUIRED')
    usout=_new_output(request['us_output_root'],'.v5-us-mapping-root',b'v5.us-mapping-root.v1\n')
    managerout=_new_output(request['manager_output_root'],'.v5-manager-plan-root',b'v5.manager-plan-root.v1\n')
    if usout.is_relative_to(managerout) or managerout.is_relative_to(usout):raise ValueError('CURRENT_RESEARCH_OUTPUT_OVERLAP')
    sources=[no_symlinks(request['us_data_root']),no_symlinks(request['materials']['root'])]
    for name in ('native_master','archives'):
        if request.get(name) is not None:sources.append(no_symlinks(request[name]['root']))
    archive_output=None
    if 'archive_import' in request:
        job=request['archive_import']
        archive_output=_new_output(job['output_root'],'.v5-archive-article-v2',b'v5.archive-article.v2\n')
        sources.append(no_symlinks(job['capture_root']))
        if any(archive_output.is_relative_to(out) or out.is_relative_to(archive_output) for out in (usout,managerout)):
            raise ValueError('CURRENT_RESEARCH_ARCHIVE_OUTPUT_OVERLAP')
        if any(source.is_relative_to(archive_output) or archive_output.is_relative_to(source) for source in sources):
            raise ValueError('CURRENT_RESEARCH_ARCHIVE_SOURCE_OVERLAP')
    for source in sources:
        if any(source.is_relative_to(out) or out.is_relative_to(source) for out in (usout,managerout)):
            raise ValueError('CURRENT_RESEARCH_SOURCE_OUTPUT_OVERLAP')
    daily=run_us_mapping(dict(target_date=target,now=context['observed_at'],
        us_data_root=request['us_data_root'],us_files=request['us_files'],manager_output_root=str(usout)))
    product=daily['persisted_daily'];run=product['run_id']
    if not re.fullmatch('[0-9a-f]{32}',run) or daily['readback_status']!='MATCHED':raise ValueError('CURRENT_RESEARCH_US_READBACK')
    prefix='us_mapping_research/'+target+'/'
    names=(prefix+'runs/'+run+'.json',prefix+'latest.json')
    raw={name:_raw_file(usout,name) for name in names}
    if json.loads(raw[names[0]])!=product:raise ValueError('CURRENT_RESEARCH_US_BYTES_CHANGED')
    head=json.loads(raw[names[1]])
    if head['run_id']!=run or head['artifact_sha256']!=product['artifact_sha256']:raise ValueError('CURRENT_RESEARCH_US_POINTER_CHANGED')
    inputs=dict(manager=dict(root=str(usout),files={name:hashlib.sha256(data).hexdigest() for name,data in raw.items()}),
        materials=copy.deepcopy(request['materials']),us=dict(root=request['us_data_root'],files=request['us_files']))
    for name in ('native_master','archives'):
        if request.get(name) is not None:inputs[name]=copy.deepcopy(request[name])
    archive_import=None
    if archive_output is not None:
        from v5_shadow.archive_article_v2 import run_import
        archive_import=run_import(request['archive_import'])
        inputs['archives']=archive_import['archive_binding']
    manager_request=dict(target_date=target,now=datetime.now(timezone.utc).isoformat(),action='refresh',view='dynamic',
        selection_date=None,announcement_date=None,inputs=inputs,rebound=None,manager_output_root=str(managerout))
    saved=run_manager_plan(manager_request)
    # Explicit dynamic current-research view; no change to frozen auto/history.
    read=run_manager_plan(dict(manager_request,action='read'))
    plan=read['payload']['plan_product']
    if plan.get('run_id')!=saved['readback']['run_id'] or plan.get('sha256')!=saved['readback']['plan_sha256']:
        raise ValueError('CURRENT_RESEARCH_PLAN_READBACK_MISMATCH')
    return dict(schema_version=SCHEMA,status='RESEARCH_SAVED_NOT_FORMAL_SELECTION',context=context,
        underlying_us_execution_kind=daily['execution_kind'],
        us_run_id=run,us_artifact_sha256=product['artifact_sha256'],
        native_master_bound=request['native_master'] is not None,
        manager_request=manager_request,manager_readback=saved['readback'],
        workspace=read['payload'],coverage_paths=coverage_paths(read['payload']),
        archive_readback=copy.deepcopy(read.get('archive_readback')),
        archive_import=archive_import,
        natural_verified=False,historical_pit_claimed=False,
        production_allowed=False,buy_gate_updated=False,orders_sent=False)


def context_worker(request):
    from v5_shadow.manager_plan import load_owner,PIN
    load_owner()
    from v4.manager_research.workspace_plan import plan_context
    from v4.manager_research.us_market_bridge import latest_completed_session
    context=plan_context(request['target_date'],now=aware(request['now']))
    us=latest_completed_session(aware(context['research_cutoff']))
    return dict(schema_version=SCHEMA,target_date=request['target_date'],observed_at=request['now'],
        hk_reference_date=context['market_session'],us_session_date=us.session_date,
        us_session_close=us.close_at.isoformat(),original_plan_context=context,manager_source_sha256=PIN,
        scope='CURRENT_CUTOFF_RESEARCH_NOT_HISTORICAL_REPAIR',natural_verified=False)


if __name__=='__main__':
    if sys.argv[1:]==['--context-worker']:
        raw=sys.stdin.buffer.read(MAX_JSON_BYTES+1)
        if len(raw)>MAX_JSON_BYTES:raise ValueError('CURRENT_RESEARCH_REQUEST_LIMIT')
        value=context_worker(json.loads(raw))
    else:
        parser=argparse.ArgumentParser(description=__doc__)
        group=parser.add_mutually_exclusive_group(required=True)
        group.add_argument('--inspect-target');group.add_argument('--request',type=Path)
        args=parser.parse_args()
        value=inspect_target(args.inspect_target) if args.inspect_target else run_current_research(json.loads(args.request.read_bytes()))
    print(canonical_bytes(value).decode())
