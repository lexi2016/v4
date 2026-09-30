#!/usr/bin/env python3
"""Read-only exact-source/archive projection witness for 20260930/1400.

Reads only the existing hourly source, payload, receipt, store manifest and the
bound candidate modules. Writes one structured witness beside this script.
It does not invoke a stage, collector, scheduler, or write to source storage.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

def _parse_args():
    parser = argparse.ArgumentParser(description="Read-only A1445 source/archive projection witness")
    parser.add_argument("--app-root", type=Path, required=True, help="candidate application source root")
    parser.add_argument("--data-root", type=Path, required=True, help="existing research data root")
    parser.add_argument("--output-dir", type=Path, default=Path.cwd(), help="directory for the derived witness")
    return parser.parse_args()

_ARGS = _parse_args()
OUT_DIR = _ARGS.output_dir.expanduser().resolve()
APP_ROOT = _ARGS.app_root.expanduser().resolve()
DATA_ROOT = _ARGS.data_root.expanduser().resolve()
EXPECTED_SOURCE_SHA = (
    "4076de79920c43cfa57336c23262a491cd77730f29b4e1a530bc5ed9836ef571"
)
EXPECTED_ARCHIVE_STORED_SHA = (
    "811b7803b540ec22c8e3f061804229e59fa51179f20a55a56ccc12d946af4af0"
)
TRADE_DATE = "20260930"
CUTOFF = datetime(2026, 9, 30, 15, 0, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

sys.path.insert(0, str(APP_ROOT))

from domains.research import build_research_archive
from infrastructure.data_store import _canonical_bytes, _sha256 as store_sha256
from infrastructure.research_store import HourlyResearchStore
from stage_center import research_context as rc


def raw_sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def json_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def value_len(value: Any) -> int | None:
    if isinstance(value, (str, list, dict)):
        return len(value)
    return None


def canonical_summary(value: Any) -> dict[str, Any]:
    encoded = _canonical_bytes(value)
    return {
        "json_type": json_type(value),
        "length": value_len(value),
        "canonical_bytes": len(encoded),
        "canonical_sha256": raw_sha(encoded),
    }


def pointer_join(parent: str, part: str | int) -> str:
    escaped = str(part).replace("~", "~0").replace("/", "~1")
    return f"{parent}/{escaped}" if parent else f"/{escaped}"


def is_row_payload(pointer: str) -> bool:
    parts = pointer.split("/")
    return any(part in {"articles", "stock_pool", "stock_research_timeline",
                        "stock_research_daily", "research_items", "raw_items"}
               for part in parts)


def side_description(value: Any, *, present: bool, pointer: str) -> dict[str, Any]:
    if not present:
        return {"present": False, "json_type": "MISSING", "length": None, "value": None}
    encoded = _canonical_bytes(value)
    desc: dict[str, Any] = {
        "present": True,
        "json_type": json_type(value),
        "length": value_len(value),
        "canonical_bytes": len(encoded),
        "canonical_sha256": raw_sha(encoded),
    }
    if isinstance(value, (dict, list)):
        if len(encoded) <= 512 and not is_row_payload(pointer):
            desc["value"] = value
        else:
            desc["value_exported"] = False
            desc["redaction_reason"] = (
                "row_payload_not_exported" if is_row_payload(pointer)
                else "container_over_512_canonical_bytes"
            )
    elif isinstance(value, str) and is_row_payload(pointer):
        desc["value_exported"] = False
        desc["redaction_reason"] = "row_payload_field_value_redacted_after_hashing"
    elif isinstance(value, str) and len(value) > 512:
        desc["value_exported"] = False
        desc["redaction_reason"] = "string_over_512_characters"
    else:
        desc["value"] = value
    return desc


def diff_walk(left: Any, right: Any, pointer: str, *,
              left_present: bool = True, right_present: bool = True,
              diffs: list[dict[str, Any]], equal: list[dict[str, Any]]) -> None:
    if not left_present or not right_present:
        if left_present == right_present and left == right:
            equal.append({"pointer": pointer, **canonical_summary(left)})
            return
        diffs.append({
            "pointer": pointer,
            "archive_stored": side_description(left, present=left_present, pointer=pointer),
            "rebuilt_projection": side_description(right, present=right_present, pointer=pointer),
        })
        return

    lt, rt = json_type(left), json_type(right)
    if lt != rt:
        diffs.append({
            "pointer": pointer,
            "archive_stored": side_description(left, present=True, pointer=pointer),
            "rebuilt_projection": side_description(right, present=True, pointer=pointer),
        })
        return

    if isinstance(left, dict):
        if left == right:
            equal.append({"pointer": pointer, **canonical_summary(left)})
            return
        for key in sorted(set(left) | set(right)):
            diff_walk(
                left.get(key), right.get(key), pointer_join(pointer, key),
                left_present=key in left, right_present=key in right,
                diffs=diffs, equal=equal,
            )
        return

    if isinstance(left, list):
        if left == right:
            equal.append({"pointer": pointer, **canonical_summary(left)})
            return
        for index in range(max(len(left), len(right))):
            diff_walk(
                left[index] if index < len(left) else None,
                right[index] if index < len(right) else None,
                pointer_join(pointer, index),
                left_present=index < len(left),
                right_present=index < len(right),
                diffs=diffs, equal=equal,
            )
        return

    if left == right:
        equal.append({"pointer": pointer, **canonical_summary(left)})
    else:
        diffs.append({
            "pointer": pointer,
            "archive_stored": side_description(left, present=True, pointer=pointer),
            "rebuilt_projection": side_description(right, present=True, pointer=pointer),
        })


def file_identity(path: Path, app_root: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    try:
        relative = path.relative_to(app_root).as_posix()
    except ValueError:
        relative = str(path)
    return {"path": relative, "bytes": len(raw), "sha256": raw_sha(raw)}


def source_field_summary(source: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for field in (
        "cannot_confirm", "report_entity_audit", "research_items",
        "stock_research_timeline", "stock_research_daily",
        "research_pool_bridge",
    ):
        if field in source:
            out[f"/{field}"] = canonical_summary(source[field])
    manifest = source.get("source_manifest")
    if isinstance(manifest, dict):
        keys = (
            "capture_origin", "collector_identity_sha256", "event_id",
            "generated_at", "hourly_slot", "module_path",
            "natural_execution_verified", "original_time_capture",
            "pit_cutoff", "producer", "producer_oracle_sha256",
            "published_at", "report_subject_policy_sha256",
            "research_hourly_domain_identity_sha256", "trade_date", "version",
        )
        out["/source_manifest"] = {
            key: manifest[key] for key in keys if key in manifest
        }
        for field in ("source_receipts", "source_types"):
            if field in manifest:
                out[f"/source_manifest/{field}"] = canonical_summary(manifest[field])
    return out


def main() -> None:
    data_root = DATA_ROOT
    store = HourlyResearchStore(data_root)

    selected_slot, verified_payload, paths = rc._verified_hourly_slot(
        data_root, trade_date=TRADE_DATE, cutoff=CUTOFF
    )
    if selected_slot != "1400":
        raise RuntimeError(f"unexpected exact slot selected: {selected_slot}")

    source_relative = f"research/hourly/source/{EXPECTED_SOURCE_SHA}.json"
    source_path = data_root / source_relative
    source_raw = source_path.read_bytes()
    source_raw_sha = raw_sha(source_raw)
    if source_raw_sha != EXPECTED_SOURCE_SHA:
        raise RuntimeError("source raw SHA mismatch")
    source = json.loads(source_raw.decode("utf-8-sig"))
    if not isinstance(source, dict):
        raise RuntimeError("source must be a JSON object")

    payload_relative = HourlyResearchStore._relative(TRADE_DATE, "1400", "LIVE")
    receipt_relative = HourlyResearchStore._receipt_relative(TRADE_DATE, "1400", "LIVE")
    payload_path = data_root / payload_relative
    receipt_path = data_root / receipt_relative
    store_manifest_path = data_root / "manifest.json"
    archive_raw = payload_path.read_bytes()
    archive_file_sha = raw_sha(archive_raw)
    archive = json.loads(archive_raw.decode("utf-8"))
    if not isinstance(archive, dict):
        raise RuntimeError("archive must be a JSON object")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    store_manifest = json.loads(store_manifest_path.read_text(encoding="utf-8"))
    stored_payload_sha = store_sha256(archive)
    if stored_payload_sha != EXPECTED_ARCHIVE_STORED_SHA:
        raise RuntimeError("stored payload canonical SHA mismatch")
    if receipt.get("payload_sha256") != stored_payload_sha:
        raise RuntimeError("receipt payload SHA mismatch")
    if store_manifest.get(payload_relative) != stored_payload_sha:
        raise RuntimeError("hourly store manifest payload SHA mismatch")
    if receipt.get("source_input_sha256") != EXPECTED_SOURCE_SHA:
        raise RuntimeError("archive receipt source SHA mismatch")
    if verified_payload != archive:
        raise RuntimeError("verified store payload differs from raw archive JSON")

    source_canonical = _canonical_bytes(source)
    archive_canonical = _canonical_bytes(archive)
    stored_base = dict(archive)
    stored_stage_evidence = stored_base.pop("stage_evidence_v1", None)
    stored_base_canonical = _canonical_bytes(stored_base)

    rebuilt = build_research_archive(source, source_input_sha256=EXPECTED_SOURCE_SHA)
    helper_expected_source_sha = getattr(
        rc, "_V35_20260929_1400_ROLE_WARNING_SOURCE_SHA256", None
    )
    compatible, compatibility_evidence = (
        rc._apply_exact_v35_20260929_1400_role_warning_projection(
            rebuilt,
            source,
            archive,
            trade_date=TRADE_DATE,
            slot="1400",
            source_input_sha256=EXPECTED_SOURCE_SHA,
        )
    )
    rebuilt_stage_evidence = compatible.pop("stage_evidence_v1", None)
    rebuilt_base_canonical = _canonical_bytes(compatible)
    rebuilt_canonical = _canonical_bytes(rebuilt)

    # Run the original validation helper once, read-only, to record its exact
    # error after its own build + compatibility-helper sequence.
    try:
        rc._bound_source_rows(
            data_root,
            payload=archive,
            paths=paths,
            trade_date=TRADE_DATE,
            slot="1400",
            cutoff=CUTOFF,
        )
        original_validation_error = None
    except Exception as exc:  # record exact type/message from the bound path
        original_validation_error = {
            "type": type(exc).__name__,
            "message": str(exc),
        }

    diffs: list[dict[str, Any]] = []
    equal: list[dict[str, Any]] = []
    diff_walk(stored_base, compatible, "", diffs=diffs, equal=equal)

    late_payload_relative = HourlyResearchStore._relative(TRADE_DATE, "1500", "LIVE")
    late_payload_path = data_root / late_payload_relative
    late_raw = late_payload_path.read_bytes()
    late_payload = json.loads(late_raw.decode("utf-8"))
    late_generated = late_payload.get("source_generated_at")
    result = {
        "schema": "v4.a1445_20260930_1400_projection_witness.v1",
        "captured_on": "20261001",
        "task_boundary": {
            "read_only_originals": True,
            "no_stage_or_collector_execution": True,
            "no_source_or_store_write": True,
            "no_202_row_export": True,
        },
        "originals": {
            "data_root_identity": "explicit --data-root argument",
            "source": {
                "root_relative_path": source_relative,
                "bytes": len(source_raw),
                "raw_file_sha256": source_raw_sha,
                "decoder_used_by_bound_consumer": "utf-8-sig",
                "has_utf8_bom": source_raw.startswith(b"\xef\xbb\xbf"),
                "ends_with_lf": source_raw.endswith(b"\n"),
                "canonical_serializer_bytes": len(source_canonical),
                "canonical_sha256": raw_sha(source_canonical),
                "source_serializer_identity": "CANNOT_CONFIRM_FROM_SOURCE_MANIFEST",
            },
            "archive": {
                "root_relative_path": payload_relative,
                "receipt_relative_path": receipt_relative,
                "store_manifest_relative_path": "manifest.json",
                "bytes": len(archive_raw),
                "raw_file_sha256": archive_file_sha,
                "stored_payload_sha256_contract": {
                    "value": stored_payload_sha,
                    "definition": "SHA-256 of canonical JSON bytes for parsed payload via infrastructure.data_store._sha256/_canonical_bytes; ensure_ascii=False, sort_keys=True, separators=(',', ':'), UTF-8, no trailing LF",
                    "receipt_matches": receipt.get("payload_sha256") == stored_payload_sha,
                    "store_manifest_matches": store_manifest.get(payload_relative) == stored_payload_sha,
                    "equals_raw_file_sha256_in_this_instance": archive_file_sha == stored_payload_sha,
                },
                "full_canonical_bytes": len(archive_canonical),
                "full_canonical_sha256": raw_sha(archive_canonical),
                "base_without_stage_evidence_v1_bytes": len(stored_base_canonical),
                "base_without_stage_evidence_v1_sha256": raw_sha(stored_base_canonical),
                "stage_evidence_v1_present_before_removal": "stage_evidence_v1" in archive,
                "source_input_sha256_in_payload": archive.get("source_input_sha256"),
                "source_generated_at": archive.get("source_generated_at"),
                "schema_version": archive.get("schema_version"),
            },
            "source_receipt_fields": {
                key: receipt.get(key) for key in (
                    "schema_version", "archive_date", "slot", "mode",
                    "payload_path", "payload_sha256", "source_input_sha256",
                    "article_count", "stock_pool_count",
                )
            },
        },
        "time_binding": {
            "stage_cutoff": CUTOFF.isoformat(),
            "selected_exact_slot": selected_slot,
            "selected_archive_source_generated_at": archive.get("source_generated_at"),
            "pit_rejected_slots": paths.get("pit_rejected_slots", ""),
            "1500_archive": {
                "root_relative_path": late_payload_relative,
                "bytes": len(late_raw),
                "raw_file_sha256": raw_sha(late_raw),
                "source_generated_at": late_generated,
                "after_cutoff": str(late_generated) > CUTOFF.isoformat(),
            },
            "decision": "15:00:02 is after 15:00:00; exact reader skips 1500 and selects the verified 1400 slot",
        },
        "source_producer_identity": {
            "producer_claimed_by_source_manifest": {
                key: source.get("source_manifest", {}).get(key)
                for key in (
                    "producer", "module_path", "producer_oracle_sha256",
                    "collector_identity_sha256",
                    "research_hourly_domain_identity_sha256",
                    "report_subject_policy_sha256", "version",
                    "capture_origin", "original_time_capture",
                    "generated_at", "published_at", "hourly_slot", "trade_date",
                )
            },
            "producer_bytes_at_original_capture": "CANNOT_CONFIRM_FROM_THIS_TRACE; producer_oracle_sha256 is the source manifest declaration",
            "correlated_source_fields": source_field_summary(source),
        },
        "reconstruction": {
            "actual_consumer_call_order": [
                "stage_center.research_context._verified_hourly_slot",
                "stage_center.research_context._bound_source_rows",
                "domains.research.build_research_archive",
                "stage_center.research_context._apply_exact_v35_20260929_1400_role_warning_projection",
                "stage_center.research_context._payload_base_sha",
            ],
            "projection_rebuild_call": "build_research_archive(source, source_input_sha256=exact source raw SHA)",
            "compatibility_helper": {
                "function": "_apply_exact_v35_20260929_1400_role_warning_projection",
                "helper_expected_source_sha256": helper_expected_source_sha,
                "actual_source_sha256": EXPECTED_SOURCE_SHA,
                "source_sha_matches_helper_guard": helper_expected_source_sha == EXPECTED_SOURCE_SHA,
                "returned_evidence": list(compatibility_evidence),
                "effect": "no-op; helper's initial source SHA guard returns a copy unchanged",
            },
            "original_bound_validation_result": original_validation_error,
            "stored_archive_stage_evidence_v1_removed_only_for_comparison": True,
            "stored_stage_evidence_v1_present": "stage_evidence_v1" in archive,
            "rebuilt_stage_evidence_v1_present": rebuilt_stage_evidence is not None,
            "rebuilt_full_canonical_bytes": len(rebuilt_canonical),
            "rebuilt_full_canonical_sha256": raw_sha(rebuilt_canonical),
            "rebuilt_base_without_stage_evidence_v1_bytes": len(rebuilt_base_canonical),
            "rebuilt_base_without_stage_evidence_v1_sha256": raw_sha(rebuilt_base_canonical),
            "only_stage_evidence_v1_removed_before_diff": True,
            "json_pointer_diff_count": len(diffs),
            "json_pointer_differences_archive_vs_rebuilt": diffs,
            "equal_subtree_summaries_type_len_canonical_sha_only": equal,
        },
        "serializer_contract": {
            "module": "infrastructure.data_store._canonical_bytes",
            "module_sha256": file_identity(APP_ROOT / "infrastructure/data_store.py", APP_ROOT)["sha256"],
            "json_dumps": {
                "ensure_ascii": False,
                "sort_keys": True,
                "separators": [",", ":"],
                "encoding": "UTF-8",
                "trailing_newline": False,
            },
            "source_raw_contract": "raw source file SHA over exact bytes; consumer decodes UTF-8-SIG; producer serializer/newline contract not declared here",
        },
        "reconstruction_modules_on_disk": [
            file_identity(APP_ROOT / relative, APP_ROOT)
            for relative in (
                "stage_center/research_context.py",
                "domains/research.py",
                "domains/research_hourly.py",
                "infrastructure/research_store.py",
                "infrastructure/data_store.py",
                "contracts/research.py",
            )
        ],
        "runtime_identity_boundary": {
            "candidate_app_root": str(APP_ROOT),
            "data_root_argument": str(data_root),
            "current_on_disk_candidate_modules_hashed": True,
            "modules_loaded_by_real_20260930_stage_process": "CANNOT_CONFIRM",
        },
        "data_export_note": {
            "original_source_and_archive_bytes_copied": False,
            "full_market_rows_exported": False,
            "row-payload difference values": "If a JSON-pointer mismatch falls inside article/stock arrays, its values are hash-described/redacted after original byte hashes; exported witness is not byte-identical to source or archive.",
        },
    }

    script_raw = Path(__file__).read_bytes()
    result["source_script"] = {
        "path": Path(__file__).name,
        "sha256": raw_sha(script_raw),
        "bytes": len(script_raw),
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    output = OUT_DIR / "a1445_20260930_1400_projection_witness.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "WITNESS_WRITTEN",
        "output": str(output),
        "diff_count": len(diffs),
        "diff_pointers": [d["pointer"] for d in diffs],
        "original_bound_error": original_validation_error,
        "source_raw_sha256": source_raw_sha,
        "archive_stored_payload_sha256": stored_payload_sha,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()

