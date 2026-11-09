"""Exact-scope received projection and the existing owner's real CAS/lock path."""
import copy
import csv
import importlib.util
import json
import os
from pathlib import Path

import pytest

MODULE = Path(__file__).resolve().parents[1] / 'ops/import_received_company_materials.py'
spec = importlib.util.spec_from_file_location('received_company_materials', MODULE)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def write_csv(path, rows):
    with path.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return m.ref(path)


@pytest.fixture
def batch(tmp_path):
    root, stage = tmp_path / 'product', tmp_path / 'stage'
    root.mkdir()
    codes = ['300149.SZ', '300856.SZ', '688111.SH']
    date, target, generation, input_sha = '20261104', '20261105', 'a' * 64, 'b' * 64
    lock = tmp_path / 'A_LONG.lock'
    lock.touch()
    owner = tmp_path / 'owner.py'
    owner.write_text('from received_company_materials import save as atomic_save\n'
                     'def save(path, value, immutable=False):\n'
                     '    return atomic_save(path, value)\n')
    # The unchanged existing adapter is a read-only dependency, explicitly pinned.
    adapter = Path(os.environ.get('V4_EXISTING_PUBLICATION_ADAPTER', str(owner)))
    product = dict(data_date=date, source_generation=generation, source_identity={'input_sha256': input_sha},
                   rows=[dict(symbol=code) for code in codes], **m.FLAGS)
    artifact = m.save(root / 'numeric.json', product)
    numeric = m.save(root / 'manifest.json', dict(data_date=date, source_generation=generation,
                     input_sha256=input_sha, artifact=artifact, **m.FLAGS))
    index = dict(dates={date: numeric, '20261029': {'keep': True}}, latest_date=date, latest=numeric,
                 company_materials={'20261029': {'keep': True}}, display_names={'keep': True},
                 top200={'keep': True}, other_owner={'value': 42})
    event = dict(schema_version='v4.a_share.daily_completion.v1', data_date=date, source_generation=generation,
                 input_sha256=input_sha, manifest=numeric, artifact=artifact, event_id='c' * 64,
                 original_charts={'keep': True}, top200={'keep': True}, status='PARTIAL_WITH_ROWS', **m.FLAGS)
    m.save(root / 'index.json', index)
    m.save(root / 'events/latest.json', event)
    fundamentals, screens, performances = [], [], []
    for i, code in enumerate(codes):
        fundamentals.append(dict(symbol=code, source_date=date, observation_date=target,
            source_generation=generation, input_digest='pack', screened_name=code, as_of='2026-11-04T23:58:08+08:00',
            business='收到的业务原文', profit_driver='营收3.14亿元，不从原文猜数', status='PARTIAL' if i == 1 else 'COMPLETED',
            source_ids=json.dumps(['source-' + code]), missing_inputs='["valuation missing"]', **m.FLAGS))
        screens.append(dict(symbol=code, source_date=date, target_date=target, v4_generation=generation,
            full_chain_status='CANNOT_CONFIRM', errors=['D_CLOSE_MISMATCH_CANONICAL'] if i == 1 else [],
            volume_to_current_MA5=0.88, volume_to_prior_MA5=0.99, p5_key_type='REVERSAL'))
        performances.append(dict(symbol=code, source_date=date, target_date=target, source_generation=generation,
            numeric_manifest_sha256=numeric['sha256'], close=11.2, current_target_day_return_pct=None,
            current_target_day_performance_status='NOT_MATERIALIZED_NOT_READ', **m.FLAGS))
    inputs = dict(fundamentals=write_csv(tmp_path / 'fund.csv', fundamentals),
        sources=write_csv(tmp_path / 'sources.csv', [dict(source_id='source-' + c, symbol=c, url='https://example.org/'+c) for c in codes]),
        claims=write_csv(tmp_path / 'claims.csv', [dict(symbol=c, statement='原文') for c in codes]),
        input_manifest=m.save(tmp_path / 'input.json', dict(source_date=date, target_date=target,
            source_generation=generation, source_input_sha256=input_sha, numeric_manifest_sha256=numeric['sha256'], input_digest='pack')),
        return_manifest=m.save(tmp_path / 'return.json', dict(source_date=date, target_date=target, input_digest='pack', **m.FLAGS)),
        secondary_rows=m.save(tmp_path / 'screen.json', screens),
        secondary_receipt=m.save(tmp_path / 'screen_receipt.json', dict(scope_size=3, strict_full_chain_certified_count=0,
            safety_flags=m.FLAGS, selected_watchlist_by_theme={'医药': {'technical_observe': [codes[0]], 'wait_for_trigger': [codes[1]]}})),
        daily_performance=m.save(tmp_path / 'performance.json', dict(rows=performances, source_date=date, target_date=target,
            source_generation=generation, numeric_manifest_sha256=numeric['sha256'], **m.FLAGS)))
    config = dict(schema='V4_RECEIVED_RESEARCH_IMPORT_V1', product_root=str(root), source_date=date, target_date=target,
        generation=generation, input_sha256=input_sha, numeric_manifest_sha256=numeric['sha256'], scope_count=3,
        owner_publisher=m.ref(owner), publication_adapter=m.ref(adapter), owner_lock=str(lock), inputs=inputs, **m.FLAGS)
    # Let the actual adapter import our fixture owner's atomic save without files
    # outside the frozen allowlist in the repository.
    import sys
    sys.modules['received_company_materials'] = m
    return dict(config=config, root=root, stage=stage, index=index, event=event, codes=codes, tmp=tmp_path)


def v2_batch(batch):
    tmp, codes = batch['tmp'], batch['codes']
    date, target = '20261104', '20261105'
    generation, input_sha, package = 'a' * 64, 'b' * 64, 'V2_TEST_PACKAGE'
    numeric_ref = m.ref(batch['root'] / 'manifest.json')
    numeric = m.load(numeric_ref)
    candidates_ref = write_csv(tmp / 'v2_candidates.csv', [dict(symbol=c, name=c) for c in codes])
    prior_research_ref = write_csv(tmp / 'v2_prior_research.csv', [dict(symbol=codes[1], status='COMPLETED')])
    prior_sources_ref = write_csv(tmp / 'v2_prior_sources.csv', [dict(symbol=codes[1], source_id='prior-source')])
    daily_rows = []
    for code in codes:
        daily_rows.append(dict(symbol=code, ts_code=code, trade_date=date, source_date=date,
            observation_date=target, source_generation=generation, input_sha256=input_sha,
            manifest_sha256=numeric_ref['sha256'], open='10', high='12', low='9', close='11.25',
            pre_close='10.5', pct_chg='7.142857', amount='123000000', volume='5000000',
            turnover_rate_pct='1.25', price_position_all_history_pct='12.5', price_position_all_history_n='800',
            price_position_250_pct='20', price_position_250_n='250', vol_ratio_60='1.2', volume_ratio_5='',
            industry_secondary_status='NOT_RUN_FOR_20261105_GENERATION', industry_secondary_theme='',
            industry_secondary_level='', industry_secondary_reason='',
            industry_secondary_gap='Previous day is not a current signal', future_d2='', future_d5=''))
    daily_ref = write_csv(tmp / 'v2_daily_performance.csv', daily_rows)
    source_rows = []
    fund_rows = []
    claim_rows = []
    for code in codes:
        source_id = 'source-' + code
        source_rows.append(dict(source_id=source_id, symbol=code, title='received report',
            url='https://example.org/' + code, sha256='d' * 64, supported_fact_or_metric='业务原文'))
        ids = [source_id, 'INPUT_CANDIDATES', 'INPUT_DAILY_PERFORMANCE']
        if code == codes[1]:
            ids += ['INPUT_PRIOR_RESEARCH', 'INPUT_PRIOR_SOURCES']
        fund_rows.append(dict(symbol=code, source_date=date, observation_date=target, package_id=package,
            input_digest='pack', source_generation=generation, input_sha256=input_sha,
            manifest_sha256=numeric_ref['sha256'], screened_name=code, verified_name=code,
            verified_short_name=code, research_as_of='2026-11-04T19:00:00+08:00',
            latest_financial_period='2026Q3_YTD', new_or_reused='NEW', status='PARTIAL',
            prior_status='COMPLETED' if code == codes[1] else '',
            prior_research_as_of='2026-10-29T19:00:00+08:00' if code == codes[1] else '',
            business='主营原文：收到的公司业务描述。', industry_chain_position='产业链位置原文：客户与产品环节。',
            profit_driver='利润原文，不将叙述解析为认证数值。', growth_quality='增长质量原文',
            cash_debt_quality='现金与债务原文', bottleneck_evidence='卡点原文',
            customer_commercialization='客户商业化原文', orders_capacity='订单产能原文',
            key_risks='风险原文', reused_modules='[]', research_tier='A_DEEPEN_RESEARCH' if code == codes[1] else 'B',
            missing_inputs='["仍有资料待补"]', source_ids=json.dumps(ids),
            industry_secondary_status='NOT_RUN_FOR_20261105_GENERATION', industry_secondary_theme='',
            industry_secondary_level='', industry_secondary_reason='',
            industry_secondary_gap='Previous day is not a current signal', future_d2='', future_d5='',
            RESEARCH_ONLY='true', production_allowed='false', buy_gate_updated='false', orders_sent='false'))
        claim_rows.append(dict(symbol=code, field='business', claim='主营原文声明', basis='RECEIVED_TEXT',
            source_ids=json.dumps([source_id]), citation_granularity='RECORD', research_as_of='2026-11-04T19:00:00+08:00'))
    shared_refs = {
        'CANDIDATES.csv': candidates_ref,
        'DAILY_PERFORMANCE.csv': daily_ref,
        'PRIOR_RESEARCH.csv': prior_research_ref,
        'PRIOR_SOURCES.csv': prior_sources_ref,
    }
    for source_id, (input_key, filename) in m.V2_SHARED_SOURCES.items():
        reference = shared_refs[filename]
        source_rows.append(dict(source_id=source_id, symbol='', title=filename, url='https://drive.google.com/file/d/'+source_id+'/view',
            sha256=reference['sha256'], supported_fact_or_metric='Bound shared input, not company disclosure'))
    fundamentals_ref = write_csv(tmp / 'v2_fundamentals.csv', fund_rows)
    sources_ref = write_csv(tmp / 'v2_sources.csv', source_rows)
    claims_ref = write_csv(tmp / 'v2_claim_lineage.csv', claim_rows)
    files = {name: dict(sha256=reference['sha256']) for name, reference in shared_refs.items()}
    batch_manifest = dict(package_id=package, input_digest='pack', source_date=date, observation_date=target,
        scope=len(codes), source_generation=generation, numeric_manifest=dict(sha256=numeric_ref['sha256']),
        numeric_product=dict(sha256=numeric['artifact']['sha256']), files=files, **m.FLAGS)
    batch_manifest_ref = m.save(tmp / 'v2_batch_manifest.json', batch_manifest)
    return_manifest_ref = m.save(tmp / 'v2_return_manifest.json', dict(package_id=package,
        source_date=date, observation_date=target, source_generation=generation, input_digest='pack',
        scope=len(codes), generated_at='2026-11-04T20:00:00+08:00', **m.FLAGS))
    priority_path = tmp / 'v2_priority_review.md'
    priority_path.write_text('300856.SZ 优先补证\n', encoding='utf-8')
    priority_ref = m.ref(priority_path)
    class_rows = []
    for row in fund_rows:
        symbol = row['symbol']
        priority = '优先补证' if symbol == codes[1] else None
        class_rows.append(dict(symbol=symbol, screened_name=row['screened_name'], verified_name=row['verified_short_name'],
            user_resource_priority=priority, user_resource_priority_source=priority_ref['path'] if priority else None,
            research_tier_received=row['research_tier'], status='RESEARCH_MAIN_CLASSIFICATION_DERIVED',
            research_main_industry='化工与新材料', industry_chain_position_received=row['industry_chain_position'],
            basis_field='business', basis_phrase='主营原文', basis_excerpt=row['business'],
            classification_method='EXPLICIT_SYMBOL_AND_EXACT_SOURCE_PHRASE', source_date=date,
            observation_date=target, source_generation=generation, source_ids=json.loads(row['source_ids']), **m.FLAGS))
    classification_ref = m.save(tmp / 'v2_classification.json', class_rows)
    classification_csv_ref = write_csv(tmp / 'v2_classification.csv', class_rows)
    class_qa_ref = m.save(tmp / 'v2_classification_qa.json', dict(
        status='PASS_364_SCOPE_WITH_TEXT_SUPPORTED_CLASSIFICATION', scope_count=len(codes),
        unique_symbol_count=len(codes), classification_count=len(codes), unknown_count=0,
        source_sha256=fundamentals_ref['sha256'], priority_source_sha256=priority_ref['sha256'],
        json_sha256=classification_ref['sha256'], csv_sha256=classification_csv_ref['sha256'], **m.FLAGS))
    inputs = dict(fundamentals=fundamentals_ref, sources=sources_ref, claim_lineage=claims_ref,
        batch_manifest=batch_manifest_ref, return_manifest=return_manifest_ref,
        daily_performance_csv=daily_ref, classification_rows=classification_ref,
        classification_csv=classification_csv_ref, classification_qa=class_qa_ref,
        priority_review=priority_ref, shared_candidates=candidates_ref,
        shared_prior_research=prior_research_ref, shared_prior_sources=prior_sources_ref)
    config = dict(schema=m.V2_SCHEMA, product_root=str(batch['root']), source_date=date,
        observation_date=target, source_generation=generation, source_input_sha256=input_sha,
        numeric_manifest={'sha256': numeric_ref['sha256']}, scope_count=len(codes),
        owner_publisher=batch['config']['owner_publisher'],
        publication_adapter=batch['config']['publication_adapter'], owner_lock=batch['config']['owner_lock'],
        inputs=inputs, **m.FLAGS)
    return dict(config=config, inputs=inputs, codes=codes, date=date, target=target, tmp=tmp,
        fundamentals=fund_rows, source_rows=source_rows, shared_refs=shared_refs, batch_manifest=batch_manifest)


def prepare(batch):
    return m.prepare(m.save(batch['tmp'] / 'config.json', batch['config']), batch['stage'])


def shard(plan, symbol):
    return next(m.load(local) for target, local in plan['immutable_files'].items() if target.endswith('/'+symbol+'.json'))


def test_v2_return_schema_normalizes_aliases_and_preserves_received_classification(batch):
    fixture = v2_batch(batch)
    config_ref = m.save(fixture['tmp'] / 'v2_import_config.json', fixture['config'])
    plan = m.prepare(config_ref, fixture['tmp'] / 'v2_stage')
    assert plan['status'] == 'PREPARED_NOT_PUBLISHED'
    assert plan['summary']['return_schema'] == m.V2_SCHEMA
    assert plan['summary']['scope_count'] == 3
    assert plan['summary']['themes'] == []
    assert plan['summary']['technical_observe_count'] == 0
    assert plan['summary']['wait_for_trigger_count'] == 0
    assert plan['summary']['secondary_status'] == 'NOT_RUN_FOR_20261105_GENERATION'
    assert plan['summary']['secondary_status_counts'] == {'NOT_RUN_FOR_20261105_GENERATION': 3}
    assert plan['summary']['user_resource_priority_counts'] == {'优先补证': 1}
    assert len(plan['completed']) == 3

    row = shard(plan, '300856.SZ')
    fund = row['received_fundamentals']
    assert fund['status'] == 'PARTIAL'
    assert fund['research_as_of'] == '2026-11-04T19:00:00+08:00'
    assert fund['prior_status'] == 'COMPLETED'
    assert fund['prior_research_as_of'] == '2026-10-29T19:00:00+08:00'
    assert fund['industry_chain_position'] == '产业链位置原文：客户与产品环节。'
    assert fund['bottleneck_evidence'] == '卡点原文'
    assert fund['customer_commercialization'] == '客户商业化原文'
    assert fund['orders_capacity'] == '订单产能原文'
    assert fund['research_tier_received'] == 'A_DEEPEN_RESEARCH'
    assert fund['user_resource_priority'] == '优先补证'
    assert fund['research_main_classification']['research_main_industry'] == '化工与新材料'
    assert json.loads(fund['received_source_record']['source_ids']) == fund['source_ids']
    assert len(fund['claims']) == 1 and fund['claims'][0]['claim'] == '主营原文声明'
    global_sources = [source for source in fund['sources'] if source['source_id'].startswith('INPUT_')]
    assert {source['source_id'] for source in global_sources} == {
        'INPUT_CANDIDATES', 'INPUT_DAILY_PERFORMANCE', 'INPUT_PRIOR_RESEARCH', 'INPUT_PRIOR_SOURCES'}
    assert all(source['symbol'] == '' for source in global_sources)
    assert row['financials_reported'] == {} and row['shareholders_reported'] == {}

    assert row['secondary_screen']['status'] == 'NOT_RUN_FOR_20261105_GENERATION'
    assert row['secondary_screen']['role'] == 'NOT_RUN'
    assert row['secondary_screen']['received_record']['theme'] is None
    assert row['secondary_screen']['received_record']['full_chain_status'] == 'NOT_RUN_FOR_20261105_GENERATION'
    assert all(value is None for value in row['secondary_screen']['reference_fields'].values())
    perf = row['daily_performance']
    assert perf['close'] == 11.25 and perf['day_return_pct'] == pytest.approx(7.142857)
    assert perf['amount_yuan'] == 123000000 and perf['volume_shares'] == 5000000
    assert perf['volume_to_current_MA5'] is None and perf['volume_to_prior_MA5'] is None
    assert perf['future_d2'] is None and perf['future_d5'] is None
    assert perf['current_target_day_return_pct'] is None
    assert perf['current_target_day_performance_status'] == 'NOT_MATERIALIZED_NOT_READ'
    assert perf['received_source_record']['future_d2'] == ''
    assert m.load(m.ref(batch['root'] / 'index.json')) == batch['index']


def test_v2_rejects_arbitrary_empty_symbol_sources_and_shared_input_scope_drift(batch):
    fixture = v2_batch(batch)
    config = fixture['config']
    source_ref = config['inputs']['sources']
    source_rows = m.csv_rows(source_ref)
    source_rows.append(dict(source_id='UNBOUND_GLOBAL_INPUT', symbol='', title='unknown.csv',
        url='https://drive.google.com/file/d/unknown/view', sha256='e' * 64))
    config['inputs']['sources'] = write_csv(fixture['tmp'] / 'v2_sources_extra.csv', source_rows)
    config_ref = m.save(fixture['tmp'] / 'v2_import_config_extra.json', config)
    with pytest.raises(ValueError, match='RECEIVED_GLOBAL_SOURCE_IDS_CONFLICT'):
        m.prepare(config_ref, fixture['tmp'] / 'v2_stage_extra')

    fixture = v2_batch(batch)
    config = fixture['config']
    prior_ref = config['inputs']['shared_prior_research']
    prior_rows = m.csv_rows(prior_ref)
    prior_rows.append(dict(symbol='000001.SZ', status='OUT_OF_SCOPE'))
    changed_prior_ref = write_csv(fixture['tmp'] / 'v2_prior_research_outside.csv', prior_rows)
    config['inputs']['shared_prior_research'] = changed_prior_ref
    source_rows = m.csv_rows(config['inputs']['sources'])
    for source in source_rows:
        if source['source_id'] == 'INPUT_PRIOR_RESEARCH':
            source['sha256'] = changed_prior_ref['sha256']
    config['inputs']['sources'] = write_csv(fixture['tmp'] / 'v2_sources_prior_drift.csv', source_rows)
    manifest = m.load(config['inputs']['batch_manifest'])
    manifest['files']['PRIOR_RESEARCH.csv']['sha256'] = changed_prior_ref['sha256']
    config['inputs']['batch_manifest'] = m.save(fixture['tmp'] / 'v2_manifest_prior_drift.json', manifest)
    config_ref = m.save(fixture['tmp'] / 'v2_import_config_prior_drift.json', config)
    with pytest.raises(ValueError, match='RECEIVED_SHARED_SOURCE_SCOPE_OUTSIDE_BATCH:INPUT_PRIOR_RESEARCH'):
        m.prepare(config_ref, fixture['tmp'] / 'v2_stage_prior_drift')


def test_exact_projection_preserves_raw_status_nulls_and_non_target_fields(batch):
    plan = prepare(batch)
    assert m.load(m.ref(batch['root'] / 'index.json')) == batch['index']
    assert m.load(m.ref(batch['root'] / 'events/latest.json')) == batch['event']
    after_index, after_event = m.load(plan['staged_index']), m.load(plan['staged_event'])
    assert {k: v for k, v in after_index.items() if k != 'company_materials'} == {k: v for k, v in batch['index'].items() if k != 'company_materials'}
    assert after_index['company_materials']['20261029'] == {'keep': True}
    assert {k: v for k, v in after_event.items() if k not in ('company_materials','event_id')} == {k: v for k, v in batch['event'].items() if k != 'event_id'}
    assert len(plan['immutable_files']) == 4
    row = shard(plan, batch['codes'][1])
    assert row['received_fundamentals']['status'] == 'PARTIAL'
    assert row['financials_reported'] == {} and row['shareholders_reported'] == {}
    assert row['daily_performance']['close'] == 11.2
    assert row['daily_performance']['current_target_day_return_pct'] is None
    assert all(value is None for value in row['secondary_screen']['reference_fields'].values())
    assert row['secondary_screen']['received_record']['volume_to_current_MA5'] == .88
    assert row['secondary_screen']['status'] == 'CANNOT_CONFIRM'
    assert row['secondary_screen']['role'] == 'wait_for_trigger'
    assert plan['summary']['original_producer_status_counts'] == {'COMPLETED': 2, 'PARTIAL': 1}


@pytest.mark.parametrize('mutation', ['extra','missing','duplicate','identity','sha','unsafe','target_intraday'])
def test_scope_identity_and_source_drift_fail_before_publication(batch, mutation):
    config = batch['config']
    path = Path(config['inputs']['secondary_rows']['path'])
    rows = m.load(config['inputs']['secondary_rows'])
    if mutation == 'extra': rows.append({**rows[0], 'symbol': '000001.SZ'})
    elif mutation == 'missing': rows.pop()
    elif mutation == 'duplicate': rows.append(rows[0])
    elif mutation == 'identity': rows[0]['target_date'] = '20261106'
    elif mutation == 'unsafe': config['production_allowed'] = True
    elif mutation == 'target_intraday':
        payload = m.load(config['inputs']['daily_performance'])
        payload['rows'][0]['current_target_day_return_pct'] = 1.2
        config['inputs']['daily_performance'] = m.save(Path(config['inputs']['daily_performance']['path']), payload)
    if mutation == 'sha': path.write_text('[]')
    elif mutation not in ('unsafe','target_intraday'): config['inputs']['secondary_rows'] = m.save(path, rows)
    with pytest.raises(ValueError): prepare(batch)
    assert m.load(m.ref(batch['root'] / 'index.json')) == batch['index']


@pytest.mark.skipif(not os.environ.get('V4_EXISTING_PUBLICATION_ADAPTER'), reason='Existing owner adapter must be explicitly pinned')
@pytest.mark.parametrize('drift', ['none','index','event','lock'])
def test_existing_owner_publication_cas_and_stable_lock(batch, drift):
    plan = prepare(batch)
    plan_ref = m.ref(batch['stage'] / 'PUBLICATION_PLAN.json')
    if drift in ('index','event'):
        path = batch['root'] / ('index.json' if drift == 'index' else 'events/latest.json')
        value = json.loads(path.read_text()); value['parallel_owner'] = 'preserve'; m.save(path, value)
    elif drift == 'lock':
        path = Path(batch['config']['owner_lock'])
        path.rename(path.with_suffix('.old')); path.touch()
    if drift == 'none':
        result = m.publish(plan_ref)
        assert result['status'] == 'PUBLISHED_HISTORY_SYNC'  # Existing adapter's unchanged receipt type.
        assert len(result['completed']) == 3
        assert json.loads((batch['root'] / 'index.json').read_text()) == m.load(plan['staged_index'])
    else:
        with pytest.raises(ValueError, match='DRIFT'):
            m.publish(plan_ref)
        if drift in ('index','event'):
            assert json.loads(path.read_text())['parallel_owner'] == 'preserve'


def advance_numeric(batch, date='20261109'):
    root = batch['root']
    original = json.loads((root / 'index.json').read_text())
    product = dict(data_date=date, source_generation='d'*64, source_identity={'input_sha256':'e'*64},
                   rows=[dict(symbol=c) for c in batch['codes']], **m.FLAGS)
    artifact = m.save(root / ('numeric-'+date+'.json'), product)
    numeric = m.save(root / ('manifest-'+date+'.json'), dict(data_date=date, source_generation='d'*64,
                     input_sha256='e'*64, artifact=artifact, **m.FLAGS))
    original['dates'][date] = numeric; original.update(latest_date=date, latest=numeric)
    event = {**batch['event'], 'data_date':date, 'source_generation':'d'*64, 'input_sha256':'e'*64,
             'manifest':numeric, 'artifact':artifact}
    m.save(root/'index.json',original);m.save(root/'events/latest.json',event)
    return original,event


def test_late_return_preserves_latest_numeric_and_completion_byte_identity(batch):
    index,event = advance_numeric(batch)
    plan=prepare(batch)
    assert m.load(plan['staged_event']) == event
    assert plan['staged_event']['sha256'] == plan['expected_event']['sha256']
    after=m.load(plan['staged_index'])
    assert {k:v for k,v in after.items() if k!='company_materials'} == {k:v for k,v in index.items() if k!='company_materials'}
    assert shard(plan,batch['codes'][0])['received_at']


def reader_fixture(batch, plan):
    source_spec=importlib.util.spec_from_file_location('company_candidate_reader', MODULE.parents[1]/'infrastructure/research_lane_source.py')
    source_module=importlib.util.module_from_spec(source_spec);source_spec.loader.exec_module(source_module)
    reader=object.__new__(source_module.ResearchLaneSource)
    index=json.loads((batch['root']/'index.json').read_text());index['company_materials'].pop('20261029',None);m.save(batch['root']/'index.json',index)
    reader._a_product_root=lambda:batch['root']
    reader._a_product_reference=m.load
    def product(date, **kwargs):
        index=json.loads((batch['root']/'index.json').read_text())
        ref=index['dates'][date]
        value=m.load(m.load(ref)['artifact'])
        return {**value,'manifest':ref}
    reader.read_a_daily_product=product
    for target,staged in plan['immutable_files'].items():m.save(target,m.load(staged))
    index=m.load(plan['staged_index']);index['company_materials'].pop('20261029',None);m.save(batch['root']/'index.json',index)
    return reader


def test_cross_day_reuses_original_identity_and_unknown_receipt_never_enters_history(batch):
    plan=prepare(batch);reader=reader_fixture(batch,plan)
    advance_numeric(batch)
    value=reader.read_a_daily_company_materials('20261109',batch['codes'][0],generation='d'*64,input_sha256='e'*64)
    assert value['materials']['data_date']=='20261104'
    assert value['source_generation']=='d'*64
    assert value['material_lifecycle']['material_identity']['source_generation']=='a'*64
    assert value['material_lifecycle']['freshness_status']=='HISTORICAL_NOT_REVIEWED_FOR_CURRENT_CANDIDATES'
    # Actual local reception occurred after the historical source day.
    old=reader.read_a_daily_company_materials('20261104',batch['codes'][0])
    assert old['status']=='NOT_MATERIALIZED' and old['availability_gaps']==['AFTER_ASOF_CUTOFF']
    index=json.loads((batch['root']/'index.json').read_text());binding=index['company_materials']['20261104']
    manifest=m.load(binding);row=m.load(manifest['items'][batch['codes'][0]])
    row.pop('received_at');manifest.pop('received_at')
    manifest['items'][batch['codes'][0]]=m.save(batch['root']/'legacy-shard.json',row)
    index['company_materials']['20261104']=m.save(batch['root']/'legacy-index.json',manifest)
    m.save(batch['root']/'index.json',index)
    current=reader.read_a_daily_company_materials('20261109',batch['codes'][0])
    assert current['material_lifecycle']['received_at'] is None
    historical=reader.read_a_daily_company_materials('20261104',batch['codes'][0])
    assert historical['availability_gaps']==['RECEIVED_TIME_UNKNOWN']


def test_same_day_generation_change_preserves_origin_and_new_candidate_missing(batch):
    plan=prepare(batch);reader=reader_fixture(batch,plan)
    advance_numeric(batch,'20261104')
    answer=reader.read_a_daily_company_materials('20261104',batch['codes'][0])
    assert answer['material_lifecycle']['material_identity']['source_generation']=='a'*64
    assert answer['source_generation']=='d'*64
    with pytest.raises(ValueError,match='PRODUCT_IDENTITY'):
        reader.read_a_daily_company_materials('20261104','000001.SZ')


def test_material_history_keeps_previous_receipt_and_future_publication_is_excluded(batch):
    plan=prepare(batch);reader=reader_fixture(batch,plan)
    manifest=m.load(m.load(plan['staged_index'])['company_materials']['20261104'])
    symbol=batch['codes'][0];row=m.load(manifest['items'][symbol])
    row['received_at']='2026-11-04T23:00:00+08:00'
    row['received_fundamentals']['as_of']='2026-11-04T22:00:00+08:00'
    row['received_fundamentals']['sources'][0]['disclosed_at']='2026-11-10T00:00:00+08:00'
    manifest['received_at']=row['received_at'];manifest['items'][symbol]=m.save(batch['root']/'future-public.json',row)
    index=json.loads((batch['root']/'index.json').read_text());index['company_materials']['20261104']=m.save(batch['root']/'future-manifest.json',manifest)
    m.save(batch['root']/'index.json',index);advance_numeric(batch)
    assert reader.read_a_daily_company_materials('20261104',symbol)['availability_gaps']==['AFTER_ASOF_CUTOFF']
    row['received_fundamentals']['sources'][0]['disclosed_at']='2026-11-04T00:00:00+08:00'
    manifest['items'][symbol]=m.save(batch['root']/'past-public.json',row)
    index=json.loads((batch['root']/'index.json').read_text());index['company_materials']['20261104']=m.save(batch['root']/'past-manifest.json',manifest)
    m.save(batch['root']/'index.json',index)
    assert reader.read_a_daily_company_materials('20261104',symbol)['status']=='PARTIAL_RECEIVED'
    second=m.prepare(m.save(batch['tmp']/'second-config.json',batch['config']),batch['tmp']/'second-stage')
    assert m.load(second['staged_index'])['company_materials_versions']['20261104']==[index['company_materials']['20261104']]


@pytest.mark.skipif(not os.environ.get('V4_MASTER_IMPORT_CONFIG'),reason='Actual return requires explicit pinned config')
def test_actual_v3_exact_scope_raw_rows_and_industry_preserved(tmp_path):
    reference=m.ref(os.environ['V4_MASTER_IMPORT_CONFIG'])
    plan=m.prepare(reference,tmp_path/'stage')
    config=m.load(reference)
    original={row['symbol']:row for row in m.csv_rows(config['inputs']['fundamentals'])}
    secondary={row['symbol']:row for row in m.csv_rows(config['inputs']['secondary_rows'])}
    manifest=m.load(plan['immutable_files'][m.load(plan['staged_index'])['company_materials']['20261109']['path']])
    assert set(manifest['items'])==set(original) and len(original)==371
    for symbol in original:
        value=m.load(plan['immutable_files'][manifest['items'][symbol]['path']])
        assert value['received_fundamentals']['received_source_record']==original[symbol]
        assert value['received_fundamentals']['status']=='PARTIAL'
        assert value['secondary_screen']['received_record']==secondary[symbol]
        assert value['received_at']==config['received_at']
        assert value['financials_reported']=={} and value['daily_performance']['future_d2'] is None
    bad=copy.deepcopy(config);bad['generation']='0'*64
    with pytest.raises(ValueError,match='NUMERIC_OR_EVENT_IDENTITY'):
        m.prepare(m.save(tmp_path/'bad-generation.json',bad),tmp_path/'bad-stage')


def test_new_candidate_without_material_and_future_receipt_remain_unknown(batch):
    plan=prepare(batch);reader=reader_fixture(batch,plan)
    advance_numeric(batch)
    index=json.loads((batch['root']/'index.json').read_text())
    numeric=m.load(index['latest']);product=m.load(numeric['artifact'])
    product['rows'].append(dict(symbol='000001.SZ'))
    numeric['artifact']=m.save(batch['root']/'new-membership.json',product)
    index['latest']=index['dates']['20261109']=m.save(batch['root']/'new-membership-manifest.json',numeric)
    m.save(batch['root']/'index.json',index)
    answer=reader.read_a_daily_company_materials('20261109','000001.SZ')
    assert answer['status']=='NOT_MATERIALIZED' and answer['missing_reason']=='NO_BOUND_MATERIALS_FOR_SYMBOL'
    bad={**batch['config'],'received_at':'2999-01-01T00:00:00+00:00'}
    # Unrelated numeric advance is consistent with its original latest completion;
    # receipt validation is exercised against the source fixture's initial index.
    m.save(batch['root']/'index.json',batch['index']);m.save(batch['root']/'events/latest.json',batch['event'])
    with pytest.raises(ValueError,match='LOCAL_RECEIPT_TIME_INVALID'):
        m.prepare(m.save(batch['tmp']/'future-receipt.json',bad),batch['tmp']/'future-stage')


@pytest.mark.parametrize('disclosed,received,history,eligible,gap', [
    ('2026-11-04','2026-11-04T21:07:36+08:00',False,True,None),
    ('2026-11-05','2026-11-04T21:07:36+08:00',False,False,'AFTER_ASOF_CUTOFF'),
    ('2026-11-04T21:31:00+08:00','2026-11-04T21:07:36+08:00',False,False,'AFTER_ASOF_CUTOFF'),
    ('2026-11-04T21:00:00+08:00','2026-11-04T21:07:36+08:00',False,True,None),
    ('2026-11-04','2026-11-04T21:31:00+08:00',False,False,'AFTER_ASOF_CUTOFF'),
    ('2026-11-04','2026-11-04',True,False,'RECEIVED_TIME_UNKNOWN'),
    ('2026-11-04','2026-11-05T00:00:00+08:00',True,False,'AFTER_ASOF_CUTOFF'),
    ('2026-11-05','2026-11-04T21:07:36+08:00',True,False,'AFTER_ASOF_CUTOFF'),
    ('2026-11-04','2026-11-04T21:07:36+08:00',True,True,None),
])
def test_date_precision_cutoff_keeps_same_day_without_inventing_timestamp(batch,monkeypatch,disclosed,received,history,eligible,gap):
    from datetime import datetime
    plan=prepare(batch);reader=reader_fixture(batch,plan)
    monkeypatch.setitem(reader.read_a_daily_company_materials.__func__.__globals__,'shanghai_now',
                        lambda:datetime.fromisoformat('2026-11-04T21:30:00+08:00'))
    index=json.loads((batch['root']/'index.json').read_text())
    manifest=m.load(index['company_materials']['20261104']);symbol=batch['codes'][0]
    row=m.load(manifest['items'][symbol]);row['received_at']=received
    row['received_fundamentals']['as_of']='2026-11-04T20:00:00+08:00'
    row['business_reported']['asof_date']='2026-11-04'
    row['received_fundamentals']['sources'][0]['disclosed_at']=disclosed
    manifest['received_at']=received;manifest['items'][symbol]=m.save(batch['root']/'precision-shard.json',row)
    index['company_materials']['20261104']=m.save(batch['root']/'precision-manifest.json',manifest)
    m.save(batch['root']/'index.json',index)
    if history:advance_numeric(batch)
    value=reader.read_a_daily_company_materials('20261104',symbol)
    assert (value['status']=='PARTIAL_RECEIVED') is eligible
    if eligible:
        assert value['materials']['received_fundamentals']['sources'][0]['disclosed_at']==disclosed
        assert value['material_lifecycle']['historical_PIT_safe'] is False
        if len(disclosed)==10:
            assert reader._company_time(disclosed) is None
            assert value['material_lifecycle']['disclosure_time_status']=='UNKNOWN_DATE_ONLY_PRESENT'
    else:assert gap in value['availability_gaps']


@pytest.mark.skipif(not os.environ.get('V4_MASTER_IMPORT_CONFIG'),reason='Actual date-boundary probe requires explicit package')
def test_actual_same_day_date_only_disclosures_use_current_received_materials(tmp_path,monkeypatch):
    from datetime import datetime
    config=m.load(m.ref(os.environ['V4_MASTER_IMPORT_CONFIG']))
    evidence=Path(config['inputs']['return_manifest']['path']).parents[2]/'company'
    plan=m.load(m.ref(evidence/'prepared_import/PUBLICATION_PLAN.json'))
    source_spec=importlib.util.spec_from_file_location('company_date_precision_reader',MODULE.parents[1]/'infrastructure/research_lane_source.py')
    source_module=importlib.util.module_from_spec(source_spec);source_spec.loader.exec_module(source_module)
    monkeypatch.setattr(source_module,'shanghai_now',lambda:datetime.fromisoformat('2026-11-09T21:30:00+08:00'))
    reader=object.__new__(source_module.ResearchLaneSource);reader._a_product_root=lambda:tmp_path
    index=m.load(plan['staged_index']);m.save(tmp_path/'index.json',index)
    reader._a_product_reference=lambda reference:m.load(plan['immutable_files'].get(reference['path'],reference))
    numeric=m.load(index['dates']['20261109']);product={**m.load(numeric['artifact']),'manifest':index['dates']['20261109']}
    reader.read_a_daily_product=lambda *args,**kwargs:product
    for symbol in ('000554.SZ','301263.SZ','603477.SH'):
        value=reader.read_a_daily_company_materials('20261109',symbol)
        assert value['status']=='PARTIAL_RECEIVED'
        assert value['material_lifecycle']['material_source_date']=='20261109'
        assert value['material_lifecycle']['received_at']==config['received_at']
        assert value['material_lifecycle']['disclosure_time_status']=='UNKNOWN_DATE_ONLY_PRESENT'
        assert value['material_lifecycle']['historical_PIT_safe'] is False
