"""Read-only decoding of explicitly bound original PyTDX response records.

The existing owner's trusted repair authority supplies these sources. This
module verifies captured bytes, request/response identities and actual clocks;
it does not establish price, volume, membership or daily-finality semantics.
Only three unchanged functions are extracted from the frozen original source.
The original collector is never imported or called.
"""
import ast
import copy
from datetime import date, datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
from typing import Any, Mapping

from .composition import no_symlinks
from .contracts import aware, exact_keys, sha, trade_date
from .module_api import _open_directory, _read_regular
from .rebound_owner import _json
from .source_capsule import checked_path


BASE = Path(__file__).resolve().parents[2]
DECODER_SHA = 'fa7dcbce4ee026b0a02c47220820d0407af183553d3304afcc5db425dce33cbd'
RAW_INPUT_SCHEMA = 'v5.hk02_pytdx_raw_repair_request.v1'
MANIFEST_SHA256 = '057a2c453ae562bc94564829dd8f78aba2b303bb7182a0b493fde9d4bedbafcd'
MANIFEST_RELATIVE = 'contracts/rebound_repair_source_manifest.json'
DECODER_RELATIVE = 'vendor/rebound_repair_baseline/hk_daily_supplement.py'
MAX_RAW_BYTES = 256 * 1024**2
SUCCESS_STATUSES = frozenset(('RESPONSE_CAPTURED', 'READY', 'PENDING'))
NATIVE_EVIDENCE = dict(volume_unit=None, volume_unit_status='NOT_PROVEN',
                       price_basis='NOT_PROVEN', scale_applied=1)


def _canonical(value):
    # Match the original _canonical exactly, without changing numeric values.
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _read(root, relative, limit):
    path = checked_path(root, relative)
    directory = _open_directory(path.parent)
    try:
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    finally:
        os.close(directory)
    try:
        return _read_regular(fd, limit)
    finally:
        os.close(fd)


def _decoder():
    manifest_raw = _read(BASE, MANIFEST_RELATIVE, 1024**2)
    if _sha(manifest_raw) != MANIFEST_SHA256:
        raise ValueError('RAW_REPAIR_SOURCE_MANIFEST_SHA')
    manifest = _json(manifest_raw)
    raw = _read(BASE, DECODER_RELATIVE, 1024**2)
    if (manifest['relative_path'] != DECODER_RELATIVE or manifest['sha256'] != DECODER_SHA
            or len(raw) != manifest['bytes'] or _sha(raw) != DECODER_SHA):
        raise ValueError('RAW_REPAIR_DECODER_SOURCE_SHA')
    names = ('_finite', '_bar_date', '_decode_bar')
    selected = [node for node in ast.parse(raw).body if isinstance(node, ast.FunctionDef) and node.name in names]
    if [node.name for node in selected] != list(names):
        raise ValueError('RAW_REPAIR_DECODER_FUNCTIONS')
    # Bind only stdlib dependencies. Preserve every original function AST node.
    scope = dict(Any=Any, Mapping=Mapping, math=math, date=date, datetime=datetime)
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(BASE / DECODER_RELATIVE), 'exec'), scope)
    return scope['_bar_date'], scope['_decode_bar']


def _pointer(document, pointer):
    """Strict RFC 6901 traversal; no inferred container or fallback key."""
    if (not isinstance(pointer, str) or len(pointer) > 4096
            or (pointer and not pointer.startswith('/'))):
        raise ValueError('RAW_REPAIR_RECORD_POINTER')
    tokens = pointer.split('/')[1:] if pointer else []
    if len(tokens) > 128:
        raise ValueError('RAW_REPAIR_RECORD_POINTER')
    value = document
    for token in tokens:
        if re.search(r'~(?![01])', token):
            raise ValueError('RAW_REPAIR_RECORD_POINTER')
        token = token.replace('~1', '/').replace('~0', '~')
        if isinstance(value, dict):
            if token not in value:
                raise ValueError('RAW_REPAIR_RECORD_POINTER_MISSING')
            value = value[token]
        elif isinstance(value, list):
            if not re.fullmatch(r'0|[1-9][0-9]*', token) or len(token) > 10 or int(token) >= len(value):
                raise ValueError('RAW_REPAIR_RECORD_POINTER_INDEX')
            value = value[int(token)]
        else:
            raise ValueError('RAW_REPAIR_RECORD_POINTER_CONTAINER')
    if not isinstance(value, dict):
        raise ValueError('RAW_REPAIR_RECORD_REQUIRED')
    return value


def _keys(value, through_date):
    if not isinstance(value, list) or not 1 <= len(value) <= 20000:
        raise ValueError('RAW_REPAIR_KEYS_BOUND')
    result = set()
    for row in value:
        exact_keys(row, ('code', 'date'))
        code, day = row['code'], trade_date(row['date'])
        if (not isinstance(code, str) or not re.fullmatch(r'HK\.\d{5}', code)
                or day >= through_date or (code, day) in result):
            raise ValueError('RAW_REPAIR_KEY_INVALID_OR_DUPLICATE')
        result.add((code, day))
    return result


def _record(record, now):
    required = {'code', 'status', 'error_code', 'request', 'request_sha256', 'source_rows',
                'response_sha256', 'returned_count', 'request_started_at',
                'response_acquired_at', 'request_finished_at'}
    if not required <= record.keys():
        raise ValueError('RAW_REPAIR_RECORD_FIELDS')
    code = record['code']
    if not isinstance(code, str) or not re.fullmatch(r'HK\.\d{5}', code):
        raise ValueError('RAW_REPAIR_RECORD_CODE')
    if not isinstance(record['status'], str) or record['status'] not in SUCCESS_STATUSES or record['error_code'] is not None:
        raise ValueError('RAW_REPAIR_RECORD_NOT_SUCCESSFUL')
    request = record['request']
    if not isinstance(request, dict) or not {'category', 'market', 'code', 'start', 'count'} <= request.keys():
        raise ValueError('RAW_REPAIR_REQUEST_FIELDS')
    if (type(request['category']) is not int or request['category'] != 4
            or type(request['market']) is not int or request['market'] != 71
            or request['code'] != code[3:]
            or type(request['start']) is not int or request['start'] < 0
            or type(request['count']) is not int or request['count'] <= 0):
        raise ValueError('RAW_REPAIR_REQUEST_IDENTITY')
    sha(record['request_sha256']); sha(record['response_sha256'])
    if _sha(_canonical(request)) != record['request_sha256']:
        raise ValueError('RAW_REPAIR_REQUEST_SHA')
    rows = record['source_rows']
    if (not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows)
            or type(record['returned_count']) is not int or record['returned_count'] != len(rows)
            or len(rows) > request['count']):
        raise ValueError('RAW_REPAIR_RESPONSE_COUNT')
    if _sha(_canonical(rows)) != record['response_sha256']:
        raise ValueError('RAW_REPAIR_RESPONSE_SHA')
    started = aware(record['request_started_at'])
    acquired = aware(record['response_acquired_at'])
    finished = aware(record['request_finished_at'])
    if not started <= acquired <= finished <= now:
        raise ValueError('RAW_REPAIR_CAPTURE_CLOCK_ORDER')
    return code, rows, started, finished


def decode_raw_repair(raw_root, *, sources, keys, through_date):
    """Decode unique missing rows from approved source-record JSON pointers.

    `sources` is a list of exact {relative, sha256, record_pointer} mappings.
    One file can contain several records and is read once with same-fd stability.
    The caller binds the returned actual capture interval to owner authority;
    bar dates, file mtimes and caller-provided replacement clocks are never used.
    """
    root = no_symlinks(raw_root)
    if not root.is_dir():
        raise ValueError('RAW_REPAIR_ROOT_REQUIRED')
    through_date = trade_date(through_date)
    wanted = _keys(keys, through_date)
    if not isinstance(sources, list) or not 1 <= len(sources) <= 2000:
        raise ValueError('RAW_REPAIR_SOURCES_BOUND')
    files, references = {}, set()
    for source in sources:
        exact_keys(source, ('relative', 'sha256', 'record_pointer'))
        relative, expected, pointer = source['relative'], sha(source['sha256']), source['record_pointer']
        if not isinstance(relative, str):
            raise ValueError('RAW_REPAIR_SOURCE_PATH')
        checked_path(root, relative)
        if not isinstance(pointer, str):
            raise ValueError('RAW_REPAIR_RECORD_POINTER')
        reference = (relative, pointer)
        if reference in references:
            raise ValueError('RAW_REPAIR_DUPLICATE_REFERENCE')
        references.add(reference)
        if relative in files and files[relative] != expected:
            raise ValueError('RAW_REPAIR_CONFLICTING_FILE_SHA')
        files[relative] = expected
    bar_date, decode = _decoder()
    documents, total = {}, 0
    for relative, expected in files.items():
        raw = _read(root, relative, MAX_RAW_BYTES-total)
        total += len(raw)
        if _sha(raw) != expected:
            raise ValueError('RAW_REPAIR_INPUT_SHA')
        documents[relative] = _json(raw)
    rows_by_key, evidence_by_key = {}, {}
    starts, finishes = [], []
    now = datetime.now(timezone.utc)
    wanted_codes = {code for code, _ in wanted}
    for source in sources:
        record = _pointer(documents[source['relative']], source['record_pointer'])
        code, raw_rows, started, finished = _record(record, now)
        if code not in wanted_codes:
            raise ValueError('RAW_REPAIR_UNREQUESTED_CODE')
        starts.append(started); finishes.append(finished)
        requested = {day for stock, day in wanted if stock == code}
        seen = set()
        selected_count = 0
        for index, raw_row in enumerate(raw_rows):
            day = bar_date(raw_row)
            if day in seen:
                raise ValueError('RAW_REPAIR_DUPLICATE_SOURCE_DATE')
            seen.add(day)
            decoded = decode(raw_row, through_date, requested)
            if decoded is None:
                continue
            key = (code, decoded['trade_date'])
            if key in rows_by_key:
                raise ValueError('RAW_REPAIR_MULTIPLE_SOURCES_FOR_KEY')
            # Keep the original numeric values. Nested metadata is returned
            # once at the top level, rather than being written into Parquet.
            decoded.pop('native_fields')
            rows_by_key[key] = dict(decoded, code_norm=code, trade_date_compact=decoded['trade_date'])
            evidence_by_key[key] = dict(code=code, date=key[1], raw_file=source['relative'],
                raw_file_sha256=source['sha256'], record_pointer=source['record_pointer'],
                source_row_index=index, source_row_sha256=_sha(_canonical(raw_row)))
            selected_count += 1
        if not selected_count:
            raise ValueError('RAW_REPAIR_UNUSED_SOURCE')
    if set(rows_by_key) != wanted:
        raise ValueError('RAW_REPAIR_EXACT_KEYS_MISSING')
    return dict(rows=[rows_by_key[key] for key in sorted(wanted)],
        row_evidence=[evidence_by_key[key] for key in sorted(wanted)],
        capture_started_at=min(starts).astimezone(timezone.utc).isoformat(timespec='microseconds'),
        capture_finished_at=max(finishes).astimezone(timezone.utc).isoformat(timespec='microseconds'),
        raw_files=dict(files), native_evidence=copy.deepcopy(NATIVE_EVIDENCE))
