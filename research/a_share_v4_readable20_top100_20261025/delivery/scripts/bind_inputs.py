"""FAST_BIND frozen matrix response and prior benchmark inputs; never reads labels."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

TASK_ROOT = Path(__file__).resolve().parents[1]
ROOT = Path('/Users/lexi/Desktop/学习/因子工厂')
SCOPE_PATH = ROOT / 'research/a_share_v4_readable20_top100_20261025/control/ROOT_SCOPE.json'
MATRIX_PATH = ROOT / 'research/a_share_v4_stage_history_restore_20261025/post_r3/MERGED_140_MATRIX.json'
PRIOR = ROOT / 'research/a_share_v4_second_selection_top100_20261025'
RESTORE = ROOT / 'research/a_share_v4_stage_history_restore_20261025'
EXPECTED_SCOPE_SHA = '874b7655b89418627043ec516e9a99f3074e194ad97f0c97068c1a2ab8cc6840'
EXPECTED_MATRIX_SHA = '7308c2c422affd285e0a7e452ed868c182f451426cb6c2de0a7983ad84bb15a6'


def sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha_file(path: Path) -> str:
    return sha_bytes(path.read_bytes())


def load_json(path: Path) -> dict:
    return json.loads(path.read_text())


def collect() -> dict:
    static = {
        'root_scope': SCOPE_PATH,
        'matrix': MATRIX_PATH,
        'restored_final_review': RESTORE / 'control/ROOT_FINAL_READER_REVIEW_TRANSCRIPT.json',
        'restored_ui_r4_receipt': RESTORE / 'control/ROOT_UI_R4_READBACK_RECEIPT.json',
        'prior_input_binding': PRIOR / 'INPUT_BINDING.json',
        'prior_truth_projection': PRIOR / 'snapshots/truth_projection.csv',
        'prior_truth_qualification': PRIOR / 'snapshots/TRUTH_QUALIFICATION.json',
        'prior_top100_membership_cache': PRIOR / 'results/daily_top100_stage_hits.csv',
        'prior_stage_cells': PRIOR / 'results/stage_cells.csv',
        'prior_last5_detail': PRIOR / 'results/last5_selected_stocks.csv',
        'prior_output_manifest': PRIOR / 'results/OUTPUT_MANIFEST.json',
        'prior_source_manifest': PRIOR / 'SOURCE_MANIFEST.json',
        'prior_identity_anomaly_note': PRIOR / 'results/SAVED_IDENTITY_ANOMALY_NOTE.md',
        'old_audit_algorithm': Path('/Users/lexi/.codex/worktrees/a-share-second-selection-top100-20261025/v4_app/research/a_share_v4_second_selection_top100_20261025/audit.py'),
        'old_saved_input_preparer': Path('/Users/lexi/.codex/worktrees/a-share-second-selection-top100-20261025/v4_app/research/a_share_v4_second_selection_top100_20261025/prepare_saved.py'),
        'prior_r2_readback_140': RESTORE / 'post_api/READBACK_140.json',
        'r3_incremental_readback': RESTORE / 'post_r3/INCREMENTAL24_READBACK.json',
        'r3_source_manifest': RESTORE / 'post_r3/MANIFEST.json',
        'r3_api_activation_receipt': RESTORE / 'control/ROOT_API_ACTIVATION_R3.json',
    }
    missing = [f'{name}:{path}' for name, path in static.items() if not path.is_file()]
    if missing:
        raise RuntimeError('FAST_BIND_STATIC_INPUT_MISSING:' + '|'.join(missing))
    static_hashes = {name: {'path': str(path), 'sha256': sha_file(path)} for name, path in static.items()}
    if static_hashes['root_scope']['sha256'] != EXPECTED_SCOPE_SHA:
        raise RuntimeError('ROOT_SCOPE_SHA_DRIFT')
    if static_hashes['matrix']['sha256'] != EXPECTED_MATRIX_SHA:
        raise RuntimeError('MERGED_MATRIX_SHA_DRIFT')

    matrix = load_json(MATRIX_PATH)
    if matrix.get('cells') != 140 or len(matrix.get('rows', [])) != 140:
        raise RuntimeError('MATRIX_CELL_COUNT_MISMATCH')
    keys = [(r.get('trade_date'), r.get('stage_id')) for r in matrix['rows']]
    if len(set(keys)) != 140:
        raise RuntimeError('MATRIX_DATE_STAGE_KEY_DUPLICATE')
    response_refs = []
    response_paths = {}
    for row in matrix['rows']:
        if row.get('response_path'):
            ref = row['response_path']
            mode = 'R3_RESPONSE_PATH'
            expected_file_sha = row.get('response_file_sha256') or row.get('response_sha256')
        elif row.get('captured_response'):
            ref = row['captured_response']
            mode = 'R2_CAPTURED_RESPONSE_PATH'
            expected_file_sha = row.get('response_sha256')
        elif row.get('prior_readback_path'):
            ref = row['prior_readback_path']
            mode = 'R2_SHARED_READBACK_140'
            expected_file_sha = row.get('prior_readback_sha256')
        else:
            raise RuntimeError(f'RESPONSE_REFERENCE_MISSING:{row.get("trade_date")}/{row.get("stage_id")}')
        expected_response_sha = row.get('response_sha256')
        item = {
            'trade_date': row.get('trade_date'),
            'stage': row.get('stage_id'),
            'response_source': row.get('response_source'),
            'reference_mode': mode,
            'path': ref,
            'expected_file_sha256': expected_file_sha,
            'expected_response_sha256': expected_response_sha,
            'sha256': None,
            'status': 'RESPONSE_FILE_MISSING',
        }
        path = Path(ref)
        if path.is_file():
            actual = sha_file(path)
            item['sha256'] = actual
            item['status'] = 'BOUND'
            if expected_file_sha and expected_file_sha != actual:
                raise RuntimeError(f'MATRIX_RESPONSE_FILE_SHA_MISMATCH:{row.get("trade_date")}/{row.get("stage_id")}')
            response_paths[str(path)] = actual
        else:
            raise RuntimeError(f'RESPONSE_FILE_MISSING:{row.get("trade_date")}/{row.get("stage_id")}:{path}')
        response_refs.append(item)

    qualification = load_json(PRIOR / 'snapshots/TRUTH_QUALIFICATION.json')
    projection_path = PRIOR / 'snapshots/truth_projection.csv'
    if qualification.get('projection_sha256') != sha_file(projection_path):
        raise RuntimeError('PRIOR_TRUTH_PROJECTION_SHA_MISMATCH')
    output_manifest = load_json(PRIOR / 'results/OUTPUT_MANIFEST.json')
    top100_path = PRIOR / 'results/daily_top100_stage_hits.csv'
    if output_manifest.get('daily_top100_stage_hits.csv') != sha_file(top100_path):
        raise RuntimeError('PRIOR_TOP100_CACHE_SHA_MISMATCH')

    review = load_json(RESTORE / 'control/ROOT_FINAL_READER_REVIEW_TRANSCRIPT.json')
    ui = load_json(RESTORE / 'control/ROOT_UI_R4_READBACK_RECEIPT.json')
    if review.get('verdict') != 'REVIEWED_PASS' or review.get('pass_signal') != 'PASS_V4_20SESSION_A_SHARE_HISTORY_READABLE_WITH_134_RETAINED_AND_6_EXPLICIT_GAPS':
        raise RuntimeError('RESTORED_FINAL_REVIEW_NOT_PASS')
    if review.get('ui_receipt_sha256') != static_hashes['restored_ui_r4_receipt']['sha256']:
        raise RuntimeError('RESTORED_UI_RECEIPT_SHA_MISMATCH')
    if ui.get('retained_selection_cells') != 134 or ui.get('genuine_unknown_cells') != 6:
        raise RuntimeError('R4_UI_RECEIPT_SCOPE_MISMATCH')

    identity = {
        'schema': 'A_SHARE_V4_READABLE20_TOP100_INPUT_BINDING_V1',
        'route_id': 'A_SHARE_V4_READABLE20_TOP100_20261025',
        'binding_type': 'FAST_BIND_REUSE_PRIOR_134_A_IDENTITY_AND_648_PRESERVATION_PASS',
        'label_data_read': False,
        'source_data_read': 'ONLY_MATRIX_AND_RESPONSE_FILE_IDENTITIES;NO_ROW_LABELS_OR_RETURNS_READ',
        'static_inputs': static_hashes,
        'matrix_response_files': response_refs,
        'matrix_cells': 140,
        'unique_response_files': len(response_paths),
        'response_file_identities': [
            {'path': path, 'sha256': digest} for path, digest in sorted(response_paths.items())
        ],
        'prior_selection_identity_reuse': {
            'retained_lists': 134,
            'genuine_missing_cells': 6,
            'source': str(RESTORE / 'control/ROOT_FINAL_READER_REVIEW_TRANSCRIPT.json'),
            'r4_readback_source': str(RESTORE / 'control/ROOT_UI_R4_READBACK_RECEIPT.json'),
            'selection_store_trios': 'REUSED_FROM_ACCEPTED_134_A_IDENTITY_PASS_NOT_REHASHED',
            'current_selection_latest_index': 'NOT_REBOUND_OR_REHASHED',
        },
        'benchmark_reuse': {
            'truth_projection_path': str(projection_path),
            'truth_projection_sha256': sha_file(projection_path),
            'top100_cache_path': str(top100_path),
            'top100_cache_sha256': sha_file(top100_path),
            'qualification_path': str(PRIOR / 'snapshots/TRUTH_QUALIFICATION.json'),
            'qualified_label': qualification.get('label'),
            'return_formula': qualification.get('return_formula'),
            'full_A_membership_certified': qualification.get('full_A_membership_certified'),
            'historical_PIT': qualification.get('historical_PIT'),
        },
        'safety': {
            'research_only': True,
            'production_allowed': False,
            'buy_gate_updated': False,
            'orders_sent': False,
        },
    }
    raw = (json.dumps(identity, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode('utf-8')
    out = TASK_ROOT / 'INPUT_BINDING.json'
    out.write_bytes(raw)
    receipt = {
        'schema': 'A_SHARE_V4_READABLE20_TOP100_FAST_BIND_RECEIPT_V1',
        'input_binding_path': str(out),
        'input_binding_sha256': sha_bytes(raw),
        'root_scope_sha256': static_hashes['root_scope']['sha256'],
        'matrix_sha256': static_hashes['matrix']['sha256'],
        'matrix_cells': 140,
        'response_cells_bound': sum(x['status'] == 'BOUND' for x in response_refs),
        'unique_response_files_bound': len(response_paths),
        'response_files_missing': sum(x['status'] == 'RESPONSE_FILE_MISSING' for x in response_refs),
        'prior_truth_projection_sha256': identity['benchmark_reuse']['truth_projection_sha256'],
        'prior_top100_cache_sha256': identity['benchmark_reuse']['top100_cache_sha256'],
        'prior_selection_identity_reuse': 'PASS_REUSED_134_A_IDENTITY_AND_648_PRESERVATION;TRIOS_NOT_REHASHED',
        'label_data_read': False,
        'next_gate': 'LINEAGE_FAST_BIND_REVIEW_THEN_CANARY_LABEL_READ',
        'safety': identity['safety'],
    }
    receipt_path = TASK_ROOT / 'FAST_BIND_RECEIPT.json'
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n')
    return receipt


if __name__ == '__main__':
    print(json.dumps(collect(), ensure_ascii=False, sort_keys=True))
