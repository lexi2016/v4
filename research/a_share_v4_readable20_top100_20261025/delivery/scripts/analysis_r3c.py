"""Deterministic descriptive Top100 accounting for the frozen V4 A-share lists."""
from __future__ import annotations

import csv
import pandas as pd
import hashlib
import json
import math
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TASK_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = TASK_ROOT / 'scripts'
CONFIG_PATH = TASK_ROOT / 'contracts/CONFIG_R3C.json'
BINDING_PATH = TASK_ROOT / 'INPUT_BINDING.json'
CONTRACT_PATH = TASK_ROOT / 'CONTRACT_R3C.json'
FREEZE_RECEIPT_PATH = TASK_ROOT / 'FREEZE_RECEIPT_R3C.json'
LINEAGE_RECEIPT_PATH = TASK_ROOT / 'receipts/LINEAGE_FAST_BIND_VERDICT.json'
OUTPUT_FILES = [
    'daily_stage_metrics.csv',
    'daily_unique_summary.csv',
    'stage_summary.csv',
    'cell_source_provenance.csv',
    'source_pit_pending.csv',
    'source_gaps.csv',
    'unknown_labels.csv',
    'stock_stage_detail.csv',
    'READABLE_20X7.md',
    'STOCK_STAGE_DETAIL.md',
    'RUN_RESULT.json',
    'OUTPUT_MANIFEST.json',
]
SAFETY = {
    'research_only': True,
    'production_allowed': False,
    'buy_gate_updated': False,
    'orders_sent': False,
}
EXCHANGE_CODE = re.compile(r'^(?:(SH|SZ|BJ)\.(\d{6})|(\d{6})\.(SH|SZ|BJ))$', re.I)
CODE_FIELDS = ('ts_code', 'symbol', 'security_code', 'code', 'stock_code')
NAME_FIELDS = ('name', 'stock_name', 'display_name', 'security_name', 'instrument_name')
RANK_FIELDS = ('rank', 'selected_rank', 'order', 'acquisition_rank')


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode('utf-8')


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha_file(path: Path) -> str:
    return sha_bytes(path.read_bytes())


def read_json(path: Path) -> Any:
    return json.loads(path.read_text())


def write_json_new(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as f:
        f.write(json_bytes(value))


def csv_value(value: Any) -> Any:
    if value is None:
        return 'null'
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, float):
        if not math.isfinite(value):
            return 'null'
        return format(value, '.10f').rstrip('0').rstrip('.')
    return value


def write_csv_new(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore', lineterminator='\n')
        writer.writeheader()
        for row in rows:
            writer.writerow({key: csv_value(row.get(key)) for key in fields})


def explicit_ts_code(value: Any) -> str | None:
    """Canonicalize only a code with an explicit venue; never infer venue from digits."""
    if value is None:
        return None
    text = str(value).strip().upper()
    match = EXCHANGE_CODE.fullmatch(text)
    if not match:
        return None
    if match.group(1):
        return f'{match.group(2)}.{match.group(1)}'
    return f'{match.group(3)}.{match.group(4)}'


def row_identity(row: dict | None) -> tuple[str | None, str | None]:
    if not isinstance(row, dict):
        return None, None
    raw = None
    explicit = None
    for field in CODE_FIELDS:
        value = row.get(field)
        if value is None or str(value).strip() == '':
            continue
        if raw is None:
            raw = str(value).strip()
        explicit = explicit_ts_code(value)
        if explicit:
            raw = str(value).strip()
            break
    return raw, explicit


def identity_from_sources(raw_code: str | None, explicit_source: str | None,
                          matrix_code: str | None, store_link_verified: bool,
                          direct_response: bool, qualified_keys=None,
                          conflict_keys=()) -> tuple[str | None, str, str | None]:
    """Join identifiers only: no leading-digit rule and no return/rank selection."""
    matrix_explicit = explicit_ts_code(matrix_code)
    authority = defaultdict(set)
    for key in qualified_keys or ():
        explicit = explicit_ts_code(key)
        if explicit:
            authority[explicit[:6]].add(explicit)
    def digits(value):
        explicit = explicit_ts_code(value)
        if explicit:
            return explicit[:6]
        match = re.fullmatch(r'A\.(\d{6})', str(value or '').strip().upper())
        return match.group(1) if match else None
    raw_digits, matrix_digits = digits(raw_code), digits(matrix_code)
    if raw_digits and matrix_digits and raw_digits != matrix_digits:
        return None, 'IDENTITY_CONFLICT', 'SOURCE_RESPONSE_MATRIX_CODE_MISMATCH'
    if explicit_source and matrix_explicit and explicit_source != matrix_explicit:
        return None, 'IDENTITY_CONFLICT', 'SOURCE_RESPONSE_MATRIX_CODE_MISMATCH'
    explicit = explicit_source or (matrix_explicit if store_link_verified else None)
    if explicit:
        peers = authority.get(explicit[:6], set())
        if qualified_keys is not None and peers and explicit not in peers:
            return None, 'IDENTITY_CONFLICT', 'EXPLICIT_VENUE_CONFLICT_WITH_QUALIFIED_AUTHORITY_KEY'
        basis = 'EXPLICIT_SOURCE_VENUE' if explicit_source else ('ACCEPTED_R4_MATRIX_STORE_BINDING' if not direct_response else 'ACCEPTED_R4_BINDING_FOR_BARE_RESPONSE_CODE')
        return explicit, basis, None
    if qualified_keys is not None and raw_digits:
        if raw_digits in {str(key).split('.')[0] for key in conflict_keys}:
            return None, 'PRESERVED_PRIOR_IDENTITY_CONFLICT', 'SECURITY_TYPE_OR_MARKET_CODE_IDENTITY_CONFLICT'
        if not store_link_verified:
            return None, 'VENUE_NOT_BOUND', 'ORIGINAL_RUN_STORE_BINDING_NOT_CONFIRMED'
        matches = authority.get(raw_digits, set())
        if len(matches) == 1:
            return next(iter(matches)), 'EXACT_DATE_UNIQUE_QUALIFIED_PANEL_TS_CODE_KEY', None
        return None, 'QUALIFIED_AUTHORITY_KEY_NOT_UNIQUE', ('NO_QUALIFIED_AUTHORITY_IDENTITY_KEY' if not matches else 'AMBIGUOUS_QUALIFIED_AUTHORITY_IDENTITY_KEY')
    if raw_code:
        return None, 'VENUE_NOT_BOUND', 'SOURCE_CODE_HAS_NO_EXPLICIT_VENUE'
    return None, 'IDENTITY_NOT_READABLE', 'NO_SOURCE_CODE_OR_EXPLICIT_STORE_BINDING'


def metric_counts(observations: list[dict] | None) -> dict:
    if observations is None:
        return {
            'selection_count_n': None,
            'known_label_count_k': None,
            'confirmed_reference_hits_h': None,
            'unknown_count_u': None,
            'qualified_misses_k_minus_h': None,
            'known_label_hit_rate_h_over_k': None,
            'all_selection_hit_rate_h_over_n': None,
            'observed_reference_match_fraction_h_over_n': None,
        }
    n = len(observations)
    known = [row for row in observations if row['hit_state'] in {'HIT', 'MISS'}]
    h = sum(row['hit_state'] == 'HIT' for row in known)
    k = len(known)
    u = n - k
    return {
        'selection_count_n': n,
        'known_label_count_k': k,
        'confirmed_reference_hits_h': h,
        'unknown_count_u': u,
        'qualified_misses_k_minus_h': k - h,
        'known_label_hit_rate_h_over_k': h / k if k else None,
        'all_selection_hit_rate_h_over_n': h / n if n and u == 0 else None,
        'observed_reference_match_fraction_h_over_n': h / n if n else None,
    }


def rank_projection(rows: list[dict]) -> list[dict]:
    """Apply the frozen return formula and strict return-desc/code-asc daily ordering."""
    valid = []
    for source in rows:
        try:
            close = float(source['close'])
            previous = float(source['pre_close'])
        except (KeyError, TypeError, ValueError):
            continue
        if close <= 0 or previous <= 0:
            continue
        return_pct = (close / previous - 1.0) * 100.0
        code = str(source['ts_code']).strip().upper()
        if not math.isfinite(return_pct) or not explicit_ts_code(code):
            continue
        valid.append({**source, 'ts_code': code, 'return_pct': return_pct})
    valid.sort(key=lambda row: (-row['return_pct'], row['ts_code']))
    for rank, row in enumerate(valid, start=1):
        row['daily_rank'] = rank
    return valid


def _field_value(row: dict, candidates: tuple[str, ...]) -> Any:
    for field in candidates:
        value = row.get(field)
        if value is not None and str(value).strip() != '':
            return value
    return None


def parse_gap_key(value: Any, dates: list[str], stages: list[str]) -> tuple[str, str] | None:
    if isinstance(value, dict):
        date = str(value.get('trade_date') or value.get('date') or '')
        stage = str(value.get('stage_id') or value.get('stage') or '')
        if date in dates and stage in stages:
            return date, stage
    if not isinstance(value, str):
        return None
    date_match = re.search(r'20\d{6}', value)
    stage_match = next((stage for stage in stages if stage in value), None)
    if date_match and stage_match:
        key = date_match.group(0), stage_match
        return key if key[0] in dates else None
    return None


def response_file_for_cell(cell: dict) -> tuple[Path | None, str]:
    if cell.get('response_path'):
        return Path(cell['response_path']), 'R3_RESPONSE_PATH'
    if cell.get('captured_response'):
        return Path(cell['captured_response']), 'R2_CAPTURED_RESPONSE_PATH'
    if cell.get('prior_readback_path'):
        return Path(cell['prior_readback_path']), 'R2_SHARED_READBACK_140'
    return None, 'NO_RESPONSE_REFERENCE'


def frozen_code_entries() -> dict:
    paths = [
        SCRIPTS / 'analysis_r3c.py',
        SCRIPTS / 'bind_inputs.py',
        SCRIPTS / 'register_event_r3.py',
    ]
    return {str(path): sha_file(path) for path in paths}


def freeze_contract() -> dict:
    config = read_json(CONFIG_PATH)
    binding = read_json(BINDING_PATH)
    bind_receipt = read_json(TASK_ROOT / 'FAST_BIND_RECEIPT.json')
    binding_sha = sha_file(BINDING_PATH)
    if bind_receipt.get('input_binding_sha256') != binding_sha:
        raise RuntimeError('FAST_BIND_RECEIPT_SHA_MISMATCH')
    if binding.get('label_data_read') is not False:
        raise RuntimeError('INPUT_BINDING_LABEL_ACCESS_NOT_CLOSED')
    code_files = frozen_code_entries()
    test_path = TASK_ROOT / 'tests/test_parser_reuse_r3c.py'
    if not test_path.is_file():
        raise RuntimeError('FOCUSED_TEST_SOURCE_MISSING')
    test_sha = sha_file(test_path)
    config_sha = sha_file(CONFIG_PATH)
    code_sha = sha_bytes(canonical_bytes(code_files))
    now = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    execution_id = f'{config["route_id"]}_CALC_{now}'
    contract = {
        'schema': 'A_SHARE_V4_READABLE20_TOP100_FROZEN_CONTRACT_V1',
        'route_id': config['route_id'],
        'execution_id': execution_id,
        'goal': config['goal'],
        'baseline_id': config['baseline_id'],
        'one_variable': config['one_variable'],
        'root_scope_path': config['root_scope_path'],
        'root_scope_sha256': config['root_scope_sha256'],
        'input_binding_path': str(BINDING_PATH),
        'input_sha256': binding_sha,
        'input_sha256_reason': None,
        'code_files': code_files,
        'code_sha256': code_sha,
        'code_sha256_reason': None,
        'test_path': str(test_path),
        'test_code_sha256': test_sha,
        'config_path': str(CONFIG_PATH),
        'config_sha256': config_sha,
        'config_sha256_reason': None,
        'signal_date_range': [config['dates'][0], config['dates'][-1]],
        'target_date_range': [config['dates'][0], config['dates'][-1]],
        'dates': config['dates'],
        'stages': config['stages'],
        'last5_dates': config['last5_dates'],
        'canary_dates': config['canary_dates'],
        'benchmark': config['benchmark'],
        'metrics': config['metrics'],
        'expected_scope': config['expected_scope'],
        'canary_acceptance': config['canary_acceptance'],
        'pass_signal': 'INDEPENDENT_PASS_20DATES_140CELLS_134LISTS_6NULLGAPS_DAILY_STAGE_COUNTS_AND_RATES_LAST5_ALLROWS_TRACEABLE_UNKNOWN_DENOM',
        'stop_rule': 'Stop on input/run/hash/key/benchmark conflict; preserve unknown labels and gaps; no 194 rerun, no source collection, no benchmark tuning.',
        'truth_access': 'NOT_READ_AT_FREEZE',
        'sealed_status': 'NO_NEW_SEALED_DATA_DESCRIPTIVE_ONLY',
        'runtime': config['runtime'],
        'device': 'MAC_LOCAL_CPU',
        'writer': '/root/second_selection_writer',
        'writer_transfer_go_path': config['writer_transfer_go_path'],
        'writer_transfer_go_sha256': config['writer_transfer_go_sha256'],
        'identity_join_policy': config['identity_join'],
        'reviewer': config['review']['independent_statistics_reviewer'],
        'lineage_reviewer': config['review']['lineage_reviewer'],
        'safety': config['safety'],
    }
    write_json_new(CONTRACT_PATH, contract)
    freeze_receipt = {
        'schema': 'A_SHARE_V4_READABLE20_TOP100_FREEZE_RECEIPT_V1',
        'contract_path': str(CONTRACT_PATH),
        'contract_sha256': sha_file(CONTRACT_PATH),
        'execution_id': execution_id,
        'input_sha256': binding_sha,
        'code_sha256': code_sha,
        'config_sha256': config_sha,
        'test_code_sha256': test_sha,
        'code_files': code_files,
        'frozen_before_label_read': True,
        'runtime': config['runtime'],
        'safety': SAFETY,
    }
    write_json_new(FREEZE_RECEIPT_PATH, freeze_receipt)
    return freeze_receipt


def load_frozen() -> tuple[dict, dict, dict]:
    contract = read_json(CONTRACT_PATH)
    config = read_json(CONFIG_PATH)
    binding = read_json(BINDING_PATH)
    if sha_file(BINDING_PATH) != contract['input_sha256']:
        raise RuntimeError('INPUT_BINDING_SHA_DRIFT')
    if sha_file(CONFIG_PATH) != contract['config_sha256']:
        raise RuntimeError('CONFIG_SHA_DRIFT')
    if sha_file(TASK_ROOT / 'tests/test_parser_reuse_r3c.py') != contract['test_code_sha256']:
        raise RuntimeError('TEST_SOURCE_SHA_DRIFT')
    current_code = frozen_code_entries()
    if current_code != contract['code_files'] or sha_bytes(canonical_bytes(current_code)) != contract['code_sha256']:
        raise RuntimeError('CODE_SHA_DRIFT')
    for item in binding['static_inputs'].values():
        path = Path(item['path'])
        if not path.is_file() or sha_file(path) != item['sha256']:
            raise RuntimeError(f'FROZEN_STATIC_INPUT_DRIFT:{path}')
    for item in binding['response_file_identities']:
        path = Path(item['path'])
        if not path.is_file() or sha_file(path) != item['sha256']:
            raise RuntimeError(f'FROZEN_RESPONSE_FILE_DRIFT:{path}')
    return contract, config, binding


def require_lineage_pass(binding: dict) -> dict:
    if not LINEAGE_RECEIPT_PATH.is_file():
        raise RuntimeError('LINEAGE_FAST_BIND_NOT_RELAYED')
    receipt = read_json(LINEAGE_RECEIPT_PATH)
    if receipt.get('input_binding_sha256') != sha_file(BINDING_PATH):
        raise RuntimeError('LINEAGE_REVIEW_INPUT_SHA_MISMATCH')
    if receipt.get('verdict') not in {'PASS', 'REVIEWED_PASS', 'PASS_FAST_BIND'}:
        raise RuntimeError('LINEAGE_FAST_BIND_NOT_PASS')
    return receipt


def load_truth(config: dict, scope_dates: list[str]) -> tuple[dict, dict, dict, dict]:
    if any(date not in config['dates'] for date in scope_dates):
        raise RuntimeError('TRUTH_SCOPE_OUTSIDE_FROZEN_DATES')
    scope = set(scope_dates)
    projection_path = Path(config['prior_truth_projection'])
    qualification = read_json(Path(config['prior_truth_qualification']))
    excluded = set(qualification.get('excluded_legacy_codes', []))
    projection: dict[str, list[dict]] = defaultdict(list)
    # Match the already accepted audit's pd.read_csv numeric parser exactly.
    # Python float(decimal text) differs at some 1-ULP near-ties; do not retune ranks.
    frame = pd.read_csv(projection_path, dtype={'trade_date': str, 'ts_code': str})
    for row in frame[frame.trade_date.isin(scope)].to_dict('records'):
        projection[str(row['trade_date'])].append(row)

    ranks: dict[str, dict[str, dict]] = {}
    for date in scope_dates:
        ranked = rank_projection(projection.get(date, []))
        day_map = {}
        for row in ranked:
            code = row['ts_code']
            if code in day_map:
                raise RuntimeError(f'DUPLICATE_QUALIFIED_TRUTH_KEY:{date}/{code}')
            day_map[code] = row
        ranks[date] = day_map

    top100_cache: dict[str, dict[str, int]] = defaultdict(dict)
    with Path(config['prior_top100_cache']).open(newline='', encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            date = str(row.get('trade_date') or '').strip()
            if date not in scope:
                continue
            code = str(row.get('ts_code') or '').strip().upper()
            try:
                rank = int(float(row['daily_rank']))
            except (KeyError, TypeError, ValueError):
                raise RuntimeError(f'TOP100_CACHE_RANK_INVALID:{date}/{code}')
            if code in top100_cache[date]:
                raise RuntimeError(f'DUPLICATE_TOP100_CACHE_KEY:{date}/{code}')
            if rank < 1 or rank > 100 or not explicit_ts_code(code):
                raise RuntimeError(f'TOP100_CACHE_ROW_INVALID:{date}/{code}/{rank}')
            top100_cache[date][code] = rank

    parity = {}
    for date in scope_dates:
        cached = top100_cache.get(date, {})
        ranks_for_date = ranks.get(date, {})
        expected = {code: row['daily_rank'] for code, row in ranks_for_date.items() if row['daily_rank'] <= 100}
        if len(cached) != 100 or sorted(cached.values()) != list(range(1, 101)):
            raise RuntimeError(f'TOP100_CACHE_NOT_STRICT100:{date}:{len(cached)}')
        if expected != cached:
            raise RuntimeError(f'TOP100_CACHE_PROJECTION_PARITY_FAIL:{date}')
        parity[date] = {'cached_rows': len(cached), 'strict_rank_parity': True}
    return ranks, top100_cache, excluded, parity


def response_rows(response: dict) -> tuple[list[dict], dict]:
    selection = response.get('selection_markets')
    if not isinstance(selection, dict) or not isinstance(selection.get('A_SHARE'), dict):
        raise RuntimeError('SOURCE_RESPONSE_A_SHARE_MISSING')
    a_share = selection['A_SHARE']
    rows = a_share.get('rows')
    if rows is None:
        rows = []
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise RuntimeError('SOURCE_RESPONSE_A_SHARE_ROWS_INVALID')
    return rows, a_share


def load_source_rows(cell: dict) -> tuple[list[dict] | None, dict, Path | None, str]:
    path, mode = response_file_for_cell(cell)
    a_share_meta = {
        'response_status': None,
        'response_selection_status': None,
        'response_source_status': None,
        'response_run_id': None,
        'response_rows_available': None,
    }
    if path is None:
        return None, a_share_meta, None, mode
    if mode == 'R2_SHARED_READBACK_140':
        return None, a_share_meta, path, mode
    response = read_json(path)
    rows, a_share = response_rows(response)
    a_share_meta.update({
        'response_status': a_share.get('status') or response.get('status'),
        'response_selection_status': a_share.get('selection_status'),
        'response_source_status': a_share.get('source_status'),
        'response_run_id': a_share.get('run_id') or response.get('run_id'),
        'response_rows_available': len(rows),
    })
    return rows, a_share_meta, path, mode


def build_gap_map(matrix: dict, config: dict) -> dict[tuple[str, str], str]:
    gaps = {}
    for value in matrix.get('unresolved_cells', []):
        key = parse_gap_key(value, config['dates'], config['stages'])
        if key:
            gaps[key] = str(value)
    return gaps


def stock_name(row: dict | None) -> str | None:
    value = _field_value(row or {}, NAME_FIELDS)
    return str(value).strip() if value is not None else None


def source_rank(row: dict | None, order_index: int) -> tuple[int, str]:
    value = _field_value(row or {}, RANK_FIELDS)
    if value is not None:
        try:
            number = int(float(value))
            if number > 0:
                return number, 'SOURCE_RESPONSE_RANK'
        except (TypeError, ValueError):
            pass
    return order_index, 'PRESERVED_SOURCE_ORDER_INDEX'


def build_cell_source(cell: dict, response_meta: dict, response_path: Path | None,
                      response_mode: str, binding_by_date_stage: dict) -> dict:
    key = (str(cell['trade_date']), str(cell['stage_id']))
    bound = binding_by_date_stage.get(key, {})
    return {
        'trade_date': key[0],
        'stage': key[1],
        'cell_state': 'CANNOT_CONFIRM_GAP' if cell.get('A_numeric_readable') is False else 'RETAINED_OR_READABLE',
        'source_mode': cell.get('response_source'),
        'source_reference_mode': response_mode,
        'source_response_path': str(response_path) if response_path else None,
        'source_response_file_sha256': bound.get('sha256'),
        'source_response_sha256': cell.get('response_sha256'),
        'matrix_response_file_sha256': cell.get('response_file_sha256'),
        'source_status': response_meta.get('response_source_status') or cell.get('A_source_status'),
        'selection_status': response_meta.get('response_selection_status') or cell.get('A_selection_status'),
        'response_status': response_meta.get('response_status') or cell.get('A_status'),
        'response_run_id': response_meta.get('response_run_id'),
        'original_run_id': cell.get('A_run_id'),
        'run_id_match_in_r4_binding': cell.get('original_saved_binding_run_match'),
        'trio_verified_in_r4_binding': cell.get('A_trio_verified'),
        'accepted_store_link': accepted_store_link(cell),
        'store_link_basis': ('ACCEPTED_R2_SHARED_TRIO_METADATA_FAST_BIND' if cell.get('original_saved_binding_run_match') is None and accepted_store_link(cell) else 'EXPLICIT_RUN_MATCH_OR_UNCONFIRMED'),
        'source_qualification': cell.get('source_quality_qualification'),
        'source_cannot_confirm_reasons': '|'.join(map(str, cell.get('A_cannot_confirm') or [])) or None,
        'historical_pit_status': 'CANNOT_CONFIRM_HISTORICAL_PIT',
        'historical_name_status': 'CANNOT_CONFIRM_HISTORICAL_NAME_BINDING',
    }


def accepted_store_link(cell: dict) -> bool:
    """Reuse accepted FAST_BIND metadata; the extra run-match flag is backfill-only."""
    if cell.get('A_trio_verified') is not True:
        return False
    match = cell.get('original_saved_binding_run_match')
    if match is not None:
        return match is True
    return (cell.get('response_source') == 'REUSED_PINNED_R2_POST140'
            and bool(cell.get('A_run_id')) and bool(cell.get('response_sha256'))
            and (cell.get('cell_runtime_identity') or {}).get('release')
            == 'a-share-stage-history-restore-20261025-r2')


def build_selected_rows(cell: dict, source_rows: list[dict] | None,
                        source_meta: dict, date_truth: dict,
                        top100_members: dict[str, int], excluded_codes: set[str],
                        config: dict) -> list[dict]:
    date = str(cell['trade_date'])
    stage = str(cell['stage_id'])
    matrix_codes = cell.get('A_codes') or []
    if not isinstance(matrix_codes, list):
        raise RuntimeError(f'MATRIX_A_CODES_NOT_LIST:{date}/{stage}')
    count_field = cell.get('A_selected_rows')
    if count_field is not None and int(count_field) != len(matrix_codes):
        raise RuntimeError(f'MATRIX_A_CODE_COUNT_MISMATCH:{date}/{stage}')
    if source_rows is not None and len(source_rows) != len(matrix_codes):
        raise RuntimeError(f'RESPONSE_MATRIX_ROW_COUNT_MISMATCH:{date}/{stage}')
    response_run_id = source_meta.get('response_run_id')
    if response_run_id and cell.get('A_run_id') and response_run_id != cell.get('A_run_id'):
        raise RuntimeError(f'SOURCE_RESPONSE_RUN_ID_MISMATCH:{date}/{stage}')
    if count_field is not None and source_meta.get('response_rows_available') is not None:
        if int(count_field) != int(source_meta['response_rows_available']):
            raise RuntimeError(f'RESPONSE_MATRIX_SELECTED_COUNT_MISMATCH:{date}/{stage}')
    if len(matrix_codes) == 0:
        return []

    store_link_verified = accepted_store_link(cell)
    observations = []
    for index, matrix_code_value in enumerate(matrix_codes, start=1):
        matrix_code = str(matrix_code_value).strip() if matrix_code_value is not None else None
        source_row = source_rows[index - 1] if source_rows is not None else None
        raw_code, explicit_source = row_identity(source_row)
        if raw_code is None:
            raw_code = matrix_code
        resolved, identity_basis, identity_reason = identity_from_sources(
            raw_code,
            explicit_source,
            matrix_code,
            store_link_verified,
            source_rows is not None,
            qualified_keys=date_truth.keys(),
            conflict_keys=config['known_identity_conflict_codes'],
        )
        matrix_explicit = explicit_ts_code(matrix_code)
        if source_rows is None and matrix_explicit and store_link_verified and not identity_reason:
            resolved = matrix_explicit
            identity_basis = 'ACCEPTED_R4_MATRIX_STORE_BINDING'
            identity_reason = None
        if resolved and resolved in config['known_identity_conflict_codes']:
            hit_state = 'UNKNOWN'
            unknown_reason = 'SECURITY_TYPE_OR_MARKET_CODE_IDENTITY_CONFLICT'
        elif identity_reason == 'SOURCE_RESPONSE_MATRIX_CODE_MISMATCH' or not resolved:
            hit_state = 'UNKNOWN'
            unknown_reason = identity_reason or 'IDENTITY_NOT_BOUND'
        elif not store_link_verified:
            hit_state = 'UNKNOWN'
            unknown_reason = 'ORIGINAL_RUN_STORE_BINDING_NOT_CONFIRMED'
        elif resolved in excluded_codes:
            hit_state = 'UNKNOWN'
            unknown_reason = 'SECURITY_IDENTITY_EXCLUDED_FROM_QUALIFIED_PANEL'
        elif resolved not in date_truth:
            hit_state = 'UNKNOWN'
            unknown_reason = 'NO_QUALIFIED_SAME_DAY_RETURN_IN_PANEL'
        elif resolved in top100_members:
            hit_state = 'HIT'
            unknown_reason = None
        else:
            hit_state = 'MISS'
            unknown_reason = None

        truth = date_truth.get(resolved) if resolved and hit_state in {'HIT', 'MISS'} else None
        name = stock_name(source_row)
        name_basis = 'CAPTURED_SOURCE_RESPONSE_DISPLAY_NAME' if name else None
        if name is None and truth:
            name = truth.get('name')
            if name:
                name_basis = 'QUALIFIED_CURRENT_PANEL_DISPLAY_NAME'
        rank, rank_basis = source_rank(source_row, index)
        if source_rows is None:
            rank, rank_basis = index, 'PRESERVED_MATRIX_SOURCE_ORDER'
        observations.append({
            'trade_date': date,
            'stage': stage,
            'selected_rank': rank,
            'source_order_index': index,
            'rank_basis': rank_basis,
            'raw_code': raw_code,
            'matrix_code': matrix_code,
            'display_code': resolved or raw_code or matrix_code,
            'resolved_ts_code': resolved,
            'identity_basis': identity_basis,
            'identity_reason': identity_reason,
            'resolve_provenance': json.dumps({'policy': identity_basis, 'exact_trade_date': date, 'authority_key': resolved, 'authority_path': config['prior_truth_projection'], 'values_or_ranks_used_for_identity': False}, sort_keys=True),
            'name': name,
            'name_basis': name_basis,
            'name_historical_qualification': 'CANNOT_CONFIRM_HISTORICAL_NAME_BINDING',
            'daily_return_pct': truth.get('return_pct') if truth else None,
            'daily_rank': truth.get('daily_rank') if truth else None,
            'hit_state': hit_state,
            'label_status': 'QUALIFIED_CURRENT_PANEL_LABEL' if hit_state in {'HIT', 'MISS'} else 'CANNOT_CONFIRM_RESULT_LABEL',
            'unknown_reason': unknown_reason,
            'source_status': source_meta.get('response_source_status') or cell.get('A_source_status'),
            'selection_status': source_meta.get('response_selection_status') or cell.get('A_selection_status'),
            'response_status': source_meta.get('response_status') or cell.get('A_status'),
            'source_run_id': cell.get('A_run_id'),
            'source_qualification': cell.get('source_quality_qualification'),
            'source_response_sha256': cell.get('response_sha256'),
            'historical_pit_status': 'CANNOT_CONFIRM_HISTORICAL_PIT',
        })
    return observations


def read_previous_names(config: dict) -> dict[tuple[str, str, int, str], str]:
    result = {}
    with Path(config['prior_last5_names']).open(newline='', encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            if not row.get('trade_date') or not row.get('stage') or not row.get('selected_rank') or not row.get('ts_code') or not row.get('name'):
                continue
            code = explicit_ts_code(row['ts_code'])
            if not code:
                continue
            try:
                rank = int(float(row['selected_rank']))
            except (TypeError, ValueError):
                continue
            result[(str(row['trade_date']), str(row['stage']), rank, code)] = str(row['name'])
    return result


def enrich_names(observations: list[dict], previous_names: dict) -> None:
    for row in observations:
        if row.get('name') or not row.get('resolved_ts_code'):
            continue
        key = (row['trade_date'], row['stage'], row['selected_rank'], row['resolved_ts_code'])
        name = previous_names.get(key)
        if name:
            row['name'] = name
            row['name_basis'] = 'PRIOR_READABLE_RESULT_DISPLAY_NAME'


def evaluate_dates(dates: list[str], config: dict, binding: dict) -> dict:
    matrix = read_json(Path(config['matrix_path']))
    matrix_rows = {(str(r['trade_date']), str(r['stage_id'])): r for r in matrix['rows']}
    if len(matrix_rows) != 140:
        raise RuntimeError('MATRIX_KEY_COUNT_MISMATCH')
    bound_responses = {str(r['path']): r for r in binding['response_file_identities']}
    bound_by_date_stage = {
        (str(r['trade_date']), str(r['stage'])): r for r in binding['matrix_response_files']
    }
    gap_map = build_gap_map(matrix, config)
    ranks, top100, excluded, parity = load_truth(config, dates)
    prev_names = read_previous_names(config)
    all_cells = []
    all_sources = []
    all_gaps = []
    all_observations = []
    all_unknown = []
    for date in dates:
        date_truth = ranks[date]
        top100_members = top100[date]
        for stage in config['stages']:
            key = (date, stage)
            cell = matrix_rows.get(key)
            if cell is None:
                raise RuntimeError(f'MATRIX_CELL_MISSING:{date}/{stage}')
            source_rows, response_meta, response_path, response_mode = load_source_rows(cell)
            bound_ref = bound_by_date_stage.get(key, {})
            source = build_cell_source(cell, response_meta, response_path, response_mode, bound_by_date_stage)
            source['source_response_file_sha256'] = bound_ref.get('sha256')
            source['source_response_reference_mode'] = response_mode
            all_sources.append(source)
            is_gap = key in gap_map
            if is_gap:
                reasons = cell.get('A_cannot_confirm') or []
                gap = {
                    'trade_date': date,
                    'stage': stage,
                    'cell_status': 'CANNOT_CONFIRM_GAP',
                    **metric_counts(None),
                    'gap_reason': '|'.join(map(str, reasons)) or gap_map[key],
                    'source_status': source['source_status'],
                    'selection_status': source['selection_status'],
                    'response_status': source['response_status'],
                    'source_mode': source['source_mode'],
                    'source_run_id': source['original_run_id'],
                    'source_response_path': source['source_response_path'],
                    'source_response_sha256': source['source_response_sha256'],
                    'source_qualification': source['source_qualification'],
                    'historical_pit_status': 'CANNOT_CONFIRM_HISTORICAL_PIT',
                }
                all_gaps.append(gap)
                observations = None
            else:
                observations = build_selected_rows(
                    cell, source_rows, response_meta, date_truth, top100_members, excluded, config
                )
                enrich_names(observations, prev_names)
                all_observations.extend(observations)
                all_unknown.extend(row for row in observations if row['hit_state'] == 'UNKNOWN')
                metrics = metric_counts(observations)
                gap = None

            cell_metrics = metric_counts(observations)
            all_cells.append({
                'trade_date': date,
                'stage': stage,
                'cell_status': 'CANNOT_CONFIRM_GAP' if is_gap else 'RETAINED_LIST',
                **cell_metrics,
                'source_status': source['source_status'],
                'selection_status': source['selection_status'],
                'response_status': source['response_status'],
                'source_mode': source['source_mode'],
                'source_run_id': source['original_run_id'],
                'source_response_sha256': source['source_response_sha256'],
                'source_qualification': source['source_qualification'],
                'unknown_reason_counts': '|'.join(f'{k}:{v}' for k, v in sorted(Counter(r['unknown_reason'] for r in (observations or []) if r['hit_state'] == 'UNKNOWN').items())) or None,
                'historical_pit_status': 'CANNOT_CONFIRM_HISTORICAL_PIT',
            })

    return {
        'dates': dates,
        'cells': all_cells,
        'sources': all_sources,
        'gaps': all_gaps,
        'observations': all_observations,
        'unknowns': all_unknown,
        'top100_parity': {d: parity[d] for d in dates},
    }


def ratio_text(value: float | None) -> str:
    return 'null' if value is None else f'{value * 100:.2f}%'


def markdown_cell(row: dict) -> str:
    if row['cell_status'] == 'CANNOT_CONFIRM_GAP':
        return 'null · 缺口'
    return (
        f"n={row['selection_count_n']}/k={row['known_label_count_k']}/"
        f"h={row['confirmed_reference_hits_h']}/u={row['unknown_count_u']} · "
        f"主率={ratio_text(row['known_label_hit_rate_h_over_k'])}"
    )


def md_escape(value: Any) -> str:
    if value is None:
        return 'null'
    return str(value).replace('|', '\\|').replace('\n', ' ')


def stage_summaries(cells: list[dict], config: dict) -> list[dict]:
    summaries = []
    for stage in config['stages']:
        rows = [row for row in cells if row['stage'] == stage]
        available = [row for row in rows if row['cell_status'] == 'RETAINED_LIST']
        n = sum(row['selection_count_n'] or 0 for row in available)
        k = sum(row['known_label_count_k'] or 0 for row in available)
        h = sum(row['confirmed_reference_hits_h'] or 0 for row in available)
        u = sum(row['unknown_count_u'] or 0 for row in available)
        summaries.append({
            'stage': stage,
            'available_cells': len(available),
            'genuine_gap_cells': len(rows) - len(available),
            'selection_count_n_available_only': n,
            'known_label_count_k': k,
            'confirmed_reference_hits_h': h,
            'unknown_count_u': u,
            'qualified_misses_k_minus_h': k - h,
            'known_label_hit_rate_h_over_k': h / k if k else None,
            'all_selection_hit_rate_h_over_n': h / n if n and u == 0 else None,
        'observed_reference_match_fraction_h_over_n': h / n if n else None,
            'summary_scope': 'AVAILABLE_LISTS_ONLY;GAPS_EXCLUDED_NOT_ZERO_FILLED',
            'full_A_market_certification': 'CANNOT_CONFIRM',
            'historical_PIT': 'CANNOT_CONFIRM',
        })
    return summaries


def readable_table(cells: list[dict], summaries: list[dict], gaps: list[dict], config: dict,
                   scope_dates: list[str],
                   result: dict) -> str:
    by_key = {(row['trade_date'], row['stage']): row for row in cells}
    lines = [
        '# V4 A股二选 Top100 命中统计｜20日 × 7阶段',
        '',
        '范围：冻结的20个日期、7个A股阶段；股票×日期×阶段为观察单位，同一股票跨阶段分别计数。结果只作描述统计。',
        '',
        f"- 保留名单格：{result['retained_cells']}；真实缺口：{result['genuine_gap_cells']}（缺口计数、命中和命中率均为null）。",
        f"- 有效入选席位 n：{result['selection_count_n']}；合格收益 k：{result['known_label_count_k']}；确认Top100命中 h：{result['confirmed_reference_hits_h']}；待确认 u：{result['unknown_count_u']}。",
        f"- 汇总主率 h/k：{ratio_text(result['known_label_hit_rate_h_over_k'])}。存在待确认时，整名单率 h/n 为 null；这不是h/n的准确率替代。",
        '- 参考集是已冻结的当前V4研究面板QFQ日收益Top100；全A历史成分及历史PIT仍 CANNOT_CONFIRM。结果标签待确认与来源/PIT待确认分开列出。',
        '- CSV 中的字面值 `null` 表示缺失或待确认，不代表数值零。',
        '',
        '## 每日各阶段',
        '',
        '每格：n=实际入选数 / k=可评收益数 / h=确认参考命中 / u=待确认数；主率=h/k。存在u时全名单率=h/n为null。',
        '',
        '| 日期 | ' + ' | '.join(config['stages']) + ' |',
        '|---|' + '|'.join(['---'] * len(config['stages'])) + '|',
    ]
    for date in scope_dates:
        values = [markdown_cell(by_key[(date, stage)]) for stage in config['stages']]
        lines.append('| ' + date + ' | ' + ' | '.join(values) + ' |')
    lines.extend(['', '## 7阶段汇总', '', '| 阶段 | 可读格 | 缺口 | n | k | h | u | 主率 h/k | 全名单率 h/n |', '|---|---:|---:|---:|---:|---:|---:|---:|---:|'])
    for row in summaries:
        lines.append(
            f"| {row['stage']} | {row['available_cells']} | {row['genuine_gap_cells']} | "
            f"{row['selection_count_n_available_only']} | {row['known_label_count_k']} | "
            f"{row['confirmed_reference_hits_h']} | {row['unknown_count_u']} | "
            f"{ratio_text(row['known_label_hit_rate_h_over_k'])} | {ratio_text(row['all_selection_hit_rate_h_over_n'])} |"
        )
    lines.extend(['', '## 真实缺口', '', '| 日期 | 阶段 | 原因 | 来源状态 |', '|---|---|---|---|'])
    for gap in gaps:
        lines.append(f"| {gap['trade_date']} | {gap['stage']} | {md_escape(gap['gap_reason'])} | {md_escape(gap['source_status'])} |")
    lines.extend([
        '',
        '## 解释边界',
        '',
        '命中只表示股票代码落入冻结的当前研究面板Top100。没有合格同日收益、身份有冲突或不在面板中的入选记录标为UNKNOWN，不算MISS。来源状态与历史PIT单独列在 `cell_source_provenance.csv` 和 `source_pit_pending.csv`。',
        '',
    ])
    return '\n'.join(lines)


def detail_markdown(rows: list[dict], dates: list[str], config: dict) -> str:
    lookup: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in rows:
        lookup[(row['trade_date'], row['stage'])].append(row)
    lines = [
        '# 最近5日逐票明细',
        '',
        '每行是原名单中的一个股票×日期×阶段观察；返回值来自冻结的当前研究面板。UNKNOWN不计为MISS。',
        '',
    ]
    for date in dates:
        lines.extend([f'## {date}', ''])
        for stage in config['stages']:
            data = lookup.get((date, stage), [])
            lines.extend([f'### {stage}', '', '| 入选名次 | 代码 | 名称 | 当日收益% | 面板日排名 | 命中状态 | 待确认原因 | 原run | 来源状态 | 来源/PIT状态 |', '|---:|---|---|---:|---:|---|---|---|---|---|'])
            for row in data:
                lines.append(
                    '| ' + ' | '.join([
                        md_escape(row.get('selected_rank')),
                        md_escape(row.get('display_code')),
                        md_escape(row.get('name')),
                        md_escape(csv_value(row.get('daily_return_pct'))),
                        md_escape(row.get('daily_rank')),
                        md_escape(row.get('hit_state')),
                        md_escape(row.get('unknown_reason')),
                        md_escape(row.get('source_run_id')),
                        md_escape(row.get('source_status')),
                        md_escape(row.get('historical_pit_status')),
                    ]) + ' |'
                )
            if not data:
                lines.append('| null | null | null | null | null | UNKNOWN | STAGE_CELL_GAP | null | CANNOT_CONFIRM | CANNOT_CONFIRM_HISTORICAL_PIT |')
            lines.append('')
    return '\n'.join(lines)


def append_gap_detail_row(gap: dict, source: dict) -> dict:
    return {
        'trade_date': gap['trade_date'],
        'stage': gap['stage'],
        'selected_rank': None,
        'source_order_index': None,
        'rank_basis': None,
        'raw_code': None,
        'matrix_code': None,
        'display_code': None,
        'resolved_ts_code': None,
        'identity_basis': None,
        'identity_reason': None,
        'name': None,
        'name_basis': None,
        'name_historical_qualification': 'CANNOT_CONFIRM_HISTORICAL_NAME_BINDING',
        'daily_return_pct': None,
        'daily_rank': None,
        'hit_state': 'UNKNOWN',
        'label_status': 'CANNOT_CONFIRM_RESULT_LABEL',
        'unknown_reason': 'STAGE_CELL_GAP',
        'source_status': source.get('source_status'),
        'selection_status': source.get('selection_status'),
        'response_status': source.get('response_status'),
        'source_run_id': source.get('original_run_id'),
        'source_qualification': source.get('source_qualification'),
        'source_response_sha256': source.get('source_response_sha256'),
        'historical_pit_status': 'CANNOT_CONFIRM_HISTORICAL_PIT',
    }


def output_rows(scope: dict, dates: list[str], config: dict) -> tuple[list[dict], list[dict], list[dict], list[dict], list[dict]]:
    cells = scope['cells']
    sources = scope['sources']
    gaps = scope['gaps']
    observations = scope['observations']
    source_by_key = {(r['trade_date'], r['stage']): r for r in sources}
    gap_by_key = {(r['trade_date'], r['stage']): r for r in gaps}
    detail_dates = config['last5_dates'] if dates == config['dates'] else dates
    gap_detail = [append_gap_detail_row(gap, source_by_key[(gap['trade_date'], gap['stage'])]) for gap in gaps if gap['trade_date'] in detail_dates]
    details = [r for r in observations if r['trade_date'] in detail_dates]
    details.extend(gap_detail)
    details.sort(key=lambda r: (r['trade_date'], config['stages'].index(r['stage']), r['selected_rank'] if r['selected_rank'] is not None else 0))
    cell_rows = [row for row in cells if row['trade_date'] in dates]
    source_rows = [row for row in sources if row['trade_date'] in dates]
    gap_rows = [row for row in gaps if row['trade_date'] in dates]
    unknown_rows = [row for row in observations if row['trade_date'] in dates and row['hit_state'] == 'UNKNOWN']
    return cell_rows, source_rows, gap_rows, details, unknown_rows


def emit_outputs(scope: dict, dates: list[str], dest: Path, config: dict,
                 contract: dict, lineage: dict, mode: str) -> dict:
    if dest.exists() and any(dest.iterdir()):
        raise RuntimeError(f'OUTPUT_DIRECTORY_NOT_EMPTY:{dest}')
    dest.mkdir(parents=True, exist_ok=True)
    cells, sources, gaps, details, unknowns = output_rows(scope, dates, config)
    summaries = stage_summaries(cells, config)
    observed = [row for row in cells if row['cell_status'] == 'RETAINED_LIST']
    n = sum(row['selection_count_n'] or 0 for row in observed)
    k = sum(row['known_label_count_k'] or 0 for row in observed)
    h = sum(row['confirmed_reference_hits_h'] or 0 for row in observed)
    u = sum(row['unknown_count_u'] or 0 for row in observed)
    result = {
        'schema': 'A_SHARE_V4_READABLE20_TOP100_RESULT_V1',
        'status': 'DIRECTION_ONLY',
        'analysis_mode': mode,
        'route_id': contract['route_id'],
        'execution_id': contract['execution_id'],
        'baseline_id': contract['baseline_id'],
        'input_sha256': contract['input_sha256'],
        'code_sha256': contract['code_sha256'],
        'config_sha256': contract['config_sha256'],
        'dates': dates,
        'stages': config['stages'],
        'cell_count': len(cells),
        'retained_cells': len(observed),
        'genuine_gap_cells': len(gaps),
        'selection_count_n': n,
        'known_label_count_k': k,
        'confirmed_reference_hits_h': h,
        'unknown_count_u': u,
        'qualified_misses_k_minus_h': k - h,
        'known_label_hit_rate_h_over_k': h / k if k else None,
        'all_selection_hit_rate_h_over_n': h / n if n and u == 0 else None,
        'observed_reference_match_fraction_h_over_n': h / n if n else None,
        'last5_detail_rows': len(details) if mode == 'FULL_20' else None,
        'last5_actual_selection_observations': sum(row['hit_state'] != 'UNKNOWN' or row['display_code'] is not None for row in details) if mode == 'FULL_20' else None,
        'top100_reference': config['benchmark']['authority'],
        'full_A_market_top100': 'CANNOT_CONFIRM',
        'historical_PIT': 'CANNOT_CONFIRM',
        'natural_verified': False,
        'selection_sources_pending_count': sum(row['source_status'] in {None, 'CANNOT_CONFIRM'} for row in sources),
        'result_labels_pending_count': len(unknowns),
        'lineage_review_verdict': lineage.get('verdict'),
        'production_allowed': False,
        **SAFETY,
    }

    write_csv_new(dest / 'daily_stage_metrics.csv', cells, [
        'trade_date', 'stage', 'cell_status', 'selection_count_n', 'known_label_count_k',
        'confirmed_reference_hits_h', 'unknown_count_u', 'qualified_misses_k_minus_h',
        'known_label_hit_rate_h_over_k', 'all_selection_hit_rate_h_over_n', 'observed_reference_match_fraction_h_over_n',
        'unknown_reason_counts', 'source_status', 'selection_status', 'response_status',
        'source_mode', 'source_run_id', 'source_response_sha256', 'source_qualification',
        'historical_pit_status',
    ])
    write_csv_new(dest / 'stage_summary.csv', summaries, [
        'stage', 'available_cells', 'genuine_gap_cells', 'selection_count_n_available_only',
        'known_label_count_k', 'confirmed_reference_hits_h', 'unknown_count_u',
        'qualified_misses_k_minus_h', 'known_label_hit_rate_h_over_k',
        'all_selection_hit_rate_h_over_n', 'summary_scope', 'full_A_market_certification', 'historical_PIT',
    ])
    write_csv_new(dest / 'cell_source_provenance.csv', sources, [
        'trade_date', 'stage', 'cell_state', 'source_mode', 'source_reference_mode',
        'source_response_path', 'source_response_file_sha256', 'source_response_sha256',
        'matrix_response_file_sha256', 'source_status', 'selection_status', 'response_status',
        'response_run_id', 'original_run_id', 'run_id_match_in_r4_binding',
        'trio_verified_in_r4_binding', 'accepted_store_link', 'store_link_basis', 'source_qualification', 'source_cannot_confirm_reasons',
        'historical_pit_status', 'historical_name_status',
    ])
    pending_source = [row for row in sources if row['source_status'] in {None, 'CANNOT_CONFIRM'} or row['historical_pit_status'] == 'CANNOT_CONFIRM_HISTORICAL_PIT']
    pending_rows = [{
        'trade_date': row['trade_date'],
        'stage': row['stage'],
        'source_status': row['source_status'],
        'selection_status': row['selection_status'],
        'response_status': row['response_status'],
        'source_mode': row['source_mode'],
        'source_run_id': row['original_run_id'],
        'source_response_path': row['source_response_path'],
        'source_response_sha256': row['source_response_sha256'],
        'run_id_match_in_r4_binding': row['run_id_match_in_r4_binding'],
        'trio_verified_in_r4_binding': row['trio_verified_in_r4_binding'],
        'source_qualification': row['source_qualification'],
        'historical_pit_status': row['historical_pit_status'],
        'pending_reason': 'SOURCE_STATUS_PENDING' if row['source_status'] in {None, 'CANNOT_CONFIRM'} else 'HISTORICAL_PIT_CANNOT_CONFIRM',
    } for row in pending_source]
    write_csv_new(dest / 'source_pit_pending.csv', pending_rows, [
        'trade_date', 'stage', 'source_status', 'selection_status', 'response_status', 'source_mode',
        'source_run_id', 'source_response_path', 'source_response_sha256', 'run_id_match_in_r4_binding',
        'trio_verified_in_r4_binding', 'accepted_store_link', 'store_link_basis', 'source_qualification', 'historical_pit_status', 'pending_reason',
    ])
    write_csv_new(dest / 'source_gaps.csv', gaps, [
        'trade_date', 'stage', 'cell_status', 'selection_count_n', 'known_label_count_k',
        'confirmed_reference_hits_h', 'unknown_count_u', 'qualified_misses_k_minus_h',
        'known_label_hit_rate_h_over_k', 'all_selection_hit_rate_h_over_n', 'observed_reference_match_fraction_h_over_n', 'gap_reason',
        'source_status', 'selection_status', 'response_status', 'source_mode', 'source_run_id',
        'source_response_path', 'source_response_sha256', 'source_qualification', 'historical_pit_status',
    ])
    write_csv_new(dest / 'unknown_labels.csv', unknowns, [
        'trade_date', 'stage', 'selected_rank', 'raw_code', 'matrix_code', 'display_code',
        'resolved_ts_code', 'identity_basis', 'identity_reason', 'resolve_provenance', 'name', 'name_basis',
        'hit_state', 'label_status', 'unknown_reason', 'source_status', 'selection_status',
        'response_status', 'source_run_id', 'source_qualification', 'source_response_sha256',
        'historical_pit_status',
    ])
    write_csv_new(dest / 'stock_stage_detail.csv', details, [
        'trade_date', 'stage', 'selected_rank', 'source_order_index', 'rank_basis', 'raw_code',
        'matrix_code', 'display_code', 'resolved_ts_code', 'identity_basis', 'identity_reason', 'resolve_provenance', 'resolve_provenance',
        'name', 'name_basis', 'name_historical_qualification', 'daily_return_pct', 'daily_rank',
        'hit_state', 'label_status', 'unknown_reason', 'source_status', 'selection_status',
        'response_status', 'source_run_id', 'source_qualification', 'source_response_sha256',
        'historical_pit_status',
    ])
    daily_unique = []
    for date in dates:
        slots = [row for row in scope['observations'] if row['trade_date'] == date]
        unique = {}
        for row in slots:
            key = row['resolved_ts_code'] or row['raw_code'] or row['matrix_code']
            previous = unique.get(key)
            if previous and previous['hit_state'] != row['hit_state']:
                raise RuntimeError(f'DAILY_IDENTITY_LABEL_CONFLICT:{date}/{key}')
            unique[key] = row
        daily_unique.append({'trade_date': date, 'available_stage_cells': sum(row['cell_status'] == 'RETAINED_LIST' and row['trade_date'] == date for row in cells), 'missing_stage_cells': sum(row['trade_date'] == date for row in gaps), 'stage_observation_slots': len(slots), 'daily_unique_selected_codes': len(unique), 'repeated_stage_observations': len(slots) - len(unique), **metric_counts(list(unique.values()))})
    write_csv_new(dest / 'daily_unique_summary.csv', daily_unique, list(daily_unique[0]))
    write_json_new(dest / 'RUN_RESULT.json', result)
    write_csv_rows = cells
    markdown = readable_table(write_csv_rows, summaries, gaps, config, dates, result)
    with (dest / 'READABLE_20X7.md').open('x', encoding='utf-8', newline='') as f:
        f.write(markdown)
    detail_dates = config['last5_dates'] if mode == 'FULL_20' else dates
    detail_md = detail_markdown(details, detail_dates, config)
    with (dest / 'STOCK_STAGE_DETAIL.md').open('x', encoding='utf-8', newline='') as f:
        f.write(detail_md)
    manifest = {path.name: sha_file(path) for path in sorted(dest.iterdir()) if path.is_file()}
    write_json_new(dest / 'OUTPUT_MANIFEST.json', manifest)
    return result


def run(mode: str) -> dict:
    contract, config, binding = load_frozen()
    lineage = require_lineage_pass(binding)
    if mode == 'canary':
        dates = config['canary_dates']
        dest = Path(config['output_root']) / 'canary_r3c'
        mode_label = 'CANARY_SEP28_AND_OCT23_GAP'
    else:
        dates = config['dates']
        dest = Path(config['output_root']) / 'results_r3c'
        mode_label = 'FULL_20'
    scope = evaluate_dates(dates, config, binding)
    if mode == 'canary':
        if len(scope['cells']) != 14:
            raise RuntimeError(f'CANARY_CELL_COUNT_MISMATCH:{len(scope["cells"])}')
        if not any(g['trade_date'] == '20261023' and g['stage'] == 'STAGE_0925' for g in scope['gaps']):
            raise RuntimeError('CANARY_DID_NOT_RETAIN_OCT23_AUCTION_GAP')
        if len(scope['gaps']) != sum((d, s) in build_gap_map(read_json(Path(config['matrix_path'])), config) for d in dates for s in config['stages']):
            raise RuntimeError('CANARY_GAP_ACCOUNTING_MISMATCH')
    if mode == 'full':
        retained = sum(row['cell_status'] == 'RETAINED_LIST' for row in scope['cells'])
        if len(scope['cells']) != 140 or retained != 134 or len(scope['gaps']) != 6:
            raise RuntimeError('FULL_SCOPE_COUNT_MISMATCH')
        latest = [row for row in scope['observations'] if row['trade_date'] in config['last5_dates']]
        if len(latest) != 340:
            raise RuntimeError(f'LAST5_ACTUAL_OBSERVATION_COUNT_MISMATCH:{len(latest)}')
        if len([row for row in scope['gaps'] if row['trade_date'] in config['last5_dates']]) != 1:
            raise RuntimeError('LAST5_GAP_COUNT_MISMATCH')
    if mode == 'canary' and (not any(row['hit_state'] in {'HIT', 'MISS'} for row in scope['observations']) or any(row['unknown_reason'] == 'ORIGINAL_RUN_STORE_BINDING_NOT_CONFIRMED' for row in scope['observations'])):
        raise RuntimeError('CANARY_IDENTITY_JOIN_ALL_UNKNOWN_STOP_FULL')
    result = emit_outputs(scope, dates, dest, config, contract, lineage, mode_label)
    return result


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in {'freeze', 'canary', 'full'}:
        raise SystemExit('usage: analysis.py freeze|canary|full')
    if sys.argv[1] == 'freeze':
        result = freeze_contract()
    else:
        result = run(sys.argv[1])
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
