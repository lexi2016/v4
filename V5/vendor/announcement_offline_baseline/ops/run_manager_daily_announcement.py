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
import shutil
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse, urlunparse
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from v4.manager_research.announcement_analysis import (
    _assert_catalog_readback,
    build_product,
    has_reader_declared_content_gap,
    product_path,
)
from v4.manager_research.announcement_selection import attach_extension, make_extension
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


def _mkdir(path: str | Path) -> None:
    Path(path).mkdir(parents=True, exist_ok=True)


def _write_new(path: str | Path, raw: bytes) -> None:
    with Path(path).open("xb") as stream:
        stream.write(raw)


def _write_exclusive(path: str | Path, value: Any) -> None:
    target = Path(path)
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    _mkdir(target.parent)
    try:
        _write_new(target, raw)
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
        unassessed_codes = {row.get("art_code") for row in semantic.get("records", [])
                            if isinstance(row, dict) and has_reader_declared_content_gap(row)}
        if terminal_body_capture is not None:
            unassessed_codes.update(row.get("art_code")
                for row in terminal_body_capture.get("failed_articles", []) if isinstance(row, dict))
        by_code = {row.get("art_code"): row for row in decisions if isinstance(row, dict)}
        if any(by_code.get(code, {}).get("disposition") != "NOT_ASSESSED"
               for code in unassessed_codes):
            raise ValueError("ANNOUNCEMENT_UNASSESSED_CONTENT_SELECTION_MUST_BE_NOT_ASSESSED")
        extension = make_extension(product, decisions)
        product = attach_extension(product, extension)
    if reviewed:
        receipt = _load(args.review_receipt)
        receipt = validate_agent_judgment_receipt(receipt, {**product, "agent_judgment_receipt": receipt})
        product["agent_judgment_receipt"] = receipt
        product.pop("sha256", None)
        product["sha256"] = digest(product)
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


def _request(api_base: str, path: str, *, method: str = "GET", payload: bytes | None = None) -> dict[str, Any]:
    base, origin = _local_api(api_base)
    headers = {"Accept": "application/json"}
    if payload is not None:
        headers.update({"Content-Type": "application/json", "Origin": origin})
    elif method.upper() == "POST":
        headers["Origin"] = origin
    request = Request(base + path, data=payload, headers=headers, method=method)
    opener = build_opener(ProxyHandler({}), _NoRedirect())
    try:
        with opener.open(request, timeout=20) as response:
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


def _capture(args: argparse.Namespace) -> dict[str, Any]:
    if getattr(args, "resume_evidence_run_id", None):
        return _resume_capture(args)
    target = date_token(args.target_date)
    publication = _publication_iso(args.publication_date)
    _local_api(args.api_base)
    query = urlencode({"date": target, "source_scope": "EASTMONEY_HK_DATE_CATALOG",
                       "publication_date": publication.replace("-", "")})
    _request(args.api_base, "/api/v4/manager/research/announcements/refresh?" + query,
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
            or catalog.get("orders_sent") is not False):
        raise ValueError("ANNOUNCEMENT_DAILY_CATALOG_EXACT_READBACK_REQUIRED")
    run_material = {"target_trade_date": target, "publication_date": publication,
        "catalog_run_id": catalog.get("run_id"), "catalog_product_sha256": catalog.get("sha256")}
    run_id = hashlib.sha256(json.dumps(run_material, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:32]
    state_root = Path(args.research_state_root).expanduser().resolve()
    if not state_root.is_dir():
        raise ValueError("ANNOUNCEMENT_RESEARCH_STATE_ROOT_MISSING")
    evidence_root = state_root / "announcement_agent_runs" / run_id / "evidence"
    _mkdir(evidence_root)
    catalog_path = evidence_root / "catalog_read.json"
    _write_exclusive(catalog_path, catalog_read)
    from ops.manager_announcement_body_batch import run_capture
    body_batch = run_capture(catalog_read, state_root / "materials", evidence_root / "body_batch",
                             target, publication)
    body_path = evidence_root / "body_corpus.json"
    body_manifest_path = evidence_root / "body_corpus_manifest.json"
    _publish_body_batch(evidence_root, body_batch)
    body_batch_receipt = evidence_root / "body_batch_receipt.json"
    capture_receipt = {"schema_version": "v4.manager_research.announcement_daily_capture.v1",
        "status": body_batch.get("status"), "evidence_run_id": run_id,
        "target_trade_date": target, "publication_date": publication,
        "catalog_run_id": catalog.get("run_id"), "catalog_product_sha256": catalog.get("sha256"),
        "catalog_read_file_sha256": _file_sha(catalog_path), "body_corpus_file_sha256": _file_sha(body_path),
        "body_corpus_manifest_file_sha256": _file_sha(body_manifest_path),
        "body_batch_receipt_sha256": _file_sha(body_batch_receipt),
        "semantic_status": "NOT_REVIEWED", "first_hkex_publication_time": "CANNOT_CONFIRM",
        "original_point_in_time_availability": "CANNOT_CONFIRM", **FLAGS}
    _write_exclusive(evidence_root / "capture_receipt.json", capture_receipt)
    return capture_receipt


def _publish_body_batch(evidence_root: Path, batch: dict[str, Any]) -> None:
    # Receipt hashes bind bytes, not the decoded JSON value. Never reserialize.
    if (batch.get("body_corpus") != "body_corpus.json"
            or batch.get("body_corpus_manifest") != "body_corpus_manifest.json"):
        raise ValueError("ANNOUNCEMENT_BATCH_ARTIFACT_PATH_INVALID")
    batch_root = evidence_root / "body_batch"
    if _load(batch_root / "batch_receipt.json") != batch:
        raise ValueError("ANNOUNCEMENT_BATCH_RECEIPT_MISMATCH")
    for name,key in (("body_corpus.json","body_corpus_sha256"),
                     ("body_corpus_manifest.json","body_corpus_manifest_sha256")):
        if _file_sha(batch_root / name) != batch.get(key):
            raise ValueError("ANNOUNCEMENT_BATCH_SOURCE_SHA_MISMATCH")
    for source,destination in (("body_corpus.json","body_corpus.json"),
            ("body_corpus_manifest.json","body_corpus_manifest.json"),
            ("batch_receipt.json","body_batch_receipt.json")):
        _copy_json_bytes(batch_root / source,evidence_root / destination)


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
    rows = body_batch._validate_catalog(api, catalog_read, store, target, publication)

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
        batch = body_batch.run_capture(catalog_read, material_root, body_root, target, publication)

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
            or body.get("schema") != "v4.manager_research.eastmoney_hk_announcement_body_corpus.v3"
            or body.get("target_notice_date") != publication
            or body.get("article_count") != len(rows)
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
        _mkdir(destination.parent)
        try:
            _write_new(destination, raw)
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
        "semantic_status": "NOT_REVIEWED", "first_hkex_publication_time": "CANNOT_CONFIRM",
        "original_point_in_time_availability": "CANNOT_CONFIRM", **FLAGS}
    receipt_path = evidence_root / "capture_receipt.json"
    try:
        _write_new(receipt_path, (json.dumps(capture_receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8"))
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
    _mkdir(destination.parent)
    try:
        _write_new(destination, raw)
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
        "catalog_read.json": _file_sha(catalog_path), "body_corpus.json": body_sha,
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
    validate_agent_judgment_receipt(receipt, product)
    product_path = evidence / "analysis_product.json"
    product_raw = (json.dumps(product, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    try:
        _write_new(product_path, product_raw)
    except FileExistsError:
        if product_path.read_bytes() != product_raw:
            raise ValueError("ANNOUNCEMENT_HANDOFF_PRODUCT_EXISTS_WITH_DIFFERENT_BYTES")
    files["analysis_product.json"] = hashlib.sha256(product_raw).hexdigest()
    manifest["files"] = files
    manifest["product_sha256"] = product["sha256"]
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
    register.add_argument("--parent-task-id", required=True)
    register.add_argument("--reader-identity", required=True)
    register.add_argument("--reviewer-identity", required=True)
    readback = sub.add_parser("readback", help="read exact owner product and import receipt")
    readback.add_argument("--target-date", required=True)
    readback.add_argument("--publication-date", required=True)
    readback.add_argument("--api-base", required=True)
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
        else:
            result = _readback(args)
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    except (OSError, ValueError, KeyError, TypeError, HTTPError) as exc:
        print(json.dumps({"status": "FAILED", "reason": str(exc), **FLAGS}, ensure_ascii=False, sort_keys=True))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
