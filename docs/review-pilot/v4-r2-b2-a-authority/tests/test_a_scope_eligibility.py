import copy
import csv
import hashlib
import json
import os
import time
from contextlib import nullcontext
from pathlib import Path

import pytest

from ops import a_share_daily_sync as owner
from ops import macos_research_panel_daily as daily
from ops import macos_research_panel_daily_authority as authority
from ops import macos_research_panel_daily_receipts as receipts


TARGET = 20261123


def _native(root, symbol, market, date, **fields):
    suffix = ("sz", "sh", "bj")[market]
    path = root / "vipdoc" / suffix / "lday" / f"{suffix}{symbol}.day"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(owner.DAY_STRUCT.pack(date, 100, 100, 100, 100, 1000.0, 100, 0))
    return {
        "symbol": symbol, "market": market, "path": str(path),
        "source_sha256_after": hashlib.sha256(path.read_bytes()).hexdigest(),
        **fields,
    }


def _accepted(root, symbol="000001", market=0):
    return _native(root, symbol, market, TARGET, status="ALREADY_CURRENT",
                   fetch_status="ALREADY_CURRENT", classification="ACCEPTED")


def _quarantine(root, symbol, market, reason, **fields):
    return _native(root, symbol, market, 20261120, status="CANNOT_CONFIRM",
                   fetch_status="REBUILD_REQUIRED", classification="QUARANTINED", quarantine=True,
                   target_date_ready=False, reason_code=reason, **fields)


def _alias(root, symbol="835305"):
    fact = owner._load_verified_bse_alias_facts()[f"{symbol}.BJ"]
    return _quarantine(
        root, symbol, 2, owner.BSE_ALIAS_SKIP_REASON, alias_skip=True, alias_fact=fact,
        alias_asset_sha256=owner.BSE_ALIAS_ASSET_SHA256, alias_review_sha256=owner.BSE_ALIAS_REVIEW_SHA256,
        replacement_target_in_scope=True, replacement_ts_code=fact["new_ts_code"],
    )


def _delisting(root, symbol="920305", market=2):
    ts_code = f"{symbol}.{('SZ', 'SH', 'BJ')[market]}"
    fact = owner._load_verified_lifecycle_facts()[ts_code]
    policy = fact.get("source_policy_ref")
    return _quarantine(
        root, symbol, market, owner.LIFECYCLE_SKIP_REASON, lifecycle_skip=True, lifecycle_fact=fact,
        lifecycle_asset_sha256=policy["sha256"] if policy else owner.LIFECYCLE_NOTES_SHA256,
        **({"lifecycle_policy_ref": policy} if policy else {}),
    )


def _scope(rows, target=TARGET):
    return authority._eligible_sync_scope(
        target, {(r["symbol"], r["market"], r["path"]): r for r in rows}, evidence_module=owner,
    )


@pytest.mark.parametrize("fault", [
    "alias_proof", "alias_sha", "out_of_scope", "wrong_market", "duplicate_replacement",
    "replacement_unresolved", "late_alias", "same_day_alias_capture", "delisting_proof",
    "delisting_sha", "late_delisting",
])
def test_unproven_terminal_classifications_stay_in_denominator(tmp_path, fault):
    root = tmp_path.resolve()
    old = _alias(root)
    replacement = _delisting(root)
    accepted = _accepted(root)
    rows = [old, replacement, accepted]
    target = TARGET
    checked = old["symbol"]
    if fault == "alias_proof":
        old.pop("alias_fact")
    elif fault == "alias_sha":
        old["alias_review_sha256"] = "0" * 64
    elif fault == "out_of_scope":
        rows.remove(replacement)
    elif fault == "wrong_market":
        rows[1] = _accepted(root, "920305", 1)
    elif fault == "duplicate_replacement":
        rows.append(dict(replacement, path=replacement["path"] + ".duplicate"))
    elif fault == "replacement_unresolved":
        rows[1] = _quarantine(root, "920305", 2, "TARGET_DATE_MISSING")
    elif fault == "late_alias":
        target = 20251008
    elif fault == "same_day_alias_capture":
        target = 20261024
    elif fault == "delisting_proof":
        replacement.pop("lifecycle_fact")
        checked = replacement["symbol"]
    elif fault == "delisting_sha":
        replacement["lifecycle_asset_sha256"] = "0" * 64
        checked = replacement["symbol"]
    elif fault == "late_delisting":
        rows[1] = _delisting(root, "002731", 0)
        target = 20261119
        checked = rows[1]["symbol"]
    scope = _scope(rows, target)
    assert checked in {row["symbol"] for row in scope["unresolved_eligible"]}
    assert scope["eligible_target_count"] == len(rows) - scope["verified_obsolete_count"]


def _report(rows, run_dir):
    keyed = [(r["symbol"], r["market"], r["path"]) for r in rows]
    counts = {
        "target_count": len(rows),
        "accepted_count": sum(r["classification"] == "ACCEPTED" for r in rows),
        "quarantine_count": sum(r["classification"] == "QUARANTINED" for r in rows),
        "pending_count": 0,
    }
    failures = [{"failure_type": "INVALID_BAR"}] if any(r.get("reason_code") == "INVALID_BAR" for r in rows) else []
    report = {
        "target_date": str(TARGET), "target_fingerprint": authority._canonical_scope_fingerprint(keyed),
        "target_keys": [{"symbol": code, "market": market, "path": path} for code, market, path in keyed],
        "status": "FAILED", "authority_status": "REBUILD_REQUIRED", "exit_code": 2,
        "run_dir": str(run_dir), "symbol_reconciliation": rows, "failures": failures,
        "technical_failure_count": len(failures), "reconciliation": {"symbols": rows, **counts}, **counts,
    }
    run_dir.mkdir(parents=True)
    with (run_dir / "file_results.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, ["symbol", "market", "path", "status", "fetch_status",
                                        "classification", "source_sha256_after"], extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return report


@pytest.mark.parametrize("case", ["complete", "accepted_replacement", "residual", "nested_proof_mismatch",
                                  "ledger_mismatch", "native_sha_drift", "minimum",
                                  "exact_unaccepted_bar", "future_unaccepted_bar", "embedded_unaccepted_bar"])
def test_authority_materializes_only_bound_inputs_and_hands_off_exact_receipt(tmp_path, monkeypatch, case):
    from ops import research_panel_daily_source, research_storage_governance

    root = tmp_path.resolve() / "tdx"
    output = tmp_path.resolve() / "receipts"
    rows = [_accepted(root), _alias(root), _delisting(root)]
    direct = case == "accepted_replacement"
    if direct:
        rows[2] = _accepted(root, "920305", 2)
    if case in {"residual", "exact_unaccepted_bar", "future_unaccepted_bar", "embedded_unaccepted_bar"}:
        rows.append(_quarantine(root, "600185", 1, "INVALID_BAR"))
    if case.endswith("_unaccepted_bar"):
        row = rows[-1]
        path = Path(row["path"])
        prior = path.read_bytes()
        day = TARGET + 1 if case == "future_unaccepted_bar" else TARGET
        current = owner.DAY_STRUCT.pack(day, 100, 100, 100, 100, 1000.0, 100, 0)
        # In the embedded case even a truthful last-date claim is insufficient.
        body = current + prior if case == "embedded_unaccepted_bar" else prior + current
        path.write_bytes(body)
        row["source_sha256_after"] = hashlib.sha256(body).hexdigest()
        row["last_date_after"] = 20261120
    report = _report(rows, output / "a_sync_authority" / str(TARGET))
    if case == "nested_proof_mismatch":
        report["reconciliation"]["symbols"] = copy.deepcopy(report["reconciliation"]["symbols"])
        report["reconciliation"]["symbols"][1]["alias_review_sha256"] = "0" * 64
    original = copy.deepcopy(report)
    if case == "ledger_mismatch":
        ledger = Path(report["run_dir"]) / "file_results.csv"
        ledger.write_text(ledger.read_text().replace(rows[0]["source_sha256_after"], "0" * 64))
    if case == "native_sha_drift":
        path = Path(rows[0]["path"])
        path.write_bytes(owner.DAY_STRUCT.pack(TARGET, 101, 101, 101, 101, 1000.0, 100, 0))
    monkeypatch.setattr(research_storage_governance, "input_preflight", lambda **_: nullcontext(None))
    monkeypatch.setattr(research_storage_governance, "input_write_seams", lambda _: nullcontext())
    monkeypatch.setattr(research_storage_governance, "guarded_raw_run", lambda *_: report)
    monkeypatch.setattr(research_panel_daily_source, "acquire_daily_input", lambda *_: {
        "path": str(tmp_path / "unused-input"), "sha256": "a" * 64,
    })
    args = (owner.__file__, root, str(TARGET), output)
    if case == "nested_proof_mismatch":
        with pytest.raises(authority.SnapshotGateError, match="proof rows disagree"):
            daily.run_windows_a_sync_authority(*args)
        assert not (output / "formula_inputs").exists()
        return
    if case.endswith("_unaccepted_bar"):
        with pytest.raises(authority.SnapshotGateError, match="unaccepted current or future native bar"):
            daily.run_windows_a_sync_authority(*args)
        assert not (output / "formula_inputs").exists()
        return
    if case == "ledger_mismatch":
        with pytest.raises(authority.SnapshotGateError, match="audited identity and SHA"):
            daily.run_windows_a_sync_authority(*args)
        return
    if case == "native_sha_drift":
        with pytest.raises(authority.SnapshotGateError, match="SHA drift"):
            daily.run_windows_a_sync_authority(*args)
        return
    if case == "minimum":
        with pytest.raises(authority.SnapshotGateError, match="1 < 2"):
            daily.run_windows_a_sync_authority(*args, minimum_target_date_files=2)
        return
    sync = daily.run_windows_a_sync_authority(*args)
    partial = case == "residual"
    assert report == original
    assert sync["target_count"] == 3 + partial
    assert sync["quarantine_count"] == 2 + partial - direct
    assert sync["scope_eligibility"]["verified_obsolete_count"] == 2 - direct
    assert sync["scope_eligibility"]["unresolved_eligible_count"] == int(partial)
    assert sync["coverage_rate"] == (0.5 if partial else 1.0)
    assert sync["authority_status"] == ("REBUILD_REQUIRED" if partial else "PASS")
    assert sync["formula_input_mode"] == "ACCEPTED_ONLY"
    assert {path.name for path in Path(sync["formula_tdx_root"]).rglob("*.day")} == (
        {"sz000001.day", "bj920305.day"} if direct else {"sz000001.day"}
    )

    selector = tmp_path.resolve() / "selector"
    backtest = tmp_path.resolve() / "backtest"
    pointers = {"selector_pointer": selector.with_suffix(".current"), "backtest_pointer": backtest.with_suffix(".current")}
    for artifact, pointer in zip((selector, backtest), pointers.values()):
        artifact.write_bytes(artifact.name.encode())
        pointer.write_text(artifact.name + "\n")
    formula = {
        "authority": {"status": "PASS", "selector_increment_rows": 1, "backtest_pointer_ready": True},
        "selector": str(selector), "selector_sha256": hashlib.sha256(selector.read_bytes()).hexdigest(),
        "backtest": str(backtest), "backtest_sha256": hashlib.sha256(backtest.read_bytes()).hexdigest(),
    }
    receipt = receipts.build_a_lane_outcome(sync, formula, str(TARGET), None)
    receipt |= {"schema_version": "v3.macos.research_panel_receipt.v1", "lane": "A"}
    assert receipts.validate_a_receipt(receipt, str(TARGET), **pointers) == ("PARTIAL_WITH_ROWS" if partial else "READY")
    # Old receipts retain the old nominal coverage contract.
    legacy = copy.deepcopy(receipt)
    legacy.pop("scope_eligibility")
    legacy["sync"].pop("scope_eligibility")
    legacy["coverage_rate"] = (1 + direct) / len(rows)
    legacy["status"] = "PARTIAL"
    assert receipts.validate_a_receipt(legacy, str(TARGET), **pointers) == "PARTIAL_WITH_ROWS"
    tampered = copy.deepcopy(receipt)
    tampered["scope_eligibility"]["eligible_target_count"] += 1
    assert receipts.validate_a_receipt(tampered, str(TARGET), **pointers) is None
    if partial:
        receipt["status"] = "READY"
        assert receipts.validate_a_receipt(receipt, str(TARGET), **pointers) is None


def test_sync_uses_index_and_keeps_nominal_producer_ledger(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    rows = [_accepted(root), _alias(root), _delisting(root)]
    targets = [
        owner.DailyTarget(code=row["symbol"], market=row["market"], path=Path(row["path"]))
        for row in rows
    ]
    original = owner._bse_alias_scope_index
    index_calls = []

    def index_once(facts, target_keys):
        keys = list(target_keys)
        index_calls.append(keys)
        return original(facts, keys)

    def provider_not_called(*_):
        pytest.fail("Exact accepted and verified obsolete symbols require no provider call")

    monkeypatch.setattr(owner, "_bse_alias_scope_index", index_once)
    report = owner.run_sync(
        targets, target_date=TARGET, api_factory=provider_not_called,
        host_candidates=(("unused", 7709),), progress_path=root / "progress.json",
    )
    assert index_calls == [[(item.code, item.market) for item in targets]]
    assert report["status"] == "FAILED"
    assert report["target_count"] == 3
    assert report["accepted_count"] == 1
    assert report["quarantine_count"] == 2
    assert report["by_symbol"]["835305"]["replacement_target_in_scope"] is True
    assert report["by_symbol"]["920305"]["lifecycle_skip"] is True


def test_frozen_d23_only_when_exact_archived_evidence_is_available():
    evidence_path = os.environ.get("V4_B2_FROZEN_D23_EVIDENCE")
    if not evidence_path:
        pytest.skip("Set V4_B2_FROZEN_D23_EVIDENCE to the exact read-only D23 evidence record.")
    evidence = json.loads(Path(evidence_path).read_text())
    raw_bytes = Path(evidence["source"]).read_bytes()
    assert hashlib.sha256(raw_bytes).hexdigest() == evidence["source_sha256"]
    source = json.loads(raw_bytes)
    rows = source["authority"]["symbol_reconciliation"]
    assert source["authority"]["target_count"] == len(rows) == 5842
    result = _scope(rows)
    assert result["eligible_target_count"] == 5579
    assert result["verified_obsolete_count"] == 263
    assert result["unresolved_eligible_count"] == 11
    assert result["eligible_coverage_rate"] == 5568 / 5579
    assert {(r["symbol"], r["market"], r["reason_code"]) for r in result["unresolved_eligible"]} == {
        (r["symbol"], r["market"], r["reason"]) for r in evidence["unresolved"]
    }
    actual_aliases = {row["symbol"]: row["replacement_ts_code"] for row in result["verified_obsolete"]
                      if "replacement_ts_code" in row}
    assert len(actual_aliases) == 232
    assert actual_aliases["835305"] == "920305.BJ"
    assert actual_aliases["839680"] == "920680.BJ"

    if os.environ.get("V4_B2_VERIFY_FROZEN_NATIVE") == "1":
        nonaccepted = {(row["symbol"], row["market"], row["path"]): row for row in rows
                       if authority._row_classification(row) != "ACCEPTED"}
        assert len(nonaccepted) == 274
        authority._assert_no_unaccepted_current_native_bar(
            TARGET, nonaccepted, classify=authority._row_classification,
        )

    baseline_path = os.environ.get("V4_B2_BASELINE_SYNC")
    if baseline_path:
        baseline_path = Path(baseline_path)
        assert hashlib.sha256(baseline_path.read_bytes()).hexdigest() == (
            "d68cfbdf1d040a9bb175ec2e78c0e1858d7a2f5c47a3bad0e1663bd0c3f77a4d"
        )
        baseline = authority._load_authority_module(baseline_path, "_v4_b2_baseline_sync")
        old, old_work = _measure_alias_lookups(baseline, rows, indexed=False)
        new, new_work = _measure_alias_lookups(owner, rows, indexed=True)
        assert old == new == actual_aliases
        assert old_work["target_code_reads"] == 2612247
        assert new_work["target_code_reads"] == 2 * len(rows)
        assert old_work["reverse_fact_rows_visited"] == 57536
        assert new_work["reverse_fact_rows_visited"] == 248
        print(json.dumps({"baseline": old_work, "candidate": new_work}, sort_keys=True))


def _measure_alias_lookups(module, rows, *, indexed):
    work = {"target_code_reads": 0, "reverse_fact_rows_visited": 0}

    class Facts(dict):
        def values(self):
            for fact in super().values():
                work["reverse_fact_rows_visited"] += 1
                yield fact

    class Target:
        def __init__(self, row):
            self.symbol = row["symbol"]
            self.market = row["market"]

        @property
        def code(self):
            work["target_code_reads"] += 1
            return self.symbol

    facts = Facts(owner._load_verified_bse_alias_facts())
    targets = [Target(row) for row in rows]
    started = time.perf_counter()
    scope_index = (
        module._bse_alias_scope_index(facts, ((row.code, row.market) for row in targets)) if indexed else None
    )
    aliases = {}
    for row in targets:
        if indexed:
            fact = module._bse_alias_fact_for_target(facts, row.code, row.market, TARGET, scope_index=scope_index)
        else:
            fact = module._bse_alias_fact_for_target(facts, row.code, row.market, TARGET, targets)
        if fact is not None:
            if indexed:
                in_scope = scope_index[1].get(fact["new_code"]) == (2,)
            else:
                in_scope = any(item.code == fact["new_code"] and item.market == 2 for item in targets)
            assert in_scope
            aliases[row.symbol] = fact["new_ts_code"]
    work["instrumented_seconds"] = time.perf_counter() - started
    return aliases, work
