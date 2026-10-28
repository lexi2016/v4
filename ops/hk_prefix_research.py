"""Run the bounded, research-only historical HK prefix reconstruction."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from domains.hk_prefix_research import (  # noqa: E402
    HKPrefixResearchError,
    rewrite_hk_prefix_research_result,
    run_hk_prefix_research,
)
from upstreams.v3_shared_data.shared_data.store import StoreError  # noqa: E402


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run one frozen HK prefix canary and then the 24-group/72-control "
            "historical research export."
        )
    )
    parser.add_argument("--source-path", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--source-sha256", required=True)
    parser.add_argument("--calendar-sdt", type=Path, required=True)
    parser.add_argument("--calendar-parity-rows", type=Path, required=True)
    parser.add_argument("--calendar-receipt", type=Path)
    parser.add_argument("--calendar-code", type=Path)
    parser.add_argument("--binding", type=Path, required=True)
    parser.add_argument("--matched-verdict", type=Path, required=True)
    parser.add_argument("--extractor", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--reuse-prefix-root",
        type=Path,
        help="Reissue metrics from an existing frozen result's 96 CSV windows without scanning raw parquet.",
    )
    parser.add_argument("--qa-receipt-sha256")
    parser.add_argument(
        "--cpu-threads",
        type=int,
        default=4,
        help="Fixed bounded execution setting; only 4 is accepted.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.reuse_prefix_root is not None:
            receipt = rewrite_hk_prefix_research_result(
                source_root=args.reuse_prefix_root,
                output_dir=args.output,
                extractor_path=args.extractor,
                qa_receipt_sha256=args.qa_receipt_sha256,
            )
        else:
            receipt = run_hk_prefix_research(
                source_path=args.source_path,
                source_manifest_path=args.source_manifest,
                source_sha256=args.source_sha256,
                calendar_path=args.calendar_sdt,
                parity_path=args.calendar_parity_rows,
                calendar_receipt_path=args.calendar_receipt,
                calendar_code_path=args.calendar_code,
                binding_path=args.binding,
                matched_verdict_path=args.matched_verdict,
                extractor_path=args.extractor,
                output_dir=args.output,
                cpu_threads=args.cpu_threads,
            )
    except (HKPrefixResearchError, StoreError, OSError, ValueError) as error:
        print(
            json.dumps(
                {
                    "status": "CANNOT_CONFIRM",
                    "error_type": type(error).__name__,
                    "error": str(error),
                    "output": str(args.output),
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
