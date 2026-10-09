"""Generated-delta and original exact-backfill route acceptance tests."""
from copy import deepcopy
import json
from pathlib import Path
import re
import shutil
from types import SimpleNamespace

import pytest

from conftest import (BACKFILL, DAY, FLAGS, R3, STAGE, WORK, BEFORE, TOOLS, digest, load,
                      prepare_case, route_source, write_json, RouteHTTPException)


def preparation_inputs(case, monkeypatch):
    tool = load("_r4_prepare_research_binding", TOOLS / "prepare_research_binding.py", monkeypatch)
    source = case.root / "current_api_support"
    shutil.copytree(R3 / "test_support/stage_base_app", source)
    app = source / "apps/api/v35_api/app.py"
    app.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(BEFORE / "apps/api/v35_api/app.py", app)
    # Only this temporary fixture's compiled trust anchor changes. Production
    # CLI/source has no environment flag, parameter, or endpoint allowing it.
    helper = case.module_path
    text = helper.read_text()
    approved = repr(case.binding_module.APPROVED_RESEARCH_RUN)
    text = re.sub(r"APPROVED_RESEARCH_RUN = \{.*?\n\}\nR3_READER_SHA256", "APPROVED_RESEARCH_RUN = " + approved + "\nR3_READER_SHA256", text, count=1, flags=re.S)
    helper.write_text(text)
    app_after = case.api_root / "apps/api/v35_api/app.py"
    app_after.write_text(re.sub(r'_STAGE_RESEARCH_READER_SHA256 = "[0-9a-f]{64}"',
                               '_STAGE_RESEARCH_READER_SHA256 = "' + digest(helper) + '"', app_after.read_text(), count=1))
    monkeypatch.setattr(tool, "REVIEWED_AFTER_SHA256", {name: digest(case.api_root / name) for name in tool.REVIEWED_AFTER_SHA256})
    args = {"manifest_path": case.manifest_path, "history_root": case.history.root,
            "api_after_root": case.api_root, "api_source_root": source,
            "output_root": case.root / "generated_binding"}
    return tool, args


def test_preparation_generates_two_exact_absent_to_present_delta_files(case, monkeypatch):
    tool, args = preparation_inputs(case, monkeypatch)
    before = {str(path): path.read_bytes() for path in case.root.rglob("*") if path.is_file()}
    result = tool.prepare_research_read_binding(**args)
    assert result["status"] == "PREPARED_NOT_DEPLOYED"
    assert len(result["files"]) == 2
    assert {row["path"] for row in result["files"]} == {
        "stage_center/approved_research_read.json", "stage_center/approved_research_read.sha256"}
    for row in result["files"]:
        assert row["before_sha256"] is None and row["before_mode"] is None
        assert row["after_sha256"] == digest(args["output_root"] / row["path"])
        assert row["after_mode"] == "0644"
        assert (args["output_root"] / row["path"]).stat().st_mode & 0o777 == 0o644
    assert result["proof_sha256"] == digest(result["proof_path"])
    proof = json.loads(Path(result["proof_path"]).read_text())
    assert proof["history"]["selection_date_count"] == 19
    assert proof["history_latest_unchanged_during_preparation"] is True
    assert proof["binding_evidence"]["markets"]["HK_CONNECT"]["run_id"] == case.selected["HK_CONNECT"]["run_id"]
    assert proof["integrated"] is proof["deployed"] is proof["natural_verified"] is False
    assert {name: Path(name).read_bytes() for name in before} == before
    with pytest.raises(tool.PreparationError, match="NEW_OUTPUT"):
        tool.prepare_research_read_binding(**args)


@pytest.mark.parametrize("fault", ["active_app", "reviewed_after", "manifest", "preexisting_binding", "overlap"])
def test_preparation_failure_writes_no_output(case, monkeypatch, fault):
    tool, args = preparation_inputs(case, monkeypatch)
    if fault == "active_app":
        path = args["api_source_root"] / "apps/api/v35_api/app.py"
        path.write_bytes(path.read_bytes() + b"\n")
    elif fault == "reviewed_after":
        path = args["api_after_root"] / "stage_center/consumer.py"
        path.write_bytes(path.read_bytes() + b"\n")
    elif fault == "manifest":
        case.manifest_path.write_bytes(case.manifest_path.read_bytes() + b"\n")
    elif fault == "preexisting_binding":
        path = args["api_source_root"] / "stage_center/approved_research_read.json"
        path.write_text("{}\n")
    else:
        args["output_root"] = case.output / "must_not_exist"
    with pytest.raises(tool.PreparationError):
        tool.prepare_research_read_binding(**args)
    assert not args["output_root"].exists()


def legacy_binding(case):
    day, backfill = "20260820", "legacy-fixture"
    store = case.runtime.selection.SelectionStore(case.history.root / "backfill" / backfill)
    envelope = deepcopy(case.selected["HK_CONNECT"])
    envelope.update(trade_date=day, source_evidence=["due_status=HISTORICAL_BACKFILL"], cannot_confirm=["LEGACY_RESEARCH_ONLY"])
    envelope.pop("run_id", None)
    envelope.pop("artifact_id", None)
    for row in envelope["rows"]:
        row.update(trade_date=day, source_mode="HK_CONNECT_FOUR_LANE", formal_eligible=False,
                   action_level="NO_BUY", trade_status="WATCH_ONLY", status="WATCH_ONLY")
    saved = store.publish(envelope, market="HK_CONNECT")
    receipt_root = case.history.root.parent / "receipts/backfill" / backfill
    config = SimpleNamespace(selection_root=store.root, receipt_root=receipt_root,
                             raw_root=case.root / "legacy_raw", backfill_run_id=backfill)
    owner = SimpleNamespace(config=config, _receipt_path=lambda date, stage: receipt_root / date / stage / "receipt.json")
    deadline = SimpleNamespace(before_receipt=lambda value: deepcopy(value), receipt_written=lambda *args: None)
    receipt = case.runtime.writer._StageCenterRunner__write_receipt_body(
        {"_deadline": deadline, "_atomic_json": write_json,
         "SAFETY_FLAGS": case.runtime.selection.SAFETY_FLAGS, "SelectionStore": case.runtime.selection.SelectionStore},
        owner, {"trade_date": day, "stage_id": STAGE, "dispatch_mode": "RECOVERY",
                "execution_origin": "HISTORICAL_BACKFILL", "due_status": "HISTORICAL_BACKFILL",
                "markets": {"HK_CONNECT": saved}, "write_performed": True, **FLAGS}, day, STAGE)
    verified = store._verify_run(day, STAGE, "HK_CONNECT", saved["run_id"])
    binding = {"selection_run_id": saved["run_id"], **{key: saved[key] for key in (
        "artifact_id", "raw_artifact_sha256", "algorithm_id", "algorithm_sha256",
        "selection_status", "source_status", "selected_rows", "source_rows")},
        "selection_manifest_sha256": verified["manifest_sha256"],
        "selection_receipt_sha256": verified["receipt_sha256"],
        "selection_artifact_sha256": verified["artifact_sha256"],
        "runner_receipt_sha256": digest(receipt_root / day / STAGE / "receipt.json"),
        "cannot_confirm_count": len(saved["cannot_confirm"]), "required_evidence": tuple(saved["source_evidence"])}
    return (day, STAGE, "HK_CONNECT", backfill), binding, store


def test_existing_exact_backfill_keeps_identical_verified_watch_only_response(case):
    reader, _ = prepare_case(case)
    key, binding, store = legacy_binding(case)
    before = route_source(case, phase="before")
    after = route_source(case, research_reader=reader)
    assert before["_APPROVED_EXACT_STAGE_BACKFILLS"] == after["_APPROVED_EXACT_STAGE_BACKFILLS"]
    before["_APPROVED_EXACT_STAGE_BACKFILLS"][key] = deepcopy(binding)
    after["_APPROVED_EXACT_STAGE_BACKFILLS"][key] = deepcopy(binding)
    args = {"date": key[0], "stage": key[1], "market": key[2], "backfill_run_id": key[3], "limit": 50}
    old = before["stage_workbench"](**args)
    new = after["stage_workbench"](**args)
    assert old == new
    assert new["mode"] == "BACKFILL" and new["recommendation_status"] == "WATCH_ONLY"
    assert new["selection_mode"] == "HISTORICAL_BACKFILL_READ_ONLY"
    assert all(row["action_level"] == "NO_BUY" and row["trade_status"] == "WATCH_ONLY" for row in new["unified_rows"])
    assert len(new["unified_rows"]) == 10
    path = store.root / store._latest()["entries"][store._key(key[0], STAGE, "HK_CONNECT")]["artifact_relative"]
    path.write_bytes(path.read_bytes() + b" ")
    for namespace in (before, after):
        with pytest.raises(RouteHTTPException) as exc:
            namespace["stage_workbench"](**args)
        assert exc.value.status_code == 409
