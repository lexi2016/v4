"""Check the exact Main projection delta using existing synthetic source fixtures."""
from __future__ import annotations

import ast
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main():
    receipt_path = Path(__file__).with_name('MAIN_OPTIONAL_STAGE_EVIDENCE.json')
    receipt = json.loads(receipt_path.read_text())
    active = Path(receipt['active_main'])
    candidate_files = {entry['path']: Path(entry['candidate']) for entry in receipt['files']}
    for entry in receipt['files']:
        assert hashlib.sha256((active / entry['path']).read_bytes()).hexdigest() == entry['before_sha256']
        assert hashlib.sha256(candidate_files[entry['path']].read_bytes()).hexdigest() == entry['after_sha256']
    sys.path.insert(0, str(active))
    original_contract = load('contracts.research', active / 'contracts/research.py')
    original_domain = load('_original_main_research', active / 'domains/research.py')
    contract = load('contracts.research', candidate_files['contracts/research.py'])
    domain = load('_candidate_main_research', candidate_files['domains/research.py'])
    root = Path(__file__).resolve().parents[3]
    tests = ast.parse((root / 'tests/test_stage_research_context_v4.py').read_text())
    fixture = next(node for node in tests.body if isinstance(node, ast.FunctionDef) and node.name == '_source')
    namespace = {}
    exec(compile(ast.Module(body=[fixture], type_ignores=[]), '<existing synthetic fixture>', 'exec'), namespace)
    source = namespace['_source']('20261120', slot='1400', with_stage_evidence=True)
    before = deepcopy(source)
    old = original_domain.build_research_archive(source, source_input_sha256='a' * 64)
    new = domain.build_research_archive(source, source_input_sha256='a' * 64)
    assert source == before
    assert 'stage_evidence_v1' not in old
    extension = new.pop('stage_evidence_v1')
    assert new == old
    new['stage_evidence_v1'] = extension
    assert extension['items'][0]['quality_score'] == 72.5
    assert extension['items'][0]['quality_score_raw'] == '72.5'
    assert extension['items'][0]['is_new_since_last_slot'] is True
    assert extension['payload_base_sha256'] == hashlib.sha256(json.dumps(old, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
    assert contract.validate_research_archive(new) == '20261120'
    missing = deepcopy(source)
    del missing['source_manifest']['receipt_sha256']
    assert domain.build_research_archive(missing, source_input_sha256='a' * 64) == original_domain.build_research_archive(missing, source_input_sha256='a' * 64)
    invalid = deepcopy(source)
    invalid['research_items'][0]['quality_score'] = True
    try:
        domain.build_research_archive(invalid, source_input_sha256='a' * 64)
    except ValueError as error:
        assert 'quality score' in str(error)
    else:
        raise AssertionError('boolean quality must remain invalid')
    assert '_ready_empty_evidence' in vars(original_contract) and '_ready_empty_evidence' in vars(contract)
    result = {
        'valid_supplied_extension': 'PASS',
        'original_base_payload_unchanged': 'PASS',
        'source_input_unchanged': 'PASS',
        'incomplete_provenance_original_behavior': 'PASS',
        'boolean_quality_rejected': 'PASS',
        'ready_empty_validator_retained': 'PASS',
        'producer_runs': 0,
        'original_archive_writes': 0,
    }
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
