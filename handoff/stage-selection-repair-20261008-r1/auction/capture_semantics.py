"""Print synthetic before/after observations using imported production paths."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent / "tests"))
from test_a_auction_prev_close import (
    DATE, STAGE, RAW_SHA, auction_row, through_adapter, publish_and_read,
)
from test_api_projection_partial import partial_api_projector
from stage_center.selection import select_a_0925_auction
from stage_center._selection_parts import market_quality


def summarize(rows):
    fields = ("code", "prev_close_price", "current_change_pct", "qmt_gap_pct",
              "current_change_pct_missing_reason", "score", "rank")
    return [{key: row.get(key) for key in fields} for row in rows]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--owner", required=True)
    parser.add_argument("--phase", required=True)
    options = parser.parse_args()
    fixture = [auction_row(code="A.000101", price=95),
               auction_row(code="A.000102", price=105),
               auction_row(code="A.000103", price=100)]
    envelope = through_adapter(fixture)
    with tempfile.TemporaryDirectory(prefix="issue28-auction-synthetic-") as temporary:
        verified, response, store = publish_and_read(Path(temporary), envelope)
        api = partial_api_projector()(response, 10)
        artifact = next(store.root.rglob("artifact.csv"))
        with artifact.open(newline="", encoding="utf-8-sig") as stream:
            csv_header = next(csv.reader(stream))
        result = {
            "scope": "SYNTHETIC_SOURCE_HARNESS; API_PROJECTION_AST_PARTIAL; NO_REAL_DATA_OR_STAGE_RUN",
            "owner_variant": options.owner, "phase": options.phase,
            "algorithm_sha256": envelope["algorithm_sha256"],
            "market_quality_source_sha256": hashlib.sha256(Path(market_quality.__file__).read_bytes()).hexdigest(),
            "input_description": "previous close 100, auction prices 95/105/100, amount 10000000 each, in input order A.000101/A.000102/A.000103",
            "adapter_selection": summarize(envelope["rows"]),
            "verified_persisted_selection": summarize(verified["rows"]),
            "partial_api_projection": summarize(api["unified_rows"]),
            "csv_header": csv_header,
            "synthetic_csv_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
            "run_id": verified["run_id"],
        }
    direct = [dict(row, amount=row["turnover"]) for row in fixture]
    direct_envelope = select_a_0925_auction(direct, DATE, RAW_SHA)
    result["direct_valid_selector_control"] = summarize(direct_envelope["rows"])
    result["direct_valid_envelope_sha256"] = hashlib.sha256(json.dumps(direct_envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    result["missing_baseline"] = summarize(through_adapter([auction_row(previous=None)])["rows"])
    result["invalid_negative_baseline_direct_control"] = summarize(select_a_0925_auction([dict(auction_row(previous=-100), amount=10_000_000)], DATE, RAW_SHA)["rows"])
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
