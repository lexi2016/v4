"""Bounded retained-prefix admission; all source packages and rows are synthetic."""
import copy
import io
import json
from pathlib import Path
import struct
import zipfile

import pytest
from ops import research_daily_capacity as capacity
from ops._a_share_daily_sync_parts.official_daily_package import SOURCE_URL
from test_daily_capacity import setup_plan


ROOT=Path(__file__).resolve().parents[4]
CODE='000001.SZ'; TARGET=20261123; RETAINED=20261120; SOURCE=20261119


def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(capacity.encoded(value))
    return capacity.file_reference(path)


def raw(date,reserved=0):return struct.pack('<IIIIIfII',date,1000,1100,900,1050,10000.,10000,reserved)


def official(root,target,previous,*,absent=False):
    root.mkdir(parents=True,exist_ok=True);buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w')as archive:
        for prefix,code in [('sh','600035'),('sz','999999'if absent else'000001'),('bj','920002')]:
            cod=bytearray(150);md=bytearray(512);cod[:6]=code.encode();cod[40:44]='样本'.encode('gbk')
            struct.pack_into('<d',md,4,10.);struct.pack_into('<4d',md,12,10.,11.,9.,10.5)
            struct.pack_into('<Q',md,56,10000);struct.pack_into('<d',md,72,10000.)
            archive.writestr(f'{prefix}{str(target)[2:]}.cod',cod);archive.writestr(f'{prefix}{str(target)[2:]}.md1',md)
    package=root/'package.zip';package.write_bytes(buffer.getvalue())
    value=dict(schema_version='a_sync_official_daily_input.v1',source_kind='TDX_OFFICIAL_G4DAY',target_date=target,
        source_url=SOURCE_URL.format(date=target),previous_session=str(previous),package=capacity.file_reference(package),
        calendar=capacity.file_reference(ROOT/'contracts/market_calendar_2026.json'),
        calendar_adapter=capacity.file_reference(ROOT/'contracts/trading_calendar.py'))
    descriptor=save(root/'input.json',value)
    return dict(source_kind='TDX_OFFICIAL_G4DAY',input_ref=descriptor,package=value['package'],previous_session=previous)


@pytest.fixture
def retained(setup_plan,tmp_path,request):
    failure=getattr(request,'param',None)
    policy,args,_=setup_plan;scope=policy['governance']['incremental_capacity']
    archive=tmp_path/'archive.day';archive.write_bytes(raw(20261118))
    native=tmp_path/'old.day';native.write_bytes(raw(SOURCE,1234))
    current=tmp_path/'current.day';current.write_bytes((raw(SOURCE,9999)if failure=='prefix'else native.read_bytes())+raw(TARGET))
    archive_ref=dict(capacity.file_reference(archive),source_role='archive')
    native_ref=dict(capacity.file_reference(native),source_role='native')
    live_ref=capacity.file_reference(current)
    new_ref=dict(live_ref,source_role='native',original_ref=dict(current_native=live_ref))
    item=dict(raw_resolution='ARCHIVE_PRIMARY_NATIVE_MISSING_AND_TAIL_V2',history_start_date=20261118,compute_start_date=20261118,
              raw_files=[archive_ref,native_ref])
    binding={'original':'same accepted history'}
    source=dict(asof_date=SOURCE,symbols={CODE:item},history_retention_binding=binding)
    source_ref=save(tmp_path/'source.json',source)
    pins={key:key+'-fixture'for key in ('driver_sha256','formula_sha256','user_formula_sha256','field_contract_sha256')}
    candidates=dict(selector='1'*64,backtest='2'*64)
    source_generation=save(tmp_path/'source_generation.json',dict(status='READY',asof_date=SOURCE,
        input_sha256=capacity.digest(source),adjustment_snapshot=source_ref,candidate_sha256=candidates,**pins))
    skipped=official(tmp_path/'skipped',RETAINED,SOURCE,absent=failure!='traded_skip')
    skipped_sync=save(tmp_path/'skipped_sync.json',dict(target_date=str(RETAINED),official_daily_source=skipped,
        symbol_reconciliation=[dict(market=0,symbol=CODE[:6],classification='QUARANTINED',quarantine=True,
            target_date_ready=False,reason_code='TARGET_DATE_MISSING',last_date_before=SOURCE,
            last_date_after=RETAINED if failure=='coverage'else SOURCE,
            source_sha256_before=native_ref['sha256'],source_sha256_after=native_ref['sha256'])]))
    prior=dict(asof_date=RETAINED,symbols={},retained_history_codes=[]if failure=='not_retained'else[CODE],
               history_retention_binding=binding,source_files=[skipped_sync])
    prior_ref=save(tmp_path/'prior.json',prior);baseline=dict(selector='3'*64,backtest='4'*64)
    parent=save(tmp_path/'parent.json',dict(status='READY',generation_id='parent',asof_date=RETAINED,
        input_sha256=capacity.digest(prior),adjustment_snapshot=prior_ref,candidate_sha256=baseline,baseline_panel_sha256=candidates,**pins))
    evidence=save(tmp_path/'evidence.json',dict(schema='qfq_retained_native_recovery_v1',target_date=TARGET,
        previous_snapshot=prior_ref,previous_generation=parent,symbols={CODE:dict(source_snapshot=source_ref,
            source_generation=source_generation,retained_sync_ref=skipped_sync)}))
    today=official(tmp_path/'today',TARGET,RETAINED)
    sync=save(tmp_path/'sync.json',dict(target_date=str(TARGET),official_daily_source=today,
        symbol_reconciliation=[dict(market=0,symbol=CODE[:6],classification='ACCEPTED',target_date_ready=True,
                                   path=live_ref['path'],source_sha256_after=live_ref['sha256'])]))
    cache=save(tmp_path/'cache.json',dict(prequery_sync_ref=sync))
    snapshot=save(tmp_path/'snapshot.json',dict(asof_date=TARGET,symbols={CODE:dict(item,raw_files=[archive_ref,new_ref])},
        source_files=[cache],research_cache_configuration=cache))
    if failure!='unapproved':scope['retained_reactivation_evidence']=dict(path=evidence['path'],sha256=evidence['sha256'])
    count=2 if failure=='undercount'else 3
    args.update(changed_rows=count,revised_symbols=1,classifications={CODE:'NEW_OR_MISSING_HISTORY'},
        source_identity=dict(snapshot_sha256=snapshot['sha256'],baseline=baseline,source_semantics=dict(pins),changed_rows_by_symbol={CODE:count},
            classification_dependencies={CODE:'a'*64},retained_reactivation_context=dict(snapshot=snapshot,
                previous_snapshot=prior_ref,baseline_generations=dict(selector='parent',backtest='parent'))))
    if failure=='hidden_rule':args['source_identity']['source_semantics']['formula_sha256']='new-rule'
    return policy,args,tmp_path


def test_verified_retained_prefix_keeps_new_kind_full_count_and_cas(retained):
    policy,args,root=retained;before={p:p.read_bytes()for p in root.rglob('*')if p.is_file()}
    plan=capacity.build_plan(policy,'qfq',**args)
    assert plan['classifications']=={CODE:'NEW_OR_MISSING_HISTORY'}
    assert plan['changed_rows']==3 and plan['revised_symbols']==1
    assert plan['predicted_bytes']==64*1024**2+8192+3*4096
    proof=plan['source_identity']['retained_reactivation_proofs'][CODE]
    assert proof['changed_rows']==3 and proof['classification_sha256']==args['source_identity']['classification_dependencies'][CODE]
    assert before=={p:p.read_bytes()for p in root.rglob('*')if p.is_file()}
    capacity.validate_plan(plan,policy=policy)
    (root/'old.day').write_bytes(raw(SOURCE,4321))
    with pytest.raises(capacity.CapacityProofError,match='INPUT_CHANGED'):capacity.validate_plan(plan,policy=policy)


@pytest.mark.parametrize('retained',['not_retained','traded_skip','coverage','prefix','undercount','unapproved','hidden_rule'],indirect=True)
def test_unproved_retained_reactivation_fails_before_writes(retained):
    policy,args,root=retained;before={p:p.read_bytes()for p in root.rglob('*')if p.is_file()}
    with pytest.raises(capacity.CapacityProofError,match='RETAINED_REACTIVATION'):
        capacity.build_plan(policy,'qfq',**args)
    assert before=={p:p.read_bytes()for p in root.rglob('*')if p.is_file()}


@pytest.mark.parametrize('failure',['rule','revised_cap','row_cap'])
def test_retained_exception_does_not_waive_existing_scope_limits(retained,failure):
    policy,args,_=retained;args=copy.deepcopy(args)
    if failure=='rule':args['classifications'][CODE]='RULE_REVISION'
    elif failure=='revised_cap':args['revised_symbols']=3
    else:args['changed_rows']=12001;args['source_identity']['changed_rows_by_symbol'][CODE]=12001
    with pytest.raises(capacity.CapacityProofError,match='FULL_REBUILD_REQUIRED'):
        capacity.build_plan(policy,'qfq',**args)
