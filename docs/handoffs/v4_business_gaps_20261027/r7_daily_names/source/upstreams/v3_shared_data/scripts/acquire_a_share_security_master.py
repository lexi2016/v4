"""Publish one exact-date A-share selector security registry from a parquet file."""
from __future__ import annotations

import argparse
import json
import sys
import hashlib
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from shared_data.a_share_security_master import (publish_a_share_security_master, acquire_current_display_names, publish_current_display_names, load_current_display_names)
from shared_data.store import StoreError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selector-parquet")
    parser.add_argument("--current-display-names", action="store_true")
    parser.add_argument("--observation-date")
    parser.add_argument("--cache-only", action="store_true")
    parser.add_argument("--extend-display-names", action="store_true")
    parser.add_argument("--expected-prior-run-id")
    parser.add_argument("--expected-index-sha256")
    parser.add_argument("--observation-output", type=Path)
    parser.add_argument("--request-json", type=Path)
    parser.add_argument("--evidence-root", type=Path)
    parser.add_argument("--official-observations", type=Path)
    parser.add_argument("--store-root", required=True)
    parser.add_argument("--signal-date", required=True)
    args = parser.parse_args(argv)
    try:
        if args.current_display_names:
            if not args.observation_date or not args.request_json or not args.evidence_root:
                parser.error("display mode requires observation-date/request-json/evidence-root")
            prior_pins=None
            seeds=json.loads(args.official_observations.read_text()) if args.official_observations else []
            if args.cache_only or args.extend_display_names:
                if not (args.extend_display_names and args.expected_prior_run_id and args.expected_index_sha256 and args.observation_output):
                    parser.error("extension requires exact prior run/index SHA and a new observation-output")
                registry=Path(args.store_root)/"assets/a_share_display_names";index_raw=(registry/"latest.json").read_bytes()
                if hashlib.sha256(index_raw).hexdigest()!=args.expected_index_sha256:raise StoreError("display-name prior index CAS mismatch")
                prior,manifest=load_current_display_names(args.store_root,args.observation_date)
                if manifest['run_id']!=args.expected_prior_run_id:raise StoreError("display-name prior run mismatch")
                artifact=json.loads((registry/'runs'/args.observation_date/manifest['run_id']/'artifact.json').read_text())
                prior_pins={row['path']:row['sha256'] for row in artifact['pages']}
                original={row['ts_code']:row for row in prior.values()}
                for row in seeds:
                    if row['ts_code'] in original and original[row['ts_code']]!=row:raise StoreError("official seed conflicts with original row")
                    original.setdefault(row['ts_code'],row)
                seeds=list(original.values())
            elif args.expected_prior_run_id or args.expected_index_sha256 or args.observation_output:
                parser.error("prior/output flags require explicit cache-only extension")
            observation = acquire_current_display_names(args.evidence_root,observation_date=args.observation_date,
                requested_codes=json.loads(args.request_json.read_text()),official_rows=seeds,
                cache_only=args.cache_only,cached_page_pins=prior_pins,output_path=args.observation_output)
            # The original V4 lock implementation is reused by this owner.
            v4_root=Path(__file__).resolve().parents[3]
            if str(v4_root) not in sys.path:sys.path.insert(0,str(v4_root))
            result = publish_current_display_names(args.store_root,observation,extend=args.extend_display_names,
                expected_prior_run_id=args.expected_prior_run_id,expected_index_sha256=args.expected_index_sha256)
        else:
            if not args.selector_parquet:
                parser.error("selector mode requires --selector-parquet")
            result = publish_a_share_security_master(
                Path(args.store_root),
                signal_date=args.signal_date,
                selector_path=Path(args.selector_parquet),
            )
    except (OSError, StoreError, ValueError) as error:
        result = {"ok": False, "status": "FAILED", "error": str(error)}
    else:
        result = {"ok": True, **result}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
