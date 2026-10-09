#!/usr/bin/env python3
"""Configure and call the original Stage runner, with isolated output roots.

No selector, quote source, pool producer, retry scheduler, or publication
protocol is implemented here. All market data enters the original runner.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

import stage_patch

FLAGS = {"RESEARCH_ONLY": True, "production_allowed": False,
         "buy_gate_updated": False, "orders_sent": False}
OUTPUT_ROOTS = (("raw_root", "raw"), ("selection_root", "selection"), ("receipt_root", "receipts"))


def configured_roots(payload, *, include_outputs=True):
    """Only inspect declared filesystem inputs; preserve their original values."""
    for key, value in payload.items():
        if not include_outputs and key in dict(OUTPUT_ROOTS):
            continue
        if isinstance(value, str) and value:
            if key.endswith("_root"):
                yield Path(value).expanduser().resolve()
            elif key.endswith("_path"):
                yield Path(value).expanduser().resolve().parent


def require_isolated_output(output, candidate, marker, roots):
    for root in (candidate, Path(marker["source_root"]), *roots):
        stage_patch.require_separate(output, root)


def configure(args):
    source = json.loads(args.source_config.expanduser().resolve(strict=True).read_text(encoding="utf-8"))
    if not isinstance(source, dict):
        raise ValueError("original config must be a JSON object")
    candidate = args.candidate_root.expanduser().resolve(strict=True)
    marker = stage_patch.verify_candidate(candidate)
    output = args.output_root.expanduser().absolute()
    if output.exists() or output.is_symlink():
        raise ValueError("output root must be new; repeat a run with its saved config")
    output = output.resolve()
    research_root = args.hk_research_root.expanduser().resolve()
    require_isolated_output(output, candidate, marker, (*configured_roots(source), research_root))
    if not isinstance(source.get("safety", {}), dict):
        raise ValueError("original config safety must be a JSON object")
    # The established stage/selection + stage/receipts relationship is also
    # how the existing API consumer discovers its original owner receipt.
    for key, name in OUTPUT_ROOTS:
        source[key] = str(output / "stage" / name)
    source["hk_current_day_research_root"] = str(research_root)
    source["safety"] = {**source.get("safety", {}), **FLAGS}
    source.update(FLAGS)
    content = json.dumps(source, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    output.mkdir(parents=True)
    path = output / "current_research_config.json"
    with path.open("x", encoding="utf-8") as stream:
        stream.write(content)
    # No source-data files are copied or changed here.
    return {"status": "CONFIGURED", "config": str(path), "candidate_root": str(candidate),
            "selection_root": source["selection_root"], "receipt_root": source["receipt_root"], **FLAGS}


def run(args):
    candidate = args.candidate_root.expanduser().resolve(strict=True)
    marker = stage_patch.verify_candidate(candidate)
    config_path = args.config.expanduser().resolve(strict=True)
    output = config_path.parent
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("saved config must be a JSON object")
    require_isolated_output(output, candidate, marker, tuple(configured_roots(payload, include_outputs=False)))
    for key, name in OUTPUT_ROOTS:
        if not isinstance(payload.get(key), str) or Path(payload[key]).resolve() != output / "stage" / name:
            raise ValueError(f"{key} must remain inside this config's isolated output directory")
    if not payload.get("hk_current_day_research_root"):
        raise ValueError("this command requires explicit current-day research opt-in")
    if any(payload.get(flag) is not expected for flag, expected in FLAGS.items()):
        raise ValueError("research safety flags differ")
    safety = payload.get("safety")
    if not isinstance(safety, dict) or any(safety.get(flag) is not expected for flag, expected in FLAGS.items()):
        raise ValueError("nested research safety flags differ")
    sys.path.insert(0, str(candidate))
    from ops.run_stage_center_nodes import _load_config, _build_runner
    config = _load_config(config_path)
    runner = _build_runner(config)
    # Original tick owns the slot lock, collectors, raw/selection stores and
    # final receipt writer. Real invocation time is never replaced by cutoff.
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    result = runner.tick(args.trade_date, now, stage_id=args.stage, historical_backfill=False)
    return {"invocation_mode": "MANUAL_CURRENT_DAY_RESEARCH", "invoked_at": now.isoformat(),
            "result": result, "natural_verified": False, **FLAGS}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    setup = sub.add_parser("configure")
    setup.add_argument("--source-config", type=Path, required=True)
    setup.add_argument("--candidate-root", type=Path, required=True)
    setup.add_argument("--output-root", type=Path, required=True)
    setup.add_argument("--hk-research-root", type=Path, required=True)
    execute = sub.add_parser("run")
    execute.add_argument("--candidate-root", type=Path, required=True)
    execute.add_argument("--config", type=Path, required=True)
    execute.add_argument("--trade-date", default="20261009")
    execute.add_argument("--stage", default="STAGE_1545_1555")
    execute.add_argument("--report", type=Path)
    args = parser.parse_args()
    report_path = None
    report_forbidden = (args.candidate_root,)
    try:
        if getattr(args, "report", None):
            marker = stage_patch.verify_candidate(args.candidate_root)
            payload = json.loads(args.config.expanduser().resolve(strict=True).read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("saved config must be a JSON object")
            report_forbidden = (args.candidate_root, Path(marker["source_root"]), *configured_roots(payload))
            report_path = stage_patch.new_report_path(args.report, forbidden_roots=report_forbidden)
        result = configure(args) if args.action == "configure" else run(args)
    except (OSError, ValueError, ImportError, RuntimeError, TypeError, KeyError) as error:
        result = {"status": "CANNOT_CONFIRM", "error": f"{type(error).__name__}: {error}", **FLAGS}
    text = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if report_path:
        try:
            stage_patch.write_new_report(report_path, text, forbidden_roots=report_forbidden)
        except (OSError, ValueError) as error:
            print(json.dumps({"status": "CANNOT_CONFIRM", "error": str(error)}), file=sys.stderr)
            return 2
    print(text, end="")
    if result.get("status") == "CANNOT_CONFIRM":
        return 2
    actual = result.get("result", result)
    return 0 if actual.get("status") in {"CONFIGURED", "READY", "READY_EMPTY", "PARTIAL_WITH_ROWS", "NOOP_ALREADY_VERIFIED"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
