"""Behavior tests for the exact R4 ordinary-page research binding."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from conftest import DAY, STAGE, BACKFILL, RouteHTTPException, digest, prepare_case, route_source, write_json


def test_ordinary_target_reads_both_approved_markets_without_repointing_history(case):
    reader, _ = prepare_case(case)
    endpoint = route_source(case, research_reader=reader)["stage_workbench"]
    actual = endpoint(date=DAY, stage=STAGE, limit=50)
    for market in ("A_SHARE", "HK_CONNECT"):
        assert actual["selection_markets"][market]["run_id"] == case.selected[market]["run_id"]
        assert len(actual["selection_markets"][market]["rows"]) == 10
    assert len(list((case.history.root / "selection_runs").iterdir())) == 19
    assert actual["execution_evidence"]["receipt_history_binding"] == "OWNER_HISTORY_SHA_BOUND"
    assert actual["execution_evidence"]["natural_verified"] is False
    assert actual["execution_evidence"]["execution_verified"] is False


def test_every_historical_date_retains_exact_original_response(case):
    reader, _ = prepare_case(case)
    old = route_source(case, phase="before")["stage_workbench"]
    new = route_source(case, research_reader=reader)["stage_workbench"]
    before = {str(path): path.read_bytes() for path in case.history.root.rglob("*") if path.is_file()}
    for day in case.ordinary:
        assert new(date=day, stage=STAGE, limit=50) == old(date=day, stage=STAGE, limit=50)
    assert new(date=DAY, stage="STAGE_0940_0945", limit=50) == old(date=DAY, stage="STAGE_0940_0945", limit=50)
    assert {str(path): path.read_bytes() for path in case.history.root.rglob("*") if path.is_file()} == before


@pytest.mark.parametrize("market", ["A_SHARE", "HK_CONNECT"])
def test_exact_r3_request_is_market_scoped(case, market):
    reader, _ = prepare_case(case)
    endpoint = route_source(case, research_reader=reader)["stage_workbench"]
    value = endpoint(date=DAY, stage=STAGE, limit=50, market=market, backfill_run_id=BACKFILL)
    assert set(value["selection_markets"]) == {market}
    assert value["selection_markets"][market]["run_id"] == case.selected[market]["run_id"]
    assert value["backfill_run_id"] == BACKFILL
    assert value["recommendation_status"] == "WATCH_ONLY"
    assert value["execution_evidence"]["natural_verified"] is False


@pytest.mark.parametrize("kwargs,status", [
    ({"market": "HK_CONNECT"}, 422), ({"backfill_run_id": BACKFILL}, 422),
    ({"market": "OTHER", "backfill_run_id": BACKFILL}, 404),
    ({"market": "HK_CONNECT", "backfill_run_id": "unapproved"}, 404),
    ({"market": "HK_CONNECT", "backfill_run_id": "../escape"}, 404),
])
def test_exact_request_rejects_incomplete_or_unapproved_identity(case, kwargs, status):
    reader, _ = prepare_case(case)
    endpoint = route_source(case, research_reader=reader)["stage_workbench"]
    with pytest.raises(RouteHTTPException) as exc:
        endpoint(date=DAY, stage=STAGE, limit=50, **kwargs)
    assert exc.value.status_code == status


@pytest.mark.parametrize("market", ["A_SHARE", "HK_CONNECT"])
@pytest.mark.parametrize("kind", ["artifact", "manifest", "receipt"])
def test_tampered_lane_trio_is_rejected_without_erasing_healthy_market(case, market, kind):
    reader, _ = prepare_case(case)
    declared = case.owner["selection_artifacts"][market]
    path = case.selection.root / declared[kind + "_relative"]
    path.write_bytes(path.read_bytes() + b" ")
    actual = route_source(case, research_reader=reader)["stage_workbench"](date=DAY, stage=STAGE, limit=50)
    sibling = "A_SHARE" if market == "HK_CONNECT" else "HK_CONNECT"
    assert actual["selection_markets"][market]["rows"] == []
    assert actual["selection_markets"][market]["status"] == "CANNOT_CONFIRM"
    assert len(actual["selection_markets"][sibling]["rows"]) == 10
    assert actual["selection_markets"][sibling]["run_id"] == case.selected[sibling]["run_id"]
    assert actual["status"] == "PARTIAL_WITH_ROWS"


def test_changed_latest_entry_cannot_retarget_approved_lane(case):
    reader, _ = prepare_case(case)
    latest = case.selection._latest()
    latest["entries"][case.selection._key(DAY, STAGE, "HK_CONNECT")]["run_id"] = case.selected["A_SHARE"]["run_id"]
    write_json(case.selection.latest_path, latest)
    value = reader.get(DAY, STAGE)
    assert value["markets"]["HK_CONNECT"]["rows"] == []
    assert len(value["markets"]["A_SHARE"]["rows"]) == 10


@pytest.mark.parametrize("target", ["run_manifest", "owner_receipt", "owner_history_receipt"])
def test_shared_pinned_evidence_tamper_rejects_target_but_history_survives(case, target):
    reader, _ = prepare_case(case)
    path = Path(case.manifest["output_paths"][target])
    path.write_bytes(path.read_bytes() + b" ")
    endpoint = route_source(case, research_reader=reader)["stage_workbench"]
    with pytest.raises(RouteHTTPException) as exc:
        endpoint(date=DAY, stage=STAGE, limit=50)
    assert exc.value.status_code == 409
    historic = next(iter(case.ordinary))
    assert endpoint(date=historic, stage=STAGE, limit=50)["selection_markets"]["A_SHARE"]["run_id"] == case.ordinary[historic]["A_SHARE"]["run_id"]


@pytest.mark.parametrize("name", ["consumer.py", "execution_evidence.py", "research_read_binding.py"])
def test_loaded_reader_source_drift_is_rejected(case, name):
    reader, _ = prepare_case(case)
    path = case.api_root / "stage_center" / name
    path.write_bytes(path.read_bytes() + b"\n# changed after import\n")
    with pytest.raises(case.binding_module.ResearchReadError, match="SOURCE"):
        reader.get(DAY, STAGE)


def test_stage_owner_source_drift_is_rejected(case):
    reader, _ = prepare_case(case)
    path = Path(case.manifest["stage_sources"][0]["actual_path"])
    path.write_bytes(path.read_bytes() + b"\n# changed owner source\n")
    with pytest.raises(case.binding_module.ResearchReadError, match="SOURCE"):
        reader.get(DAY, STAGE)


def test_binding_byte_digest_must_match_sidecar(case):
    reader, path = prepare_case(case)
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(case.binding_module.ResearchReadError, match="BINDING_SHA"):
        reader.get(DAY, STAGE)


@pytest.mark.parametrize("text", ["a" * 64, "a" * 64 + "\n\n", "A" * 64 + "\n", "not-a-digest\n"])
def test_sidecar_uses_one_canonical_ascii_digest(case, text):
    reader, path = prepare_case(case)
    path.with_suffix(".sha256").write_text(text)
    with pytest.raises(case.binding_module.ResearchReadError, match="BINDING_SHA"):
        reader.get(DAY, STAGE)


@pytest.mark.parametrize("missing", ["json", "sha256"])
def test_partial_binding_pair_fails_visibly(case, missing):
    reader, path = prepare_case(case)
    (path if missing == "json" else path.with_suffix(".sha256")).unlink()
    with pytest.raises(case.binding_module.ResearchReadError, match="BINDING_PAIR"):
        reader.get(DAY, STAGE)


def test_both_absent_disables_opt_in_without_changing_ordinary_reads(case):
    reader, path = prepare_case(case)
    path.unlink()
    path.with_suffix(".sha256").unlink()
    assert reader.get(DAY, STAGE) is None
    old = route_source(case, phase="before")["stage_workbench"]
    new = route_source(case, research_reader=reader)["stage_workbench"]
    assert new(date=DAY, stage=STAGE, limit=50) == old(date=DAY, stage=STAGE, limit=50)


@pytest.mark.parametrize("component", ["binding", "sidecar", "selection_namespace", "receipt_namespace"])
def test_symlink_paths_are_never_followed(case, component):
    reader, path = prepare_case(case)
    target = {"binding": path, "sidecar": path.with_suffix(".sha256"),
              "selection_namespace": case.selection.root, "receipt_namespace": case.receipts}[component]
    saved = target.with_name(target.name + ".original")
    target.rename(saved)
    target.symlink_to(saved, target_is_directory=saved.is_dir())
    with pytest.raises(case.binding_module.ResearchReadError, match="SYMLINK"):
        reader.get(DAY, STAGE)


def test_history_root_in_binding_must_equal_still_configured_root(case):
    reader, path = prepare_case(case)
    value = json.loads(path.read_text())
    value["history_root"] = str(case.output / "selection")
    write_json(path, value)
    path.with_suffix(".sha256").write_text(digest(path) + "\n")
    with pytest.raises(case.binding_module.ResearchReadError, match="HISTORY_ROOT"):
        reader.get(DAY, STAGE)


def test_config_cannot_replace_transitive_pins_even_with_a_matching_sidecar(case):
    reader, path = prepare_case(case)
    value = json.loads(path.read_text())
    value["markets"]["HK_CONNECT"]["artifact_bytes_sha256"] = "0" * 64
    write_json(path, value)
    path.with_suffix(".sha256").write_text(digest(path) + "\n")
    with pytest.raises(case.binding_module.ResearchReadError, match="CONFIG_EVIDENCE"):
        reader.get(DAY, STAGE)


def test_binding_preparation_rejects_unapproved_manifest(case):
    case.manifest_path.write_bytes(case.manifest_path.read_bytes() + b" ")
    with pytest.raises(case.binding_module.ResearchReadError, match="MANIFEST_SHA"):
        case.binding_module.build_research_read_binding(
            manifest_path=case.manifest_path, history_root=case.history.root, api_after_root=case.api_root)


def test_generated_binding_contains_exact_identity_and_reads_are_pure(case):
    reader, path = prepare_case(case)
    binding = json.loads(path.read_text())
    snapshot = {str(p): p.read_bytes() for p in case.root.rglob("*") if p.is_file()}
    value = reader.get(DAY, STAGE)
    for market in ("A_SHARE", "HK_CONNECT"):
        lane = value["markets"][market]
        assert lane["run_id"] == binding["markets"][market]["run_id"]
        assert lane["research_read_binding"]["artifact_bytes_sha256"] == binding["markets"][market]["artifact_bytes_sha256"]
        assert lane["research_read_binding"]["runner_receipt_sha256"] == binding["owner_receipt_sha256"]
    assert value["research_read_binding"]["run_manifest_sha256"] == digest(case.manifest_path)
    assert value["research_read_binding"]["history_root_preserved"] is True
    assert value["research_read_binding"]["reader_sources"]["stage_center/consumer.py"] == digest(case.api_root / "stage_center/consumer.py")
    assert value["RESEARCH_ONLY"] is True
    assert value["production_allowed"] is value["buy_gate_updated"] is value["orders_sent"] is False
    assert {str(p): p.read_bytes() for p in case.root.rglob("*") if p.is_file()} == snapshot


def test_original_selection_safety_schema_does_not_require_an_invented_research_field(case):
    assert all("RESEARCH_ONLY" not in value for value in case.selected.values())
    reader, _ = prepare_case(case)
    value = reader.get(DAY, STAGE)
    assert all(len(value["markets"][market]["rows"]) == 10 for market in ("A_SHARE", "HK_CONNECT"))
    assert value["RESEARCH_ONLY"] is True
