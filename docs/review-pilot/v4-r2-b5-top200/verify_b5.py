"""Verify the B5 overlays against the frozen Main/API and their bound D23 data."""
import argparse
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import sys
from types import SimpleNamespace
from unittest.mock import patch
from urllib.request import urlopen


BATCH = Path(__file__).resolve().parent
REPO = BATCH.parents[2]
DATE = '2026-11-23'
DAY = DATE.replace('-', '')
WORKBENCH = '/api/v4/research/workbench/days/' + DATE
FLAGS = dict(RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)


def overlay(module_name, path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def check_preimage(active, relative_path, sha):
    assert hashlib.sha256((active / relative_path).read_bytes()).hexdigest() == sha, relative_path


def verify_main(active, environment):
    path = 'ops/research_panel_top200.py'
    check_preimage(active, path, 'eb4bebabac454d18cb39d00935315bdd8b79b1883b20c0378e99253fca5e56c9')
    top = overlay('ops.research_panel_top200', REPO / path)
    root = Path(environment['V4_A_SHARE_DAILY_PRODUCT_ROOT']) / 'daily_products/a_share'
    store = Path(environment['V4_WORKBENCH_CLASSIFICATION_ROOT'])
    index_path = root / 'index.json'
    index = json.loads(index_path.read_bytes())
    reference = index['top200'][DAY]
    original = top.load(reference)
    quotes, _ = top.official_quotes(original['official_input'], int(DAY))
    excluded = top._known_no_current_bar(int(DAY))
    top._set_rank_eligibility(original['coverage'], quotes, excluded)
    for row in original['coverage']:
        assert (row['daily_gain_rank_eligibility'] is True) == ('rank' in row)
        assert row['historical_pit_eligibility'] == 'CANNOT_CONFIRM'
        if row['symbol'] in excluded:
            assert row['daily_gain_rank_eligibility'] is False
        elif row['symbol'] not in quotes:
            assert row['daily_gain_rank_eligibility'] is None
    outcomes = {row['daily_gain_rank_eligibility'] for row in original['coverage']}
    assert outcomes == {True, False, None}
    product = top.load(top.load(original['numeric_manifest'])['artifact'])
    context = SimpleNamespace(target=int(DAY), generation=original['source_generation'], identity=product['source_identity'])
    reused, info = top.build(context, root, original['official_input'], store)
    assert info['reused'] and info['reference'] == reference and reused == top.load(reference)
    print('PASS_MAIN_D23_OFFICIAL_RANK_PARITY_AND_IMMUTABLE_REUSE', reference['sha256'])

    # Exercise the D30 exact-metadata branch with only the existing Top200
    # reference omitted from the in-memory index. All source bytes stay pinned.
    exact_date = '20261030'
    exact = top.load(index['top200'].pop(exact_date))
    exact_product = top.load(top.load(exact['numeric_manifest'])['artifact'])
    exact_context = SimpleNamespace(target=int(exact_date), generation=exact['source_generation'],
                                    identity=exact_product['source_identity'], unchanged=lambda: None)
    read_bytes = Path.read_bytes

    def read_without_existing(path):
        return json.dumps(index).encode() if path == index_path else read_bytes(path)

    with patch.object(Path, 'read_bytes', read_without_existing):
        assembled, result = top.build(exact_context, root, exact['official_input'], store)
    assert result['reused'] is False and result['computed_structures'] == 0
    assert assembled['historical_PIT'] is False and assembled['historical_pit_eligibility'] == 'CANNOT_CONFIRM'
    for new, old in zip(assembled['top200'], exact['top200'], strict=True):
        assert new == {**old, 'daily_gain_rank_eligibility': True, 'historical_pit_eligibility': 'CANNOT_CONFIRM'}
    print('PASS_MAIN_D30_EXACT_METADATA_ASSEMBLY')


def verify_api(active, environment, before_url):
    host_path = 'infrastructure/research_workbench_host.py'
    classification_path = 'infrastructure/research_classification_view.py'
    check_preimage(active, host_path, '167cf79aac24ffb297487e8a062f4f4ab426f7e5efb5f3e2d4443498f5878742')
    check_preimage(active, classification_path, '7804b682a0d9dd4ec5d8a62bda429d68ffc876655449dc781bea5092ab48b88e')
    host = overlay('infrastructure.research_workbench_host', BATCH / 'api-overlay' / host_path)
    classification = overlay('infrastructure.research_classification_view', REPO / classification_path)
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from infrastructure.research_lane_source import ResearchLaneSource

    for key in ('V4_WORKBENCH_HOST_BINDING', 'V4_WORKBENCH_HOST_BINDING_SHA256',
                'V4_WORKBENCH_V192_SHARED_ROOT', 'V4_WORKBENCH_V192_SHARED_PACKAGE_ROOT',
                'V4_WORKBENCH_V192_READER_SHA256'):
        os.environ[key] = environment[key]
    source = ResearchLaneSource(
        Path(environment['V4_RESEARCH_DATA_ROOT']),
        a_share_daily_root=Path(environment['V4_A_SHARE_DAILY_PRODUCT_ROOT']),
        original_chart_artifact_root=Path(environment['V4_ORIGINAL_CHART_ARTIFACT_ROOT']),
    )
    app = FastAPI()
    app.include_router(host.create_workbench_router(source), prefix='/api/v4/research')
    aliases = {'300010.SZ': ('豆神教育', 'ST豆神'), '600678.SH': ('四川金顶', 'ST金顶')}
    with TestClient(app) as client:
        def get(path):
            response = client.get(WORKBENCH + path)
            assert response.status_code == 200, response.text
            return response.json()

        day = get('')
        by_symbol = {row['symbol']: row for row in day['rows']}
        assert day['scope_count'] == 104 == len(by_symbol)
        assert day['classification_identity_counts'] == {
            'BOUND_EXACT_CODE_NAME': 102, 'BOUND_SAME_ENTITY_ST_NAME': 2,
        }
        for symbol, names in aliases.items():
            row = by_symbol[symbol]
            item = row['classification']
            assert row['eligible_candidate'] is True and item['classification']['symbol'] == symbol
            assert (item['current_name'], item['received_name']) == names
            assert item['identity_evidence']['url'].startswith('https://')

        top = get('/top200')
        assert top['historical_PIT'] is False and top['status'] == 'PARTIAL_DESCRIPTIVE'
        assert top['historical_pit_eligibility'] == 'CANNOT_CONFIRM'
        archive = host.checked(top['artifact'])
        assert len(top['top200']) == archive['top200_count'] == 200
        for new, old in zip(top['top200'], archive['top200'], strict=True):
            assert new == {**old, 'daily_gain_rank_eligibility': True, 'historical_pit_eligibility': 'CANNOT_CONFIRM'}

        stock_path = '/single-research/300010.SZ'
        score = get(stock_path)
        assert score['status'] == 'MATERIALIZED'
        if before_url:
            with urlopen(before_url.rstrip('/') + WORKBENCH + stock_path, timeout=10) as response:
                assert json.load(response) == score
            print('PASS_API_B1_SCORE_RESPONSE_PARITY')

        original_join = classification.ReceivedClassificationStore.join
        conflict_symbol = '300010.SZ'

        def join_conflict(store, rows, **kwargs):
            fixture = copy.deepcopy(rows)
            next(row for row in fixture if row['symbol'] == conflict_symbol)['display_name'] = '冲突名称'
            return original_join(store, fixture, **kwargs)

        with patch.object(classification.ReceivedClassificationStore, 'join', join_conflict):
            quarantined = get('')
        conflict = next(row for row in quarantined['rows'] if row['symbol'] == conflict_symbol)
        assert conflict['eligible_candidate'] is False and conflict['classification']['classification'] is None
        assert conflict['classification']['identity_status'] == 'IDENTITY_CONFLICT_NAME'
        assert set(conflict['group_states'].values()) == {'UNKNOWN'} and conflict['history_rates'] == {}
        assert 'groups' not in conflict['source_row'] and 'pending_groups' not in conflict['source_row']
        groups = quarantined['formula_groups']
        assert groups['quarantined_identity_count'] == 1
        assert groups['source_group_counts'] == day['formula_groups']['group_counts']
        for group, count in groups['group_counts'].items():
            assert count == groups['source_group_counts'][group] - (by_symbol[conflict_symbol]['group_states'][group] == 'TRUE')
        for payload in (day, top, score, quarantined):
            assert all(payload[key] is expected for key, expected in FLAGS.items())

        bind_name = classification._name_binding
        for source_record in ({}, {'name': None}, {'name': ''}, {'name': ' '}):
            assert bind_name('A_SHARE', conflict_symbol, '豆神教育', source_record, DATE) == (
                'CANNOT_CONFIRM_RECEIVED_NAME_MISSING', None)

        def bind_missing_received(kind, symbol, display_name, record, source_date):
            if symbol == conflict_symbol:
                record = {**record, 'name': None}
            return bind_name(kind, symbol, display_name, record, source_date)

        with patch.object(classification, '_name_binding', bind_missing_received):
            # A fresh router gives this simulated source its own join cache.
            trial = FastAPI()
            trial.include_router(host.create_workbench_router(source), prefix='/api/v4/research')
            with TestClient(trial) as missing_client:
                response = missing_client.get(WORKBENCH)
                assert response.status_code == 200, response.text
                missing = response.json()
        row = next(row for row in missing['rows'] if row['symbol'] == conflict_symbol)
        assert row['classification']['identity_status'] == 'CANNOT_CONFIRM_RECEIVED_NAME_MISSING'
        assert row['classification']['classification'] is None and row['eligible_candidate'] is True
        assert missing['formula_groups']['group_counts'] == day['formula_groups']['group_counts']

    binding = host.checked(dict(path=environment['V4_WORKBENCH_HOST_BINDING'],
                                sha256=environment['V4_WORKBENCH_HOST_BINDING_SHA256']))
    store = classification.ReceivedClassificationStore(binding['classification_store_root'])
    try:
        rows = [dict(symbol=symbol, display_name=names[0]) for symbol, names in aliases.items()]
        assert store.join(rows, source_date=DATE)['identity_counts'] == {classification.SAME_ENTITY_NAME_STATUS: 2}
        assert store.join(rows, source_date='2026-04-28')['identity_counts'] == {classification.NAME_CONFLICT_STATUS: 2}
        for display_name in (None, '', ' '):
            missing = store.join([dict(symbol='300010.SZ', display_name=display_name)], source_date=DATE)
            assert missing['identity_counts'] == {'CANNOT_CONFIRM_CURRENT_NAME_MISSING': 1}
    finally:
        store.close()
    print('PASS_API_D23_RANK_ALIASES_AND_CONFLICT_QUARANTINE')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('role', choices=('api', 'main'))
    parser.add_argument('--launch-agent', type=Path, required=True)
    parser.add_argument('--before-url')
    args = parser.parse_args()
    with args.launch_agent.open('rb') as stream:
        environment = plistlib.load(stream)['EnvironmentVariables']
    active = Path(environment['V4_APP_ROOT'])
    os.chdir(active)
    sys.path.insert(0, str(active))
    sys.path[1:1] = [path for path in environment.get('PYTHONPATH', '').split(os.pathsep) if path]
    if args.role == 'api':
        verify_api(active, environment, args.before_url)
    else:
        verify_main(active, environment)


if __name__ == '__main__':
    main()
