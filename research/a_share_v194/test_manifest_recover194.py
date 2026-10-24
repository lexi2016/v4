"""Only synthetic saved-output recovery; no real input or numerical engine."""
import csv
import json
from pathlib import Path

import pytest

import manifest_recover194 as recovery


def test_manifest_only_recovery_preserves_outputs_and_exact_count_roles(tmp_path, monkeypatch):
    root = tmp_path / "new_evidence"
    build = root / "inputs/original"
    canary = root / "build/canary"
    build.mkdir(parents=True)
    canary.mkdir(parents=True)
    monkeypatch.setattr(recovery, "EVIDENCE_ROOT", root)
    monkeypatch.setattr(recovery, "EXPECTED_CODE_COUNT", 2)
    def js(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, sort_keys=True))
        return dict(path=str(path), sha256=recovery.sha_file(path))
    def csvfile(name, rows):
        path = build / name
        with path.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
    keys = ["000001.SZ", "600000.SH"]
    csvfile("RESEARCH_CODE_KEYS.csv", [dict(code=c) for c in keys])
    csvfile("STOCK_COVERAGE.csv", [dict(code=keys[0], candidate_union_rows=2, raw_formula_natural_rows=1,
             technical_candidate_exclusions=1), dict(code=keys[1], candidate_union_rows=2,
             raw_formula_natural_rows=1, technical_candidate_exclusions=0)])
    for name, size in [("RAW_FORMULA_NATURAL.csv", 2), ("RAW_CANDIDATE_UNION.csv", 4),
                       ("candidates.csv", 3), ("truth.csv", 5), ("SOURCE_AXES.csv", 2)]:
        csvfile(name, [dict(code=keys[i % 2], row=i, note="unknown" if name == "truth.csv" and i == 4 else "saved") for i in range(size)])
    dates = ["2001-01-02", "2001-01-03", "2026-10-16"]
    calendar = [dict(target_date=day, signal_date=signal, truth_rankable_research_rows=rankable,
                     truth_positive_denominator=rankable, selection_slots=0, candidate_rows=1,
                     raw_candidate_union_rows=2 if i == 0 else 1)
                for i, (day, signal, rankable) in enumerate(zip(dates, ["2001-01-01", "2001-01-02", "2026-10-15"], [2, 1, 1]))]
    csvfile("calendar.csv", calendar)
    csvfile("coverage.csv", calendar)
    js(build / "TECHNICAL_EXCLUSIONS.json", [dict(code=keys[0], reason="SAVED_UNKNOWN")])
    policy = dict(eligible_target_dates=dates[:2], initial_train_target_dates=dates[:1],
                  oof_target_dates=dates[1:2], excluded_incomplete_target_dates=[],
                  all_incomplete_target_dates=[], effect_acceptance_ceiling="DIRECTION_ONLY")
    js(build / "DATE_POLICY.json", policy)
    dictionary = dict(panel_numeric_policy="Float32 values consumed as stored; no round, int cast, or rescaling.",
                      label_definition="close_QFQ_anchor_D(D)/close_QFQ_anchor_D(D-1)-1 using same source and target-D event anchor.")
    js(build / "DATA_DICTIONARY.json", dictionary)
    raw = root / "raw_never_read.parquet"
    raw.write_bytes(b"no numerical engine may read this")
    locator = root / "locator.txt"
    locator.write_text(str(raw))
    snapshot = js(root / "snapshot.json", dict(panel_bindings=dict(backtest=dict(
        pointer_path=str(locator), pointer_sha256=recovery.sha_file(locator), target_sha256="b" * 64)),
        selected_panel_schema=dict(conversion_rule="RAW8 float64 OHLC/amount and uint64 vol preserved; exact uint64-to-model conversion")))
    raw_binding = js(root / "raw_binding.json", dict(raw_artifact=dict(path=str(raw), sha256="b" * 64),
                     raw_projection_result=dict(path="/immutable/producer.json", sha256="c" * 64)))
    orig_id = "ORIGINAL_FAILED_PRODUCER"
    contract = js(root / "original_contract.json", dict(execution_id=orig_id))
    start = js(root / "original_start.json", dict(execution_id=orig_id, event_type="RUN_STARTED", event_sha256="d" * 64))
    original = dict(execution_id=orig_id, build_dir=str(build), canary_dir=str(canary), contract=contract,
                    panel_snapshot=snapshot, start_receipt=start, start_event_sha256="d" * 64,
                    engine_source_bindings={}, source_manifest=dict(path="/frozen/source.json", sha256="e" * 64),
                    history_binding=dict(qfq_manifest=raw_binding))
    original_ref = js(root / "original_config.json", original)
    template = Path(recovery.__file__).with_name("long_data194.py")
    assert recovery.sha_file(template) == recovery.TEMPLATE_SHA
    identity = dict(build_config_sha256=recovery.canonical_sha(original), implementation_sha256=recovery.TEMPLATE_SHA,
                    contract_sha256=contract["sha256"], panel_snapshot_sha256=snapshot["sha256"],
                    start_receipt_sha256=start["sha256"], panel_target_path=str(raw), panel_target_stat=recovery.panel_stat(raw),
                    accepted64_manifest_sha256="f" * 64, research_code_count=2,
                    research_code_list_sha256=recovery.sha_file(build / "RESEARCH_CODE_KEYS.csv"))
    identity_ref = js(build / "BUILD_IDENTITY.json", identity)
    scan = js(build / "PANEL_SCAN_RECEIPT.json", dict(panel_rows_scanned=10, pool_rows_retained=10))
    projection = js(build / "_intermediate/processing/PROJECTION_RESOURCE_RECEIPT.json",
                    dict(codes=2, identity_sha256=recovery.canonical_sha(identity)))
    canary_ref = js(canary / "RECEIPT.json", dict(build_identity_sha256=recovery.canonical_sha(identity)))
    failed = js(root / "failed_terminal.json", dict(child_returncode=1, fit_count=0, execution_id=orig_id))
    new_id = "METADATA_RECOVERY"
    new_contract = js(root / "recovery_contract.json", dict(execution_id=new_id))
    new_start = js(root / "recovery_start.json", dict(execution_id=new_id, event_type="RUN_STARTED", event_sha256="1" * 64))
    config = dict(schema="V194_MANIFEST_ONLY_RECOVERY_CONFIG_V1", execution_id=new_id,
                  output_dir=str(root / "inputs/recovered"), recovery_source_sha256=recovery.sha_file(recovery.__file__),
                  contract=new_contract, start_receipt=new_start, start_event_sha256="1" * 64,
                  original_build_config=original_ref, original_build_identity=identity_ref,
                  original_source=dict(path=str(template), sha256=recovery.TEMPLATE_SHA), original_failed_terminal=failed,
                  panel_scan_receipt=scan, projection_receipt=projection, canary_receipt=canary_ref,
                  original_source_code_bindings={str(template):recovery.TEMPLATE_SHA},
                  saved_outputs={key:dict(path=str(build/name), stat=recovery.panel_stat(build/name))
                                 for key,name in recovery.OUTPUT_FILES.items()})
    before = {p:p.read_bytes() for p in build.iterdir() if p.is_file()}
    real_sha = recovery.sha_file
    def no_raw_or_npz_read(path):
        assert Path(path) != raw and Path(path).suffix != ".npz"
        return real_sha(path)
    monkeypatch.setattr(recovery, "sha_file", no_raw_or_npz_read)
    result = recovery.recover(config)
    manifest = recovery.load_json(result["manifest_path"])
    assert result["truth_rows"] == manifest["truth_rows"] == 4
    assert result["physical_truth_file_rows"] == manifest["files"]["truth"]["rows"] == 5
    assert list(manifest["truth_positive_denominator_by_date"].values()) == [2, 1, 1]
    assert set(manifest["selection_slots_by_date"].values()) == {0}
    assert (manifest["candidate_rows"],manifest["raw_candidate_union_rows"],manifest["raw_formula_natural_rows"],manifest["technical_candidate_exclusions"]) == (3,4,2,1)
    assert manifest["panel_binding"]["target_sha256_status"] == "RAW_PROJECTION_RECEIPT_BOUND"
    assert manifest["panel_binding"]["target_sha256_declared"] == "b" * 64
    assert manifest["historical_availability_bound"] is False and manifest["maximum_claim"] == "DIRECTION_ONLY"
    assert "NOT_LIVE_CURRENT" in manifest["calendar_source"]
    assert manifest["metadata_recovery"]["original_producer_execution_id"] == orig_id
    assert result["execution_id"] == new_id and result["fit_count"] == 0
    corrected = recovery.load_json(manifest["files"]["dictionary"]["path"])
    assert corrected["panel_numeric_policy"].startswith("RAW8 float64")
    assert {**corrected, "panel_numeric_policy": dictionary["panel_numeric_policy"]} == dictionary
    assert all(p.read_bytes() == content for p,content in before.items())
    # The actual consumer accepts absolute references to the unchanged old tables.
    from long_run194 import _read_bound_manifest_csv
    assert len(_read_bound_manifest_csv(manifest, Path(result["manifest_path"]), "candidates", recovery.saved_csv)) == 3
    with (build / "truth.csv").open("a") as stream:
        stream.write("drift\n")
    changed = {**config, "output_dir":str(root/"inputs/drift_rejected")}
    with pytest.raises(ValueError, match="SAVED_OUTPUT_STAT_DRIFT"):
        recovery.recover(changed)
    assert not Path(changed["output_dir"]).exists()
