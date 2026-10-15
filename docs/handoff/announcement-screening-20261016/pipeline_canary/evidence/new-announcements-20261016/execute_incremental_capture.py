"""One-date operator wrapper for the already-reviewed canonical HK capture owner.

The token exists only in this process and the canonical lease record required by
CaptureStore. This runner never reads it back into evidence or stdout. The lease
is revoked in finally even when capture or readback fails.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from uuid import uuid4

REPO = Path("/Users/lexi/Desktop/学习/v4_app")
OUT = Path(__file__).resolve().parent
PLAN_PATH = OUT / "capture-lease-plan.json"
EXPECTED_PLAN_SHA256 = "dda90cdc30ae3115566aa174ee7426fac1f2f3690dc2a970972a28b3c8304ae4"
CONFIG = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/config/oversold-nextday-recovery-20261015-r1.json")
CAPTURE_ROOT = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/state/manager_workbench_capture")
LEASE_ROOT = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/state/manager_workbench_source_leases")
LEASE_FILE = LEASE_ROOT / "leases/EASTMONEY_HK.json"
OWNER = "v4.manager_workbench.capture_announcements"
SOURCE = "EASTMONEY_HK"
ALLOWED_DATES = ("20261014", "20261015", "20261016")
MAX_LEASE_SECONDS = 55 * 60


def raw_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def redacted_lease_snapshot() -> dict:
    raw = LEASE_FILE.read_bytes()
    record = json.loads(raw)
    return {
        "path": str(LEASE_FILE),
        "file_sha256": hashlib.sha256(raw).hexdigest(),
        "owner": record.get("owner"),
        "source": record.get("source"),
        "enabled": record.get("enabled"),
        "granted_at": record.get("granted_at"),
        "expires_at": record.get("expires_at"),
        "revoked_at": record.get("revoked_at"),
        "token_redacted": "token" in record,
    }


def load_preparation_module():
    path = OUT / "prepare_incremental_capture.py"
    spec = importlib.util.spec_from_file_location("announcement_capture_preparation", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("PREPARATION_MODULE_LOAD_FAILED")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verify_frozen_plan(publication_date: str):
    if publication_date not in ALLOWED_DATES:
        raise ValueError("PUBLICATION_DATE_OUTSIDE_FROZEN_PLAN")
    if raw_sha(PLAN_PATH) != EXPECTED_PLAN_SHA256:
        raise RuntimeError("REVIEWED_CAPTURE_PLAN_SHA_MISMATCH")
    plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    if plan.get("owner") != OWNER or plan.get("source") != SOURCE:
        raise RuntimeError("CAPTURE_PLAN_OWNER_OR_SOURCE_MISMATCH")
    if plan.get("capture_root") != str(CAPTURE_ROOT) or plan.get("lease_root") != str(LEASE_ROOT):
        raise RuntimeError("CAPTURE_PLAN_ROOT_MISMATCH")
    if plan.get("lease_policy", {}).get("maximum_duration_seconds") != MAX_LEASE_SECONDS:
        raise RuntimeError("CAPTURE_PLAN_LEASE_LIMIT_MISMATCH")
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    if raw_sha(CONFIG) != plan.get("config_sha256"):
        raise RuntimeError("CAPTURE_CONFIG_CHANGED_AFTER_REVIEW")
    if config.get("capture_enabled") is not False or config.get("capture_lease_token"):
        raise RuntimeError("CAPTURE_CONFIG_NOT_DISABLED_OR_TOKEN_PRESENT")
    if Path(config.get("capture_root", "")).resolve() != CAPTURE_ROOT.resolve():
        raise RuntimeError("CAPTURE_ROOT_MISMATCH")
    if Path(config.get("capture_lease_root", "")).resolve() != LEASE_ROOT.resolve():
        raise RuntimeError("CAPTURE_LEASE_ROOT_MISMATCH")

    sys.path.insert(0, str(REPO))
    from v4.manager_workbench.contracts import Phase, RunContext
    from v4.manager_workbench.inputs.capture import capture_window, resolve_publication_window
    from v4.manager_workbench.inputs.capture_store import OWNER as CANONICAL_OWNER
    if CANONICAL_OWNER != OWNER:
        raise RuntimeError("CANONICAL_CAPTURE_OWNER_MISMATCH")
    context = RunContext(
        target_date=plan["call_plan"]["target_trade_date"],
        phase=Phase.MANUAL,
        cutoff=plan["call_plan"]["cutoff"],
        trigger="MANUAL",
        rules_version=str(config.get("rules_version", "")),
    )
    window = resolve_publication_window(context, publication_date=publication_date)
    expected_call = next(c for c in plan["call_plan"]["calls"] if c["publication_date"] == publication_date)
    if window != expected_call["window"]:
        raise RuntimeError("CAPTURE_WINDOW_DRIFT_FROM_REVIEWED_PLAN")
    if raw_sha(Path(capture_window.__code__.co_filename)) != plan.get("entrypoint_source_sha256"):
        raise RuntimeError("CAPTURE_ENTRYPOINT_SHA_CHANGED_AFTER_REVIEW")
    return plan, context, capture_window


def readback_product(store, product: dict) -> dict:
    saved_ref = product.get("saved_ref", {})
    artifact_ref = saved_ref.get("artifact_ref")
    expected_sha = saved_ref.get("sha256")
    if not isinstance(artifact_ref, str) or not isinstance(expected_sha, str):
        raise RuntimeError("CAPTURE_PRODUCT_SAVED_REF_MISSING")
    raw = store.io.read_bytes(artifact_ref)
    if hashlib.sha256(raw).hexdigest() != expected_sha:
        raise RuntimeError("CAPTURE_PRODUCT_READBACK_SHA_MISMATCH")
    loaded = json.loads(raw)
    persisted_product = {key: value for key, value in product.items() if key != "saved_ref"}
    if loaded != persisted_product or loaded.get("owner") != OWNER or loaded.get("source") != SOURCE:
        raise RuntimeError("CAPTURE_PRODUCT_READBACK_IDENTITY_MISMATCH")
    for article in loaded.get("rows", []):
        body_ref = article.get("body_artifact_ref")
        body_sha = article.get("source_sha256")
        if not isinstance(body_ref, str) or not isinstance(body_sha, str):
            raise RuntimeError("CAPTURE_ARTICLE_ARTIFACT_REF_MISSING")
        article_raw = store.io.read_bytes(body_ref)
        if hashlib.sha256(article_raw).hexdigest() != body_sha:
            raise RuntimeError("CAPTURE_ARTICLE_READBACK_SHA_MISMATCH")
        article_product = json.loads(article_raw)
        if article_product.get("art_code") != article.get("art_code"):
            raise RuntimeError("CAPTURE_ARTICLE_READBACK_IDENTITY_MISMATCH")
        if article.get("body_complete") is True:
            body = article.get("body_text")
            body_hash = hashlib.sha256(body.encode("utf-8")).hexdigest() if isinstance(body, str) else None
            if body_hash != article.get("body_text_sha256"):
                raise RuntimeError("CAPTURE_BODY_TEXT_SHA_MISMATCH")
    return loaded


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--publication-date", required=True, choices=ALLOWED_DATES)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    plan, context, capture_window = verify_frozen_plan(args.publication_date)
    if args.dry_run:
        print(json.dumps({
            "status": "DRY_RUN_PASS",
            "publication_date": args.publication_date,
            "window": next(c["window"] for c in plan["call_plan"]["calls"] if c["publication_date"] == args.publication_date),
            "capture_calls": 0,
            "lease_grants": 0,
            "external_network_calls": 0,
            "application_state_writes": 0,
        }, ensure_ascii=False))
        return 0

    import requests
    from v4.manager_workbench.inputs.capture_store import CaptureStore

    invocation_id = uuid4().hex
    before_path = OUT / f"lease-pregrant-{args.publication_date}-{invocation_id}.json"
    receipt_path = OUT / f"lease-revocation-{args.publication_date}-{invocation_id}.json"
    capture_path = OUT / f"capture-execution-{args.publication_date}-{invocation_id}.json"
    old_lease = redacted_lease_snapshot()
    write_json(before_path, {"schema_version": "v4.announcement.capture_lease_pregrant.v1", "invocation_id": invocation_id, **old_lease})

    store = CaptureStore(CAPTURE_ROOT, source=SOURCE, lease_root=LEASE_ROOT)
    transport = requests.Session()
    active_lease = None
    product = None
    operation_error = None
    revoke_error = None
    try:
        expires_at = store.now().astimezone(timezone.utc) + timedelta(seconds=MAX_LEASE_SECONDS)
        store.grant(expires_at=expires_at, owner=OWNER)
        store.assert_exclusive_owner(OWNER)
        active_lease = redacted_lease_snapshot()
        if not active_lease.get("enabled") or active_lease.get("owner") != OWNER or active_lease.get("source") != SOURCE:
            raise RuntimeError("GRANTED_LEASE_IDENTITY_MISMATCH")
        product = capture_window(context, {
            "publication_date": args.publication_date,
            "max_bodies": plan["call_plan"]["max_bodies_per_date"],
            "transport": transport,
        }, store)
    except Exception as exc:
        operation_error = {"type": type(exc).__name__, "message": str(exc)[:240]}
    finally:
        if store.token is not None:
            try:
                store.revoke()
            except Exception as exc:
                revoke_error = {"type": type(exc).__name__, "message": str(exc)[:240]}
        transport.close()

    after_lease = redacted_lease_snapshot()
    revoked = (
        after_lease.get("enabled") is False
        and after_lease.get("owner") == OWNER
        and after_lease.get("source") == SOURCE
        and bool(after_lease.get("revoked_at"))
        and revoke_error is None
    )
    write_json(receipt_path, {
        "schema_version": "v4.announcement.capture_lease_revocation_receipt.v1",
        "invocation_id": invocation_id,
        "owner": OWNER,
        "source": SOURCE,
        "maximum_lease_seconds": MAX_LEASE_SECONDS,
        "pregrant": old_lease,
        "active_lease_redacted": active_lease,
        "post_revoke": after_lease,
        "revoked": revoked,
        "grant_capture_error": operation_error,
        "revoke_error": revoke_error,
        "token_value_recorded": False,
    })

    capture_summary = {
        "schema_version": "v4.announcement.owner_capture_execution.v1",
        "invocation_id": invocation_id,
        "publication_date": args.publication_date,
        "target_date": context.target_date,
        "cutoff": context.cutoff,
        "owner": OWNER,
        "source": SOURCE,
        "entrypoint": "v4.manager_workbench.inputs.capture.capture_window",
        "entrypoint_source_sha256": plan["entrypoint_source_sha256"],
        "reviewed_plan_sha256": EXPECTED_PLAN_SHA256,
        "pregrant_receipt_path": str(before_path),
        "pregrant_receipt_sha256": raw_sha(before_path),
        "lease_revocation_receipt_path": str(receipt_path),
        "lease_revocation_receipt_sha256": raw_sha(receipt_path),
        "lease_revoked": revoked,
        "grant_capture_error": operation_error,
        "revoke_error": revoke_error,
        "no_model_calls": True,
        "no_api_calls": True,
        "no_configuration_writes": True,
        "capture_product": None,
    }
    exit_code = 0
    readback_error = None
    if product is not None and operation_error is None:
        try:
            loaded = readback_product(store, product)
        except Exception as exc:
            loaded = None
            readback_error = {"type": type(exc).__name__, "message": str(exc)[:240]}
            exit_code = 13
        capture_summary["readback_error"] = readback_error
    if product is not None and operation_error is None and readback_error is None:
        catalogues = loaded.get("catalogues", [])
        catalogue = catalogues[0] if len(catalogues) == 1 else {}
        catalogue_pass = (
            catalogue.get("publication_date") == args.publication_date[:4] + "-" + args.publication_date[4:6] + "-" + args.publication_date[6:]
            and catalogue.get("terminal_empty_seen") is True
            and catalogue.get("total_hits") == catalogue.get("observed_count") == len(loaded.get("rows", []))
            and not catalogue.get("gaps")
            and len({row.get("art_code") for row in loaded.get("rows", [])}) == len(loaded.get("rows", []))
        )
        complete_bodies = sum(1 for row in loaded.get("rows", []) if row.get("body_complete") is True)
        capture_summary["capture_product"] = {
            "artifact_ref": product["saved_ref"]["artifact_ref"],
            "sha256": product["saved_ref"]["sha256"],
            "run_id": product.get("run_id"),
            "coverage_status": product.get("coverage_status"),
            "scope_count": product.get("scope_count"),
            "observed_count": product.get("observed_count"),
            "catalogue": catalogue,
            "complete_body_count": complete_bodies,
            "body_gap_row_count": sum(1 for row in loaded.get("rows", []) if row.get("body_complete") is not True),
            "product_gaps": product.get("gaps", []),
            "available_after_cutoff": "CAPTURE_AVAILABLE_AFTER_RESEARCH_CUTOFF" in product.get("gaps", []),
            "readback_sha_verified": True,
            "article_artifact_and_body_hashes_verified": True,
            "canary_pass": catalogue_pass and complete_bodies > 0,
        }
        if not catalogue_pass or complete_bodies == 0:
            exit_code = 10
    else:
        if exit_code == 0:
            exit_code = 11

    if not revoked:
        exit_code = 12
    capture_summary["status"] = "CAPTURED_AND_REVOKED" if exit_code == 0 else "STOPPED_WITH_GAP"
    capture_product_summary = capture_summary.get("capture_product") or {}
    capture_summary["canary_pass"] = bool(capture_product_summary.get("canary_pass", False))
    capture_summary["exit_code"] = exit_code
    write_json(capture_path, capture_summary)
    print(json.dumps({
        "status": capture_summary["status"],
        "publication_date": args.publication_date,
        "run_id": (product or {}).get("run_id"),
        "coverage_status": (product or {}).get("coverage_status"),
        "scope_count": (product or {}).get("scope_count"),
        "observed_count": (product or {}).get("observed_count"),
        "complete_body_count": capture_summary.get("capture_product", {}).get("complete_body_count"),
        "body_gap_row_count": capture_summary.get("capture_product", {}).get("body_gap_row_count"),
        "canary_pass": capture_summary["canary_pass"],
        "lease_revoked": revoked,
        "pregrant_receipt": str(before_path),
        "lease_revocation_receipt": str(receipt_path),
        "capture_receipt": str(capture_path),
        "token_value_recorded": False,
        "exit_code": exit_code,
    }, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
