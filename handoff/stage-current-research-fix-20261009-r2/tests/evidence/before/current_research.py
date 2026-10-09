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

FLAGS = {"RESEARCH_ONLY": True, "production_allowed": False,
         "buy_gate_updated": False, "orders_sent": False}


def configure(args):
    source = json.loads(args.source_config.read_text())
    if not isinstance(source, dict):
        raise ValueError("original config must be a JSON object")
    candidate = args.candidate_root.expanduser().resolve(strict=True)
    if not (candidate / "V4_CANARY_IDENTITY.json").is_file():
        raise ValueError("use stage_patch.py prepare for this isolated application first")
    output = args.output_root.expanduser().absolute()
    if output.exists() or output.is_symlink():
        raise ValueError("output root must be new; repeat a run with its saved config")
    # The established stage/selection + stage/receipts relationship is also
    # how the existing API consumer discovers its original owner receipt.
    for key, name in (("raw_root", "raw"), ("selection_root", "selection"), ("receipt_root", "receipts")):
        source[key] = str(output / "stage" / name)
    source["hk_current_day_research_root"] = str(args.hk_research_root.expanduser().absolute())
    source["safety"] = {**source.get("safety", {}), **FLAGS}
    source.update(FLAGS)
    for key in ("a_0925_recovery_authorization", "backfill_run_id"):
        source.pop(key, None)
    output.mkdir(parents=True)
    path = output / "current_research_config.json"
    path.write_text(json.dumps(source, ensure_ascii=False, indent=2) + "\n")
    # No source-data files are copied or changed here.
    return {"status": "CONFIGURED", "config": str(path), "candidate_root": str(candidate),
            "selection_root": source["selection_root"], "receipt_root": source["receipt_root"], **FLAGS}


def run(args):
    candidate = args.candidate_root.expanduser().resolve(strict=True)
    marker = candidate / "V4_CANARY_IDENTITY.json"
    if not marker.is_file():
        raise ValueError("an isolated candidate application is required")
    output = args.config.expanduser().resolve(strict=True).parent
    payload = json.loads(args.config.read_text())
    for key, name in (("raw_root", "raw"), ("selection_root", "selection"), ("receipt_root", "receipts")):
        if Path(payload[key]).resolve() != output / "stage" / name:
            raise ValueError(f"{key} must remain inside this config's isolated output directory")
    if not payload.get("hk_current_day_research_root"):
        raise ValueError("this command requires explicit current-day research opt-in")
    if any(payload.get(flag) is not expected for flag, expected in FLAGS.items()):
        raise ValueError("research safety flags differ")
    sys.path.insert(0, str(candidate))
    from ops.run_stage_center_nodes import _load_config, _build_runner
    config = _load_config(args.config)
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
    try:
        result = configure(args) if args.action == "configure" else run(args)
    except (OSError, ValueError, ImportError, RuntimeError, TypeError) as error:
        result = {"status": "CANNOT_CONFIRM", "error": f"{type(error).__name__}: {error}", **FLAGS}
    text = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if getattr(args, "report", None):
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text)
    print(text, end="")
    if result.get("status") == "CANNOT_CONFIRM":
        return 2
    actual = result.get("result", result)
    return 0 if actual.get("status") in {"CONFIGURED", "READY", "READY_EMPTY", "PARTIAL_WITH_ROWS", "NOOP_ALREADY_VERIFIED"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
