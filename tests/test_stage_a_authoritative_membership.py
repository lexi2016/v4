import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from stage_center.a_share_membership import SELECTOR_POINTER_ENV, resolve_membership
from stage_center.acquisition import SourceResult, StageUniverseBinding, build_plan

CODES = ("A.600000", "A.920045", "A.920985", "A.000660", "A.515880")
TRADE_DATE = "20261112"
SIGNAL_DATE = "20261111"


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_sha(value) -> str:
    return _sha(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode())


def _write_json(path: Path, value: dict) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    path.write_bytes(raw)
    return raw


def make_inputs(tmp_path, *, mutate_receipt=None, mutate_snapshot=None, signal_date=SIGNAL_DATE,
                trade_date=TRADE_DATE, current_schema="v2"):
    snapshot_path = tmp_path / "qfq" / "snapshot.json"
    selector_path = tmp_path / "qfq" / "selector.parquet"
    receipt_path = tmp_path / "qfq" / "candidate_receipt.json"
    pointer_path = tmp_path / "data_layer_interface_current" / "CURRENT_SELECTOR_READY_PANEL.txt"

    snapshot = dict(
        schema="a_share_qfq_adjustment_input_research_cache_v1",
        asof_date=int(signal_date),
        coverage_end_date=int(signal_date),
        original_target_codes=["600000.SH", "920045.BJ", "920985.BJ"],
        symbols={"600000.SH": {}, "920985.BJ": {}},
        original_quarantine_eligible={"920045.BJ": {"reason": "SUSPENDED"}},
        quarantine_symbols={},
        production_allowed=False,
        buy_gate_updated=False,
        orders_sent=False,
    )
    if mutate_snapshot:
        mutate_snapshot(snapshot)
    snapshot_raw = _write_json(snapshot_path, snapshot)
    snapshot_sha = _sha(snapshot_raw)

    generation_id = "a" * 64
    input_sha = "f" * 64
    table = pa.table({"ts_code": ["600000.SH"], "trade_date": [signal_date]}).replace_schema_metadata(
        {b"a_share_qfq_contract_v1": json.dumps(dict(
            generation_id=generation_id,
            input_sha256=input_sha,
            asof_date=int(signal_date),
            generation_manifest_path=str(receipt_path),
            snapshot_file_sha256=snapshot_sha,
        )).encode()}
    )
    selector_path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, selector_path)
    selector_sha = _sha(selector_path.read_bytes())

    receipt = dict(
        schema="a_share_qfq_panel_v1",
        status="CANDIDATE_READY",
        generation_id=generation_id,
        input_sha256=input_sha,
        asof_date=int(signal_date),
        target_date=int(signal_date),
        generation_manifest_path=str(receipt_path),
        candidates={"selector": str(selector_path)},
        candidate_sha256={"selector": selector_sha},
        adjustment_snapshot={"path": str(snapshot_path), "sha256": snapshot_sha},
        snapshot_file_sha256=snapshot_sha,
        pit_certified=False,
        RESEARCH_ONLY=True,
        production_allowed=False,
        buy_gate_updated=False,
        orders_sent=False,
    )
    if mutate_receipt:
        mutate_receipt(receipt)
    _write_json(receipt_path, receipt)
    pointer_path.parent.mkdir(parents=True, exist_ok=True)
    pointer_path.write_text(str(selector_path) + "\n", encoding="utf-8")

    codes_sha = _canonical_sha(list(CODES))
    if current_schema == "v3":
        current = dict(
            schema_version="v3_5.stage_acquisition_universe.current.v3",
            trade_date=trade_date,
            role="A_SHARE_STAGE_ACQUISITION_UNIVERSE_V3",
            status="READY",
            run_id="fixture-run-20261112",
            artifact_canonical_sha256="c" * 64,
            manifest_canonical_sha256="d" * 64,
            receipt_canonical_sha256="e" * 64,
            codes_sha256=codes_sha,
            source_pool_provenance_sha256="b" * 64,
            row_count=len(CODES),
            production_allowed=False,
            buy_gate_updated=False,
            orders_sent=False,
        )
    else:
        current = dict(
            schema_version="v3_5.stage_acquisition_universe.current.v2",
            trade_date=trade_date,
            role="A_SHARE_STAGE_ACQUISITION_UNIVERSE_V2",
            status="READY",
            run_id="fixture-run-20261112",
            artifact_sha256="c" * 64,
            manifest_sha256="d" * 64,
            receipt_sha256="e" * 64,
            codes_sha256=codes_sha,
            source_projection_sha256="b" * 64,
            row_count=len(CODES),
            production_allowed=False,
            buy_gate_updated=False,
            orders_sent=False,
        )
    current_role = current["role"]
    current_relative = f"current/{trade_date}/{current_role}/current.json"
    current_path = tmp_path / "candidate" / current_relative
    current_raw = _write_json(current_path, current)
    candidate = SimpleNamespace(
        root=tmp_path / "candidate",
        trade_date=trade_date,
        current_relative=current_relative,
        current_sha256=_sha(current_raw),
        run_id=current["run_id"],
        codes=CODES,
        artifact_sha256=current.get("artifact_sha256", current.get("artifact_canonical_sha256")),
        manifest_sha256=current.get("manifest_sha256", current.get("manifest_canonical_sha256")),
        receipt_sha256=current.get("receipt_sha256", current.get("receipt_canonical_sha256")),
        source_projection_sha256=current.get("source_projection_sha256", ""),
    )
    return candidate, pointer_path, current_path, selector_path, receipt_path, snapshot_path


def _membership(candidate, pointer_path, trade_date=TRADE_DATE):
    return resolve_membership(candidate, trade_date, selector_pointer_path=pointer_path)


def test_exact_d_minus_one_selector_binds_full_inventory_and_preserves_etf_guard(tmp_path, monkeypatch):
    candidate, pointer_path, *_ = make_inputs(tmp_path)
    monkeypatch.setenv(SELECTOR_POINTER_ENV, str(pointer_path))
    monkeypatch.setenv("V4_STAGE_A_MEMBERSHIP_CONFIG", "/stale/20261112.json")
    monkeypatch.setenv("V4_STAGE_A_MEMBERSHIP_CONFIG_SHA256", "9" * 64)
    membership = resolve_membership(candidate, TRADE_DATE)

    assert membership.report["status"] == "BOUND_POSITIVE_INVENTORY"
    assert membership.report["trade_date"] == TRADE_DATE
    assert membership.report["signal_date"] == SIGNAL_DATE
    assert membership.report["candidate_current_sha256"] == candidate.current_sha256
    assert membership.report["receipt_status"] == "CANDIDATE_READY"
    assert membership.report["qfq_pit_certified"] is False
    assert membership.report["outer_a_receipt"] == "NOT_READ"
    assert membership.report["inventory_rows"] == 3
    assert membership.report["unknown_codes"] == ["A.000660"]
    assert membership.codes == CODES[:-1]
    assert membership.report["quarantined"] == [
        {"code": "A.515880", "reason": "NON_EQUITY_CODE_FAMILY", "classification": "KNOWN_NON_STOCK_FAMILY"}
    ]
    assert membership.report["inventory_is_listing_or_pit_proof"] is False


def test_strict_v3_candidate_current_binding_is_supported(tmp_path):
    candidate, pointer_path, *_ = make_inputs(tmp_path, current_schema="v3")
    membership = _membership(candidate, pointer_path)
    assert membership.report["status"] == "BOUND_POSITIVE_INVENTORY"
    assert membership.report["candidate_current_sha256"] == candidate.current_sha256


def test_request_scoring_and_coverage_share_filter_and_hk_is_untouched(tmp_path):
    candidate, pointer_path, *_ = make_inputs(tmp_path)
    membership = _membership(candidate, pointer_path)
    a = StageUniverseBinding.ready(market="A_SHARE", trade_date=TRADE_DATE, role="SOURCE", codes=CODES,
                                   source_run_id="r", sha256=candidate.current_sha256)
    hk = StageUniverseBinding.ready(market="HK_CONNECT", trade_date=TRADE_DATE, role="HK", codes=("HK.00700",), source_run_id="h", sha256="c" * 64)
    plan = build_plan(tmp_path, TRADE_DATE, "STAGE_0930_0935", candidate=SimpleNamespace(codes=CODES),
                      universe_bindings={"A_SHARE": membership.bind(a), "HK_CONNECT": membership.bind(hk)})
    assert plan.codes_for("A_SHARE") == CODES[:-1]
    assert plan.codes_for("HK_CONNECT") == ("HK.00700",)
    source = SourceResult("cached", "PARTIAL_WITH_ROWS", rows=tuple({"code": code} for code in ["SH.600000", "BJ.920045", "BJ.920985", "SH.515880"]), requested_rows=5,
                          missing_symbols=("SZ.000660",), cannot_confirm=("ORIGINAL_QUOTE_GAP",))
    filtered = membership.source(source)
    assert len(source.rows) == 4
    assert len(filtered.rows) == 3 and filtered.requested_rows == 4
    assert filtered.missing_symbols == ("SZ.000660",)
    assert membership.source(source, "HK_CONNECT") is source
    raw = dict(requested_rows=5, missing_symbols=["SZ.000660"], cannot_confirm=["ORIGINAL_QUOTE_GAP"], source_evidence=[])
    view = membership.builder_raw(raw, filtered)
    assert raw["requested_rows"] == 5 and view["requested_rows"] == 4
    assert "ORIGINAL_QUOTE_GAP" in view["cannot_confirm"]
    assert any("A.000660" in reason for reason in view["cannot_confirm"])


def test_missing_exact_pointer_stays_unknown_even_with_stale_config_env(tmp_path, monkeypatch):
    candidate, *_ = make_inputs(tmp_path)
    monkeypatch.setenv("V4_STAGE_A_MEMBERSHIP_CONFIG", "/stale/20261112.json")
    monkeypatch.setenv("V4_STAGE_A_MEMBERSHIP_CONFIG_SHA256", "9" * 64)
    monkeypatch.delenv(SELECTOR_POINTER_ENV, raising=False)
    membership = resolve_membership(candidate, TRADE_DATE)
    assert membership.codes == CODES[:-1]
    assert membership.report["status"] == "UNKNOWN"
    assert "MEMBERSHIP_SELECTOR_POINTER_REQUIRED" in membership.report["reason"]


def test_wrong_trade_date_or_candidate_current_sha_stays_unknown(tmp_path):
    candidate, pointer_path, *_ = make_inputs(tmp_path)
    wrong_date = _membership(candidate, pointer_path, "20261113")
    wrong_sha_candidate = SimpleNamespace(**{**vars(candidate), "current_sha256": "9" * 64})
    wrong_sha = _membership(wrong_sha_candidate, pointer_path)
    assert wrong_date.report["status"] == "UNKNOWN"
    assert "MEMBERSHIP_CANDIDATE_DATE_MISMATCH" in wrong_date.report["reason"]
    assert wrong_sha.report["status"] == "UNKNOWN"
    assert "MEMBERSHIP_CANDIDATE_CURRENT_SHA_MISMATCH" in wrong_sha.report["reason"]


def test_pointer_to_neighbor_date_does_not_fallback_or_rebind(tmp_path):
    candidate, pointer_path, *_ = make_inputs(tmp_path, signal_date="20261117", trade_date="20261119")
    # The target date's exact previous A day is 20261118; the current selector
    # is one trading day older and cannot be substituted.
    membership = _membership(candidate, pointer_path, "20261119")
    assert membership.report["status"] == "UNKNOWN"
    assert "MEMBERSHIP_SELECTOR_DATE_MISMATCH" in membership.report["reason"]


def test_failed_generation_receipt_stays_unknown(tmp_path):
    candidate, pointer_path, *_ = make_inputs(tmp_path, mutate_receipt=lambda r: r.update(status="FAILED"))
    membership = _membership(candidate, pointer_path)
    assert membership.report["status"] == "UNKNOWN"
    assert "MEMBERSHIP_GENERATION_RECEIPT_MISMATCH" in membership.report["reason"]


@pytest.mark.parametrize("mutation", [
    lambda s: s.pop("original_target_codes"),
    lambda s: s["symbols"].pop("920985.BJ"),
])
def test_incomplete_original_inventory_stays_unknown(tmp_path, mutation):
    candidate, pointer_path, *_ = make_inputs(tmp_path, mutate_snapshot=mutation)
    membership = _membership(candidate, pointer_path)
    assert membership.report["status"] == "UNKNOWN"
    assert "MEMBERSHIP_ORIGINAL_TARGET_INVENTORY" in membership.report["reason"]


def test_selector_date_mismatch_stays_unknown(tmp_path):
    candidate, pointer_path, *_ = make_inputs(tmp_path, signal_date="20261110")
    membership = _membership(candidate, pointer_path)
    assert membership.report["status"] == "UNKNOWN"
    assert "MEMBERSHIP_SELECTOR_DATE_MISMATCH" in membership.report["reason"]


def test_pointer_drift_during_validation_stays_unknown(tmp_path, monkeypatch):
    candidate, pointer_path, *_ = make_inputs(tmp_path)
    original = pointer_path.read_bytes()
    from stage_center import a_share_membership
    read_footer = a_share_membership._selector_footer

    def drift_after_footer(selector_path, raw=None):
        footer = read_footer(selector_path, raw)
        pointer_path.write_bytes(original + b"\n")
        return footer

    monkeypatch.setattr(a_share_membership, "_selector_footer", drift_after_footer)
    membership = _membership(candidate, pointer_path)
    assert membership.report["status"] == "UNKNOWN"
    assert "MEMBERSHIP_SELECTOR_AUTHORITY_DRIFT" in membership.report["reason"]


def test_snapshot_path_drift_after_hash_and_parse_stays_unknown(tmp_path, monkeypatch):
    candidate, pointer_path, _, _, _, snapshot_path = make_inputs(tmp_path)
    from stage_center import a_share_membership
    original_loads = json.loads

    def mutate_snapshot_after_parse(raw, *args, **kwargs):
        value = original_loads(raw, *args, **kwargs)
        if isinstance(value, dict) and "original_target_codes" in value:
            snapshot_path.write_text("{}", encoding="utf-8")
        return value

    monkeypatch.setattr(a_share_membership.json, "loads", mutate_snapshot_after_parse)
    membership = _membership(candidate, pointer_path)
    assert membership.report["status"] == "UNKNOWN"
    assert "MEMBERSHIP_SNAPSHOT_AUTHORITY_DRIFT" in membership.report["reason"]
