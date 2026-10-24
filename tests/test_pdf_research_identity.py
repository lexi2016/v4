from dataclasses import replace
import hashlib

import pytest

from infrastructure.pdf_research import PageText
from infrastructure.pdf_research_identity import (
    AnalysisConfiguration, IdentityError, SourceOccurrence, build_analysis_identity,
)


def _input():
    text = 'Page one: exact source body and 2026 earnings.'
    return dict(pdf_sha256='a' * 64,
                pages=[PageText(1, 1, text, 'NATIVE_TEXT', hashlib.sha256(text.encode()).hexdigest(), 'pypdf-6.10.0')],
                page_count=1, extraction_provenance={'native': {'version': '6.10.0'}, 'ocr': None},
                extraction_version='selection-v1', model_visible_metadata={'title': '20261023-report.pdf'},
                configuration=AnalysisConfiguration('existing-model', 'frozen-model-sha', {'temperature': 0, 'sampler': {'top_p': 1}},
                    {'type': 'object'}, 'card-v1', [{'role': 'system', 'content': 'Exact prompt'}], 'prompt-v1', 'semantic-v1'))


def test_occurrences_are_namespaced_without_losing_legacy_ids():
    left = SourceOccurrence('zsxq', '123')
    right = SourceOccurrence('upload', '123')
    assert left.original_source_id == right.original_source_id == '123'
    assert left.occurrence_id != right.occurrence_id
    assert SourceOccurrence('a:b', 'c').occurrence_id != SourceOccurrence('a', 'b:c').occurrence_id


def test_duplicate_occurrences_and_mapping_order_share_identical_analysis():
    args = _input()
    before = build_analysis_identity(**args)
    # Occurrence ID is deliberately separate, unless visible in the request.
    assert SourceOccurrence('zsxq', 'first') != SourceOccurrence('zsxq', 'second')
    args['model_visible_metadata'] = {'archived_date': None, 'title': '20261023-report.pdf', 'source_document_date': None}
    after = build_analysis_identity(**args)
    assert before == after
    assert before.analysis_id == hashlib.sha256(before.canonical_manifest).hexdigest()
    assert before.manifest['model_visible_metadata']['source_document_date'] is None
    value = before.manifest
    value['pdf_sha256'] = 'bad'
    assert before.manifest['pdf_sha256'] == 'a' * 64


@pytest.mark.parametrize('field,value', [
    ('pdf_sha256', 'b' * 64), ('extraction_version', 'selection-v2'),
    ('extraction_provenance', {'native': {'version': '6.10.0'}, 'ocr': {'version': 'new'}}),
    ('model_visible_metadata', {'source_document_date': '2026-10-22'}),
    ('model_visible_metadata', {'archived_date': '2026-10-23', 'publisher': 'House'}),
    ('page_count', 2),
])
def test_relevant_manifest_input_changes_identity(field, value):
    args = _input()
    original = build_analysis_identity(**args)
    args[field] = value
    if field == 'page_count':
        args['pages'] = [replace(args['pages'][0], page_total=2)]
    assert build_analysis_identity(**args).analysis_id != original.analysis_id


@pytest.mark.parametrize('field,value', [('model_id', 'other'), ('model_version', 'different-weights'), ('model_config', {'temperature': .2}),
    ('schema', {'type': 'object', 'required': ['claims']}), ('schema_version', 'card-v2'),
    ('prompt', [{'role': 'system', 'content': 'Changed'}]), ('prompt_version', 'prompt-v2'),
    ('semantic_pipeline_version', 'semantic-v2')])
def test_each_model_configuration_dimension_is_bound(field, value):
    args = _input()
    original = build_analysis_identity(**args)
    args['configuration'] = replace(args['configuration'], **{field: value})
    assert build_analysis_identity(**args).analysis_id != original.analysis_id


def test_actual_page_text_sha_and_partial_coverage_are_explicit():
    args = _input()
    original = build_analysis_identity(**args)
    args['pages'] = [replace(args['pages'][0], text='Changed source', text_sha256=None)]
    assert build_analysis_identity(**args).analysis_id != original.analysis_id
    args['pages'] = [replace(args['pages'][0], text_sha256='f' * 64)]
    with pytest.raises(IdentityError, match='PAGE_TEXT_SHA_MISMATCH'):
        build_analysis_identity(**args)
    args = _input()
    args['page_count'] = 3
    args['pages'] = [replace(args['pages'][0], page_number=2, page_total=3)]
    assert build_analysis_identity(**args).manifest['coverage'] == 'PARTIAL'


@pytest.mark.parametrize('kind', ['empty', 'duplicate', 'reversed', 'blank', 'status', 'nan'])
def test_invalid_missing_or_corrupt_identity_inputs_fail_closed(kind):
    args = _input()
    p = args['pages'][0]
    if kind == 'empty': args['pages'] = []
    if kind == 'duplicate': args['pages'] = [p, p]
    if kind == 'reversed':
        args['page_count'] = 2
        args['pages'] = [replace(p, page_number=2, page_total=2), replace(p, page_total=2)]
    if kind == 'blank': args['pages'] = [replace(p, text='')]
    if kind == 'status': args['pages'] = [replace(p, status='FAILED')]
    if kind == 'nan': args['model_visible_metadata'] = {'score': float('nan')}
    with pytest.raises(IdentityError): build_analysis_identity(**args)
