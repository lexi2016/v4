#!/usr/bin/env python3
"""Read-only diagnosis using the explicitly loaded V4 hourly source contracts.

Run with the intended Stage application's root in PYTHONPATH. This command
prints JSON only; it never publishes, repairs, writes a witness, or updates
an input/latest pointer. Runtime module paths and SHAs are part of its result.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any, Mapping
from zoneinfo import ZoneInfo

sys.dont_write_bytecode = True

from domains import research as research_domain
from infrastructure.owned_io import SafeRoot
from infrastructure.research_store import HourlyResearchStore
from stage_center import research_context as context


FLAGS = {"RESEARCH_ONLY": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False}
MAX_DIFFERENCES = 200


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _summary(value: Any) -> Any:
    if value is None or type(value) in (bool, int, float):
        return value
    if isinstance(value, str) and len(value) <= 160:
        return value
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {"type": type(value).__name__, "length": len(value), "value_sha256": _sha(raw)}


def _differences(archive: Any, projected: Any, path: str = "") -> list[dict[str, Any]]:
    """Compare JSON types too: 97 and 97.0 have different canonical bytes."""
    output = []
    if isinstance(archive, dict) and isinstance(projected, dict):
        for key in sorted(set(archive) | set(projected)):
            pointer = path + "/" + key.replace("~", "~0").replace("/", "~1")
            if key not in archive or key not in projected:
                output.append({"path": pointer, "kind": "MISSING_KEY",
                    "archive_present": key in archive, "reprojected_present": key in projected,
                    "archive": _summary(archive.get(key)), "reprojected": _summary(projected.get(key))})
            else:
                output.extend(_differences(archive[key], projected[key], pointer))
    elif isinstance(archive, list) and isinstance(projected, list):
        for index in range(max(len(archive), len(projected))):
            pointer = path + "/" + str(index)
            if index >= len(archive) or index >= len(projected):
                output.append({"path": pointer, "kind": "MISSING_INDEX",
                    "archive_present": index < len(archive), "reprojected_present": index < len(projected),
                    "archive": _summary(archive[index]) if index < len(archive) else None,
                    "reprojected": _summary(projected[index]) if index < len(projected) else None})
            else:
                output.extend(_differences(archive[index], projected[index], pointer))
    elif type(archive) is not type(projected) or archive != projected:
        output.append({"path": path or "/", "kind": "VALUE_OR_TYPE",
            "archive_type": type(archive).__name__, "reprojected_type": type(projected).__name__,
            "archive": _summary(archive), "reprojected": _summary(projected)})
    return output


def diagnose(root: Path | str, trade_date: str, slot: str, *, stage_cutoff: str | None = None) -> dict[str, Any]:
    supplied_root = Path(root).expanduser()
    if not supplied_root.is_absolute() or not supplied_root.is_dir():
        raise ValueError("explicit existing absolute research root is required")
    root = supplied_root.resolve()
    store = HourlyResearchStore(root)
    io = SafeRoot(root)
    # Use the store's exact, date/slot-validated addressing. No latest lookup.
    archive_relative = store._relative(trade_date, slot, "LIVE")
    receipt_relative = store._receipt_relative(trade_date, slot, "LIVE")
    cutoff = (datetime.strptime(f"{trade_date} {stage_cutoff}", "%Y%m%d %H:%M:%S").replace(tzinfo=ZoneInfo("Asia/Shanghai"))
              if stage_cutoff is not None else context._source_slot_cutoff(trade_date, slot))
    report = {
        "schema_version": "v4.source_witness_diagnostic.v1", "status": "CANNOT_CONFIRM",
        "research_root": str(root), "trade_date": trade_date, "slot": slot,
        "stage_cutoff": cutoff.isoformat(),
        "cutoff_basis": "EXPLICIT_STAGE_CUTOFF" if stage_cutoff is not None else "SOURCE_SLOT_END_NOT_STAGE_ACCEPTANCE",
        "archive_path": str(root / archive_relative), "receipt_path": str(root / receipt_relative),
        "manifest_path": str(root / "manifest.json"), "witness_path": None,
        "archive_raw_sha256": None, "receipt_raw_sha256": None, "manifest_raw_sha256": None,
        "receipt_source_input_sha256": None, "archive_source_input_sha256": None,
        "witness_raw_sha256": None, "archive_base_sha256": None,
        "pure_builder_base_sha256": None, "reprojected_base_sha256": None,
        "store_validation_error": None, "original_validator_error": None, "projection_error": None,
        "differences": [], "difference_count": 0, "differences_truncated": False,
        "projection_compatibility_evidence": [], "inputs_changed_during_read": [], "read_errors": [],
        "runtime_modules": {name: {"path": str(Path(module.__file__).resolve()),
                                     "sha256": _sha(Path(module.__file__).read_bytes())}
                            for name, module in (("domains.research", research_domain), ("stage_center.research_context", context))},
        "write_performed": False, **FLAGS,
    }
    seen = {}

    def read(relative, label):
        try:
            raw = io.read_bytes(relative)
            seen[relative] = _sha(raw)
            return raw, json.loads(raw.decode("utf-8-sig"))
        except (OSError, UnicodeError, ValueError) as error:
            report["read_errors"].append(f"{label}:{type(error).__name__}:{error}")
            return None, None

    archive_raw, payload = read(archive_relative, "archive")
    receipt_raw, receipt = read(receipt_relative, "receipt")
    manifest_raw, _manifest = read("manifest.json", "manifest")
    for name, raw in (("archive_raw_sha256", archive_raw), ("receipt_raw_sha256", receipt_raw), ("manifest_raw_sha256", manifest_raw)):
        report[name] = _sha(raw) if raw is not None else None
    try:
        if store.read_exact(trade_date, slot, mode="LIVE") is None:
            report["store_validation_error"] = "HOURLY_ARCHIVE_MISSING"
    except (OSError, TypeError, ValueError, AttributeError, KeyError) as error:
        report["store_validation_error"] = str(error)

    if isinstance(payload, Mapping) and isinstance(receipt, Mapping):
        source_sha = receipt.get("source_input_sha256")
        report["receipt_source_input_sha256"] = source_sha
        report["archive_source_input_sha256"] = payload.get("source_input_sha256")
        report["archive_base_sha256"] = context._payload_base_sha(payload)
        if isinstance(source_sha, str) and re.fullmatch(r"[0-9a-f]{64}", source_sha):
            source_relative = f"research/hourly/source/{source_sha}.json"
            report["witness_path"] = str(root / source_relative)
            witness_raw, source = read(source_relative, "witness")
            report["witness_raw_sha256"] = _sha(witness_raw) if witness_raw is not None else None
            # Preserve the original reader's exact exception or missing-input
            # result independently of the field-diff diagnostic below.
            try:
                rows, evidence = context._bound_source_rows(root, payload=payload,
                    paths={"source_input_sha256": source_sha}, trade_date=trade_date, slot=slot, cutoff=cutoff)
                if rows is None:
                    report["original_validator_error"] = ";".join(evidence)
            except (OSError, TypeError, ValueError, AttributeError, KeyError) as error:
                report["original_validator_error"] = str(error)
            if isinstance(source, Mapping):
                try:
                    projected = research_domain.build_research_archive(source, source_input_sha256=source_sha)
                    report["pure_builder_base_sha256"] = context._payload_base_sha(projected)
                    for compatibility in (
                        context._apply_exact_v35_20260929_1400_role_warning_projection,
                        context._apply_exact_v4_20260930_1400_role_warning_projection,
                    ):
                        projected, evidence = compatibility(projected, source, payload,
                            trade_date=trade_date, slot=slot, source_input_sha256=source_sha)
                        report["projection_compatibility_evidence"].extend(evidence)
                    report["reprojected_base_sha256"] = context._payload_base_sha(projected)
                    archive_base, projected_base = dict(payload), dict(projected)
                    archive_base.pop("stage_evidence_v1", None)
                    projected_base.pop("stage_evidence_v1", None)
                    differences = _differences(archive_base, projected_base)
                    report["difference_count"] = len(differences)
                    report["differences"] = differences[:MAX_DIFFERENCES]
                    report["differences_truncated"] = len(differences) > MAX_DIFFERENCES
                except (OSError, TypeError, ValueError, AttributeError, KeyError) as error:
                    report["projection_error"] = str(error)
        else:
            report["read_errors"].append("RECEIPT_SOURCE_SHA_INVALID")
    for relative, expected in seen.items():
        try:
            unchanged = _sha(io.read_bytes(relative)) == expected
        except (OSError, ValueError):
            unchanged = False
        if not unchanged:
            report["inputs_changed_during_read"].append(relative)
    if (not report["store_validation_error"] and not report["original_validator_error"]
            and not report["projection_error"] and not report["read_errors"]
            and not report["inputs_changed_during_read"]
            and report["archive_base_sha256"] is not None
            and report["archive_base_sha256"] == report["reprojected_base_sha256"]):
        report["status"] = "MATCH"
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--research-root", required=True, type=Path)
    parser.add_argument("--trade-date", required=True)
    parser.add_argument("--slot", required=True)
    parser.add_argument("--stage-cutoff", help="Exact local stage cutoff HH:MM:SS; omitted means source-slot diagnosis only")
    args = parser.parse_args(argv)
    try:
        report = diagnose(args.research_root, args.trade_date, args.slot, stage_cutoff=args.stage_cutoff)
    except (OSError, TypeError, ValueError, AttributeError, KeyError) as error:
        report = {"schema_version": "v4.source_witness_diagnostic.v1", "status": "CANNOT_CONFIRM",
                  "input_error": f"{type(error).__name__}:{error}", "write_performed": False, **FLAGS}
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if report["status"] == "MATCH" else 3


if __name__ == "__main__":
    raise SystemExit(main())
