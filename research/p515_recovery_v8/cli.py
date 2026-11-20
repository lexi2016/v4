"""P5.15 V8 three-mode CLI and read-only official six-package preparation."""
from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
import sys

from .authority import AuthorityClient, MODES
from .validation import Rejected, read_json, require


def run_pipeline(anchor: Path, mode: str, *, auth: Path | None = None,
                 prelaunch: Path | None = None, unit: str = "F1_RETRY") -> dict:
    """One RPC validation and execution chain shared by CLI and Python callers."""
    require(mode in MODES, "UNKNOWN_MODE")
    client = AuthorityClient(anchor)
    checked = client.request("check")
    if mode == "CHECK_ONLY":
        return checked
    require(auth is not None and prelaunch is not None, "SIGNED_AUTHORIZATION_AND_PRELAUNCH_REQUIRED")
    grant = read_json(auth)
    require(prelaunch.is_file(), "PRELAUNCH_FILE_REQUIRED")
    reserved = client.request("reserve", unit=unit, envelope=grant,
                              prelaunch_b64=base64.b64encode(prelaunch.read_bytes()).decode("ascii"), mode=mode)
    committed = client.request("execute", transaction_id=reserved["transaction_id"], lease_token=reserved["lease_token"])
    return {**committed, "trace": checked["trace"] + reserved["trace"] +
            ["SERVER_OWNED_EXECUTION", "OUTPUT_FULLY_VERIFIED", "MANIFEST_AND_COMPLETION_COMMITTED"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description="P515 V8 authority-governed zero-FIT recovery")
    parser.add_argument("--mode", choices=MODES, required=True)
    parser.add_argument("--anchor", type=Path)
    parser.add_argument("--official-config", type=Path)
    parser.add_argument("--auth", type=Path)
    parser.add_argument("--prelaunch", type=Path)
    parser.add_argument("--unit", choices=("F1_RETRY", "FINAL_DEV"), default="F1_RETRY")
    args = parser.parse_args(argv)
    try:
        if args.official_config is not None:
            require(args.mode == "CHECK_ONLY", "OFFICIAL_PREPARATION_IS_READ_ONLY")
            from .official_inputs import prepare_official
            prepared = prepare_official(read_json(args.official_config))
            output = {"state": "CHECK_ONLY", "scope": prepared["scope"],
                      "execution_identity_sha256": prepared["execution_identity_sha256"],
                      "identity": {key: value for key, value in prepared["identity"].items()
                                   if key not in ("fold_manifest", "purge_and_pending")},
                      "baseline": {key: value for key, value in prepared["baseline"].items()
                                   if key != "original_identity_manifest"},
                      "real_counts": dict.fromkeys(("model_fit", "preprocessing_fit", "model_api",
                                                    "new_probability", "predict", "deserialization", "formal_start"), 0)}
        else:
            require(args.anchor is not None, "AUTHORITY_ANCHOR_REQUIRED")
            output = run_pipeline(args.anchor, args.mode, auth=args.auth, prelaunch=args.prelaunch, unit=args.unit)
        print(json.dumps(output, sort_keys=True, ensure_ascii=False, allow_nan=False))
        return 0
    except Exception as exc:
        print(json.dumps({"state": "REJECTED", "error": str(exc), "error_type": type(exc).__name__},
                         ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
