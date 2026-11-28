from datetime import date, datetime
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

HERE = Path(__file__).resolve().parent
DAY = date(2026, 11, 27)


def module_at(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def reads(monkeypatch):
    name = "content_projection.seven_p0_reads"
    previous = module_at(name, HERE.parent / "r21_seven_p0/seven_p0_reads.py")
    monkeypatch.setitem(sys.modules, name, previous)
    return module_at("content_projection.formal_admission_reads", HERE / "formal_admission_reads.py")


def test_partial_stage_retains_verified_observations_without_promoting(reads, monkeypatch, tmp_path):
    runner = SimpleNamespace(sha256="d" * 64)
    observation = {"selection_artifacts": {"A_SHARE": {}}, "status": "PARTIAL_WITH_ROWS",
                   "recorded_at": "2026-11-27T09:36:55+08:00"}
    monkeypatch.setattr(reads, "observe_stage_receipt", lambda *args: (runner, observation))
    selection = {
        "status": "PARTIAL_WITH_ROWS", "source_status": "CANNOT_CONFIRM", "run_id": "partial",
        **{name: {"sha256": "b" * 64} for name in ("artifact", "manifest", "receipt")},
    }
    monkeypatch.setattr(reads, "_read_selection", lambda *args: ([{"symbol": "002001.SZ"}], selection))

    def unavailable(*args):
        pytest.fail("partial observations must not enter formal raw admission")

    monkeypatch.setattr(reads, "_read_raw", unavailable)
    evidence, symbols = reads.stage_evidence(tmp_path, DAY, "STAGE_0930_0935")
    assert evidence["owner_receipt_verified"] is True
    assert evidence["observation_row_count"] == 1 and evidence["formal_row_count"] is None
    assert evidence["gap"] == "A_SELECTION_SOURCE_NOT_FORMAL_READY"
    assert not symbols


@pytest.mark.parametrize("within_cutoff", [True, False])
def test_ready_stage_requires_exact_window_and_source_symbols(reads, monkeypatch, tmp_path, within_cutoff):
    def observe(root, start, stage, end):
        assert root == tmp_path and stage == "STAGE_0930_0935"
        assert start.isoformat() == "2026-11-27T09:35:00+08:00"
        assert end.isoformat() == "2026-11-27T09:38:00+08:00"
        return SimpleNamespace(sha256="a" * 64), {
            "selection_artifacts": {"A_SHARE": {}}, "status": "READY",
            "recorded_at": "2026-11-27T09:36:00+08:00",
        }

    monkeypatch.setattr(reads, "observe_stage_receipt", observe)
    selection = {
        "status": "READY", "source_status": "READY", "run_id": "ready", "source_rows": 1,
        "raw_artifact_sha256": "d" * 64,
        **{name: {"sha256": "b" * 64} for name in ("artifact", "manifest", "receipt")},
    }
    monkeypatch.setattr(reads, "_read_selection", lambda *args: ([{"symbol": "002001.SZ"}], selection))
    clock = "09:34:00" if within_cutoff else "09:39:00"
    raw = [{"code": "002001.SZ", "bar_time": clock, "update_time": f"{DAY}T{clock}+08:00",
            "temporal_cutoff_safe": "true"}]
    source = {"status": "READY", "source_status": "READY", "requested_rows": 1,
              "window": "09:30-09:35", "cutoff_at": "09:35:00", "temporal_cutoff_safe": True,
              "artifact": {"sha256": "d" * 64}}
    monkeypatch.setattr(reads, "_read_raw", lambda *args: (raw, source))
    evidence, symbols = reads.stage_evidence(tmp_path, DAY, "STAGE_0930_0935")
    if within_cutoff:
        assert evidence["status"] == "READY" and symbols == {"002001.SZ"}
    else:
        assert evidence["gap"] == "A_SOURCE_CUTOFF_OR_FULL_COVERAGE_UNVERIFIED" and not symbols


def test_stage7_is_separate_from_selection(reads, monkeypatch, tmp_path):
    def source(data, day, target):
        assert str(DAY) == day and target == "2026-11-30" and data == tmp_path
        binding = {
            "row_count": 1, "target_date": target, "run_id": "raw-source",
            "registry_sha256": "a" * 64, "manifest_canonical_sha256": "b" * 64,
            "formal_rows_sha256": "c" * 64, "source_identity": {},
        }
        return binding, [{"symbol": "002001.SZ", "stage_selection_eligible": False}]

    absent = reads.formal_stage7(tmp_path, DAY)
    assert absent["gap"] == "VERIFIED_STAGE7_REGISTRY_UNAVAILABLE" and absent["row_count"] is None
    monkeypatch.setattr(reads, "read_stage7", source)
    verified = reads.formal_stage7(tmp_path, DAY, date(2026, 11, 30))
    assert verified["status"] == "READY" and verified["required_role"] == "A_SHARE_1MIN_STAGE_1445_1500"
    assert verified["source_merge_role"] == "SOURCE_ONLY" and not verified["stage_selection_eligible"]


def test_stage_aggregation_keeps_missing_counts_null(reads, monkeypatch, tmp_path):
    def observed(owner, day, stage):
        valid = stage == "STAGE_0930_0935"
        return ({"status": "READY" if valid else "CANNOT_CONFIRM", "owner_receipt_verified": True,
                 "observation_row_count": 1, "formal_row_count": 1 if valid else None},
                {"002001.SZ"} if valid else set())

    monkeypatch.setattr(reads, "stage_evidence", observed)
    rows = [{"code": "002001.SZ"}, {"code": "002002.SZ"}]
    result = reads.stage_projection({"dates": [{"stocks": rows}]}, tmp_path, tmp_path, DAY)["dates"][0]
    assert result["stage_coverage"]["available"] == 1 and result["stage_coverage"]["observed_stage_rows"] == 7
    assert result["seven_stage"]["status"] == "PARTIAL" and result["seven_stage"]["hit_count"] == 1
    assert result["seven_stage"]["stages"]["STAGE_0925"]["hit_count"] is None
    assert rows[0]["stage_memberships"] == ["STAGE_0930_0935"] and rows[1]["stage_memberships"] == []
    assert result["stage7_formal_review"]["row_count"] is None


def test_frontend_and_api_identity_fail_closed_after_tampering(reads, monkeypatch, tmp_path):
    monkeypatch.setattr(reads, "_actual_process", lambda root: True)
    archive = "v4_core_pure_r21_20261127.zip"
    monkeypatch.setattr(reads, "FROZEN_SOURCE", reads.digest(archive.encode()))
    api = {}
    for file in reads.SOURCE_EXECUTION_FILES:
        path = tmp_path / file
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(file)
        api[file] = reads.digest(path.read_bytes())
    script = b"export const admitted = true;"
    digest = reads.digest(script)
    entry = f"/assets/main-r21-formal-{digest[:12]}.js"
    assets = tmp_path / "frontend/dist/assets"
    assets.mkdir(parents=True)
    bundle = assets / Path(entry).name
    bundle.write_bytes(script)
    html = f'<script type="module" crossorigin src="{entry}"></script>'.encode()
    (assets.parent / "index.html").write_bytes(html)
    manifest = {"schema": "v4.r21.isolated_runtime_manifest.v1", "track": reads.TRACK,
                "api_files": api, "frontend": {"script_path": entry, "bundle_sha256": digest,
                                               "index_sha256": reads.digest(html)}}
    (tmp_path / "content_projection/formal_admission_manifest.json").write_text(json.dumps(manifest))
    verified = reads.RuntimeIdentity(tmp_path)
    assert verified.payload()["status"] == "VERIFIED"
    assert verified.runtime()["status"] == "MANIFEST_EXECUTION_FILES_VERIFIED"
    bundle.write_bytes(b"elsewhere")
    assert verified.payload()["reason"] == "R21_RUNTIME_BYTES_CHANGED"
    assert verified.runtime()["status"] == "CANNOT_CONFIRM"


def test_replay_goes_only_to_bound_date_and_persisted_receipt(reads, monkeypatch, tmp_path):
    slot = reads.SLOT_IDS[1]
    common = {"trade_date": str(DAY), "execution_mode": "BACKFILL",
              "natural_window_evidence": False, "pit_evidence": False, **reads.SAFETY}
    relative = "backfill/2026-11-27/receipts/daily_windows/2026-11-27_0925.jsonl"
    artifact = tmp_path / "owner-home" / relative
    artifact.parent.mkdir(parents=True)
    window = {**common, "slot_id": slot, "window": "09:25", "backfill_ref": relative,
              "scheduled_for": datetime(2026, 11, 27, 9, 25, tzinfo=reads.SHANGHAI).isoformat(),
              "schedule_status": "PARTIAL"}
    artifact.write_bytes(reads.canonical(window) + b"\n")
    passed = {**common, "slot_id": "all", "windows": [window]}
    missing = {**common, "slot_id": reads.SLOT_IDS[0], "windows": [], "reason": "NO_BOUND_R17_SCHEDULED_WINDOW"}
    for file, variable, body in (("D27_BACKFILL_STDOUT.json", "REPLAY_STDOUT_SHA256", passed),
                                 ("D27_SLOT1.json", "REPLAY_SLOT1_SHA256", missing)):
        raw = reads.canonical(body)
        (tmp_path / file).write_bytes(raw)
        monkeypatch.setattr(reads, variable, reads.digest(raw))
    locator = {"root": str(tmp_path)}
    result = reads.historical_replay(locator, DAY)
    assert result["slot_coverage"] == 1 and result["status"] == "HISTORICAL_REPLAY_READBACK"
    assert result["natural_verified"] is False and result["windows"][0]["natural_verified"] is False
    assert not reads.historical_replay(locator, date(2026, 11, 26))["windows"]
    artifact.write_text("{}\n")
    assert not reads.historical_replay(locator, DAY)["windows"]
