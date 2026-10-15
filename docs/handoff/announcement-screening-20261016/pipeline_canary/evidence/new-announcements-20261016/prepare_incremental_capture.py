#!/usr/bin/env python3
"""Prepare auditable announcement capture and mixed-history sample artifacts.

This helper only reads frozen local evidence/config/lease metadata and writes
files inside this evidence directory. It never grants a lease, calls a source,
submits a CaptureJobs job, or calls a model. Real source capture remains an
explicit later operation through the existing capture_window owner.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import inspect
import json
from pathlib import Path
from typing import Any


REPO = Path("/Users/lexi/Desktop/学习/v4_app")
OUT = Path(__file__).resolve().parent
SOURCE_EVIDENCE = Path(
    "/Users/lexi/Desktop/学习/agents调试/助手/qwen_flash_next_20261013/"
    "pipeline_canary/evidence/recent-day-20261014"
)
SOURCE_RECORDS = SOURCE_EVIDENCE / "source-window-records.jsonl"
TRIAGE = SOURCE_EVIDENCE / "triage-manifest.json"
CANDIDATE = SOURCE_EVIDENCE / "candidate-172/ready-v2/candidate-manifest.json"
QUEUE_STATE = SOURCE_EVIDENCE / (
    "candidate-172/ready-v2/queue-state/"
    "recent-day-20261014-172-fbfa1f6bd4e1e1e58947/queue-state.json"
)
RECOVERY_CANDIDATE = SOURCE_EVIDENCE / "candidate-172/recovery-balanced-v1/candidate-manifest.json"
RECOVERY_QUEUE_STATE = SOURCE_EVIDENCE / (
    "candidate-172/recovery-balanced-v1/queue-state/"
    "recent-day-20261014-172-recovery-ba29d61e4f608ab73b35/queue-state.json"
)
PROBE_RECEIPT = SOURCE_EVIDENCE / "candidate-172/recovery-balanced-v1/probe-stop-receipt.json"
PROBE_REVIEW = SOURCE_EVIDENCE / "candidate-172/recovery-balanced-v1/first-probe-semantic-review.json"
CONFIG = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v4.local/config/"
    "oversold-nextday-recovery-20261015-r1.json"
)
CAPTURE_ROOT = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v4.local/state/manager_workbench_capture"
)
LEASE_ROOT = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v4.local/state/manager_workbench_source_leases"
)
LEASE_FILE = LEASE_ROOT / "leases/EASTMONEY_HK.json"
PREVIOUS_RIGHT = "2026-10-14T21:43:25+08:00"
RESEARCH_RIGHT = "2026-10-16T00:14:26+08:00"
TARGET_DATE = "20261016"
PUBLICATION_DATES = ("20261014", "20261015", "20261016")
OWNER = "v4.manager_workbench.capture_announcements"
SOURCE = "EASTMONEY_HK"
EXPLICIT_RETEST_ID = "AN202610141830469351"
KNOWN_TARGETED_IDS = {"AN202610141830470256", "AN202610141830469348"}
CHUNK_DEVELOPMENT_IDS = {"AN202610141830470198", "AN202610141830425814"}


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def stable_pick(bucket: str, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    return min(
        candidates,
        key=lambda row: hashlib.sha256(
            f"capability-sample-v1|{TARGET_DATE}|{bucket}|{row['art_code']}|{row['body_text_sha256']}".encode()
        ).hexdigest(),
    )


def _capture_plan() -> dict[str, Any]:
    import sys

    sys.path.insert(0, str(REPO))
    from v4.manager_workbench.contracts import Phase, RunContext
    from v4.manager_workbench.inputs.capture import capture_window, resolve_publication_window
    from v4.manager_workbench.inputs.capture_store import OWNER as CANONICAL_OWNER

    cfg = read_json(CONFIG)
    lease = read_json(LEASE_FILE)
    if cfg.get("capture_enabled") is not False or cfg.get("capture_lease_token"):
        raise RuntimeError("CAPTURE_CONFIG_NOT_DISABLED_OR_TOKEN_PRESENT")
    if Path(cfg.get("capture_root", "")).resolve() != CAPTURE_ROOT.resolve():
        raise RuntimeError("CAPTURE_ROOT_MISMATCH")
    if Path(cfg.get("capture_lease_root", "")).resolve() != LEASE_ROOT.resolve():
        raise RuntimeError("CAPTURE_LEASE_ROOT_MISMATCH")
    if CANONICAL_OWNER != OWNER or lease.get("owner") != OWNER or lease.get("source") != SOURCE:
        raise RuntimeError("CAPTURE_OWNER_OR_SOURCE_MISMATCH")
    if lease.get("enabled") is not False:
        raise RuntimeError("CAPTURE_LEASE_NOT_REVOKED")

    ctx = RunContext(
        target_date=TARGET_DATE,
        phase=Phase.MANUAL,
        cutoff=RESEARCH_RIGHT,
        trigger="MANUAL",
        rules_version=str(cfg.get("rules_version", "")),
    )
    windows = [resolve_publication_window(ctx, publication_date=day) for day in PUBLICATION_DATES]
    expected_dates = ["2026-10-14", "2026-10-15", "2026-10-16"]
    if [w["publication_dates"] for w in windows] != [[d] for d in expected_dates]:
        raise RuntimeError("CAPTURE_PUBLICATION_DATE_PLAN_MISMATCH")

    left = datetime.fromisoformat(PREVIOUS_RIGHT)
    right = datetime.fromisoformat(RESEARCH_RIGHT)
    prepared_at = datetime.now(timezone.utc)
    sample = [
        {"art_code": "LEFT", "display_time": PREVIOUS_RIGHT},
        {"art_code": "RIGHT", "display_time": RESEARCH_RIGHT},
        {"art_code": "OUTSIDE_LEFT", "display_time": "2026-10-14T21:43:24.999000+08:00"},
        {"art_code": "OUTSIDE_RIGHT", "display_time": "2026-10-16T00:14:26.001000+08:00"},
    ]
    included = [
        row["art_code"] for row in sample
        if left <= datetime.fromisoformat(row["display_time"]) <= right
    ]
    if included != ["LEFT", "RIGHT"]:
        raise RuntimeError("INCREMENTAL_DISPLAY_BOUNDARY_CHECK_FAILED")

    expires_at = datetime.fromisoformat(lease["expires_at"])
    if expires_at.tzinfo is None or expires_at.utcoffset() is None:
        raise RuntimeError("CAPTURE_LEASE_EXPIRY_TIMEZONE_MISSING")
    plan = {
        "schema_version": "v4.announcement_incremental_capture_lease_plan.v1",
        "prepared_at_utc": prepared_at.isoformat(),
        "cutoff_state_at_prepare": "PAST_AT_PREPARATION" if prepared_at.astimezone(right.tzinfo) > right else "FUTURE_AT_PREPARATION",
        "owner": OWNER,
        "source": SOURCE,
        "entrypoint": "v4.manager_workbench.inputs.capture.capture_window",
        "entrypoint_source_path": inspect.getsourcefile(capture_window),
        "entrypoint_source_sha256": file_sha(Path(inspect.getsourcefile(capture_window))),
        "capture_store_owner": CANONICAL_OWNER,
        "capture_root": str(CAPTURE_ROOT),
        "lease_root": str(LEASE_ROOT),
        "config_path": str(CONFIG),
        "config_sha256": file_sha(CONFIG),
        "config_capture_enabled": False,
        "config_lease_token_present": False,
        "lease_state": {k: lease.get(k) for k in ("owner", "source", "enabled", "granted_at", "expires_at", "revoked_at")},
        "lease_file_sha256": file_sha(LEASE_FILE),
        "lease_expired_at_prepare": expires_at.astimezone(timezone.utc) <= prepared_at,
        "lease_policy": {
            "must_wait_for_independent_review_pass": True,
            "must_wait_for_explicit_user_approval": True,
            "grant_now": False,
            "capture_now": False,
            "automatic_grant": False,
            "maximum_duration_seconds": 3300,
            "maximum_duration_minutes": 55,
            "explicitly_revoke_in_finally": True,
            "reject_active_or_other_owner_lease": True,
        },
        "call_plan": {
            "target_trade_date": TARGET_DATE,
            "cutoff": RESEARCH_RIGHT,
            "publication_dates": list(PUBLICATION_DATES),
            "calls": [
                {
                    "publication_date": day,
                    "window": window,
                    "call": "capture_window(context, {publication_date, max_bodies, transport}, existing_capture_store)",
                }
                for day, window in zip(PUBLICATION_DATES, windows)
            ],
            "max_bodies_per_date": 20000,
            "actual_owner_time_semantics": "publication_date daily windows; later incremental filter uses inclusive display_time bounds",
            "incremental_display_window": {
                "left_inclusive": PREVIOUS_RIGHT,
                "right_inclusive": RESEARCH_RIGHT,
                "field": "display_time",
                "source_basis": "EASTMONEY_HK date catalogue mirror; not HKEX first-publication time",
            },
            "deduplicate_by": "EASTMONEY:{art_code}",
            "after_cutoff_policy": "preserve captured_at/available_at; keep PIT=CANNOT_CONFIRM; never rewrite timestamps",
            "do_not_call": ["CaptureJobs.submit", "CaptureJobs._work", "model inference"],
        },
        "dry_run_checks": {
            "publication_date_windows_valid": True,
            "left_and_right_seconds_inclusive": included == ["LEFT", "RIGHT"],
            "outside_neighbors_excluded": True,
            "prior_and_cross_product_duplicates_removed": True,
            "lease_grant_calls": 0,
            "capture_window_calls": 0,
            "source_http_calls": 0,
            "model_calls": 0,
            "capture_store_writes": 0,
            "lease_store_writes": 0,
            "other_application_state_writes": 0,
        },
        "safety": {
            "research_only": True,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        },
    }
    synthetic_products = [
        {"owner": OWNER, "source": SOURCE, "rows": sample},
        {"owner": OWNER, "source": SOURCE, "rows": [{"art_code": "RIGHT", "display_time": RESEARCH_RIGHT}]},
    ]
    deduped = filter_incremental_owner_rows(synthetic_products, {"EASTMONEY:LEFT"})
    if [row["art_code"] for row in deduped] != ["RIGHT"]:
        raise RuntimeError("INCREMENTAL_DISPLAY_DEDUP_CHECK_FAILED")
    return plan


def capture_with_existing_owner(context: Any, publication_date: str, capture_store: Any, transport: Any) -> dict[str, Any]:
    """Invoke the canonical owner for one exact date after approval and lease setup.

    This wrapper never grants a lease. The caller must pass the already
    configured CaptureStore and transport; capture_window enforces the active
    exclusive lease at each network/write boundary.
    """
    if publication_date not in PUBLICATION_DATES:
        raise ValueError("PUBLICATION_DATE_OUTSIDE_FROZEN_PLAN")
    import sys

    sys.path.insert(0, str(REPO))
    from v4.manager_workbench.inputs.capture import capture_window
    from v4.manager_workbench.inputs.capture_store import OWNER as CANONICAL_OWNER

    if CANONICAL_OWNER != OWNER or getattr(capture_store, "source", None) != SOURCE:
        raise ValueError("CAPTURE_OWNER_OR_SOURCE_MISMATCH")
    capture_store.assert_exclusive_owner(OWNER)
    return capture_window(
        context,
        {"publication_date": publication_date, "max_bodies": 20000, "transport": transport},
        capture_store,
    )


def filter_incremental_owner_rows(products: list[dict[str, Any]], prior_article_ids: set[str]) -> list[dict[str, Any]]:
    """Filter owner products to the frozen inclusive display-time window and deduplicate."""
    left = datetime.fromisoformat(PREVIOUS_RIGHT)
    right = datetime.fromisoformat(RESEARCH_RIGHT)
    seen = set(prior_article_ids)
    selected: list[dict[str, Any]] = []
    for product in products:
        if product.get("owner") != OWNER or product.get("source") != SOURCE:
            raise ValueError("CAPTURE_PRODUCT_OWNER_OR_SOURCE_MISMATCH")
        for row in product.get("rows", []):
            code = row.get("art_code")
            display = row.get("display_time")
            if not isinstance(code, str) or not isinstance(display, str):
                raise ValueError("CAPTURE_ROW_IDENTITY_OR_TIME_MISSING")
            instant = datetime.fromisoformat(display)
            if instant.tzinfo is None or instant.utcoffset() is None:
                raise ValueError("CAPTURE_ROW_TIMEZONE_MISSING")
            if not left <= instant <= right:
                continue
            article_id = f"EASTMONEY:{code}"
            if article_id in seen:
                continue
            seen.add(article_id)
            selected.append({**row, "article_id": article_id})
    return selected


def _prior_attempt_inventory() -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    queue_specs = (
        ("ready-v2", QUEUE_STATE, CANDIDATE),
        ("recovery-balanced-v1", RECOVERY_QUEUE_STATE, RECOVERY_CANDIDATE),
    )
    attempts: dict[str, dict[str, Any]] = {}
    queue_reports: list[dict[str, Any]] = []
    for label, state_path, manifest_path in queue_specs:
        state = read_json(state_path)
        manifest = read_json(manifest_path)
        jobs = state.get("jobs", {})
        incomplete: list[str] = []
        queue_attempts = 0
        queue_article_ids: set[str] = set()
        for key, job in jobs.items():
            attempt_count = int(job.get("attempt_count", 0))
            if attempt_count < 1:
                continue
            queue_attempts += attempt_count
            job_dir = state_path.parent / "jobs" / key
            request_path = job_dir / "input.json"
            response_paths = sorted(job_dir.glob("attempt-*.raw"))
            if not request_path.is_file() or len(response_paths) < attempt_count:
                incomplete.append(key)
                continue
            request_raw = request_path.read_bytes()
            request = json.loads(request_raw)
            article_id = request.get("article_id")
            if not isinstance(article_id, str) or not article_id.startswith("EASTMONEY:"):
                raise RuntimeError("PRIOR_REQUEST_ARTICLE_ID_INVALID")
            art_code = article_id.split(":", 1)[1]
            queue_article_ids.add(art_code)
            request_body = request.get("article_body")
            if not isinstance(request_body, str):
                raise RuntimeError("PRIOR_REQUEST_BODY_INVALID")
            request_body_sha256 = hashlib.sha256(request_body.encode("utf-8")).hexdigest()
            if request_body_sha256 != request.get("body_sha256"):
                raise RuntimeError("PRIOR_REQUEST_BODY_HASH_MISMATCH")
            entry = attempts.setdefault(art_code, {"article_id": article_id, "model_request_count": 0, "queue_evidence": []})
            entry["model_request_count"] += attempt_count
            entry["queue_evidence"].append({
                "queue_label": label,
                "queue_id": manifest.get("queue", {}).get("queue_id"),
                "attempt_count": attempt_count,
                "request_path": str(request_path),
                "request_sha256": hashlib.sha256(request_raw).hexdigest(),
                "request_body_sha256": request_body_sha256,
                "raw_responses": [
                    {"path": str(path), "sha256": file_sha(path)} for path in response_paths
                ],
            })
        if incomplete:
            raise RuntimeError("PRIOR_ATTEMPT_REQUEST_OR_RAW_MISSING")
        started = sum(1 for e in state.get("events", []) if e.get("event") == "attempt_started")
        persisted = sum(1 for e in state.get("events", []) if e.get("event") == "raw_persisted")
        queue_reports.append({
            "queue_label": label,
            "queue_state_path": str(state_path),
            "queue_state_sha256": file_sha(state_path),
            "candidate_manifest_path": str(manifest_path),
            "candidate_manifest_sha256": file_sha(manifest_path),
            "queue_id": manifest.get("queue", {}).get("queue_id"),
            "queue_job_count": len(jobs),
            "attempted_article_count": len(queue_article_ids),
            "model_request_attempt_count": queue_attempts,
            "attempt_started_events": started,
            "raw_persisted_events": persisted,
            "request_files_with_raw_response": len(queue_article_ids),
            "attempt_free_pending_count": sum(1 for j in jobs.values() if int(j.get("attempt_count", 0)) == 0),
            "all_attempts_have_input_and_raw": not incomplete and started == persisted == queue_attempts,
        })
    if len(queue_reports) != 2 or any(not q["all_attempts_have_input_and_raw"] for q in queue_reports):
        raise RuntimeError("PRIOR_QUEUE_ATTEMPT_INVENTORY_INCOMPLETE")
    manifest = read_json(CANDIDATE)
    inventory = {
        "queue_reports": queue_reports,
        "attempted_article_count_union": len(attempts),
        "model_request_attempt_count_sum": sum(q["model_request_attempt_count"] for q in queue_reports),
        "candidate_manifest_model_called_at_freeze": manifest.get("safety", {}).get("model_called"),
        "candidate_manifest_attempts_at_freeze": manifest.get("queue", {}).get("attempts_at_freeze"),
        "manifest_low_priority_isolated_count": len(manifest.get("isolated_ids", {}).get("low_priority", [])),
        "all_observed_attempts_have_input_and_raw": True,
        "recovery_probe_receipt_path": str(PROBE_RECEIPT),
        "recovery_probe_receipt_sha256": file_sha(PROBE_RECEIPT),
        "semantic_review_path": str(PROBE_REVIEW),
        "semantic_review_sha256": file_sha(PROBE_REVIEW),
    }
    probe = read_json(PROBE_RECEIPT)
    review = read_json(PROBE_REVIEW)
    if probe.get("article_id", "").split(":")[-1] != EXPLICIT_RETEST_ID or review.get("article_id") != probe.get("article_id"):
        raise RuntimeError("RETEST_EVIDENCE_ID_MISMATCH")
    inventory["explicit_retest_article_id"] = probe["article_id"]
    inventory["explicit_retest_attempt_count"] = probe.get("attempt_count")
    inventory["explicit_retest_response_sha256"] = probe.get("raw_response_sha256")
    inventory["explicit_retest_semantic_review_verdict"] = review.get("verdict")
    return attempts, inventory


def _sample_artifacts() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    records = read_jsonl(SOURCE_RECORDS)
    triage_doc = read_json(TRIAGE)
    triage = {row["art_code"]: row for row in triage_doc.get("article_triage", [])}
    prior, attempt_inventory = _prior_attempt_inventory()
    candidate = read_json(CANDIDATE)
    low_priority = set(candidate.get("isolated_ids", {}).get("low_priority", []))
    low_priority_codes = {str(item).split(":")[-1] for item in low_priority}

    by_code = {row.get("art_code"): row for row in records}
    if len(records) != len(by_code) or set(by_code) != set(triage):
        raise RuntimeError("SOURCE_RECORD_TRIAGE_IDENTITY_MISMATCH")
    valid: list[dict[str, Any]] = []
    invalid_count = 0
    for row in records:
        body = row.get("body_text")
        computed = hashlib.sha256(body.encode("utf-8")).hexdigest() if isinstance(body, str) else None
        t = triage[row["art_code"]]
        if not (
            row.get("body_complete") is True
            and isinstance(body, str)
            and bool(body.strip())
            and computed == row.get("body_text_sha256") == row.get("computed_body_text_sha256")
            and t.get("body_status") == "COMPLETE_HASH_VERIFIED"
            and row.get("source_sha256") == t.get("source_sha256")
        ):
            invalid_count += 1
            continue
        valid.append(row)

    def pool(bucket: str, *, require_seen: bool | None, low_only: bool = False) -> list[dict[str, Any]]:
        out = []
        for row in valid:
            code = row["art_code"]
            if triage[code].get("route_bucket") != bucket:
                continue
            is_seen = code in prior
            if require_seen is not None and is_seen != require_seen:
                continue
            if low_only and code not in low_priority_codes:
                continue
            if code in KNOWN_TARGETED_IDS or code in CHUNK_DEVELOPMENT_IDS:
                continue
            out.append(row)
        return out

    selected: list[tuple[dict[str, Any], str, str]] = []
    retest_row = by_code.get(EXPLICIT_RETEST_ID)
    if not retest_row or retest_row not in valid or EXPLICIT_RETEST_ID not in prior:
        raise RuntimeError("EXPLICIT_RETEST_SAMPLE_UNAVAILABLE")
    selected.append((retest_row, "operating_performance", "RETEST"))
    selected.append((stable_pick("corporate_action", pool("corporate_action_review", require_seen=True)), "corporate_action", "DEVELOPMENT"))
    selected.append((stable_pick("risk", pool("risk_review", require_seen=True)), "risk", "DEVELOPMENT"))
    selected.append((stable_pick("routine_share_capital", pool("share_capital_follow_up", require_seen=False, low_only=True)), "routine", "UNSEEN"))
    selected.append((stable_pick("routine_meeting", pool("earnings_or_meeting_follow_up", require_seen=False, low_only=True)), "routine", "UNSEEN"))
    selected.append((stable_pick("routine_governance", pool("governance_or_corporate_action_follow_up", require_seen=False, low_only=True)), "routine", "UNSEEN"))

    input_rows: list[dict[str, Any]] = []
    sample_rows: list[dict[str, Any]] = []
    for index, (row, stratum, history_class) in enumerate(selected, start=1):
        code = row["art_code"]
        t = triage[code]
        article_id = f"EASTMONEY:{code}"
        history = prior.get(code)
        prior_requests = history.get("queue_evidence", []) if history else []
        if history and (
            not prior_requests
            or any(item.get("request_body_sha256") != row.get("body_text_sha256") for item in prior_requests)
        ):
            raise RuntimeError("PRIOR_REQUEST_SOURCE_BODY_IDENTITY_MISMATCH")
        if history_class == "RETEST" and not history:
            raise RuntimeError("RETEST_ATTEMPT_EVIDENCE_MISSING")
        if history_class == "DEVELOPMENT" and not history:
            raise RuntimeError("DEVELOPMENT_ATTEMPT_EVIDENCE_MISSING")
        if history_class == "UNSEEN" and (history or code not in low_priority_codes):
            raise RuntimeError("UNSEEN_LOW_PRIORITY_EVIDENCE_MISMATCH")
        raw = row.get("raw_row", {})
        publication_date = str(raw.get("notice_date", ""))[:10]
        pages = row.get("pages", [])
        page_refs = [p.get("source_ref", {}) for p in pages if isinstance(p, dict)]
        available = [ref.get("available_at") for ref in page_refs if ref.get("available_at")]
        input_row = {
            "article_id": article_id,
            "market": "HK",
            "source": SOURCE,
            "publication_date": publication_date,
            "source_display_time": row.get("display_time"),
            "title": row.get("title"),
            "article_body": row.get("body_text"),
            "issuer_codes": [
                {"code": item.get("code"), "name": item.get("name"), "source_stock_code": item.get("source_stock_code")}
                for item in row.get("source_issuer_codes", [])
            ],
            "source_evidence": {
                "owner": OWNER,
                "source_sha256": row.get("source_sha256"),
                "body_sha256": row.get("body_text_sha256"),
                "body_artifact_ref": row.get("body_artifact_ref"),
                "listing_source_ref": row.get("listing_source_ref"),
                "body_page_evidence": [
                    {k: ref.get(k) for k in ("evidence_id", "role", "sha256", "available_at", "source_url", "artifact_ref", "verification")}
                    for ref in page_refs
                ],
                "available_at": max(available) if available else None,
                "first_hkex_publication_time": "CANNOT_CONFIRM",
                "original_point_in_time_availability": "CANNOT_CONFIRM",
            },
        }
        input_rows.append(input_row)
        sample_evidence = {
            "sample_index": index,
            "article_id": article_id,
            "art_code": code,
            "title": row.get("title"),
            "stratum": stratum,
            "source_route_bucket": t.get("route_bucket"),
            "source_route": t.get("route"),
            "history_class": history_class,
            "body_complete": True,
            "body_sha256": row.get("body_text_sha256"),
            "source_sha256": row.get("source_sha256"),
            "body_bytes": len(row["body_text"].encode("utf-8")),
            "input_line_sha256": canonical_sha(input_row),
            "source_row_index": row.get("record_index"),
            "previous_model_evidence": history,
            "retest_receipt": (
                {
                    "path": str(PROBE_RECEIPT),
                    "sha256": file_sha(PROBE_RECEIPT),
                    "raw_response_sha256": read_json(PROBE_RECEIPT).get("raw_response_sha256"),
                    "semantic_review_path": str(PROBE_REVIEW),
                    "semantic_review_sha256": file_sha(PROBE_REVIEW),
                    "semantic_review_verdict": read_json(PROBE_REVIEW).get("verdict"),
                }
                if history_class == "RETEST" else None
            ),
            "history_basis": (
                "explicit single-probe request and raw response were reviewed; regression/retest only"
                if history_class == "RETEST" else
                "actual model request input.json and raw response exist; not a sealed blind item"
                if history_class == "DEVELOPMENT" else
                "no request/raw response for this ID in inspected queue state; isolated as low priority in the inspected candidate manifest"
            ),
        }
        sample_rows.append(sample_evidence)

    if len(input_rows) != 6 or len({r["article_id"] for r in input_rows}) != 6:
        raise RuntimeError("CAPABILITY_SAMPLE_COUNT_OR_DEDUP_FAILED")
    forbidden_keys = {"route", "route_bucket", "classification", "answer", "summary", "judgment", "previous_model_evidence", "history_class"}
    if any(forbidden_keys & set(r) for r in input_rows):
        raise RuntimeError("MODEL_INPUT_LABEL_OR_ANSWER_FIELD_PRESENT")
    counts: dict[str, dict[str, int]] = {}
    for bucket, label in (
        ("operating_review", "operating_performance"),
        ("corporate_action_review", "corporate_action"),
        ("risk_review", "risk"),
        ("share_capital_follow_up", "routine_share_capital"),
        ("earnings_or_meeting_follow_up", "routine_meeting"),
        ("governance_or_corporate_action_follow_up", "routine_governance"),
    ):
        pool_rows = [r for r in valid if triage[r["art_code"]].get("route_bucket") == bucket]
        counts[label] = {
            "complete_source_rows": len(pool_rows),
            "with_actual_prior_model_request": sum(r["art_code"] in prior for r in pool_rows),
            "without_actual_prior_model_request": sum(r["art_code"] not in prior for r in pool_rows),
        }
    sample_manifest = {
        "schema_version": "v4.announcement.capability_sample_manifest.v1",
        "status": "PREPARED_MIXED_HISTORY_NOT_SEALED_BLIND",
        "purpose": "small research-only announcement text capability sample; no inference executed",
        "selection_algorithm": "fixed explicit probe for RETEST; otherwise minimum SHA256(seed|target|bucket|art_code|body_sha256) among complete hash-verified rows matching the prior-request class",
        "selection_seed": "capability-sample-v1|20261016",
        "source_window_reference": {
            "path": str(SOURCE_RECORDS),
            "sha256": file_sha(SOURCE_RECORDS),
            "triage_path": str(TRIAGE),
            "triage_sha256": file_sha(TRIAGE),
            "capture_product_shas": [x.get("sha256") for x in read_json(TRIAGE).get("capture_products", []) if isinstance(x, dict)],
        },
        "attempt_inventory": attempt_inventory,
        "complete_source_record_count": len(valid),
        "rejected_source_record_count": invalid_count,
        "class_counts": counts,
        "sample": sample_rows,
        "input_file": str(OUT / "capability-sample-inputs.jsonl"),
        "input_file_contains_route_or_answer": False,
        "input_file_contains_prior_output": False,
        "all_samples_body_hash_verified": True,
        "all_samples_original_pit_status": "CANNOT_CONFIRM",
        "safety": {"research_only": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False},
    }
    return input_rows, sample_manifest


def main() -> int:
    plan = _capture_plan()
    input_rows, sample_manifest = _sample_artifacts()
    plan_path = OUT / "capture-lease-plan.json"
    inputs_path = OUT / "capability-sample-inputs.jsonl"
    manifest_path = OUT / "capability-sample-manifest.json"
    audit_path = OUT / "preparation-audit.json"
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    inputs_path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n" for row in input_rows), encoding="utf-8")
    sample_manifest["input_file_sha256"] = file_sha(inputs_path)
    sample_manifest["input_file_bytes"] = inputs_path.stat().st_size
    manifest_path.write_text(json.dumps(sample_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    audit = {
        "schema_version": "v4.announcement.incremental_capture_preparation_audit.v1",
        "status": "PREPARED_REVIEW_PENDING",
        "capture_plan_sha256": file_sha(plan_path),
        "sample_manifest_sha256": file_sha(manifest_path),
        "sample_input_sha256": file_sha(inputs_path),
        "capture_calls": 0,
        "lease_grants": 0,
        "model_calls": 0,
        "capture_store_writes": 0,
        "lease_store_writes": 0,
        "other_application_state_writes": 0,
        "evidence_directory_writes": 4,
        "external_network_calls": 0,
        "capture_enabled": plan["config_capture_enabled"],
        "lease_enabled": plan["lease_state"]["enabled"],
        "sample_count": len(input_rows),
        "sample_history_counts": {
            value: sum(1 for row in sample_manifest["sample"] if row["history_class"] == value)
            for value in ("UNSEEN", "DEVELOPMENT", "RETEST")
        },
        "sample_strata": sorted({row["stratum"] for row in sample_manifest["sample"]}),
        "sample_not_sealed_blind": True,
        "frozen_cutoff_pit_status": "CANNOT_CONFIRM for official HKEX first-publication time; any fresh post-cutoff capture retains later availability",
    }
    audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": audit["status"],
        "capture_plan": str(plan_path),
        "capture_plan_sha256": audit["capture_plan_sha256"],
        "sample_manifest": str(manifest_path),
        "sample_manifest_sha256": audit["sample_manifest_sha256"],
        "sample_inputs": str(inputs_path),
        "sample_inputs_sha256": audit["sample_input_sha256"],
        "sample_count": audit["sample_count"],
        "sample_history_counts": audit["sample_history_counts"],
        "capture_calls": 0,
        "lease_grants": 0,
        "model_calls": 0,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
