from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from stage_center.acquisition import SourceResult
from stage_center.acquisition import StageUniverseBinding
from stage_center.live_collectors import production_selection_builders
from stage_center._live_collectors_parts import selection_builder_registry as registry
from stage_center import selection as stage_selection
from stage_center import runner as stage_runner
from stage_center._runner_parts import tick_planning
from infrastructure import preselection_pool_store


_MISSING = ("HK.03268", "HK.03355", "HK.03881", "HK.09690")
_ZERO_VOLUME_REFERENCE = ("HK.01304", "HK.01333", "HK.01377")
_RESEARCH_ROW_PIT_STATUS = "NOT_FORMAL_PIT_MINUTE_CAPTURE_OCCURRED_AFTER_TARGET_CUTOFF"


def _contracted_case(monkeypatch):
    special = [*_MISSING, *_ZERO_VOLUME_REFERENCE, "HK.02402", "HK.02922"]
    codes = list(special)
    candidate = 10000
    while len(codes) < 100:
        code = f"HK.{candidate:05d}"
        if code not in codes:
            codes.append(code)
        candidate += 1
    pool_codes = tuple(sorted(codes))
    pool_codes_sha = hashlib.sha256(
        json.dumps(pool_codes, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    monkeypatch.setattr(registry, "_HK_0930_D1_CODES_SHA256", pool_codes_sha)

    evidence = (
        "historical_observation_contract=HK_STAGE0930_RESEARCH_ONLY",
        "historical_base_raw_sha256=eabaa273897b0db7261d0e0d3245493e75297e5f148edad665061d90fb5f6070",
        "historical_gap_fields_sha256=11e256bec4ee181f956bb2792260290b1e2b5784a9838ebef91b3074eebbcc3e",
        "historical_gap_csv_sha256=d02371d0d8fdb28fad944bc0881943ba1deb4899bf57b11f9a4f3d1adb6a7546",
        "historical_gap_receipt_sha256=1d1d6cbd74aff12d48cfa250551430ec8e7a046075a8769438c93e974375996a",
        "historical_d1_pool_sha256=c6202648a73d0103b2ec43e393618ca31e67183c730a4df4db018eced2cfacd0",
        "historical_formal_pit=false",
        "historical_active_lane_authority=UNVERIFIED",
        "production_allowed=false",
        "buy_gate_updated=false",
        "orders_sent=false",
        "due_status=HISTORICAL_BACKFILL",
        "hk_d1_sha256=c6202648a73d0103b2ec43e393618ca31e67183c730a4df4db018eced2cfacd0",
        "hk_d1_binding_sha256=c6202648a73d0103b2ec43e393618ca31e67183c730a4df4db018eced2cfacd0",
        "hk_d1_membership=exact_date_top100",
    )
    rows = []
    for code in pool_codes:
        if code in _MISSING:
            continue
        is_zero_reference = code in _ZERO_VOLUME_REFERENCE
        rows.append(
            {
                "code": code,
                "name": code,
                "last_price": None if is_zero_reference else 11.0,
                "update_time": "2026-09-25 09:35:00" if code == "HK.02922" else None,
                "source_last_bar_time": "2026-09-25 09:32:00" if code == "HK.02922" else None,
                "window_start": "2026-09-25 09:31:00" if code == "HK.02922" else None,
                "window_end": "2026-09-25 09:35:00" if code == "HK.02922" else None,
                "bar_count": 5 if code == "HK.02922" else None,
                "prev_close_price": 10.0,
                "volume": 0.0 if is_zero_reference else 8000.0 if code == "HK.02922" else 100.0,
                "turnover": 123456.0 if code == "HK.02922" else None,
                "historical_turnover_unit": "HKD" if code == "HK.02922" else None,
                "volume_ratio": None,
                "turnover_rate": None,
                "platform_circular_market_cap_hkd_yi": None,
                "offer_float_market_cap_hkd_yi": None,
                "historical_source_id": "EASTMONEY_HK_HISTORICAL_1M",
                "historical_observation_contract": "HK_STAGE0930_RESEARCH_ONLY",
                "formal_pit_status": _RESEARCH_ROW_PIT_STATUS,
                "candidate_lanes": [],
            }
        )
    source = SourceResult(
        registry._HK_0930_RESEARCH_SOURCE_ID,
        "PARTIAL_WITH_ROWS",
        rows=tuple(rows),
        requested_rows=100,
        missing_symbols=_MISSING,
        source_evidence=evidence,
    )
    plan = SimpleNamespace(
        trade_date="20260925",
        stage_id="STAGE_0930_0935",
        codes_for=lambda market: pool_codes if market == "HK_CONNECT" else (),
    )
    raw = {
        "trade_date": "20260925",
        "stage_id": "STAGE_0930_0935",
        "market": "HK_CONNECT",
        "source_id": registry._HK_0930_RESEARCH_SOURCE_ID,
        "status": "PARTIAL_WITH_ROWS",
        "requested_rows": 100,
        "artifact_sha256": "a" * 64,
        "source_evidence": evidence,
    }
    return source, plan, raw


def test_hk_stage0930_historical_builder_uses_price_bar_time_but_keeps_window_amounts(monkeypatch):
    source, plan, raw = _contracted_case(monkeypatch)
    captured = {}

    def capture_selector(rows, *_args, **kwargs):
        captured["rows"] = tuple(rows)
        captured["kwargs"] = kwargs
        return {"rows": tuple(rows), "source_evidence": kwargs["source_evidence"]}

    monkeypatch.setattr(stage_selection, "select_hk_four_lane", capture_selector)
    envelope = production_selection_builders(plan.stage_id)["HK_CONNECT"](source, plan, raw)

    priced = next(row for row in envelope["rows"] if row["code"] == "HK.02922")
    zero = next(row for row in envelope["rows"] if row["code"] == "HK.01304")
    assert priced["update_time"] == "2026-09-25 09:32:00"
    assert priced["turnover"] == 123456.0
    assert zero["update_time"] is None
    assert zero["last_price"] is None
    source_price = next(row for row in source.rows if row["code"] == "HK.02922")
    assert source_price["update_time"] == source_price["window_end"] == "2026-09-25 09:35:00"
    assert source_price["volume"] == 8000.0
    assert source_price["turnover"] == 123456.0


def test_hk_stage0930_historical_research_selector_reuses_existing_four_lane_formula(monkeypatch):
    assert registry._HK_0930_D1_CODES_SHA256 == "07e8760a9c3171691d26a43240795c6b56e7a494fadb6acbd5f153b7801b7b34"
    source, plan, raw = _contracted_case(monkeypatch)

    envelope = production_selection_builders(plan.stage_id)["HK_CONNECT"](source, plan, raw)

    assert envelope["selection_status"] == "PARTIAL_WITH_ROWS"
    assert envelope["requested_rows"] == 100
    assert len(envelope["rows"]) == 10
    assert set(envelope["missing_symbols"]) == set(_MISSING)
    assert "hk_selection_mode=HK_STAGE0930_RESEARCH_ONLY" in envelope["source_evidence"]
    assert "historical_observation=WATCH_ONLY_NO_BUY" in envelope["source_evidence"]
    assert all(row["action_level"] == "NO_BUY" for row in envelope["rows"])
    assert not any("LIVE_HKCONNECT_GAINER" in row["candidate_lanes"] for row in envelope["rows"])


@pytest.mark.parametrize(
    ("violation", "expected_reason"),
    (
        ("wrong_date", "HK_0930_RESEARCH_DATE_MISMATCH"),
        ("wrong_stage", "HK_0930_RESEARCH_STAGE_MISMATCH"),
        ("zero_volume_price", "HK_0930_RESEARCH_ZERO_VOLUME_PRICE_USED_AS_SIGNAL"),
        ("volume_ratio", "HK_0930_RESEARCH_VOLUME_RATIO_MUST_REMAIN_UNKNOWN"),
        ("turnover_unit", "HK_0930_RESEARCH_TURNOVER_UNIT_MUST_BE_HKD"),
        ("unknown_amount", "HK_0930_RESEARCH_UNVERIFIED_TURNOVER_MUST_REMAIN_UNKNOWN"),
        ("missing_receipt", "HK_0930_RESEARCH_MARKER_MISSING:historical_gap_receipt_sha256"),
    ),
)
def test_hk_stage0930_historical_research_selector_fails_closed(monkeypatch, violation, expected_reason):
    source, plan, raw = _contracted_case(monkeypatch)
    rows = [dict(row) for row in source.rows]
    evidence = list(source.source_evidence)
    if violation == "wrong_date":
        plan.trade_date = "20260924"
    elif violation == "wrong_stage":
        plan.stage_id = "STAGE_0935_0940"
    elif violation == "zero_volume_price":
        next(row for row in rows if row["code"] == "HK.01304")["last_price"] = 128.1
    elif violation == "volume_ratio":
        rows[0]["volume_ratio"] = 0.0
    elif violation == "turnover_unit":
        rows[0]["turnover"] = 1.0
    elif violation == "unknown_amount":
        next(row for row in rows if row["code"] == "HK.02402")["turnover"] = 1.0
    elif violation == "missing_receipt":
        evidence.remove(
            "historical_gap_receipt_sha256=1d1d6cbd74aff12d48cfa250551430ec8e7a046075a8769438c93e974375996a"
        )
    source = SourceResult(
        source.source_id,
        source.status,
        rows=tuple(rows),
        requested_rows=source.requested_rows,
        missing_symbols=source.missing_symbols,
        source_evidence=tuple(evidence),
    )

    envelope = production_selection_builders(plan.stage_id)["HK_CONNECT"](source, plan, raw)

    assert envelope["selection_status"] == "CANNOT_CONFIRM"
    assert envelope["rows"] == []
    assert expected_reason in envelope["cannot_confirm"]


def _install_historical_pool_resolver(monkeypatch, root: Path, *, wrong_signal=False, wrong_sha=False):
    expected_sha = stage_runner._HK_0930_RESEARCH_D1_SHA256
    codes = tuple(f"HK.{10000 + index:05d}" for index in range(100))
    signal_date = "20260923" if wrong_signal else "20260924"
    artifact = {
        "schema_version": "v3_5.preselection_pool.v1",
        "trade_date": "20260925",
        "target_date": "20260925",
        "signal_date": signal_date,
        "pool_id": "hkconnect_d1_top100",
        "status": "STRICT_0_2_READY",
        "stage_selection_eligible": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
        "rows": [
            {"code": code, "target_date": "20260925", "signal_date": signal_date}
            for code in codes
        ],
    }
    artifact_sha = "e" * 64 if wrong_sha else expected_sha
    snapshot = {
        "artifact": artifact,
        "artifact_raw_sha256": artifact_sha,
        "pool_sha256": artifact_sha,
        "physical_source_root": str(root),
        "artifact_relative": "preselection_pools/20260925/hkconnect_d1_top100.json",
    }

    class FakeResolver:
        def __init__(self, resolver_root, *, source_root=None):
            self.root = Path(resolver_root)

        @contextmanager
        def source_read_lease(self, trade_date, *, timeout_seconds=10):
            yield

        def root_for_date(self, trade_date):
            return self.root

        def read_pool_snapshot(self, trade_date, pool_id):
            if trade_date != "20260925" or pool_id != "hkconnect_d1_top100":
                raise FileNotFoundError(trade_date)
            return snapshot

    monkeypatch.setattr(preselection_pool_store, "PreselectionSourceResolver", FakeResolver)
    monkeypatch.setattr(
        stage_runner,
        "_build_hk_d1_binding",
        lambda resolver_root, trade_date, *, preselection_source_root=None: StageUniverseBinding.ready(
            market="HK_CONNECT",
            trade_date=trade_date,
            role="HK_CONNECT_D1_TOP100",
            codes=codes,
            source_run_id="hk-d1-20260925-research-test",
            sha256=expected_sha,
            evidence=(
                f"hk_d1_json={root}/preselection_pools/20260925/hkconnect_d1_top100.json",
                f"hk_d1_sha256={expected_sha}",
                "hk_d1_membership=exact_date_top100",
            ),
        ),
    )
    return codes


def _run_test_binding_through_tick(monkeypatch, root: Path, **pool_options):
    _install_historical_pool_resolver(monkeypatch, root, **pool_options)

    def tick_body(
        _scope,
        _self,
        trade_date,
        _evaluated_at,
        *,
        stage_id,
        historical_backfill,
        historical_markets,
        _skip_precapture,
    ):
        assert historical_backfill is True
        assert historical_markets == ("HK_CONNECT",)
        assert stage_id == "STAGE_0930_0935"
        return stage_runner._build_hk_stage_binding(
            root, trade_date, preselection_source_root=root
        )

    monkeypatch.setattr(tick_planning, "_StageCenterRunner_tick_body", tick_body)
    return stage_runner.StageCenterRunner.tick(
        object(),
        "20260925",
        datetime.fromisoformat("2026-10-05T12:00:00+08:00"),
        stage_id="STAGE_0930_0935",
        historical_backfill=True,
        historical_markets=("HK_CONNECT",),
        historical_research_contract="HK_STAGE0930_RESEARCH_ONLY",
    )


def test_hk_stage0930_historical_binding_uses_only_exact_target_pool_under_explicit_tick_contract(monkeypatch, tmp_path):
    binding = _run_test_binding_through_tick(monkeypatch, tmp_path)

    assert binding.status == "READY"
    assert binding.sha256 == stage_runner._HK_0930_RESEARCH_D1_SHA256
    assert len(binding.codes) == 100
    assert "hk_research_contract=HK_STAGE0930_RESEARCH_ONLY" in binding.evidence
    assert "hk_d1_source_trade_date=20260925" in binding.evidence
    assert "hk_d1_source_signal_date=20260924" in binding.evidence
    assert "hk_d1_binding_mode=EXPLICIT_HK_STAGE0930_RESEARCH_TARGET_DATE" in binding.evidence


@pytest.mark.parametrize("pool_options", ({"wrong_signal": True}, {"wrong_sha": True}))
def test_hk_stage0930_historical_binding_rejects_wrong_signal_or_pool_sha(monkeypatch, tmp_path, pool_options):
    with pytest.raises(stage_runner.RunnerError, match="date, signal, or SHA mismatch"):
        _run_test_binding_through_tick(monkeypatch, tmp_path, **pool_options)


def test_hk_stage0930_binding_contract_rejects_non_historical_tick(monkeypatch):
    def unexpected_tick_body(*args, **kwargs):
        raise AssertionError("invalid research binding context reached tick execution")

    monkeypatch.setattr(tick_planning, "_StageCenterRunner_tick_body", unexpected_tick_body)
    with pytest.raises(stage_runner.RunnerError, match="binding context mismatch"):
        stage_runner.StageCenterRunner.tick(
            object(),
            "20260925",
            datetime.fromisoformat("2026-10-05T12:00:00+08:00"),
            stage_id="STAGE_0930_0935",
            historical_backfill=False,
            historical_markets=("HK_CONNECT",),
            historical_research_contract="HK_STAGE0930_RESEARCH_ONLY",
        )
