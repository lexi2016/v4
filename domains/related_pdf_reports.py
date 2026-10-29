"""Read-only, non-PIT candidate associations over V4's verified PDF reader.

No acquisition, OCR, selection, or trading decisions occur here.  Matches are
textual evidence, not certified report subjects.  A batch shares one scan.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

try:
    from domains.report_subjects import report_title_evidence
except ModuleNotFoundError as error:
    if error.name != "domains.report_subjects":
        raise
    # Without the optional title-role parser, keep every hit as a neutral text
    # candidate.  This avoids asserting a report subject from a mere mention.
    report_title_evidence = None
from domains.related_pdf_cursor import (CURSORS, PriorDocument, MAX_CURRENT_PAGE_BYTES,
                                      MAX_PRIOR_BYTES, MAX_PRIOR_DOCUMENTS, CURSOR_TTL_SECONDS)
from infrastructure import zsxq_pdf_ingestion as pdf_owner
from upstreams.v3_shared_data.shared_data.store import StoreError

SAFETY = {"research_only": True, "production_allowed": False,
          "buy_gate_updated": False, "orders_sent": False}
MAX_SYMBOLS = 250
DEFAULT_DOCUMENTS = 5
MAX_DOCUMENTS = 10
DEFAULT_DATES = 1
MAX_DATES = 2
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_HINT_NAME = re.compile(r"[\u3400-\u9fffA-Za-z0-9·* .&\-]{2,32}\Z")
_CJK_INTERCHAR_SPACES = re.compile(r"(?<=[\u3400-\u9fff]) +(?=[\u3400-\u9fff])")
_CODE_IN_TEXT = re.compile(
    r"(?<![A-Za-z0-9])(?:(?P<prefix>SH|SZ|BJ|A|HK)\s*\.\s*)?"
    r"(?P<digits>\d{1,6})(?:\s*\.\s*(?P<suffix>SH|SZ|BJ|HK))?"
    r"(?![A-Za-z0-9])", re.I)


def _day(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{8}", value):
        raise ValueError("IDENTITY_DATE_INVALID")
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError as error:
        raise ValueError("IDENTITY_DATE_INVALID") from error
    return value


def _symbol(value: str) -> dict[str, str | None]:
    raw = str(value or "").strip().upper()
    a = re.fullmatch(r"(?:(A|SH|SZ|BJ)\.(\d{6})|(\d{6})\.(SH|SZ|BJ))", raw)
    if a:
        exchange = a.group(1) or a.group(4)
        digits = a.group(2) or a.group(3)
        return {"symbol": "A." + digits, "market": "A", "code": digits,
                "exchange": None if exchange == "A" else exchange}
    hk = re.fullmatch(r"(?:HK\.(\d{1,5})|(\d{1,5})\.HK)", raw)
    if hk:
        digits = (hk.group(1) or hk.group(2)).zfill(5)
        return {"symbol": "HK." + digits, "market": "HK", "code": digits, "exchange": "HK"}
    raise ValueError("SYMBOL_INVALID")


def _load_identity(root: Path | str | None, day: str, symbol: Mapping[str, Any], *,
                   loader_cache: dict[str, Any] | None = None) -> dict[str, Any]:
    """Use exact-date verified V4 registries. Names are never supplied by callers."""
    result: dict[str, Any] = {"status": "CANNOT_CONFIRM", "name": None, "witnesses": [],
                              "reason": "EXACT_DATE_IDENTITY_NOT_AVAILABLE"}
    if root is None:
        return result
    observations: list[dict[str, Any]] = []
    if symbol["market"] == "A":
        from upstreams.v3_shared_data.shared_data.a_share_security_master import (
            load_current_display_names, load_verified_a_share_security_master)
        for label, loader in (("A_SHARE_SELECTOR_MASTER", load_verified_a_share_security_master),
                              ("A_SHARE_DISPLAY_NAME_ONLY", load_current_display_names)):
            try:
                if loader_cache is not None:
                    if label not in loader_cache:
                        try:
                            loader_cache[label] = loader(root, day)
                        except (StoreError, OSError, ValueError, KeyError, TypeError):
                            loader_cache[label] = None
                    loaded = loader_cache[label]
                    if loaded is None:
                        continue
                    rows, manifest = loaded
                else:
                    rows, manifest = loader(root, day)
                row = rows.get(symbol["code"])
                if row:
                    exchange = str(row.get("market") or row.get("exchange") or "").upper()
                    observations.append({"name": str(row.get("name") or "").strip(),
                        "exchange": exchange, "source": label, "date": day,
                        "run_id": manifest.get("run_id"), "artifact_sha256": manifest.get("artifact_sha256"),
                        "evidence_sha256": row.get("evidence_sha256"),
                        "observed_at": row.get("observed_at"), "available_at": row.get("available_at")})
            except (StoreError, OSError, ValueError, KeyError, TypeError):
                continue
    else:
        from upstreams.v3_shared_data.shared_data.hk_security_master import load_verified_hk_security_master_snapshot
        try:
            if loader_cache is not None:
                if "HK_SECURITY_MASTER_SNAPSHOT" not in loader_cache:
                    try:
                        loader_cache["HK_SECURITY_MASTER_SNAPSHOT"] = load_verified_hk_security_master_snapshot(root, day)
                    except (StoreError, OSError, ValueError, KeyError, TypeError):
                        loader_cache["HK_SECURITY_MASTER_SNAPSHOT"] = None
                loaded = loader_cache["HK_SECURITY_MASTER_SNAPSHOT"]
                if loaded is None:
                    return result
                rows, _manifest, witness = loaded
            else:
                rows, _manifest, witness = load_verified_hk_security_master_snapshot(root, day)
            row = rows.get(symbol["symbol"])
            if row:
                observations.append({"name": str(row.get("name") or "").strip(), "exchange": "HK",
                    "source": "HK_SECURITY_MASTER_SNAPSHOT", "date": day,
                    "run_id": witness.get("run_id"), "artifact_sha256": witness.get("artifact_sha256"),
                    "manifest_sha256": witness.get("manifest_sha256"),
                    "observed_at": row.get("captured_at"), "available_at": row.get("captured_at")})
        except (StoreError, OSError, ValueError, KeyError, TypeError):
            pass
    valid = [row for row in observations if len(row["name"]) >= 2 and row["exchange"] in {"SH", "SZ", "BJ", "HK"}]
    result["witnesses"] = observations
    names = {row["name"] for row in valid}
    exchanges = {row["exchange"] for row in valid}
    if not valid:
        return result
    if len(names) != 1 or len(exchanges) != 1 or (symbol["exchange"] and symbol["exchange"] not in exchanges):
        result["reason"] = "SECURITY_IDENTITY_CONFLICT"
        return result
    return {"status": "EXACT_DATE_SOURCE_VERIFIED_REFERENCE_ONLY", "name": next(iter(names)),
            "exchange": next(iter(exchanges)), "witnesses": valid, "reason": None,
            "pit_certified": False}


def _name_variants(identity: Mapping[str, Any]) -> list[str]:
    """Preserve the name and add only the Chinese intercharacter-space form.

    This is a search alias, not an identity assertion.  It does not alter
    English names or arbitrary punctuation and works with existing indexes.
    """
    name = identity.get("_search_name")
    if not isinstance(name, str) or not name:
        return []
    compact = _CJK_INTERCHAR_SPACES.sub("", name)
    return list(dict.fromkeys([name, compact]))


def _matches(text: str, symbol: Mapping[str, Any], identity: Mapping[str, Any]) -> list[dict[str, str]]:
    hits: list[dict[str, str]] = []
    target_exchange = identity.get("exchange") or symbol.get("exchange")
    for m in _CODE_IN_TEXT.finditer(text):
        prefix, suffix = (m.group("prefix") or "").upper(), (m.group("suffix") or "").upper()
        digits = m.group("digits")
        if prefix and suffix and prefix != suffix:
            continue
        marker = prefix or suffix
        if symbol["market"] == "HK" and (marker != "HK" or len(digits) > 5 or digits.zfill(5) != symbol['code']):
            continue  # A bare or mismatched number is not market-identified.
        if symbol["market"] == "A" and digits != symbol["code"]:
            continue
        if symbol["market"] == "A" and (marker == "HK" or (marker in {"SH", "SZ", "BJ"} and target_exchange and marker != target_exchange)):
            continue
        hits.append({"kind": "CODE_EXPLICIT_MARKET" if marker in {"SH", "SZ", "BJ", "HK"} else "CODE_MARKET_UNCONFIRMED",
                     "text": text[max(0, m.start()-55):min(len(text), m.end()+85)]})
    for name in _name_variants(identity):
        pos = text.find(name)
        if pos >= 0:
            hit = {"kind": str(identity.get("_search_kind") or "NAME_REFERENCE_ONLY"),
                   "text": text[max(0, pos-55):min(len(text), pos+len(name)+85)]}
            if name != identity.get("_search_name"):
                hit["name_match_form"] = "CJK_INTERCHAR_SPACE_REMOVED"
            hits.append(hit)
    return hits[:3]


def _safe(payload: Mapping[str, Any]) -> bool:
    return all(payload.get(key) is value for key, value in SAFETY.items())


def _title_role(text: str, symbol: Mapping[str, Any], identity: Mapping[str, Any]) -> str:
    if report_title_evidence is None:
        return "TITLE_OR_FILENAME_MENTION_CANDIDATE"
    info = report_title_evidence(text, "research_report")
    for subject in info["subjects"]:
        raw_matches = _matches(str(subject.get("raw_code") or ""), symbol, identity)
        if raw_matches:
            return "TITLE_SUBJECT_TEXT_CANDIDATE"
    if info.get("publisher") in _name_variants(identity):
        return "REPORT_PUBLISHER_TEXT_CANDIDATE"
    return "TITLE_OR_FILENAME_MENTION_CANDIDATE"


def _search_profiles(parsed: Mapping[str, Mapping[str, Any]], identities: Mapping[str, Mapping[str, Any]],
                     hints: Sequence[str]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    if len(hints) > MAX_SYMBOLS:
        raise ValueError("NAME_HINT_COUNT_INVALID")
    names_by_symbol: dict[str, set[str]] = {}
    for raw in hints:
        if not isinstance(raw, str) or len(raw) > 70 or raw.count(":") != 1:
            raise ValueError("NAME_HINT_INVALID")
        code, name = raw.split(":", 1)
        name = name.strip()
        if not _HINT_NAME.fullmatch(name) or not re.search(r"[\u3400-\u9fffA-Za-z]", name):
            raise ValueError("NAME_HINT_INVALID")
        hint_symbol = _symbol(code)
        key = str(hint_symbol["symbol"])
        if key not in parsed:
            raise ValueError("NAME_HINT_SYMBOL_NOT_REQUESTED")
        expected_exchange = parsed[key].get("exchange")
        if hint_symbol.get("exchange") and expected_exchange and hint_symbol["exchange"] != expected_exchange:
            raise ValueError("NAME_HINT_EXCHANGE_CONFLICT")
        names_by_symbol.setdefault(key, set()).add(name)
    profiles: dict[str, dict[str, Any]] = {}
    hint_status: dict[str, dict[str, Any]] = {}
    for key in parsed:
        identity = identities[key]
        profile = dict(identity)
        hints_for_symbol = names_by_symbol.get(key, set())
        verified_name = identity.get("name") if identity.get("status") == "EXACT_DATE_SOURCE_VERIFIED_REFERENCE_ONLY" else None
        if verified_name:
            profile.update(_search_name=verified_name, _search_kind="NAME_REFERENCE_ONLY")
            hint_status[key] = {"status": "VERIFIED_REFERENCE_PRECEDENCE" if hints_for_symbol else "NOT_PROVIDED", "name": None}
        elif identity.get("reason") == "SECURITY_IDENTITY_CONFLICT":
            hint_status[key] = {"status": "SUPPRESSED_IDENTITY_CONFLICT", "name": None}
        elif len(hints_for_symbol) > 1:
            hint_status[key] = {"status": "CONFLICTING_CALLER_HINTS", "name": None}
        elif hints_for_symbol:
            name = next(iter(hints_for_symbol))
            profile.update(_search_name=name, _search_kind="NAME_HINT_UNVERIFIED")
            hint_status[key] = {"status": "CALLER_PROVIDED_UNVERIFIED", "name": name}
        else:
            hint_status[key] = {"status": "NOT_PROVIDED", "name": None}
        profiles[key] = profile
    owners: dict[str, set[str]] = {}
    for key, profile in profiles.items():
        for name in _name_variants(profile):
            owners.setdefault(name, set()).add(key)
    for name, keys in owners.items():
        if len(keys) > 1:
            for key in keys:
                profiles[key].pop("_search_name", None)
                profiles[key].pop("_search_kind", None)
                hint_status[key] = {"status": "AMBIGUOUS_NAME_ACROSS_SYMBOLS", "name": name}
    return profiles, hint_status


def _revalidate_prior(data_root: Path | str, prior: tuple[PriorDocument, ...], reader: Any) -> None:
    """Recheck every previously emitted source with the original owner."""
    for item in prior:
        try:
            detail = reader.read_pdf_document_detail(Path(data_root), item.document_id, item.research_date)
            receipt = detail.get('receipt') or {}
            processing = detail.get('processing') or {}
            if (not isinstance(detail, Mapping) or not _safe(detail) or detail.get('status') != 'READY'
                or detail.get('schema_version') != 'v4.zsxq_pdf_document_detail.v1'
                or detail.get('document_id') != item.document_id or detail.get('research_date') != item.research_date
                or receipt.get('integrity') != 'SOURCE_PDF_AND_PAGE_HASHES_VERIFIED'
                or receipt.get('verified_pdf_sha256') != item.pdf_sha256 or receipt.get('sha256') != item.receipt_sha256
                or processing.get('verified_pdf_size') != item.pdf_size or processing.get('verified_pages_size') != item.pages_size):
                raise ValueError('prior detail mismatch')
        except Exception as error:
            raise ValueError('SEARCH_CURSOR_STALE') from error


def _indexed_result(data_root: Path | str, day: str, parsed: Mapping[str, Mapping[str, Any]],
                    identities: Mapping[str, Mapping[str, Any]], profiles: Mapping[str, Mapping[str, Any]],
                    hint_status: Mapping[str, Mapping[str, Any]], terms: Mapping[str, list[str]],
                    search: Mapping[str, Any], max_documents: int, cursor: str | None, reader: Any) -> dict[str, Any]:
    signature = hashlib.sha256(json.dumps({'data_root': str(Path(data_root).resolve()), 'identity_date': day, 'symbols': parsed, 'terms': terms,
        'identity': identities, 'hints': hint_status},
        ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    candidates = search['candidates']
    cursor_state = CURSORS.resolve(cursor, str(search['checkpoint_sha256']), signature, len(candidates)) if cursor else None
    offset = cursor_state.offset if cursor_state else 0
    prior = cursor_state.prior if cursor_state else ()
    chunk = []
    page_bytes = 0
    for candidate in candidates[offset:offset + max_documents]:
        pdf_size, pages_size = candidate.get('verified_pdf_size'), candidate.get('verified_pages_size')
        if type(pdf_size) is not int or type(pages_size) is not int or pdf_size < 1 or pages_size < 1:
            raise ValueError('SEARCH_INDEX_SIZE_INVALID')
        artifact_bytes = pdf_size + pages_size
        if page_bytes + artifact_bytes > MAX_CURRENT_PAGE_BYTES:
            break
        chunk.append(candidate)
        page_bytes += artifact_bytes
    if offset < len(candidates) and not chunk:
        raise ValueError('SEARCH_PAGE_ARTIFACT_LIMIT')
    grouped: dict[str, dict[str, dict[str, Any]]] = {key: {} for key in parsed}
    all_sources: dict[str, list[dict[str, Any]]] = {}
    gaps = list(search['coverage'].get('gaps') or [])
    verified = 0
    current_verified: dict[tuple[str, str], PriorDocument] = {}
    for candidate in chunk:
        doc_id, source_day = candidate['document_id'], candidate['research_date']
        try:
            detail = reader.read_pdf_document_detail(Path(data_root), doc_id, source_day)
        except (pdf_owner.ZsxqPdfError, OSError, ValueError) as error:
            gaps.append({'research_date': source_day, 'document_id': doc_id,
                         'reason': getattr(error, 'code', type(error).__name__)})
            continue
        if (not isinstance(detail, Mapping) or not _safe(detail) or detail.get('status') != 'READY'
            or detail.get('schema_version') != 'v4.zsxq_pdf_document_detail.v1'
            or detail.get('document_id') != doc_id or detail.get('research_date') != source_day
            or not isinstance(detail.get('receipt'), Mapping)
            or detail['receipt'].get('integrity') != 'SOURCE_PDF_AND_PAGE_HASHES_VERIFIED'
            or detail['receipt'].get('verified_pdf_sha256') != candidate.get('verified_pdf_sha256')
            or not isinstance(detail.get('source'), Mapping) or not isinstance(detail.get('processing'), Mapping)
            or detail['processing'].get('verified_pdf_size') != candidate.get('verified_pdf_size')
            or detail['processing'].get('verified_pages_size') != candidate.get('verified_pages_size')
            or not re.fullmatch(r'[0-9a-f]{64}', str(detail['receipt'].get('sha256') or ''))
            or not isinstance(detail.get('pages'), list)):
            gaps.append({'research_date': source_day, 'document_id': doc_id, 'reason': 'DOCUMENT_DETAIL_CONTRACT_INVALID'})
            continue
        verified += 1
        source, processing = detail['source'], detail['processing']
        pdf_sha = detail['receipt']['verified_pdf_sha256']
        current_verified[(source_day, doc_id)] = PriorDocument(doc_id, source_day, pdf_sha,
            detail['receipt']['sha256'], processing['verified_pdf_size'], processing['verified_pages_size'])
        record = {'document_id': doc_id, 'research_date': source_day, 'source_run_id': source.get('source_run_id'),
                  'topic_id': source.get('topic_id'), 'file_id': source.get('file_id'),
                  'topic_title': source.get('topic_title'), 'original_filename': source.get('original_filename'),
                  'source_topic_published_at': source.get('source_topic_published_at'),
                  'source_fetched_at': source.get('source_fetched_at'), 'pdf_published_at': source.get('pdf_published_at'),
                  'available_at': processing.get('available_at'), 'pit_status': processing.get('pit_status') or source.get('pit_status'),
                  'receipt_sha256': detail['receipt'].get('sha256')}
        all_sources.setdefault(pdf_sha, []).append(record)
        segments = [('topic_title', None, str(source.get('topic_title') or '')),
                    ('original_filename', None, str(source.get('original_filename') or ''))]
        segments += [('page', page.get('page_number'), str(page.get('text') or ''))
                     for page in detail['pages'] if isinstance(page, Mapping)]
        for key, symbol in parsed.items():
            evidence = []
            for location, page_number, text in segments:
                for hit in _matches(text, symbol, profiles[key]):
                    role = _title_role(text, symbol, profiles[key]) if location != 'page' else 'BODY_MENTION_CANDIDATE'
                    evidence.append({'location': location, 'page_number': page_number, 'role': role, **hit})
                if len(evidence) >= 8:
                    break
            if not evidence:
                continue
            report = grouped[key].setdefault(pdf_sha, {'relation_status': 'TEXT_CANDIDATE_NOT_SUBJECT_CONFIRMED',
                                                       'verified_pdf_sha256': pdf_sha, 'dedup_status': 'VERIFIED_PDF_BYTES', 'sources': []})
            report['sources'].append({**record, 'evidence': evidence[:8], 'text_match_in_source': True})
    stocks = []
    for key in parsed:
        for digest, report in grouped[key].items():
            found = {(s['research_date'], s['document_id']) for s in report['sources']}
            for source in all_sources[digest]:
                if (source['research_date'], source['document_id']) not in found:
                    report['sources'].append({**source, 'evidence': [], 'text_match_in_source': False})
        reports = list(grouped[key].values())
        stocks.append({'symbol': key, 'identity': identities[key], 'search_hint': hint_status[key],
                       'reports': reports, 'result_status': 'CANDIDATES_FOUND' if reports else 'NO_MATCH_IN_SCANNED_DOCUMENTS_COVERAGE_INCOMPLETE'})
    next_offset = offset + len(chunk)
    next_cursor = None
    checkpoint_valid = True
    if search['coverage'].get('indexed_documents', 0) > verified:
        gaps.append({'reason': 'NONRETURNED_ARTIFACTS_NOT_REVERIFIED_IN_THIS_REQUEST',
                     'count': search['coverage']['indexed_documents'] - verified})
    try:
        final = reader.query_pdf_search_index(Path(data_root), {})
        checkpoint_changed = final.get('checkpoint_sha256') != search.get('checkpoint_sha256')
        if checkpoint_changed:
            gaps.append({'reason': 'SEARCH_CHECKPOINT_CHANGED_DURING_READ'})
            checkpoint_valid = False
            for stock in stocks:
                stock['reports'] = []
                stock['result_status'] = 'CANNOT_CONFIRM'
        # Source status may change without an owner-index mutation.
        final_gaps = final.get('coverage', {}).get('gaps', [])
        gaps.extend(g for g in final_gaps if g not in gaps)
        invalid_runs = {g.get('source_run_id') for g in final_gaps if isinstance(g, Mapping) and g.get('source_run_id')}
        if invalid_runs and not checkpoint_changed:
            for stock in stocks:
                retained = []
                for report in stock['reports']:
                    report['sources'] = [source for source in report['sources'] if source.get('source_run_id') not in invalid_runs]
                    if report['sources']:
                        retained.append(report)
                stock['reports'] = retained
                stock['result_status'] = 'CANDIDATES_FOUND' if retained else 'NO_MATCH_IN_SCANNED_DOCUMENTS_COVERAGE_INCOMPLETE'
    except (OSError, ValueError, KeyError, TypeError) as error:
        gaps.append({'reason': 'SEARCH_CHECKPOINT_RECHECK_FAILED', 'error': type(error).__name__})
        checkpoint_valid = False
        for stock in stocks:
            stock['reports'] = []
            stock['result_status'] = 'CANNOT_CONFIRM'
    if cursor_state and checkpoint_valid:
        try:
            _revalidate_prior(data_root, prior, reader)
        except ValueError:
            CURSORS.invalidate(cursor)
            raise
    if not checkpoint_valid:
        CURSORS.invalidate(cursor)
    emitted = {(source['research_date'], source['document_id'])
               for stock in stocks for report in stock['reports'] for source in report['sources']}
    combined = {(item.research_date, item.document_id): item for item in prior}
    combined.update({key: current_verified[key] for key in emitted if key in current_verified})
    pagination_incomplete = False
    if checkpoint_valid and next_offset < len(candidates):
        cumulative = tuple(combined.values())
        if len(cumulative) > MAX_PRIOR_DOCUMENTS or sum(item.pdf_size + item.pages_size for item in cumulative) > MAX_PRIOR_BYTES:
            pagination_incomplete = True
            gaps.append({'reason': 'SEARCH_PAGINATION_VALIDATION_LIMIT', 'remaining_candidates': len(candidates) - next_offset})
        else:
            next_cursor = CURSORS.issue(str(search['checkpoint_sha256']), signature, next_offset, cumulative)
            gaps.append({'reason': 'SEARCH_PAGINATION_REQUIRED', 'remaining_candidates': len(candidates) - next_offset})
    coverage = {**search['coverage'], 'gaps': gaps, 'candidate_documents': len(candidates),
                'detail_attempts': len(chunk), 'verified_documents': verified, 'page_offset': offset,
                'indexed_content_time': 'VERIFIED_AT_LAST_INDEX_UPDATE',
                'limits': {'documents': max_documents, 'current_page_artifact_bytes': MAX_CURRENT_PAGE_BYTES,
                           'prior_documents': MAX_PRIOR_DOCUMENTS, 'prior_artifact_bytes': MAX_PRIOR_BYTES,
                           'cursor_ttl_seconds': CURSOR_TTL_SECONDS}, 'legacy_max_dates_ignored': True,
                'prior_revalidated': len(prior) if checkpoint_valid else 0,
                'pagination_incomplete': pagination_incomplete, 'pagination_required': next_cursor is not None}
    return {'schema_version': 'v4.related_pdf_reports.candidate.v1', 'status': 'PARTIAL',
            'search_mode': 'FULLTEXT_INDEX', 'identity_date': day, 'time_semantics': 'CURRENT_KNOWLEDGE_NON_PIT',
            'coverage': coverage, 'next_cursor': next_cursor, 'stocks': stocks, **SAFETY}


def read_related_pdf_reports(data_root: Path | str, identity_root: Path | str | None, *,
                             identity_date: str, symbols: Sequence[str], hints: Sequence[str] = (),
                             max_dates: int = DEFAULT_DATES, max_documents: int = DEFAULT_DOCUMENTS,
                             cursor: str | None = None,
                             identity_reader: Callable[..., dict[str, Any]] = _load_identity,
                             reader: Any = pdf_owner) -> dict[str, Any]:
    day = _day(identity_date)
    if not symbols or len(symbols) > MAX_SYMBOLS:
        raise ValueError("SYMBOL_COUNT_INVALID")
    if type(max_dates) is not int or not 1 <= max_dates <= MAX_DATES or type(max_documents) is not int or not 1 <= max_documents <= MAX_DOCUMENTS:
        raise ValueError("SCAN_LIMIT_INVALID")
    parsed: dict[str, dict[str, Any]] = {}
    for requested in symbols:
        item = _symbol(requested)
        key = str(item["symbol"])
        if key in parsed and parsed[key].get("exchange") and item.get("exchange") and parsed[key]["exchange"] != item["exchange"]:
            raise ValueError("SYMBOL_EXCHANGE_CONFLICT")
        if key not in parsed or item.get("exchange"):
            parsed[key] = item
    identity_cache: dict[str, Any] = {}
    identities = {key: (identity_reader(identity_root, day, item, loader_cache=identity_cache)
                         if identity_reader is _load_identity else identity_reader(identity_root, day, item))
                  for key, item in parsed.items()}
    profiles, hint_status = _search_profiles(parsed, identities, hints)
    terms = {}
    for key, symbol in parsed.items():
        codes = [str(symbol['code'])]
        if symbol['market'] == 'HK':
            short = str(symbol['code']).lstrip('0') or '0'
            codes.append(short if len(short) >= 2 else 'HK')
        terms[key] = list(dict.fromkeys(codes + _name_variants(profiles[key])))
    search_gaps: list[dict[str, Any]] = []
    if hasattr(reader, 'query_pdf_search_index'):
        try:
            search = reader.query_pdf_search_index(Path(data_root), terms)
            if search.get('status') != 'NOT_MATERIALIZED':
                return _indexed_result(data_root, day, parsed, identities, profiles, hint_status,
                                       terms, search, max_documents, cursor, reader)
            search_gaps = list(search.get('coverage', {}).get('gaps') or [])
        except (OSError, ValueError, KeyError, TypeError) as error:
            if str(error) in {'SEARCH_CURSOR_STALE', 'SEARCH_CURSOR_INVALID'}:
                raise
            search_gaps = [{'reason': 'SEARCH_INDEX_READ_FAILED', 'error': type(error).__name__}]
    if hasattr(reader, 'query_pdf_search_index'):
        if cursor is not None:
            raise ValueError('SEARCH_CURSOR_STALE')
        # A GET may query an existing derived index, but it must not fall back
        # to enumerating every source date/document or performing excerpt OCR
        # when that index is absent.  Return the gap and let its existing
        # owner decide separately whether to build it.
        return {
            'schema_version': 'v4.related_pdf_reports.candidate.v1',
            'status': 'NOT_MATERIALIZED',
            'search_mode': 'NOT_MATERIALIZED',
            'identity_date': day,
            'time_semantics': 'CURRENT_KNOWLEDGE_NON_PIT',
            'coverage': {
                'scope': 'PREBUILT_SEARCH_INDEX_ONLY',
                'dates_scanned': [],
                'candidate_documents': 0,
                'detail_attempts': 0,
                'verified_documents': 0,
                'page_offset': 0,
                'gaps': search_gaps or [{'reason': 'SEARCH_INDEX_NOT_MATERIALIZED'}],
            },
            'next_cursor': None,
            'stocks': [
                {'symbol': key, 'identity': identities[key], 'search_hint': hint_status[key], 'reports': []}
                for key in parsed
            ],
            **SAFETY,
        }
    if cursor is not None:
        raise ValueError('SEARCH_CURSOR_STALE')
    by_stock: dict[str, dict[str, Any]] = {key: {"symbol": key, "identity": identities[key],
                                                 "search_hint": hint_status[key], "reports": []} for key in parsed}
    scope = reader.read_pdf_index_scope(Path(data_root))
    gaps: list[dict[str, Any]] = search_gaps + list(scope.get("gaps") or [])
    dates = list(scope.get("dates") or [])
    if len(dates) > max_dates:
        gaps.append({"reason": "DATE_LIMIT_REACHED", "available": len(dates), "selected": max_dates})
        dates = dates[-max_dates:]
    dates = list(reversed(dates))  # Latest indexed source dates first, not publication order.
    scanned_dates: list[str] = []
    counters = Counter()
    unavailable_reasons: Counter[tuple[str, str]] = Counter()
    seen_documents: set[tuple[str, str]] = set()
    grouped: dict[str, dict[str, dict[str, Any]]] = {key: {} for key in parsed}
    all_sources: dict[str, list[dict[str, Any]]] = {}
    gaps.append({"reason": "EXCERPT_SHORTLIST_CAN_MISS_MIDDLE_PAGES"})
    for source_day in dates:
        scanned_dates.append(source_day)
        projection = reader.read_pdf_ingestion_projection(Path(data_root), source_day)
        if not isinstance(projection, Mapping) or not _safe(projection) or projection.get("research_date") != source_day:
            gaps.append({"research_date": source_day, "reason": "PROJECTION_CONTRACT_INVALID"})
            continue
        for reason in projection.get("cannot_confirm") or []:
            gaps.append({"research_date": source_day, "reason": str(reason)})
        for row in projection.get("items") or []:
            if not isinstance(row, Mapping):
                gaps.append({"research_date": source_day, "reason": "PROJECTION_ITEM_INVALID"})
                continue
            doc_id = str(row.get("document_id") or "")
            key = (source_day, doc_id)
            if key in seen_documents:
                continue
            seen_documents.add(key)
            counters["indexed_documents"] += 1
            if row.get("status") != "READY" or row.get("can_open_detail") is not True:
                counters["unavailable_documents"] += 1
                reason = str(row.get("reason_code") or row.get("status") or "DOCUMENT_UNAVAILABLE")
                unavailable_reasons[(source_day, reason)] += 1
                continue
            projected_source = row.get("source") or {}
            if not isinstance(projected_source, Mapping):
                gaps.append({"research_date": source_day, "document_id": doc_id, "reason": "PROJECTION_SOURCE_INVALID"})
                continue
            shortlist_text = "\n".join(str(value or "") for value in (
                projected_source.get("topic_title"), projected_source.get("original_filename"),
                row.get("excerpt"), row.get("last_page_excerpt")))
            if not any(_matches(shortlist_text, symbol, profiles[key]) for key, symbol in parsed.items()):
                counters["not_shortlisted_documents"] += 1
                continue
            counters["shortlisted_documents"] += 1
            if counters["detail_attempts"] >= max_documents:
                counters["shortlisted_not_verified_limit"] += 1
                continue
            counters["detail_attempts"] += 1
            try:
                detail = reader.read_pdf_document_detail(Path(data_root), doc_id, source_day)
            except (pdf_owner.ZsxqPdfError, OSError, ValueError) as error:
                counters["unavailable_documents"] += 1
                gaps.append({"research_date": source_day, "document_id": doc_id,
                             "reason": getattr(error, "code", type(error).__name__)})
                continue
            if (not isinstance(detail, Mapping) or not _safe(detail) or detail.get("status") != "READY"
                or detail.get("schema_version") != "v4.zsxq_pdf_document_detail.v1"
                or detail.get("document_id") != doc_id or detail.get("research_date") != source_day
                or not isinstance(detail.get("receipt"), Mapping)
                or detail["receipt"].get("integrity") != "SOURCE_PDF_AND_PAGE_HASHES_VERIFIED"):
                counters["unavailable_documents"] += 1
                gaps.append({"research_date": source_day, "document_id": doc_id, "reason": "DOCUMENT_DETAIL_CONTRACT_INVALID"})
                continue
            counters["verified_documents"] += 1
            pdf_sha = detail["receipt"].get("verified_pdf_sha256")
            if not isinstance(pdf_sha, str) or not _SHA.fullmatch(pdf_sha):
                pdf_sha = None
                gaps.append({"research_date": source_day, "document_id": doc_id, "reason": "VERIFIED_PDF_SHA_UNAVAILABLE"})
            source = detail.get("source") or {}
            processing = detail.get("processing") or {}
            if not isinstance(source, Mapping) or not isinstance(processing, Mapping) or not isinstance(detail.get("pages"), list):
                gaps.append({"research_date": source_day, "document_id": doc_id, "reason": "DOCUMENT_DETAIL_STRUCTURE_INVALID"})
                continue
            group_key = "sha256:" + pdf_sha if pdf_sha else f"unmerged:{source_day}:{doc_id}"
            source_record = {"document_id": doc_id, "research_date": source_day,
                "topic_id": source.get("topic_id"), "file_id": source.get("file_id"),
                "topic_title": source.get("topic_title"), "original_filename": source.get("original_filename"),
                "source_topic_published_at": source.get("source_topic_published_at"),
                "source_fetched_at": source.get("source_fetched_at"),
                "pdf_published_at": source.get("pdf_published_at"), "available_at": processing.get("available_at"),
                "pit_status": processing.get("pit_status") or source.get("pit_status"),
                "receipt_sha256": detail["receipt"].get("sha256")}
            all_sources.setdefault(group_key, []).append(source_record)
            segments = [("topic_title", None, str(source.get("topic_title") or "")),
                        ("original_filename", None, str(source.get("original_filename") or ""))]
            segments += [("page", page.get("page_number"), str(page.get("text") or ""))
                         for page in detail["pages"] if isinstance(page, Mapping)]
            for symbol_key, symbol in parsed.items():
                evidence: list[dict[str, Any]] = []
                for location, page_number, text in segments:
                    hits = _matches(text, symbol, profiles[symbol_key])
                    for hit in hits:
                        role = _title_role(text, symbol, profiles[symbol_key]) if location != "page" else "BODY_MENTION_CANDIDATE"
                        evidence.append({"location": location, "page_number": page_number, "role": role, **hit})
                    if len(evidence) >= 8:
                        break
                if not evidence:
                    continue
                report = grouped[symbol_key].setdefault(group_key, {"relation_status": "TEXT_CANDIDATE_NOT_SUBJECT_CONFIRMED",
                    "verified_pdf_sha256": pdf_sha, "dedup_status": "VERIFIED_PDF_BYTES" if pdf_sha else "CANNOT_CONFIRM",
                    "sources": []})
                report["sources"].append({**source_record, "evidence": evidence[:8], "text_match_in_source": True})
    gaps.extend({"research_date": source_day, "reason": reason, "count": count}
                for (source_day, reason), count in sorted(unavailable_reasons.items()))
    if counters["shortlisted_not_verified_limit"]:
        gaps.append({"reason": "DOCUMENT_LIMIT_REACHED", "limit": max_documents,
                     "unverified_candidates": counters["shortlisted_not_verified_limit"]})
    for symbol_key, item in by_stock.items():
        for group_key, report in grouped[symbol_key].items():
            found = {(s["research_date"], s["document_id"]) for s in report["sources"]}
            for source in all_sources[group_key]:
                if (source["research_date"], source["document_id"]) not in found:
                    report["sources"].append({**source, "evidence": [], "text_match_in_source": False})
        item["reports"] = list(grouped[symbol_key].values())
        item["result_status"] = "CANDIDATES_FOUND" if item["reports"] else "NO_MATCH_IN_SCANNED_DOCUMENTS_COVERAGE_INCOMPLETE"
    return {"schema_version": "v4.related_pdf_reports.candidate.v1", "status": "PARTIAL", "search_mode": "EXCERPT_CANARY", "next_cursor": None,
            "identity_date": day, "time_semantics": "CURRENT_KNOWLEDGE_NON_PIT",
            "coverage": {"scope": scope.get("scope"), "indexed_dates_seen": len(scope.get("dates") or []),
                         "dates_selected": dates, "dates_scanned": scanned_dates, **dict(counters),
                         "shortlist": "TITLE_FILENAME_FIRST_AND_LAST_EXCERPT_ONLY",
                         "limits": {"dates": max_dates, "documents": max_documents},
                         "gaps": gaps, "historical_sources_complete": False},
            "stocks": list(by_stock.values()), **SAFETY}
