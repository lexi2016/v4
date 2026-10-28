"""Receipt-bound, read-only Stage A projection of the existing WeChat archive.

The archive remains authoritative. Only the explicit ops command writes a small
reference index; this reader never imports, repairs, downloads or derives stocks.
Paths in receipts are untrusted. Only relative archived_filename and optionally
same-input manifest members are opened beneath a configured root, without links.
"""
from __future__ import annotations

import base64
import csv
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
from typing import Any, Iterator
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

SCHEMA = 'v4.wechat_materials.stage_a.v1'
INDEX_SCHEMA = 'v4.wechat_archive_reference.v1'
SAFETY = {'RESEARCH_ONLY': True, 'WATCH_ONLY': True, 'NO_BUY_GATE': True,
          'production_allowed': False, 'buy_gate_updated': False, 'orders_sent': False}
FILES = {'report': 'report.md', 'coverage': 'coverage.csv', 'mentions': 'mentions.csv',
         'unmapped': 'unmapped.csv', 'summary': 'summary.json'}
SHA = re.compile(r'^[0-9a-f]{64}$')
PACKAGE_ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$')
IDENTITY_KEYS = ('original_url', 'article_id', 'title', 'account', 'biz',
                 'published_at', 'article_date', 'content_hash', 'source_run_id')
MAX_JSON = 2 * 1024 * 1024
MAX_ARTIFACT = 32 * 1024 * 1024
MAX_REPORT = 4 * 1024 * 1024
MAX_FROZEN_MEMBER = 1024 * 1024 * 1024
MAX_RECORDS = 10000
MAX_MENTION_ROWS = 10000
MAX_MENTION_FIELD = 2000
MENTIONS_SCHEMA = 'v4.wechat_mentions.stage_a.v1'
MENTION_COLUMNS = ('market', 'code', 'name', 'source_index', 'mapping_status',
                   'source_named_or_derived', 'claim_context', 'entity_id',
                   'source_name', 'listing_origin')
MENTION_MARKETS = ('A', 'BJ', 'HK')
MENTION_CODE = re.compile(r'^\d{5,6}\.(?:SH|SZ|BJ|HK)$')
MENTION_SOURCE_INDEX = re.compile(r'^(?:BODY|IMAGE\d{3})$')
MENTION_TOKEN = re.compile(r'^[A-Za-z0-9_.-]{1,128}$')


class ArchiveError(ValueError):
    """Stable path-free reason code safe to expose in an API response."""
    def __init__(self, code: str, status_code: int = 409):
        super().__init__(code)
        self.code, self.status_code = code, status_code


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate key')
        result[key] = value
    return result


def parse_json(data: bytes, code: str) -> dict:
    try:
        obj = json.loads(data.decode('utf-8-sig'), object_pairs_hook=_pairs,
                         parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        if not isinstance(obj, dict):
            raise ValueError('not an object')
        return obj
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ArchiveError(code) from exc


def _sha(value: Any) -> str:
    if not isinstance(value, str) or not SHA.fullmatch(value):
        raise ArchiveError('INVALID_SHA256', 422)
    return value


def _text(value: Any, maximum: int = 2000) -> str | None:
    if value is None or value == '':
        return None
    if not isinstance(value, str) or len(value) > maximum or '\x00' in value:
        raise ArchiveError('INVALID_TEXT_FIELD')
    return value


def safe_url(value: Any) -> str | None:
    if not isinstance(value, str) or len(value) > 4000 or re.search(r'[\s\\\x00-\x1f\x7f]', value):
        return None
    try:
        u = urlsplit(value)
        if u.scheme not in ('https', 'http') or not u.hostname or u.username or u.password:
            return None
        _ = u.port
        return value
    except ValueError:
        return None


def aware_time(value: Any) -> str | None:
    if not isinstance(value, str) or not re.fullmatch(
            r'\d{4}-\d\d-\d\dT\d\d:\d\d(?::\d\d(?:\.\d+)?)?(?:Z|[+-]\d\d:\d\d)', value):
        return None
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return value if dt.utcoffset() is not None else None
    except ValueError:
        return None


def valid_date(value: Any) -> str:
    try:
        if not isinstance(value, str) or not re.fullmatch(r'\d{8}', value):
            raise ValueError()
        datetime.strptime(value, '%Y%m%d')
        return value
    except ValueError as exc:
        raise ArchiveError('INVALID_DATE', 422) from exc


def relative_path(value: Any) -> str:
    if (not isinstance(value, str) or not value or len(value) > 2000
            or re.search(r'[\\:\x00-\x1f\x7f]', value)):
        raise ArchiveError('UNSAFE_PATH')
    parts = value.split('/')
    if any(p in ('', '.', '..') for p in parts) or PurePosixPath(value).is_absolute():
        raise ArchiveError('UNSAFE_PATH')
    return value


def _io_error(exc: OSError) -> ArchiveError:
    if isinstance(exc, FileNotFoundError):
        return ArchiveError('SOURCE_MISSING', 410)
    if isinstance(exc, PermissionError):
        return ArchiveError('SOURCE_NOT_READABLE', 403)
    return ArchiveError('UNSAFE_PATH')


@contextmanager
def directory(path: Path, *, create: bool = False) -> Iterator[int]:
    """POSIX openat walk: no check-then-open symlink race, including root parents."""
    path = path.absolute()
    if '..' in path.parts or not hasattr(os, 'O_NOFOLLOW'):
        raise ArchiveError('UNSAFE_OR_UNSUPPORTED_ROOT')
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            if create:
                try:
                    os.mkdir(part, mode=0o700, dir_fd=fd)
                except FileExistsError:
                    pass
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = nxt
        yield fd
    except OSError as exc:
        raise _io_error(exc) from exc
    finally:
        os.close(fd)


def read_bytes(root: Path, relative: str, expected_sha: str | None = None,
               expected_size: int | None = None, limit: int = MAX_JSON) -> bytes:
    relative_path(relative)
    if expected_sha is not None:
        _sha(expected_sha)
    if expected_size is not None and (type(expected_size) is not int or not 0 <= expected_size <= limit):
        raise ArchiveError('INVALID_ARTIFACT_SIZE')
    parts = relative.split('/')
    try:
        with directory(root.joinpath(*parts[:-1])) as parent:
            fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            with os.fdopen(fd, 'rb') as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
                    raise ArchiveError('UNSAFE_FILE_OR_TOO_LARGE')
                data = stream.read(limit + 1)
        if len(data) > limit:
            raise ArchiveError('ARTIFACT_TOO_LARGE')
        if expected_sha is not None and digest(data) != expected_sha:
            raise ArchiveError('HASH_MISMATCH')
        if expected_size is not None and len(data) != expected_size:
            raise ArchiveError('SIZE_MISMATCH')
        return data
    except OSError as exc:
        raise _io_error(exc) from exc


def _refs(receipt: dict, receipt_path: str) -> dict[str, dict]:
    if receipt.get('receipt_version') not in ('wechat-chat-return-v1', 'wechat-chat-return-v2'):
        raise ArchiveError('UNSUPPORTED_RECEIPT_VERSION')
    for key in ('production_allowed', 'buy_gate_updated', 'orders_sent'):
        if receipt.get(key) not in (None, False) or (key in receipt and receipt[key] is not False):
            raise ArchiveError('RECEIPT_SAFETY_CONFLICT')
    files = receipt.get('archived_files')
    if not isinstance(files, dict) or 'report' not in files or not set(files).issubset(FILES):
        raise ArchiveError('INVALID_ARCHIVED_FILES')
    parent = PurePosixPath(receipt_path).parent
    refs = {}
    for role, value in files.items():
        if not isinstance(value, dict):
            raise ArchiveError('INVALID_ARCHIVED_FILES')
        name = relative_path(value.get('archived_filename'))
        # The actual importer writes immediate versioned filenames, not subdirectories.
        if '/' in name:
            raise ArchiveError('UNSAFE_PATH')
        size = value.get('bytes')
        if type(size) is not int or not 0 < size <= (MAX_REPORT if role == 'report' else MAX_ARTIFACT):
            raise ArchiveError('INVALID_ARTIFACT_SIZE')
        refs[role] = {'path': str(parent / name), 'sha256': _sha(value.get('sha256')),
                      'bytes': size, 'filename': name, 'kind': 'CHAT_RETURN'}
    return refs


def _bind_manifest(binding: dict, manifest: dict, path: str) -> tuple[dict, dict]:
    if (binding.get('package_identity_status') != 'VERIFIED'
            or not binding.get('input_digest')
            or manifest.get('manifest_version') != 'chat-materials-ocr-v2'):
        raise ArchiveError('IDENTITY_CONFLICT_MANIFEST')
    descriptor = manifest.get('input_descriptor')
    if (not isinstance(descriptor, dict) or digest(canonical(descriptor)) != binding['input_digest']
            or manifest.get('input_digest') != binding['input_digest']
            or manifest.get('package_id') != binding.get('package_id')):
        raise ArchiveError('IDENTITY_CONFLICT_MANIFEST')
    ident = descriptor.get('identity')
    if not isinstance(ident, dict) or any(k not in ident or ident[k] != manifest.get(k) for k in IDENTITY_KEYS):
        raise ArchiveError('IDENTITY_CONFLICT_MANIFEST')
    for key, counterpart in [('original_url','article_url'), ('source_run_id','source_run_id'),
                             ('article_id','article_id'), ('article_date','article_date'),
                             ('title','article_title'), ('content_hash','content_hash')]:
        if binding.get(counterpart) and ident.get(key) != binding[counterpart]:
            raise ArchiveError('IDENTITY_CONFLICT_MANIFEST')
    count = manifest.get('total_images')
    if binding.get('image_count') is not None and binding['image_count'] != count:
        raise ArchiveError('IDENTITY_CONFLICT_IMAGE_COUNT')
    if type(count) is not int or not 0 <= count <= 5000:
        raise ArchiveError('INVALID_INPUT_SOURCES')
    entries = descriptor.get('sources')
    expected = ['BODY', 'OCR_FULL', 'IMAGE_MANIFEST'] + [f'IMAGE{i:03d}' for i in range(1,count+1)]
    if not isinstance(entries, list) or len(entries) != len(expected):
        raise ArchiveError('INVALID_INPUT_SOURCES')
    refs, paths = {}, set()
    for sid, entry in zip(expected, entries):
        if not isinstance(entry, dict) or entry.get('source_id') != sid:
            raise ArchiveError('INVALID_INPUT_SOURCES')
        member = relative_path(entry.get('path'))
        if member in paths:
            raise ArchiveError('INVALID_INPUT_SOURCES')
        paths.add(member)
        if type(entry.get('bytes')) is not int or not 0 <= entry['bytes'] <= MAX_ARTIFACT:
            raise ArchiveError('INVALID_ARTIFACT_SIZE')
        refs['source_'+sid] = {'path': str(PurePosixPath(path).parent / member),
            'sha256': _sha(entry.get('sha256')), 'bytes':entry['bytes'], 'filename':PurePosixPath(member).name,
            'kind':'FROZEN_INPUT', 'source_id':sid}
    return ident, refs


def _report_identity(data: bytes, summary: dict | None, binding: dict) -> str | None:
    try:
        text = data.decode('utf-8-sig')
    except UnicodeError:
        return None
    header = None
    if text.startswith('<!-- wechat-return:'):
        match = re.match(r'^<!-- wechat-return: (\{[^\n]+\}) -->\r?\n', text)
        if not match:
            raise ArchiveError('IDENTITY_CONFLICT_REPORT_HEADER')
        header = parse_json(match[1].encode(), 'IDENTITY_CONFLICT_REPORT_HEADER')
    for obj in (header, summary):
        if obj is None:
            continue
        for field in ('package_id', 'input_digest'):
            if field in obj and (obj.get(field) or None) != (binding.get(field) or None):
                raise ArchiveError('IDENTITY_CONFLICT_RETURN')
        if obj.get('url') and obj['url'] != binding.get('article_url'):
            raise ArchiveError('IDENTITY_CONFLICT_RETURN')
        for field, bfield in [('article_date','article_date'),('article_id','article_id')]:
            if obj.get(field) and binding.get(bfield) and obj[field] != binding[bfield]:
                raise ArchiveError('IDENTITY_CONFLICT_RETURN')
    if header and summary and header.get('return_id') != summary.get('return_id'):
        raise ArchiveError('IDENTITY_CONFLICT_RETURN_ID')
    rid = (summary or header or {}).get('return_id')
    if rid is not None and (not isinstance(rid,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}',rid)):
        raise ArchiveError('INVALID_RETURN_ID')
    return rid


def _parse_mentions(data: bytes) -> tuple[list[dict], dict]:
    """Parse the archived mention CSV without silently repairing its rows.

    The CSV is a structured chat return, not a second stock producer.  Every
    input row must satisfy the frozen columns and market/code contract before
    it can be projected into the read-only Stage A panel.
    """
    if len(data) > MAX_ARTIFACT:
        raise ArchiveError('MENTIONS_TOO_LARGE', 413)
    try:
        text = data.decode('utf-8-sig')
    except UnicodeError as exc:
        raise ArchiveError('MENTIONS_TEXT_UNREADABLE') from exc
    if '\x00' in text:
        raise ArchiveError('MENTIONS_MALFORMED')
    old_limit = csv.field_size_limit()
    csv.field_size_limit(MAX_MENTION_FIELD)
    try:
        # Strict mode rejects malformed quoting instead of letting the CSV
        # reader recover a different row shape.  Keep the raw physical lines
        # only to distinguish permitted trailing blank lines from an empty
        # row embedded before later source material.
        reader = csv.reader(io.StringIO(text, newline=''), strict=True)
        raw_lines = text.splitlines()
        try:
            header = next(reader)
        except StopIteration as exc:
            raise ArchiveError('MENTIONS_EMPTY') from exc
        if tuple(header) != MENTION_COLUMNS:
            raise ArchiveError('MENTIONS_INVALID_COLUMNS')
        rows: list[dict] = []
        for row_number, values in enumerate(reader, start=2):
            # A trailing blank line is normal CSV formatting; an interior
            # blank line or an incomplete row is a source contract failure.
            if not values:
                if not any(line != '' for line in raw_lines[reader.line_num:]):
                    continue
                raise ArchiveError(f'MENTIONS_MALFORMED_ROW_{row_number}')
            if len(rows) >= MAX_MENTION_ROWS:
                raise ArchiveError('MENTIONS_ROW_LIMIT', 413)
            if len(values) != len(MENTION_COLUMNS):
                raise ArchiveError(f'MENTIONS_MALFORMED_ROW_{row_number}')
            item = {key: value for key, value in zip(MENTION_COLUMNS, values)}
            if any(not isinstance(value, str) or not value.strip() or len(value) > MAX_MENTION_FIELD
                   for value in item.values()):
                raise ArchiveError(f'MENTIONS_MALFORMED_ROW_{row_number}')
            item = {key: value.strip() for key, value in item.items()}
            market, code = item['market'], item['code']
            if market not in MENTION_MARKETS or not MENTION_CODE.fullmatch(code):
                raise ArchiveError(f'MENTIONS_INVALID_SECURITY_{row_number}')
            suffix = code.rsplit('.', 1)[-1]
            expected_suffixes = {'A': {'SH', 'SZ'}, 'BJ': {'BJ'}, 'HK': {'HK'}}[market]
            if suffix not in expected_suffixes:
                raise ArchiveError(f'MENTIONS_MARKET_CODE_MISMATCH_{row_number}')
            if not MENTION_SOURCE_INDEX.fullmatch(item['source_index']):
                raise ArchiveError(f'MENTIONS_INVALID_SOURCE_INDEX_{row_number}')
            if not MENTION_TOKEN.fullmatch(item['entity_id']):
                raise ArchiveError(f'MENTIONS_INVALID_ENTITY_{row_number}')
            for key in ('source_named_or_derived', 'listing_origin'):
                if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]{0,63}', item[key]):
                    raise ArchiveError(f'MENTIONS_INVALID_{key.upper()}_{row_number}')
            rows.append(item)
        # A valid header-only file means zero mentions, not a missing file.
        return rows, _mention_counts(rows)
    except csv.Error as exc:
        raise ArchiveError('MENTIONS_MALFORMED') from exc
    finally:
        csv.field_size_limit(old_limit)


def _mention_counts(rows: list[dict]) -> dict:
    groups = {(row['market'], row['code']) for row in rows}
    issuers = {row['entity_id'] for row in rows}
    markets = {market: {'rows': 0, 'listings': 0} for market in MENTION_MARKETS}
    for row in rows:
        markets[row['market']]['rows'] += 1
    for market, _code in groups:
        markets[market]['listings'] += 1
    return {
        'rows': len(rows),
        'listings': len(groups),
        'issuers': len(issuers),
        'market_rows': {market: markets[market]['rows'] for market in MENTION_MARKETS},
        'market_listings': {market: markets[market]['listings'] for market in MENTION_MARKETS},
        'source_named_rows': sum(row['source_named_or_derived'] == 'SOURCE_NAMED' for row in rows),
        'source_named_listings': len({(row['market'], row['code']) for row in rows
                                      if row['source_named_or_derived'] == 'SOURCE_NAMED'}),
        'source_named_entities': len({row['entity_id'] for row in rows
                                      if row['source_named_or_derived'] == 'SOURCE_NAMED'}),
        'supplemental_listing_rows': sum(row['listing_origin'] == 'SUPPLEMENTAL_LISTING' for row in rows),
    }


def _source_index_key(value: str) -> tuple[int, str]:
    if value == 'BODY':
        return -1, value
    try:
        return int(value[5:]), value
    except (TypeError, ValueError):
        return (10**9, str(value))


def _deduplicate_mentions(rows: list[dict]) -> list[dict]:
    """Collapse repeated source rows to one listing while retaining evidence."""
    groups: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        groups.setdefault((row['market'], row['code']), []).append(row)
    output = []
    market_order = {market: index for index, market in enumerate(MENTION_MARKETS)}
    for (market, code), members in groups.items():
        first = members[0]
        source_indexes = sorted({row['source_index'] for row in members}, key=_source_index_key)
        source_names = list(dict.fromkeys(row['source_name'] for row in members))
        contexts = list(dict.fromkeys(row['claim_context'] for row in members))
        mapping_statuses = list(dict.fromkeys(row['mapping_status'] for row in members))
        origins = list(dict.fromkeys(row['listing_origin'] for row in members))
        sources = list(dict.fromkeys(row['source_named_or_derived'] for row in members))
        entity_ids = list(dict.fromkeys(row['entity_id'] for row in members))
        output.append({
            'market': market,
            'code': code,
            'name': first['name'],
            'entity_id': first['entity_id'],
            'entity_ids': entity_ids,
            'mapping_status': first['mapping_status'],
            'mapping_statuses': mapping_statuses,
            'source_named_or_derived': sources[0] if len(sources) == 1 else 'MULTIPLE',
            'source_named_or_derived_values': sources,
            'listing_origin': 'SUPPLEMENTAL_LISTING' if 'SUPPLEMENTAL_LISTING' in origins else origins[0],
            'listing_origins': origins,
            'source_count': len(members),
            'source_indexes': source_indexes,
            'source_index_count': len(source_indexes),
            'source_names': source_names,
            'claim_contexts': contexts,
            # Keep the first value as a compact table field; the complete
            # deduplicated contexts remain available for expansion.
            'claim_context': contexts[0],
        })
    output.sort(key=lambda row: (market_order[row['market']], row['code'], row['name']))
    return output


def _trusted_input_binding(binding: dict, input_digest: str | None) -> bool:
    """Match the importer contract before exposing RECEIPT_BOUND.

    A receipt can carry a syntactically valid input digest while omitting the
    package/run identity or the trusted ZIP hash.  Those fields are the
    provenance evidence supplied by the importer; their presence alone must
    not promote a return to a bound state.
    """
    package_id = _text(binding.get('package_id'))
    source_run_id = _text(binding.get('source_run_id'))
    declared_sha = _text(binding.get('package_sha256_declared'))
    observed_sha = _text(binding.get('package_sha256_observed'))
    return bool(
        package_id and PACKAGE_ID.fullmatch(package_id) and source_run_id and input_digest and SHA.fullmatch(input_digest)
        and declared_sha and SHA.fullmatch(declared_sha)
        and observed_sha and SHA.fullmatch(observed_sha)
        and declared_sha == observed_sha
        and binding.get('package_sha256_status') == 'VERIFIED'
    )


def _strict_frozen_input(reader, receipt_path: str, receipt: dict, refs: dict,
                         returned: dict[str, bytes]) -> tuple[dict, dict, dict]:
    """Verify only the explicit extractor references in a new-standard receipt."""
    binding = receipt.get('binding')
    if (not isinstance(binding, dict) or binding.get('package_identity_status') != 'VERIFIED'
            or not _trusted_input_binding(binding, binding.get('input_digest'))):
        raise ArchiveError('FROZEN_INPUT_BINDING_UNTRUSTED')
    if (receipt.get('receipt_version') != 'wechat-chat-return-v2'
            or receipt.get('status') != 'REPORT_AND_STRUCTURED_ARCHIVED'
            or receipt.get('structured_validation_status') != 'COMPLETE'
            or receipt.get('missing_artifacts') != []
            or receipt.get('invalid_artifacts') != []
            or set(refs) != set(FILES)):
        raise ArchiveError('FROZEN_INPUT_RETURN_INCOMPLETE')
    local = receipt.get('local_acceptance')
    if (not isinstance(local, dict) or local.get('input_binding_valid') is not True
            or local.get('structure_valid') is not True
            or local.get('semantic_research_accepted') is not False):
        raise ArchiveError('FROZEN_INPUT_RETURN_INCOMPLETE')
    if (receipt.get('review_contract_version') != 'wechat-event-dispositions-v1'
            or receipt.get('event_dispositions_contract_status') != 'PASS'):
        raise ArchiveError('FROZEN_INPUT_REVIEW_CONTRACT_REQUIRED')
    frozen = receipt.get('frozen_input')
    if not isinstance(frozen, dict) or frozen.get('status') != 'VERIFIED':
        raise ArchiveError('FROZEN_INPUT_RECEIPT_MISSING_OR_BLOCKED')
    parent = PurePosixPath(receipt_path).parent
    try:
        manifest_member = relative_path(frozen.get('manifest_path'))
        extraction_receipt_member = relative_path(frozen.get('receipt_path'))
        manifest_path = str(parent / manifest_member)
        extraction_receipt_path = str(parent / extraction_receipt_member)
        manifest_sha = _sha(frozen.get('manifest_sha256'))
        extraction_receipt_sha = _sha(frozen.get('receipt_sha256'))
        extraction_data = read_bytes(reader.archive_root, extraction_receipt_path,
                                     extraction_receipt_sha, limit=MAX_JSON)
        manifest_data = read_bytes(reader.archive_root, manifest_path, manifest_sha,
                                   limit=MAX_JSON)
    except ArchiveError as exc:
        if exc.code == 'SOURCE_MISSING':
            raise ArchiveError('FROZEN_INPUT_RECEIPT_OR_MANIFEST_MISSING') from exc
        if exc.code == 'HASH_MISMATCH':
            raise ArchiveError('FROZEN_INPUT_RECEIPT_OR_MANIFEST_HASH_MISMATCH') from exc
        raise
    extraction = parse_json(extraction_data, 'INVALID_FROZEN_INPUT_RECEIPT')
    manifest = parse_json(manifest_data, 'INVALID_MANIFEST')
    if (extraction.get('receipt_version') != 'wechat-frozen-input-extraction-v1'
            or extraction.get('status') != 'VERIFIED'
            or extraction.get('package_id') != binding.get('package_id')
            or extraction.get('input_digest') != binding.get('input_digest')
            or extraction.get('package_zip_sha256_trusted') != binding.get('package_sha256_declared')
            or extraction.get('package_zip_sha256_observed') != binding.get('package_sha256_observed')
            or extraction.get('frozen_manifest_member') != 'manifest.json'
            or extraction.get('frozen_manifest_sha256_observed') != digest(manifest_data)
            or extraction.get('review_contract_version') != 'wechat-event-dispositions-v1'
            or manifest.get('manifest_version') != 'chat-materials-ocr-v2'
            or manifest_path.rsplit('/', 1)[-1] != extraction.get('frozen_manifest_member')):
        raise ArchiveError('FROZEN_INPUT_RECEIPT_IDENTITY_MISMATCH')
    ident, source_refs = _bind_manifest(binding, manifest, manifest_path)
    frozen_root = str(PurePosixPath(manifest_path).parent)

    members = extraction.get('members')
    if (not isinstance(members, list) or type(extraction.get('zip_member_count')) is not int
            or len(members) != extraction.get('zip_member_count')
            or len(members) > 10000 or extraction.get('zip_members_all_extracted_and_verified') is not True):
        raise ArchiveError('FROZEN_INPUT_MEMBER_INVENTORY_INVALID')
    seen = set()
    inventory = []
    member_identity = {}
    for member in members:
        if (not isinstance(member, dict) or set(member) != {'name', 'bytes', 'sha256'}
                or type(member.get('bytes')) is not int or member['bytes'] < 0):
            raise ArchiveError('FROZEN_INPUT_MEMBER_INVENTORY_INVALID')
        name = relative_path(member.get('name'))
        if name in seen:
            raise ArchiveError('FROZEN_INPUT_MEMBER_INVENTORY_INVALID')
        seen.add(name)
        member_sha = _sha(member.get('sha256'))
        try:
            read_bytes(reader.archive_root, str(PurePosixPath(frozen_root) / name),
                       member_sha, member['bytes'], limit=MAX_FROZEN_MEMBER)
        except ArchiveError as exc:
            if exc.code == 'SOURCE_MISSING':
                raise ArchiveError('FROZEN_INPUT_MEMBER_MISSING') from exc
            if exc.code in ('HASH_MISMATCH', 'SIZE_MISMATCH'):
                raise ArchiveError('FROZEN_INPUT_MEMBER_HASH_MISMATCH') from exc
            raise
        member_identity[name] = (member['bytes'], member_sha)
        inventory.append({'name': name, 'bytes': member['bytes'], 'sha256': member_sha})
    inventory_sha = digest(json.dumps(inventory, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))
    if extraction.get('zip_member_inventory_sha256') != inventory_sha:
        raise ArchiveError('FROZEN_INPUT_MEMBER_INVENTORY_HASH_MISMATCH')
    if ('manifest.json' not in seen
            or member_identity.get('manifest.json') != (len(manifest_data), digest(manifest_data))):
        raise ArchiveError('FROZEN_INPUT_MANIFEST_MEMBER_MISMATCH')

    descriptor = manifest.get('input_descriptor')
    descriptor_entries = descriptor.get('sources') if isinstance(descriptor, dict) else None
    declared_sources = extraction.get('descriptor_sources')
    if (not isinstance(descriptor_entries, list) or not isinstance(declared_sources, list)
            or len(declared_sources) != len(descriptor_entries)
            or type(extraction.get('descriptor_source_count')) is not int
            or type(extraction.get('descriptor_sources_verified')) is not int
            or extraction.get('descriptor_source_count') != len(descriptor_entries)
            or extraction.get('descriptor_sources_verified') != len(descriptor_entries)
            or extraction.get('complete_source_paths') is not True):
        raise ArchiveError('FROZEN_INPUT_DESCRIPTOR_SOURCES_INVALID')
    for expected, archived in zip(descriptor_entries, declared_sources):
        if (not isinstance(archived, dict) or archived.get('status') != 'VERIFIED'
                or archived.get('source_id') != expected.get('source_id')
                or archived.get('path') != expected.get('path')
                or archived.get('bytes') != expected.get('bytes')
                or archived.get('sha256') != expected.get('sha256')):
            raise ArchiveError('FROZEN_INPUT_DESCRIPTOR_SOURCES_INVALID')
        if archived['path'] not in member_identity:
            raise ArchiveError('FROZEN_INPUT_DESCRIPTOR_SOURCE_MISSING')
        if member_identity[archived['path']] != (archived['bytes'], archived['sha256']):
            raise ArchiveError('FROZEN_INPUT_DESCRIPTOR_SOURCE_HASH_MISMATCH')
        source_ref = source_refs['source_' + archived['source_id']]
        source_ref['path'] = str(PurePosixPath(frozen_root) / archived['path'])

    manifest_csv = next((source for source in descriptor_entries
                         if isinstance(source, dict) and source.get('source_id') == 'IMAGE_MANIFEST'), None)
    if not isinstance(manifest_csv, dict) or manifest_csv.get('path') not in member_identity:
        raise ArchiveError('FROZEN_INPUT_IMAGE_MANIFEST_MISSING')
    image_manifest_sha = member_identity[manifest_csv['path']][1]
    if manifest.get('manifest_sha256') != image_manifest_sha:
        raise ArchiveError('FROZEN_INPUT_IMAGE_MANIFEST_HASH_MISMATCH')

    images = manifest.get('images')
    declared_images = extraction.get('ordered_original_images')
    image_count = manifest.get('total_images')
    if (not isinstance(images, list) or not isinstance(declared_images, list)
            or type(image_count) is not int or len(images) != image_count
            or len(declared_images) != image_count or type(extraction.get('image_count')) is not int
            or extraction.get('image_count') != image_count
            or extraction.get('ordered_original_images_verified') is not True):
        raise ArchiveError('FROZEN_INPUT_ORDERED_IMAGES_INVALID')
    for index, (image, archived) in enumerate(zip(images, declared_images), 1):
        if (not isinstance(image, dict) or not isinstance(archived, dict)
                or image.get('idx') != index or archived.get('idx') != index
                or image.get('path') != archived.get('path')
                or image.get('bytes') != archived.get('bytes')
                or image.get('sha256') != archived.get('sha256')
                or archived.get('status') != 'VERIFIED'
                or archived['path'] not in member_identity):
            raise ArchiveError('FROZEN_INPUT_ORDERED_IMAGES_INVALID')
        if member_identity[archived['path']] != (archived['bytes'], archived['sha256']):
            raise ArchiveError('FROZEN_INPUT_ORDERED_IMAGE_HASH_MISMATCH')

    summary = parse_json(returned['summary'], 'INVALID_SUMMARY')
    return_id = _report_identity(returned['report'], summary, binding)
    if (summary.get('schema_version') != 2
            or summary.get('review_contract_version') != 'wechat-event-dispositions-v1'
            or summary.get('package_id') != binding.get('package_id')
            or summary.get('input_digest') != binding.get('input_digest')
            or summary.get('manifest_sha256') != image_manifest_sha
            or not return_id or summary.get('return_id') != return_id):
        raise ArchiveError('FROZEN_INPUT_SUMMARY_IDENTITY_MISMATCH')
    try:
        coverage = list(csv.DictReader(io.StringIO(returned['coverage'].decode('utf-8-sig'), newline='')))
    except (UnicodeError, csv.Error) as exc:
        raise ArchiveError('FROZEN_INPUT_EVENT_DISPOSITIONS_INVALID') from exc
    event_sources = {str(row.get('source_index') or '') for row in coverage if row.get('event') == 'EVENT'}
    dispositions = summary.get('event_dispositions')
    allowed = {'PROMOTE', 'HOLD', 'REJECT', 'CANNOT_CONFIRM'}
    if (not isinstance(dispositions, dict) or set(dispositions) != event_sources
            or any(not isinstance(value, str) or value not in allowed
                   for value in dispositions.values())):
        raise ArchiveError('FROZEN_INPUT_EVENT_DISPOSITIONS_INVALID')

    # Optional legacy manifest arguments may corroborate the strict reference,
    # but never replace it.
    return ({'path': manifest_path, 'sha256': manifest_sha}, ident, source_refs)


def make_snapshot(receipt: dict, refs: dict, *, receipt_sha: str, indexed_at: str,
                  manifest_identity: dict | None, return_id: str | None) -> dict:
    binding = receipt.get('binding')
    if not isinstance(binding,dict):
        raise ArchiveError('INVALID_BINDING')
    ident = manifest_identity or {}
    issues = []
    def text(key, fallback=None):
        return _text(ident.get(key, fallback))
    url = text('original_url',binding.get('article_url'))
    link = safe_url(url)
    if not link: issues.append('ARTICLE_URL_UNCONFIRMED')
    article_date = text('article_date',binding.get('article_date'))
    if article_date:
        try: valid_date(article_date)
        except ArchiveError:
            issues.append('ARTICLE_DATE_INVALID'); article_date = None
    pub_raw = text('published_at',binding.get('published_at'))
    pub = aware_time(pub_raw)
    if not pub: issues.append('PUBLISHED_AT_UNCONFIRMED')
    if pub and article_date and datetime.fromisoformat(pub.replace('Z','+00:00')).strftime('%Y%m%d') != article_date:
        raise ArchiveError('IDENTITY_CONFLICT_PUBLISHED_DATE')
    received = aware_time(receipt.get('received_at'))
    if not received: issues.append('RECEIVED_AT_UNCONFIRMED')
    if pub and received and datetime.fromisoformat(pub.replace('Z','+00:00')) > datetime.fromisoformat(received.replace('Z','+00:00')):
        issues.append('PUBLISHED_AFTER_RECEIVED_CONFLICT')
    account = text('account',binding.get('account'))
    if not account: issues.append('ACCOUNT_UNCONFIRMED')
    input_digest = _text(binding.get('input_digest'))
    if input_digest: _sha(input_digest)
    missing = [name for key,name in FILES.items() if key not in refs]
    declared_missing = receipt.get('missing_artifacts', [])
    if not isinstance(declared_missing,list): raise ArchiveError('INVALID_RECEIPT_MISSING_LIST')
    if set(declared_missing) != set(missing): issues.append('RECEIPT_MISSING_LIST_MISMATCH')
    local = receipt.get('local_acceptance') or {}
    if not isinstance(local,dict): raise ArchiveError('INVALID_LOCAL_ACCEPTANCE')
    scope = local.get('independent_review_scope') or []
    if not isinstance(scope,list): raise ArchiveError('INVALID_REVIEW_SCOPE')
    declared_structure = _text(receipt.get('structured_validation_status')) or 'UNKNOWN'
    binding_state = _text(binding.get('package_identity_status')) or 'UNKNOWN'
    if binding_state == 'VERIFIED':
        binding_state = ('RECEIPT_BOUND' if _trusted_input_binding(binding, input_digest)
                         and not missing and local.get('input_binding_valid') is True
                         else 'RETURN_UNBOUND')
    archive_state = _text(receipt.get('status'), 128) or 'UNKNOWN'
    if set(refs) == {'report'}:
        archive_state = 'REPORT_ONLY_ARCHIVED'
    elif missing:
        archive_state = 'REPORT_WITH_STRUCTURED_PARTIAL'
    if archive_state != receipt.get('status'):
        issues.append('RECEIPT_ARCHIVE_STATE_CONFLICT')
    if missing: issues.append('STRUCTURED_ARTIFACTS_MISSING')
    if not manifest_identity: issues.append('FROZEN_INPUT_NOT_REGISTERED')
    issues.extend(['RESEARCH_NOT_INDEPENDENTLY_VERIFIED', 'AVAILABLE_AT_NOT_ESTABLISHED'])
    return {
        'article': {'article_id':text('article_id',binding.get('article_id')), 'title':text('title',binding.get('article_title')),
                    'account':account,'biz':text('biz',binding.get('biz')),'url':link,
                    'article_date':article_date,'published_at':pub,
                    'metadata_origin':'BOUND_FROZEN_MANIFEST' if manifest_identity else 'IMPORT_RECEIPT'},
        'identity':{'package_id':_text(binding.get('package_id')), 'source_run_id':_text(binding.get('source_run_id')),
                    'input_digest':input_digest,'return_id':return_id, 'receipt_sha256':receipt_sha,
                    'package_sha256':_text(binding.get('package_sha256_observed')),
                    'package_sha256_status':_text(binding.get('package_sha256_status')) or 'UNKNOWN',
                    'manifest_sha256':_text(binding.get('package_manifest_sha256_observed'))},
        'received_at':received,'indexed_at':indexed_at,'available_at':None,
        'states':{'archive':archive_state, 'input_binding':binding_state,
                  'structure':'MISSING' if missing else declared_structure,
                  'research_review':'NOT_EVALUATED_STAGE_A'},
        'receipt_claims':{'archive':receipt.get('status','UNKNOWN'), 'structure':declared_structure,
                          'bytes_archived':local.get('bytes_archived') is True,
                          'input_binding_valid':local.get('input_binding_valid') is True,
                          'structure_valid':local.get('structure_valid') is True,
                          'chat_claimed_complete':local.get('chat_claimed_complete') is True,
                          'semantic_research_accepted':local.get('semantic_research_accepted') is True,
                          'independent_review_scope':[str(v)[:500] for v in scope]},
        'missing_artifacts':missing,'cannot_confirm':issues,
        'source_status':'BOUND_MANIFEST_REGISTERED' if manifest_identity else 'NOT_REGISTERED',
        'origin':_text(receipt.get('report_origin')) or 'UNKNOWN',
        'archive_owner':'WECHAT_LOCAL_ARCHIVE','write_policy':'READ_ONLY',**SAFETY,
    }


class WechatResearchArchive:
    def __init__(self, archive_root: Path | str | None, index_root: Path | str):
        self.archive_root = Path(archive_root).expanduser().absolute() if archive_root else None
        self.index_root = Path(index_root).expanduser().absolute()

    def require_roots(self):
        if self.archive_root is None:
            raise ArchiveError('NOT_CONFIGURED', 503)
        if (self.archive_root == self.index_root or self.archive_root in self.index_root.parents
                or self.index_root in self.archive_root.parents):
            raise ArchiveError('INDEX_MUST_NOT_OVERLAP_ARCHIVE')

    def prepare(self, receipt: str, receipt_sha256: str, *, manifest: str | None = None,
                manifest_sha256: str | None = None,
                require_frozen_input: bool = False) -> dict:
        self.require_roots()
        relative_path(receipt)
        raw = read_bytes(self.archive_root, receipt, receipt_sha256)
        rec = parse_json(raw,'INVALID_RECEIPT')
        binding = rec.get('binding')
        if not isinstance(binding,dict): raise ArchiveError('INVALID_BINDING')
        refs = _refs(rec, receipt)
        returned = {k:read_bytes(self.archive_root, v['path'], v['sha256'],v['bytes'],MAX_REPORT if k=='report' else MAX_ARTIFACT)
                    for k,v in refs.items()}
        summary = None
        summary_invalid = False
        if 'summary' in returned:
            try: summary=parse_json(returned['summary'],'INVALID_SUMMARY')
            except ArchiveError:
                summary_invalid = True  # Keep raw bytes, but do not display a contradicted COMPLETE claim.
        rid = _report_identity(returned['report'], summary, binding)
        ident, source_refs = None, {}
        manifest_ref = None
        if require_frozen_input:
            strict_ref, ident, source_refs = _strict_frozen_input(self, receipt, rec, refs, returned)
            if manifest or manifest_sha256:
                if not manifest or not manifest_sha256:
                    raise ArchiveError('MANIFEST_REF_INCOMPLETE')
                supplied_path = relative_path(manifest)
                supplied_sha = _sha(manifest_sha256)
                if supplied_path != strict_ref['path'] or supplied_sha != strict_ref['sha256']:
                    raise ArchiveError('FROZEN_INPUT_MANIFEST_REF_CONFLICT')
            manifest_ref = strict_ref
            manifest_data = read_bytes(self.archive_root, manifest_ref['path'], manifest_ref['sha256'],
                                       limit=MAX_JSON)
            source_refs['source_INPUT_MANIFEST'] = {'path':manifest_ref['path'],
                'sha256':manifest_ref['sha256'],'bytes':len(manifest_data),
                'filename':PurePosixPath(manifest_ref['path']).name,'kind':'FROZEN_INPUT'}
        elif manifest or manifest_sha256:
            if not manifest or not manifest_sha256: raise ArchiveError('MANIFEST_REF_INCOMPLETE')
            manifest_data = read_bytes(self.archive_root,manifest,manifest_sha256)
            mf=parse_json(manifest_data,'INVALID_MANIFEST')
            ident,source_refs=_bind_manifest(binding,mf,manifest)
            manifest_ref={'path':manifest,'sha256':manifest_sha256}
            source_refs['source_INPUT_MANIFEST'] = {'path':manifest,'sha256':manifest_sha256,
                'bytes':len(manifest_data),'filename':PurePosixPath(manifest).name,'kind':'FROZEN_INPUT'}
        indexed_at=datetime.now(timezone.utc).isoformat()
        snapshot=make_snapshot(rec,refs,receipt_sha=receipt_sha256,indexed_at=indexed_at,manifest_identity=ident,return_id=rid)
        if summary_invalid:
            snapshot['cannot_confirm'].append('SUMMARY_JSON_UNREADABLE')
            snapshot['states']['structure'] = 'INVALID_SUMMARY_JSON'
        # received/index time and paths are NOT content version identities.
        fingerprint={'binding':{k:binding.get(k) or None for k in ('package_id','source_run_id','input_digest','article_url','article_id','article_title','article_date','content_hash','package_sha256_observed')},
                     'return_id':rid,'files':{k:{'sha256':v['sha256'],'bytes':v['bytes']} for k,v in refs.items()}}
        record_id=digest(canonical(fingerprint))
        snapshot['record_id']=record_id
        return {'schema_version':INDEX_SCHEMA,'record_id':record_id,'fingerprint':fingerprint,
                'archive_root':str(self.archive_root),'receipt':{'path':receipt,'sha256':receipt_sha256},
                'manifest':manifest_ref,'snapshot':snapshot,'snapshot_sha256':digest(canonical(snapshot)),'artifacts':{**refs,**source_refs}, **SAFETY}

    def _records(self) -> list[dict]:
        self.require_roots()
        try:
            with directory(self.index_root/'records') as fd:
                names=sorted(os.listdir(fd))
        except ArchiveError as exc:
            if exc.code=='SOURCE_MISSING': return []
            raise
        names=[n for n in names if not n.startswith('.tmp-')]
        if len(names)>MAX_RECORDS: raise ArchiveError('INDEX_LIMIT_EXCEEDED',503)
        records=[]
        for name in names:
            if not re.fullmatch(r'[0-9a-f]{64}\.json',name): raise ArchiveError('INDEX_INVALID',503)
            records.append(self._record(name[:-5]))
        return records

    def _record(self, record_id: str) -> dict:
        if not SHA.fullmatch(record_id): raise ArchiveError('INVALID_RECORD_ID',422)
        try:
            record=parse_json(read_bytes(self.index_root,'records/'+record_id+'.json'), 'INDEX_INVALID')
        except ArchiveError as exc:
            if exc.code=='SOURCE_MISSING': raise ArchiveError('RECORD_NOT_FOUND',404) from exc
            raise
        if (record.get('schema_version')!=INDEX_SCHEMA or record.get('record_id')!=record_id
                or digest(canonical(record.get('fingerprint')))!=record_id
                or record.get('archive_root')!=str(self.archive_root)
                or not isinstance(record.get('snapshot'),dict)
                or record.get('snapshot_sha256')!=digest(canonical(record.get('snapshot')))
                or not isinstance(record.get('receipt'),dict)
                or not isinstance(record.get('artifacts'),dict)):
            raise ArchiveError('INDEX_INVALID',503)
        return record

    def _inspect(self, record: dict, *, include_report: bool) -> dict:
        card=json.loads(json.dumps(record['snapshot']))
        card.update(SAFETY)
        report={'status':'SOURCE_MISSING','content':None}
        artifacts=[]
        try:
            rr=record['receipt']
            rec=parse_json(read_bytes(self.archive_root,rr['path'],rr['sha256']),'INVALID_RECEIPT')
            expected_refs=_refs(rec,rr['path'])
            if record.get('manifest'):
                mr=record['manifest']
                manifest_data = read_bytes(self.archive_root,mr['path'],mr['sha256'])
                mf=parse_json(manifest_data,'INVALID_MANIFEST')
                _, sources=_bind_manifest(rec['binding'],mf,mr['path'])
                expected_refs.update(sources)
                expected_refs['source_INPUT_MANIFEST'] = {'path':mr['path'],'sha256':mr['sha256'],
                    'bytes':len(manifest_data),'filename':PurePosixPath(mr['path']).name,'kind':'FROZEN_INPUT'}
            if expected_refs!=record['artifacts']:
                raise ArchiveError('INDEX_INVALID')
        except (ArchiveError, KeyError, TypeError) as exc:
            reason=exc.code if isinstance(exc,ArchiveError) else 'INDEX_INVALID'
            card['states']['archive']='QUARANTINED'
            card['cannot_confirm']=sorted(set(card['cannot_confirm']+[reason]))
            return {'schema_version':SCHEMA,'status':'QUARANTINED','material':card,
                    'report':{'status':reason,'content':None},'artifacts':[],**SAFETY}
        for role, ref in record['artifacts'].items():
            item={'artifact_id':role,'filename':ref['filename'],'sha256':ref['sha256'],
                  'bytes':ref['bytes'],'kind':ref['kind'],'status':'NOT_RECHECKED'}
            # All returned files checked live. Source images only opened on demand.
            if ref['kind']=='CHAT_RETURN':
                try:
                    data=read_bytes(self.archive_root,ref['path'],ref['sha256'],ref['bytes'],MAX_REPORT if role=='report' else MAX_ARTIFACT)
                    item['status']='HASH_MATCH'
                    if role=='report':
                        report={'status':'READABLE','content':None}
                        try:
                            text = data.decode('utf-8-sig')
                            if include_report: report['content'] = text
                        except UnicodeError:
                            report['status'] = 'TEXT_UNREADABLE'
                except ArchiveError as exc:
                    item['status']=exc.code
                    card['cannot_confirm'].append(f'{role}:{exc.code}')
                    if role=='report': report={'status':exc.code,'content':None}
                    else: card['states']['structure']='NOT_CURRENTLY_VERIFIABLE'
            artifacts.append(item)
        if report['status']!='READABLE':
            card['states']['archive']='REPORT_UNAVAILABLE'
        return {'schema_version':SCHEMA,'status':'READY' if report['status']=='READABLE' else 'PARTIAL',
                'material':card,'report':report,'artifacts':artifacts,**SAFETY}

    def detail(self, record_id: str) -> dict:
        self.require_roots()
        return self._inspect(self._record(record_id),include_report=True)

    def artifact(self, record_id: str, artifact_id: str) -> tuple[bytes,str,str]:
        self.require_roots()
        record=self._record(record_id)
        inspected=self._inspect(record,include_report=False)
        if inspected['status']=='QUARANTINED':
            raise ArchiveError('QUARANTINED')
        if artifact_id not in record['artifacts']:
            raise ArchiveError('ARTIFACT_NOT_FOUND',404)
        ref=record['artifacts'][artifact_id]
        data=read_bytes(self.archive_root,ref['path'],ref['sha256'],ref['bytes'],MAX_REPORT if artifact_id=='report' else MAX_ARTIFACT)
        # Never render attacker-controlled HTML/SVG or follow embedded resources.
        mime='text/plain; charset=utf-8' if artifact_id=='report' else 'application/octet-stream'
        name=FILES.get(artifact_id,artifact_id+'.bin')
        return data,name,mime

    @staticmethod
    def _article_key(record: dict) -> tuple[str, str]:
        card = record.get('snapshot') or {}
        article = card.get('article') or {}
        # URL is retained for legacy receipts where article_id is absent.  A
        # bound article_id is preferred when no URL was preserved.
        identity = article.get('url') or article.get('article_id') or article.get('title') or ''
        return str(identity), str(article.get('article_date') or '')

    @staticmethod
    def _received_key(record: dict) -> tuple[float, str]:
        card = record.get('snapshot') or {}
        value = card.get('received_at')
        try:
            stamp = datetime.fromisoformat(str(value).replace('Z', '+00:00')).timestamp()
        except (TypeError, ValueError, OverflowError):
            stamp = float('-inf')
        return stamp, str(record.get('record_id') or '')

    def _latest_article_records(self, date: str) -> list[dict]:
        """Pick one receipt per exact article/date before reading its bytes."""
        selected = [record for record in self._records()
                    if (record.get('snapshot') or {}).get('article', {}).get('article_date') == date]
        latest: dict[tuple[str, str], dict] = {}
        for record in selected:
            key = self._article_key(record)
            previous = latest.get(key)
            if previous is None or self._received_key(record) > self._received_key(previous):
                latest[key] = record
        return sorted(latest.values(), key=lambda item: self._received_key(item), reverse=True)

    def _mention_summary(self, record: dict, counts: dict) -> tuple[str, dict | None]:
        """Check optional summary identity/counts without trusting its claims."""
        ref = record.get('artifacts', {}).get('summary')
        if not ref:
            return 'CANNOT_CONFIRM', None
        data, _name, _mime = self.artifact(record['record_id'], 'summary')
        summary = parse_json(data, 'SUMMARY_INVALID')
        card = record.get('snapshot') or {}
        article = card.get('article') or {}
        identity = card.get('identity') or {}
        for key, expected in (
            ('url', article.get('url')),
            ('article_date', article.get('article_date')),
            ('package_id', identity.get('package_id')),
            ('input_digest', identity.get('input_digest')),
            ('return_id', identity.get('return_id')),
        ):
            value = summary.get(key)
            if value is not None and expected is not None and value != expected:
                raise ArchiveError('IDENTITY_CONFLICT_SUMMARY')
        declared = summary.get('mentions_counts')
        if declared is not None:
            if not isinstance(declared, dict):
                raise ArchiveError('SUMMARY_INVALID')
            expected_counts = {
                'total': counts['rows'],
                'A': counts['market_rows']['A'],
                'BJ': counts['market_rows']['BJ'],
                'HK': counts['market_rows']['HK'],
                'entities': counts['issuers'],
                'source_named_entities': counts['source_named_entities'],
                'supplemental_listing_rows': counts['supplemental_listing_rows'],
            }
            for key, expected in expected_counts.items():
                if key in declared and declared[key] != expected:
                    raise ArchiveError('MENTIONS_COUNT_MISMATCH')
        status = summary.get('status', 'CANNOT_CONFIRM')
        if not isinstance(status, str) or not status:
            raise ArchiveError('SUMMARY_INVALID')
        return status, summary

    def _mention_document(self, record: dict) -> dict:
        """Read one indexed version, failing closed on any live tamper."""
        inspected = self._inspect(record, include_report=False)
        if inspected['status'] == 'QUARANTINED':
            raise ArchiveError('QUARANTINED', 409)
        artifacts = {item['artifact_id']: item for item in inspected['artifacts']}
        for artifact in artifacts.values():
            # A selected version is immutable.  Do not fall back to an older
            # record if any returned byte of this version changed or vanished.
            if artifact['kind'] == 'CHAT_RETURN' and artifact['status'] != 'HASH_MATCH':
                raise ArchiveError(artifact['status'], 409)
        mention = artifacts.get('mentions')
        if mention is None:
            return {'status': 'MISSING', 'record': record, 'material': inspected['material'],
                    'raw_rows': [], 'counts': None, 'summary_status': 'CANNOT_CONFIRM',
                    'summary': None, 'provenance': []}
        # Structured mentions are research evidence only when the importer
        # established a trusted receipt binding.  Report-only records remain
        # the explicit MISSING result above, but an unbound mentions.csv must
        # never become READY through either date or record-id lookup.
        states = inspected['material'].get('states') or {}
        if states.get('input_binding') != 'RECEIPT_BOUND':
            raise ArchiveError('RETURN_UNBOUND', 409)
        data, filename, _mime = self.artifact(record['record_id'], 'mentions')
        rows, counts = _parse_mentions(data)
        summary_status, summary = self._mention_summary(record, counts)
        provenance = {'record_id': record['record_id'], 'artifact_id': 'mentions',
                      'filename': filename, 'sha256': mention['sha256'],
                      'bytes': mention['bytes'], 'status': mention['status']}
        return {'status': 'READY', 'record': record, 'material': inspected['material'],
                'raw_rows': rows, 'counts': counts, 'summary_status': summary_status,
                'summary': summary, 'provenance': [provenance]}

    def list_mentions(self, *, record_id: str | None = None, date: str | None = None,
                      date_basis: str = 'article', market: str | None = None,
                      q: str = '', cursor: str | None = None, limit: int = 50) -> dict:
        """Return receipt-bound, deduplicated mention rows for the UI.

        This endpoint is deliberately separate from preselection pools.  It
        exposes no score/rank fields and never writes or mutates a stage input.
        """
        if date is not None:
            valid_date(date)
        if date_basis != 'article' or (date is None and record_id is None):
            raise ArchiveError('INVALID_QUERY', 422)
        if market is not None and market not in MENTION_MARKETS:
            raise ArchiveError('INVALID_QUERY', 422)
        if not isinstance(q, str) or len(q) > 500 or type(limit) is not int or not 1 <= limit <= 100:
            raise ArchiveError('INVALID_QUERY', 422)
        q = q.strip()
        query = {'record_id': record_id, 'date': date, 'date_basis': date_basis,
                 'market': market, 'q': q, 'limit': limit}
        base = {'schema_version': MENTIONS_SCHEMA, 'query': query,
                'date_basis': 'article', 'article_date': date, 'timezone': 'Asia/Shanghai',
                'status': 'NOT_INDEXED', 'record_id': record_id, 'record_ids': [],
                'material': None, 'materials': [], 'items': [], 'rows': [],
                'total': 0, 'returned': 0, 'next_cursor': None,
                'counts': None, 'provenance': [], 'summary_status': 'CANNOT_CONFIRM',
                'missing_artifacts': [],
                'cannot_confirm': ['ARCHIVE_NOT_INDEXED'], **SAFETY}
        if self.archive_root is None:
            base['status'] = 'NOT_CONFIGURED'
            base['cannot_confirm'] = ['NOT_CONFIGURED']
            return base
        if record_id is not None:
            records = [self._record(record_id)]
        else:
            records = self._latest_article_records(date or '')
        if not records:
            base['status'] = 'NOT_INDEXED'
            base['cannot_confirm'] = [f'NO_ARTICLE_ARCHIVE:{date or record_id}']
            return base

        documents = [self._mention_document(record) for record in records]
        ready = [doc for doc in documents if doc['status'] == 'READY']
        first = documents[0]
        material_cards = [doc['material'] for doc in documents]
        base.update({
            'record_id': first['record']['record_id'] if len(documents) == 1 else None,
            'record_ids': [doc['record']['record_id'] for doc in documents],
            'material': first['material'], 'materials': material_cards,
            'article_date': (first['material'].get('article') or {}).get('article_date'),
        })
        if not ready:
            base['status'] = 'MISSING'
            base['missing_artifacts'] = ['mentions']
            base['cannot_confirm'] = sorted({reason for doc in documents
                                              for reason in doc['material'].get('cannot_confirm', [])}
                                             | {'STRUCTURED_MENTIONS_MISSING'})
            return base

        raw_rows = [row for doc in ready for row in doc['raw_rows']]
        counts = _mention_counts(raw_rows)
        deduped = _deduplicate_mentions(raw_rows)
        if market:
            deduped = [row for row in deduped if row['market'] == market]
        if q:
            folded = q.casefold()
            deduped = [row for row in deduped if folded in ' '.join(
                str(row.get(key) or '') for key in (
                    'market', 'code', 'name', 'entity_id', 'mapping_status',
                    'source_named_or_derived', 'listing_origin', 'source_index',
                    'source_indexes', 'source_names', 'claim_context', 'claim_contexts',
                )).casefold()]
        revisions = [{'record_id': doc['record']['record_id'],
                      'mentions_sha256': doc['provenance'][0]['sha256']} for doc in ready]
        revision = digest(canonical(revisions))
        offset = 0
        if cursor:
            try:
                token = parse_json(base64.urlsafe_b64decode(cursor + '=' * ((-len(cursor)) % 4)),
                                   'INVALID_CURSOR')
                if token.get('query') != query or token.get('revision') != revision:
                    raise ArchiveError('CURSOR_STALE', 409)
                offset = token.get('offset')
                if type(offset) is not int or offset < 0:
                    raise ArchiveError('INVALID_CURSOR', 422)
            except ArchiveError:
                raise
            except (ValueError, KeyError, TypeError) as exc:
                raise ArchiveError('INVALID_CURSOR', 422) from exc
        if offset > len(deduped):
            raise ArchiveError('INVALID_CURSOR', 422)
        page = deduped[offset:offset + limit]
        next_offset = offset + len(page)
        next_cursor = None
        if next_offset < len(deduped):
            next_cursor = base64.urlsafe_b64encode(canonical(
                {'query': query, 'revision': revision, 'offset': next_offset})).decode().rstrip('=')
        cannot = {reason for doc in ready for reason in doc['material'].get('cannot_confirm', [])}
        summary_statuses = sorted({doc['summary_status'] for doc in ready})
        if any(status == 'PARTIAL_WITH_UNREADABLE' for status in summary_statuses):
            cannot.add('PARTIAL_WITH_UNREADABLE')
        cannot.add('ISSUER_MAPPING_NOT_INDEPENDENTLY_VERIFIED')
        provenance = [entry for doc in ready for entry in doc['provenance']]
        base.update({
            'status': 'READY', 'items': page, 'rows': page, 'total': len(deduped),
            'returned': len(page), 'next_cursor': next_cursor,
            'counts': counts, 'market_totals': counts['market_listings'],
            'summary_status': summary_statuses[0] if len(summary_statuses) == 1 else summary_statuses,
            'provenance': provenance, 'index_revision': revision,
            'cannot_confirm': sorted(cannot),
            'missing_artifacts': [],
        })
        return base

    def list_materials(self, *, date: str | None = None, date_basis: str = 'article',
                       q: str = '', cursor: str | None = None, limit: int = 20) -> dict:
        if date is not None: valid_date(date)
        if date_basis not in ('article','received') or type(limit) is not int or not 1<=limit<=50:
            raise ArchiveError('INVALID_QUERY',422)
        if not isinstance(q,str) or len(q)>500: raise ArchiveError('INVALID_QUERY',422)
        query={'date':date,'date_basis':date_basis,'q':q.strip(),'limit':limit}
        base={'schema_version':SCHEMA,'query':query,'timezone':'Asia/Shanghai',
              'items':[],'total':0,'returned':0,'next_cursor':None,'index_revision':None,**SAFETY}
        if self.archive_root is None: return {**base,'status':'NOT_CONFIGURED'}
        records=self._records()
        revision=digest(canonical(records))
        base['index_revision']=revision
        offset=0
        if cursor:
            try:
                token=parse_json(base64.urlsafe_b64decode(cursor+'='*((-len(cursor))%4)),'INVALID_CURSOR')
                if token.get('query')!=query: raise ArchiveError('INVALID_CURSOR',422)
                if token.get('revision')!=revision: raise ArchiveError('CURSOR_STALE',409)
                offset=token['offset']
                if type(offset) is not int or offset<0: raise ArchiveError('INVALID_CURSOR',422)
            except (ValueError,KeyError) as exc:
                if isinstance(exc,ArchiveError) and exc.code=='CURSOR_STALE': raise
                raise ArchiveError('INVALID_CURSOR',422) from exc
        def date_for(card):
            if date_basis=='article': return card['article']['article_date']
            t=card['received_at']
            return datetime.fromisoformat(t.replace('Z','+00:00')).astimezone(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%d') if t else None
        selected=[]
        for r in records:
            c=r['snapshot']
            hay=' '.join(str(v or '') for v in [*c['article'].values(),*c['identity'].values()]).casefold()
            if (date is None or date_for(c)==date) and query['q'].casefold() in hay:
                selected.append(r)
        selected.sort(key=lambda r:(datetime.fromisoformat(r['snapshot']['received_at'].replace('Z','+00:00')).timestamp()
                                    if r['snapshot']['received_at'] else float('-inf'),r['record_id']),reverse=True)
        if offset>len(selected): raise ArchiveError('INVALID_CURSOR',422)
        items=[self._inspect(r,include_report=False)['material'] for r in selected[offset:offset+limit]]
        next_offset=offset+len(items)
        nxt=None
        if next_offset<len(selected):
            nxt=base64.urlsafe_b64encode(canonical({'query':query,'revision':revision,'offset':next_offset})).decode().rstrip('=')
        return {**base,'status':'READY' if records else 'NOT_INDEXED','items':items,'total':len(selected),
                'returned':len(items),'next_cursor':nxt}
