import hashlib
import json
from pathlib import Path

import pytest

from infrastructure.research_workbench_formula_group_supplement import (
    PINNED_SCORE_RULES_MAP_SHA256,
    PINNED_SCORE_RULES_SHA256,
    _canonical_sha,
    load,
)


FLAGS = dict(RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)
SYMBOL = '000610.SZ'
SOURCE_DATE = '2026-11-20'
OBSERVATION_DATE = '2026-11-23'
GENERATION = 'e' * 64
INPUT = 'f' * 64
SELECTOR = '9' * 64
NUMERIC = dict(path='/products/20261120.json', sha256='b' * 64)
RULES = PINNED_SCORE_RULES_SHA256
BASIS = dict(price_basis='QFQ_ASOF', volume_basis='QFQ_EVENT_VOLUME')


def write_ref(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode()
    path.write_bytes(raw)
    return dict(path=str(path.resolve()), sha256=hashlib.sha256(raw).hexdigest())


def write_f10_ref(owner_root, directory, value):
    raw = (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode()
    digest = hashlib.sha256(raw).hexdigest()
    path = owner_root / directory / (digest + '.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return dict(path=str(path.resolve()), sha256=digest)


def write_f10_stock(owner_root, symbol, invalid=None):
    row = dict(symbol=symbol, status='OBSERVED', historical_PIT=False, **FLAGS)
    if invalid == 'wrong_symbol':
        row['symbol'] = '999999.SZ'
    elif invalid == 'failed_status':
        row['status'] = 'FAILED'
    elif invalid == 'unsafe_flags':
        row['buy_gate_updated'] = True
    elif invalid == 'historical_pit':
        row['historical_PIT'] = True
    raw = (json.dumps(row, sort_keys=True, separators=(',', ':')) + '\n').encode()
    if invalid == 'corrupt_json':
        raw = b'{not-json\n'
    elif invalid == 'non_object':
        raw = b'[]\n'
    digest = hashlib.sha256(raw).hexdigest()
    if invalid == 'sha_mismatch':
        digest = hashlib.sha256(b'different bytes').hexdigest()
    stock_root = owner_root
    if invalid == 'outside_root':
        stock_root = owner_root.parents[2] / 'foreign_f10' / owner_root.parent.name / owner_root.name
    path = stock_root / 'stocks' / symbol / (digest + '.json')
    if invalid != 'missing':
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    return dict(path=str(path), sha256=digest)


def build_supplement(root, *, pin_rules=True, corrupt_rules=False, symbols=None, f10_outcomes=None,
        d35c_items=None, invalid_f10=None, include_unreadable_non_roster=False,
        supplement_status='COMPLETE', f10_raw_counts=None):
    symbols = [SYMBOL] if symbols is None else symbols
    day_root = root / SOURCE_DATE
    score_root = root / 'score-action'
    formula = dict(schema='V4_WORKBENCH_FORMULA_GROUP_OVERRIDE_V1', source_date=SOURCE_DATE,
        observation_date=OBSERVATION_DATE, generation=GENERATION, input_sha256=INPUT,
        numeric_manifest=NUMERIC, selector_sha256=SELECTOR,
        rows=[dict(symbol=symbol) for symbol in symbols], **FLAGS)
    formula_ref = write_ref(day_root / 'formula/artifact.json', formula)
    roster_sha = hashlib.sha256(json.dumps(sorted(symbols), ensure_ascii=False, sort_keys=True,
        separators=(',', ':')).encode()).hexdigest()
    identity = dict(source_date=SOURCE_DATE, observation_date=OBSERVATION_DATE,
        generation=GENERATION, input_sha256=INPUT, numeric_manifest=NUMERIC,
        selector_sha256=SELECTOR, formula_group_sha256=formula_ref['sha256'],
        roster_symbols_sha256=roster_sha, roster_count=len(symbols))
    index_rules = dict(RULES, kb_action='3' * 64) if corrupt_rules else RULES
    index = dict(items={symbol:dict(path=f'/score/{symbol}.json',sha256='4'*64) for symbol in symbols},
        numeric_manifest=NUMERIC, source_generation=GENERATION, input_sha256=INPUT,
        source_selector_sha256=SELECTOR, rules=index_rules, price_basis=BASIS, **FLAGS)
    index_ref = write_ref(score_root / 'indexes/index.json', index)
    descriptor = dict(status='READY', data_date='20261120', source_generation=GENERATION,
        input_sha256=INPUT, numeric_manifest=NUMERIC, counts=dict(total=len(symbols)), index=index_ref, **FLAGS)
    replay = dict(schema='V4_FORMULA_GROUP_SCORE_ACTION_REPLAY_V1',
        status='PREPARED_EXACT_OWNER_REPLAY', same_rule_sha=True, source_date=SOURCE_DATE,
        source_generation=GENERATION, input_sha256=INPUT, numeric_manifest=NUMERIC,
        formula_group_sha256=formula_ref['sha256'], descriptor=descriptor,
        statuses={symbol:dict(record_status='MATERIALIZED',score_status='READY',score=4)
            for symbol in symbols}, **FLAGS)
    if pin_rules:
        replay['score_rules'] = RULES
        replay['price_basis'] = BASIS
        replay['score_rule_map_sha256'] = PINNED_SCORE_RULES_MAP_SHA256
    replay_ref = write_ref(day_root / 'supplements/receipts/score-replay.json', replay)
    score_binding = dict(status='READY', receipt=replay_ref, artifact_root=str(score_root.resolve()),
        descriptor=descriptor)
    f10_binding = None
    if f10_outcomes is not None:
        observed, failed, remaining = f10_outcomes
        upstream_ref = dict(path='/products/upstream.json', sha256='5' * 64)
        scope_sha = '6' * 64
        owner_root = root/'f10'/SOURCE_DATE.replace('-', '')/GENERATION[:16]
        checkpoint_items = {symbol:write_f10_stock(owner_root, symbol, (invalid_f10 or {}).get(symbol))
            for symbol in observed}
        if include_unreadable_non_roster:
            checkpoint_items['999999.BJ'] = dict(
                path=str(root/'unreadable-foreign-stock.json'), sha256='7' * 64)
        checkpoint = dict(schema='v4.a_share.f10_checkpoint.v1',
            identity=dict(data_date='20261120', source_generation=GENERATION,
                input_sha256=INPUT, selector_sha256=SELECTOR, scope_sha256=scope_sha),
            items=checkpoint_items, upstream_success_receipt=upstream_ref, **FLAGS)
        checkpoint_ref = write_f10_ref(owner_root, 'checkpoints', checkpoint)
        raw_counts = f10_raw_counts or {}
        requested = raw_counts.get('requested', len(symbols) + (1 if include_unreadable_non_roster else 0))
        observed_count = raw_counts.get('observed', len(checkpoint_items))
        scope_count = raw_counts.get('scope_count', requested)
        receipt = dict(schema='v4.a_share.f10_daily_receipt.v1', status='PARTIAL',
            data_date='20261120', source_generation=GENERATION, input_sha256=INPUT,
            selector_sha256=SELECTOR, numeric_manifest=NUMERIC, scope_sha256=scope_sha,
            scope=dict(kind='ADMITTED_DAILY_UNIVERSE', count=scope_count, symbols=None),
            priority_scope=dict(symbols=sorted(symbols),
                count=raw_counts.get('priority_count', len(symbols))),
            checkpoint=checkpoint_ref, upstream_success_receipt=upstream_ref,
            requested=requested, observed=observed_count,
            failures={symbol:{'status':'FAILED'} for symbol in failed},
            remaining=list(remaining), historical_PIT=False, **FLAGS)
        f10_receipt_ref = write_f10_ref(owner_root, 'receipts', receipt)
        f10_binding = dict(status='PARTIAL', receipt=f10_receipt_ref)
    artifact = dict(schema='V4_WORKBENCH_FORMULA_GROUP_SUPPLEMENT_V1', status=supplement_status,
        **identity, score_action=score_binding, **FLAGS)
    if f10_binding is not None:
        artifact['f10'] = f10_binding
    if d35c_items is not None:
        marks_bundle = dict(schema='V4_WORKBENCH_ORIGINAL_D35C_MARKS_V1',
            source_date=SOURCE_DATE, generation=GENERATION, input_sha256=INPUT,
            numeric_manifest=NUMERIC, formula_group_sha256=formula_ref['sha256'],
            roster_symbols_sha256=roster_sha,
            price_basis='QFQ_ASOF_' + SOURCE_DATE.replace('-', ''),
            volume_basis=BASIS['volume_basis'], items=d35c_items,
            historical_PIT=False, **FLAGS)
        artifact['d35c_marks'] = write_ref(
            day_root / 'supplements/d35c/marks.json', marks_bundle)
        artifact['d35c_status'] = 'READY'
    artifact_ref = write_ref(day_root / 'supplements/artifacts/supplement.json', artifact)
    receipt = dict(schema='V4_WORKBENCH_FORMULA_GROUP_SUPPLEMENT_RECEIPT_V1', status='COMMITTED',
        artifact=artifact_ref, **identity, **FLAGS)
    receipt_ref = write_ref(day_root / 'supplements/receipts/supplement-receipt.json', receipt)
    pointer = dict(schema='V4_WORKBENCH_FORMULA_GROUP_SUPPLEMENT_COMMIT_V1',
        module='formula_group_supplement', status=supplement_status, **identity,
        artifact=artifact_ref, receipt=receipt_ref, **FLAGS)
    write_ref(day_root / 'supplements/latest.json', pointer)
    product = dict(data_date='20261120', source_generation=GENERATION,
        source_identity=dict(input_sha256=INPUT, selector_artifact_sha256=SELECTOR, basis=BASIS),
        manifest=NUMERIC)
    return day_root.parent, product, formula_ref


def test_legacy_exact_score_replay_remains_readable_when_base_index_has_rules(tmp_path):
    root, product, formula_ref = build_supplement(tmp_path, pin_rules=False)

    value = load(root, SOURCE_DATE, product, formula_ref, OBSERVATION_DATE)

    assert value['score_action']['status'] == 'READY'
    assert value['score_action']['receipt']['sha256']


def test_new_exact_score_replay_pins_its_rules_and_price_basis(tmp_path):
    root, product, formula_ref = build_supplement(tmp_path, pin_rules=True)

    value = load(root, SOURCE_DATE, product, formula_ref, OBSERVATION_DATE)

    assert value['score_action']['status'] == 'READY'


def test_score_replay_with_rule_drift_is_rejected(tmp_path):
    root, product, formula_ref = build_supplement(tmp_path, pin_rules=True, corrupt_rules=True)

    with pytest.raises(ValueError, match='WORKBENCH_FORMULA_SUPPLEMENT_SCORE_INDEX_CONFLICT'):
        load(root, SOURCE_DATE, product, formula_ref, OBSERVATION_DATE)


def test_legacy_complete_with_twenty_observed_and_two_failed_is_read_as_partial(tmp_path):
    symbols = [f'{number:06d}.SZ' for number in range(100, 122)]
    observed, failed = symbols[:20], symbols[20:]
    root, product, formula_ref = build_supplement(tmp_path, symbols=symbols,
        f10_outcomes=(observed, failed, []))

    value = load(root, SOURCE_DATE, product, formula_ref, OBSERVATION_DATE)

    assert value['supplement_status'] == 'PARTIAL'
    assert value['f10_coverage'] == dict(status='PARTIAL', observed=20, failed=2,
        remaining=0, receipt_sha256=value['f10_coverage']['receipt_sha256'],
        schema=value['f10_coverage']['schema'], source_date=SOURCE_DATE,
        observation_date=OBSERVATION_DATE, generation=GENERATION, input_sha256=INPUT,
        numeric_manifest_sha256=NUMERIC['sha256'],
        roster_symbols_sha256=value['f10_coverage']['roster_symbols_sha256'], roster_count=22,
        **FLAGS)


def test_persisted_partial_f10_coverage_is_recomputed_for_exact_roster_without_owner_counts_or_paths(tmp_path):
    symbols = [f'{number:06d}.SZ' for number in range(100, 122)]
    root, product, formula_ref = build_supplement(tmp_path, symbols=symbols,
        f10_outcomes=(symbols[:20], symbols[20:], []), supplement_status='PARTIAL',
        f10_raw_counts=dict(requested=999, observed=0, scope_count=1, priority_count=1))

    value = load(root, SOURCE_DATE, product, formula_ref, OBSERVATION_DATE)

    coverage = value['f10_coverage']
    assert value['supplement_status'] == 'PARTIAL'
    assert coverage['status'] == 'PARTIAL'
    assert (coverage['observed'], coverage['failed'], coverage['remaining']) == (20, 2, 0)
    assert coverage['source_date'] == SOURCE_DATE
    assert coverage['observation_date'] == OBSERVATION_DATE
    assert coverage['generation'] == GENERATION
    assert coverage['input_sha256'] == INPUT
    assert coverage['numeric_manifest_sha256'] == NUMERIC['sha256']
    assert coverage['roster_count'] == 22
    assert coverage['roster_symbols_sha256'] == _canonical_sha(symbols)
    assert not any('path' in key.lower() for key in coverage)


def test_missing_f10_receipt_is_cannot_confirm_with_explicit_counts(tmp_path):
    root, product, formula_ref = build_supplement(tmp_path)

    value = load(root, SOURCE_DATE, product, formula_ref, OBSERVATION_DATE)

    coverage = value['f10_coverage']
    assert coverage['status'] == 'CANNOT_CONFIRM'
    assert (coverage['observed'], coverage['failed'], coverage['remaining']) == (0, 0, 1)
    assert coverage['receipt_sha256'] is None
    assert not any('path' in key.lower() for key in coverage)


def test_exact_roster_without_supplement_pointer_is_cannot_confirm(tmp_path):
    root, product, formula_ref = build_supplement(tmp_path)
    (root / SOURCE_DATE / 'supplements/latest.json').unlink()

    value = load(root, SOURCE_DATE, product, formula_ref, OBSERVATION_DATE)

    assert value['f10_coverage']['status'] == 'CANNOT_CONFIRM'
    assert (value['f10_coverage']['observed'], value['f10_coverage']['failed'],
            value['f10_coverage']['remaining']) == (0, 0, 1)
    assert value['f10_coverage']['roster_symbols_sha256'] == _canonical_sha([SYMBOL])


def test_empty_exact_roster_without_supplement_pointer_remains_complete(tmp_path):
    root, product, formula_ref = build_supplement(tmp_path, symbols=[])
    (root / SOURCE_DATE / 'supplements/latest.json').unlink()

    value = load(root, SOURCE_DATE, product, formula_ref, OBSERVATION_DATE)

    assert value['f10_coverage']['status'] == 'COMPLETE'
    assert (value['f10_coverage']['observed'], value['f10_coverage']['failed'],
            value['f10_coverage']['remaining']) == (0, 0, 0)


def test_complete_f10_coverage_requires_every_roster_symbol_observed(tmp_path):
    root, product, formula_ref = build_supplement(tmp_path,
        f10_outcomes=([SYMBOL], [], []),
        d35c_items={SYMBOL:dict(status='READY', unresolved_conditions=0)})

    value = load(root, SOURCE_DATE, product, formula_ref, OBSERVATION_DATE)

    assert value['supplement_status'] == 'COMPLETE'
    assert value['f10_coverage']['status'] == 'COMPLETE'


@pytest.mark.parametrize('invalid', ['missing', 'sha_mismatch', 'wrong_symbol', 'failed_status',
        'corrupt_json', 'non_object', 'unsafe_flags', 'historical_pit', 'outside_root'])
def test_complete_f10_readback_counts_invalid_claimed_row_as_failed(tmp_path, invalid):
    root, product, formula_ref = build_supplement(tmp_path,
        f10_outcomes=([SYMBOL], [], []),
        d35c_items={SYMBOL:dict(status='READY', unresolved_conditions=0)},
        invalid_f10={SYMBOL:invalid})

    value = load(root, SOURCE_DATE, product, formula_ref, OBSERVATION_DATE)

    assert value['f10_coverage']['status'] == 'PARTIAL'
    assert value['f10_coverage']['observed'] == 0
    assert value['f10_coverage']['failed'] == 1
    assert value['f10_coverage']['remaining'] == 0
    assert value['supplement_status'] == 'PARTIAL'
    assert not any('path' in key.lower() for key in value['f10_coverage'])


def test_twenty_valid_and_two_invalid_f10_rows_downgrade_legacy_complete(tmp_path):
    symbols = [f'{number:06d}.SZ' for number in range(100, 122)]
    invalid_f10 = {symbols[-2]:'missing', symbols[-1]:'sha_mismatch'}
    ready_items = {symbol:dict(status='READY', unresolved_conditions=0) for symbol in symbols}
    root, product, formula_ref = build_supplement(tmp_path, symbols=symbols,
        f10_outcomes=(symbols, [], []), d35c_items=ready_items, invalid_f10=invalid_f10)

    value = load(root, SOURCE_DATE, product, formula_ref, OBSERVATION_DATE)

    assert value['f10_coverage']['status'] == 'PARTIAL'
    assert value['f10_coverage']['observed'] == 20
    assert value['f10_coverage']['failed'] == 2
    assert value['f10_coverage']['remaining'] == 0
    assert value['supplement_status'] == 'PARTIAL'


def test_f10_readback_skips_unreadable_checkpoint_shards_outside_roster(tmp_path):
    root, product, formula_ref = build_supplement(tmp_path,
        f10_outcomes=([SYMBOL], [], []),
        d35c_items={SYMBOL:dict(status='READY', unresolved_conditions=0)},
        include_unreadable_non_roster=True)

    value = load(root, SOURCE_DATE, product, formula_ref, OBSERVATION_DATE)

    assert value['f10_coverage']['status'] == 'COMPLETE'
    assert value['f10_coverage']['observed'] == 1
    assert value['f10_coverage']['failed'] == 0
    assert value['supplement_status'] == 'COMPLETE'


def test_all_observed_f10_does_not_hide_legacy_unresolved_d35c(tmp_path):
    root, product, formula_ref = build_supplement(tmp_path,
        f10_outcomes=([SYMBOL], [], []),
        d35c_items={SYMBOL:dict(status='READY', unresolved_conditions=1,
            marks=[dict(id=1, trade_date='20261120')],
            lines={'白线':[dict(trade_date='20261120', y='1')],
                   '黄线':[dict(trade_date='20261120', y='2')]})})

    value = load(root, SOURCE_DATE, product, formula_ref, OBSERVATION_DATE)

    assert value['f10_coverage']['status'] == 'COMPLETE'
    assert value['supplement_status'] == 'PARTIAL'
    assert value['d35c_marks']['sha256']


def test_nonempty_complete_without_d35c_binding_is_effectively_partial(tmp_path):
    root, product, formula_ref = build_supplement(tmp_path,
        f10_outcomes=([SYMBOL], [], []))

    value = load(root, SOURCE_DATE, product, formula_ref, OBSERVATION_DATE)

    assert value['f10_coverage']['status'] == 'COMPLETE'
    assert value['supplement_status'] == 'PARTIAL'


def test_empty_exact_roster_remains_vacuously_complete_without_f10_receipt(tmp_path):
    root, product, formula_ref = build_supplement(tmp_path, symbols=[])

    value = load(root, SOURCE_DATE, product, formula_ref, OBSERVATION_DATE)

    assert value['supplement_status'] == 'COMPLETE'
    assert value['f10_coverage']['status'] == 'COMPLETE'
    assert (value['f10_coverage']['observed'], value['f10_coverage']['failed'],
            value['f10_coverage']['remaining']) == (0, 0, 0)
    assert value['f10_coverage']['receipt_sha256'] is None


def test_pinned_score_rule_map_matches_active_main_source_and_contract_bytes():
    assert _canonical_sha(PINNED_SCORE_RULES_SHA256) == PINNED_SCORE_RULES_MAP_SHA256
    root = Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/v4-audit-repairs-20261120-main-r1/app')
    actual = {}
    for name in PINNED_SCORE_RULES_SHA256:
        path = (root / 'contracts' / name) if name.endswith('.json') else (root / 'ops' / name)
        actual[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    assert actual == PINNED_SCORE_RULES_SHA256
