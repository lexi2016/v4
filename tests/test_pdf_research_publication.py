import json
from pathlib import Path
import pytest
from infrastructure.pdf_research_identity import SourceOccurrence
from infrastructure.pdf_research_publication import PdfPublisher, PublicationError, digest, read_json
from infrastructure import pdf_research_protocol as p


def fixture(tmp_path):
    publisher = PdfPublisher(tmp_path / 'research')
    task = {'analysis_id': 'a' * 64, 'input_manifest': {'actual': 'complete input'},
        'pdf_sha256': 'b' * 64, 'page_count': 1,
        'metadata': {'title': 'Report', 'source_document_date': None, 'archived_date': None},
        'chunks': [{'sha256': 'c' * 64, 'evidence_ids': ['d' * 64]}],
        'occurrences': [{'namespace': 'zsxq', 'original_source_id': 'legacy-id',
            'model_visible_metadata': {'title': 'Report', 'source_document_date': None, 'archived_date': None}}]}
    card = {'material_type': '研究资料', 'event_or_meeting_object': 'UNKNOWN',
        'facts': [{'claim': '原文称公司发展', 'evidence': [{'page_number': 1, 'evidence_id': 'd' * 64}]}],
        'forecasts': [], 'risks': [], 'source_usage_limits': [], 'unknowns': []}
    def chunks(generation):
        return [{'analysis_id': task['analysis_id'], 'generation': generation, 'chunk_index': 1,
            'chunk_sha256': 'c' * 64, 'deterministic_status': 'PASS', 'raw_sha256': 'e' * 64,
            'validated': {'card': card}}]
    return publisher, task, chunks


def publish(publisher, task, chunks, generation=0, crash=None):
    return publisher.publish(task, generation, chunks(generation), generated_at='2026-10-23T00:00:00Z',
        writer_id='writer', source_sha256={'actual-source': 'f' * 64}, crash=crash)


def review_file(tmp_path, meta):
    value = {'verdict': 'PASS', 'review_type': 'CONTENT', 'scope': 'FULL_ANALYSIS', 'critical_errors': 0,
        'analysis_id': meta['analysis_id'], 'input_manifest_sha256': meta['analysis_id'], 'context_id': meta['context_id'],
        'generation': meta['generation'], 'result_sha256': meta['result_sha256'],
        'protocol_sha256': p.PROTOCOL_SHA256, 'independent': True, 'reviewer_id': 'independent-reviewer'}
    path = tmp_path / f"review-{meta['generation']}.json"
    path.write_text(json.dumps(value))
    return value, path


def test_pending_generation_does_not_replace_accepted_and_duplicate_occurrence_reuses_result(tmp_path):
    publisher, task, chunks = fixture(tmp_path)
    meta = publish(publisher, task, chunks)
    occurrence = SourceOccurrence('zsxq', 'legacy-id')
    assert publisher.pointers(occurrence, task['analysis_id'])['accepted'] is None
    _, path = review_file(tmp_path, meta)
    publisher.accept(task['analysis_id'], 0, {'path': str(path), 'sha256': digest(path.read_bytes())})
    publish(publisher, task, chunks, 1)
    pointer = publisher.pointers(occurrence, task['analysis_id'])
    assert pointer['accepted']['generation'] == 0
    assert pointer['latest_generated']['generation'] == 1
    task['occurrences'] = [{'namespace': 'upload', 'original_source_id': 'new-occurrence', 'model_visible_metadata': task['metadata']}]
    reused = publish(publisher, task, chunks)
    assert reused['result_sha256'] == meta['result_sha256']
    assert publisher.pointers(SourceOccurrence('upload', 'new-occurrence'), task['analysis_id'])['accepted']['generation'] == 0


@pytest.mark.parametrize('damage', ['writer', 'wrong_result', 'code_only', 'partial_scope', 'wrong_context', 'critical'])
def test_only_bound_independent_full_content_review_can_advance_pointer(tmp_path, damage):
    publisher, task, chunks = fixture(tmp_path)
    meta = publish(publisher, task, chunks)
    value, path = review_file(tmp_path, meta)
    if damage == 'writer': value['reviewer_id'] = 'writer'
    if damage == 'wrong_result': value['result_sha256'] = 'f' * 64
    if damage == 'code_only': value['review_type'] = 'CODE'
    if damage == 'partial_scope': value['scope'] = 'ONE_CLAIM'
    if damage == 'wrong_context': value['context_id'] = 'f' * 64
    if damage == 'critical': value['critical_errors'] = 1
    path.write_text(json.dumps(value))
    with pytest.raises(PublicationError, match='CONTENT_REVIEW_REQUIRED'):
        publisher.accept(task['analysis_id'], 0, {'path': str(path), 'sha256': digest(path.read_bytes())})
    assert publisher.pointers(SourceOccurrence('zsxq', 'legacy-id'), task['analysis_id'])['accepted'] is None


def test_metadata_context_and_source_occurrence_cannot_cross_join(tmp_path):
    publisher, task, chunks = fixture(tmp_path)
    publish(publisher, task, chunks)
    assert publisher.pointers(SourceOccurrence('zsxq', 'other-id'), task['analysis_id'])['latest_generated'] is None
    assert publisher.pointers(SourceOccurrence('zsxq', 'legacy-id'), 'f' * 64)['latest_generated'] is None
    task['occurrences'][0]['model_visible_metadata'] = {'source_document_date': '2026-10-20'}
    with pytest.raises(PublicationError, match='CONTEXT_MISMATCH'): publish(publisher, task, chunks, 1)


def test_index_rebuild_reconstructs_from_formal_metadata_and_detects_tamper(tmp_path):
    publisher, task, chunks = fixture(tmp_path)
    publish(publisher, task, chunks)
    index = read_json(publisher.root / 'analysis-index.json')
    (publisher.root / 'analysis-index.json').unlink()
    assert publisher.rebuild_index() == 1
    assert read_json(publisher.root / 'analysis-index.json') == index
    path = publisher.version_root(task['analysis_id'], 0) / 'metadata.json'
    value = read_json(path);value['context_id'] = 'f' * 64;path.write_text(json.dumps(value))
    with pytest.raises(PublicationError, match='METADATA_BINDING'): publisher.rebuild_index()


def test_legacy_scoped_reference_preserves_original_bytes_and_never_creates_new_accepted(tmp_path):
    publisher, task, chunks = fixture(tmp_path)
    result = tmp_path / 'old-result.json';result.write_bytes(b'{"old":true}')
    review = tmp_path / 'old-review.json';review.write_bytes(b'{"status":"SCOPED_PASS","scope":"one claim"}')
    before = [result.read_bytes(), review.read_bytes()]
    occurrence = SourceOccurrence('zsxq', 'original-id')
    value = publisher.import_legacy_reference(occurrence, 'b' * 64,
        {'path': str(result), 'sha256': digest(result.read_bytes())},
        {'path': str(review), 'sha256': digest(review.read_bytes())}, 'one claim')
    assert value['analysis_id'] is None
    assert value['status'] == 'LEGACY_SCOPED_REFERENCE_NOT_NEW_INPUT_ACCEPTANCE'
    assert publisher.pointers(occurrence, task['analysis_id'])['accepted'] is None
    assert [result.read_bytes(), review.read_bytes()] == before


def test_owned_root_and_symlink_escape_are_rejected(tmp_path):
    publisher, task, chunks = fixture(tmp_path)
    outside = tmp_path / 'outside';outside.mkdir()
    publisher.root.mkdir()
    (publisher.root / 'analyses').symlink_to(outside)
    with pytest.raises(PublicationError, match='SYMLINK'): publish(publisher, task, chunks)
