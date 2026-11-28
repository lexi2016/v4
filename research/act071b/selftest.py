"""Targeted ACT-071B synthetic checks for selection and the first-test handoff."""

from __future__ import annotations

from collections import Counter
from datetime import date, timedelta
from itertools import combinations
from pathlib import Path
from random import Random
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from research.act070a.case_contract import FROZEN_GUARDS, json_bytes, sha256, strict_json
from research.act071a.case_contract import CASE_FILES, FIRST_TEST_DIR, OUTPUT_SCHEMA, RECEIPT_SCHEMA
from research.act071a.validate_b_output import validate_from_paths
from research.act071b.generate_cases import EXPECTED_GENERATION, RECEIPT_NAME, _verify_windows, _write_cases
from research.act071b.selection import Proxy, earliest_disjoint, first_feasible, freeze_pool, observed_proxies, read_sessions


def _check_exact_search():
    # The early Q0 blocks the first of just two Q1 opportunities. A greedy
    # selection that takes the earliest eligible D would fail this stock.
    day = date(2020, 1, 1)
    fixed = [(34, 0), (35, 1), (70, 1), (105, 0), (140, 0), (175, 2), (210, 2), (245, 3), (280, 3)]
    items = [Proxy(i, day + timedelta(days=i), q) for i, q in fixed]
    assert earliest_disjoint(items) == tuple(items[1:])
    rng = Random(7102)
    for _ in range(36):
        indices = sorted(rng.sample(range(34, 540), 12))
        quadrants = [0, 1, 2, 3] * 3
        rng.shuffle(quadrants)
        items = [Proxy(i, day + timedelta(days=i), q) for i, q in zip(indices, quadrants, strict=True)]
        oracle = next((group for group in combinations(items, 8)
                       if Counter(item.quadrant for item in group) == {0: 2, 1: 2, 2: 2, 3: 2}
                       and all(right.index - left.index >= 35 for left, right in zip(group, group[1:]))), ())
        assert earliest_disjoint(items) == oracle


def _session_rows(count: int) -> list[dict]:
    return [
        {"date": date(2020, 1, 1) + timedelta(days=i), "open": 10, "high": 13,
         "low": 8, "close": 12 if i % 2 else 9, "volume": 110 if i % 3 == 1 else 100}
        for i in range(count)
    ]


def _check_session_barrier():
    data = _session_rows(90)
    data[40]["volume"] = None
    proxies = {item.index for item in observed_proxies(read_sessions(data))}
    assert proxies == set(range(34, 40)) | set(range(75, 90))


def _check_pool_and_cases():
    pool = freeze_pool(["000001.SZ", "600000.SH", "600001.SH", "831039.BJ"], {"831039.BJ"})
    visited = []

    def load(code):
        visited.append(code)
        assert len(visited) < 3
        return _session_rows(12 if code == pool[0] else 349)

    selected, skips = first_feasible(pool, load)
    assert visited == list(pool[:2]) and selected.stock_code == pool[1]
    assert [row["stock_code"] for row in skips] == [pool[0]]
    assert skips[0]["reason"] == "INSUFFICIENT_OBSERVED_QUADRANT_DATES"
    identity = {"generation": EXPECTED_GENERATION, "panel_sha256": "a" * 64, "manifest_sha256": "b" * 64}
    exclusions = {"sha256": "c" * 64}
    with TemporaryDirectory(prefix=".act071b-selftest-") as temp:
        stage = Path(temp)
        cases = _write_cases(stage, selected, identity, exclusions)
        proof = _verify_windows(selected, cases)
        assert len(cases) == 8 and len(proof["pairwise_nonoverlap"]) == 28 and proof["b2_false_count"] == 4
        for case_id, case in cases.items():
            folder = stage / FIRST_TEST_DIR / case_id
            archive = stage / case["isolated_zip"]
            assert sha256(archive.read_bytes()) == case["isolated_zip_sha256"]
            with ZipFile(archive) as zipped:
                assert zipped.namelist() == list(CASE_FILES)
                assert all(zipped.read(name) == (folder / name).read_bytes() for name in CASE_FILES)
            sample = strict_json((folder / "input.json").read_bytes())
            signed = sample["rows"]
            assert len(signed) == 72 and signed[-1]["fields"]["p4_segment_binding"] == "UNBOUND"
            assert all(value == "UNKNOWN" for key, value in signed[-1]["fields"].items()
                       if key.startswith("event_chain_state"))
            assert any("ohlcv" in row["fields"] for row in signed)
        receipt = stage / RECEIPT_NAME
        receipt.write_bytes(json_bytes({"schema_version": RECEIPT_SCHEMA, "guards": FROZEN_GUARDS, "cases": cases}))
        for case_id in ("T01", "T08"):
            response = stage / "check.json"
            response.write_bytes(json_bytes({"schema_version": OUTPUT_SCHEMA, "case_id": case_id,
                                             "input_sha256": cases[case_id]["input_sha256"],
                                             "claims": [], "abstain_codes": ["INSUFFICIENT_D_ONLY_EVIDENCE"]}))
            verdict = validate_from_paths(stage / FIRST_TEST_DIR / case_id, receipt, response)
            assert verdict["accepted"], verdict
            assert verdict["immutable_b2"] == cases[case_id]["immutable_b2"]


def main():
    for check in (_check_exact_search, _check_session_barrier, _check_pool_and_cases):
        check()
    print(json_bytes({"status": "PASS", "checks": 3, "synthetic_exact_search_trials": 37,
                      "synthetic_isolated_case_zip_membership_checks": 8, "synthetic_frozen_validator_roundtrips": 2,
                      "market_source_opens": 0, "historical_forward_source_opens": 0, "models_called": 0}).decode())


if __name__ == "__main__":
    main()
