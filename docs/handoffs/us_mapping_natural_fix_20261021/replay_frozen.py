"""Offline actual-input canary; only new isolated derived state may be written."""
from __future__ import annotations
import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import socket
import sys


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--code-root',type=Path,required=True)
    p.add_argument('--config',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    assert a.output.is_absolute() and not a.output.exists()
    a.output.mkdir(parents=True)
    sys.path[:0]=[str(a.code_root),str(a.code_root/'upstreams')]
    # No collection, HTTP, model or other network action is permitted in this replay.
    def forbidden(*_,**__):raise AssertionError('OFFLINE_NETWORK_FORBIDDEN')
    socket.socket.connect=forbidden
    socket.socket.connect_ex=forbidden
    socket.create_connection=forbidden
    from v4.manager_workbench.config import load_config
    from v4.manager_workbench.contracts import PlanSnapshot, RunContext, Lane
    from v4.manager_workbench.engines.us_mapping import run_us_mapping
    from v4.manager_workbench.inputs.native import NativeAdapters
    from v4.manager_workbench.service import create_service
    from v4.manager_workbench import engines
    official=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/state/manager_workbench/manager_workbench')
    source=official/'snapshots/e6feeeb310bf40fda91e1561f285d908.json'
    input_path=official/'input_snapshots/1488f9594fd952a607e92d5f7f628341805a83bf9c4377c34ad2a189d1685b58.json'
    source_sha,input_sha=sha(source),sha(input_path)
    original_input=json.loads(input_path.read_bytes())
    context=RunContext.model_validate(original_input['context'])
    assert context.target_date=='20261021' and context.source_sessions=={'hk_price':'20261020','us':'20261020'}
    original_pin=deepcopy(context.scope_refs['owner_bindings']['us_mapping'])
    original_pin_sha=digest(original_pin)
    assert original_pin['hk_industry_classification']==dict(status='UNAVAILABLE',gap='HK_INDUSTRY_CLASSIFICATION_EXACT_DATE_BINDING_MISSING')
    config=load_config(a.config).model_copy(update={'state_root':a.output/'state','capture_enabled':False})
    adapter=NativeAdapters(config)
    batch=adapter.us_mapping(context)
    assert context.scope_refs['owner_bindings']['us_mapping']==original_pin
    payload=next(r['us_factor_payload'] for r in batch.records if 'us_factor_payload' in r)
    industry=payload['hk_industry_classification']
    assert industry['status']=='READY',industry.get('gap')
    assert industry['artifact']['observed_trade_date']=='20261014'
    assert industry['artifact']['captured_at']=='2026-10-14T11:03:29.919614+08:00'
    assert industry['artifact']['source_asof'] is None and industry['artifact']['source_asof_status']=='UNKNOWN'
    assert industry['artifact']['status']=='PARTIAL'
    assert industry['hk_industry_identity']['status']=='READY'
    assert industry['hk_industry_identity']['source_date']=='20261020'
    result=run_us_mapping(context.model_dump(mode='json'),batch.model_dump(mode='json'))
    factor=next(r['us_factor_summary'] for r in result['rows'] if 'us_factor_summary' in r)
    daily=factor['single_day_mapping']
    assert len(daily['rows'])==len({r['symbol'] for r in daily['rows']})==698
    assert len(daily['catalog_relation_dispositions'])==1003
    assert not any(p.get('relation_type')=='CATALOG_OBSERVATION_ONLY' for r in daily['rows'] for p in r['mapping_paths'])
    assert daily['strict_v1_status']=='PAUSED_NOT_EXECUTED'
    assert daily['formal_target_eligibility']=='CANNOT_CONFIRM'
    assert daily['RESEARCH_ONLY'] and not any(daily[k] for k in ['production_allowed','buy_gate_updated','orders_sent'])
    medicine_ids={'R659','R979','R980','R600','R844','R981','R601','R678'}
    medicine_codes={'HK.'+r['hk_code'] for r in original_pin['full_overlay_projection'] if r['relation_id'] in medicine_ids}
    medical_catalog=[r for r in daily['catalog_relation_dispositions'] if r['catalog_relation_id'] in medicine_ids]
    assert len(medical_catalog)==8 and not any(r['catalog_disposition'].startswith('ADOPTED_') for r in medical_catalog)
    medicine=[dict(symbol=r['symbol'],decision=r['decision'],reason=r.get('reason')) for r in daily['rows'] if r['symbol'] in medicine_codes]
    # The actual adapter must also fail closed when a same-day pin is present but corrupt.
    blocked_config=config.model_copy(deep=True)
    override=deepcopy(blocked_config.source_bindings['hk_industry_classification']['observed_policy_template'])
    override.update(target_date=context.target_date,artifact_sha256='0'*64)
    blocked_config.source_bindings['hk_industry_classification'][context.target_date]=override
    bad_context=RunContext.model_validate(original_input['context'])
    bad_batch=NativeAdapters(blocked_config).us_mapping(bad_context)
    bad_payload=next(r['us_factor_payload'] for r in bad_batch.records if 'us_factor_payload' in r)
    assert bad_payload['hk_industry_classification']['status']=='UNAVAILABLE'
    assert bad_payload['hk_industry_classification']['gap']=='OWNER_SHA_MISMATCH'
    assert bad_context.scope_refs['owner_bindings']['us_mapping']==original_pin
    # A different frozen failure must remain visible rather than using a template.
    other_context=RunContext.model_validate(original_input['context'])
    other_context.scope_refs['owner_bindings']['us_mapping']['hk_industry_classification']['gap']='OWNER_SHA_MISMATCH'
    other_batch=NativeAdapters(config).us_mapping(other_context)
    other_payload=next(r['us_factor_payload'] for r in other_batch.records if 'us_factor_payload' in r)
    assert other_payload['hk_industry_classification']['status']=='UNAVAILABLE'
    assert other_payload['hk_industry_classification']['gap']=='OWNER_SHA_MISMATCH'
    source_plan=PlanSnapshot.model_validate(json.loads(source.read_bytes()))
    service=create_service(config,adapter,engines,object())
    try:
        # Read the real immutable plan, then provide it to an isolated store; no official pointer/plan write.
        service.store.list_plans=lambda _: [source_plan]
        frozen=service.freeze_preopen('20261021',cutoff=datetime.fromisoformat('2026-10-21T09:25:00+08:00'))
        us_lane=next(l for l in frozen.lanes if l.lane==Lane.US_MAPPING)
        assert us_lane.state.value=='PARTIAL' and us_lane.rows==[]
        assert frozen.changes['source_run_id']==source_plan.run_id
        diag=frozen.changes['preopen_filter_diagnostics']['US_MAPPING']
        assert diag['source_row_count']==1063 and diag['accepted_row_count']==0
        assert {g for e in diag['excluded_evidence'] for g in e['gaps']} >= {'SOURCE_AVAILABLE_AT_UNKNOWN','CONNECT_MEMBERSHIP_TARGET_EFFECTIVE_PERIOD_UNCONFIRMED'}
    finally:service.jobs.stop()
    assert sha(source)==source_sha and sha(input_path)==input_sha
    summary=dict(state='OFFLINE_CANARY_COMPLETED_NOT_NATURAL',code_root=str(a.code_root),python=sys.executable,
        frozen_source_run_id=source_plan.run_id,source_snapshot_sha256=source_sha,input_snapshot_sha256=input_sha,
        frozen_us_pin_sha256=original_pin_sha,frozen_us_pin_unchanged=True,
        quote_artifact_sha256=original_pin['quote_sha256'],quote_receipt_sha256=original_pin['owner_receipt_sha256'],
        quote_manifest_sha256=original_pin['owner_manifest_sha256'],quote_source_session=context.source_sessions['us'],
        capture_cutoff=original_pin.get('capture_cutoff'),capture_run_id=original_pin.get('capture_run_id'),
        observed_source=dict(artifact_sha256=industry['artifact_sha256'],observed_trade_date='20261014',
            captured_at=industry['artifact']['captured_at'],source_asof_status='UNKNOWN',status='PARTIAL'),
        master_identity=industry['hk_industry_identity'],industry_summary=factor['industry_summary'],
        daily_counts=daily['counts'],daily_row_count=len(daily['rows']),catalog_relation_count=1003,
        medical_rows=medicine,medical_catalog_dispositions=medical_catalog,preopen_diagnostics=diag,preopen_state=us_lane.state.value,
        bad_explicit_override='UNAVAILABLE_OWNER_SHA_MISMATCH',other_frozen_failure='PRESERVED',
        formal_target_eligibility=daily['formal_target_eligibility'],strict_v1_status=daily['strict_v1_status'],
        source_files={str(p.relative_to(a.code_root)):sha(p) for p in [a.code_root/rel for rel in
            ['v4/manager_workbench/inputs/native.py','v4/manager_workbench/inputs/source_bindings.py','v4/manager_workbench/service.py']]},
        official_state_writes=False,network_or_model_calls=False)
    (a.output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:summary[k] for k in ['state','daily_row_count','daily_counts','preopen_state','frozen_us_pin_unchanged','bad_explicit_override']},ensure_ascii=False))


if __name__=='__main__':main()
