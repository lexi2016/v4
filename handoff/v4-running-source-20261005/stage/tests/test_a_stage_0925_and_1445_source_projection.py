from __future__ import annotations

import copy
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from domains.research import build_research_archive
from stage_center.live_collectors import collect_a_share_auction
from stage_center.research_context import (
    ResearchContextError,
    _apply_exact_v35_20260929_1400_role_warning_projection,
    _bound_source_rows,
    _payload_base_sha,
)


TRADE_DATE = "20260929"
SOURCE_SHA256 = "506c947cad54071a286853df20afc74e10bb544b2b639fea1ea7a443216bc3fc"
ARCHIVE_BASE_SHA256 = "16b41f40ba224d3adecd7682ec552dadd4869d2a56c2461b5456d122dfa3d5ac"
FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "a1445_projection_20260929"


class FrozenReplayProvider:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def snapshot(self, symbols, *, trade_date: str, stage_id: str, cutoff_at: str):
        assert tuple(symbols) == ("A.000001",)
        assert (trade_date, stage_id, cutoff_at) == (
            TRADE_DATE, "STAGE_0925", "2026-09-29T09:25:05",
        )
        return copy.deepcopy(self.payload)


def _auction_payload(captured_at: str, capture_mode: str = "NATURAL") -> dict:
    return {
        "schema_version": "v3_5.read_only_quote_batch.v1",
        "trade_date": TRADE_DATE,
        "stage_id": "STAGE_0925",
        "captured_at": captured_at,
        "market_cutoff_at": "2026-09-29T09:25:05",
        "capture_mode": capture_mode,
        "source": "PYTDX_A_SHARE_0925_HISTORY_TRANSACTION",
        "source_method": "pytdx.hq.get_history_transaction_data",
        "temporal_cutoff_safe": True,
        "rows": [{
            "symbol": "A.000001",
            "open_price": 10.5,
            "last_price": 10.5,
            "high_price": 10.5,
            "low_price": 10.5,
            "prev_close_price": 10.0,
            "turnover": 105000.0,
            "volume": 100.0,
            "source_tick_count": 1,
            "source_last_tick_time": "09:25:00",
            "source_method": "pytdx.hq.get_history_transaction_data",
        }],
        "cannot_confirm": [],
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _collect_auction(tmp_path: Path, captured_at: str):
    return collect_a_share_auction(
        SimpleNamespace(trade_date=TRADE_DATE, stage_id="STAGE_0925"),
        codes=("A.000001",),
        python_path=sys.executable,
        shared_root=tmp_path.resolve(),
        replay_provider=FrozenReplayProvider(_auction_payload(captured_at)),
    )


def _collect_payload(tmp_path: Path, payload: dict):
    return collect_a_share_auction(
        SimpleNamespace(trade_date=TRADE_DATE, stage_id="STAGE_0925"),
        codes=("A.000001",),
        python_path=sys.executable,
        shared_root=tmp_path.resolve(),
        replay_provider=FrozenReplayProvider(payload),
    )


@pytest.mark.parametrize(
    "captured_at",
    ("2026-09-29T09:25:03+08:00", "2026-09-29T01:25:03Z"),
)
def test_0925_collector_compares_aware_capture_to_shanghai_cutoff(
    tmp_path: Path, captured_at: str,
) -> None:
    result = _collect_auction(tmp_path, captured_at)

    assert result.status == "READY"
    assert len(result.rows) == 1
    assert result.rows[0]["update_time"] == "2026-09-29 09:25:00"
    assert not any("offset-naive" in item for item in result.cannot_confirm)


@pytest.mark.parametrize(
    "captured_at",
    ("2026-09-28T09:25:03+08:00", "2026-09-29T01:25:06Z"),
)
def test_0925_collector_still_rejects_wrong_date_and_capture_after_cutoff(
    tmp_path: Path, captured_at: str,
) -> None:
    result = _collect_auction(tmp_path, captured_at)

    assert result.status == "CANNOT_CONFIRM"
    assert not result.rows
    assert result.cannot_confirm == (
        "PYTDX_0925_REPLAY_ERROR:ValueError:replay captured_at is outside exact date/cutoff",
    )


def test_0925_collector_allows_exact_cutoff_recovery_and_marks_natural_unverified(
    tmp_path: Path,
) -> None:
    payload = _auction_payload("2026-09-29T11:49:03+08:00", capture_mode="RECOVERY")
    result = _collect_payload(tmp_path, payload)

    assert result.status == "READY"
    assert result.rows[0]["update_time"] == "2026-09-29 09:25:00"
    assert "replay_captured_at=2026-09-29T11:49:03+08:00" in result.source_evidence
    assert "replay_capture_mode=RECOVERY" in result.source_evidence
    assert "replay_market_cutoff_at=2026-09-29T09:25:05" in result.source_evidence
    assert "CANNOT_CONFIRM_NATURAL_0925_CAPTURE_RECOVERY_ONLY" in result.cannot_confirm


def test_0925_collector_rejects_recovery_without_exact_cutoff_or_0925_tick(
    tmp_path: Path,
) -> None:
    unbound_cutoff = _auction_payload("2026-09-29T11:49:03+08:00", capture_mode="RECOVERY")
    unbound_cutoff.pop("market_cutoff_at")
    assert _collect_payload(tmp_path, unbound_cutoff).status == "CANNOT_CONFIRM"

    wrong_cutoff = _auction_payload("2026-09-29T11:49:03+08:00", capture_mode="RECOVERY")
    wrong_cutoff["market_cutoff_at"] = "2026-09-29T09:25:06+08:00"
    assert _collect_payload(tmp_path, wrong_cutoff).status == "CANNOT_CONFIRM"

    wrong_tick = _auction_payload("2026-09-29T11:49:03+08:00", capture_mode="RECOVERY")
    wrong_tick["rows"][0]["source_last_tick_time"] = "09:24:00"
    result = _collect_payload(tmp_path, wrong_tick)
    assert result.status == "CANNOT_CONFIRM"
    assert not result.rows


def _archive_inputs() -> tuple[dict, dict, bytes, bytes]:
    source_bytes = (FIXTURE_ROOT / "source.json").read_bytes()
    archive_bytes = (FIXTURE_ROOT / "archive.json").read_bytes()
    assert hashlib.sha256(source_bytes).hexdigest() == SOURCE_SHA256
    source = json.loads(source_bytes)
    payload = json.loads(archive_bytes)
    assert _payload_base_sha(payload) == ARCHIVE_BASE_SHA256
    return source, payload, source_bytes, archive_bytes


def _witness_root(tmp_path: Path, source_bytes: bytes, source_sha256: str = SOURCE_SHA256) -> Path:
    root = tmp_path.resolve() / "data"
    witness = root / "research" / "hourly" / "source" / f"{source_sha256}.json"
    witness.parent.mkdir(parents=True)
    witness.write_bytes(source_bytes)
    return root


def _bound(
    root: Path,
    payload: dict,
    *,
    trade_date: str = TRADE_DATE,
    source_sha256: str = SOURCE_SHA256,
):
    return _bound_source_rows(
        root,
        payload=payload,
        paths={"source_input_sha256": source_sha256},
        trade_date=trade_date,
        slot="1400",
        cutoff=datetime.fromisoformat("2026-09-29T14:45:00+08:00"),
    )


def test_a1445_exact_source_and_archive_pair_projects_the_original_warning_fields(
    tmp_path: Path,
) -> None:
    _source, archive, source_bytes, _archive_bytes = _archive_inputs()
    root = _witness_root(tmp_path, source_bytes)

    projected_rows, evidence = _bound(root, archive)

    assert projected_rows is not None
    assert any(item == "v4_hourly_archive_projection_compat_warning_count=4" for item in evidence)
    assert any(
        item == "v4_hourly_archive_projection_compat_payload_base_sha256=" + ARCHIVE_BASE_SHA256
        for item in evidence
    )
    warnings = archive["cannot_confirm"]
    assert sum(item.startswith("REPORT_ROLE_EVIDENCE_EXCLUDED:") for item in warnings) == 4


def test_a1445_exact_source_pair_rejects_wrong_date_or_source_identity() -> None:
    source, archive, _source_bytes, _archive_bytes = _archive_inputs()
    projected = build_research_archive(copy.deepcopy(source), source_input_sha256=SOURCE_SHA256)

    with pytest.raises(ValueError, match="SOURCE_DATE_SLOT_MISMATCH"):
        _apply_exact_v35_20260929_1400_role_warning_projection(
            projected, source, archive, trade_date="20260928", slot="1400",
            source_input_sha256=SOURCE_SHA256,
        )

    wrong_source = copy.deepcopy(source)
    wrong_source["source_manifest"]["producer"] = "unregistered.producer"
    with pytest.raises(ValueError, match="SOURCE_IDENTITY_MISMATCH:producer"):
        _apply_exact_v35_20260929_1400_role_warning_projection(
            projected, wrong_source, archive, trade_date=TRADE_DATE, slot="1400",
            source_input_sha256=SOURCE_SHA256,
        )


def test_a1445_projection_is_idempotent_when_the_exact_warning_set_is_already_present() -> None:
    source, archive, _source_bytes, _archive_bytes = _archive_inputs()
    projected = build_research_archive(copy.deepcopy(source), source_input_sha256=SOURCE_SHA256)
    projected["cannot_confirm"] = list(archive["cannot_confirm"])

    compatible, evidence = _apply_exact_v35_20260929_1400_role_warning_projection(
        projected, source, archive, trade_date=TRADE_DATE, slot="1400",
        source_input_sha256=SOURCE_SHA256,
    )

    assert compatible == projected
    assert _payload_base_sha(compatible) == ARCHIVE_BASE_SHA256
    assert sum(
        item.startswith("REPORT_ROLE_EVIDENCE_EXCLUDED:")
        for item in compatible["cannot_confirm"]
    ) == 4
    assert "v4_hourly_archive_projection_compat_warning_count=4" in evidence


def test_a1445_source_and_archive_sha_mismatches_fail_closed(tmp_path: Path) -> None:
    _source, archive, source_bytes, _archive_bytes = _archive_inputs()
    wrong_source_sha = "0" * 64
    root = _witness_root(tmp_path, source_bytes, source_sha256=wrong_source_sha)
    with pytest.raises(ResearchContextError, match="SOURCE_WITNESS_SHA_MISMATCH"):
        _bound(root, archive, source_sha256=wrong_source_sha)

    root = _witness_root(tmp_path / "archive-tamper", source_bytes)
    altered_archive = copy.deepcopy(archive)
    altered_archive["cannot_confirm"].append("REPORT_ROLE_EVIDENCE_EXCLUDED:999999")
    with pytest.raises(ResearchContextError, match="ARCHIVE_BASE_SHA_MISMATCH"):
        _bound(root, altered_archive)
