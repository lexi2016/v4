from __future__ import annotations

import hashlib
import inspect
import json
import importlib
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

import pytest
from fastapi.testclient import TestClient

from ops import run_hk_morning_selection_recovery_20261016 as recovery
from stage_center.consumer import StageSelectionConsumer
from stage_center.selection import SelectionStore


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree_sha(path: Path) -> str:
    digest = hashlib.sha256()
    if not path.exists():
        return "ABSENT"
    for item in sorted(path.rglob("*")):
        if item.is_file():
            digest.update(item.relative_to(path).as_posix().encode("utf-8"))
            digest.update(b"\0")
            digest.update(hashlib.sha256(item.read_bytes()).digest())
    return digest.hexdigest()


def _selection_rows(stage_id: str, *, score_shift: int = 0) -> list[dict[str, Any]]:
    cutoff_by_stage = {
        "STAGE_0930_0935": "09:35:00",
        "STAGE_0935_0940": "09:40:00",
        "STAGE_0940_0945": "09:45:00",
        "STAGE_0945_1030": "10:30:00",
    }
    return [
        {
            "code": f"HK.{index:05d}",
            "score": 70 - index + score_shift,
            "rank": index,
            "status": "WATCH_ONLY" if index == 1 else "NO_TRADE",
            "formal_eligible": False,
            "support": 10.0,
            "pressure": 12.0,
            "invalidation": 9.0,
            "source_mode": "HK_CONNECT_FOUR_LANE",
            "lane_evidence": ["candidate_bucket=FOUR_LANE_OBSERVATION"],
            "action_level": "NO_BUY",
            "trade_status": "WATCH_ONLY" if index == 1 else "NO_TRADE",
            "trade_status_contract": "WATCH_ONLY",
            "name": f"Observation {index}",
            "stock_name": f"Observation {index}",
            "source_last_bar_time": f"2026-10-16 {cutoff_by_stage[stage_id]}",
            "current_change_pct": float(index) / 10,
            "open_price": 10.0,
            "last_price": 11.0,
            "high_price": 12.0,
            "low_price": 9.0,
            "support_primary_price": 10.0,
            "pressure_price": 12.0,
            "invalidation_price": 9.0,
        }
        for index in range(1, 11)
    ]


@pytest.fixture
def source_bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    selection_root = tmp_path / "source" / "stage" / "selection"
    raw_root = tmp_path / "source" / "stage" / "raw"
    capture_root = raw_root / ".futu_minute_captures" / recovery.TRADE_DATE
    active_state_root = tmp_path / "active-state"
    selection_root.mkdir(parents=True)
    raw_root.mkdir(parents=True)
    capture_root.mkdir(parents=True)
    active_state_root.mkdir()

    codes = [f"HK.{index:05d}" for index in range(1, 101)]
    d1_pool_path = tmp_path / "d1-pool.json"
    d1_pool_path.write_text(
        json.dumps({"rows": [{"code_norm": code} for code in codes]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        recovery,
        "_validate_d1_pool",
        lambda path, expected: {
            "sha256": recovery.D1_POOL_SHA256,
            "source_sha256": recovery.D1_SOURCE_SHA256,
            "code_set_sha256": recovery.D1_CODE_SET_SHA256,
        },
    )

    cutoff_by_stage = {
        "STAGE_0930_0935": ("09:35:00", "2026-10-16T09:36:10+08:00"),
        "STAGE_0935_0940": ("09:40:00", "2026-10-16T09:41:11+08:00"),
        "STAGE_0940_0945": ("09:45:00", "2026-10-16T09:46:10+08:00"),
        "STAGE_0945_1030": ("10:30:00", "2026-10-16T10:31:08+08:00"),
    }
    pins: list[recovery.StagePin] = []
    originals: dict[str, dict[str, Any]] = {}
    raw_pins: dict[str, dict[str, Any]] = {}
    for index, (stage_id, (cutoff, captured_at)) in enumerate(cutoff_by_stage.items(), 1):
        capture_sha256 = hashlib.sha256(f"capture:{stage_id}".encode()).hexdigest()
        raw_sha256 = hashlib.sha256(f"raw:{stage_id}".encode()).hexdigest()
        raw_run_id = f"raw-run-test-{index}"
        source_evidence = [
            "route=shared_futu_hkconnect_minute",
            f"futu_capture_sha256={capture_sha256}",
            f"futu_captured_at={captured_at}",
            f"active_snapshot_codes_sha256={recovery.D1_CODE_SET_SHA256}",
            f"active_snapshot_expected_pool_artifact_sha256={recovery.D1_POOL_SHA256}",
            f"hk_d1_sha256={recovery.D1_POOL_SHA256}",
            f"hk_d1_source_sha256={recovery.D1_SOURCE_SHA256}",
            "HK_ACTIVE_SNAPSHOT_UNAVAILABLE",
        ]
        envelope = {
            "schema_version": "stage_center.selection.v2",
            "trade_date": recovery.TRADE_DATE,
            "stage_id": stage_id,
            "market": recovery.MARKET,
            "algorithm_id": recovery.ALGORITHM_ID,
            "algorithm_sha256": recovery.ALGORITHM_SHA256,
            "raw_artifact_sha256": raw_sha256,
            "source_status": "CANNOT_CONFIRM",
            "selection_status": "PARTIAL_WITH_ROWS",
            "requested_rows": 100,
            "source_rows": 100,
            "selected_rows": 10,
            "coverage_ratio": 0.1,
            "missing_symbols": [],
            "rows": _selection_rows(stage_id),
            "source_evidence": source_evidence,
            "cannot_confirm": ["HK_ACTIVE_SNAPSHOT_UNAVAILABLE"],
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
        store = SelectionStore(selection_root)
        published = store.publish(envelope, market=recovery.MARKET)
        verified = store._verify_run(
            recovery.TRADE_DATE, stage_id, recovery.MARKET, published["run_id"]
        )
        run_dir = (
            selection_root
            / "selection_runs"
            / recovery.TRADE_DATE
            / f"HK_CONNECT_SELECTION_{stage_id}"
            / published["run_id"]
        )
        pins.append(
            recovery.StagePin(
                stage_id=stage_id,
                cutoff_time=cutoff,
                backfill_run_id=f"test-hk-morning-20261016-{index}",
                original_run_id=published["run_id"],
                original_artifact_id=published["artifact_id"],
                original_selection_artifact_sha256=verified["artifact_sha256"],
                original_selection_manifest_sha256=_sha(run_dir / "manifest.json"),
                original_selection_receipt_sha256=_sha(run_dir / "receipt.json"),
                original_selection_manifest_canonical_sha256=verified["manifest_sha256"],
                original_selection_receipt_canonical_sha256=verified["receipt_sha256"],
                original_raw_artifact_sha256=raw_sha256,
                original_raw_run_id=raw_run_id,
                capture_sha256=capture_sha256,
                captured_at=captured_at,
                capture_row_count=100,
                raw_row_count=100,
            )
        )
        originals[stage_id] = verified["envelope"]
        raw_pins[stage_id] = {
            "codes": set(codes),
            "raw_run_id": raw_run_id,
            "raw_manifest_sha256": hashlib.sha256(f"raw manifest:{stage_id}".encode()).hexdigest(),
            "raw_receipt_sha256": hashlib.sha256(f"raw receipt:{stage_id}".encode()).hexdigest(),
            "raw_artifact_sha256": raw_sha256,
        }

    def fake_raw_codes(_raw_root: Path, pin: recovery.StagePin) -> dict[str, Any]:
        return dict(raw_pins[pin.stage_id])

    def fake_capture(_capture_root: Path, pin: recovery.StagePin, expected_codes: set[str]) -> dict[str, Any]:
        return {
            "capture_path": f"/private/tmp/{pin.stage_id}.json",
            "capture_sha256": pin.capture_sha256,
            "captured_at": pin.captured_at,
            "stage_cutoff_at": f"2026-10-16T{pin.cutoff_time}+08:00",
            "capture_after_target_cutoff": True,
            "capture_row_count": pin.capture_row_count,
            "code_set_sha256": recovery.D1_CODE_SET_SHA256,
        }

    monkeypatch.setattr(recovery, "_raw_codes", fake_raw_codes)
    monkeypatch.setattr(recovery, "_validate_capture", fake_capture)
    return {
        "tmp_path": tmp_path,
        "selection_root": selection_root,
        "raw_root": raw_root,
        "capture_root": capture_root,
        "d1_pool_path": d1_pool_path,
        "active_state_root": active_state_root,
        "pins": tuple(pins),
        "codes": set(codes),
        "originals": originals,
    }


def _copy_candidate_backfills(output_root: Path, selection_root: Path) -> None:
    for source in (output_root / "selection" / "backfill").iterdir():
        destination = selection_root / "backfill" / source.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, destination)
    source_receipts = output_root / "receipts" / "backfill"
    destination_receipts = selection_root.parent / "receipts" / "backfill"
    destination_receipts.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_receipts, destination_receipts)


def _install_api_bindings(
    monkeypatch: pytest.MonkeyPatch, receipt: dict[str, Any]
) -> None:
    from apps.api.v35_api import app as api_module

    for stage_id, binding in receipt["stages"].items():
        original = binding["original"]
        api_binding = {
            **binding,
            "original_manifest_sha256": original["original_selection_manifest_canonical_sha256"],
            "original_receipt_sha256": original["original_selection_receipt_canonical_sha256"],
        }
        monkeypatch.setitem(
            api_module._HK_MORNING_SELECTION_RECOVERY_BINDING_BY_DATE_STAGE,
            (recovery.TRADE_DATE, stage_id),
            api_binding,
        )
        monkeypatch.setitem(
            api_module._APPROVED_EXACT_STAGE_BACKFILLS,
            (
                recovery.TRADE_DATE,
                stage_id,
                recovery.MARKET,
                binding["backfill_run_id"],
            ),
            {
                key: binding[key]
                for key in (
                    "selection_run_id",
                    "artifact_id",
                    "raw_artifact_sha256",
                    "algorithm_id",
                    "algorithm_sha256",
                    "selection_status",
                    "source_status",
                    "requested_rows",
                    "source_rows",
                    "selected_rows",
                    "missing_rows",
                    "missing_codes",
                    "cannot_confirm_count",
                    "selection_manifest_sha256",
                    "selection_receipt_sha256",
                    "selection_artifact_sha256",
                    "runner_receipt_sha256",
                    "source_evidence_sha256",
                    "required_evidence",
                )
            },
        )


def _api_client(selection_root: Path, data_root: Path) -> TestClient:
    from apps.api.v35_api.app import create_app

    return TestClient(
        create_app(
            data_root=data_root,
            stage_center_selection_root=selection_root,
            current_date=recovery.TRADE_DATE,
        )
    )


def _run_actual_frontend_stage_validator(
    payloads: list[dict[str, Any]], output_root: Path
) -> None:
    api_module = importlib.import_module("apps.api.v35_api.app")
    application_root = Path(api_module.__file__).resolve().parents[3]
    frontend_source = application_root / "apps" / "web" / "src" / "api" / "pool_stage.ts"
    repository_root = Path(__file__).resolve().parents[1]
    esbuild = repository_root / "apps" / "web" / "node_modules" / ".bin" / "esbuild"
    node = shutil.which("node")
    assert frontend_source.is_file()
    assert esbuild.is_file()
    assert node is not None

    output_root.mkdir(parents=True)
    bundle_path = output_root / "pool_stage_validator.mjs"
    payload_path = output_root / "stage_payloads.json"
    script_path = output_root / "validate_payloads.mjs"
    payload_path.write_text(json.dumps(payloads, ensure_ascii=False), encoding="utf-8")
    script_path.write_text(
        """import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';

const { loadStageSnapshot } = await import(pathToFileURL(process.argv[2]).href);
const cases = JSON.parse(await readFile(process.argv[3], 'utf8'));
for (const item of cases) {
  const validate = async (payload) => {
    globalThis.fetch = async (url) => {
      const parsed = new URL(url, 'http://localhost');
      assert.equal(parsed.pathname, '/api/v3/workbench/stage');
      assert.equal(parsed.searchParams.get('limit'), '50');
      return new Response(JSON.stringify(payload), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      });
    };
    return loadStageSnapshot(item.date, item.stage_id);
  };

  const accepted = await validate(item.payload);
  assert.equal(accepted.selection_markets.HK_CONNECT.trade_date, item.date);
  assert.equal(accepted.selection_markets.HK_CONNECT.stage_id, item.stage_id);
  for (const field of ['trade_date', 'stage_id']) {
    const missingIdentity = structuredClone(item.payload);
    delete missingIdentity.selection_markets.HK_CONNECT[field];
    await assert.rejects(
      () => validate(missingIdentity),
      (error) => error instanceof Error
          && error.message.includes('selection_markets.HK_CONNECT')
          && error.message.includes(field === 'trade_date'
            ? 'trade_date 与请求日期不一致'
            : 'stage_id 与请求不一致'),
    );
  }
}
""",
        encoding="utf-8",
    )
    build = subprocess.run(
        [
            str(esbuild),
            str(frontend_source),
            "--bundle",
            "--format=esm",
            "--platform=browser",
            f"--outfile={bundle_path}",
        ],
        cwd=repository_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert build.returncode == 0, build.stdout + build.stderr
    result = subprocess.run(
        [node, str(script_path), str(bundle_path), str(payload_path)],
        cwd=repository_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_four_stage_observation_projection_preserves_original_identity(
    source_bundle: dict[str, Any],
) -> None:
    bundle = source_bundle
    before = _tree_sha(bundle["selection_root"])
    output_root = bundle["tmp_path"] / "inactive-output"
    receipt = recovery.build_recovery(
        output_root=output_root,
        selection_root=bundle["selection_root"],
        raw_root=bundle["raw_root"],
        capture_root=bundle["capture_root"],
        d1_pool_path=bundle["d1_pool_path"],
        pins=bundle["pins"],
        active_state_root=bundle["active_state_root"],
    )

    assert receipt["stage_count"] == 4
    assert receipt["status"] == "OBSERVATION_UNVERIFIED"
    assert receipt["source_status"] == "CANNOT_CONFIRM"
    assert receipt["formal_eligible"] is False
    assert receipt["natural_verified"] is False
    assert receipt["production_allowed"] is False
    assert _tree_sha(bundle["selection_root"]) == before
    for stage_id, original in bundle["originals"].items():
        binding = receipt["stages"][stage_id]
        recovered_store = SelectionStore(
            output_root / "selection" / "backfill" / binding["backfill_run_id"]
        )
        recovered = recovered_store.read_verified(
            recovery.TRADE_DATE, stage_id, recovery.MARKET
        )
        assert recovered["run_id"] == original["run_id"]
        assert recovered["artifact_id"] == original["artifact_id"]
        assert recovered["raw_artifact_sha256"] == original["raw_artifact_sha256"]
        assert recovered["rows"] == original["rows"]
        assert recovered["cannot_confirm"] == ["HK_ACTIVE_SNAPSHOT_UNAVAILABLE"]
        assert recovered["source_status"] == "CANNOT_CONFIRM"
        assert recovered["selection_status"] == "PARTIAL_WITH_ROWS"
        assert "historical_temporal_cutoff_safe=false" in recovered["source_evidence"]
        assert "historical_capture_after_target_cutoff=true" in recovered["source_evidence"]
        assert "observation_status=OBSERVATION_UNVERIFIED" in recovered["source_evidence"]
        assert all(row["action_level"] == "NO_BUY" and row["formal_eligible"] is False for row in recovered["rows"])
        consumer_parameters = inspect.signature(StageSelectionConsumer).parameters
        receipt_root_keyword = (
            "runner_receipt_root"
            if "runner_receipt_root" in consumer_parameters
            else "execution_receipt_root"
        )
        consumer = StageSelectionConsumer(
            output_root / "selection" / "backfill" / binding["backfill_run_id"],
            **{receipt_root_keyword: output_root / "receipts"},
        )
        runner_verified, runner_sha = consumer._verify_backfill_runner_receipt(
            trade_date=recovery.TRADE_DATE,
            stage_id=stage_id,
            market=recovery.MARKET,
            backfill_run_id=binding["backfill_run_id"],
            envelope=recovered,
        )
        assert runner_verified is True
        assert runner_sha == binding["runner_receipt_sha256"]
        pin = next(item for item in bundle["pins"] if item.stage_id == stage_id)
        assert binding["selection_artifact_sha256"] == pin.original_selection_artifact_sha256


def test_api_projects_only_exact_original_runs_and_keeps_a_lane_unchanged(
    source_bundle: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = source_bundle
    machine_d1_pool_sha256 = _sha(recovery.DEFAULT_D1_POOL)
    assert machine_d1_pool_sha256 == recovery.D1_POOL_SHA256
    selection_root = bundle["selection_root"]
    output_root = bundle["tmp_path"] / "api-output"
    baseline_a_by_stage = {}
    with _api_client(selection_root, bundle["tmp_path"] / "baseline-api-data") as baseline_client:
        for stage_id in bundle["originals"]:
            baseline_response = baseline_client.get(
                "/api/v3/workbench/stage",
                params={"date": recovery.TRADE_DATE, "stage": stage_id, "limit": 10},
            )
            assert baseline_response.status_code == 200
            baseline_a_by_stage[stage_id] = baseline_response.json()["markets"]["A"]
    receipt = recovery.build_recovery(
        output_root=output_root,
        selection_root=selection_root,
        raw_root=bundle["raw_root"],
        capture_root=bundle["capture_root"],
        d1_pool_path=bundle["d1_pool_path"],
        pins=bundle["pins"],
        active_state_root=bundle["active_state_root"],
    )
    _copy_candidate_backfills(output_root, selection_root)
    _install_api_bindings(monkeypatch, receipt)

    with _api_client(selection_root, bundle["tmp_path"] / "api-data") as client:
        first_stage = "STAGE_0930_0935"
        exact_binding = receipt["stages"][first_stage]
        exact_response = client.get(
            "/api/v3/workbench/stage",
            params={
                "date": recovery.TRADE_DATE,
                "stage": first_stage,
                "limit": 10,
                "market": recovery.MARKET,
                "backfill_run_id": exact_binding["backfill_run_id"],
            },
        )
        assert exact_response.status_code == 200, exact_response.text
        responses = {}
        for stage_id, original in bundle["originals"].items():
            response = client.get(
                "/api/v3/workbench/stage",
                params={"date": recovery.TRADE_DATE, "stage": stage_id, "limit": 10},
            )
            assert response.status_code == 200
            payload = response.json()
            hk = payload["markets"]["HK"]
            assert payload["status"] == "PARTIAL_WITH_ROWS", json.dumps(payload, sort_keys=True)
            assert hk["display_mode"] == "OBSERVATION_UNVERIFIED"
            assert hk["status"] == "PARTIAL_WITH_ROWS"
            assert hk["source_status"] == "CANNOT_CONFIRM"
            assert hk["selected_rows"] == 10
            assert hk["candidate_count"] == 10
            assert len(hk["rows"]) == 10
            assert (
                payload["market_readback_bindings"]["markets"]["HK_CONNECT"][
                    "target_pool_sha256"
                ]
                == machine_d1_pool_sha256
            )
            assert hk["cannot_confirm"] == ["HK_ACTIVE_SNAPSHOT_UNAVAILABLE"]
            assert "HK_CAPTURE_AFTER_STAGE_CUTOFF_PIT_UNSAFE" in hk["display_reasons"]
            assert all(row["action_level"] == "NO_BUY" for row in hk["rows"])
            assert all(row["formal_eligible"] is False for row in hk["rows"])
            for row, original_row in zip(hk["rows"], original["rows"]):
                assert row["code"] == original_row["code"]
                assert row["rank"] == original_row["rank"]
                assert row["score"] == original_row["score"]
                assert row["source_last_bar_time"] == original_row["source_last_bar_time"]
            responses[stage_id] = payload
            assert payload["markets"]["A"] == baseline_a_by_stage[stage_id]


        # A new natural selection identity must remain the displayed source.
        stage_id = "STAGE_0930_0935"
        later_root = bundle["tmp_path"] / "later" / "stage" / "selection"
        later_root.mkdir(parents=True)
        later_envelope = {
            **bundle["originals"][stage_id],
            "raw_artifact_sha256": hashlib.sha256(b"later raw source").hexdigest(),
            "source_status": "READY",
            "selection_status": "READY",
            "rows": _selection_rows(stage_id, score_shift=2),
            "source_evidence": ["later_natural_selection=verified_source_identity"],
            "cannot_confirm": [],
        }
        later_envelope.pop("run_id", None)
        later_envelope.pop("artifact_id", None)
        later_published = SelectionStore(later_root).publish(
            later_envelope, market=recovery.MARKET
        )
        _copy_candidate_backfills(output_root, later_root)
        with _api_client(later_root, bundle["tmp_path"] / "later-api-data") as later_client:
            later_response = later_client.get(
                "/api/v3/workbench/stage",
                params={"date": recovery.TRADE_DATE, "stage": stage_id, "limit": 10},
            )
        assert later_response.status_code == 200
        later_hk = later_response.json()["markets"]["HK"]
        assert later_hk["run_id"] == later_published["run_id"]
        assert later_hk.get("backfill_run_id") is None
        assert later_hk["rows"][0]["score"] == later_envelope["rows"][0]["score"]


def test_early_hk_selection_markets_identity_matches_real_frontend_validator(
    source_bundle: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = source_bundle
    output_root = bundle["tmp_path"] / "frontend-api-output"
    receipt = recovery.build_recovery(
        output_root=output_root,
        selection_root=bundle["selection_root"],
        raw_root=bundle["raw_root"],
        capture_root=bundle["capture_root"],
        d1_pool_path=bundle["d1_pool_path"],
        pins=bundle["pins"],
        active_state_root=bundle["active_state_root"],
    )
    _copy_candidate_backfills(output_root, bundle["selection_root"])
    _install_api_bindings(monkeypatch, receipt)

    payloads = []
    with _api_client(
        bundle["selection_root"], bundle["tmp_path"] / "frontend-api-data"
    ) as client:
        for stage_id in bundle["originals"]:
            response = client.get(
                "/api/v3/workbench/stage",
                params={"date": recovery.TRADE_DATE, "stage": stage_id, "limit": 50},
            )
            assert response.status_code == 200, response.text
            payload = response.json()
            hk_connect = payload["selection_markets"]["HK_CONNECT"]
            assert hk_connect["trade_date"] == recovery.TRADE_DATE
            assert hk_connect["stage_id"] == stage_id
            assert payload["markets"]["HK"]["status"] == "PARTIAL_WITH_ROWS"
            assert len(payload["markets"]["HK"]["rows"]) == 10
            payloads.append(
                {"date": recovery.TRADE_DATE, "stage_id": stage_id, "payload": payload}
            )

    _run_actual_frontend_stage_validator(
        payloads, bundle["tmp_path"] / "frontend-validator"
    )


def test_recovery_fails_closed_before_output_when_capture_pin_is_bad(
    source_bundle: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = source_bundle
    monkeypatch.setattr(
        recovery,
        "_validate_capture",
        lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("pinned capture SHA mismatch")),
    )
    output_root = bundle["tmp_path"] / "bad-capture-output"
    with pytest.raises(ValueError, match="pinned capture SHA mismatch"):
        recovery.build_recovery(
            output_root=output_root,
            selection_root=bundle["selection_root"],
            raw_root=bundle["raw_root"],
            capture_root=bundle["capture_root"],
            d1_pool_path=bundle["d1_pool_path"],
            pins=bundle["pins"],
            active_state_root=bundle["active_state_root"],
        )
    assert not output_root.exists()
