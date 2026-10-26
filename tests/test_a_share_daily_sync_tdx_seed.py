"""Synthetic fixtures for explicit TDX seed evidence; no provider imports."""
import hashlib
import importlib.util
import json
import struct
import sys
import types
from pathlib import Path

import pytest

PARTS = Path('/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/a-share-daily-sync-component-20261025-seedguard-ipo-r4/ops/_a_share_daily_sync_parts')
pkg = types.ModuleType('_tdx_seed_under_test')
pkg.__path__ = [str(PARTS)]
sys.modules[pkg.__name__] = pkg
spec = importlib.util.spec_from_file_location(pkg.__name__ + '.progress', Path(__file__).resolve().parents[1] / 'ops/_a_share_daily_sync_parts/progress.py')
p = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = p
spec.loader.exec_module(p)
CODE = '920002.BJ'
DAY = struct.Struct('<IIIIIfII')
SCOPE = {'DAY_STRUCT': DAY, 'MAX_CROSS_DAY_CLOSE_RATIO': 1.5}


def save(path, value):
    path.write_text(json.dumps(value, sort_keys=True))
    return dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())


@pytest.fixture
def case(tmp_path):
    terms = ('hongli_panqianliutong', 'peigujia_qianzongguben', 'songgu_qianzongguben', 'peigu_houzongguben')
    cash = struct.unpack('<f', struct.pack('<f', 2.1))[0]
    row = dict(market=2, code='920002', ts_code=CODE, datetime=20260212, category=1,
               **dict(zip(terms, [2.099999904632568, 0., 0., 0.])))
    event = dict(ex_date=20260212, a=1., b=-cash / 10, volume_a=1.)
    refs = {k: save(tmp_path / (k + '.json'), dict(fixture=k)) for k in ('raw', 'zip', 'decoder', 'converter')}
    policy = dict(policy_id='TDX_GBBQ_CATEGORY1_AFFINE_BJ_V1', controller='fixture', RESEARCH_ONLY=True,
                  production_allowed=False, buy_gate_updated=False, orders_sent=False,
                  category_policy={'1': 'PRICE_ACTION_PER10_CASH_RIGHTS_BONUS_AFFINE'})
    pol = save(tmp_path / 'policy.json', policy)
    rows = save(tmp_path / 'rows.json', dict(ts_code=CODE, rows=[row]))
    witnesses = [dict(date=row['datetime'], category=1, field=k, stored_JSON=row[k], true_wire_float=v, true_wire_hex=v.hex())
                 for k, v in zip(terms, [cash, 0., 0., 0.])]
    wire = dict(code=CODE, rows=[row], exact_term_evidence=witnesses)
    wr = save(tmp_path / 'wire.json', wire)
    proof = dict(schema='GENUINE_ORIGINAL_WIRE_SINGLE_SYMBOL_PROOF', code=CODE, original_decoder=refs['decoder'], original_raw=refs['raw'],
                 decoder_calls=1, original_JSON_double_precision15_roundtrip=True, true_price_term_inputs_equal_prior_original_converter=True,
                 event_coefficients_cast=False, original_converter_output_reused=refs['converter'], events=[event], wire_rows=1)
    pr = save(tmp_path / 'proof.json', proof)
    closure = dict(schema='TDX_GBBQ_ORIGINAL_WIRE_SINGLE_SYMBOL_CLOSURE_V1', symbol=CODE, asof_date=20261023, compute_start_date=20240530,
                   wire_schema='<B7sIBffff', term_encoding='IEEE754_BINARY32', source_kind='TDX_GBBQ_CATEGORY1_AFFINE_BJ_V1_NOT_FUTU_EQUIVALENT',
                   futu_equivalence=False, source_files=[refs['raw'], refs['zip'], refs['decoder'], pol, rows], policy=pol, symbol_rows=rows,
                   wire_result=pr, wire_rows=wr, original_converter=refs['converter'], events=[event])
    closure.update(raw=refs['raw'], decoder=refs['decoder'])
    cr = save(tmp_path / 'closure.json', closure)
    raw = tmp_path / 'archive.day'
    raw.write_bytes(DAY.pack(20260211, 10000, 10000, 10000, 10000, 1000., 100, 0) + DAY.pack(20260212, 9900, 9900, 9900, 9900, 1000., 100, 0))
    rawref = dict(path=str(raw), sha256=hashlib.sha256(raw.read_bytes()).hexdigest(), source_role='archive')
    item = dict(history_start_date=20240530, history_end_date=20261019, compute_start_date=20240530, event_coverage_complete=True,
                source_method='TDX_OFFICIAL_TERMS_BOUND_CONVERSION', raw_resolution='ARCHIVE_PRIMARY_NATIVE_MISSING_AND_TAIL_V2', events=[event], raw_files=[rawref])
    bundle = dict(descriptor=dict(tdx_seed_sources={CODE: cr}), snapshot=dict(asof_date=20261023, symbols={CODE: item}), checkpoint={'symbols': {}}, coverage=20261023, symbols={})
    return dict(root=tmp_path, item=item, bundle=bundle, closure=closure, wire=wire, proof=proof, policy=policy, rows=[row])


def rebind(c, kind):
    if kind == 'closure':
        c['bundle']['descriptor']['tdx_seed_sources'][CODE] = save(c['root'] / 'closure.json', c['closure'])
    else:
        field = dict(wire='wire_rows', proof='wire_result', policy='policy', rows='symbol_rows')[kind]
        value = dict(ts_code=CODE, rows=c['rows']) if kind == 'rows' else c[kind]
        old = c['closure'][field]
        new = save(Path(old['path']), value)
        c['closure'][field] = new
        if kind in ('policy', 'rows'):
            c['closure']['source_files'] = [new if x == old else x for x in c['closure']['source_files']]
        rebind(c, 'closure')


def test_exact_float32_source_terms_and_no_event_coefficient_cast(case):
    result = p._seed_symbol_evidence(SCOPE, case['bundle'], CODE)
    assert result['events'][20260212][1] == -0.20999999046325685
    assert result['provider_response'] == case['bundle']['descriptor']['tdx_seed_sources'][CODE]


@pytest.mark.parametrize('change,reason', [
    ('futu_equivalence', 'tdx_source_kind_or_scope'), ('asof', 'tdx_source_kind_or_scope'),
    ('compute_start', 'tdx_source_kind_or_scope'), ('codec', 'tdx_source_kind_or_scope'),
    ('raw_source', 'tdx_genuine_wire_binding'), ('bad_wire', 'tdx_wire_term_parity'),
    ('unknown_category', 'tdx_unexplained_category'), ('wrong_code', 'tdx_row_identity'),
    ('missing_event', 'tdx_adopted_event_conflict'), ('wrong_event', 'tdx_adopted_event_conflict'),
    ('missing_ref', 'tdx_source_closure'), ('bad_policy', 'tdx_category_policy')])
def test_invalid_tdx_proof_fails_closed(case, change, reason):
    if change in ('futu_equivalence', 'asof', 'compute_start', 'codec'):
        field, value = dict(futu_equivalence=('futu_equivalence', True), asof=('asof_date', 20261022),
                            compute_start=('compute_start_date', 20240529), codec=('wire_schema', 'float64'))[change]
        case['closure'][field] = value
        rebind(case, 'closure')
    elif change == 'raw_source': case['proof']['original_raw'] = case['proof']['original_decoder']; rebind(case, 'proof')
    elif change == 'bad_wire': case['wire']['exact_term_evidence'][0]['true_wire_hex'] = '0x0.0p+0'; rebind(case, 'wire')
    elif change == 'unknown_category': case['policy']['category_policy']['1'] = 'BLOCK'; rebind(case, 'policy')
    elif change == 'wrong_code':
        case['rows'][0]['code'] = '920003'; case['wire']['rows'] = case['rows']; rebind(case, 'rows'); rebind(case, 'wire')
    elif change == 'missing_event': case['item']['events'] = []
    elif change == 'wrong_event': case['item']['events'][0]['b'] = 0
    elif change == 'missing_ref': case['closure']['source_files'].pop(); rebind(case, 'closure')
    elif change == 'bad_policy': case['policy']['production_allowed'] = True; rebind(case, 'policy')
    with pytest.raises(ValueError, match=reason):
        p._seed_symbol_evidence(SCOPE, case['bundle'], CODE)


def test_mutated_pinned_rows_rejected(case):
    Path(case['closure']['symbol_rows']['path']).write_text('{}')
    with pytest.raises(ValueError, match='reference_sha256_mismatch'):
        p._seed_symbol_evidence(SCOPE, case['bundle'], CODE)


def test_futu_dispatch_keeps_original_provider_guard(case):
    case['item']['source_method'] = 'FUTU_GET_REHAB_AFFINE'
    case['bundle']['checkpoint']['symbols'][CODE] = dict(status='ERROR', asof_date=20261023)
    with pytest.raises(ValueError, match='provider_status'):
        p._seed_symbol_evidence(SCOPE, case['bundle'], CODE)


def test_raw_basis_conflict_is_not_waived(case):
    context = dict(path='synthetic-descriptor', bundle=case['bundle'], records=[])
    assert not p._explain_seed_pair(SCOPE, context, CODE, 20261023, 20260211, 20260212, 100., 20.)
    assert context['records'][0]['reason'] == 'pair_raw_basis_conflict'
