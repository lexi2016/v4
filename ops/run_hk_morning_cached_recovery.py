"""Offline 2026-10-15 HK morning recovery canary through the StageCenter runner."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

TRADE_DATE = "20261015"
STAGES = (
    "STAGE_0925",
    "STAGE_0930_0935",
    "STAGE_0935_0940",
    "STAGE_0940_0945",
)
MINUTE_STAGES = frozenset(STAGES[1:])
DEFAULT_D1_ROOT = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data"
)
DEFAULT_SECOND_FILTER_ROOT = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v4.local/state/data/opening_second_filter"
)
DEFAULT_CAPTURE = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v4.local/state/stage/raw/"
    ".futu_minute_captures/20261015/STAGE_0945_1030/"
    "45fdc5d16d1dec2e7f087dfdb802f3c5b92e67d4e380aa6c49ddea15881ab455.json"
)
DEFAULT_STAGE_RELEASE = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/"
    "node-minute-stage-20261014-r1/app"
)
DEFAULT_PYTHON = PROJECT_ROOT / ".venv/bin/python"
RECOVERY_CAPTURE_ENV = "V4_HK_MORNING_CACHED_CAPTURE"
SHANGHAI = ZoneInfo("Asia/Shanghai")
RUNTIME_STATE_ROOT = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v4.local/state"
)


def _tree_sha256(path: Path) -> str:
    if not path.exists():
        return "ABSENT"
    if path.is_file():
        return hashlib.sha256(path.read_bytes()).hexdigest()
    digest = hashlib.sha256()
    for item in sorted(path.rglob("*")):
        if item.is_symlink():
            digest.update(b"SYMLINK\0" + item.relative_to(path).as_posix().encode())
        elif item.is_file():
            relative = item.relative_to(path).as_posix().encode("utf-8")
            digest.update(relative + b"\0" + hashlib.sha256(item.read_bytes()).digest())
    return digest.hexdigest()


def _protected_live_state_digests() -> dict[str, str]:
    stage = RUNTIME_STATE_ROOT / "stage"
    protected = (
        stage / "raw/runs/20261015",
        stage / "raw/bundle_runs/20261015",
        stage / "selection/selection_runs/20261015",
        stage / "receipts/20261015",
        stage / "raw/latest.json",
        stage / "raw/bundle_latest.json",
        stage / "selection/selection_latest.json",
    )
    return {str(path): _tree_sha256(path) for path in protected}


def _mode_token(source_evidence: tuple[str, ...]) -> str:
    prefix = "stage_center_observation_mode="
    values = [item[len(prefix):] for item in source_evidence if item.startswith(prefix)]
    if len(values) != 1:
        raise RuntimeError("cached after-fact source did not produce one manifest token")
    return values[0]


def _result_selection(result: dict[str, Any], stage_id: str) -> dict[str, Any]:
    if result.get("trade_date") != TRADE_DATE or result.get("stage_id") != stage_id:
        raise RuntimeError(f"runner returned the wrong slot for {stage_id}")
    markets = result.get("markets")
    if not isinstance(markets, dict) or set(markets) != {"HK_CONNECT"}:
        raise RuntimeError(f"runner did not isolate the HK lane for {stage_id}")
    item = markets["HK_CONNECT"]
    if not isinstance(item, dict) or item.get("write_performed") is False:
        raise RuntimeError(f"runner did not publish the HK lane for {stage_id}")
    return item


def run_offline_canary(
    *,
    output_root: Path,
    d1_root: Path = DEFAULT_D1_ROOT,
    second_filter_root: Path = DEFAULT_SECOND_FILTER_ROOT,
    capture_path: Path = DEFAULT_CAPTURE,
    stage_release: Path = DEFAULT_STAGE_RELEASE,
    python_path: Path = DEFAULT_PYTHON,
) -> dict[str, Any]:
    output_root = output_root.expanduser().resolve(strict=False)
    runtime_state_root = RUNTIME_STATE_ROOT.expanduser().resolve(strict=False)
    if output_root.exists():
        raise ValueError("output_root must be a new directory")
    if output_root == runtime_state_root or runtime_state_root in output_root.parents:
        raise ValueError("offline canary output cannot be inside the active runtime state")
    if not d1_root.is_dir() or not second_filter_root.is_dir() or not capture_path.is_file():
        raise FileNotFoundError("one or more pinned HK recovery inputs are unavailable")
    shared_root = stage_release / "upstreams/v3_shared_data"
    if not shared_root.is_dir() or not python_path.is_file():
        raise FileNotFoundError("read-only stage release bridge or project Python is unavailable")

    output_root.mkdir(parents=True, exist_ok=False)
    started_at = datetime.now(SHANGHAI)
    before_live = _protected_live_state_digests()
    old_capture_env = os.environ.get(RECOVERY_CAPTURE_ENV)
    os.environ[RECOVERY_CAPTURE_ENV] = str(capture_path.expanduser().resolve())
    try:
        from stage_center.acquisition import build_plan
        from stage_center._live_collectors_parts.hk_minute import (
            _hk_morning_cached_d1_provenance,
        )
        from stage_center.live_collectors import collect_hk_minute
        from stage_center.runner import (
            RunnerConfig,
            StageCenterRunner,
            _build_hk_stage_binding,
            _candidate_from_hk_binding,
        )
        from stage_center.selection import SelectionStore

        config = RunnerConfig(
            candidate_acquisition_root=output_root / "candidate_input",
            raw_root=output_root / "stage/raw",
            selection_root=output_root / "stage/selection",
            receipt_root=output_root / "stage/receipts",
            hk_d1_root=d1_root,
            hk_second_filter_root=second_filter_root,
            hk_auction_root=second_filter_root,
            shared_data_root=shared_root,
            python_path=python_path,
        )
        runner = StageCenterRunner(config)
        binding = _build_hk_stage_binding(config.hk_d1_root, TRADE_DATE)
        d1_provenance = _hk_morning_cached_d1_provenance(binding, binding.codes)
        if (
            binding.sha256 != "66225363e4dd1b9da4f316d75a8dcc5f249bc0968128c646e9632a1a8b1b1c67"
            or d1_provenance is None
            or len(binding.codes) != 100
        ):
            raise RuntimeError("canonical D1 Top100 identity differs from the frozen input")
        candidate = _candidate_from_hk_binding(
            root=config.candidate_acquisition_root,
            trade_date=TRADE_DATE,
            binding=binding,
        )
        stage_summaries: list[dict[str, Any]] = []
        evaluated_at_by_stage: dict[str, str] = {}

        for stage_id in STAGES:
            evaluated_at = datetime.now(SHANGHAI)
            evaluated_at_by_stage[stage_id] = evaluated_at.isoformat()
            token = None
            prepared = None
            if stage_id in MINUTE_STAGES:
                plan = build_plan(
                    config.candidate_acquisition_root,
                    TRADE_DATE,
                    stage_id,
                    candidate=candidate,
                    universe_bindings={"HK_CONNECT": binding},
                    historical_backfill=True,
                )
                prepared = collect_hk_minute(
                    plan,
                    codes=plan.codes_for("HK_CONNECT"),
                    python_path=python_path,
                    shared_root=shared_root,
                    snapshot_root=None,
                    replay_provider=None,
                )
                if prepared.status != "PARTIAL_WITH_ROWS" or len(prepared.rows) != 100:
                    raise RuntimeError(
                        f"{stage_id} cached source rejected: {prepared.cannot_confirm}"
                    )
                token = _mode_token(tuple(prepared.source_evidence))

            result = runner.tick(
                TRADE_DATE,
                evaluated_at,
                stage_id=stage_id,
                historical_backfill=True,
                historical_markets=("HK_CONNECT",),
                historical_observation_contract=token,
                _skip_precapture=True,
            )
            market_result = _result_selection(result, stage_id)
            selection_run_id = str(market_result.get("run_id") or "")
            if not selection_run_id:
                raise RuntimeError(f"{stage_id} returned no immutable selection run id")
            selection_latest = next(
                (
                    path
                    for path in (output_root / "stage/selection").glob(
                        "backfill/*/selection_latest.json"
                    )
                    if selection_run_id in path.read_text(encoding="utf-8")
                ),
                None,
            )
            if selection_latest is None:
                raise RuntimeError(f"{stage_id} selection latest pointer is missing")
            envelope = SelectionStore(selection_latest.parent).read_verified(
                TRADE_DATE, stage_id, "HK_CONNECT"
            )
            selected = list(envelope.get("rows") or ())
            if market_result.get("selected_rows") != len(selected):
                raise RuntimeError(f"{stage_id} selection row count readback mismatch")
            if any(row.get("action_level") != "NO_BUY" for row in selected):
                raise RuntimeError(f"{stage_id} selection exceeded the NO_BUY boundary")
            if stage_id in MINUTE_STAGES:
                if (
                    envelope.get("formal_eligible") is not False
                    or envelope.get("selection_mode") != "RESEARCH_ONLY"
                    or envelope.get("observation_status") != "OBSERVATION_UNVERIFIED"
                    or not any(
                        "HK_HISTORICAL_ORDERBOOK_UNAVAILABLE" in str(item)
                        for item in envelope.get("cannot_confirm", ())
                    )
                ):
                    raise RuntimeError(f"{stage_id} lost an after-fact or orderbook uncertainty marker")
                if len(selected) > 10:
                    raise RuntimeError(f"{stage_id} exceeded the existing four-lane Top10 cap")
            stage_summaries.append(
                {
                    "stage_id": stage_id,
                    "runner_evaluated_at": evaluated_at.isoformat(),
                    "runner_status": result.get("status"),
                    "due_status": result.get("due_status"),
                    "selection_status": market_result.get("selection_status"),
                    "source_status": market_result.get("source_status"),
                    "selected_rows": len(selected),
                    "selection_run_id": selection_run_id,
                    "raw_artifact_sha256": market_result.get("raw_artifact_sha256"),
                    "formal_eligible": envelope.get("formal_eligible"),
                    "selection_mode": envelope.get("selection_mode"),
                    "observation_status": envelope.get("observation_status"),
                    "cannot_confirm": list(envelope.get("cannot_confirm") or ()),
                    "source_evidence": list(envelope.get("source_evidence") or ()),
                    "prepared_source_rows": len(prepared.rows) if prepared is not None else 20,
                }
            )

        after_live = _protected_live_state_digests()
        if before_live != after_live:
            raise RuntimeError("live stage raw/selection/receipt bytes changed during offline canary")
        summary = {
            "schema_version": "hk_morning_cached_recovery_offline_canary.v1",
            "status": "PASS",
            "trade_date": TRADE_DATE,
            "clock_timezone": "Asia/Shanghai",
            "run_started_at": started_at.isoformat(),
            "runner_evaluated_at_by_stage": evaluated_at_by_stage,
            "receipt_captured_at": datetime.now(SHANGHAI).isoformat(),
            "source_capture_sha256": "45fdc5d16d1dec2e7f087dfdb802f3c5b92e67d4e380aa6c49ddea15881ab455",
            "d1_artifact_sha256": binding.sha256,
            "d1_source_run_id": d1_provenance[2],
            "stage_results": stage_summaries,
            "protected_live_state_sha256_before": before_live,
            "protected_live_state_sha256_after": after_live,
            "write_root": str(output_root),
            "research_only": True,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
        (output_root / "offline_canary_receipt.json").write_text(
            json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        return summary
    finally:
        if old_capture_env is None:
            os.environ.pop(RECOVERY_CAPTURE_ENV, None)
        else:
            os.environ[RECOVERY_CAPTURE_ENV] = old_capture_env


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--d1-root", type=Path, default=DEFAULT_D1_ROOT)
    parser.add_argument("--second-filter-root", type=Path, default=DEFAULT_SECOND_FILTER_ROOT)
    parser.add_argument("--capture", type=Path, default=DEFAULT_CAPTURE)
    parser.add_argument("--stage-release", type=Path, default=DEFAULT_STAGE_RELEASE)
    parser.add_argument("--python", type=Path, default=DEFAULT_PYTHON)
    args = parser.parse_args(argv)
    try:
        summary = run_offline_canary(
            output_root=args.output_root,
            d1_root=args.d1_root,
            second_filter_root=args.second_filter_root,
            capture_path=args.capture,
            stage_release=args.stage_release,
            python_path=args.python,
        )
    except Exception as error:
        print(json.dumps({"status": "FAIL", "error_type": type(error).__name__, "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
