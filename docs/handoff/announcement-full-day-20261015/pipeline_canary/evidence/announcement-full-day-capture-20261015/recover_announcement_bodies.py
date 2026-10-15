"""Bounded recovery through the existing EASTMONEY_HK capture owner.

The script retries only body gaps from the frozen 2026-10-15 canonical product.
Each network request goes through CaptureStore.fetch with the existing source
identity, request scope, and body validator. Product reconstruction uses the
same capture_window entrypoint with transport=None, so only verified cache hits
can be consumed and no second network pass is possible.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
from pathlib import Path
import sys
import time
from uuid import uuid4

REPO = Path("/Users/lexi/Desktop/学习/v4_app")
BASE = Path("/Users/lexi/Desktop/学习/agents调试/助手/qwen_flash_next_20261013/pipeline_canary")
OUT = BASE / "evidence/announcement-full-day-capture-20261015"
OLD_EVIDENCE = BASE / "evidence/new-announcements-20261016"
STATE = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/state")
CONFIG = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/config/oversold-nextday-recovery-20261015-r1.json")
CAPTURE_ROOT = STATE / "manager_workbench_capture"
LEASE_ROOT = STATE / "manager_workbench_source_leases"
LEASE_FILE = LEASE_ROOT / "leases/EASTMONEY_HK.json"
OLD_PRODUCT = CAPTURE_ROOT / "products/0f473ec38e13744895973cdb04530f159420e0fc651056f24f803c33c11ce4ae.json"
OWNER = "v4.manager_workbench.capture_announcements"
SOURCE = "EASTMONEY_HK"
PUBLICATION_DATE = "2026-10-15"
CANARY_ART_CODE = "AN202610151830509956"
EXPECTED_OLD_PRODUCT_SHA = "0f473ec38e13744895973cdb04530f159420e0fc651056f24f803c33c11ce4ae"
EXPECTED_CAPTURE_SOURCE_SHA = "18ebbef7a0a56d7e61113b60b902d990ba09ed763c6084191f221dd135568578"
MAX_LEASE_SECONDS = 55 * 60
MIN_REQUEST_INTERVAL_SECONDS = 1.0
MAX_RETRY_AFTER_WAIT_SECONDS = 30.0
MAX_EXTERNAL_GETS = 3000
MAX_BODY_PAGES = 150
MAX_BODY_CHARACTERS = 1_000_000


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stable_sha(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def lease_snapshot() -> dict:
    raw = LEASE_FILE.read_bytes()
    value = json.loads(raw)
    return {
        "file_sha256": hashlib.sha256(raw).hexdigest(),
        "owner": value.get("owner"),
        "source": value.get("source"),
        "enabled": value.get("enabled"),
        "granted_at": value.get("granted_at"),
        "expires_at": value.get("expires_at"),
        "revoked_at": value.get("revoked_at"),
        "token_redacted": bool(value.get("token")),
    }


def parse_retry_after(value: str | None, now: datetime) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value.strip()))
    except (TypeError, ValueError):
        pass
    try:
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return max(0.0, (parsed.astimezone(timezone.utc) - now.astimezone(timezone.utc)).total_seconds())
    except (TypeError, ValueError, OverflowError):
        return None


class RecordingSession:
    """Serial transport that stops after global failure and records safe headers."""

    def __init__(self, requests_module, *, deadline: datetime):
        self.session = requests_module.Session()
        self.events: list[dict] = []
        self.blocked = False
        self.stop_reason: str | None = None
        self.deadline = deadline
        self.last_request_monotonic: float | None = None
        self.next_allowed_at: datetime | None = None

    def _block(self, reason: str) -> None:
        self.blocked = True
        self.stop_reason = reason

    def get(self, url: str, **kwargs):
        if self.blocked:
            raise RuntimeError("RECOVERY_STOPPED_AFTER_GLOBAL_FAILURE")
        now = datetime.now(timezone.utc)
        if now + timedelta(seconds=25) >= self.deadline:
            self._block("LEASE_DEADLINE_GUARD")
            raise RuntimeError("RECOVERY_LEASE_DEADLINE_GUARD")
        if len([event for event in self.events if event.get("network_requested")]) >= MAX_EXTERNAL_GETS:
            self._block("EXTERNAL_GET_BUDGET_REACHED")
            raise RuntimeError("RECOVERY_EXTERNAL_GET_BUDGET_REACHED")

        wait_seconds = MIN_REQUEST_INTERVAL_SECONDS
        if self.last_request_monotonic is not None:
            wait_seconds = max(0.0, MIN_REQUEST_INTERVAL_SECONDS - (time.monotonic() - self.last_request_monotonic))
        if self.next_allowed_at is not None:
            wait_seconds = max(wait_seconds, (self.next_allowed_at - now).total_seconds())
        if wait_seconds > MAX_RETRY_AFTER_WAIT_SECONDS:
            self._block("RETRY_AFTER_EXCEEDS_BOUNDED_WAIT")
            self.events.append({"network_requested": False, "url": url, "stop_reason": self.stop_reason,
                                "retry_after_wait_seconds": round(wait_seconds, 3)})
            raise RuntimeError("RECOVERY_RETRY_AFTER_EXCEEDS_BOUNDED_WAIT")
        if wait_seconds > 0:
            time.sleep(wait_seconds)

        started = datetime.now(timezone.utc)
        try:
            response = self.session.get(url, **kwargs)
        except Exception as exc:
            self.last_request_monotonic = time.monotonic()
            self.events.append({"network_requested": True, "url": url,
                                "transport_error_type": type(exc).__name__, "transport_error": str(exc)[:240]})
            self._block("TRANSPORT_ERROR")
            raise
        self.last_request_monotonic = time.monotonic()
        retry_after = response.headers.get("Retry-After")
        retry_wait = parse_retry_after(retry_after, datetime.now(timezone.utc))
        event = {
            "network_requested": True,
            "url": url,
            "status_code": response.status_code,
            "retry_after": retry_after,
            "retry_after_seconds": round(retry_wait, 3) if retry_wait is not None else None,
            "date_header": response.headers.get("Date"),
            "content_type": response.headers.get("Content-Type"),
            "content_length_header": response.headers.get("Content-Length"),
            "final_url_matches_request": getattr(response, "url", url) == url,
            "elapsed_seconds": round((datetime.now(timezone.utc) - started).total_seconds(), 3),
        }
        self.events.append(event)
        if retry_wait is not None and retry_wait > 0:
            self.next_allowed_at = datetime.now(timezone.utc) + timedelta(seconds=retry_wait)
        status = response.status_code
        if status != 200 and status != 404:
            self._block(f"HTTP_{status}")
        return response

    def close(self) -> None:
        self.session.close()


def load_context_and_store():
    sys.path.insert(0, str(REPO))
    from v4.manager_workbench.contracts import Phase, RunContext
    from v4.manager_workbench.inputs.capture import capture_window, content_url, resolve_publication_window, _body_page
    from v4.manager_workbench.inputs.capture_store import CaptureStore, OWNER as CANONICAL_OWNER, encoded
    if CANONICAL_OWNER != OWNER:
        raise RuntimeError("CANONICAL_CAPTURE_OWNER_MISMATCH")
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    if config.get("capture_enabled") is not False or config.get("capture_lease_token"):
        raise RuntimeError("CAPTURE_CONFIG_NOT_DISABLED_OR_TOKEN_PRESENT")
    if Path(config.get("capture_root", "")).resolve() != CAPTURE_ROOT.resolve():
        raise RuntimeError("CAPTURE_ROOT_MISMATCH")
    if Path(config.get("capture_lease_root", "")).resolve() != LEASE_ROOT.resolve():
        raise RuntimeError("CAPTURE_LEASE_ROOT_MISMATCH")
    if file_sha(Path(capture_window.__code__.co_filename)) != EXPECTED_CAPTURE_SOURCE_SHA:
        raise RuntimeError("CAPTURE_ENTRYPOINT_SOURCE_CHANGED")
    if file_sha(OLD_PRODUCT) != EXPECTED_OLD_PRODUCT_SHA:
        raise RuntimeError("FROZEN_OLD_PRODUCT_SHA_CHANGED")
    old = json.loads(OLD_PRODUCT.read_text(encoding="utf-8"))
    if old.get("owner") != OWNER or old.get("source") != SOURCE or len(old.get("rows", [])) != 392:
        raise RuntimeError("FROZEN_PRODUCT_IDENTITY_OR_COUNT_MISMATCH")
    if old.get("window", {}).get("publication_dates") != [PUBLICATION_DATE]:
        raise RuntimeError("FROZEN_PRODUCT_DATE_MISMATCH")
    context = RunContext(
        target_date=old["target_trade_date"], phase=Phase.MANUAL,
        cutoff=old["window"]["research_cutoff"], trigger="MANUAL",
        rules_version=str(config.get("rules_version", "")),
    )
    resolved = resolve_publication_window(context, publication_date=PUBLICATION_DATE)
    if resolved != old["window"]:
        raise RuntimeError("CANONICAL_WINDOW_DRIFT_FROM_FROZEN_PRODUCT")
    store = CaptureStore(CAPTURE_ROOT, source=SOURCE, lease_root=LEASE_ROOT)
    gaps = [row for row in old["rows"] if row.get("body_complete") is not True
            and row.get("window_consumption_status") != "EXCLUDED_OUTSIDE_WINDOW"]
    complete = [row for row in old["rows"] if row.get("body_complete") is True]
    if len(gaps) != 199 or len(complete) != 193:
        raise RuntimeError("FROZEN_BODY_COVERAGE_COUNT_MISMATCH")
    candidate = next((row for row in gaps if row.get("art_code") == CANARY_ART_CODE), None)
    if candidate is None or "CAPTURE_HTTP_STATUS_NOT_200" not in candidate.get("gaps", []):
        raise RuntimeError("FROZEN_CANARY_GAP_MISMATCH")
    scope = dict(protocol="EASTMONEY_CONTENT_V1", publication_date=PUBLICATION_DATE,
                 listing_sha256=hashlib.sha256(encoded(candidate["raw_row"])).hexdigest())
    url = content_url(CANARY_ART_CODE, 1)
    request = dict(source=SOURCE, method="GET", url=url, scope=scope)
    request_key = hashlib.sha256(encoded(request)).hexdigest()
    pointer = store._json(store.io, f"requests/{request_key}.json")
    if pointer is not None:
        raise RuntimeError("CANARY_SUCCESS_POINTER_ALREADY_EXISTS")
    attempts = []
    for name in store.io.files(f"attempts/{request_key}"):
        receipt = store._json(store.io, f"attempts/{request_key}/{name}")
        if receipt:
            attempts.append({"name": name, "status": receipt.get("status"), "error": receipt.get("error"),
                             "started_at": receipt.get("started_at")})
    if not attempts or any(item.get("status") == "CAPTURED" for item in attempts):
        raise RuntimeError("CANARY_PRIOR_ATTEMPT_STATE_UNEXPECTED")
    last_attempt = max(datetime.fromisoformat(item["started_at"]) for item in attempts)
    cooldown_seconds = (datetime.now(timezone.utc) - last_attempt.astimezone(timezone.utc)).total_seconds()
    if cooldown_seconds < 3600:
        raise RuntimeError("CANARY_COOLDOWN_NOT_ELAPSED")
    return old, context, store, gaps, complete, candidate, scope, url, request_key, attempts, cooldown_seconds, capture_window, _body_page


def redacted_product_readback(store, product: dict) -> dict:
    saved = product.get("saved_ref") or {}
    ref = saved.get("artifact_ref")
    expected_sha = saved.get("sha256")
    if not isinstance(ref, str) or not isinstance(expected_sha, str):
        raise RuntimeError("RECOVERY_PRODUCT_SAVED_REF_MISSING")
    raw = store.io.read_bytes(ref)
    if hashlib.sha256(raw).hexdigest() != expected_sha:
        raise RuntimeError("RECOVERY_PRODUCT_READBACK_SHA_MISMATCH")
    loaded = json.loads(raw)
    expected = {key: value for key, value in product.items() if key != "saved_ref"}
    if loaded != expected or loaded.get("owner") != OWNER or loaded.get("source") != SOURCE:
        raise RuntimeError("RECOVERY_PRODUCT_READBACK_CONTENT_MISMATCH")
    for row in loaded.get("rows", []):
        artifact_ref = row.get("body_artifact_ref")
        artifact_sha = row.get("source_sha256")
        if not isinstance(artifact_ref, str) or not isinstance(artifact_sha, str):
            raise RuntimeError("RECOVERY_ROW_ARTIFACT_REF_MISSING")
        article_raw = store.io.read_bytes(artifact_ref)
        if hashlib.sha256(article_raw).hexdigest() != artifact_sha:
            raise RuntimeError("RECOVERY_ROW_ARTIFACT_SHA_MISMATCH")
        article = json.loads(article_raw)
        if article.get("art_code") != row.get("art_code"):
            raise RuntimeError("RECOVERY_ROW_IDENTITY_MISMATCH")
        if row.get("body_complete") is True:
            body = row.get("body_text")
            body_sha = hashlib.sha256(body.encode("utf-8")).hexdigest() if isinstance(body, str) else None
            if body_sha != row.get("body_text_sha256"):
                raise RuntimeError("RECOVERY_BODY_TEXT_SHA_MISMATCH")
    return loaded


def derive_evidence(old: dict, product: dict, output_stem: str) -> tuple[dict, list[dict]]:
    old_rows = {row["art_code"]: row for row in old["rows"]}
    rows = product["rows"]
    if len(rows) != 392 or len({row.get("art_code") for row in rows}) != 392:
        raise RuntimeError("RECOVERY_PRODUCT_DIRECTORY_IDENTITY_MISMATCH")
    if set(old_rows) != {row.get("art_code") for row in rows}:
        raise RuntimeError("RECOVERY_PRODUCT_DIRECTORY_MEMBERSHIP_DRIFT")
    original_complete = {row["art_code"]: row["body_text_sha256"] for row in old["rows"] if row.get("body_complete") is True}
    for code, body_hash in original_complete.items():
        match = next(row for row in rows if row["art_code"] == code)
        if match.get("body_complete") is not True or match.get("body_text_sha256") != body_hash:
            raise RuntimeError("PREVIOUSLY_COMPLETE_BODY_CHANGED")
    newly_complete = [row for row in rows if row.get("body_complete") is True and old_rows[row["art_code"]].get("body_complete") is not True]
    remaining = [row for row in rows if row.get("body_complete") is not True and row.get("window_consumption_status") != "EXCLUDED_OUTSIDE_WINDOW"]
    by_reason: dict[str, int] = {}
    for row in remaining:
        for reason in row.get("gaps", []):
            by_reason[reason] = by_reason.get(reason, 0) + 1
    body_inputs = []
    for row in newly_complete:
        body_inputs.append({
            "article_id": f"EASTMONEY:{row['art_code']}",
            "source": SOURCE,
            "owner": OWNER,
            "publication_date": row["publication_date"],
            "display_time": row["display_time"],
            "publication_time_basis": row["publication_time_basis"],
            "first_hkex_publication_time": "CANNOT_CONFIRM",
            "original_point_in_time_availability": "CANNOT_CONFIRM",
            "title": row["title"],
            "source_issuer_codes": row["source_issuer_codes"],
            "body_text": row["body_text"],
            "body_text_sha256": row["body_text_sha256"],
            "source_sha256": row["source_sha256"],
            "body_artifact_ref": row["body_artifact_ref"],
            "available_at": row["available_at"],
            "pages": row["pages"],
        })
    payload = "".join(json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n" for item in body_inputs).encode("utf-8")
    input_path = OUT / f"{output_stem}-recovered-model-inputs.jsonl"
    input_path.write_bytes(payload)
    manifest = {
        "schema_version": "v4.announcement.full_day_body_recovery.v1",
        "status": "CAPTURE_RECOVERED" if not remaining else "EXTERNAL_BLOCKER_WITH_RECEIPT",
        "date": PUBLICATION_DATE,
        "owner": OWNER,
        "source": SOURCE,
        "source_product": product.get("saved_ref"),
        "previous_source_product": {"artifact_ref": "products/0f473ec38e13744895973cdb04530f159420e0fc651056f24f803c33c11ce4ae.json",
                                    "run_id": old.get("run_id"), "sha256": EXPECTED_OLD_PRODUCT_SHA},
        "directory": {"previous_rows": 392, "new_rows": len(rows), "same_art_code_set": True},
        "coverage": {"previous_complete": len(original_complete), "newly_complete": len(newly_complete),
                     "complete_total": sum(row.get("body_complete") is True for row in rows),
                     "remaining_body_gaps": len(remaining), "remaining_gap_reasons": by_reason},
        "newly_complete_articles": [{"article_id": f"EASTMONEY:{row['art_code']}", "art_code": row["art_code"],
                                      "title": row["title"], "body_text_sha256": row["body_text_sha256"],
                                      "source_sha256": row["source_sha256"], "available_at": row["available_at"]}
                                     for row in newly_complete],
        "model_input": {"path": str(input_path), "rows": len(body_inputs), "sha256": hashlib.sha256(payload).hexdigest(),
                        "contains_labels_or_answers": False},
        "pit": {"first_hkex_publication_time": "CANNOT_CONFIRM", "original_point_in_time_availability": "CANNOT_CONFIRM"},
        "research_only": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    manifest_path = OUT / f"{output_stem}-recovery-manifest.json"
    write_json(manifest_path, manifest)
    manifest["manifest_path"] = str(manifest_path)
    manifest["manifest_sha256"] = file_sha(manifest_path)
    return manifest, body_inputs


def execute() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "recovery-plan.json").write_text("", encoding="utf-8") if False else None
    (old, context, store, gaps, complete, candidate, scope, canary_url, canary_key,
     prior_attempts, cooldown_seconds, capture_window, body_page_validator) = load_context_and_store()
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    old_lease = lease_snapshot()
    if old_lease.get("enabled") is not False or old_lease.get("owner") != OWNER or old_lease.get("source") != SOURCE:
        raise RuntimeError("LEASE_NOT_REVOKED_OR_OWNER_MISMATCH")
    invocation_id = uuid4().hex
    stem = f"20261015-{invocation_id}"
    plan = {
        "schema_version": "v4.announcement.full_day_body_recovery_plan.v1",
        "invocation_id": invocation_id,
        "date": PUBLICATION_DATE,
        "owner": OWNER,
        "source": SOURCE,
        "previous_product_sha256": EXPECTED_OLD_PRODUCT_SHA,
        "previous_product_run_id": old.get("run_id"),
        "directory_rows": len(old["rows"]),
        "previous_body_complete": len(complete),
        "eligible_body_gaps": len(gaps),
        "canary": {"art_code": CANARY_ART_CODE, "title": candidate.get("title"), "url": canary_url,
                   "request_sha256": canary_key, "prior_attempts": prior_attempts,
                   "cooldown_seconds": round(cooldown_seconds, 3)},
        "maximum_lease_seconds": MAX_LEASE_SECONDS,
        "max_external_gets": MAX_EXTERNAL_GETS,
        "min_request_interval_seconds": MIN_REQUEST_INTERVAL_SECONDS,
        "old_evidence_immutable": True,
        "network_calls_before_execution": 0,
        "configuration_writes": 0,
        "model_calls": 0,
    }
    plan_path = OUT / f"{stem}-plan.json"
    write_json(plan_path, plan)
    write_json(OUT / f"{stem}-pregrant.json", {"schema_version": "v4.announcement.capture_lease_pregrant.v1",
                "invocation_id": invocation_id, "lease": old_lease, "config_sha256": file_sha(CONFIG),
                "config_capture_enabled": config.get("capture_enabled"), "config_token_present": bool(config.get("capture_lease_token"))})

    import requests
    from v4.manager_workbench.inputs.capture_store import OWNER as STORE_OWNER
    if STORE_OWNER != OWNER:
        raise RuntimeError("CANONICAL_STORE_OWNER_MISMATCH")
    transport = RecordingSession(requests, deadline=datetime.now(timezone.utc) + timedelta(seconds=MAX_LEASE_SECONDS - 60))
    grant_ok = False
    revoked = False
    operation_error = None
    revoke_error = None
    product = None
    product_readback_error = None
    recoveries: list[dict] = []
    stop_reason = None
    canary_passed = False
    recovery_manifest = None
    expires_at = store.now().astimezone(timezone.utc) + timedelta(seconds=MAX_LEASE_SECONDS)
    try:
        store.grant(expires_at=expires_at, owner=OWNER)
        grant_ok = True
        store.assert_exclusive_owner(OWNER)
        current_lease = json.loads(LEASE_FILE.read_text(encoding="utf-8"))
        if current_lease.get("enabled") is not True or current_lease.get("owner") != OWNER or current_lease.get("source") != SOURCE:
            raise RuntimeError("ACTIVE_LEASE_IDENTITY_MISMATCH")

        ordered = [candidate] + sorted((row for row in gaps if row["art_code"] != CANARY_ART_CODE),
                                       key=lambda row: (row.get("display_time", ""), row["art_code"]))
        for row_index, listing in enumerate(ordered, start=1):
            article = listing["art_code"]
            expected_total = None
            text_characters = 0
            page_count = 0
            page_errors: list[str] = []
            for page_index in range(1, MAX_BODY_PAGES + 1):
                url = __import__("v4.manager_workbench.inputs.capture", fromlist=["content_url"]).content_url(article, page_index)
                body_scope = dict(protocol="EASTMONEY_CONTENT_V1", publication_date=listing["publication_date"],
                                  listing_sha256=hashlib.sha256(__import__("v4.manager_workbench.inputs.capture_store", fromlist=["encoded"]).encoded(listing["raw_row"])).hexdigest())
                try:
                    raw, receipt = store.fetch(url, scope=body_scope, transport=transport,
                        validate=lambda value, p=page_index, total=expected_total: body_page_validator(value, listing, p, total))
                    data, matched = body_page_validator(raw, listing, page_index, expected_total)
                    expected_total = data["page_size"]
                    text_characters += len(data["notice_content"])
                    page_count += 1
                    if text_characters > MAX_BODY_CHARACTERS:
                        page_errors.append("BODY_CONTENT_TEXT_LIMIT_EXCEEDED")
                        break
                    if page_index == expected_total:
                        break
                except Exception as exc:
                    page_errors.append(str(exc)[:240])
                    break
            complete_now = expected_total is not None and page_count == expected_total and not page_errors
            result = {"art_code": article, "article_id": f"EASTMONEY:{article}", "title": listing.get("title"),
                      "page_count": page_count, "expected_page_count": expected_total,
                      "complete_from_cache_or_fetch": complete_now, "gaps": page_errors,
                      "external_get_count_after_article": sum(bool(event.get("network_requested")) for event in transport.events)}
            recoveries.append(result)
            if row_index == 1:
                canary_passed = complete_now
                if not canary_passed:
                    stop_reason = "CANARY_BODY_NOT_COMPLETE"
                    break
            if transport.blocked:
                stop_reason = transport.stop_reason
                break
            if page_errors and page_errors[0] not in {"CAPTURE_HTTP_STATUS_NOT_200"}:
                # A 404 is isolated to this source document; content/transport
                # errors remain visible and do not trigger retries for this ID.
                if not (transport.events and transport.events[-1].get("status_code") == 404):
                    stop_reason = "VALIDATION_OR_CACHE_FAILURE"
                    break

        # Build a fresh canonical product strictly from existing success cache.
        # A None transport is deliberate: this phase cannot issue external GETs.
        product = capture_window(context, {"publication_date": PUBLICATION_DATE,
                                           "max_bodies": 20000, "transport": None}, store)
        try:
            loaded = redacted_product_readback(store, product)
            product_readback_error = None
        except Exception as exc:
            loaded = None
            product_readback_error = {"type": type(exc).__name__, "message": str(exc)[:240]}
        if loaded is not None:
            recovery_manifest, _ = derive_evidence(old, product, stem)
    except Exception as exc:
        operation_error = {"type": type(exc).__name__, "message": str(exc)[:320]}
    finally:
        if grant_ok and store.token is not None:
            try:
                store.revoke()
            except Exception as exc:
                revoke_error = {"type": type(exc).__name__, "message": str(exc)[:240]}
        transport.close()

    after_lease = lease_snapshot()
    revoked = bool(grant_ok and after_lease.get("enabled") is False and after_lease.get("owner") == OWNER
                   and after_lease.get("source") == SOURCE and after_lease.get("revoked_at") and revoke_error is None)
    if product is not None:
        saved = product.get("saved_ref") or {}
        product_summary = {"run_id": product.get("run_id"), "coverage_status": product.get("coverage_status"),
                           "rows": product.get("observed_count"), "gaps": product.get("gaps"),
                           "artifact_ref": saved.get("artifact_ref"), "sha256": saved.get("sha256"),
                           "owner": product.get("owner"), "source": product.get("source")}
    else:
        product_summary = None
    input_path = OUT / f"{stem}-recovered-model-inputs.jsonl"
    manifest_path = OUT / f"{stem}-recovery-manifest.json"
    manifest_summary = None
    if manifest_path.exists():
        manifest_summary = {"path": str(manifest_path), "sha256": file_sha(manifest_path),
                            "model_input_path": str(input_path) if input_path.exists() else None,
                            "model_input_sha256": file_sha(input_path) if input_path.exists() else None}
    network_events = transport.events
    summary = {
        "schema_version": "v4.announcement.full_day_body_recovery_receipt.v1",
        "invocation_id": invocation_id,
        "plan_path": str(plan_path),
        "plan_sha256": file_sha(plan_path),
        "status": recovery_manifest.get("status") if recovery_manifest else "EXTERNAL_BLOCKER_WITH_RECEIPT",
        "owner": OWNER,
        "source": SOURCE,
        "publication_date": PUBLICATION_DATE,
        "previous_product_sha256": EXPECTED_OLD_PRODUCT_SHA,
        "canary_art_code": CANARY_ART_CODE,
        "canary_passed": canary_passed,
        "prior_attempts": prior_attempts,
        "cooldown_seconds_at_start": round(cooldown_seconds, 3),
        "maximum_lease_seconds": MAX_LEASE_SECONDS,
        "lease_granted": grant_ok,
        "lease_revoked": revoked,
        "lease_after": after_lease,
        "grant_or_capture_error": operation_error,
        "revoke_error": revoke_error,
        "stop_reason": stop_reason,
        "recovery_rows_attempted": len(recoveries),
        "recovery_row_results": recoveries,
        "external_get_count": sum(bool(event.get("network_requested")) for event in network_events),
        "http_events": network_events,
        "canonical_product_readback_error": product_readback_error,
        "canonical_product": product_summary,
        "derived_manifest": manifest_summary,
        "model_calls": 0,
        "api_calls": 0,
        "configuration_writes": 0,
        "research_only": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    receipt_path = OUT / f"{stem}-recovery-receipt.json"
    write_json(receipt_path, summary)
    print(json.dumps({"receipt_path": str(receipt_path), "receipt_sha256": file_sha(receipt_path), **summary},
                     ensure_ascii=False, indent=2))
    if not revoked:
        return 2
    return 0 if summary["status"] == "CAPTURE_RECOVERED" else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="perform approved temporary-lease recovery")
    args = parser.parse_args()
    if not args.execute:
        old, _, _, gaps, complete, candidate, scope, url, request_key, attempts, cooldown, _, _ = load_context_and_store()
        plan = {"status": "DRY_RUN_PASS", "external_network_calls": 0, "lease_grants": 0,
                "state_writes": 0, "old_product_sha256": EXPECTED_OLD_PRODUCT_SHA,
                "date": PUBLICATION_DATE, "rows": len(old["rows"]), "complete": len(complete),
                "gaps": len(gaps), "canary_art_code": candidate["art_code"],
                "canary_request_sha256": request_key, "canary_prior_attempts": attempts,
                "cooldown_seconds": round(cooldown, 3), "url": url,
                "body_scope_sha256": hashlib.sha256(json.dumps(scope, sort_keys=True, separators=(",", ":")).encode()).hexdigest()}
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0
    return execute()


if __name__ == "__main__":
    raise SystemExit(main())
