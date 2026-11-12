from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .core import (
    DEFAULT_DATA_ROOT,
    DEFAULT_SOURCE_ROOT,
    EvidenceValidationError,
    inspect_bundle,
    reconcile,
    run_video,
)
from .review import run_review


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="review-core")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_video_parser = subparsers.add_parser("run-video")
    run_video_parser.add_argument("--trade-date", required=True)
    run_video_parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    run_video_parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    run_video_parser.add_argument("--source-index", type=Path)
    run_video_parser.add_argument("--source-package-root", type=Path)
    run_video_parser.add_argument("--mode", choices=("import-existing", "acquire"), default="import-existing")
    run_video_parser.add_argument("--allow-network", action="store_true")
    run_video_parser.add_argument("--funasr-path", type=Path)
    run_video_parser.add_argument("--ffmpeg-path", type=Path)
    run_video_parser.add_argument("--ytdlp-path", type=Path)
    run_video_parser.add_argument("--python-path", type=Path)
    run_video_parser.add_argument("--target-mid", default="3546557003598528")
    run_video_parser.add_argument("--target-uploader", default="比巴卜作手")
    run_video_parser.add_argument("--independent-review-input", type=Path)

    run_review_parser = subparsers.add_parser("run-review")
    run_review_parser.add_argument("--trade-date", required=True)
    run_review_parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    run_review_parser.add_argument("--output-root", type=Path)
    run_review_parser.add_argument("--v3-artifact-root", type=Path)
    run_review_parser.add_argument("--v3-payload-path", type=Path)
    run_review_parser.add_argument("--replay-root", type=Path)
    run_review_parser.add_argument("--replay-review-path", type=Path)
    run_review_parser.add_argument("--video-data-root", type=Path, default=DEFAULT_DATA_ROOT)
    run_review_parser.add_argument("--public-source-root", type=Path)
    run_review_parser.add_argument("--selector-path", type=Path)
    run_review_parser.add_argument("--selector-root", type=Path)
    run_review_parser.add_argument("--tdx-root", type=Path)
    run_review_parser.add_argument("--formal-pool-path", type=Path)
    run_review_parser.add_argument("--review-pool-path", type=Path)
    run_review_parser.add_argument("--stage-root", type=Path)

    reconcile_parser = subparsers.add_parser("reconcile")
    reconcile_parser.add_argument("--lookback-trading-days", type=int, default=5)
    reconcile_parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)

    inspect_parser = subparsers.add_parser("inspect")
    inspect_parser.add_argument("--trade-date", required=True)
    inspect_parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)

    schedule_parser = subparsers.add_parser("schedule-once")
    schedule_parser.add_argument("--trade-date", required=True)
    schedule_parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    schedule_parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    schedule_parser.add_argument("--mode", choices=("import-existing", "acquire"), default="import-existing")
    schedule_parser.add_argument("--allow-network", action="store_true")
    schedule_parser.add_argument("--lookback-trading-days", type=int, default=5)
    return parser


def _print(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "run-review":
            result = run_review(
                args.trade_date,
                v3_artifact_root=args.v3_artifact_root,
                v3_payload_path=args.v3_payload_path,
                replay_root=args.replay_root,
                replay_review_path=args.replay_review_path,
                video_data_root=args.video_data_root,
                output_root=args.output_root or args.data_root,
                public_source_root=args.public_source_root,
                selector_path=args.selector_path,
                selector_root=args.selector_root,
                tdx_root=args.tdx_root,
                formal_pool_path=args.formal_pool_path,
                review_pool_path=args.review_pool_path,
                stage_root=args.stage_root,
            )
            _print(result)
            return 0
        if args.command == "run-video":
            independent_review_input = None
            if args.independent_review_input:
                independent_review_input = json.loads(
                    args.independent_review_input.read_text(encoding="utf-8-sig")
                )
            result = run_video(
                args.trade_date,
                data_root=args.data_root,
                source_root=args.source_root,
                source_index_path=args.source_index,
                source_package_root=args.source_package_root,
                mode=args.mode,
                allow_network=args.allow_network,
                funasr_path=args.funasr_path,
                ffmpeg_path=args.ffmpeg_path,
                ytdlp_path=args.ytdlp_path,
                python_path=args.python_path,
                target_mid=args.target_mid,
                target_uploader=args.target_uploader,
                independent_review_input=independent_review_input,
            )
            payload = dict(result)
            payload.update(result.get("manifest") or {})
            _print(payload)
            return 0
        if args.command == "inspect":
            manifest = inspect_bundle(args.trade_date, args.data_root)
            payload = dict(manifest)
            payload["inspection_status"] = "INSPECT_OK"
            payload["manifest_path"] = str(
                args.data_root
                / "review"
                / manifest["trade_date"]
                / "runs"
                / manifest["run_id"]
                / "manifest.json"
            )
            _print(payload)
            return 0
        if args.command == "reconcile":
            _print(
                reconcile(
                    data_root=args.data_root,
                    lookback_trading_days=args.lookback_trading_days,
                )
            )
            return 0
        if args.command == "schedule-once":
            from .scheduler import run_once

            _print(
                run_once(
                    args.trade_date,
                    data_root=args.data_root,
                    source_root=args.source_root,
                    mode=args.mode,
                    allow_network=args.allow_network,
                    lookback_trading_days=args.lookback_trading_days,
                )
            )
            return 0
    except (EvidenceValidationError, OSError, ValueError) as exc:
        _print({"status": "BLOCKED", "error": str(exc)})
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
