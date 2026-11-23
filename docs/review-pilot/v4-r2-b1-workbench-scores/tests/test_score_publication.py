"""Exercise both deployed role overlays using only isolated artifact fixtures."""
from collections import Counter
from hashlib import sha256
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

import infrastructure
import ops

B1 = Path(__file__).resolve().parents[1]
infrastructure.__path__.insert(0, str(B1 / 'api-overlay' / 'infrastructure'))
ops.__path__ = [str(B1.parent / 'v4-main-daily-capacity-path-a' / 'app-overlay' / 'ops'), *ops.__path__]

from infrastructure import research_workbench_formula_group_supplement as reader
from infrastructure.research_workbench_score_action import (
    PINNED_SCORE_CALCULATION_SHA256, SCORE_CALCULATION_MODULE, read_score_action)
from ops import materialize_workbench_score_action as writer
from ops import research_panel_daily_product as product_owner
from ops import sync_stock_history_completion as publisher


FLAGS = reader.FLAGS
DAY = '2026-11-23'
OBSERVATION = '2026-11-24'
WRITER = 'materialize_workbench_score_action.py'
SYMBOLS = ['000001.SZ', '600000.SH']


def save(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    blob = writer.canonical(payload) + b'\n'
    path.write_bytes(blob)
    return {'path': str(path), 'sha256': sha256(blob).hexdigest()}


def load(path_or_ref):
    path = Path(path_or_ref['path']) if isinstance(path_or_ref, dict) else path_or_ref
    return json.loads(path.read_bytes())


def make_product(tmp_path):
    manifest = save(tmp_path / 'manifest.json', {'scope': 'test'})
    identity = dict(data_date='20261123', source_generation='generation',
                    input_sha256='input', numeric_manifest=manifest)
    basis = dict(price_basis='QFQ_ASOF', volume_basis='SAME_VOLUME')
    product = dict(source_generation='generation', manifest=manifest,
                   source_identity=dict(basis=basis, input_sha256='input',
                                        selector_artifact_sha256='selector'))
    return identity, product


def rules_metadata(encoding):
    rules = dict(reader.PINNED_SCORE_RULES_SHA256)
    if encoding in {'new', 'bad_calculation'}:
        rules.pop(WRITER)
        rules[SCORE_CALCULATION_MODULE] = (PINNED_SCORE_CALCULATION_SHA256
                                           if encoding == 'new' else '9' * 64)
        return {'rules': rules, 'writer_provenance': dict(module=WRITER, sha256='a' * 64)}
    if encoding == 'd23':
        rules[WRITER] = '005c8b3ef4723ffc56385d2ad91d5487e3cd3aeb30d56886671f063e39c96b1b'
    if encoding == 'bad_rule':
        rules['kb_hold_score.py'] = '0' * 64
    if encoding == 'bad_legacy_writer':
        rules[WRITER] = 'b' * 64
    return {'rules': rules}


def make_index(root, name, symbols, identity, product, metadata, *, row_writers=None):
    outcomes = Counter()
    refs = {}
    writers = set()
    for symbol in symbols:
        materialized = symbol == SYMBOLS[0]
        status = 'MATERIALIZED' if materialized else 'UNKNOWN'
        hold = dict(kb_hold_score_status='PARTIAL_WITH_UNKNOWN', kb_hold_score=None,
                    kb_hold_score_min=2, kb_hold_score_max=4) if materialized else None
        payload = dict(symbol=symbol, trade_date=identity['data_date'], status=status,
                       hold_score=hold, reason=None if materialized else 'EXACT_TARGET_BAR_UNAVAILABLE',
                       cache_identity=dict(rules=metadata['rules'], price_basis=product['source_identity']['basis']),
                       historical_PIT=False, **FLAGS)
        if metadata.get('writer_provenance'):
            provenance = (row_writers or {}).get(symbol, metadata['writer_provenance'])
            payload['writer_provenance'] = provenance
            writers.add(provenance['sha256'])
        refs[symbol] = save(root / 'records' / (symbol + '.json'), payload)
        outcomes[status.lower()] += 1
    counts = dict(total=len(symbols), materialized=outcomes['materialized'], unknown=outcomes['unknown'])
    value = dict(schema=writer.SCHEMA, **identity, **metadata, source_selector_sha256='selector',
                 price_basis=product['source_identity']['basis'], items=refs, counts=counts,
                 historical_PIT=False, **FLAGS)
    if metadata.get('writer_provenance'):
        value['row_writer_sha256s'] = sorted(writers)
    return dict(index=save(root / 'indexes' / (name + '.json'), value), **identity, counts=counts,
                status='PARTIAL_WITH_UNKNOWN' if counts['unknown'] else 'READY', **FLAGS)


def make_supplement(tmp_path, encoding):
    identity, product = make_product(tmp_path)
    root = tmp_path / 'groups'
    day_root = root / DAY
    formula = save(day_root / 'formula.json', dict(
        schema='V4_WORKBENCH_FORMULA_GROUP_OVERRIDE_V1', source_date=DAY,
        observation_date=OBSERVATION, generation=identity['source_generation'], input_sha256='input',
        numeric_manifest=product['manifest'], selector_sha256='selector',
        rows=[dict(symbol=symbol) for symbol in SYMBOLS]))
    shared = dict(source_date=DAY, observation_date=OBSERVATION, generation='generation',
                  input_sha256='input', numeric_manifest=product['manifest'], selector_sha256='selector',
                  formula_group_sha256=formula['sha256'], roster_symbols_sha256=reader._canonical_sha(SYMBOLS),
                  roster_count=len(SYMBOLS))
    marks = save(day_root / 'marks.json', dict(
        schema='V4_WORKBENCH_ORIGINAL_D35C_MARKS_V1', **shared, price_basis='QFQ_ASOF_20261123',
        volume_basis='SAME_VOLUME', items={s: {'status': 'READY', 'unresolved_conditions': 0}
                                          for s in SYMBOLS}, historical_PIT=False, **FLAGS))
    metadata = rules_metadata(encoding)
    score_root = tmp_path / 'scores'
    descriptor = make_index(score_root, 'supplement', SYMBOLS, identity, product, metadata)
    replay = dict(schema='V4_FORMULA_GROUP_SCORE_ACTION_REPLAY_V1', status='PREPARED_EXACT_OWNER_REPLAY',
                  same_rule_sha=True, descriptor=descriptor, statuses={s: {} for s in SYMBOLS},
                  source_date=DAY, source_generation='generation', input_sha256='input',
                  numeric_manifest=product['manifest'], formula_group_sha256=formula['sha256'],
                  score_rules=metadata['rules'], score_rule_map_sha256=reader._canonical_sha(metadata['rules']),
                  price_basis=product['source_identity']['basis'], **FLAGS)
    if metadata.get('writer_provenance'):
        replay['writer_provenance'] = metadata['writer_provenance']
    score = save(day_root / 'score.json', replay)
    artifact = save(day_root / 'artifact.json', dict(
        schema='V4_WORKBENCH_FORMULA_GROUP_SUPPLEMENT_V1', status='PARTIAL', **shared,
        d35c_marks=marks, d35c_status='READY',
        score_action=dict(receipt=score, descriptor=descriptor, artifact_root=str(score_root)), **FLAGS))
    receipt = save(day_root / 'receipt.json', dict(
        schema='V4_WORKBENCH_FORMULA_GROUP_SUPPLEMENT_RECEIPT_V1', status='COMMITTED',
        artifact=artifact, **shared, **FLAGS))
    pointer = save(day_root / 'supplements/latest.json', dict(
        schema='V4_WORKBENCH_FORMULA_GROUP_SUPPLEMENT_COMMIT_V1', module='formula_group_supplement',
        status='PARTIAL', artifact=artifact, receipt=receipt, **shared, **FLAGS))
    return (root, DAY, product, formula, OBSERVATION), score_root, descriptor, marks, score, pointer


@pytest.mark.parametrize('encoding', ['legacy', 'd23', 'new'])
def test_reader_accepts_pin_compatible_formats_and_preserves_ranges(tmp_path, encoding):
    args, score_root, descriptor, marks, score, _ = make_supplement(tmp_path, encoding)
    value = reader.load(*args)
    assert value['d35c_marks'] == marks and value['score_action']['receipt'] == score
    exact = read_score_action(score_root, descriptor, args[2], DAY, SYMBOLS[0])
    assert exact['status'] == 'MATERIALIZED'
    assert exact['row']['hold_score']['kb_hold_score'] is None
    assert exact['row']['hold_score']['kb_hold_score_max'] == 4
    unknown = read_score_action(score_root, descriptor, args[2], DAY, SYMBOLS[1])
    assert unknown['status'] == 'UNKNOWN' and unknown['row'] is not None


@pytest.mark.parametrize('encoding', ['bad_rule', 'bad_legacy_writer', 'bad_calculation'])
def test_bad_score_rule_keeps_chart_and_f10_available(tmp_path, encoding):
    args, _, _, marks, _, _ = make_supplement(tmp_path, encoding)
    value = reader.load(*args)
    assert 'score_action' not in value
    assert value['score_error'] == 'WORKBENCH_FORMULA_SCORE_BINDING_INVALID'
    assert value['d35c_marks'] == marks and value['f10_coverage']['roster_count'] == 2
    assert reader.load(*args, features=('d35c_marks',))['d35c_marks'] == marks


def test_changed_sidecar_bytes_are_rejected_only_for_that_sidecar(tmp_path):
    args, _, _, marks, score, _ = make_supplement(tmp_path, 'd23')
    Path(marks['path']).write_text('{}')
    value = reader.load(*args)
    assert value['d35c_error'] and value['score_action']['receipt'] == score
    args, _, _, marks, score, _ = make_supplement(tmp_path, 'd23')
    Path(score['path']).write_text('{}')
    value = reader.load(*args)
    assert value['score_error'] and value['d35c_marks'] == marks


def make_union_fixture(tmp_path, monkeypatch, encoding='d23', newer_encoding=None):
    identity, product = make_product(tmp_path)
    metadata = rules_metadata(encoding)
    monkeypatch.setattr(writer, 'authority_identity',
                        lambda: {k: v for k, v in metadata['rules'].items() if k != WRITER}
                        | {SCORE_CALCULATION_MODULE: PINNED_SCORE_CALCULATION_SHA256})
    root = tmp_path / 'product'
    base = make_index(root / 'score_action', 'base', SYMBOLS[:1], identity, product, metadata)
    incoming = rules_metadata(newer_encoding) if newer_encoding else metadata
    row_writers = None
    if encoding == 'new' == newer_encoding:
        incoming['writer_provenance'] = dict(module=WRITER, sha256='b' * 64)
        row_writers = {SYMBOLS[0]: metadata['writer_provenance']}
    addition = make_index(root / 'score_action', 'supplement', SYMBOLS, identity, product,
                          incoming, row_writers=row_writers)
    index = save(root / 'index.json', dict(dates={identity['data_date']: identity['numeric_manifest']},
        latest_date=identity['data_date'], score_action={identity['data_date']: base}, review='preserved'))
    event = save(root / 'events/latest.json', dict(data_date=identity['data_date'], event_id='preimage',
        manifest=identity['numeric_manifest'], score_action=base, f10='preserved',
        source_generation=identity['source_generation'], input_sha256=identity['input_sha256']))
    lock = tmp_path / 'owner.lock'
    lock.touch()
    monkeypatch.setattr(publisher, 'DEFAULT_OWNER_LOCK', lock)
    monkeypatch.setattr(publisher, '_inherited_owner_duplicate', lambda binding, day: None)
    context = SimpleNamespace(root=root, target=identity['data_date'], generation=identity['source_generation'],
                              identity=product['source_identity'], unchanged=lambda: None)
    return context, base, addition, index, event


def test_actual_cas_publisher_merges_without_rewriting_rows(tmp_path, monkeypatch):
    context, base, addition, index, event = make_union_fixture(tmp_path, monkeypatch)
    days = load(index)['dates']
    result = writer.publish_formula_score_union(context, addition, tmp_path / 'stage')
    descriptor = result['descriptor']
    assert result['status'] == 'PUBLISHED_SCORE_UNION'
    assert descriptor['counts'] == {'total': 2, 'materialized': 1, 'unknown': 1}
    assert load(index)['score_action']['20261123'] == load(event)['score_action'] == descriptor
    assert load(index)['dates'] == days and load(index)['review'] == load(event)['f10'] == 'preserved'
    assert load(descriptor['index'])['items'][SYMBOLS[0]] == load(base['index'])['items'][SYMBOLS[0]]
    assert load(descriptor['index'])['items'] == load(addition['index'])['items']
    again = writer.publish_formula_score_union(context, addition, tmp_path / 'stage')
    assert again['status'] == 'ALREADY_PUBLISHED_SCORE_UNION'


def test_main_cas_rejects_moved_index_and_preserves_event(tmp_path, monkeypatch):
    context, _, addition, index, event = make_union_fixture(tmp_path, monkeypatch)
    actual_publish = publisher.publish
    pre_event = Path(event['path']).read_bytes()
    moved_index = dict(load(index), review='moved')

    def race(plan):
        save(Path(index['path']), moved_index)
        return actual_publish(plan)

    monkeypatch.setattr(publisher, 'publish', race)
    with pytest.raises(ValueError):
        writer.publish_formula_score_union(context, addition, tmp_path / 'stage')
    assert load(index) == moved_index and Path(event['path']).read_bytes() == pre_event


def test_main_cas_restores_exact_index_if_event_replacement_fails(tmp_path, monkeypatch):
    context, _, addition, index, event = make_union_fixture(tmp_path, monkeypatch)
    pre_index = Path(index['path']).read_bytes()
    pre_event = Path(event['path']).read_bytes()
    replace = os.replace

    def fail_event(source, target):
        if Path(target) == Path(event['path']):
            raise OSError('synthetic event failure')
        return replace(source, target)

    monkeypatch.setattr(os, 'replace', fail_event)
    with pytest.raises(OSError, match='synthetic event failure'):
        writer.publish_formula_score_union(context, addition, tmp_path / 'stage')
    assert Path(index['path']).read_bytes() == pre_index
    assert Path(event['path']).read_bytes() == pre_event


def test_pinned_calculation_is_the_exact_extracted_source():
    assert writer.sha(writer.calculation.__file__) == PINNED_SCORE_CALCULATION_SHA256
    assert writer.LEGACY_EQUIVALENT_CALCULATION_SHA256 == PINNED_SCORE_CALCULATION_SHA256


def test_writer_provenance_is_preserved_without_changing_semantic_cache(tmp_path, monkeypatch):
    calls = []

    def fixture(symbol, rows, target, basis, rules, qualification, identity, prior_records, legacy_rules):
        calls.append(rules)
        return dict(symbol=symbol, trade_date=target, cache_identity=identity, status='UNKNOWN', **FLAGS)

    monkeypatch.setattr(writer.calculation, 'calculate_score', fixture)
    metadata = rules_metadata('new')
    rules = metadata['rules']
    old = metadata['writer_provenance']
    new = dict(module=WRITER, sha256='b' * 64)
    inputs = (SYMBOLS[0], [], '20261123', {}, str(tmp_path))
    initial = writer.project_symbol((*inputs, rules, old, {}))
    refs_before = {p: p.read_bytes() for p in tmp_path.rglob('*.json')}
    continued = writer.project_symbol((*inputs, rules, new, {}))
    assert continued['reused'] and continued['record'] == initial['record']
    assert continued['record']['writer_provenance'] == old and len(calls) == 1
    assert {p: p.read_bytes() for p in tmp_path.rglob('*.json')} == refs_before
    changed = dict(rules, **{SCORE_CALCULATION_MODULE: '9' * 64})
    recomputed = writer.project_symbol((*inputs, changed, new, {}))
    assert not recomputed['reused'] and len(calls) == 2
    assert recomputed['record']['writer_provenance'] == new
    assert writer.legacy_rule_maps(changed) == ()


def test_new_score_union_retains_different_immutable_writer_provenance(tmp_path, monkeypatch):
    context, base, addition, index, _ = make_union_fixture(tmp_path, monkeypatch, 'new', 'new')
    result = writer.publish_formula_score_union(context, addition, tmp_path / 'stage')
    assert result['status'] == 'PUBLISHED_SCORE_UNION'
    merged = load(result['descriptor']['index'])
    assert merged['row_writer_sha256s'] == ['a' * 64, 'b' * 64]
    assert merged['items'][SYMBOLS[0]] == load(base['index'])['items'][SYMBOLS[0]]
    assert merged['items'][SYMBOLS[1]] == load(addition['index'])['items'][SYMBOLS[1]]
    assert load(index)['score_action']['20261123'] == result['descriptor']


def test_mixed_encoding_leaves_current_score_descriptor_unchanged(tmp_path, monkeypatch):
    context, _, addition, index, event = make_union_fixture(tmp_path, monkeypatch, 'd23', 'new')
    pre_index = Path(index['path']).read_bytes()
    pre_event = Path(event['path']).read_bytes()
    with pytest.raises(ValueError, match='SCORE_UNION_ROW_ENCODING_CONFLICT'):
        writer.publish_formula_score_union(context, addition, tmp_path / 'stage')
    assert Path(index['path']).read_bytes() == pre_index
    assert Path(event['path']).read_bytes() == pre_event


def test_reader_rejects_changed_new_calculation_even_without_supplement_loader(tmp_path):
    args, score_root, descriptor, _, _, _ = make_supplement(tmp_path, 'bad_calculation')
    with pytest.raises(ValueError, match='SCORE_CALCULATION_PIN_CONFLICT'):
        read_score_action(score_root, descriptor, args[2], DAY, SYMBOLS[0])
