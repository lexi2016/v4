"""One fixed six-slot replacement entrypoint; no daemon, model, or second fetcher."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from domains.intraday_research import (
    IntradayAttemptError,
    SLOTS,
    SAFETY,
    capture_intraday,
)


def main(argv: list[str] | None = None, *, transport=None, clock=None) -> int:
    parser = argparse.ArgumentParser(description="Capture one V4 owned schema-3 intraday slot")
    parser.add_argument("--date", required=True)
    parser.add_argument("--slot", required=True, choices=[slot.replace(":", "") for slot in SLOTS])
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--config-sha256", required=True)
    parser.add_argument("--source-manifest-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        result = capture_intraday(args.date, args.slot, config_path=args.config, config_sha256=args.config_sha256,
            source_manifest_sha256=args.source_manifest_sha256, transport=transport, clock=clock)
    except IntradayAttemptError as error:
        print(json.dumps({
            "status": "CANNOT_CONFIRM",
            "error_code": error.error_code,
            "attempt_state": error.attempt_state,
            **SAFETY,
        }, sort_keys=True))
        return 2
    except Exception:
        # Paths, provider errors, response bodies and credentials never go to UI.
        print(json.dumps({
            "status": "CANNOT_CONFIRM",
            "error_code": "INTRADAY_CAPTURE_REFUSED",
            **SAFETY,
        }, sort_keys=True))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
