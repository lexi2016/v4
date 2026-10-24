"""Task3 read contracts. All publications/reviews here are local test fixtures."""
import ast
import inspect
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from infrastructure.pdf_research_identity import SourceOccurrence
from infrastructure.pdf_research_publication import PdfPublisher, PdfResearchReader, digest, read_json, write_json
from apps.api.v35_api import research_lane_router as router_module


def publication(root, aid='a' * 64, date='2026-10-23', occurrence='same-document', generation=0):
    publisher = PdfPublisher(root)
    metadata = {'title': 'Explicit test fixture', 'source_document_date': date, 'archived_date': '2026-10-24'}
    task = {'analysis_id': aid, 'input_manifest': {'test_fixture': True}, 'metadata': metadata,
        'pdf_sha256': 'b' * 64, 'page_count': 1, 'chunks': [{'sha256': 'c' * 64, 'evidence_ids': ['d' * 64]}],
        'occurrences': [{'namespace': 'zsxq', 'original_source_id': occurrence, 'model_visible_metadata': metadata}]}
    card = {'material_type': 'Test fixture', 'event_or_meeting_object': 'UNKNOWN', 'facts': [
        {'claim': 'A cited fact', 'evidence': [{'page_number': 1, 'evidence_id': 'd' * 64, 'quote': 'Exact source sentence', 'page_text_sha256': 'e' * 64}]}],
        'forecasts': [], 'risks': [], 'source_usage_limits': [], 'unknowns': []}
    chunks = [{'analysis_id': aid, 'generation': generation, 'chunk_index': 1, 'chunk_sha256': 'c' * 64,
        'deterministic_status': 'PASS', 'raw_sha256': 'e' * 64, 'validated': {'card': card}}]
    meta = publisher.publish(task, generation, chunks, generated_at='2026-10-24T00:00:00Z', writer_id='test-writer', source_sha256={})
    return publisher, meta, task


def api(root):
    app = FastAPI()
    app.include_router(router_module.create_research_lane_router(root))
    return TestClient(app)


def roots(tmp_path):
    data = tmp_path / 'data'; data.mkdir()
    research = data / 'external_sources/zsxq_hourly/pdf_local/research'
    return data, research


def manifest(root):
    return {str(p.relative_to(root)): digest(p.read_bytes()) for p in root.rglob('*') if p.is_file()}


def test_summary_is_lazy_date_bound_default20_and_cursor_snapshot_bound(tmp_path, monkeypatch):
    data, research = roots(tmp_path)
    for n in range(23): publication(research, digest(str(n).encode()), occurrence=str(n))
    publication(research, 'f' * 64, date=None)
    publication(research, 'e' * 64, date='2026-10-22')
    before = manifest(data)
    import infrastructure.pdf_research_publication as module
    original = module.read_bytes
    def read(path, **kwargs):
        assert Path(path).name != 'result.json', 'list eagerly opened a body'
        return original(path, **kwargs)
    monkeypatch.setattr(module, 'read_bytes', read)
    client = api(data)
    page = client.get('/api/v3/research/pdf-research?research_date=20261023')
    assert page.status_code == 200 and page.headers['cache-control'] == 'no-store'
    first = page.json(); assert len(first['items']) == 20 and first['total_count'] == 23
    assert all('body_markdown' not in row for row in first['items'])
    second = client.get('/api/v3/research/pdf-research', params={'research_date': '20261023', 'cursor': first['next_cursor']}).json()
    assert len(second['items']) == 3 and second['next_cursor'] is None
    assert not {x['reference_id'] for x in first['items']} & {x['reference_id'] for x in second['items']}
    assert client.get('/api/v3/research/pdf-research', params={'research_date': '20261022', 'cursor': first['next_cursor']}).status_code == 422
    assert client.get('/api/v3/research/pdf-research?undated=true').json()['total_count'] == 1
    for query in ['', '?research_date=20260230', '?research_date=20261023&undated=true', '?cursor=garbage&undated=true']:
        assert client.get('/api/v3/research/pdf-research' + query).status_code == 422
    assert manifest(data) == before


def test_detail_fixed_occurrence_date_generation_and_source_context(tmp_path):
    data, research = roots(tmp_path)
    publisher, meta, _ = publication(research)
    occurrence = SourceOccurrence('zsxq', 'same-document')
    # This mocked review exercises reader selection only, not content acceptance.
    receipt = {'verdict': 'PASS', 'review_type': 'CONTENT', 'scope': 'FULL_ANALYSIS', 'critical_errors': 0,
        'analysis_id': meta['analysis_id'], 'input_manifest_sha256': meta['analysis_id'], 'context_id': meta['context_id'],
        'generation': 0, 'result_sha256': meta['result_sha256'], 'protocol_sha256': meta['protocol_sha256'],
        'independent': True, 'reviewer_id': 'test-only-mocked-reviewer'}
    path = tmp_path / 'mock-review.json'; path.write_text(json.dumps(receipt))
    publisher.accept(meta['analysis_id'], 0, {'path': str(path), 'sha256': digest(path.read_bytes())})
    publication(research, generation=1)
    publication(research, 'f' * 64, date='2026-10-22')
    client = api(data); row = client.get('/api/v3/research/pdf-research?research_date=20261023').json()['items'][0]
    assert row['accepted']['generation'] == 0 and row['latest_generated']['generation'] == 1
    params = {'research_date': '20261023', 'occurrence_id': occurrence.occurrence_id, 'generation': 1}
    before = manifest(data)
    detail = client.get('/api/v3/research/pdf-research/' + meta['analysis_id'], params=params)
    assert detail.status_code == 200
    body = detail.json(); assert body['semantic_review'] == 'PENDING_INDEPENDENT_REVIEW'
    assert digest(body['body_markdown'].encode()) == body['body_sha256']
    assert body['result_sha256'] == row['latest_generated']['result_sha256']
    for key, value in [('research_date', '20261022'), ('occurrence_id', '0' * 64), ('generation', 99)]:
        assert client.get('/api/v3/research/pdf-research/' + meta['analysis_id'], params={**params, key: value}).status_code == 404
    result = publisher.version_root(meta['analysis_id'], 1) / 'result.json'; result.write_text('{}')
    assert client.get('/api/v3/research/pdf-research/' + meta['analysis_id'], params=params).status_code == 409
    assert set(manifest(data)) == set(before)


def test_legacy_scope_body_and_sha_preserved_without_full_acceptance(tmp_path):
    data, research = roots(tmp_path)
    result = tmp_path / 'legacy.json'; result.write_text('{"facts":[{"claim":"old scoped fact"}]}')
    review = tmp_path / 'review.json'; review.write_text('{"status":"SCOPED_PASS","scope":"one fact only"}')
    occ = SourceOccurrence('local_pdf', 'old-id')
    PdfPublisher(research).import_legacy_reference(occ, 'b' * 64,
        {'path': str(result), 'sha256': digest(result.read_bytes())}, {'path': str(review), 'sha256': digest(review.read_bytes())}, 'one fact only')
    client = api(data); row = client.get('/api/v3/research/pdf-research?undated=true').json()['items'][0]
    assert row['accepted'] is None and row['analysis_id'] is None and row['scope'] == 'one fact only'
    value = client.get('/api/v3/research/pdf-research/' + row['reference_id'], params={'undated': True, 'occurrence_id': occ.occurrence_id}).json()
    assert value['body_markdown'].encode() == result.read_bytes()
    assert value['result_sha256'] == digest(result.read_bytes())
    review.write_text('{}')
    assert client.get('/api/v3/research/pdf-research?undated=true').status_code == 409


def test_scoped_legacy_is_linked_only_to_same_occurrence_pdf_and_undated_context(tmp_path):
    data, research = roots(tmp_path)
    publisher, _, _ = publication(research, date=None)
    publication(research, 'e' * 64, date='2026-10-22')
    result = tmp_path / 'legacy.json'; result.write_text('{"content":{"material_type":"历史资料","event_or_meeting_object":"对象","facts":[{"claim":"旧范围事实","evidence":[{"page_number":1}]}]}}')
    reference = {'path': str(result), 'sha256': digest(result.read_bytes())}
    review = tmp_path / 'legacy-review.json'; review.write_text(json.dumps({'status':'SCOPED_PASS','document_id':'same-document','card':reference}))
    publisher.import_legacy_reference(SourceOccurrence('zsxq', 'same-document'), 'b' * 64,
        reference, {'path':str(review),'sha256':digest(review.read_bytes())}, 'one fact only')
    reader = PdfResearchReader(research)
    row = next(x for x in reader.list(undated=True)['items'] if x['reference_kind']=='ANALYSIS')
    assert row['accepted'] is None and len(row['legacy_references']) == 1
    assert reader.list(research_date='20261022')['items'][0]['legacy_references'] == []
    legacy = row['legacy_references'][0]
    detail = reader.detail(legacy['reference_id'], occurrence_id=legacy['occurrence']['occurrence_id'], undated=True)
    assert '旧范围事实 [第1页]' in detail['body_markdown'] and detail['analysis_id'] is None
    assert detail['result_sha256'] == reference['sha256']


def test_failed_summary_validates_manifest_reference_and_journal_without_repair(tmp_path):
    from infrastructure.pdf_research_execution import Journal, RUN_SCHEMA
    data, research = roots(tmp_path)
    identity_manifest = {'fixture':'failed run'}; aid = digest(__import__('infrastructure.pdf_research_identity',fromlist=['canonical_json']).canonical_json(identity_manifest))
    metadata = {'source_document_date':'2026-10-23'}
    task = {'analysis_id':aid,'input_manifest':identity_manifest,'metadata':metadata,'pdf_sha256':'b'*64,
        'occurrences':[{'namespace':'test','original_source_id':'failed','model_visible_metadata':metadata}]}
    run = {'schema':RUN_SCHEMA,'run_id':'failed','tasks':[task]}
    external = tmp_path/'run.json';external.write_text(json.dumps(run))
    reference = {'path':str(external),'sha256':digest(external.read_bytes())}
    directory = research/'analysis-runs/failed'
    write_json(research,directory/'manifest.json',run)
    write_json(research,research/'analysis-queue/failed.json',{'run_id':'failed','reference':reference})
    journal = Journal(research,directory/'journal.jsonl');journal.append({'event':'binding','run_manifest_sha256':reference['sha256']})
    journal.append({'event':'failed','analysis_id':aid,'code':'CONTENT_FAILED'})
    before=manifest(data);client=api(data)
    row=client.get('/api/v3/research/pdf-research?research_date=20261023').json()['items'][0]
    assert row['execution_status']=='FAILED' and row['reason_code']=='CONTENT_FAILED' and row['latest_generated'] is None
    assert manifest(data)==before
    changed=read_json(directory/'manifest.json');changed['tasks'][0]['metadata']['source_document_date']='2026-10-22'
    (directory/'manifest.json').write_text(json.dumps(changed))
    assert client.get('/api/v3/research/pdf-research?research_date=20261023').status_code==409


def test_lane_has_independent_missing_pdf_summary_and_ocr_detail_additive_refs(tmp_path, monkeypatch):
    data, _ = roots(tmp_path)
    client = api(data)
    value = client.get('/api/v3/research/lane?research_date=20261023').json()
    assert value['status'] == 'NOT_MATERIALIZED'
    assert value['pdf_research']['status'] == 'NOT_MATERIALIZED'
    assert 'ocr_ingestion' in value
    original = {'schema_version': 'v4.zsxq_pdf_document_detail.v1', 'document_id': 'a' * 64, 'research_date': '20261023', 'pages': []}
    monkeypatch.setattr(router_module, 'read_pdf_document_detail', lambda *args: dict(original))
    response = client.get('/api/v3/research/pdf-documents/' + 'a' * 64 + '?research_date=20261023')
    assert response.json() == {**original, 'analysis_references': []}
    assert not list(data.rglob('*'))


def test_non_pdf_role_projection_and_optional_defaults_match_active_baseline():
    active = Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/hkex-announcements-api-20261023-r1/app/apps/api/v35_api/research_lane_router.py')
    tree = ast.parse(active.read_text())
    names = {'_lane_response', '_status_only_lane_response'}
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    namespace = dict(vars(router_module))
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(active), 'exec'), namespace)
    archive = {'articles': [{'article_id': 'x', 'published_at': '', 'title': '高盛：测试公司（HK.00700）', 'stock_name': '高盛', 'stock_code': '', 'source_type': 'zsxq'}],
        'stock_pool': [], 'article_count': 1, 'stock_pool_count': 0, 'cannot_confirm': [], 'source_schema_version': 'fixture', 'source_generated_at': '', 'source_counts': {}}
    for name, args in [('_lane_response', archive), ('_status_only_lane_response', {'slots': []})]:
        kwargs = {'research_date': '20261023', 'endpoint_mode': 'EXACT'}
        if name == '_status_only_lane_response': kwargs['page_trade_date'] = None
        assert getattr(router_module, name)(args, **kwargs) == namespace[name](args, **kwargs)
    from apps.api.v35_api._research_lane_router_parts.lane_response import __lane_response_body
    from apps.api.v35_api._research_lane_router_parts.status_response import __status_only_lane_response_body
    for helper, old in [(__lane_response_body, namespace['_lane_response']), (__status_only_lane_response_body, namespace['_status_only_lane_response'])]:
        current = inspect.signature(helper).parameters
        for key, parameter in inspect.signature(old).parameters.items():
            if parameter.kind == inspect.Parameter.KEYWORD_ONLY: assert current[key].default == parameter.default
