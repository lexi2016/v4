"""Resume-safe fixed wrapper for the shared v1.9.2 preselection artifact."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from infrastructure.formula_generation import FormulaGenerationError, read_formula_generation
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
    args = parser.parse_args(argv)
    package_root = Path(os.environ["V35_SHARED_PACKAGE_ROOT"])
    store_root = Path(os.environ["V3_SHARED_DATA_STORE_ROOT"])
    panel_value = os.environ.get("V3_SHARED_SELECTOR_READY_PANEL")
    panel = Path(panel_value) if panel_value else None
    generation_evidence: dict[str, object] | None = None
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
        if (
            generation_evidence is not None
            and existing_panel_sha != generation_evidence["selector_source_sha256"]
        ):
            # A verified old pool is still a valid historical artifact, but it
            # cannot be relabelled as the current generation's source.  Do not
            # publish a second same-date producer or silently reuse it.
            outcome = {
                "ok": False,
                "status": "FAILED",
                "error": "existing V192 pool source does not match generation selector_source",
            }
        else:
            outcome = {
                "ok": True,
                "already_exists": True,
                "status": existing.run.receipt["status"],
                **existing.run.verification,
            }
    except StoreError:
        if panel is None or not panel.is_file():
            print(json.dumps({"ok": False, "status": "CANNOT_CONFIRM",
                "failure_class": "UPSTREAM_NOT_READY", "reason": "A_V192_EXACT_INPUT_MISSING:selector panel unavailable",
                "production_allowed": False, "buy_gate_updated": False, "orders_sent": False}, sort_keys=True))
            return 1
        try:
            outcome = materialize_frozen_v192_selector(
                store_root,
                panel_path=panel,
                signal_date=args.signal_date,
                target_date=args.target_date,
            )
            outcome = {"ok": True, **outcome}
        except (OSError, RuntimeError, StoreError, ValueError) as error:
            outcome = {"ok": False, "status": "FAILED", "error": str(error)}
    if generation_evidence is not None:
        outcome["formula_generation"] = generation_evidence
        outcome["source_panel"] = {
            "path": str(panel.resolve()),
            "sha256": generation_evidence["selector_source_sha256"],
            "role": "selector_source",
        }
    outcome.update(
        {
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
    )
    print(json.dumps(outcome, ensure_ascii=False, sort_keys=True))
    return 0 if outcome.get("ok") and outcome.get("status") == "READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
