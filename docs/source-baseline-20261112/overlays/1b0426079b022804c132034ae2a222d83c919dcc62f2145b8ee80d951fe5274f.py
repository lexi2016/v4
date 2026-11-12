from dataclasses import replace
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from stage_center.a_share_membership import CONFIG_ENV, CONFIG_SHA_ENV, SCHEMA, resolve_membership
from stage_center.acquisition import SourceResult, StageUniverseBinding, build_plan

CODES = ("A.600000", "A.920045", "A.920985", "A.000660", "A.515880")
SHA = "b" * 64


def write(path, value):
    path.write_text(json.dumps(value))
    return {"path":str(path), "sha256":hashlib.sha256(path.read_bytes()).hexdigest()}


def authority(tmp_path, *, mutate_snapshot=None, mutate_config=None):
    generation = "a" * 64
    snapshot = dict(schema="a_share_qfq_adjustment_input_research_cache_v1", asof_date=20261111,
                    coverage_end_date=20261111, original_target_codes=["600000.SH", "920045.BJ", "920985.BJ"],
                    symbols={"600000.SH":{}, "920985.BJ":{}},
                    original_quarantine_eligible={"920045.BJ":{"reason":"SUSPENDED"}}, quarantine_symbols={})
    if mutate_snapshot:
        mutate_snapshot(snapshot)
    snapref = write(tmp_path/"snapshot.json", snapshot)
    manifest_path = tmp_path/"manifest.json"
    panel = tmp_path/"selector.parquet"
    footer = dict(generation_id=generation, asof_date=20261111, generation_manifest_path=str(manifest_path), snapshot_file_sha256=snapref['sha256'])
    # Only one traded daily bar. Two legitimate BJ targets have no daily bar.
    pq.write_table(pa.table({'ts_code':['600000.SH'], 'trade_date':['20261111']}).replace_schema_metadata(
        {b'a_share_qfq_contract_v1':json.dumps(footer).encode()}), panel)
    panel_ref = dict(path=str(panel),sha256=hashlib.sha256(panel.read_bytes()).hexdigest())
    manifest = dict(status="CANDIDATE_READY", asof_date=20261111, target_date=20261111,
                    generation_id=generation, adjustment_snapshot=snapref, snapshot_file_sha256=snapref['sha256'],
                    candidates={'selector':str(panel)},candidate_sha256={'selector':panel_ref['sha256']},
                    production_allowed=False, buy_gate_updated=False, orders_sent=False)
    config = dict(schema=SCHEMA+'.config',trade_date='20261112',signal_date='20261111',candidate_current_sha256=SHA,
                  generation_id=generation,generation_manifest=write(manifest_path,manifest),selector=panel_ref)
    if mutate_config:
        mutate_config(config)
    ref=write(tmp_path/'config.json',config)
    return {CONFIG_ENV:ref['path'],CONFIG_SHA_ENV:ref['sha256']}


def resolve(env):
    return resolve_membership(CODES,'20261112',candidate_sha256=SHA,environ=env)


def test_dated_positive_inventory_keeps_bj_suspended_and_unknown_but_quarantines_etf(tmp_path):
    m=resolve(authority(tmp_path))
    assert m.report['status']=='BOUND_POSITIVE_INVENTORY'
    assert m.codes==CODES[:-1]
    assert m.report['unknown_codes']==['A.000660']
    assert m.report['quarantined']==[dict(code='A.515880',reason='NON_EQUITY_CODE_FAMILY',classification='KNOWN_NON_STOCK_FAMILY')]
    assert m.report['inventory_is_listing_or_pit_proof'] is False


def test_request_scoring_and_coverage_share_filter_and_hk_is_untouched(tmp_path):
    m=resolve(authority(tmp_path))
    a=StageUniverseBinding.ready(market='A_SHARE',trade_date='20261112',role='SOURCE',codes=CODES,source_run_id='r',sha256=SHA)
    hk=StageUniverseBinding.ready(market='HK_CONNECT',trade_date='20261112',role='HK',codes=('HK.00700',),source_run_id='h',sha256='c'*64)
    plan=build_plan(tmp_path,'20261112','STAGE_0930_0935',candidate=SimpleNamespace(codes=CODES),universe_bindings={'A_SHARE':m.bind(a),'HK_CONNECT':m.bind(hk)})
    assert plan.codes_for('A_SHARE')==CODES[:-1]
    assert plan.codes_for('HK_CONNECT')==('HK.00700',)
    source=SourceResult('cached','PARTIAL_WITH_ROWS',rows=tuple({'code':code} for code in ['SH.600000','BJ.920045','BJ.920985','SH.515880']),requested_rows=5,missing_symbols=('SZ.000660',),cannot_confirm=('ORIGINAL_QUOTE_GAP',))
    filtered=m.source(source)
    assert len(source.rows)==4  # Original object untouched.
    assert len(filtered.rows)==3 and filtered.requested_rows==4
    assert filtered.missing_symbols==('SZ.000660',)
    assert m.source(source,'HK_CONNECT') is source
    raw=dict(requested_rows=5,missing_symbols=['SZ.000660'],cannot_confirm=['ORIGINAL_QUOTE_GAP'],source_evidence=[])
    view=m.builder_raw(raw,filtered)
    assert raw['requested_rows']==5 and view['requested_rows']==4
    assert 'ORIGINAL_QUOTE_GAP' in view['cannot_confirm']
    assert any('A.000660' in reason for reason in view['cannot_confirm'])


@pytest.mark.parametrize('changes',[{}, {CONFIG_ENV:'/missing'}, {CONFIG_SHA_ENV:'a'*64}])
def test_missing_authority_never_drops_or_globally_blocks_candidates(changes):
    m=resolve(changes)
    assert m.codes==CODES[:-1] and m.report['status']=='UNKNOWN'
    src=SourceResult('cache','READY',rows=({'code':'A.600000'},),requested_rows=5)
    result=m.source(src)
    assert result.rows==src.rows and result.requested_rows==4 and result.status=='PARTIAL_WITH_ROWS'
    assert 'A_MEMBERSHIP_AUTHORITY_UNKNOWN' in result.cannot_confirm
    assert m.report['quarantined'][0]['code']=='A.515880'
    assert set(CODES[:-1])==set(m.codes)  # Includes both BJ and unknown stock.


@pytest.mark.parametrize('field,value',[('trade_date','20261113'),('signal_date','20261112'),('generation_id','f'*64),('candidate_current_sha256','f'*64)])
def test_mismatched_authority_is_unknown_without_shrinking_request(tmp_path,field,value):
    m=resolve(authority(tmp_path,mutate_config=lambda c:c.update({field:value})))
    assert m.codes==CODES[:-1] and m.report['status']=='UNKNOWN'


@pytest.mark.parametrize('mutation',[
    lambda s:s.pop('original_target_codes'),
    lambda s:s['symbols'].pop('920985.BJ'),
])
def test_incomplete_inventory_cannot_be_used_as_negative_membership(tmp_path,mutation):
    m=resolve(authority(tmp_path,mutate_snapshot=mutation))
    assert m.codes==CODES[:-1] and m.report['status']=='UNKNOWN'


def test_tampered_authority_sha_never_filters(tmp_path):
    env=authority(tmp_path)
    Path(env[CONFIG_ENV]).write_text('{}')
    m=resolve(env)
    assert m.codes==CODES[:-1] and m.report['status']=='UNKNOWN'
