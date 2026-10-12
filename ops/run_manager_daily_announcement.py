#!/usr/bin/env python3
"""Deterministic bridge for reviewed daily announcement owner products.

Capture and reading remain with the configured existing operator and the
restored heartbeat's human/agent readers. This command validates their exact
artifacts, builds the existing analysis projection, imports through the
ManagerResearch owner API, and verifies its readback.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse, urlunparse
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

APP_ROOT = Path(__file__).resolve().parents[1]
HKEX_DIRECTORY_REFRESH_TIMEOUT_SECONDS = 120
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from v4.manager_research.announcement_analysis import (
    _record_identity,
    _assert_catalog_readback,
    build_product,
    has_reader_declared_content_gap,
    product_path,
)
from v4.manager_research.announcement_selection import attach_extension, make_extension
from v4.manager_research.announcement_processing import (
    build_incremental_processing, process_saved_window, validate_preopen_window,
)
from v4.manager_research.workspace_announcements import (
    validate_agent_judgment_receipt,
    validate_owner_analysis_import_receipt,
    validate_terminal_body_capture,
)
from v4.manager_research.workspace_projection import FLAGS, date_token, digest


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req: Request, fp: Any, code: int,
                         msg: str, headers: Any, newurl: str) -> None:
        return None


def _load(path: str | Path) -> Any:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    return value


def _file_sha(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _publication_iso(value: str) -> str:
    token = value.replace("-", "") if isinstance(value, str) else ""
    try:
        iso = datetime.strptime(token, "%Y%m%d").strftime("%Y-%m-%d")
    except (TypeError, ValueError) as exc:
        raise ValueError("ANNOUNCEMENT_PUBLICATION_DATE_INVALID") from exc
    if value not in {iso, token}:
        raise ValueError("ANNOUNCEMENT_PUBLICATION_DATE_INVALID")
    return iso


def _write_exclusive(path: str | Path, value: Any) -> None:
    target = Path(path)
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open("xb") as stream:
            stream.write(raw)
    except FileExistsError:
        existing = json.loads(target.read_text(encoding="utf-8"))
        if existing != value:
            raise ValueError("ANNOUNCEMENT_CANDIDATE_OUTPUT_EXISTS_WITH_DIFFERENT_CONTENT")


def _build(args: argparse.Namespace, *, reviewed: bool, include_product: bool = False,
           terminal_body_capture: dict[str, Any] | None = None) -> dict[str, Any]:
    target = date_token(args.target_date)
    publication = args.publication_date
    if len(publication) == 8 and publication.isdigit():
        publication = f"{publication[:4]}-{publication[4:6]}-{publication[6:8]}"
    if len(publication) != 10 or publication[4] != "-":
        raise ValueError("ANNOUNCEMENT_PUBLICATION_DATE_INVALID")
    catalog_read = _load(args.catalog_read)
    semantic = _load(args.semantic_catalog)
    body = _load(args.body_corpus)
    if (catalog_read.get("target_trade_date") != target
            or catalog_read.get("publication_date") != publication
            or catalog_read.get("readback_status") != "VERIFIED"):
        raise ValueError("ANNOUNCEMENT_DAILY_CATALOG_DATE_OR_READBACK_MISMATCH")
    if terminal_body_capture is None and getattr(args, "body_capture_evidence_root", None):
        trusted_catalog = _assert_catalog_readback(catalog_read, target, publication)
        source_run_id = trusted_catalog.get("run_id")
        catalog_sha = trusted_catalog.get("sha256")
        if (not isinstance(source_run_id, str) or len(source_run_id) != 32
                or any(char not in "0123456789abcdef" for char in source_run_id)
                or catalog_sha != digest({key: value for key, value in trusted_catalog.items()
                    if key != "sha256"})
                or any(trusted_catalog.get(key) is not expected for key, expected in FLAGS.items())):
            raise ValueError("ANNOUNCEMENT_DAILY_CATALOG_RUN_ID_OR_SHA_INVALID")
        expected_run_id = _evidence_run_id(target, publication, dict(trusted_catalog))
        capture_path = Path(args.body_capture_evidence_root) / "capture_receipt.json"
        if capture_path.is_symlink() or not capture_path.is_file():
            raise ValueError("ANNOUNCEMENT_BODY_CAPTURE_ARTIFACT_MISSING")
        capture_receipt = _load(capture_path)
        if (not isinstance(capture_receipt, dict)
                or capture_receipt.get("evidence_run_id") != expected_run_id):
            raise ValueError("ANNOUNCEMENT_BODY_CAPTURE_RUN_ID_MISMATCH")
        terminal_body_capture = validate_terminal_body_capture(
            Path(args.body_capture_evidence_root), catalog_read, target, publication,
            expected_run_id=expected_run_id)
    if (any(isinstance(row, dict) and row.get("body_status") == "BODY_CAPTURE_FAILED"
            for row in body.get("rows", [])) and terminal_body_capture is None):
        raise ValueError("ANNOUNCEMENT_BODY_CAPTURE_TERMINAL_EVIDENCE_REQUIRED")
    semantic_sha = _file_sha(args.semantic_catalog)
    body_sha = _file_sha(args.body_corpus)
    verified_inputs = [
        {"name": "semantic_catalog", "sha256": semantic_sha,
         "canonical_sha256": digest(semantic), "row_count": semantic.get("row_count")},
        {"name": "body_corpus", "sha256": body_sha,
         "canonical_sha256": digest(body), "row_count": body.get("article_count")},
    ]
    product = build_product(semantic, body, catalog_read,
        semantic_sha256=semantic_sha, body_sha256=body_sha,
        verified_inputs=verified_inputs, pdf_derivative_sha256s={},
        target_trade_date=target, publication_date=publication,
        terminal_body_capture=terminal_body_capture)
    if getattr(args, 'decisions', None):
        decisions_value = _load(args.decisions)
        decisions = decisions_value.get("article_decisions") if isinstance(decisions_value, dict) else decisions_value
        if not isinstance(decisions, list):
            raise ValueError("ANNOUNCEMENT_HANDOFF_DECISIONS_INVALID")
        unassessed_identities = {_record_identity(row) for row in semantic.get("records", [])
                            if isinstance(row, dict) and has_reader_declared_content_gap(row)}
        if terminal_body_capture is not None:
            unassessed_identities.update(("art_code", row.get("art_code"))
                for row in terminal_body_capture.get("failed_articles", [])
                if isinstance(row, dict) and isinstance(row.get("art_code"), str))
        by_identity = {_record_identity(row): row for row in decisions if isinstance(row, dict)}
        if any(by_identity.get(identity, {}).get("disposition") != "NOT_ASSESSED"
               for identity in unassessed_identities):
            raise ValueError("ANNOUNCEMENT_UNASSESSED_CONTENT_SELECTION_MUST_BE_NOT_ASSESSED")
        extension = make_extension(product, decisions)
        product = attach_extension(product, extension)
    if reviewed:
        receipt = _load(args.review_receipt)
        receipt = validate_agent_judgment_receipt(receipt, {**product, "agent_judgment_receipt": receipt})
        product["agent_judgment_receipt"] = receipt
        # The judgment receipt changes the base product identity. Rebind the
        # same decisions to that final base before validating or writing it.
        selection_extension = product.pop("stock_selection", None)
        product.pop("sha256", None)
        product["sha256"] = digest(product)
        if selection_extension is not None:
            product = attach_extension(product,
                make_extension(product, selection_extension["article_decisions"]))
        validate_agent_judgment_receipt(receipt, product)
        _write_exclusive(args.out, product)
    result = {
        "status": "BUILT_REVIEWED_CANDIDATE" if reviewed else "PREPARED_EXACT_INPUTS",
        "target_trade_date": target,
        "publication_date": publication,
        "product_sha256": product["sha256"],
        "catalog_product_sha256": product["source_manifest"]["catalog_product_sha256"],
        "semantic_catalog_file_sha256": semantic_sha,
        "body_corpus_file_sha256": body_sha,
        "decision_status": receipt["decision_status"] if reviewed else "NOT_ASSESSED",
        "decision_count": receipt["article_decision_count"] if reviewed else 0,
        "body_capture_status": terminal_body_capture.get("status") if terminal_body_capture else None,
        "body_capture_failed_article_count": len(terminal_body_capture.get("failed_articles", []))
            if terminal_body_capture else 0,
        "output": str(Path(args.out).resolve()) if reviewed else None,
        **FLAGS,
    }
    if include_product:
        result["product"] = product
    return result


def _local_api(api_base: str) -> tuple[str, str]:
    parsed = urlparse(api_base)
    if (parsed.scheme not in {"http", "https"} or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
            or parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment):
        raise ValueError("ANNOUNCEMENT_IMPORT_API_MUST_BE_LOOPBACK")
    base = api_base.rstrip("/")
    origin = urlunparse((parsed.scheme, parsed.netloc, "", "", "", ""))
    return base, origin


def _monthly_connect_eligibility(target: str) -> dict[str, Any]:
    """Read or once-capture the current-month native V2 Connect authority."""
    from datetime import timezone
    from zoneinfo import ZoneInfo

    hk_now = datetime.now(ZoneInfo("Asia/Hong_Kong"))
    if target[:6] != hk_now.strftime("%Y%m"):
        raise ValueError("HK_CONNECT_MONTHLY_TARGET_OUTSIDE_CURRENT_MONTH")
    cutoff = datetime.now(timezone.utc)
    cutoff_iso = cutoff.astimezone(ZoneInfo("Asia/Hong_Kong")).isoformat(timespec="microseconds")
    root_text = os.environ.get("V4_MANAGER_UNIVERSE_ROOT", "").strip()
    universe_root = Path(root_text).expanduser() if root_text else Path(
        "/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/"
        "v3_shared_data/.runtime/data")
    if (not universe_root.is_absolute() or universe_root.is_symlink()
            or universe_root.resolve() != universe_root or not universe_root.is_dir()):
        raise ValueError("HK_CONNECT_MONTHLY_AUTHORITY_ROOT_INVALID")
    owner_root_text = os.environ.get("V4_MANAGER_UNIVERSE_OWNER_ROOT", "").strip()
    owner_sha = os.environ.get("V4_MANAGER_UNIVERSE_OWNER_SHA256", "").strip()
    owner_root = Path(owner_root_text).expanduser() if owner_root_text else APP_ROOT
    owner_source = owner_root / "stage_center" / "hk_universe_preflight.py"
    if (not owner_root.is_absolute() or owner_root.is_symlink()
            or owner_root.resolve() != owner_root or owner_source.is_symlink()
            or not owner_source.is_file()):
        raise ValueError("HK_CONNECT_MONTHLY_AUTHORITY_OWNER_INVALID")
    actual_owner_sha = _file_sha(owner_source)
    if owner_sha and owner_sha != actual_owner_sha:
        raise ValueError("HK_CONNECT_MONTHLY_AUTHORITY_OWNER_SHA_MISMATCH")
    if not owner_sha:
        owner_sha = actual_owner_sha
    if not re.fullmatch(r"[0-9a-f]{64}", owner_sha):
        raise ValueError("HK_CONNECT_MONTHLY_AUTHORITY_OWNER_SHA_INVALID")

    from domains.manager_research_evidence import read_universe_evidence

    universe_root_path = universe_root.resolve(strict=True)
    month_root = universe_root_path / "universes"
    date_candidates = []
    if month_root.is_dir() and not month_root.is_symlink():
        for path in month_root.iterdir():
            if (path.is_dir() and not path.is_symlink()
                    and re.fullmatch(r"\d{8}", path.name)
                    and path.name[:6] == target[:6]
                    and path.name <= hk_now.strftime("%Y%m%d")
                    and (path / "HK_CONNECT_FULL_MARKET.json").exists()):
                date_candidates.append(path.name)

    invalid_candidates: list[dict[str, str]] = []
    selected = None
    for source_date in sorted(date_candidates, reverse=True):
        try:
            universe = read_universe_evidence(universe_root_path, source_date,
                as_of=cutoff, clock=lambda: cutoff, authority_owner_root=owner_root,
                authority_owner_sha256=owner_sha, require_v2=True)
            source = dict(universe.source)
            if (source.get("source_date") != source_date
                    or source.get("market") != "HK_CONNECT"
                    or source.get("role") != "HK_CONNECT_FULL_MARKET_AUTHORITY"):
                raise ValueError("HK_CONNECT_MONTHLY_SOURCE_DATE_OR_ROLE_INVALID")
            acquired = datetime.fromisoformat(str(source.get("acquired_at", "")).replace("Z", "+00:00"))
            available = datetime.fromisoformat(str(source.get("available_at", "")).replace("Z", "+00:00"))
            if (acquired.tzinfo is None or available.tzinfo is None
                    or acquired > available or available > cutoff):
                raise ValueError("HK_CONNECT_MONTHLY_SOURCE_TIME_INVALID")
            codes = sorted(set(universe.codes))
            if not codes or any(not isinstance(code, str) or not re.fullmatch(r"HK\.\d{5}", code)
                                for code in codes):
                raise ValueError("HK_CONNECT_MONTHLY_CODES_INVALID")
            refs = ("artifact_ref", "manifest_ref", "receipt_ref", "current_ref",
                    "capture_ref", "publication_ref")
            file_hashes = {}
            for key in refs:
                ref = source.get(key)
                if not isinstance(ref, str) or not ref or "\\" in ref or ".." in Path(ref).parts:
                    raise ValueError("HK_CONNECT_MONTHLY_AUTHORITY_REFERENCE_INVALID")
                path = universe_root_path / ref
                if path.is_symlink() or not path.is_file():
                    raise ValueError("HK_CONNECT_MONTHLY_AUTHORITY_FILE_MISSING_OR_SYMLINK")
                file_hashes[key] = _file_sha(path)
            selected = (source_date, source, codes, file_hashes)
            break
        except Exception as exc:
            reason = str(exc)
            invalid_candidates.append({"source_date": source_date,
                "error_code": reason[:180] if re.fullmatch(r"[A-Z0-9_:. -]{1,180}", reason) else type(exc).__name__})

    if selected is not None and invalid_candidates:
        raise ValueError("HK_CONNECT_MONTHLY_NEWER_CANDIDATE_UNVERIFIED")

    if selected is None:
        if invalid_candidates:
            raise ValueError("HK_CONNECT_MONTHLY_LATEST_CANDIDATE_UNVERIFIED")
        if target != hk_now.strftime("%Y%m%d"):
            raise ValueError("HK_CONNECT_MONTHLY_SNAPSHOT_MISSING_FOR_TARGET_MONTH")
        local_contract_sha = _file_sha(APP_ROOT / "stage_center" / "hk_universe_preflight.py")
        if owner_sha != local_contract_sha:
            raise ValueError("HK_CONNECT_MONTHLY_CAPTURE_OWNER_DOES_NOT_MATCH_LOCAL_V2_CONTRACT")
        from ops._macos_research_panel_daily_parts.hk_market_capture import capture_hk_connect_monthly_membership
        capture_hk_connect_monthly_membership(trade_date=target, store_root=universe_root_path,
            shared_package_root=APP_ROOT / "upstreams" / "v3_shared_data",
            futu_python=Path(sys.executable))
        cutoff = datetime.now(timezone.utc)
        cutoff_iso = cutoff.astimezone(ZoneInfo("Asia/Hong_Kong")).isoformat(timespec="microseconds")
        universe = read_universe_evidence(universe_root_path, target, as_of=cutoff,
            clock=lambda: cutoff, authority_owner_root=owner_root,
            authority_owner_sha256=owner_sha, require_v2=True)
        source = dict(universe.source)
        if source.get("source_date") != target or source.get("market") != "HK_CONNECT":
            raise ValueError("HK_CONNECT_MONTHLY_CAPTURE_READBACK_INVALID")
        codes = sorted(set(universe.codes))
        refs = ("artifact_ref", "manifest_ref", "receipt_ref", "current_ref",
                "capture_ref", "publication_ref")
        file_hashes = {}
        for key in refs:
            ref = source.get(key)
            if not isinstance(ref, str) or not ref or "\\" in ref or ".." in Path(ref).parts:
                raise ValueError("HK_CONNECT_MONTHLY_CAPTURE_AUTHORITY_REFERENCE_INVALID")
            path = universe_root_path / ref
            if path.is_symlink() or not path.is_file():
                raise ValueError("HK_CONNECT_MONTHLY_CAPTURE_AUTHORITY_FILE_INVALID")
            file_hashes[key] = _file_sha(path)
        selected = (target, source, codes, file_hashes)

    source_date, source, codes, file_hashes = selected
    material = {
        "schema_version": "v4.manager_research.hk_connect_monthly_eligibility.v1",
        "status": "VERIFIED", "policy": "CALENDAR_MONTH_LATEST_VERIFIED_V2",
        "month": target[:6], "target_trade_date": target,
        "source_date": source_date, "capture_cutoff_at": cutoff_iso,
        "source": source, "authority_file_sha256s": file_hashes,
        "code_count": len(codes), "codes_sha256": digest(codes), "codes": codes,
        "invalid_newer_candidates": invalid_candidates, **FLAGS,
    }
    return {**material, "identity_sha256": digest(material)}


def _request(api_base: str, path: str, *, method: str = "GET", payload: bytes | None = None,
             timeout_seconds: float = 20) -> dict[str, Any]:
    if (isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float))
            or timeout_seconds <= 0 or timeout_seconds > 180):
        raise ValueError("ANNOUNCEMENT_IMPORT_API_TIMEOUT_INVALID")
    base, origin = _local_api(api_base)
    headers = {"Accept": "application/json"}
    if payload is not None:
        headers.update({"Content-Type": "application/json", "Origin": origin})
    elif method.upper() == "POST":
        headers["Origin"] = origin
    request = Request(base + path, data=payload, headers=headers, method=method)
    opener = build_opener(ProxyHandler({}), _NoRedirect())
    try:
        with opener.open(request, timeout=timeout_seconds) as response:
            if response.status not in {200, 201}:
                raise ValueError("ANNOUNCEMENT_IMPORT_API_HTTP_STATUS_" + str(response.status))
            raw = response.read(16 * 1024 * 1024 + 1)
            if len(raw) > 16 * 1024 * 1024:
                raise ValueError("ANNOUNCEMENT_IMPORT_API_RESPONSE_TOO_LARGE")
    except HTTPError as exc:
        raise ValueError("ANNOUNCEMENT_IMPORT_API_HTTP_ERROR_" + str(exc.code)) from exc
    except URLError as exc:
        raise ValueError("ANNOUNCEMENT_IMPORT_API_UNAVAILABLE") from exc
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("ANNOUNCEMENT_IMPORT_API_RESPONSE_INVALID")
    return value


def _refresh_hkex_daily_directory(api_base: str, path: str) -> dict[str, Any]:
    """Give the synchronously paged full-day source capture a bounded wait."""
    return _request(api_base, path, method="POST",
        timeout_seconds=HKEX_DIRECTORY_REFRESH_TIMEOUT_SECONDS)


def _prior_hkex_daily_directory_run_ids(readback: Any, target: str) -> set[str]:
    """Return the exact-day run IDs visible immediately before this capture."""
    if (not isinstance(readback, dict)
            or readback.get("target_trade_date") != target
            or readback.get("daily_publication_date") != target
            or readback.get("publication_timezone") != "Asia/Hong_Kong"
            or readback.get("status") == "READBACK_FAILED"):
        raise ValueError("ANNOUNCEMENT_DAILY_HKEX_PRECAPTURE_READBACK_INVALID")
    coverage = readback.get("coverage")
    if not isinstance(coverage, dict):
        raise ValueError("ANNOUNCEMENT_DAILY_HKEX_PRECAPTURE_COVERAGE_INVALID")
    products = coverage.get("market_directory_products")
    if products is None and readback.get("status") == "NOT_RUN":
        return set()
    if not isinstance(products, list):
        raise ValueError("ANNOUNCEMENT_DAILY_HKEX_PRECAPTURE_PRODUCTS_INVALID")
    run_ids: set[str] = set()
    for product in products:
        if not isinstance(product, dict):
            raise ValueError("ANNOUNCEMENT_DAILY_HKEX_PRECAPTURE_PRODUCT_INVALID")
        if (product.get("source_scope") != "HKEX_OFFICIAL_FULL_MARKET_DIRECTORY_V1"
                or product.get("from_date") != target or product.get("to_date") != target
                or product.get("window_mode") != "HK_CALENDAR_DAY_V1"):
            continue
        run_id = product.get("product_run_id")
        if (not isinstance(run_id, str) or re.fullmatch(r"[0-9a-f]{32}", run_id) is None
                or run_id in run_ids):
            raise ValueError("ANNOUNCEMENT_DAILY_HKEX_PRECAPTURE_PRODUCT_ID_INVALID")
        run_ids.add(run_id)
    return run_ids


def _verified_hkex_current_attempt(readback: Any, target: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Bind a daily projection to its signed, exact-day owner attempt."""
    attempt = readback.get("attempt") if isinstance(readback, dict) else None
    if not isinstance(attempt, dict):
        raise ValueError("ANNOUNCEMENT_DAILY_HKEX_CURRENT_ATTEMPT_PRODUCT_BINDING_INVALID")
    unsigned_attempt = {key: value for key, value in attempt.items() if key != "sha256"}
    attempt_sha256 = attempt.get("sha256")
    started_at = attempt.get("started_at")
    finished_at = attempt.get("finished_at")
    try:
        started = datetime.fromisoformat(str(started_at).replace("Z", "+00:00"))
        finished = datetime.fromisoformat(str(finished_at).replace("Z", "+00:00"))
    except ValueError:
        started = finished = None
    input_coverage = attempt.get("input_coverage")
    market = input_coverage.get("market_directory") if isinstance(input_coverage, dict) else None
    run_id = attempt.get("run_id")
    if (attempt.get("target_trade_date") != target
            or attempt.get("execution_kind") != "SCHEDULED_REFRESH"
            or attempt.get("state") not in {"SUCCEEDED", "PARTIAL"}
            or not isinstance(run_id, str) or re.fullmatch(r"[0-9a-f]{32}", run_id) is None
            or not isinstance(attempt_sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", attempt_sha256) is None
            or digest(unsigned_attempt) != attempt_sha256
            or started is None or finished is None
            or started.tzinfo is None or finished.tzinfo is None or finished < started
            or not isinstance(input_coverage, dict)
            or input_coverage.get("source_order") != [
                "EASTMONEY_HK_DATE_CATALOG", "HKEX_OFFICIAL_FULL_MARKET_DIRECTORY"]
            or not isinstance(market, dict)):
        raise ValueError("ANNOUNCEMENT_DAILY_HKEX_CURRENT_ATTEMPT_PRODUCT_BINDING_INVALID")
    return attempt, market


def _hkex_attempt_matches_product(market: dict[str, Any], product: dict[str, Any],
                                  target: str) -> bool:
    """Require attempt and product to agree on their exact day, window and SHA."""
    expected_window_start = (f"{target[:4]}-{target[4:6]}-{target[6:]}T00:00:00+08:00")
    try:
        cutoff = datetime.fromisoformat(str(market.get("query_cutoff", "")).replace("Z", "+00:00"))
    except ValueError:
        return False
    fields = (
        ("product_run_id", "product_run_id"),
        ("product_sha256", "product_sha256"),
        ("status", "status"),
        ("directory_exhaustion", "directory_exhaustion"),
        ("from_date", "from_date"),
        ("to_date", "to_date"),
        ("window_mode", "window_mode"),
        ("publication_window_start", "publication_window_start"),
        ("query_cutoff", "query_cutoff"),
        ("record_count", "record_count"),
        ("loaded_record", "loaded_record"),
        ("captured_page_count", "captured_page_count"),
        ("captured_row_count", "captured_row_count"),
        ("unique_news_id_count", "unique_news_id_count"),
        ("gaps", "gaps"),
        ("body_gaps", "body_gaps"),
        ("body_documents_captured", "body_document_count"),
        ("pending_document_count", "pending_document_count"),
    )
    return bool(
        market.get("status") == "COMPLETE"
        and market.get("directory_exhaustion") == "VERIFIED"
        and market.get("from_date") == target
        and market.get("to_date") == target
        and market.get("window_mode") == "HK_CALENDAR_DAY_V1"
        and market.get("publication_window_start") == expected_window_start
        and cutoff.tzinfo is not None
        and cutoff.strftime("%Y-%m-%d") == expected_window_start[:10]
        and product.get("source_scope") == "HKEX_OFFICIAL_FULL_MARKET_DIRECTORY_V1"
        and all(market.get(attempt_key) == product.get(product_key)
                for attempt_key, product_key in fields)
    )


def _hkex_document_set_identity(documents: list[dict[str, Any]]) -> str:
    """Digest a complete directory document set independent of row ordering."""
    return digest(sorted((dict(document) for document in documents),
        key=lambda document: str(document.get("news_id", ""))))


def _bind_fresh_hkex_daily_directory(before: Any, refresh: Any, after: Any,
                                     target: str, publication: str) -> tuple[set[str], list[dict[str, Any]], str]:
    """Require the POST and GET to bind one new complete exact-day owner product."""
    from ops.manager_announcement_body_batch import _verified_hkex_directory_readback

    prior_ids = _prior_hkex_daily_directory_run_ids(before, target)
    run_ids, documents = _verified_hkex_directory_readback(after, target, publication)
    new_ids = run_ids - prior_ids
    if len(new_ids) != 1:
        raise ValueError("ANNOUNCEMENT_DAILY_HKEX_FRESH_DIRECTORY_RUN_REQUIRED")
    fresh_run_id = next(iter(new_ids))
    if not isinstance(refresh, dict):
        raise ValueError("ANNOUNCEMENT_DAILY_HKEX_CURRENT_ATTEMPT_PRODUCT_BINDING_INVALID")
    post_attempt, post_market = _verified_hkex_current_attempt(refresh, target)
    read_attempt, read_market = _verified_hkex_current_attempt(after, target)
    previous_attempt = before.get("attempt") if isinstance(before, dict) else None
    if (post_attempt.get("run_id") == (previous_attempt or {}).get("run_id")
            or (post_attempt.get("run_id"), post_attempt.get("sha256"))
                != (read_attempt.get("run_id"), read_attempt.get("sha256"))):
        raise ValueError("ANNOUNCEMENT_DAILY_HKEX_CURRENT_ATTEMPT_PRODUCT_BINDING_INVALID")

    coverage = refresh.get("coverage")
    after_coverage = after.get("coverage") if isinstance(after, dict) else None
    products = after_coverage.get("market_directory_products") if isinstance(after_coverage, dict) else None
    matching_products = [product for product in products if isinstance(product, dict)
        and product.get("product_run_id") == fresh_run_id] if isinstance(products, list) else []
    if (len(matching_products) != 1
            or not _hkex_attempt_matches_product(post_market, matching_products[0], target)
            or not _hkex_attempt_matches_product(read_market, matching_products[0], target)):
        raise ValueError("ANNOUNCEMENT_DAILY_HKEX_CURRENT_ATTEMPT_PRODUCT_BINDING_INVALID")

    if isinstance(coverage, dict) and isinstance(coverage.get("market_directory_products"), list):
        # Calendar-day owner readbacks expose the verified product and its
        # complete per-run document set directly. Bind that actual POST body
        # to the subsequent GET rather than expecting the automatic-reader
        # market_directory_captures summary shape.
        post_run_ids, post_documents = _verified_hkex_directory_readback(refresh, target, publication)
        if (post_run_ids != run_ids
                or _hkex_document_set_identity(post_documents) != _hkex_document_set_identity(documents)):
            raise ValueError("ANNOUNCEMENT_DAILY_HKEX_CURRENT_ATTEMPT_PRODUCT_BINDING_INVALID")
    else:
        captures = coverage.get("market_directory_captures") if isinstance(coverage, dict) else None
        fresh_captures = [item for item in captures if isinstance(item, dict)
            and item.get("product_run_id") == fresh_run_id] if isinstance(captures, list) else []
        fresh_capture = fresh_captures[0] if len(fresh_captures) == 1 else {}
        capture_fields = (
            ("target_trade_date", target), ("from_date", target), ("to_date", target),
            ("window_mode", "HK_CALENDAR_DAY_V1"),
            ("publication_window_start", matching_products[0].get("publication_window_start")),
            ("query_cutoff", matching_products[0].get("query_cutoff")),
            ("record_count", matching_products[0].get("record_count")),
            ("loaded_record", matching_products[0].get("loaded_record")),
            ("captured_page_count", matching_products[0].get("captured_page_count")),
            ("expected_page_count", matching_products[0].get("expected_page_count")),
            ("captured_row_count", matching_products[0].get("captured_row_count")),
            ("unique_news_id_count", matching_products[0].get("unique_news_id_count")),
            ("product_sha256", matching_products[0].get("product_sha256")),
        )
        post_documents = refresh.get("official_documents")
        current_post_documents = [document for document in post_documents
            if isinstance(document, dict) and document.get("capture_run_id") == fresh_run_id] \
            if isinstance(post_documents, list) else None
        if (len(fresh_captures) != 1 or fresh_capture.get("status") != "VERIFIED"
                or any(fresh_capture.get(key) != expected for key, expected in capture_fields)
                or current_post_documents is None
                or len(current_post_documents) != len(documents)
                or {document.get("news_id") for document in current_post_documents}
                    != {document.get("news_id") for document in documents}
                or not _hkex_attempt_matches_product(post_market, matching_products[0], target)):
            raise ValueError("ANNOUNCEMENT_DAILY_HKEX_CURRENT_ATTEMPT_PRODUCT_BINDING_INVALID")
    return run_ids, documents, fresh_run_id


def _capture(args: argparse.Namespace) -> dict[str, Any]:
    if getattr(args, "resume_evidence_run_id", None):
        return _resume_capture(args)
    target = date_token(args.target_date)
    publication = _publication_iso(args.publication_date)
    _local_api(args.api_base)
    query = urlencode({"date": target, "source_scope": "EASTMONEY_HK_DATE_CATALOG",
                       "publication_date": publication.replace("-", ""), "force_fresh": "true"})
    eastmoney_started_at = datetime.now().astimezone().isoformat(timespec="seconds")
    eastmoney_refresh = _request(args.api_base, "/api/v4/manager/research/announcements/refresh?" + query,
             method="POST")
    catalog_query = urlencode({"date": target, "source_scope": "EASTMONEY_HK_DATE_CATALOG",
                               "publication_date": publication.replace("-", "")})
    catalog_read = _request(args.api_base, "/api/v4/manager/research/announcements?" + catalog_query)
    catalog = catalog_read.get("catalog") if isinstance(catalog_read.get("catalog"), dict) else None
    if (catalog_read.get("readback_status") != "VERIFIED"
            or catalog_read.get("target_trade_date") != target
            or catalog_read.get("publication_date") != publication
            or not isinstance(catalog, dict)
            or catalog.get("target_trade_date") != target
            or catalog.get("publication_date") != publication
            or catalog.get("status") != "COMPLETE"
            or catalog.get("RESEARCH_ONLY") is not True
            or catalog.get("production_allowed") is not False
            or catalog.get("buy_gate_updated") is not False
            or catalog.get("orders_sent") is not False
            or catalog.get("capture_mode") not in {"FRESH", "EXPLICIT_FRESH_CAPTURE"}
            or any(not isinstance(page.get("source_ref"), dict)
                   or page["source_ref"].get("from_cache") is not False
                   for page in catalog.get("page_receipts", []))):
        raise ValueError("ANNOUNCEMENT_DAILY_CATALOG_EXACT_READBACK_REQUIRED")
    if (not isinstance(eastmoney_refresh.get("catalog"), dict)
            or eastmoney_refresh["catalog"].get("run_id") != catalog.get("run_id")
            or eastmoney_refresh["catalog"].get("sha256") != catalog.get("sha256")):
        raise ValueError("ANNOUNCEMENT_DAILY_FRESH_CATALOG_OWNER_READBACK_MISMATCH")
    directory_query = urlencode({"date": target,
        "source_scope": "HKEX_OFFICIAL_FULL_DAY_DIRECTORY"})
    hkex_before_readback = _request(args.api_base,
        "/api/v4/manager/research/announcements?" + urlencode({"date": target}))
    hkex_refresh = _refresh_hkex_daily_directory(args.api_base,
        "/api/v4/manager/research/announcements/refresh?" + directory_query)
    hkex_readback = _request(args.api_base,
        "/api/v4/manager/research/announcements?" + urlencode({"date": target}))
    hkex_run_ids, hkex_documents, hkex_fresh_run_id = _bind_fresh_hkex_daily_directory(
        hkex_before_readback, hkex_refresh, hkex_readback, target, publication)
    monthly_eligibility = _monthly_connect_eligibility(target)
    run_material = {"target_trade_date": target, "publication_date": publication,
        "catalog_run_id": catalog.get("run_id"), "catalog_product_sha256": catalog.get("sha256")}
    run_id = hashlib.sha256(json.dumps(run_material, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:32]
    state_root = Path(args.research_state_root).expanduser().resolve()
    if not state_root.is_dir():
        raise ValueError("ANNOUNCEMENT_RESEARCH_STATE_ROOT_MISSING")
    evidence_root = state_root / "announcement_agent_runs" / run_id / "evidence"
    evidence_root.mkdir(parents=True, exist_ok=True)
    catalog_path = evidence_root / "catalog_read.json"
    _write_exclusive(catalog_path, catalog_read)
    hkex_read_path = evidence_root / "hkex_directory_read.json"
    _write_exclusive(hkex_read_path, hkex_readback)
    eligibility_path = evidence_root / "monthly_connect_eligibility.json"
    _write_exclusive(eligibility_path, monthly_eligibility)
    from ops.manager_announcement_body_batch import run_capture
    body_batch = run_capture(catalog_read, state_root / "materials", evidence_root / "body_batch",
                             target, publication, hkex_directory_readback=hkex_readback,
                             monthly_connect_eligibility=monthly_eligibility)
    body_path = evidence_root / "body_corpus.json"
    body_manifest_path = evidence_root / "body_corpus_manifest.json"
    if body_batch.get("body_corpus") != "body_corpus.json":
        body_value = _load(evidence_root / "body_batch" / str(body_batch.get("body_corpus")))
        _write_exclusive(body_path, body_value)
    else:
        _write_exclusive(body_path, _load(evidence_root / "body_batch/body_corpus.json"))
    _write_exclusive(body_manifest_path, _load(evidence_root / "body_batch/body_corpus_manifest.json"))
    body_batch_receipt = evidence_root / "body_batch_receipt.json"
    _write_exclusive(body_batch_receipt, _load(evidence_root / "body_batch/batch_receipt.json"))
    capture_receipt = {"schema_version": "v4.manager_research.announcement_daily_capture.v1",
        "status": body_batch.get("status"), "evidence_run_id": run_id,
        "target_trade_date": target, "publication_date": publication,
        "catalog_run_id": catalog.get("run_id"), "catalog_product_sha256": catalog.get("sha256"),
        "catalog_read_file_sha256": _file_sha(catalog_path), "body_corpus_file_sha256": _file_sha(body_path),
        "catalog_capture_mode": catalog.get("capture_mode"),
        "eastmoney_capture_started_at": eastmoney_started_at,
        "hkex_directory_read_file_sha256": _file_sha(hkex_read_path),
        "hkex_directory_run_ids": sorted(hkex_run_ids),
        "hkex_directory_capture_mode": "FRESH_OWNER_CAPTURE",
        "hkex_prior_directory_run_ids": sorted(_prior_hkex_daily_directory_run_ids(hkex_before_readback, target)),
        "hkex_fresh_directory_run_id": hkex_fresh_run_id,
        "hkex_directory_document_count": len(hkex_documents),
        "hkex_directory_readback_sha256": body_batch.get("hkex_official_supplement", {}).get("directory_readback_sha256"),
        "hkex_directory_status": "COMPLETE_AS_OF_CAPTURE_CUTOFF",
        "hkex_body_coverage_status": body_batch.get("hkex_official_supplement", {}).get("body_coverage_status"),
        "hkex_eligible_document_count": body_batch.get("hkex_official_supplement", {}).get("eligible_document_count"),
        "hkex_excluded_document_count": body_batch.get("hkex_official_supplement", {}).get("excluded_document_count"),
        "hkex_unresolved_document_count": body_batch.get("hkex_official_supplement", {}).get("unresolved_document_count"),
        "eastmoney_directory_coverage": body_batch.get("eastmoney_directory_coverage"),
        "monthly_connect_eligibility_identity_sha256": monthly_eligibility.get("identity_sha256"),
        "monthly_connect_source_date": monthly_eligibility.get("source_date"),
        "monthly_connect_code_count": monthly_eligibility.get("code_count"),
        "monthly_connect_authority_file_sha256s": monthly_eligibility.get("authority_file_sha256s"),
        "monthly_connect_eligibility_file_sha256": _file_sha(eligibility_path),
        "body_corpus_manifest_file_sha256": _file_sha(body_manifest_path),
        "body_batch_receipt_sha256": _file_sha(body_batch_receipt),
        "semantic_status": "NOT_REVIEWED", "first_hkex_publication_time": "CANNOT_CONFIRM",
        "original_point_in_time_availability": "CANNOT_CONFIRM", **FLAGS}
    _write_exclusive(evidence_root / "capture_receipt.json", capture_receipt)
    return capture_receipt


def _evidence_run_id(target: str, publication: str, catalog: dict[str, Any]) -> str:
    run_material = {"target_trade_date": target, "publication_date": publication,
        "catalog_run_id": catalog.get("run_id"), "catalog_product_sha256": catalog.get("sha256")}
    return hashlib.sha256(json.dumps(run_material, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:32]


def _resume_capture(args: argparse.Namespace) -> dict[str, Any]:
    """Continue only the exact saved catalog run; this path never POSTs refresh."""
    target = date_token(args.target_date)
    publication = _publication_iso(args.publication_date)
    run_id = str(args.resume_evidence_run_id)
    if len(run_id) != 32 or any(c not in "0123456789abcdef" for c in run_id):
        raise ValueError("ANNOUNCEMENT_AGENT_EVIDENCE_RUN_ID_INVALID")
    _local_api(args.api_base)
    state_root = Path(args.research_state_root).expanduser().resolve(strict=True)
    from v4.manager_research.workspace_announcements import _handoff_root
    evidence_root = _handoff_root(SimpleNamespace(root=state_root), run_id)
    catalog_path = evidence_root / "catalog_read.json"
    if catalog_path.is_symlink() or not catalog_path.is_file():
        raise ValueError("ANNOUNCEMENT_RESUME_CATALOG_READBACK_MISSING")
    catalog_read = _load(catalog_path)
    catalog = catalog_read.get("catalog") if isinstance(catalog_read.get("catalog"), dict) else None
    if (not isinstance(catalog, dict)
            or catalog_read.get("readback_status") != "VERIFIED"
            or catalog_read.get("target_trade_date") != target
            or catalog_read.get("publication_date") != publication
            or catalog.get("target_trade_date") != target
            or catalog.get("publication_date") != publication
            or catalog.get("source_scope") != "EASTMONEY_HK_DATE_CATALOG"
            or catalog.get("status") != "COMPLETE"
            or catalog.get("RESEARCH_ONLY") is not True
            or catalog.get("production_allowed") is not False
            or catalog.get("buy_gate_updated") is not False
            or catalog.get("orders_sent") is not False):
        raise ValueError("ANNOUNCEMENT_RESUME_CATALOG_PAIR_OR_SOURCE_INVALID")
    if digest({key: value for key, value in catalog.items() if key != "sha256"}) != catalog.get("sha256"):
        raise ValueError("ANNOUNCEMENT_RESUME_CATALOG_PRODUCT_SHA_INVALID")
    if _evidence_run_id(target, publication, catalog) != run_id:
        raise ValueError("ANNOUNCEMENT_RESUME_EVIDENCE_RUN_ID_MISMATCH")

    # Revalidate every saved listing page and identity through the original
    # producer validator; the shared MaterialStore is read-only in this step.
    from ops import manager_announcement_body_batch as body_batch
    api = body_batch.imports()
    api["_body_security_match"] = body_batch._body_security_match
    material_root = state_root / "materials"
    store = api["MaterialStore"](material_root)
    directory_rows = body_batch._validate_catalog(api, catalog_read, store, target, publication)
    hkex_read_path = evidence_root / "hkex_directory_read.json"
    eligibility_path = evidence_root / "monthly_connect_eligibility.json"
    if (hkex_read_path.is_symlink() or not hkex_read_path.is_file()
            or eligibility_path.is_symlink() or not eligibility_path.is_file()):
        raise ValueError("ANNOUNCEMENT_RESUME_DAILY_SOURCE_EVIDENCE_MISSING")
    hkex_readback = _load(hkex_read_path)
    monthly_eligibility = _load(eligibility_path)
    eligibility_codes, eligibility_identity = body_batch._verified_monthly_connect_eligibility(
        monthly_eligibility, publication)
    hkex_run_ids, all_hkex_documents = body_batch._verified_hkex_directory_readback(
        hkex_readback, target, publication)
    (rows, eastmoney_row_eligibility, eligible_hkex_documents,
     hkex_directory_eligibility) = body_batch._apply_monthly_connect_eligibility(
        directory_rows, all_hkex_documents, eligibility_codes, eligibility_identity)

    query = urlencode({"date": target, "source_scope": "EASTMONEY_HK_DATE_CATALOG",
                       "publication_date": publication.replace("-", "")})
    owner_readback = _request(args.api_base, "/api/v4/manager/research/announcements?" + query)
    owner_catalog = owner_readback.get("catalog") if isinstance(owner_readback.get("catalog"), dict) else None
    if (owner_readback.get("readback_status") != "VERIFIED"
            or owner_readback.get("target_trade_date") != target
            or owner_readback.get("publication_date") != publication
            or not isinstance(owner_catalog, dict)
            or owner_catalog.get("target_trade_date") != target
            or owner_catalog.get("publication_date") != publication
            or owner_catalog.get("run_id") != catalog.get("run_id")
            or owner_catalog.get("sha256") != catalog.get("sha256")
            or owner_catalog.get("source_scope") != "EASTMONEY_HK_DATE_CATALOG"
            or owner_catalog.get("status") != "COMPLETE"):
        raise ValueError("ANNOUNCEMENT_RESUME_OWNER_CATALOG_DRIFT")

    body_root = evidence_root / "body_batch"
    if body_root.is_symlink():
        raise ValueError("ANNOUNCEMENT_RESUME_BODY_ROOT_SYMLINK")
    batch_receipt_path = body_root / "batch_receipt.json"
    attempt_path = body_root / "batch_attempt.json"
    if batch_receipt_path.is_symlink():
        raise ValueError("ANNOUNCEMENT_RESUME_BODY_RECEIPT_SYMLINK")
    if batch_receipt_path.is_file():
        batch = _load(batch_receipt_path)
    else:
        if attempt_path.exists() or attempt_path.is_symlink():
            raise ValueError("ANNOUNCEMENT_RESUME_BODY_ATTEMPT_INDETERMINATE_NO_RETRY")
        batch = body_batch.run_capture(catalog_read, material_root, body_root, target, publication,
            hkex_directory_readback=hkex_readback,
            monthly_connect_eligibility=monthly_eligibility)

    body_path = body_root / "body_corpus.json"
    manifest_path = body_root / "body_corpus_manifest.json"
    if any(path.is_symlink() or not path.is_file() for path in (body_path, manifest_path, batch_receipt_path)):
        raise ValueError("ANNOUNCEMENT_RESUME_BODY_ARTIFACT_MISSING")
    body = _load(body_path)
    manifest = _load(manifest_path)
    article_ids = [row.get("art_code") for row in rows]
    input_identity_payload = {"target_trade_date": target, "publication_date": publication,
        "catalog_run_id": catalog["run_id"], "catalog_sha256": catalog["sha256"],
        "article_ids": article_ids, "listing_body_sha256s": [row.get("raw_body_sha256") for row in rows]}
    input_identity_payload.update(monthly_connect_eligibility_identity_sha256=eligibility_identity,
        hkex_directory_readback_sha256=body_batch.digest(body_batch.json_bytes(hkex_readback)),
        hkex_eligible_news_ids=[doc.get("news_id") for doc in eligible_hkex_documents])
    input_identity = hashlib.sha256(body_batch.json_bytes(input_identity_payload)).hexdigest()
    body_rows = body.get("rows") if isinstance(body, dict) else None
    manifest_articles = manifest.get("article_receipts") if isinstance(manifest, dict) else None
    if (batch.get("schema") != "v4.manager_research.announcement_body_batch_receipt.v1"
            or batch.get("status") not in {"PASS_COMPLETE_CONTENT_API_BODIES_ALL_ROWS",
                                            "PARTIAL_BODY_MATERIAL_CAPTURE_WITH_TERMINAL_GAPS"}
            or batch.get("target_trade_date") != target
            or batch.get("publication_date") != publication
            or batch.get("catalog_run_id") != catalog.get("run_id")
            or batch.get("catalog_sha256") != catalog.get("sha256")
            or batch.get("input_identity_sha256") != input_identity
            or batch.get("article_rows") != len(rows)
            or batch.get("terminal_article_receipts") != len(rows)
            or batch.get("body_corpus") != "body_corpus.json"
            or batch.get("body_corpus_manifest") != "body_corpus_manifest.json"
            or batch.get("body_corpus_sha256") != _file_sha(body_path)
            or batch.get("body_corpus_manifest_sha256") != _file_sha(manifest_path)
            or not isinstance(body, dict)
            or body.get("schema") != "v4.manager_research.eastmoney_hk_multi_source_announcement_body_corpus.v1"
            or body.get("target_notice_date") != publication
            or body.get("article_count") != len(rows)
            or body.get("eastmoney_article_count") != len(rows)
            or body.get("source_variant_count") != len(eligible_hkex_documents)
            or body.get("combined_document_count") != len(rows) + len(eligible_hkex_documents)
            or body.get("monthly_connect_eligibility", {}).get("identity_sha256") != eligibility_identity
            or body.get("hkex_directory_readback_sha256") != body_batch.digest(body_batch.json_bytes(hkex_readback))
            or body.get("input_identity_sha256") != input_identity
            or body.get("source_manifest_sha256") != _file_sha(manifest_path)
            or not isinstance(body_rows, list)
            or [row.get("art_code") for row in body_rows if isinstance(row, dict)] != article_ids
            or not isinstance(manifest, dict)
            or manifest.get("target_trade_date") != target
            or manifest.get("publication_date") != publication
            or manifest.get("catalog_run_id") != catalog.get("run_id")
            or manifest.get("catalog_sha256") != catalog.get("sha256")
            or manifest.get("input_identity_sha256") != input_identity
            or not isinstance(manifest_articles, list)
            or [row.get("art_code") for row in manifest_articles if isinstance(row, dict)] != article_ids):
        raise ValueError("ANNOUNCEMENT_RESUME_BODY_RECEIPT_BINDING_INVALID")

    # Copy the exact verified body-batch bytes into the stable evidence paths.
    # Existing different bytes are a conflict, never an overwrite.
    for source, destination in (
        (body_path, evidence_root / "body_corpus.json"),
        (manifest_path, evidence_root / "body_corpus_manifest.json"),
        (batch_receipt_path, evidence_root / "body_batch_receipt.json"),
    ):
        raw = source.read_bytes()
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            with destination.open("xb") as stream:
                stream.write(raw)
        except FileExistsError:
            if destination.is_symlink() or destination.read_bytes() != raw:
                raise ValueError("ANNOUNCEMENT_RESUME_EXISTING_ARTIFACT_CONFLICT")
    capture_receipt = {"schema_version": "v4.manager_research.announcement_daily_capture.v1",
        "status": batch["status"], "evidence_run_id": run_id,
        "target_trade_date": target, "publication_date": publication,
        "catalog_run_id": catalog["run_id"], "catalog_product_sha256": catalog["sha256"],
        "catalog_read_file_sha256": _file_sha(catalog_path),
        "body_corpus_file_sha256": _file_sha(evidence_root / "body_corpus.json"),
        "body_corpus_manifest_file_sha256": _file_sha(evidence_root / "body_corpus_manifest.json"),
        "body_batch_receipt_sha256": _file_sha(evidence_root / "body_batch_receipt.json"),
        "hkex_directory_read_file_sha256": _file_sha(hkex_read_path),
        "hkex_directory_run_ids": sorted(hkex_run_ids),
        "hkex_directory_capture_mode": "RESUMED_SAVED_DIRECTORY_READBACK",
        "hkex_directory_document_count": len(all_hkex_documents),
        "hkex_directory_readback_sha256": body.get("hkex_directory_readback_sha256"),
        "hkex_eligible_document_count": len(eligible_hkex_documents),
        "hkex_excluded_document_count": sum(item["status"] == "NOT_ELIGIBLE" for item in hkex_directory_eligibility),
        "hkex_unresolved_document_count": sum(item["status"] == "UNRESOLVED" for item in hkex_directory_eligibility),
        "hkex_body_coverage_status": batch.get("hkex_official_supplement", {}).get("body_coverage_status"),
        "eastmoney_directory_coverage": {
            "raw_row_count": len(directory_rows), "eligible_row_count": len(rows),
            "excluded_row_count": sum(item["status"] == "NOT_ELIGIBLE" for item in eastmoney_row_eligibility),
            "unresolved_row_count": sum(item["status"] == "UNRESOLVED" for item in eastmoney_row_eligibility),
        },
        "monthly_connect_eligibility_identity_sha256": eligibility_identity,
        "monthly_connect_source_date": monthly_eligibility.get("source_date"),
        "monthly_connect_code_count": monthly_eligibility.get("code_count"),
        "monthly_connect_authority_file_sha256s": monthly_eligibility.get("authority_file_sha256s"),
        "monthly_connect_eligibility_file_sha256": _file_sha(eligibility_path),
        "semantic_status": "NOT_REVIEWED", "first_hkex_publication_time": "CANNOT_CONFIRM",
        "original_point_in_time_availability": "CANNOT_CONFIRM", **FLAGS}
    receipt_path = evidence_root / "capture_receipt.json"
    try:
        with receipt_path.open("xb") as stream:
            stream.write((json.dumps(capture_receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8"))
    except FileExistsError:
        if receipt_path.is_symlink() or _load(receipt_path) != capture_receipt:
            raise ValueError("ANNOUNCEMENT_RESUME_CAPTURE_RECEIPT_CONFLICT")
    return capture_receipt


def _import(args: argparse.Namespace) -> dict[str, Any]:
    run_id = args.evidence_run_id
    state_root = Path(args.research_state_root).expanduser().resolve(strict=True)
    from v4.manager_research.workspace_announcements import _handoff_root, validate_registered_handoff
    evidence_root = _handoff_root(SimpleNamespace(root=state_root), run_id)
    manifest = _load(evidence_root / "handoff_manifest.v1.json")
    product = _load(evidence_root / "analysis_product.json")
    validate_registered_handoff(SimpleNamespace(root=state_root), run_id,
        manifest.get("sha256"), product.get("sha256"), product)
    query = urlencode({"date": product["target_trade_date"],
                       "publication_date": product["publication_date"].replace("-", "")})
    envelope = {"schema_version": "v4.manager_research.announcement_analysis_import_ref.v1",
        "evidence_run_id": run_id, "handoff_manifest_sha256": manifest["sha256"],
        "product_sha256": product["sha256"]}
    body = json.dumps(envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    result = _request(args.api_base, "/api/v4/manager/research/announcements/analysis/import",
                      method="POST", payload=body)
    analysis = result.get("analysis")
    owner_receipt = validate_owner_analysis_import_receipt(result.get("owner_import_receipt"), product)
    if (not isinstance(analysis, dict) or analysis.get("status") != "VERIFIED"
            or analysis.get("product_sha256") != product.get("sha256")
            or owner_receipt.get("product_sha256") != product.get("sha256")):
        raise ValueError("ANNOUNCEMENT_IMPORT_OWNER_READBACK_MISMATCH")
    return {"status": result.get("import_status") or "IMPORTED",
        "target_trade_date": product["target_trade_date"], "publication_date": product["publication_date"],
        "evidence_run_id": run_id, "handoff_manifest_sha256": manifest["sha256"],
        "product_sha256": product["sha256"], "owner_available_at": owner_receipt["available_at"],
        "owner_receipt_sha256": owner_receipt["sha256"], **FLAGS}


def _copy_json_bytes(source: str | Path, destination: Path) -> str:
    raw = Path(source).read_bytes()
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, (dict, list)):
        raise ValueError("ANNOUNCEMENT_HANDOFF_JSON_OBJECT_REQUIRED")
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with destination.open("xb") as stream:
            stream.write(raw)
    except FileExistsError:
        if destination.read_bytes() != raw:
            raise ValueError("ANNOUNCEMENT_HANDOFF_OUTPUT_EXISTS_WITH_DIFFERENT_BYTES")
    return hashlib.sha256(raw).hexdigest()


def _register_handoff(args: argparse.Namespace) -> dict[str, Any]:
    target = date_token(args.target_date)
    publication = _publication_iso(args.publication_date)
    if len(args.evidence_run_id) != 32 or any(c not in "0123456789abcdef" for c in args.evidence_run_id):
        raise ValueError("ANNOUNCEMENT_AGENT_EVIDENCE_RUN_ID_INVALID")
    state_root = Path(args.research_state_root).expanduser().resolve(strict=True)
    from v4.manager_research.workspace_announcements import _handoff_root, validate_registered_handoff
    from v4.manager_research.workspace_projection import digest
    store_ref = SimpleNamespace(root=state_root)
    evidence = _handoff_root(store_ref, args.evidence_run_id)
    capture = _load(evidence / "capture_receipt.json")
    catalog_path = evidence / "catalog_read.json"
    body_path = evidence / "body_corpus.json"
    catalog_read = _load(catalog_path)
    catalog = catalog_read.get("catalog") if isinstance(catalog_read.get("catalog"), dict) else {}
    terminal_capture = validate_terminal_body_capture(
        evidence, catalog_read, target, publication, expected_run_id=args.evidence_run_id)
    if (capture.get("status") != terminal_capture.get("status")
            or capture.get("evidence_run_id") != args.evidence_run_id
            or capture.get("target_trade_date") != target
            or capture.get("publication_date") != publication
            or catalog_read.get("readback_status") != "VERIFIED"
            or catalog.get("sha256") != capture.get("catalog_product_sha256")):
        raise ValueError("ANNOUNCEMENT_HANDOFF_CAPTURE_NOT_COMPLETE_EXACT_PAIR")
    semantic_path = evidence / "semantic_catalog.json"
    reader_path = evidence / "reader_output.json"
    reviewer_path = evidence / "reviewer_output.json"
    semantic_sha = _copy_json_bytes(args.semantic_catalog, semantic_path)
    reader_sha = _copy_json_bytes(args.semantic_catalog, reader_path)
    reviewer_sha = _copy_json_bytes(args.reviewer_output, reviewer_path)
    decisions_path = None
    decisions_sha = None
    decisions_value = None
    if args.decisions:
        decisions_path = evidence / "article_decisions.json"
        decisions_sha = _copy_json_bytes(args.decisions, decisions_path)
        raw_decisions = _load(decisions_path)
        if isinstance(raw_decisions, dict):
            if set(raw_decisions) != {"article_decisions"}:
                raise ValueError("ANNOUNCEMENT_HANDOFF_DECISIONS_INVALID")
            decisions_value = raw_decisions.get("article_decisions")
        else:
            decisions_value = raw_decisions
        if not isinstance(decisions_value, list):
            raise ValueError("ANNOUNCEMENT_HANDOFF_DECISIONS_INVALID")
    reviewer = _load(reviewer_path)
    decision_status = "EXPLICIT_DISPOSITIONS" if decisions_value is not None else "NOT_ASSESSED"
    decision_payload_sha = digest(decisions_value) if decisions_value is not None else None
    reviewed_at = reviewer.get("reviewed_at")
    if (reviewer.get("schema_version") != "v4.manager_research.announcement_agent_review.v1"
            or reviewer.get("review_conclusion") != "PASS"
            or reviewer.get("target_trade_date") != target or reviewer.get("publication_date") != publication
            or reviewer.get("evidence_run_id") != args.evidence_run_id
            or reviewer.get("decision_status") != decision_status
            or reviewer.get("decision_payload_sha256") != decision_payload_sha
            or reviewer.get("reader_identity") != args.reader_identity
            or reviewer.get("reviewer_identity") != args.reviewer_identity
            or args.reader_identity == args.reviewer_identity
            or not isinstance(reviewed_at, str) or not reviewed_at.strip()):
        raise ValueError("ANNOUNCEMENT_HANDOFF_REVIEW_OUTPUT_INVALID")
    body_sha = _file_sha(body_path)
    catalog_sha = catalog.get("sha256")
    if (reviewer.get("catalog_product_sha256") != catalog_sha
            or reviewer.get("semantic_catalog_sha256") != semantic_sha
            or reviewer.get("body_corpus_sha256") != body_sha):
        raise ValueError("ANNOUNCEMENT_HANDOFF_REVIEW_SOURCE_SHA_MISMATCH")
    files = {
        "catalog_read.json": _file_sha(catalog_path),
        "hkex_directory_read.json": _file_sha(evidence / "hkex_directory_read.json")
            if (evidence / "hkex_directory_read.json").is_file() else None,
        "monthly_connect_eligibility.json": _file_sha(evidence / "monthly_connect_eligibility.json")
            if (evidence / "monthly_connect_eligibility.json").is_file() else None,
        "body_corpus.json": body_sha,
        "body_corpus_manifest.json": _file_sha(evidence / "body_corpus_manifest.json"),
        "body_batch_receipt.json": _file_sha(evidence / "body_batch_receipt.json"),
        "capture_receipt.json": _file_sha(evidence / "capture_receipt.json"),
        "semantic_catalog.json": semantic_sha, "reader_output.json": reader_sha,
        "reviewer_output.json": reviewer_sha,
        "article_decisions.json": decisions_sha,
    }
    build_args = SimpleNamespace(target_date=target, publication_date=publication,
        catalog_read=str(catalog_path), semantic_catalog=str(semantic_path), body_corpus=str(body_path),
        out=None, decisions=None, review_receipt=None)
    built = _build(build_args, reviewed=False, include_product=True,
        terminal_body_capture=terminal_capture)
    product = built["product"]
    preopen_window = None
    preopen_window_sha = None
    if args.preopen_window_json:
        window_path = Path(args.preopen_window_json).expanduser()
        if window_path.is_symlink() or not window_path.is_file():
            raise ValueError("ANNOUNCEMENT_PREOPEN_WINDOW_INPUT_MISSING")
        try:
            window_payload = json.loads(window_path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("ANNOUNCEMENT_PREOPEN_WINDOW_INPUT_INVALID") from exc
        preopen_window = validate_preopen_window(window_payload, target_trade_date=target,
            semantic_sha256=semantic_sha, body_sha256=body_sha, decisions=decisions_value)
        current_day = next((row for row in preopen_window.get("source_days", [])
            if isinstance(row, dict) and row.get("publication_date") == publication), None)
        current_draft_ref = (current_day.get("source_files", {}).get("analysis_product")
            if isinstance(current_day, dict)
            and isinstance(current_day.get("source_files"), dict) else None)
        if not isinstance(current_draft_ref, dict):
            raise ValueError("ANNOUNCEMENT_PREOPEN_WINDOW_DRAFT_BINDING_MISMATCH")
        current_draft_path = Path(current_draft_ref.get("path", ""))
        try:
            current_draft = json.loads(current_draft_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("ANNOUNCEMENT_PREOPEN_WINDOW_DRAFT_BINDING_MISMATCH") from exc
        if (not isinstance(current_day, dict)
                or current_day.get("product_readiness") != "DERIVED_DRAFT_UNREGISTERED"
                or current_draft_ref.get("sha256") != current_day.get("analysis_product_sha256")
                or current_draft.get("sha256") != product.get("sha256")
                or current_draft.get("source_manifest_sha256") != product.get("source_manifest_sha256")
                or current_day.get("semantic_catalog_sha256") != semantic_sha
                or current_day.get("body_corpus_sha256") != body_sha):
            raise ValueError("ANNOUNCEMENT_PREOPEN_WINDOW_DRAFT_BINDING_MISMATCH")
        binding = {"evidence_run_id": args.evidence_run_id,
            "target_trade_date": target, "publication_date": publication,
            "source_semantic_catalog_sha256": semantic_sha,
            "source_body_corpus_file_sha256": body_sha,
            "decision_file_sha256": decisions_sha,
            "decision_payload_sha256": decision_payload_sha,
            "draft_analysis_product_sha256": current_day["analysis_product_sha256"],
            "draft_source_manifest_sha256": product.get("source_manifest_sha256")}
        preopen_window["registered_binding"] = binding
        preopen_window["registered_fingerprint_sha256"] = digest({
            "input_fingerprint_sha256": preopen_window["input_fingerprint_sha256"],
            "registered_binding": binding})
    incremental_processing = build_incremental_processing(product, body, decisions_value,
        target_trade_date=target, publication_date=publication,
        semantic_sha256=semantic_sha, body_sha256=body_sha,
        decision_sha256=decisions_sha, reviewer_sha256=reviewer_sha)
    product["source_manifest"]["incremental_processing"] = incremental_processing
    if preopen_window is not None:
        product["source_manifest"]["preopen_window"] = preopen_window
    product["source_manifest_sha256"] = digest(product["source_manifest"])
    product.pop("sha256", None)
    product["sha256"] = digest(product)
    manifest = {
        "schema_version": "v4.manager_research.announcement_agent_handoff.v1",
        "evidence_run_id": args.evidence_run_id, "target_trade_date": target,
        "publication_date": publication, "source_run_id": catalog.get("run_id"),
        "source_run_sha256": catalog_sha, "catalog_product_sha256": catalog_sha,
        "semantic_catalog_sha256": semantic_sha, "body_corpus_sha256": body_sha,
        "reader_identity": args.reader_identity, "reviewer_identity": args.reviewer_identity,
        "reviewed_at": reviewed_at, "decision_status": decision_status,
        "decision_payload_sha256": decision_payload_sha, "files": files, **FLAGS,
    }
    manifest_sha = digest(manifest)
    receipt = {
        "schema_version": "v4.manager_research.announcement_agent_judgment.v1",
        "status": "VERIFIED", "target_trade_date": target, "publication_date": publication,
        "parent_task_id": str(args.parent_task_id), "parent_run_id": args.evidence_run_id,
        "evidence_run_id": args.evidence_run_id, "reader_identity": args.reader_identity,
        "reviewer_identity": args.reviewer_identity, "reviewed_at": reviewed_at,
        "evidence_binding_status": "OUTPUT_BOUND", "external_review_status": "DECLARED",
        "reviewer_conclusion": "PASS", "reviewer_decision_payload_sha256": decision_payload_sha,
        "agent_output_sha256": reader_sha, "reader_output_sha256": reader_sha,
        "reviewer_output_sha256": reviewer_sha, "source_run_id": catalog.get("run_id"),
        "source_run_sha256": catalog_sha, "semantic_catalog_sha256": semantic_sha,
        "body_corpus_sha256": body_sha, "semantic_catalog_sha256_legacy": semantic_sha,
        "catalog_product_sha256": catalog_sha, "decision_status": decision_status,
        "decision_payload_sha256": decision_payload_sha,
        "article_decision_count": len(decisions_value) if decisions_value is not None else 0,
        **FLAGS,
    }
    product["agent_judgment_receipt"] = receipt
    product.pop("sha256", None)
    product["sha256"] = digest(product)
    receipt["sha256"] = digest(receipt)
    product.pop("sha256", None)
    product["sha256"] = digest(product)
    if decisions_value is not None:
        # The receipt is part of the base product identity. Build the selection
        # extension only after that identity is final so its base hash verifies
        # during owner import and plan readback.
        extension = make_extension(product, decisions_value)
        product = attach_extension(product, extension)
        if digest(extension.get("article_decisions")) != decision_payload_sha:
            raise ValueError("ANNOUNCEMENT_HANDOFF_DECISIONS_NOT_CANONICAL")
    if preopen_window is not None:
        window_path = evidence / "preopen_window.json"
        _write_exclusive(window_path, preopen_window)
        preopen_window_sha = _file_sha(window_path)
    validate_agent_judgment_receipt(receipt, product)
    product_path = evidence / "analysis_product.json"
    product_raw = (json.dumps(product, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    try:
        with product_path.open("xb") as stream:
            stream.write(product_raw)
    except FileExistsError:
        if product_path.read_bytes() != product_raw:
            raise ValueError("ANNOUNCEMENT_HANDOFF_PRODUCT_EXISTS_WITH_DIFFERENT_BYTES")
    files["analysis_product.json"] = hashlib.sha256(product_raw).hexdigest()
    if preopen_window_sha is not None:
        files["preopen_window.json"] = preopen_window_sha
    manifest["files"] = files
    manifest["product_sha256"] = product["sha256"]
    if preopen_window is not None:
        manifest["preopen_window_sha256"] = preopen_window_sha
        manifest["preopen_window_input_fingerprint_sha256"] = preopen_window["input_fingerprint_sha256"]
        manifest["preopen_window_registered_fingerprint_sha256"] = preopen_window["registered_fingerprint_sha256"]
    manifest["sha256"] = digest(manifest)
    manifest_path = evidence / "handoff_manifest.v1.json"
    _write_exclusive(manifest_path, manifest)
    validated = validate_registered_handoff(store_ref, args.evidence_run_id,
        manifest["sha256"], product["sha256"], product)
    return {"status": "OUTPUT_BOUND_HANDOFF_REGISTERED", "evidence_run_id": args.evidence_run_id,
        "handoff_manifest_sha256": manifest["sha256"], "product_sha256": product["sha256"],
        "reader_output_sha256": reader_sha, "reviewer_output_sha256": reviewer_sha,
        "decision_status": decision_status, "reader_identity": args.reader_identity,
        "reviewer_identity": args.reviewer_identity, "external_review_status": "DECLARED",
        "incremental_processing_fingerprint_sha256": incremental_processing["input_fingerprint_sha256"],
        "incremental_processing_counts": incremental_processing["counts"],
        "preopen_window_input_fingerprint_sha256": (
            preopen_window.get("input_fingerprint_sha256") if preopen_window is not None else None),
        "preopen_window_registered_fingerprint_sha256": (
            preopen_window.get("registered_fingerprint_sha256") if preopen_window is not None else None),
        "output_binding_status": "OUTPUT_BOUND", **FLAGS}


def _readback(args: argparse.Namespace) -> dict[str, Any]:
    target = date_token(args.target_date)
    publication = _publication_iso(args.publication_date)
    publication_token = publication.replace("-", "")
    query = urlencode({"date": target, "publication_date": publication_token})
    result = _request(args.api_base, "/api/v4/manager/research/announcements/analysis?" + query)
    analysis = result.get("analysis")
    if not isinstance(analysis, dict) or analysis.get("status") != "VERIFIED":
        raise ValueError("ANNOUNCEMENT_ANALYSIS_OWNER_READBACK_UNAVAILABLE")
    if (result.get("target_trade_date") != target
            or result.get("publication_date") != publication):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_OWNER_READBACK_DATE_PAIR_MISMATCH")
    product = {"target_trade_date": target, "publication_date": publication,
        "sha256": analysis.get("product_sha256")}
    receipt = result.get("owner_import_receipt")
    if receipt is None:
        raise ValueError("ANNOUNCEMENT_ANALYSIS_OWNER_IMPORT_RECEIPT_MISSING")
    validated_receipt = validate_owner_analysis_import_receipt(receipt, product)
    if (validated_receipt.get("target_trade_date") != target
            or validated_receipt.get("publication_date") != publication
            or validated_receipt.get("product_sha256") != analysis.get("product_sha256")):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_OWNER_IMPORT_RECEIPT_DATE_OR_PRODUCT_MISMATCH")
    return {"status": "OWNER_READBACK_VERIFIED", "target_trade_date": target,
        "publication_date": publication, "product_sha256": analysis.get("product_sha256"),
        "owner_available_at": validated_receipt.get("available_at"),
        "owner_receipt_sha256": validated_receipt.get("sha256"), **FLAGS}


def _process_saved_window(args: argparse.Namespace) -> dict[str, Any]:
    manifest_path = Path(args.inputs_manifest).expanduser()
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError("ANNOUNCEMENT_WINDOW_INPUT_MANIFEST_MISSING")
    raw = manifest_path.read_bytes()
    manifest_sha = hashlib.sha256(raw).hexdigest()
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("ANNOUNCEMENT_WINDOW_INPUT_MANIFEST_INVALID") from exc
    started = perf_counter()
    result = process_saved_window(manifest, base_dir=manifest_path.parent)
    elapsed = perf_counter() - started
    result["processing"]["elapsed_seconds"] = round(elapsed, 6)
    result["input_manifest_file_sha256"] = manifest_sha
    output = Path(args.out).expanduser()
    _write_exclusive(output, result)
    return {"status": result["status"], "output": str(output.resolve()),
        "target_trade_date": result["target_trade_date"], "window_start": result["window_start"],
        "as_of": result["as_of"], "input_fingerprint_sha256": result["input_fingerprint_sha256"],
        "input_manifest_file_sha256": manifest_sha, "coverage": result["coverage"],
        "retrospective_research": {
            "status": result["retrospective_research"]["status"],
            "candidate_count": result["retrospective_research"]["candidate_count"],
            "positive_candidate_count": result["retrospective_research"]["positive_candidate_count"],
            "pending_count": result["retrospective_research"]["pending_count"]},
        "actual_preopen": {"status": result["actual_preopen"]["status"],
            "positive_candidate_count": result["actual_preopen"]["positive_candidate_count"],
            "gaps": result["actual_preopen"]["gaps"]},
        "processing": result["processing"], "physical_http_request_count": 0,
        "llm_inference_count": 0, **FLAGS}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    capture = sub.add_parser("capture", help="refresh exact owner catalog readback and capture every article body")
    capture.add_argument("--target-date", required=True)
    capture.add_argument("--publication-date", required=True)
    capture.add_argument("--api-base", required=True)
    capture.add_argument("--research-state-root", required=True,
        help="same ManagerResearch state root used by the API; material refs are read from its materials store")
    capture.add_argument("--resume-evidence-run-id", default=None,
        help="resume the exact saved catalog run without POST refresh; requires matching date pair and owner GET readback")
    prepare = sub.add_parser("prepare", help="validate exact date-bound source artifacts without writing")
    prepare.add_argument("--target-date", required=True)
    prepare.add_argument("--publication-date", required=True)
    prepare.add_argument("--catalog-read", required=True)
    prepare.add_argument("--semantic-catalog", required=True)
    prepare.add_argument("--body-corpus", required=True)
    prepare.add_argument("--body-capture-evidence-root",
        help="fixed evidence directory containing capture/batch receipts and original article artifacts")
    build = sub.add_parser("build-reviewed", help="build a product from actual reviewed inputs")
    build.add_argument("--target-date", required=True)
    build.add_argument("--publication-date", required=True)
    build.add_argument("--catalog-read", required=True)
    build.add_argument("--semantic-catalog", required=True)
    build.add_argument("--body-corpus", required=True)
    build.add_argument("--body-capture-evidence-root",
        help="fixed evidence directory containing capture/batch receipts and original article artifacts")
    build.add_argument("--review-receipt", required=True)
    build.add_argument("--decisions")
    build.add_argument("--out", required=True)
    imp = sub.add_parser("import", help="import through the loopback V4 owner API and verify readback")
    imp.add_argument("--evidence-run-id", required=True)
    imp.add_argument("--research-state-root", required=True)
    imp.add_argument("--api-base", required=True)
    register = sub.add_parser("register-handoff", help="bind actual reader and reviewer output bytes under the fixed local evidence root")
    register.add_argument("--evidence-run-id", required=True)
    register.add_argument("--research-state-root", required=True)
    register.add_argument("--target-date", required=True)
    register.add_argument("--publication-date", required=True)
    register.add_argument("--semantic-catalog", required=True)
    register.add_argument("--reviewer-output", required=True)
    register.add_argument("--decisions")
    register.add_argument("--preopen-window-json")
    register.add_argument("--parent-task-id", required=True)
    register.add_argument("--reader-identity", required=True)
    register.add_argument("--reviewer-identity", required=True)
    readback = sub.add_parser("readback", help="read exact owner product and import receipt")
    readback.add_argument("--target-date", required=True)
    readback.add_argument("--publication-date", required=True)
    readback.add_argument("--api-base", required=True)
    window = sub.add_parser("process-saved-window",
        help="derive a bounded pre-open window from SHA-bound saved products and reviewed rule files")
    window.add_argument("--inputs-manifest", required=True)
    window.add_argument("--out", required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.command == "prepare":
            result = _build(args, reviewed=False)
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        elif args.command == "capture":
            result = _capture(args)
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        elif args.command == "build-reviewed":
            result = _build(args, reviewed=True)
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        elif args.command == "import":
            result = _import(args)
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        elif args.command == "register-handoff":
            result = _register_handoff(args)
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        elif args.command == "process-saved-window":
            result = _process_saved_window(args)
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        else:
            result = _readback(args)
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    except (OSError, ValueError, KeyError, TypeError, HTTPError) as exc:
        print(json.dumps({"status": "FAILED", "reason": str(exc), **FLAGS}, ensure_ascii=False, sort_keys=True))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
