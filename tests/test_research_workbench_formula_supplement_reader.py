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


def build_supplement(root, *, pin_rules=True, corrupt_rules=False):
    day_root = root / SOURCE_DATE
    score_root = root / 'score-action'
    formula = dict(schema='V4_WORKBENCH_FORMULA_GROUP_OVERRIDE_V1', source_date=SOURCE_DATE,
        observation_date=OBSERVATION_DATE, generation=GENERATION, input_sha256=INPUT,
        numeric_manifest=NUMERIC, selector_sha256=SELECTOR,
        rows=[dict(symbol=SYMBOL)], **FLAGS)
    formula_ref = write_ref(day_root / 'formula/artifact.json', formula)
    roster_sha = hashlib.sha256(json.dumps([SYMBOL], ensure_ascii=False, sort_keys=True,
        separators=(',', ':')).encode()).hexdigest()
    identity = dict(source_date=SOURCE_DATE, observation_date=OBSERVATION_DATE,
        generation=GENERATION, input_sha256=INPUT, numeric_manifest=NUMERIC,
        selector_sha256=SELECTOR, formula_group_sha256=formula_ref['sha256'],
        roster_symbols_sha256=roster_sha, roster_count=1)
    index_rules = dict(RULES, kb_action='3' * 64) if corrupt_rules else RULES
    index = dict(items={SYMBOL:dict(path='/score/row.json',sha256='4'*64)},
        numeric_manifest=NUMERIC, source_generation=GENERATION, input_sha256=INPUT,
        source_selector_sha256=SELECTOR, rules=index_rules, price_basis=BASIS, **FLAGS)
    index_ref = write_ref(score_root / 'indexes/index.json', index)
    descriptor = dict(status='READY', data_date='20261120', source_generation=GENERATION,
        input_sha256=INPUT, numeric_manifest=NUMERIC, counts=dict(total=1), index=index_ref, **FLAGS)
    replay = dict(schema='V4_FORMULA_GROUP_SCORE_ACTION_REPLAY_V1',
        status='PREPARED_EXACT_OWNER_REPLAY', same_rule_sha=True, source_date=SOURCE_DATE,
        source_generation=GENERATION, input_sha256=INPUT, numeric_manifest=NUMERIC,
        formula_group_sha256=formula_ref['sha256'], descriptor=descriptor,
        statuses={SYMBOL:dict(record_status='MATERIALIZED',score_status='READY',score=4)}, **FLAGS)
    if pin_rules:
        replay['score_rules'] = RULES
        replay['price_basis'] = BASIS
        replay['score_rule_map_sha256'] = PINNED_SCORE_RULES_MAP_SHA256
    replay_ref = write_ref(day_root / 'supplements/receipts/score-replay.json', replay)
    score_binding = dict(status='READY', receipt=replay_ref, artifact_root=str(score_root.resolve()),
        descriptor=descriptor)
    artifact = dict(schema='V4_WORKBENCH_FORMULA_GROUP_SUPPLEMENT_V1', status='COMPLETE',
        **identity, score_action=score_binding, **FLAGS)
    artifact_ref = write_ref(day_root / 'supplements/artifacts/supplement.json', artifact)
    receipt = dict(schema='V4_WORKBENCH_FORMULA_GROUP_SUPPLEMENT_RECEIPT_V1', status='COMMITTED',
        artifact=artifact_ref, **identity, **FLAGS)
    receipt_ref = write_ref(day_root / 'supplements/receipts/supplement-receipt.json', receipt)
    pointer = dict(schema='V4_WORKBENCH_FORMULA_GROUP_SUPPLEMENT_COMMIT_V1',
        module='formula_group_supplement', status='COMPLETE', **identity,
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


def test_pinned_score_rule_map_matches_active_main_source_and_contract_bytes():
    assert _canonical_sha(PINNED_SCORE_RULES_SHA256) == PINNED_SCORE_RULES_MAP_SHA256
    root = Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/v4-audit-repairs-20261120-main-r1/app')
    actual = {}
    for name in PINNED_SCORE_RULES_SHA256:
        path = (root / 'contracts' / name) if name.endswith('.json') else (root / 'ops' / name)
        actual[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    assert actual == PINNED_SCORE_RULES_SHA256
