"""Read existing SOP evidence; write only this task's isolated evidence root."""
import argparse
import copy
from datetime import datetime, timedelta
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from ops import research_panel_factor_cache as fc


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--sync", type=Path, required=True)
    args = parser.parse_args()
    baseline_path = args.evidence_root / "BASELINE_REPRO.json"
    baseline = json.loads(baseline_path.read_text())
    sync_ref = dict(path=str(args.sync.resolve()), sha256=fc.sha(args.sync))
    assert sync_ref == baseline["summary"], "SYNC_CHANGED_SINCE_REPRO"
    rows = {code: row for code, row in fc._sync_prequery_rows(sync_ref, 20261030).items()
            if row.get("lifecycle_skip")}
    assert len(rows) == 29
    before = {code: fc.sha(Path(row["path"])) for code, row in rows.items()}
    calls = []

    def forbidden_provider():
        calls.append("client_factory")
        raise AssertionError("PROVIDER_MUST_NOT_BE_INVOKED")

    # First use the actual collection entry point for the reported single stock.
    with tempfile.TemporaryDirectory(prefix="single_000016_", dir=args.evidence_root) as temporary:
        single = fc.collect_metadata(["000016.SZ"], cache_root=Path(temporary), target=20261030,
            prequery_sync_ref=sync_ref, client_factory=forbidden_provider, min_interval=0, retries=0)
    assert single["provider_call_count"] == 0 and calls == []
    assert single["symbols"]["000016.SZ"]["status"] == "SOP_SKIPPED"
    assert single["status"] == "PARTIAL_EXPECTED_EXCLUSIONS"
    assert fc.sha(Path(rows["000016.SZ"]["path"])) == before["000016.SZ"]
    fc._json(args.evidence_root / "REAL_000016.json", single)

    previous = {item["code"]: item for item in baseline["rows"]}
    results = []
    for code, row in rows.items():
        decision = fc._verified_sop_skip(code, row, 20261030, sync_ref)
        assert decision is not None and decision["provider_invoked"] is False, code
        assert decision["original_sync_row"] == row
        assert fc.sha(Path(row["path"])) == before[code] == previous[code]["raw"]["sha256"]
        if previous[code]["accepted"]:
            assert decision["proof_route"] == previous[code]["proof_route"], code
        prior_day = int((datetime.strptime(row["lifecycle_fact"]["delisting_effective_date"], "%Y%m%d")
                         - timedelta(days=1)).strftime("%Y%m%d"))
        assert fc._verified_sop_skip(code, row, prior_day, sync_ref) is None
        results.append(dict(code=code, previous_accepted=previous[code]["accepted"], accepted=True,
            proof_route=decision["proof_route"], raw_unchanged=True, raw_sha256=before[code],
            classification=decision["classification"], source_quality=row["lifecycle_fact"].get("source_quality"),
            accepted_review_literal=row["lifecycle_fact"]["accepted_review_literal"]))
    bad = copy.deepcopy(rows["000016.SZ"])
    bad["lifecycle_fact"]["accepted_case_result_ref"]["sha256"] = "0" * 64
    assert fc._verified_sop_skip("000016.SZ", bad, 20261030, sync_ref) is None
    assert fc._verified_sop_skip("200016.SZ", rows["000016.SZ"], 20261030, sync_ref) is None
    report = dict(status="PASS_READ_ONLY_BINDING_SCOPE", observed_at=fc._now(), sync=sync_ref,
        source=dict(path=str(Path(fc.__file__).resolve()), sha256=fc.sha(Path(fc.__file__))),
        baseline=dict(path=str(baseline_path), sha256=fc.sha(baseline_path)), single_zero_provider=True,
        fixed_count=sum(not row["previous_accepted"] for row in results),
        retained_count=sum(row["previous_accepted"] for row in results), rows=results,
        negative_approval_sha_rejected=True, b_share_code_rejected=True, all_pre_effective_rejected=True,
        consumer_independent_review="PENDING_UNCHANGED", provider_contexts_created=len(calls),
        RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False,
        installation="NOT_RUN", natural_daily_resume="NOT_RUN", price_chain_admission=False)
    assert report["fixed_count"] == 9 and report["retained_count"] == 20
    fc._json(args.evidence_root / "REAL_29_BINDING_RESULT.json", report)
    print(json.dumps({key: report[key] for key in ("status", "fixed_count", "retained_count", "provider_contexts_created")}))


if __name__ == "__main__":
    main()
