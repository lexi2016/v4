from __future__ import annotations

import copy
import json
from pathlib import Path

import pandas as pd
import pytest

from upstreams.v3_shared_data.shared_data.hk_panel_audit import (
    audit_frame, reconcile_frames, stage_hk_panel_candidate,
    load_staged_hk_panel_candidate, strict_window_readiness, SAFETY,
)
from upstreams.v3_shared_data.shared_data.hashing import sha256_file
from upstreams.v3_shared_data.shared_data.store import StoreError


def bar(code='HK.00001', date='20261001', **changes):
    return dict(code_norm=code, trade_date_compact=date, open=10., high=11., low=9., close=10., amount=30_000_000., trade=1_000., **changes)


def test_every_row_accounted_identical_refs_conflict_invalid_and_outside():
    rows = [bar(), bar(), bar('HK.00002'), dict(bar('HK.00002'), close=10.5),
        bar('HK.00003', '20260230'), dict(bar('HK.00004'), close=float('nan')),
        dict(bar('HK.00005'), open=12.), bar('HK.00006', '20261024'),
        dict(bar('HK.00007'), amount=-1), dict(bar('HK.00008'), trade=0)]
    facts, ledger, profile = audit_frame(pd.DataFrame(rows), package='C', source_sha256='a'*64, through_date='20261023')
    assert len(ledger) == sum(profile['dispositions'].values()) == len(rows)
    assert ledger.source_row.tolist() == list(range(len(rows)))
    assert ledger.disposition.tolist() == ['ACCEPTED', 'DUPLICATE_IDENTICAL', 'QUARANTINED', 'QUARANTINED', 'QUARANTINED', 'QUARANTINED', 'QUARANTINED', 'OUT_OF_WINDOW', 'QUARANTINED', 'ACCEPTED']
    assert ledger.loc[1, 'representative_source_row'] == 0
    assert 'OHLC_ORDER_INVALID' in ledger.loc[6, 'reasons']
    assert facts.loc[9, 'trade'] == 0  # zero is retained, never invented or filled


def test_c_over_b_uses_raw_keys_even_when_c_quarantined():
    c = pd.DataFrame([dict(bar(), close=-1), bar('HK.00002')])
    b = pd.DataFrame([bar(), bar('HK.00002'), bar('HK.00003')])
    result, ledger, profile = reconcile_frames(c,b,c_sha256='a'*64,b_sha256='b'*64,through_date='20261023')
    assert set(result.code_norm) == {'HK.00002','HK.00003'}
    assert ledger[ledger.source_package.eq('B')].disposition.tolist() == ['SHADOWED_BY_C','SHADOWED_BY_C','ACCEPTED']
    assert set(result.price_readiness) == {'PENDING'}
    assert profile['c_over_b_overlap_rows'] == 2


def test_candidate_is_repeatable_hash_bound_and_does_not_touch_input(tmp_path):
    c, b = tmp_path/'c.parquet', tmp_path/'b.parquet'
    pd.DataFrame([bar()]).to_parquet(c,index=False)
    pd.DataFrame([bar('HK.00002')]).to_parquet(b,index=False)
    pins = sha256_file(c), sha256_file(b)
    def stage(destination):
        return stage_hk_panel_candidate(c,b,destination,expected_c_sha256=pins[0],expected_b_sha256=pins[1],through_date='20261023')
    one, two = stage(tmp_path/'one'), stage(tmp_path/'two')
    assert one == two == stage(tmp_path/'one')
    assert pins == (sha256_file(c),sha256_file(b))
    frame, manifest = load_staged_hk_panel_candidate(tmp_path/'one/manifest.json',sha256_file(tmp_path/'one/manifest.json'))
    assert len(frame) == 2 and manifest['semantic_status'] == 'CANNOT_CONFIRM'
    (tmp_path/'one/candidate.parquet').write_bytes(b'changed')
    with pytest.raises(StoreError,match='ARTIFACT_SHA_MISMATCH'):
        load_staged_hk_panel_candidate(tmp_path/'one/manifest.json',sha256_file(tmp_path/'one/manifest.json'))
    with pytest.raises(StoreError,match='IMMUTABLE_CONFLICT'):stage(tmp_path/'one')


def window():
    dates = pd.bdate_range('2026-09-23',periods=21).strftime('%Y%m%d').tolist()
    return dates,[bar(date=d) for d in dates]


def material(tmp_path, dates, **changes):
    records = [dict(code='HK.00001',date=d,panel_sha256='a'*64,available_at='2026-10-21T10:00:00+08:00',price_currency='HKD',amount_currency='HKD',amount_unit='HKD',adjustment='PIT_ADJUSTED',corporate_actions_complete=True,pit_available=True,eligible=True,suspended=False,listing_date='20000101',**changes) for d in list(dict.fromkeys([*dates,'20261023']))]
    path = tmp_path/'material.json'
    path.write_text(json.dumps(dict(schema_version='hk_panel_strict_material.v1',market='HK',panel_sha256='a'*64,records=records,**SAFETY)))
    ref = dict(reference=str(path),sha256=sha256_file(path))
    return [dict(row,evidence_refs=[ref]) for row in records]


def ready(rows, dates, proof=None):
    return strict_window_readiness(rows,code='HK.00001',sessions=dates,cutoff='2026-10-23T09:00:00+08:00',panel_sha256='a'*64,proof=proof,target_date='20261023')


@pytest.mark.parametrize('proof', [None,{},'VERIFIED',[None],['bad'],[{'code':'HK.00001','date':'20261001','corporate_actions_complete':True}]])
def test_unknown_and_malformed_proof_stays_pending(proof):
    dates, rows = window()
    result = ready(rows,dates,proof)
    assert result['status'] == 'PENDING' and result['field_readiness']['adjustment'] == 'PENDING'


def test_fixture_material_pass_reject_precedence_and_tamper(tmp_path):
    dates, rows = window()
    proof = material(tmp_path,dates)
    assert ready(rows,dates,proof)['status'] == 'PASS'
    # A future material cannot certify an earlier cutoff.
    future = copy.deepcopy(proof)
    for record in future:record['available_at'] = '2026-10-24T10:00:00+08:00'
    assert ready(rows,dates,future)['status'] == 'PENDING'
    proof = material(tmp_path,dates,**{})
    data=json.loads((tmp_path/'material.json').read_text())
    data['records'][-1]['eligible']=False
    (tmp_path/'material.json').write_text(json.dumps(data))
    proof=[dict(r,evidence_refs=[dict(reference=str(tmp_path/'material.json'),sha256=sha256_file(tmp_path/'material.json'))]) for r in data['records']]
    # Other missing proof must never erase a known failure.
    proof.pop(0)
    assert ready(rows,dates,proof)['status'] == 'REJECT'
    (tmp_path/'material.json').write_text('{}')
    assert ready(rows,dates,proof)['status'] == 'PENDING'


def test_missing_duplicate_and_nonfinite_window_facts_cannot_pass(tmp_path):
    dates,rows=window();proof=material(tmp_path,dates)
    assert ready(rows[:-1],dates,proof)['status']=='PENDING'
    assert ready(rows+rows[-1:],dates,proof)['status']=='PENDING'
    rows[1]['amount']=float('inf')
    assert ready(rows,dates,proof)['status']=='PENDING'


def test_target_only_membership_and_missing_target_fail_closed(tmp_path):
    dates,rows=window();proof=material(tmp_path,dates)
    payload=json.loads((tmp_path/'material.json').read_text())
    for record in payload['records'][:-1]:
        record['eligible']=False;record['suspended']=True
    (tmp_path/'material.json').write_text(json.dumps(payload))
    proof=[dict(row,evidence_refs=[dict(reference=str(tmp_path/'material.json'),sha256=sha256_file(tmp_path/'material.json'))]) for row in payload['records']]
    assert ready(rows,dates,proof)['status']=='PASS'
    no_target=strict_window_readiness(rows,code='HK.00001',sessions=dates,cutoff='2026-10-23T09:00:00+08:00',panel_sha256='a'*64,proof=proof)
    assert no_target['status']=='PENDING' and no_target['field_readiness']['eligibility']=='PENDING'
    rows[0]['resolution_held_fields']='trade'
    assert ready(rows,dates,proof)['status']=='PASS'
    rows[0]['resolution_held_fields']='close,trade'
    assert ready(rows,dates,proof)['status']=='PENDING'


def test_reconciliation_retains_price_path_when_only_trade_is_held():
    class Policy:
        manifest_sha256='d'*64
        decisions={('HK.00001','20261001'):{}}
        corrections={}
        def check_panel(self,sha):assert sha=='a'*64
        def project_frame(self,frame):return frame
        def held_fields(self,code,date):return ['trade']
    candidate,ledger,profile=reconcile_frames(pd.DataFrame([bar()]),pd.DataFrame([bar('HK.00002')]),c_sha256='a'*64,b_sha256='b'*64,through_date='20261023',policy=Policy())
    assert len(candidate)==2 and candidate.iloc[0]['resolution_held_fields']=='trade'
    assert ledger.iloc[0]['disposition']=='ACCEPTED_WITH_FIELD_HOLDS'


def test_byte_bound_numeric_unknowns_cannot_be_substituted_by_boolean_claims(tmp_path):
    dates, rows = window()
    proof = material(tmp_path, dates)
    assert ready(rows, dates, proof)['status'] == 'PASS'  # authentic booleans
    path = tmp_path/'material.json'
    payload = json.loads(path.read_text())
    for record in payload['records']:
        for key in ('corporate_actions_complete', 'pit_available', 'eligible'):
            record[key] = 1
        record['suspended'] = 0
    path.write_text(json.dumps(payload))
    refs = [dict(reference=str(path), sha256=sha256_file(path))]
    actual = [dict(record, evidence_refs=refs) for record in payload['records']]
    for record in proof:
        record['evidence_refs'] = refs
    assert ready(rows, dates, actual)['status'] == 'PENDING'
    assert ready(rows, dates, proof)['status'] == 'PENDING'


@pytest.mark.parametrize('field', ['research_only', 'production_allowed', 'buy_gate_updated', 'orders_sent'])
def test_material_schema_rejects_numeric_safety_flags(tmp_path, field):
    dates, rows = window()
    proof = material(tmp_path, dates)
    path = tmp_path/'material.json'
    payload = json.loads(path.read_text())
    payload[field] = int(payload[field])
    path.write_text(json.dumps(payload))
    refs = [dict(reference=str(path), sha256=sha256_file(path))]
    for record in proof:
        record['evidence_refs'] = refs
    assert ready(rows, dates, proof)['status'] == 'PENDING'


@pytest.mark.parametrize('field', ['open', 'high', 'low', 'close', 'amount', 'trade'])
@pytest.mark.parametrize('value', [True, False])
def test_mixed_boolean_is_not_a_financial_numeric_fact(field, value):
    rows = [dict(bar(), **{field:value}), bar('HK.00002')]
    facts, ledger, profile = audit_frame(pd.DataFrame(rows), package='C', source_sha256='a'*64)
    assert ledger.disposition.tolist() == ['QUARANTINED', 'ACCEPTED']
    assert 'BOOLEAN_' + field.upper() in ledger.iloc[0]['reasons']
    assert ledger.source_row.tolist() == [0, 1]
    assert ledger.source_sha256.tolist() == ['a'*64, 'a'*64]
    assert facts.iloc[1][field] == rows[1][field]
    assert profile['input_rows'] == 2
