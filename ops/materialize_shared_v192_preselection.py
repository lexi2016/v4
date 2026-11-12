"""Resume-safe fixed wrapper for the shared v1.9.2 preselection artifact."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from infrastructure.formula_generation import FormulaGenerationError, read_formula_generation, read_selector_source_binding
from infrastructure.isolated_package_loader import load_isolated_package_module


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--signal-date", required=True)
    parser.add_argument("--target-date", required=True)
    parser.add_argument(
        "--generation-pointer",
        type=Path,
        default=None,
        help="Strict V4 generation pointer whose selector_source is the V192 input",
    )
    parser.add_argument(
        "--source-panel",
        type=Path,
        default=None,
        help="Optional exact source panel override, checked against generation metadata",
    )
    parser.add_argument("--historical-backfill", action="store_true")
    parser.add_argument("--expected-previous-json", type=Path, default=None,
                        help="Exact verified prior run identity for the existing store CAS")
    args = parser.parse_args(argv)
    package_root = Path(os.environ.get("V4_SHARED_PACKAGE_ROOT") or os.environ["V35_SHARED_PACKAGE_ROOT"])
    store_root = Path(os.environ["V3_SHARED_DATA_STORE_ROOT"])
    panel_value = os.environ.get("V3_SHARED_SELECTOR_READY_PANEL")
    panel = Path(panel_value) if panel_value else None
    generation_evidence: dict[str, object] | None = None
    source_evidence: dict[str, object] | None = None
    expected_previous = None
    identity_keys = {"run_id", "artifact_sha256", "manifest_sha256", "receipt_sha256",
                     "artifact_relative", "manifest_relative", "receipt_relative"}
    try:
        if args.expected_previous_json is not None:
            expected_previous = json.loads(args.expected_previous_json.read_bytes())
            if (not args.historical_backfill or not isinstance(expected_previous, dict)
                    or set(expected_previous) != identity_keys
                    or any(not isinstance(value, str) or not value for value in expected_previous.values())):
                raise ValueError("historical replacement requires complete exact previous identity")
        if args.historical_backfill and expected_previous is None:
            raise ValueError("historical replacement requires --expected-previous-json")
        if args.source_panel is not None and args.generation_pointer is None:
            panel = args.source_panel.expanduser()
            source_evidence = read_selector_source_binding(panel, expected_signal_date=args.signal_date)
        elif panel is not None and args.generation_pointer is None:
            from ops.research_panel_logical import is_logical
            if is_logical(panel):
                source_evidence = read_selector_source_binding(panel, expected_signal_date=args.signal_date)
            else:
                # Legacy physical fixtures still bind their actual bytes and
                # exact signal-day coverage before any prior run can be reused.
                from infrastructure.formula_generation import _parquet_dates, _sha256_file
                if max(_parquet_dates(panel)) != args.signal_date.replace("-", ""):
                    raise ValueError("selector source asof date mismatch")
                source_evidence = dict(path=str(panel.resolve()), sha256=_sha256_file(panel),
                                       signal_date=args.signal_date.replace("-", ""))
        elif args.generation_pointer is None:
            raise ValueError("A_V192_EXACT_INPUT_MISSING:selector panel unavailable")
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(json.dumps(dict(ok=False, status="FAILED", error=str(error),
              production_allowed=False, buy_gate_updated=False, orders_sent=False), sort_keys=True))
        return 1
    if args.generation_pointer is not None:
        try:
            generation = read_formula_generation(
                args.generation_pointer,
                # The formula generation is dated by the source signal day;
                # V192 owns the independent next-target-day check below.
                expected_target_date=args.signal_date,
                require_source=True,
            )
            panel = Path(generation["selector_source"])
            if args.source_panel is not None:
                requested = args.source_panel.expanduser().resolve()
                if requested != panel.resolve():
                    raise FormulaGenerationError("source panel does not match generation selector_source")
            generation_evidence = {
                "path": str(generation["path"]),
                "sha256": generation["sha256"],
                "bytes": generation["bytes"],
                "generation_id": generation["generation_id"],
                "target_date": generation["target_date"],
                "selector_source": str(panel),
                "selector_source_sha256": generation["selector_source_evidence"]["sha256"],
            }
        except (FormulaGenerationError, OSError, UnicodeError, ValueError) as error:
            outcome = {
                "ok": False,
                "status": "FAILED",
                "error": f"strict generation source unavailable: {error}",
            }
            outcome.update(
                {
                    "production_allowed": False,
                    "buy_gate_updated": False,
                    "orders_sent": False,
                }
            )
            print(json.dumps(outcome, ensure_ascii=False, sort_keys=True))
            return 1
    selector_module = load_isolated_package_module(
        package_root,
        package_directory="shared_data",
        module_leaf="v192_selector",
        namespace_prefix="v35_shared_v192_selector",
    )
    StoreError = getattr(selector_module, "StoreError")
    materialize_frozen_v192_selector = getattr(
        selector_module, "materialize_frozen_v192_selector"
    )
    read_verified_v192_pool = getattr(selector_module, "read_verified_v192_pool")

    def materialize():
        if panel is None or not panel.is_file():
            raise ValueError("A_V192_EXACT_INPUT_MISSING:selector panel unavailable")
        options = ({"historical_backfill": True, "expected_previous": expected_previous}
                   if args.historical_backfill else {})
        return materialize_frozen_v192_selector(
            store_root, panel_path=panel, signal_date=args.signal_date,
            target_date=args.target_date, **options)

    try:
        existing = read_verified_v192_pool(
            store_root,
            target_date=args.target_date,
            expected_signal_date=args.signal_date,
        )
        existing_provenance = existing.run.manifest.get("provenance")
        existing_panel_sha = (
            existing_provenance.get("panel_sha256")
            if isinstance(existing_provenance, dict)
            else None
        )
        expected_sha = (source_evidence["sha256"] if source_evidence is not None else
                        generation_evidence["selector_source_sha256"] if generation_evidence is not None else
                        None)
        if expected_previous is not None and any(
                existing.run.verification.get(key) != value for key, value in expected_previous.items()):
            if (existing.run.receipt.get("supersedes") != expected_previous
                    or expected_sha != existing_panel_sha):
                raise ValueError("expected_previous identity mismatch")
            outcome = {"ok": True, "already_exists": True,
                       "status": existing.run.receipt["status"], **existing.run.verification}
        elif expected_sha is not None and existing_panel_sha != expected_sha:
            if not args.historical_backfill:
                raise ValueError("existing V192 pool source does not match exact selector_source")
            outcome = {"ok": True, **materialize()}
        else:
            outcome = {"ok": True, "already_exists": True,
                       "status": existing.run.receipt["status"], **existing.run.verification}
    except StoreError as error:
        if args.historical_backfill:
            outcome = {"ok": False, "status": "FAILED", "error": str(error)}
        else:
            try:
                outcome = {"ok": True, **materialize()}
            except (OSError, RuntimeError, StoreError, ValueError) as failure:
                outcome = {"ok": False, "status": "FAILED", "error": str(failure)}
    except (OSError, RuntimeError, ValueError) as error:
        outcome = {"ok": False, "status": "FAILED", "error": str(error)}
    if generation_evidence is not None:
        outcome["formula_generation"] = generation_evidence
        outcome["source_panel"] = {
            "path": str(panel.resolve()),
            "sha256": generation_evidence["selector_source_sha256"],
            "role": "selector_source",
        }
    if source_evidence is not None:
        outcome["source_panel"] = {**source_evidence, "role": "selector_source"}
    outcome.update(
        {
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
    )
    print(json.dumps(outcome, ensure_ascii=False, sort_keys=True))
    return 0 if outcome.get("ok") and outcome.get("status") in {"READY", "READY_EMPTY"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
