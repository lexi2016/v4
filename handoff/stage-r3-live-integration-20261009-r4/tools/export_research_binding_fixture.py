#!/usr/bin/env python3
"""Export a fresh synthetic R4 workbench response using the original R3 stores."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True


def export_fixture(output_root):
    # Test support owns the only synthetic approval substitution. The delivered
    # production reader and preparation CLI expose no fixture input or bypass.
    test_root = Path(os.environ.get("R4_API_TEST_ROOT", Path(__file__).resolve().parents[1] / "tests"))
    sys.path.insert(0, str(test_root))
    import conftest as fixture
    from pytest import MonkeyPatch
    output = Path(output_root).expanduser().absolute()
    if output.exists() or any(path.is_symlink() for path in (output, *output.parents)):
        raise ValueError("fresh regular output root required")
    output.mkdir(parents=True)
    with MonkeyPatch.context() as patch:
        case = fixture.case.__wrapped__(patch, output / "fixture")
        reader, binding_path = fixture.prepare_case(case)
        if reader is None:
            raise ValueError("delivered R4 reader is unavailable")
        consumer = reader.get(fixture.DAY, fixture.STAGE)
        response = fixture.route_source(case, research_reader=reader)["stage_workbench"](
            date=fixture.DAY, stage=fixture.STAGE, limit=50)
        identities = {}
        for market in ("A_SHARE", "HK_CONNECT"):
            lane = response["selection_markets"][market]
            if lane["run_id"] != case.selected[market]["run_id"] or len(lane["rows"]) != 10:
                raise ValueError("original owner and workbench run differ")
            identities[market] = {"run_id": lane["run_id"], "selected_rows": len(lane["rows"]),
                                  "requested_rows": lane["requested_rows"], "source_rows": lane["source_rows"]}
        paths = {"consumer_response": output / "consumer_response.json",
                 "workbench_response": output / "workbench_response.json"}
        for name, value in (("consumer_response", consumer), ("workbench_response", response)):
            paths[name].write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
        receipt = {
            "status": "PASS", "fixture_only": True,
            "scope": "SYNTHETIC_TRIOS_ORIGINAL_R3_SELECTION_STORE_OWNER_WRITER_AND_EXACT_R4_API_ROUTE",
            "http_service_started": False, "real_market_acquisition": False,
            "markets": identities, "before_api_app_sha256": fixture.digest(fixture.BEFORE / "apps/api/v35_api/app.py"),
            "after_source_sha256": {str(path.relative_to(fixture.AFTER)): fixture.digest(path)
                                    for path in sorted(fixture.AFTER.rglob("*.py"))},
            "binding_sha256": fixture.digest(binding_path),
            "files": {name: {"path": str(path), "sha256": fixture.digest(path)} for name, path in paths.items()},
            "natural_verified": False, "execution_verified": False,
            "RESEARCH_ONLY": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
        }
        (output / "FIXTURE_RECEIPT.json").write_text(json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
        return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    result = export_fixture(args.output)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
