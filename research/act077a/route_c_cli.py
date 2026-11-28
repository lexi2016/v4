"""Mount ACT-077A case IDs in-process and run the unmodified V1.1 CLI."""

from __future__ import annotations

import re

from research.act071a.case_contract import CASE_PATTERNS

ROUTE = "KB_BENCHMARK"
BLIND_ROUTE = "BLIND_SHADOW"
ROUTE_CASES = {ROUTE: re.compile(r"K0[1-5]"), BLIND_ROUTE: re.compile(r"B(?:0[1-9]|1[0-6])")}


def register_routes() -> None:
    for scope, pattern in ROUTE_CASES.items():
        if scope in CASE_PATTERNS and CASE_PATTERNS[scope] != pattern:
            raise RuntimeError(f"Conflicting case registration for {scope}")
    CASE_PATTERNS.update(ROUTE_CASES)


def main() -> int:
    from research.act071a.validate_b_output import main as frozen_main

    register_routes()
    return frozen_main()


if __name__ == "__main__":
    raise SystemExit(main())
