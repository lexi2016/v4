"""Offline regression fixtures for existing HK owners and exact-date consumers.

All rows and artifacts in this module are deterministic test inputs. They do
not establish that the corresponding Mac owner artifacts exist or were run.
"""
import hashlib
import json
from datetime import datetime
from pathlib import Path

import pytest

from v4.manager_research import connect_selection as connect
from v4.manager_research import workspace_plan as planner
from v4.manager_research.workspace_daily_channels import build_daily_channels
from upstreams.v3_shared_data.shared_data.hk_security_master import (
    HKSecurityMasterReadError,
    load_verified_hk_security_master_snapshot,
    publish_hk_security_master,
)


TARGET = "20261009"
SESSION = "20261008"
CONTEXT = {
    "plan_trade_date": TARGET,
    "market_session": SESSION,
    "research_cutoff": "2026-10-09T09:00:00+08:00",
}
ENV_KEYS = (
    "V4_MANAGER_UNIVERSE_ROOT",
    "V4_MANAGER_UNIVERSE_OWNER_ROOT",
    "V4_MANAGER_UNIVERSE_OWNER_SHA256",
    "V4_MANAGER_HK_CAPTURE_RECEIPT_ROOT",
    "V4_MANAGER_HK_DISPATCH_RECEIPT_ROOT",
)


@pytest.fixture(autouse=True)
def isolated_hk_environment(monkeypatch):
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def assert_research_only(value):
    assert value["RESEARCH_ONLY"] is True
    assert value["production_allowed"] is False
    assert value["buy_gate_updated"] is False
    assert value["orders_sent"] is False


def test_explicit_empty_connect_binding_cannot_fall_back_to_environment(tmp_path, monkeypatch):
    ambient = tmp_path / "ambient-authority"
    ambient.mkdir()
    monkeypatch.setenv("V4_MANAGER_UNIVERSE_ROOT", str(ambient))

    result = connect.read_scope(CONTEXT, binding={})

    assert result["status"] == "CANNOT_CONFIRM"
    assert result["codes"] == []
    assert result["gaps"] == ["HK_CONNECT_TARGET_AUTHORITY_ROOT_NOT_BOUND"]
    assert_research_only(result)


def test_connect_rejects_a_root_with_a_symlinked_ancestor(tmp_path, monkeypatch):
    actual = tmp_path / "actual"
    authority = actual / "authority"
    authority.mkdir(parents=True)
    alias = tmp_path / "alias"
    alias.symlink_to(actual, target_is_directory=True)
    monkeypatch.setenv("V4_MANAGER_UNIVERSE_ROOT", str(alias / "authority"))

    result = connect.read_scope(CONTEXT)

    assert result["status"] == "CANNOT_CONFIRM"
    assert result["codes"] == []
    assert result["gaps"] == ["HK_CONNECT_TARGET_AUTHORITY_ROOT_INVALID"]
    assert_research_only(result)


@pytest.mark.parametrize("binding", [{"universe_root": "relative"}, {"universe_root": []}, []])
def test_invalid_explicit_connect_binding_fails_closed(binding):
    result = connect.read_scope(CONTEXT, binding=binding)

    assert result["status"] == "CANNOT_CONFIRM"
    assert result["codes"] == []
    assert result["identity"] is None
    assert result["gaps"] == ["HK_CONNECT_TARGET_AUTHORITY_ROOT_INVALID"]
    assert_research_only(result)


def canonical_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256(value):
    return hashlib.sha256(value).hexdigest()


def publish_test_master(root, *, day=SESSION, captured_at="2026-10-08T17:00:00+08:00"):
    """Use the existing producer in a temporary fixture root; never live data."""
    return publish_hk_security_master(
        root,
        trade_date=day,
        rows=[{"code": "HK.01234", "name": "SYNTHETIC HK FIXTURE", "outstanding_shares": 1000}],
        universe_codes_sha256=sha256(canonical_bytes(["HK.01234"])),
        captured_at=captured_at,
    )


def test_existing_master_artifact_has_one_exact_run_and_byte_witness(tmp_path):
    published = publish_test_master(tmp_path)

    names, manifest, witness = load_verified_hk_security_master_snapshot(tmp_path, SESSION)

    assert sorted(names) == ["HK.01234"]
    assert manifest["trade_date"] == SESSION
    assert manifest["run_id"] == published["run_id"] == witness["run_id"]
    for kind in ("manifest", "receipt", "artifact"):
        assert witness[f"{kind}_sha256"] == sha256(Path(witness[f"{kind}_path"]).read_bytes())
    assert witness["read_diagnostic"]["status"] == "VERIFIED"
    assert witness["read_diagnostic"]["requested_entry_present"] is True
    assert manifest["later_snapshot_price_allowed"] is False
    for key in ("production_allowed", "buy_gate_updated", "orders_sent"):
        assert manifest[key] is False


def test_master_missing_exact_date_does_not_read_older_or_latest_entry(tmp_path):
    publish_test_master(tmp_path, day="20261007")
    publish_test_master(tmp_path, day="20261009")

    with pytest.raises(HKSecurityMasterReadError) as caught:
        load_verified_hk_security_master_snapshot(tmp_path, SESSION)

    assert caught.value.reason_code == "HK_SECURITY_MASTER_EXACT_DATE_ENTRY_MISSING"
    diagnostic = caught.value.diagnostic
    assert diagnostic["status"] == "MISSING"
    assert diagnostic["requested_trade_date"] == SESSION
    assert diagnostic["requested_entry_present"] is False
    assert diagnostic["entry_count"] == 2
    assert diagnostic["latest_entry_date"] == TARGET
    assert len(diagnostic["latest_json_sha256"]) == 64


@pytest.mark.parametrize("case, expected", [
    ("artifact_sha", "HK_SECURITY_MASTER_ARTIFACT_CHECKSUM_MISMATCH"),
    ("manifest_sha", "HK_SECURITY_MASTER_MANIFEST_CHECKSUM_MISMATCH"),
    ("run_id", "HK_SECURITY_MASTER_IDENTITY_OR_SAFETY_INVALID"),
    ("trade_date", "HK_SECURITY_MASTER_IDENTITY_OR_SAFETY_INVALID"),
    ("unsafe", "HK_SECURITY_MASTER_IDENTITY_OR_SAFETY_INVALID"),
    ("outside_root", "HK_SECURITY_MASTER_METADATA_INVALID"),
])
def test_master_invalid_referenced_evidence_is_invalid_not_missing(tmp_path, case, expected):
    published = publish_test_master(tmp_path)
    asset_root = tmp_path / "assets" / "hk_security_master"
    run_root = asset_root / "runs" / SESSION / published["run_id"]
    manifest_path = run_root / "manifest.json"
    receipt_path = run_root / "receipt.json"
    manifest = json.loads(manifest_path.read_bytes())
    receipt = json.loads(receipt_path.read_bytes())
    if case == "artifact_sha":
        (run_root / "artifact.csv").write_bytes(b"tampered fixture bytes")
    elif case == "manifest_sha":
        receipt["manifest_sha256"] = "0" * 64
        receipt_path.write_bytes(canonical_bytes(receipt))
    else:
        if case == "run_id":
            manifest["run_id"] = "different-fixture-run"
        elif case == "trade_date":
            manifest["trade_date"] = TARGET
        elif case == "unsafe":
            manifest["production_allowed"] = True
        elif case == "outside_root":
            manifest["artifact_relative"] = "../../outside.csv"
        manifest_path.write_bytes(canonical_bytes(manifest))

    with pytest.raises(HKSecurityMasterReadError) as caught:
        load_verified_hk_security_master_snapshot(tmp_path, SESSION)

    assert caught.value.reason_code == expected
    assert caught.value.diagnostic["status"] == "INVALID"
    assert caught.value.diagnostic["requested_entry_present"] is True


@pytest.fixture
def synthetic_hk_calendar(tmp_path, monkeypatch):
    """Exercise the native resolver with a labelled offline calendar fixture."""
    import contracts.trading_calendar as calendar

    def market(derives=()):
        return {
            "label": "SYNTHETIC CALENDAR FIXTURE",
            "derives_from": list(derives),
            "full_day_sessions": [{"start": "0930", "end": "1600"}],
            "half_day_sessions": [{"start": "0930", "end": "1200"}],
            "full_day_close": "1610",
            "half_day_close": "1210",
            "half_days": [],
            "holiday_periods": [],
        }

    value = {
        "schema_version": calendar.SCHEMA_VERSION,
        "year": 2026,
        "timezone": "Asia/Shanghai",
        "official_sources": [
            {"market": key, "name": "SYNTHETIC NOT OFFICIAL", "url": f"https://fixture.invalid/{key}"}
            for key in calendar.MARKET_KEYS
        ],
        "markets": {
            "a_share": market(),
            "hk_securities": market(),
            "hk_connect_southbound": market(["a_share", "hk_securities"]),
        },
    }
    path = tmp_path / "synthetic_calendar.json"
    path.write_bytes(canonical_bytes(value))
    monkeypatch.setattr(calendar, "CALENDAR_PATH", path)
    return path


def publish_test_hk02_panel(root, *, day=SESSION, available_at="2026-10-08T18:00:00+08:00"):
    """Write only a synthetic artifact in the original immutable panel layout."""
    import pandas as pd

    sessions = planner.rebound_history_sessions(day)
    rows = [
        {
            "trade_date_compact": session,
            "code_norm": "HK.01234",
            "name": "SYNTHETIC HK FIXTURE",
            "open": 100.0,
            "high": 100.0,
            "low": 90.0,
            "close": 100.0,
            "amount": 150_000_000.0,
            "trade": 100.0,
            "pre_close": 100.0,
        }
        for session in sessions["prior60"]
    ]
    rows.append({**rows[-1], "trade_date_compact": day, "open": 70.0, "high": 80.0,
                 "low": 60.0, "close": 70.0, "trade": 200.0})
    frame = pd.DataFrame(rows)
    panel_bytes = frame.to_parquet(index=False)
    panel_sha = sha256(panel_bytes)
    relative_root = f"panels/{day}-{panel_sha[:12]}"
    relative_panel = f"{relative_root}/hkconnect_vipdoc_daily_panel.parquet"
    asset_root = root / "assets" / "hk_0_2"
    panel_path = asset_root / relative_panel
    panel_path.parent.mkdir(parents=True, exist_ok=True)
    panel_path.write_bytes(panel_bytes)
    manifest = {
        "asset_schema_version": "v3_shared_data.hk_0_2_panel_asset.v2",
        "source_contract": "tdx_vipdoc_71_day+verified_zero_trade_repairs",
        "panel_max_date": day,
        "panel_relative": relative_panel,
        "panel_sha256": panel_sha,
        "panel_rows": len(rows),
        "panel_code_count": 1,
        "manifest_prepared_at": available_at,
        "research_only": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    manifest_path = asset_root / relative_root / "manifest.json"
    manifest_path.write_bytes(canonical_bytes(manifest))
    (asset_root / "panel_latest.json").write_bytes(canonical_bytes({
        "manifest_relative": f"{relative_root}/manifest.json",
    }))
    return manifest_path, panel_path


def screen_channel(screen):
    value = {
        "target_trade_date": TARGET,
        "date_bindings": {"selection_date": TARGET, "plan_date": TARGET, "announcement_date": SESSION},
        "market_screen": screen,
    }
    return next(channel for channel in build_daily_channels(value)["channels"]
                if channel["channel"] == "OVERSOLD")


def test_exact_panel_and_master_read_into_screen_without_inventing_volume_provenance(tmp_path, synthetic_hk_calendar):
    published = publish_test_master(tmp_path)
    manifest_path, panel_path = publish_test_hk02_panel(tmp_path)
    context = {**CONTEXT, "calendar_sha256": sha256(synthetic_hk_calendar.read_bytes())}

    screen = planner.read_rebound_screen(tmp_path, context)

    assert screen["status"] == "READY_WITH_GAPS", screen["gaps"]
    assert screen["verified_session"] == SESSION
    assert screen["authority"]["panel_witness"]["panel_sha256"] == sha256(panel_path.read_bytes())
    assert screen["authority"]["panel_witness"]["panel_manifest_sha256"] == sha256(manifest_path.read_bytes())
    assert screen["authority"]["security_master"]["run_id"] == published["run_id"]
    assert screen["coverage"]["numeric_history_complete_count"] == 1
    assert screen["coverage"]["history_pending_count"] == 1
    assert screen["strict"] == screen["near"] == []
    assert screen["authority"]["volume_provenance"]["status"] == "NOT_PROVEN"
    assert "SCREEN_VOLUME_UNIT_OR_SCALE_NOT_PROVEN" in screen["gaps"]
    assert len(screen["input_identity"]) == 64
    assert_research_only(screen)

    channel = screen_channel(screen)
    assert channel["status"] == "PARTIAL"
    assert channel["candidate_count"] is None
    assert channel["pending_count"] == 1
    assert channel["data_date"] == SESSION
    assert channel["input_identity"] == screen["input_identity"]
    assert_research_only(channel)


@pytest.mark.parametrize("missing", ["index", "exact_entry"])
def test_screen_missing_master_stays_cannot_confirm_through_channel(tmp_path, synthetic_hk_calendar, missing):
    publish_test_hk02_panel(tmp_path)
    if missing == "exact_entry":
        publish_test_master(tmp_path, day=TARGET)

    screen = planner.read_rebound_screen(tmp_path, CONTEXT)

    reason = "HK_SECURITY_MASTER_INDEX_MISSING" if missing == "index" else "HK_SECURITY_MASTER_EXACT_DATE_ENTRY_MISSING"
    assert screen["status"] == "CANNOT_CONFIRM"
    assert screen["gaps"] == ["SCREEN_SECURITY_MASTER_READ_FAILED:" + reason]
    assert screen["verified_session"] == SESSION
    diagnostic = screen["data_context"]["security_master_read"]
    assert diagnostic["status"] == "MISSING"
    assert diagnostic["reason_code"] == reason
    channel = screen_channel(screen)
    assert channel["status"] == "CANNOT_CONFIRM"
    assert channel["candidate_count"] is None
    assert channel["rows"] == []
    assert_research_only(channel)


@pytest.mark.parametrize("late", ["master", "panel"])
def test_screen_rejects_artifact_available_after_research_cutoff(tmp_path, synthetic_hk_calendar, late):
    time_late = "2026-10-09T09:00:01+08:00"
    publish_test_master(tmp_path, captured_at=time_late if late == "master" else "2026-10-08T17:00:00+08:00")
    publish_test_hk02_panel(tmp_path, available_at=time_late if late == "panel" else "2026-10-08T18:00:00+08:00")

    screen = planner.read_rebound_screen(tmp_path, CONTEXT)

    expected = "SCREEN_SECURITY_MASTER_AFTER_CUTOFF_OR_UNVERIFIED" if late == "master" else "PLAN_HK_02_PANEL_AFTER_RESEARCH_CUTOFF"
    assert screen["status"] == "CANNOT_CONFIRM"
    assert expected in screen["gaps"]
    assert screen_channel(screen)["status"] == "CANNOT_CONFIRM"
    assert_research_only(screen)


def test_screen_uses_exact_session_panel_when_latest_points_to_later_date(tmp_path, synthetic_hk_calendar):
    publish_test_master(tmp_path)
    exact_manifest, exact_panel = publish_test_hk02_panel(tmp_path)
    publish_test_hk02_panel(tmp_path, day=TARGET, available_at="2026-10-09T18:00:00+08:00")

    screen = planner.read_rebound_screen(tmp_path, CONTEXT)

    assert screen["status"] == "READY_WITH_GAPS", screen["gaps"]
    assert screen["verified_session"] == SESSION
    assert screen["authority"]["panel_witness"]["panel_sha256"] == sha256(exact_panel.read_bytes())
    assert screen["authority"]["panel_witness"]["panel_manifest_sha256"] == sha256(exact_manifest.read_bytes())
    assert screen_channel(screen)["status"] == "PARTIAL"


def publish_test_v2(root, *, day=TARGET, codes=("HK.01234", "HK.05678"),
                    acquired_at="2026-10-09T08:00:00+08:00",
                    available_at="2026-10-09T08:01:00+08:00"):
    """Use the existing pure V2 builder for labelled synthetic captured inputs.

    No capture/ensure method runs. Every generated file stays in the test root;
    recorded fixture provenance is not a claim of an actual owner execution.
    """
    from domains.manager_research_evidence import load_universe_owner

    app_root = Path(__file__).resolve().parents[1]
    owner_ref = "stage_center/hk_universe_preflight.py"
    owner_sha = sha256((app_root / owner_ref).read_bytes())
    owner = load_universe_owner(app_root, owner_sha, require_v2=True)
    producer_ref = "ops/_macos_research_panel_daily_parts/hk_market_capture.py"
    forward = {key: sha256(("SYNTHETIC FIXTURE " + key).encode()) for key in (
        "forward_receipt_sha256", "candidate_manifest_sha256", "candidate_build_receipt_sha256",
        "api_writer_receipt_sha256", "api_reviewer_receipt_sha256", "api_source_mapping_sha256",
    )}
    forward["source_head"] = "74478a0e62be215c8527ccc9a14b89b51042d014"
    producer = {
        "workload_id": "v35_dispatcher.research_panel_daily_hk",
        "code_ref": producer_ref,
        "code_sha256": sha256((app_root / producer_ref).read_bytes()),
        "forward_source_set": forward,
        "forward_source_set_sha256": owner._sha256(forward),
    }
    per_plate = {
        owner.HKCONNECT_PLATE_CODES[0]: [codes[0]],
        owner.HKCONNECT_PLATE_CODES[1]: sorted(set(codes)),
    }
    responses = {}
    for plate, plate_codes in per_plate.items():
        material = {
            "requested_plate": plate,
            "serialization_version": "futu.dataframe.records.canonical-json.v1",
            "columns": ["code", "name"],
            "rows": [{"code": code, "name": "SYNTHETIC HK FIXTURE"} for code in plate_codes],
        }
        responses[plate] = {
            **material, "return_code": 0, "row_count": len(plate_codes),
            "requested_at": acquired_at, "completed_at": acquired_at,
            "response_sha256": owner._sha256(material),
        }
    source = {
        "target_date": day,
        "plate_codes": per_plate,
        "plate_response_sha256": {plate: row["response_sha256"] for plate, row in responses.items()},
        "capture_run_id": f"synthetic-capture-{day}",
        "acquired_at": acquired_at,
    }
    capture = {
        "schema_version": owner.HK_CONNECT_CAPTURE_SCHEMA_V2,
        "status": "READY", "target_date": day,
        "capture_run_id": source["capture_run_id"],
        "producer_owner": producer,
        "plate_responses": responses,
        "plate_codes": per_plate,
        "plate_response_counts": {plate: len(values) for plate, values in per_plate.items()},
        "plate_response_sha256": source["plate_response_sha256"],
        "acquired_at": acquired_at,
        "membership_source_payload": source,
        "membership_source_sha256": owner._sha256(source),
        "overlap_count": len(set(per_plate[owner.HKCONNECT_PLATE_CODES[0]])
                             & set(per_plate[owner.HKCONNECT_PLATE_CODES[1]])),
        "codes": sorted(set(codes)), "code_count": len(set(codes)),
        **owner.SAFETY_FLAGS,
    }
    capture["capture_sha256"] = owner._sha256(capture)
    contract_owner = {"code_ref": owner_ref, "code_sha256": owner_sha,
                      "role": "PURE_CAPTURED_HK_CONNECT_CONTRACT_V2"}
    built = owner.build_captured_hk_connect_authority_v2(
        capture, trade_date=day, producer_owner=producer, contract_owner=contract_owner)
    for key in ("artifact", "manifest", "receipt", "current", "capture"):
        relative = built["capture_relative"] if key == "capture" else built["paths"][f"{key}_relative"]
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(built[f"{key}_bytes"])
    publication = {
        "schema_version": owner.HK_CONNECT_PUBLICATION_SCHEMA_V2,
        "status": "READY", "target_date": day, "effective_date": day,
        "trade_date": day, "source_date": day, "market": "HK_CONNECT", "scope": "FULL_MARKET",
        "run_id": built["run_id"], "publication_relative": built["publication_relative"],
        "available_at": available_at, "acquired_at": acquired_at,
        "capture_run_id": capture["capture_run_id"], "capture_sha256": capture["capture_sha256"],
        "artifact_relative": built["paths"]["artifact_relative"], "artifact_sha256": built["artifact_sha256"],
        "manifest_relative": built["paths"]["manifest_relative"],
        "receipt_relative": built["paths"]["receipt_relative"],
        "current_relative": built["paths"]["current_relative"], "current_sha256": built["current_sha256"],
        "workload_id": producer["workload_id"], "producer_owner": producer,
        "contract_owner": contract_owner, "forward_source_set": forward,
        "forward_source_set_sha256": producer["forward_source_set_sha256"], **owner.SAFETY_FLAGS,
    }
    publication["publication_sha256"] = owner._sha256(publication)
    (root / built["publication_relative"]).write_bytes(owner._canonical_json_line(publication))
    binding = {"universe_root": root, "authority_owner_root": app_root, "authority_owner_sha256": owner_sha}
    return binding, built


@pytest.fixture
def synthetic_authority_observation_clock(monkeypatch):
    import domains.manager_research_evidence as evidence

    class FixtureReadClock(datetime):
        @classmethod
        def now(cls, tz=None):
            # Deliberately later than the research cutoff: persisted source
            # clocks, not the reader's current observation, authorize inputs.
            value = datetime.fromisoformat("2026-10-09T12:00:00+08:00")
            return value.astimezone(tz)

    monkeypatch.setattr(evidence, "datetime", FixtureReadClock)


def test_explicit_v2_binding_reads_original_chain_into_connect_channel(
        tmp_path, monkeypatch, synthetic_hk_calendar, synthetic_authority_observation_clock):
    binding, built = publish_test_v2(tmp_path / "authority")
    monkeypatch.setenv("V4_MANAGER_UNIVERSE_ROOT", str(tmp_path / "unrelated-environment-root"))
    context = {**CONTEXT, "calendar_sha256": sha256(synthetic_hk_calendar.read_bytes())}

    scope = connect.read_scope(context, binding=binding)

    assert scope["status"] == "OWNER_VERIFIED", scope["gaps"]
    assert scope["codes"] == ["HK.01234", "HK.05678"]
    assert scope["source"]["run_id"] == built["run_id"]
    assert scope["source"]["sha256"] == built["artifact_sha256"]
    assert scope["source"]["source_date"] == TARGET
    assert scope["source"]["acquired_at"] == "2026-10-09T08:00:00+08:00"
    assert scope["source"]["available_at"] == "2026-10-09T08:01:00+08:00"
    assert scope["source"]["read_at"] == "2026-10-09T12:00:00+08:00"
    assert scope["calendar_applicability"]["status"] == "APPLICABLE"
    assert_research_only(scope)

    cards, rejected = connect.filter_cards([
        {"symbol": "HK.01234", "name": "SYNTHETIC HK FIXTURE", "why_watch": ["Synthetic owner evidence"]},
        {"symbol": "HK.09999", "name": "OUTSIDE SYNTHETIC MEMBERSHIP"},
    ], scope, target_date=TARGET)
    assert [row["symbol"] for row in cards] == ["HK.01234"]
    assert rejected[0]["reason"] == "NOT_IN_TARGET_HK_CONNECT_UNIVERSE"
    value = {
        "target_trade_date": TARGET,
        "date_bindings": {"plan_date": TARGET, "selection_date": TARGET, "announcement_date": SESSION},
        "plan_context": CONTEXT,
        "stocks": cards, "focus_symbols": ["HK.01234"],
        "owner_chain": {"focus_inputs": {"status": "READY", "gaps": []}},
        "selection_diagnostics": {"status": "READY", "membership": scope, "connect_gaps": []},
    }
    channel = next(row for row in build_daily_channels(value)["channels"] if row["channel"] == "HK_CONNECT")
    assert channel["status"] == "READY"
    assert channel["candidate_count"] == 1
    assert channel["rows"][0]["symbol"] == "HK.01234"
    assert channel["input_identity"] == scope["identity"]
    assert channel["authority"]["source"]["run_id"] == built["run_id"]
    assert_research_only(channel)


@pytest.mark.parametrize("clock", ["acquired_at", "available_at"])
def test_connect_v2_rejects_persisted_times_after_cutoff(tmp_path, synthetic_authority_observation_clock, clock):
    kwargs = {clock: "2026-10-09T09:00:01+08:00"}
    if clock == "acquired_at":
        kwargs["available_at"] = "2026-10-09T09:00:02+08:00"
    binding, _ = publish_test_v2(tmp_path, **kwargs)

    scope = connect.read_scope(CONTEXT, binding=binding)

    assert scope["status"] == "CANNOT_CONFIRM"
    assert scope["codes"] == []
    assert scope["gaps"] == ["HK_CONNECT_TARGET_AUTHORITY_UNVERIFIED:HK_CONNECT_TARGET_AUTHORITY_AFTER_CUTOFF_OR_WRONG_DATE"]
    assert_research_only(scope)


def test_connect_v2_persisted_availability_equal_to_cutoff_is_accepted(tmp_path, synthetic_authority_observation_clock):
    binding, _ = publish_test_v2(tmp_path, available_at=CONTEXT["research_cutoff"])

    scope = connect.read_scope(CONTEXT, binding=binding)

    assert scope["status"] == "OWNER_VERIFIED", scope["gaps"]
    assert_research_only(scope)


@pytest.mark.parametrize("case, expected", [
    ("missing_exact_date", "HK_UNIVERSE_V2_ARTIFACT_MISSING"),
    ("empty_root", "HK_UNIVERSE_V2_ARTIFACT_MISSING"),
    ("owner_sha", "HK_UNIVERSE_OWNER_SHA_MISMATCH"),
    ("manifest_identity", "HK_UNIVERSE_V2_CHAIN_IDENTITY_MISMATCH"),
    ("publication_sha", "HK_UNIVERSE_V2_PUBLICATION_SHA_INVALID"),
    ("cross_root_symlink", "HK_UNIVERSE_V2_ARTIFACT_INVALID"),
])
def test_connect_v2_invalid_chain_never_becomes_verified_or_valid_empty(
        tmp_path, synthetic_authority_observation_clock, case, expected):
    root = tmp_path / "authority"
    day = SESSION if case == "missing_exact_date" else TARGET
    capture_time = "2026-10-08T08:00:00+08:00" if day == SESSION else "2026-10-09T08:00:00+08:00"
    publication_time = "2026-10-08T08:01:00+08:00" if day == SESSION else "2026-10-09T08:01:00+08:00"
    binding, built = publish_test_v2(root, day=day, acquired_at=capture_time, available_at=publication_time)
    if case == "empty_root":
        (tmp_path / "empty").mkdir()
        binding["universe_root"] = tmp_path / "empty"
    elif case == "owner_sha":
        binding["authority_owner_sha256"] = "0" * 64
    elif case == "manifest_identity":
        path = root / built["paths"]["manifest_relative"]
        value = json.loads(path.read_bytes())
        value["run_id"] = "synthetic-wrong-run"
        path.write_bytes(canonical_bytes(value) + b"\n")
    elif case == "publication_sha":
        path = root / built["publication_relative"]
        value = json.loads(path.read_bytes())
        value["publication_sha256"] = "0" * 64
        path.write_bytes(canonical_bytes(value) + b"\n")
    elif case == "cross_root_symlink":
        path = root / built["paths"]["artifact_relative"]
        outside = tmp_path / "outside-authority-artifact.json"
        outside.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(outside)

    scope = connect.read_scope(CONTEXT, binding=binding)

    assert scope["status"] == "CANNOT_CONFIRM"
    assert scope["codes"] == []
    assert scope["identity"] is None
    assert scope["gaps"] == ["HK_CONNECT_TARGET_AUTHORITY_UNVERIFIED:" + expected]
    assert_research_only(scope)


def test_v2_cards_preserve_persisted_availability_and_ignore_reader_observation_clock(
        tmp_path, monkeypatch, synthetic_authority_observation_clock):
    import domains.manager_research_evidence as evidence
    from v4.manager_research.workspace_projection import build_workspace

    binding, _ = publish_test_v2(tmp_path)
    cards = [{"symbol": "HK.01234", "name": "SYNTHETIC HK FIXTURE"}]
    first_scope = connect.read_scope(CONTEXT, binding=binding)
    first_cards, _ = connect.filter_cards(cards, first_scope)

    class LaterReadClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.fromisoformat("2026-10-09T12:01:00+08:00").astimezone(tz)

    monkeypatch.setattr(evidence, "datetime", LaterReadClock)
    second_scope = connect.read_scope(CONTEXT, binding=binding)
    second_cards, _ = connect.filter_cards(cards, second_scope)

    assert first_scope["status"] == second_scope["status"] == "OWNER_VERIFIED"
    assert first_scope["identity"] == second_scope["identity"]
    assert first_scope["source"]["read_at"] != second_scope["source"]["read_at"]
    assert first_cards == second_cards
    assert first_cards[0]["membership_source"]["available_at"] == "2026-10-09T08:01:00+08:00"
    assert "read_at" not in first_cards[0]["membership_source"]
    first_workspace = build_workspace(TARGET, catalyst={}, discovered_cards=first_cards, plan_context=CONTEXT)
    second_workspace = build_workspace(TARGET, catalyst={}, discovered_cards=second_cards, plan_context=CONTEXT)
    assert first_workspace["input_identity"] == second_workspace["input_identity"]
