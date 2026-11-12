from __future__ import annotations

import json
import hashlib
import shutil
import sys
from datetime import datetime
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import pytest

import stage_center.hk_universe_preflight as hk_preflight
from stage_center.hk_universe_preflight import (
    ensure_hk_connect_universe,
    recover_hk_connect_universe,
)
from stage_center.runner import _validate_hk_full_universe


SHARED_PACKAGE_ROOT = Path(__file__).parents[1] / "upstreams" / "v3_shared_data"


TRADE_DATE = "20260828"
NOW = datetime(2026, 8, 28, 12, tzinfo=ZoneInfo("Asia/Shanghai"))
RECOVERY_NOW = datetime(2026, 8, 29, 12, tzinfo=ZoneInfo("Asia/Shanghai"))
PLATES = ("HK.GangGuTong", "HK.LIST1922")


class _Frame:
    def __init__(self, rows: list[dict[str, str]]) -> None:
        self.rows = rows

    def to_dict(self, *, orient: str) -> list[dict[str, str]]:
        assert orient == "records"
        return list(self.rows)


class _QuoteContext:
    def __init__(self, rows_by_plate: dict[str, list[dict[str, str]]]) -> None:
        self.rows_by_plate = rows_by_plate
        self.closed = False

    def get_plate_stock(self, plate: str) -> tuple[int, _Frame]:
        return 0, _Frame(self.rows_by_plate[plate])

    def close(self) -> None:
        self.closed = True


def _codes(count: int) -> list[str]:
    return [f"HK.{number:05d}" for number in range(1, count + 1)]


def _rows(codes: list[str]) -> list[dict[str, str]]:
    return [{"code": code} for code in codes]


def _resolve_stage_universe(root: Path, trade_date: str = TRADE_DATE):
    from stage_center.live_collectors import _load_shared_module

    module = _load_shared_module(SHARED_PACKAGE_ROOT, "scripts.live_acquisition.universe")
    module_file = Path(str(module.__file__)).resolve()
    module_file.relative_to(SHARED_PACKAGE_ROOT.resolve())
    return module.resolve_stage_universe(root, trade_date, "HK_CONNECT")


def _ensure(tmp_path: Path, count: int = 652, *, rows: list[dict[str, str]] | None = None) -> Path:
    codes = _codes(count)
    plate_rows = rows if rows is not None else _rows(codes)

    def factory() -> _QuoteContext:
        return _QuoteContext({plate: list(plate_rows) for plate in PLATES})

    ensure_hk_connect_universe(
        tmp_path,
        TRADE_DATE,
        now=NOW,
        quote_context_factory=factory,
    )
    return tmp_path


@pytest.mark.parametrize("count", (651, 652, 653))
def test_futu_authority_uses_dynamic_union_count(tmp_path: Path, count: int) -> None:
    root = _ensure(tmp_path, count)

    resolved = _resolve_stage_universe(root)

    assert len(resolved.codes) == count
    assert resolved.codes_sha256


def test_runner_reuses_strict_verified_authority_for_dynamic_652(tmp_path: Path) -> None:
    root = _ensure(tmp_path, 652)

    path, codes, artifact_sha = _validate_hk_full_universe(root, TRADE_DATE)

    assert path == root / "universes" / TRADE_DATE / "HK_CONNECT_FULL_MARKET.json"
    assert len(codes) == 652
    assert artifact_sha


def test_runner_uses_bundled_reader_when_alternate_module_is_cached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from stage_center import live_collectors

    root = _ensure(tmp_path, 652)
    fake_scripts = ModuleType("scripts")
    fake_scripts.__path__ = []
    fake_live_acquisition = ModuleType("scripts.live_acquisition")
    fake_live_acquisition.__path__ = []
    fake_universe = ModuleType("scripts.live_acquisition.universe")
    fake_universe.__file__ = str(tmp_path / "alternate" / "universe.py")

    def fake_resolve(*_args: Any, **_kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(
            path=root / "universes" / TRADE_DATE / "HK_CONNECT_FULL_MARKET.json",
            codes=("HK.FAKE",),
        )

    fake_universe.resolve_stage_universe = fake_resolve
    monkeypatch.setitem(sys.modules, "scripts", fake_scripts)
    monkeypatch.setitem(sys.modules, "scripts.live_acquisition", fake_live_acquisition)
    monkeypatch.setitem(sys.modules, "scripts.live_acquisition.universe", fake_universe)

    loaded: dict[str, Path] = {}
    original_loader = live_collectors._load_shared_module

    def capture_loader(shared_root: Path, module_name: str) -> Any:
        module = original_loader(shared_root, module_name)
        loaded["module_file"] = Path(str(module.__file__)).resolve()
        return module

    monkeypatch.setattr(live_collectors, "_load_shared_module", capture_loader)

    _path, codes, _artifact_sha = _validate_hk_full_universe(root, TRADE_DATE)

    assert len(codes) == 652
    loaded["module_file"].relative_to(SHARED_PACKAGE_ROOT.resolve())
    assert sys.modules["scripts"] is fake_scripts
    assert sys.modules["scripts.live_acquisition"] is fake_live_acquisition
    assert sys.modules["scripts.live_acquisition.universe"] is fake_universe


@pytest.mark.parametrize(
    "rows",
    (
        _rows(_codes(599)),
        _rows(_codes(651)) + [{"code": "HK.00001"}],
        _rows(_codes(651)) + [{"code": "HK.BAD"}],
    ),
    ids=("below_minimum", "duplicate", "invalid_code"),
)
def test_futu_source_rows_fail_closed(tmp_path: Path, rows: list[dict[str, str]]) -> None:
    with pytest.raises(ValueError):
        _ensure(tmp_path, rows=rows)


def _read_line(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_line(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def _authority_paths(root: Path) -> dict[str, Path]:
    current_path = root / "universes" / TRADE_DATE / "HK_CONNECT_FULL_MARKET.current.json"
    current = _read_line(current_path)
    return {
        "artifact": root / current["artifact_relative"],
        "manifest": root / current["manifest_relative"],
        "receipt": root / current["receipt_relative"],
        "current": current_path,
    }


PARENT_TRADE_DATE = "20260827"
PARENT_NOW = datetime(2026, 8, 27, 12, tzinfo=ZoneInfo("Asia/Shanghai"))
RECOVERY_NOTICE_DATE = "20260826"
RECOVERY_EVIDENCE_URL = "https://www.sse.com.cn/disclosure/notice/20260826-hk-connect.pdf"
RECOVERY_DELTA_CODE = "HK.03308"


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manual_recovery_fixture(
    tmp_path: Path,
    *,
    parent_artifact_sha256: str | None = None,
    parent_codes_sha256: str | None = None,
    delta_codes: tuple[str, ...] = (RECOVERY_DELTA_CODE,),
    plate_codes: dict[str, list[str]] | None = None,
    evidence_sha256: str | None = None,
    evidence_url: str = RECOVERY_EVIDENCE_URL,
    evidence_claim_url: str | None = None,
    notice_date: str = RECOVERY_NOTICE_DATE,
    evidence_claim_notice_date: str | None = None,
    effective_date: str = TRADE_DATE,
    evidence_claim_effective_date: str | None = None,
    now: datetime = NOW,
) -> Path:
    parent_codes = _codes(651)
    parent_rows = _rows(parent_codes)
    ensure_hk_connect_universe(
        tmp_path,
        PARENT_TRADE_DATE,
        now=PARENT_NOW,
        quote_context_factory=lambda: _QuoteContext(
            {plate: list(parent_rows) for plate in PLATES}
        ),
    )
    parent_artifact = tmp_path / "universes" / PARENT_TRADE_DATE / "HK_CONNECT_FULL_MARKET.json"
    parent_payload = _read_line(parent_artifact)
    target_codes = sorted(set(parent_codes).union(delta_codes))
    if plate_codes is None:
        plate_codes = {plate: list(target_codes) for plate in PLATES}
    evidence_path = tmp_path / "official-evidence.json"
    evidence_payload = {
        "official_url": evidence_claim_url or evidence_url,
        "notice_date": evidence_claim_notice_date or notice_date,
        "effective_date": evidence_claim_effective_date or effective_date,
        "added_codes": list(delta_codes),
        "fact": "official membership addition takes effect on the next HK Connect trading day",
    }
    evidence_path.write_text(
        json.dumps(evidence_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    rows_by_plate = {plate: _rows(values) for plate, values in plate_codes.items()}
    recover_hk_connect_universe(
        tmp_path,
        TRADE_DATE,
        parent_trade_date=PARENT_TRADE_DATE,
        parent_artifact_sha256=parent_artifact_sha256 or _sha256_file(parent_artifact),
        parent_codes_sha256=parent_codes_sha256 or str(parent_payload["codes_sha256"]),
        official_evidence_path=evidence_path,
        official_evidence_sha256=evidence_sha256 or _sha256_file(evidence_path),
        official_evidence_url=evidence_url,
        notice_date=notice_date,
        effective_date=effective_date,
        delta_codes=delta_codes,
        now=now,
        quote_context_factory=lambda: _QuoteContext(rows_by_plate),
    )
    return tmp_path


def test_manual_recovery_accepts_parent_delta_and_equal_current_plates(tmp_path: Path) -> None:
    root = _manual_recovery_fixture(tmp_path)

    resolved = _resolve_stage_universe(root)
    current = _read_line(_authority_paths(root)["current"])
    lineage = current["recovery_lineage"]

    assert len(resolved.codes) == 652
    assert current["source_materialization"] == "MANUAL_RECOVERY"
    assert current["natural_verified"] is False
    assert lineage["parent"]["trade_date"] == PARENT_TRADE_DATE
    parent_payload = _read_line(
        root / "universes" / PARENT_TRADE_DATE / "HK_CONNECT_FULL_MARKET.json"
    )
    assert lineage["parent"]["codes_sha256"] == parent_payload["codes_sha256"]
    assert lineage["official_evidence"]["delta_codes"] == [RECOVERY_DELTA_CODE]
    assert lineage["plate_capture"]["captured_at"] == NOW.isoformat(timespec="seconds")
    assert lineage["natural_verified"] is False


def test_manual_recovery_allows_corroboration_after_target_date(tmp_path: Path) -> None:
    root = _manual_recovery_fixture(tmp_path, now=RECOVERY_NOW)

    resolved = _resolve_stage_universe(root)
    current = _read_line(_authority_paths(root)["current"])

    assert len(resolved.codes) == 652
    assert current["trade_date"] == TRADE_DATE
    assert current["captured_at"] == RECOVERY_NOW.isoformat(timespec="seconds")
    assert current["recovered_at"] == RECOVERY_NOW.isoformat(timespec="seconds")
    assert current["corroborated_at"] == RECOVERY_NOW.isoformat(timespec="seconds")


def test_manual_recovery_evidence_is_store_relative_and_portable(tmp_path: Path) -> None:
    root = _manual_recovery_fixture(tmp_path)
    current = _read_line(_authority_paths(root)["current"])
    evidence_relative = current["recovery_lineage"]["official_evidence"]["path"]

    assert not Path(evidence_relative).is_absolute()
    assert (root / evidence_relative).is_file()
    (root / "official-evidence.json").unlink()

    relocated = tmp_path.parent / "relocated-authority-root"
    shutil.copytree(root, relocated)
    resolved = _resolve_stage_universe(relocated)

    assert len(resolved.codes) == 652


@pytest.mark.parametrize(
    "chain_file",
    ("manifest.json", "receipt.json", "HK_CONNECT_FULL_MARKET.current.json"),
    ids=("manifest", "receipt", "current"),
)
def test_manual_recovery_retries_after_one_chain_write_failure(
    tmp_path: Path, chain_file: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = hk_preflight._atomic_create_bytes
    failed = False

    def fail_once(path: Path, encoded: bytes) -> bool:
        nonlocal failed
        if (
            not failed
            and path.name == chain_file
            and f"/universes/{TRADE_DATE}/" in path.as_posix()
        ):
            failed = True
            raise OSError(f"injected one-shot failure: {chain_file}")
        return original(path, encoded)

    monkeypatch.setattr(hk_preflight, "_atomic_create_bytes", fail_once)
    with pytest.raises(OSError, match="injected one-shot failure"):
        _manual_recovery_fixture(tmp_path)
    assert failed is True
    with pytest.raises(ValueError):
        _resolve_stage_universe(tmp_path)

    monkeypatch.setattr(hk_preflight, "_atomic_create_bytes", original)
    _manual_recovery_fixture(tmp_path, now=RECOVERY_NOW)
    assert len(_resolve_stage_universe(tmp_path).codes) == 652


def test_manual_recovery_rejects_conflicting_chain_bytes(tmp_path: Path) -> None:
    root = _manual_recovery_fixture(tmp_path)
    paths = _authority_paths(root)
    manifest = _read_line(paths["manifest"])
    manifest["status"] = "CONFLICT"
    _write_line(paths["manifest"], manifest)
    conflicting_bytes = paths["manifest"].read_bytes()

    with pytest.raises(ValueError, match="authority chain conflict"):
        _manual_recovery_fixture(root)

    assert paths["manifest"].read_bytes() == conflicting_bytes


def test_manual_recovery_requires_parent_before_target(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="earlier"):
        recover_hk_connect_universe(
            tmp_path,
            TRADE_DATE,
            parent_trade_date="20260829",
            parent_artifact_sha256="a" * 64,
            parent_codes_sha256="b" * 64,
            official_evidence_path=tmp_path / "missing-evidence.json",
            official_evidence_sha256="c" * 64,
            official_evidence_url=RECOVERY_EVIDENCE_URL,
            notice_date=RECOVERY_NOTICE_DATE,
            effective_date=TRADE_DATE,
            delta_codes=[RECOVERY_DELTA_CODE],
        )


def test_manual_recovery_cli_forwards_explicit_audit_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    captured: dict[str, Any] = {}

    def fake_recover(*args: Any, **kwargs: Any) -> dict[str, Any]:
        captured["args"] = args
        captured["kwargs"] = kwargs
        return {
            "ok": True,
            "source_materialization": "MANUAL_RECOVERY",
            "natural_verified": False,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }

    monkeypatch.setattr(hk_preflight, "recover_hk_connect_universe", fake_recover)
    evidence_path = tmp_path / "official-evidence.json"
    result = hk_preflight.main(
        [
            "--store-root",
            str(tmp_path / "store"),
            "--trade-date",
            "20260828",
            "--parent-trade-date",
            "20260827",
            "--parent-artifact-sha256",
            "a" * 64,
            "--parent-codes-sha256",
            "b" * 64,
            "--official-evidence-path",
            str(evidence_path),
            "--official-evidence-sha256",
            "c" * 64,
            "--official-evidence-url",
            RECOVERY_EVIDENCE_URL,
            "--notice-date",
            "20260826",
            "--effective-date",
            "20260828",
            "--delta-code",
            RECOVERY_DELTA_CODE,
        ]
    )

    assert result == 0
    assert captured["args"] == (tmp_path / "store", "20260828")
    assert captured["kwargs"]["parent_trade_date"] == "20260827"
    assert captured["kwargs"]["delta_codes"] == [RECOVERY_DELTA_CODE]
    assert json.loads(capsys.readouterr().out)["natural_verified"] is False


@pytest.mark.parametrize(
    "kwargs",
    (
        {"parent_artifact_sha256": "0" * 64},
        {"parent_codes_sha256": "0" * 64},
    ),
    ids=("parent_artifact_sha", "parent_codes_sha"),
)
def test_manual_recovery_rejects_wrong_parent_binding(tmp_path: Path, kwargs: dict[str, str]) -> None:
    with pytest.raises(ValueError):
        _manual_recovery_fixture(tmp_path, **kwargs)


@pytest.mark.parametrize(
    "delta_codes",
    ((), (RECOVERY_DELTA_CODE, "HK.03309")),
    ids=("missing_delta", "multiple_delta"),
)
def test_manual_recovery_requires_one_explicit_delta(tmp_path: Path, delta_codes: tuple[str, ...]) -> None:
    with pytest.raises(ValueError):
        _manual_recovery_fixture(tmp_path, delta_codes=delta_codes)


@pytest.mark.parametrize("plate_case", ("unequal", "extra", "removed"))
def test_manual_recovery_requires_equal_parent_plus_delta_plates(
    tmp_path: Path, plate_case: str
) -> None:
    target_codes = _codes(651) + [RECOVERY_DELTA_CODE]
    if plate_case == "unequal":
        plate_codes = {PLATES[0]: list(target_codes), PLATES[1]: list(target_codes[:-1])}
    elif plate_case == "extra":
        plate_codes = {PLATES[0]: list(target_codes) + ["HK.99999"], PLATES[1]: list(target_codes)}
    else:
        plate_codes = {plate: _codes(651) for plate in PLATES}
    with pytest.raises(ValueError):
        _manual_recovery_fixture(tmp_path, plate_codes=plate_codes)


@pytest.mark.parametrize(
    "kwargs",
    (
        {"evidence_sha256": "0" * 64},
        {"evidence_url": "https://www.sse.com.cn/right-url", "evidence_claim_url": RECOVERY_EVIDENCE_URL},
        {"notice_date": "20260825", "evidence_claim_notice_date": RECOVERY_NOTICE_DATE},
        {"effective_date": "20260829", "evidence_claim_effective_date": TRADE_DATE},
    ),
    ids=("evidence_sha", "evidence_url", "notice_date", "effective_date"),
)
def test_manual_recovery_rejects_official_evidence_mismatch(
    tmp_path: Path, kwargs: dict[str, str]
) -> None:
    with pytest.raises(ValueError):
        _manual_recovery_fixture(tmp_path, **kwargs)


@pytest.mark.parametrize(
    "mutation",
    ("natural_verified", "current_lineage", "receipt_lineage", "evidence_file"),
)
def test_manual_recovery_rejects_tampered_lineage_and_evidence(
    tmp_path: Path, mutation: str
) -> None:
    root = _manual_recovery_fixture(tmp_path)
    paths = _authority_paths(root)
    if mutation == "natural_verified":
        current = _read_line(paths["current"])
        current["natural_verified"] = True
        _write_line(paths["current"], current)
    elif mutation == "current_lineage":
        current = _read_line(paths["current"])
        current["recovery_lineage"]["parent"]["codes_sha256"] = "0" * 64
        _write_line(paths["current"], current)
    elif mutation == "receipt_lineage":
        receipt = _read_line(paths["receipt"])
        receipt["recovery_lineage"]["official_evidence"]["delta_codes"] = ["HK.03309"]
        _write_line(paths["receipt"], receipt)
    else:
        evidence_relative = _read_line(paths["current"])["recovery_lineage"]["official_evidence"]["path"]
        evidence_path = root / evidence_relative
        evidence_path.write_text(evidence_path.read_text(encoding="utf-8") + "tampered", encoding="utf-8")
    with pytest.raises(ValueError):
        _resolve_stage_universe(root)


@pytest.mark.parametrize(
    "mutation",
    (
        "missing_plate",
        "extra_plate",
        "plate_union",
        "count",
        "codes_sha",
        "source_sha",
        "artifact_sha",
        "manifest_sha",
        "receipt_sha",
        "date",
        "run",
        "current_path",
    ),
)
def test_verified_authority_rejects_chain_tampering(tmp_path: Path, mutation: str) -> None:
    root = _ensure(tmp_path)
    paths = _authority_paths(root)
    artifact = _read_line(paths["artifact"])
    current = _read_line(paths["current"])

    if mutation == "missing_plate":
        del artifact["plate_codes"]["HK.LIST1922"]
        _write_line(paths["artifact"], artifact)
    elif mutation == "extra_plate":
        artifact["plate_codes"]["HK.EXTRA"] = list(artifact["plate_codes"][PLATES[0]])
        _write_line(paths["artifact"], artifact)
    elif mutation == "plate_union":
        artifact["plate_codes"][PLATES[0]] = artifact["plate_codes"][PLATES[0]][:-1]
        artifact["plate_codes"][PLATES[1]] = artifact["plate_codes"][PLATES[1]][:-1]
        _write_line(paths["artifact"], artifact)
    elif mutation == "count":
        artifact["code_count"] -= 1
        _write_line(paths["artifact"], artifact)
    elif mutation == "codes_sha":
        artifact["codes_sha256"] = "0" * 64
        _write_line(paths["artifact"], artifact)
    elif mutation == "source_sha":
        artifact["source_sha256"] = "0" * 64
        _write_line(paths["artifact"], artifact)
    elif mutation == "artifact_sha":
        current["artifact_sha256"] = "0" * 64
        _write_line(paths["current"], current)
    elif mutation == "manifest_sha":
        current["manifest_sha256"] = "0" * 64
        _write_line(paths["current"], current)
    elif mutation == "receipt_sha":
        current["receipt_sha256"] = "0" * 64
        _write_line(paths["current"], current)
    elif mutation == "date":
        current["trade_date"] = "20260829"
        _write_line(paths["current"], current)
    elif mutation == "run":
        current["run_id"] = "0" * 24
        _write_line(paths["current"], current)
    elif mutation == "current_path":
        current["current_relative"] = "universes/20260828/wrong-current.json"
        _write_line(paths["current"], current)
    else:  # pragma: no cover - parametrization guards this branch
        raise AssertionError(mutation)

    with pytest.raises(ValueError):
        _resolve_stage_universe(root)
