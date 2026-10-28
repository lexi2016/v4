"""Exercise the current A formula retention entrypoint and its frozen history contract.

The historical anomaly checks call the same real function used by the public
formula runner; this file does not replace formula, file reader or publication
behavior.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]


def _implementation():
    from ops import a_formula_increment as increment

    return {
        "_audit_existing_history": increment._audit_existing_history,
        "AuthorityError": increment.AuthorityError,
    }


def _approved():
    contract = json.loads((ROOT / "contracts/a_known_history_gaps.json").read_text(encoding="utf-8"))
    seeds = contract["seeds"]
    # The archive input is optional at collection time, but when supplied by
    # the focused command it must match the canonical contract byte-for-byte
    # at the seed/key level. This keeps the test tied to the runtime contract
    # while retaining an independently copied archive fixture for comparison.
    archive_path = os.environ.get("A_KNOWN_HISTORY_ARCHIVE_FIXTURE")
    if archive_path:
        archive = json.loads(Path(archive_path).read_text(encoding="utf-8"))
        assert archive["seeds"] == seeds
    return seeds


def _frame(seed):
    return pd.DataFrame([{**k, "trade_date": int(k["trade_date"]), "open": 9., "low": 8.,
                          "high": 10., "close": 11., "retained_extra": "untouched"} for k in seed["keys"]])


@pytest.mark.parametrize("role", ["selector", "backtest"])
def test_exact_approved_anomalies_are_retained_not_repaired(role):
    impl = _implementation(); seed = next(x for x in _approved() if x["role"] == role)
    current = _frame(seed); before = current.copy(deep=True)
    result = impl["_audit_existing_history"](current, current.copy(), role=role, target_date=20260911,
                                            seed_sha256=seed["seed_sha256"])
    assert sum(g["rows"] for g in result["known_historical_gaps"]) == 354
    assert result["historical_health"] == "CANNOT_CONFIRM"
    pd.testing.assert_frame_equal(before, current)


def test_public_run_increment_authority_binds_runtime_history_roles(tmp_path: Path, monkeypatch) -> None:
    """Exercise the real public runner branch and its contract-role aliases."""
    from ops import a_formula_increment as increment

    seeds = {seed["role"]: seed for seed in _approved()}
    frames = {role: _frame(seed) for role, seed in seeds.items()}
    target_row = pd.DataFrame([{
        "ts_code": "600001.SH",
        "trade_date": 20260911,
        "open": 9.0,
        "high": 10.0,
        "low": 8.0,
        "close": 9.0,
        "volume": 100,
        "amount": 1000,
        "retained_extra": "new-target",
    }])
    frames = {role: pd.concat([frame, target_row], ignore_index=True) for role, frame in frames.items()}
    output_root = tmp_path / "output"
    data_root = output_root / "data"
    return_root = output_root / "runs"
    pointers = output_root / "pointers"
    pointers.mkdir(parents=True)
    selector_pointer = pointers / "selector.txt"
    backtest_pointer = pointers / "backtest.txt"
    selector_pointer.write_bytes(b"old-selector\n")
    backtest_pointer.write_bytes(b"old-backtest\n")
    selector_seed = tmp_path / "selector-seed.parquet"
    backtest_seed = tmp_path / "backtest-seed.parquet"
    selector_seed.write_bytes(b"selector-seed-placeholder")
    backtest_seed.write_bytes(b"backtest-seed-placeholder")
    input_root = tmp_path / "input"
    input_root.mkdir()
    input_manifest = input_root / "manifest.json"
    contract_csv = tmp_path / "contract.csv"
    contract_csv.write_bytes(b"contract-placeholder")

    manifest = {
        "run_id": "role-binding-fixture",
        "manifest_sha256": "m" * 64,
    }
    monkeypatch.setattr(increment, "_load_input_manifest", lambda *_args, **_kwargs: (pd.DataFrame(), manifest))
    monkeypatch.setattr(increment, "load_authoritative_contract_rows", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(increment, "build_contract_policy", lambda *_args, **_kwargs: {"contract_version": "fixture"})
    monkeypatch.setattr(increment, "_read_seed", lambda _path, role: frames[role].copy(deep=True))
    monkeypatch.setattr(increment, "collect_increment_history", lambda frame: frame.copy(deep=True))
    monkeypatch.setattr(increment, "compute_formula_features", lambda frame: frame.copy(deep=True))
    monkeypatch.setattr(increment, "_backfill_increment_contract_columns", lambda frame, *_args: frame)
    monkeypatch.setattr(increment, "_audit_increment_boundary", lambda *_args: {"status": "PASS"})
    monkeypatch.setattr(increment, "filter_increment_rows", lambda *_args, **_kwargs: pd.DataFrame())

    seed_digests = {str(selector_seed): seeds["selector"]["seed_sha256"], str(backtest_seed): seeds["backtest"]["seed_sha256"]}

    def fake_sha256(path: Path | str) -> str:
        return seed_digests.get(str(path), "c" * 64)

    monkeypatch.setattr(increment, "sha256_file", fake_sha256)
    result = increment.run_increment_authority(
        target_date=20260911,
        input_root=input_root,
        input_manifest=input_manifest,
        data_root=data_root,
        return_root=return_root,
        selector_pointer=selector_pointer,
        backtest_pointer=backtest_pointer,
        selector_seed=selector_seed,
        backtest_seed=backtest_seed,
        contract_csv=contract_csv,
    )

    assert result["status"] == "READY", result.get("error")
    assert set(result["gates"]) == {"selector_history", "backtest_history"}
    for runtime_role, contract_role in (("selector_history", "selector"), ("backtest_history", "backtest")):
        gate = result["gates"][runtime_role]
        assert gate["role"] == runtime_role
        assert gate["known_historical_gap_binding"]["contract_role"] == contract_role
        assert gate["known_historical_gap_binding"]["status"] == "EXACT_SEED_AND_KEYS_MATCH"
        assert sum(item["rows"] for item in gate["known_historical_gaps"]) == 354


def test_unknown_history_role_fails_closed() -> None:
    impl = _implementation()
    seed = _approved()[0]
    current = _frame(seed)
    with pytest.raises(impl["AuthorityError"], match="historical role is not approved"):
        impl["_audit_existing_history"](
            current,
            current.copy(),
            role="selector_history_untrusted",
            target_date=20260911,
            seed_sha256=seed["seed_sha256"],
        )


@pytest.mark.parametrize("mutation", ["extra", "same_count_replacement", "missing", "all_missing", "wrong_seed", "wrong_role", "unknown_role"])
def test_unapproved_anomaly_identity_fails_closed(mutation):
    impl = _implementation(); seed = _approved()[0]; current = _frame(seed)
    digest, role = seed["seed_sha256"], seed["role"]
    if mutation == "extra":
        extra = current.iloc[[0]].copy(); extra["ts_code"] = "09999.HK"
        current = pd.concat([current, extra], ignore_index=True)
    elif mutation == "same_count_replacement":
        current.loc[0, "ts_code"] = "09999.HK"
    elif mutation == "missing":
        current = current.iloc[1:].copy()
    elif mutation == "all_missing":
        current["close"] = 9.
    elif mutation == "wrong_seed":
        digest = "0" * 64
    elif mutation == "wrong_role":
        role = "backtest"
    else:
        role = "selector_history_untrusted"
    with pytest.raises(impl["AuthorityError"]):
        impl["_audit_existing_history"](current, current.copy(), role=role, target_date=20260911, seed_sha256=digest)
