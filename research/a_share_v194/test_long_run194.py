"""Focused safety tests for the long-history runtime adapter; no model fits."""
from __future__ import annotations

import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

import long_training_adapter as adapter
import long_run194 as runner


def test_native_thread_budget_sets_effective_limits_and_rejects_overcommit():
    env = {}
    configured = adapter.configure_native_thread_budget(
        processes=8, threads_per_process=1, total_thread_budget=12, environ=env
    )
    assert configured["effective_native_threads"] == 8
    assert all(env[name] == "1" for name in adapter.NATIVE_THREAD_VARIABLES)
    assert env["OMP_DYNAMIC"] == "FALSE"
    with pytest.raises(ValueError, match="THREAD_BUDGET_EXCEEDED"):
        adapter.configure_native_thread_budget(
            processes=8, threads_per_process=2, total_thread_budget=12, environ={}
        )


def test_safe_fit_workers_use_canary_rss_memory_and_thread_caps():
    selection = adapter.select_safe_fit_workers(
        requested_workers=8,
        threads_per_worker=1,
        total_thread_budget=12,
        canary_peak_rss_bytes=2_000,
        available_memory_bytes=20_000,
        memory_safety_fraction=0.5,
    )
    assert selection["actual_workers"] == 5
    assert selection["effective_threads"] == 5
    with pytest.raises(ValueError, match="FIT_CANARY_EXCEEDS_MEMORY_SAFETY_HEADROOM"):
        adapter.select_safe_fit_workers(
            requested_workers=8,
            threads_per_worker=2,
            total_thread_budget=12,
            canary_peak_rss_bytes=6_000,
            available_memory_bytes=10_000,
            memory_safety_fraction=0.5,
        )


def _write_input_bindings(tmp_path: Path):
    codes_path = tmp_path / "codes.txt"
    codes_path.write_text("code\n" + "".join(f"{index:06d}.SZ\n" for index in range(1, 5534)), encoding="utf-8")
    code_sha = adapter.sha256_file(codes_path)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({
        "schema": "test",
        "universe_scope": adapter.FROZEN_UNIVERSE_SCOPE,
        "universe_code_count": 5533,
        "universe_code_list_sha256": code_sha,
        "universe_code_list_path": str(codes_path),
        "candidate_truth_same_universe": True,
    }) + "\n", encoding="utf-8")
    manifest_sha = adapter.sha256_file(manifest_path)
    review_path = tmp_path / "review.json"
    review_path.write_text(json.dumps({
        "status": "PASS_LONG_INPUT_PASSPORT",
        "input_manifest_path": str(manifest_path),
        "input_manifest_sha256": manifest_sha,
        "universe_code_list_path": str(codes_path),
        "universe_code_list_sha256": code_sha,
        "universe_code_count": 5533,
        "candidate_truth_same_universe": True,
    }) + "\n", encoding="utf-8")
    return codes_path, manifest_path, manifest_sha, review_path


def test_input_pass_requires_matching_reviewed_manifest(tmp_path: Path):
    codes_path, manifest_path, manifest_sha, review_path = _write_input_bindings(tmp_path)
    code_sha = adapter.sha256_file(codes_path)
    config = {
        "input_manifest": str(manifest_path),
        "input_manifest_path": str(manifest_path),
        "input_manifest_sha256": manifest_sha,
        "frozen_universe": {
            "code_list_path": str(codes_path),
            "code_list_sha256": code_sha,
            "code_count": 5533,
        },
        "independent_input_review": {
            "path": str(review_path),
            "sha256": adapter.sha256_file(review_path),
        },
    }
    assert adapter.verify_independent_input_pass(config)["input_manifest_sha256"] == manifest_sha

    manifest_path.write_text('{"schema":"changed"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="INPUT_MANIFEST_SHA_DRIFT"):
        adapter.verify_independent_input_pass(config)


def test_frozen_universe_requires_sorted_unique_normalized_codes(tmp_path: Path):
    codes_path, manifest_path, manifest_sha, review_path = _write_input_bindings(tmp_path)
    lines = codes_path.read_text(encoding="utf-8").splitlines()
    lines[-1] = lines[-2]
    codes_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    review_path.write_text(json.dumps({
        "status": "PASS_LONG_INPUT_PASSPORT",
        "input_manifest_path": str(manifest_path),
        "input_manifest_sha256": manifest_sha,
        "universe_code_list_path": str(codes_path),
        "universe_code_list_sha256": adapter.sha256_file(codes_path),
        "universe_code_count": 5533,
        "candidate_truth_same_universe": True,
    }) + "\n", encoding="utf-8")
    manifest = adapter.load_json(manifest_path)
    manifest["universe_code_list_sha256"] = adapter.sha256_file(codes_path)
    adapter.atomic_write_json(manifest_path, manifest)
    updated_sha = adapter.sha256_file(manifest_path)
    review = adapter.load_json(review_path)
    review["input_manifest_sha256"] = updated_sha
    adapter.atomic_write_json(review_path, review)
    config = {
        "input_manifest": str(manifest_path),
        "input_manifest_path": str(manifest_path),
        "input_manifest_sha256": updated_sha,
        "frozen_universe": {
            "code_list_path": str(codes_path),
            "code_list_sha256": adapter.sha256_file(codes_path),
            "code_count": 5533,
        },
        "independent_input_review": {
            "path": str(review_path),
            "sha256": adapter.sha256_file(review_path),
        },
    }
    with pytest.raises(ValueError, match="FROZEN_UNIVERSE_DUPLICATE_CODES"):
        adapter.verify_independent_input_pass(config)


def _write_r2_bounded_input_bindings(tmp_path: Path, *, technical_features=None):
    features = technical_features or [
        "tech_192", "B1", "B2", "B3", "BREAKOUT", "BREAKOUT_DOJI", "M2_MINUS", "M2_PLUS",
        "SINGLE_NEEDLE", "THREE_QUARTER_YIN", "BRICK_FANBAO",
    ]
    code_path = tmp_path / "RESEARCH_CODE_KEYS.csv"
    code_path.write_text("code\n" + "".join(f"{index:06d}.SZ\n" for index in range(1, 5534)), encoding="utf-8")
    code_sha = adapter.sha256_file(code_path)
    universe_scope = "Exact accepted 5,533 research code keys; not all-A historical certification."
    label = "close_QFQ_anchor_D(D)/close_QFQ_anchor_D(D-1)-1 using same source and target-D event anchor."
    files = {
        name: {"path": str(tmp_path / f"{name}.csv"), "sha256": (name[0] * 64)}
        for name in ("candidates", "truth", "calendar", "date_policy", "raw_formula_natural")
    }
    parent_path = tmp_path / "parent.json"
    parent = {
        "schema": "V194_DATASET_MANIFEST_V2",
        "universe_scope": universe_scope,
        "research_code_list": {"path": str(code_path), "sha256": code_sha, "count": 5533},
        "technical_features": features,
        "source_state_columns": ["source_fupan", "source_stage7", "source_research"],
        "label_definition": label,
        "formula_identity": "FORMULA255_OFFLINE",
        "signal_date_range": ["20210506", "20261021"],
        "target_date_range": ["20210507", "20261022"],
        "eligible_target_dates": ["2021-01-02"],
        "exposed_targets_excluded": ["2026-10-16", "2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22"],
        "files": {**files, "coverage": {"path": str(tmp_path / "coverage-parent.csv"), "rows": 1, "sha256": "a" * 64},
                  "dictionary": {"path": str(tmp_path / "dictionary-parent.json"), "rows": -1, "sha256": "b" * 64}},
    }
    adapter.atomic_write_json(parent_path, parent)
    parent_sha = adapter.sha256_file(parent_path)
    child_path = tmp_path / "child.json"
    coverage_path = tmp_path / "coverage-r2.csv"
    coverage_path.write_text("target_date\n2021-01-02\n", encoding="utf-8")
    coverage_sha = adapter.sha256_file(coverage_path)
    dictionary_path = tmp_path / "dictionary-r2.json"
    dictionary_path.write_text('{"schema":"R2_TEST_DICTIONARY_V1"}\n', encoding="utf-8")
    dictionary_sha = adapter.sha256_file(dictionary_path)
    child_files = {
        **files,
        "coverage": {"path": str(coverage_path), "rows": 1, "sha256": coverage_sha},
        "dictionary": {"path": str(dictionary_path), "rows": -1, "sha256": dictionary_sha},
    }
    child = {**parent, "files": child_files,
             "parent_manifest": {"path": str(parent_path), "sha256": parent_sha}}
    adapter.atomic_write_json(child_path, child)
    child_sha = adapter.sha256_file(child_path)
    r1_path = tmp_path / "r1-review.json"
    r1 = {
        "manifest": {"path": str(parent_path), "sha256": parent_sha},
        "component_vs_full_status": {"source_code_and_universe_canary_component": "PASS"},
        "verified": {
            "code_list_and_stock_coverage": "PASS_EXACT_FIXED_5533_RESEARCH_POOL_NOT_ALL_A",
            "candidate_tables": {"candidate_keys_unique_ordered_and_within_pool": True},
            "truth": {"all_codes_within_fixed_pool": True},
        },
        "evidence_paths": [{"path": str(code_path), "sha256": code_sha}],
    }
    adapter.atomic_write_json(r1_path, r1)
    r1_sha = adapter.sha256_file(r1_path)
    review_path = tmp_path / "r2-review.json"
    r2 = {
        "decision": "PASS_R2_COVERAGE_METADATA_DELTA",
        "bounded_research_input_readiness": "PASS",
        "whole_input_status": "CANNOT_CONFIRM",
        "maximum_claim": "DIRECTION_ONLY; NOT_HISTORICAL_ALL_A_CERTIFICATION; NO_MODEL_EVALUATION",
        "bounded_research_input_scope": "Current reconstructed research-input metadata and frozen parent bindings only; not a historical point-in-time certification.",
        "coverage_metadata_delta": "PASS",
        "reviewed_binding": {
            "child_manifest": {"path": str(child_path), "sha256": child_sha, "same_build_execution_id": True},
            "parent_manifest": {"path": str(parent_path), "sha256": parent_sha},
            "r1_review_result": {"path": str(r1_path), "sha256": r1_sha},
            "coverage": {"path": str(coverage_path), "rows": 1, "sha256": coverage_sha},
            "data_dictionary": {"path": str(dictionary_path), "sha256": dictionary_sha},
            "registered_event_hashes_recomputed_from_registry": True,
        },
    }
    adapter.atomic_write_json(review_path, r2)
    short_r1_path = tmp_path / "short-r1-source-manifest.json"
    adapter.atomic_write_json(short_r1_path, {"schema": "SHORT_R1_SOURCE_MANIFEST_FIXTURE"})
    short_r1_sha = adapter.sha256_file(short_r1_path)
    build_contract_path = tmp_path / "input-build-contract.json"
    adapter.atomic_write_json(build_contract_path, {
        "execution_id": "A_SHARE_V194_LONG_INPUT_BUILD_FIXTURE",
        "frozen_source_bindings": {str(short_r1_path.resolve()): short_r1_sha},
        "input_identity": {"expected_output_paths": {"input_build_dir": str(parent_path.parent)}},
    })
    config = {
        "input_manifest": str(child_path),
        "input_manifest_path": str(child_path),
        "input_manifest_sha256": child_sha,
        "frozen_universe": {
            "code_list_path": str(code_path),
            "code_list_sha256": code_sha,
            "code_count": 5533,
            "scope": universe_scope,
        },
        "independent_input_review": {"path": str(review_path), "sha256": adapter.sha256_file(review_path)},
        "input_source_lineage": {
            "input_build_contract": {"path": str(build_contract_path), "sha256": adapter.sha256_file(build_contract_path)},
            "short_r1_source_manifest": {"path": str(short_r1_path), "sha256": short_r1_sha},
        },
    }
    return config, review_path


def test_r2_bounded_review_accepts_exact_r2_r1_parent_child_chain(tmp_path: Path):
    config, _ = _write_r2_bounded_input_bindings(tmp_path)

    bound = adapter.verify_independent_input_pass(config)

    assert bound["review_scope"] == "BOUNDED_RECONSTRUCTED_RESEARCH_INPUT"
    assert bound["bounded_research_input_readiness"] == "PASS"
    assert bound["whole_input_status"] == "CANNOT_CONFIRM"
    assert bound["maximum_claim"] == "DIRECTION_ONLY"


def test_r2_bounded_review_rejects_broken_child_manifest_sha(tmp_path: Path):
    config, review_path = _write_r2_bounded_input_bindings(tmp_path)
    review = adapter.load_json(review_path)
    review["reviewed_binding"]["child_manifest"]["sha256"] = "0" * 64
    adapter.atomic_write_json(review_path, review)
    config["independent_input_review"]["sha256"] = adapter.sha256_file(review_path)

    with pytest.raises(ValueError, match="R2_CHILD_MANIFEST_SHA_OR_EXECUTION_DRIFT"):
        adapter.verify_independent_input_pass(config)


def test_r2_bounded_review_rejects_using_full_parent_as_runtime_child(tmp_path: Path):
    config, _ = _write_r2_bounded_input_bindings(tmp_path)
    parent_path = Path(config["input_manifest_path"]).with_name("parent.json")
    config["input_manifest"] = str(parent_path)
    config["input_manifest_path"] = str(parent_path)
    config["input_manifest_sha256"] = adapter.sha256_file(parent_path)

    with pytest.raises(ValueError, match="R2_CHILD_MANIFEST_PATH_DRIFT"):
        adapter.verify_independent_input_pass(config)


def test_r2_bounded_review_rejects_coverage_byte_drift(tmp_path: Path):
    config, _ = _write_r2_bounded_input_bindings(tmp_path)
    manifest = adapter.load_json(Path(config["input_manifest_path"]))
    coverage_path = Path(manifest["files"]["coverage"]["path"])
    coverage_path.write_text(coverage_path.read_text(encoding="utf-8") + "2021-01-03\n", encoding="utf-8")

    with pytest.raises(ValueError, match="R2_METADATA_FILE_SHA_DRIFT:coverage"):
        adapter.verify_independent_input_pass(config)


def test_r2_bounded_review_rejects_incomplete_technical_feature_binding(tmp_path: Path):
    features = [
        "tech_192", "B1", "B2", "B3", "BREAKOUT", "BREAKOUT_DOJI", "M2_MINUS", "M2_PLUS",
        "SINGLE_NEEDLE", "THREE_QUARTER_YIN",
    ]
    config, _ = _write_r2_bounded_input_bindings(tmp_path, technical_features=features)

    with pytest.raises(ValueError, match="CHILD_PARENT_MODEL_BINDING_DRIFT:technical_features|R2_TECHNICAL_FEATURE_BINDING_DRIFT"):
        adapter.verify_independent_input_pass(config)


def _bounded_manifest_fixture(tmp_path: Path, *, technical_features=None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    codes_path = tmp_path / "codes.csv"
    codes_path.write_text("code\n" + "".join(f"{index:06d}.SZ\n" for index in range(1, 5534)), encoding="utf-8")
    features = technical_features or [
        "tech_192", "B1", "B2", "B3", "BREAKOUT", "BREAKOUT_DOJI", "M2_MINUS", "M2_PLUS",
        "SINGLE_NEEDLE", "THREE_QUARTER_YIN", "BRICK_FANBAO",
    ]
    manifest = {
        "research_only": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
        "schema": "V194_DATASET_MANIFEST_V2", "historical_availability_bound": False,
        "semantic_ready": False, "evidence_level": "CANNOT_CONFIRM", "label_historical_vintage": "CANNOT_CONFIRM",
        "official_calendar_parity": "CANNOT_CONFIRM", "passport_status": "NOT_YET_A194_DATASET_PASSPORT_FAST_BIND",
        "lineage_review_pass": False, "design_review_pass": False,
        "formula_identity": "FORMULA255_OFFLINE", "technical_features": features,
        "source_state_columns": ["source_fupan", "source_stage7", "source_research"],
        "label_definition": "close_QFQ_anchor_D(D)/close_QFQ_anchor_D(D-1)-1 using same source and target-D event anchor.",
        "universe_scope": "Exact accepted 5,533 research code keys; not all-A historical certification.",
        "research_code_list": {"count": 5533, "sha256": "a" * 64, "path": str(codes_path)},
        "training_allowed": False, "whole_input_status": "CANNOT_CONFIRM",
    }
    input_pass = {
        "review_scope": "BOUNDED_RECONSTRUCTED_RESEARCH_INPUT", "bounded_research_input_readiness": "PASS",
        "whole_input_status": "CANNOT_CONFIRM", "maximum_claim": "DIRECTION_ONLY",
        "universe_scope": manifest["universe_scope"], "universe_code_count": 5533,
        "universe_code_list_sha256": "a" * 64, "universe_code_list_path": str(codes_path),
    }
    model_module = SimpleNamespace(
        TECHNICAL=[
            "tech_192", "B1", "B2", "B3", "BREAKOUT", "BREAKOUT_DOJI", "M2_MINUS", "M2_PLUS",
            "SINGLE_NEEDLE", "THREE_QUARTER_YIN", "BRICK_FANBAO",
        ],
        SOURCES=["source_fupan", "source_stage7", "source_research"],
    )
    return manifest, input_pass, model_module


def test_bounded_manifest_adapter_accepts_only_the_frozen_research_status(tmp_path: Path):
    manifest, input_pass, model_module = _bounded_manifest_fixture(tmp_path)

    runner._validate_bounded_research_manifest(manifest, synthetic=False, input_pass=input_pass, model_module=model_module)

    assert manifest["semantic_ready"] is False
    assert manifest["evidence_level"] == "CANNOT_CONFIRM"


def test_bounded_manifest_adapter_rejects_semantic_upgrade_and_missing_feature(tmp_path: Path):
    manifest, input_pass, model_module = _bounded_manifest_fixture(tmp_path)
    manifest["semantic_ready"] = True
    with pytest.raises(ValueError, match="BOUNDED_INPUT_SEMANTIC_STATUS_MUST_REMAIN_UNCERTIFIED"):
        runner._validate_bounded_research_manifest(manifest, synthetic=False, input_pass=input_pass, model_module=model_module)

    manifest, input_pass, model_module = _bounded_manifest_fixture(tmp_path / "second")
    manifest["technical_features"] = manifest["technical_features"][:-1]
    with pytest.raises(ValueError, match="TECHNICAL_FEATURE_SET_DRIFT"):
        runner._validate_bounded_research_manifest(manifest, synthetic=False, input_pass=input_pass, model_module=model_module)


def _prepare_parity_fixture(tmp_path: Path, monkeypatch, *, one_class_training=False, denominator_drift=False):
    module_dir = str(Path(runner.__file__).resolve().parent)
    if module_dir not in sys.path:
        sys.path.insert(0, module_dir)
    import model194
    import run194

    dates = [f"2021-01-{day:02d}" for day in range(1, 21)]
    calendar = []
    truth = []
    rows = []
    for index, date in enumerate(dates):
        labels = (1, 1) if one_class_training and index < 10 else (1, 0)
        positive_denominator = sum(labels)
        if denominator_drift and index == 0:
            positive_denominator += 1
        calendar.append({
            "target_date": date,
            "truth_positive_denominator": str(positive_denominator),
        })
        for code_index, label in enumerate(labels, start=1):
            label_text = str(label)
            available = f"{date}T15:00:00+08:00"
            truth.append({"target_date": date, "code": f"{code_index:06d}.SZ", "label": label_text})
            rows.append({
                "target_date": date,
                "code": f"{code_index:06d}.SZ",
                "label": label_text,
                "label_available_at": available,
            })
    manifest = {"eligible_target_dates": dates}
    model_config = {"technical_features": list(model194.TECHNICAL), "top_n": 50, "seed": 194}
    identity = {"manifest_sha256": "a" * 64}
    tables = {"truth": truth, "calendar": calendar}
    monkeypatch.setattr(
        run194,
        "bound_dataset",
        lambda _config: (manifest, tables, rows, model_config, identity),
    )
    pipeline = run194
    config = {"evaluation_asof": "2021-02-01T00:00:00+08:00"}
    return pipeline, config


def test_bounded_prepare_matches_legacy_plan_field_by_field(tmp_path: Path, monkeypatch):
    pipeline, config = _prepare_parity_fixture(tmp_path, monkeypatch)

    legacy = pipeline.prepare(config)
    bounded = runner._prepare_bounded_research_plan(config, pipeline)

    assert bounded == legacy
    assert bounded[-1]["schema"] == "V194_RUN_FREEZE_V2"
    assert bounded[-1]["splits"] == pipeline.m.make_splits(bounded[-1]["eligible_target_dates"])


@pytest.mark.parametrize(
    ("one_class_training", "denominator_drift", "expected_error"),
    [
        (False, True, "TRUTH_DENOMINATOR_DRIFT"),
        (True, False, "TRAIN_REQUIRES_TWO_CLASSES"),
    ],
)
def test_bounded_prepare_preserves_legacy_validation_errors(
    tmp_path: Path, monkeypatch, one_class_training: bool,
    denominator_drift: bool, expected_error: str,
):
    pipeline, config = _prepare_parity_fixture(
        tmp_path,
        monkeypatch,
        one_class_training=one_class_training,
        denominator_drift=denominator_drift,
    )

    messages = []
    for prepare in (
        pipeline.prepare,
        lambda run_config: runner._prepare_bounded_research_plan(run_config, pipeline),
    ):
        with pytest.raises(ValueError, match=expected_error) as raised:
            prepare(config)
        messages.append(str(raised.value))

    assert messages == [expected_error, expected_error]


def test_oof_worker_selection_requires_matching_successful_fit_canary(tmp_path: Path):
    manifest_sha = "a" * 64
    review_sha = "b" * 64
    manifest_path = str(tmp_path / "manifest.json")
    review_path = str(tmp_path / "review.json")
    universe_path = str(tmp_path / "codes.csv")
    canary_path = tmp_path / "canary_terminal.json"
    canary_path.write_text(json.dumps({
        "route_id": "A_SHARE_V194_LONG_HISTORY_AUTHORITY_R1_20261024",
        "execution_id": "A_SHARE_V194_LONG_CANARY_TEST",
        "run_stage": "canary",
        "exit_status": "SUCCESS",
        "runtime_budget": {
            "threads_per_process": 1,
            "input_manifest_sha256": manifest_sha,
            "input_review_sha256": review_sha,
            "fit_counts": {
                "real_fit_entered": 2,
                "real_fit_returned": 2,
                "synthetic_fit_entered": 0,
                "synthetic_fit_returned": 0,
            },
            "fit_canary_identity": {
                "schema_version": "a_share_v194.fit_canary_identity.v1",
                "route_id": "A_SHARE_V194_LONG_HISTORY_AUTHORITY_R1_20261024",
                "input_manifest_path": manifest_path,
                "input_manifest_sha256": manifest_sha,
                "input_review_path": review_path,
                "input_review_sha256": review_sha,
                "universe_code_list_path": universe_path,
                "universe_code_list_sha256": "c" * 64,
                "universe_code_count": 5533,
                "universe_scope": adapter.FROZEN_UNIVERSE_SCOPE,
                "threads_per_process": 1,
                "model_config_sha256": "d" * 64,
                "frozen_identity_sha256": "e" * 64,
                "frozen_plan_sha256": "f" * 64,
                "first_fold_id": "fold_01",
                "first_fold_sha256": "1" * 64,
                "long_runner_code_sha256": adapter.sha256_file(Path(runner.__file__).resolve()),
                "adapter_code_sha256": adapter.sha256_file(Path(adapter.__file__).resolve()),
                "legacy_code_sha256": {
                    "model_code_sha256": "4" * 64,
                    "report_code_sha256": "5" * 64,
                    "runner_code_sha256": "6" * 64,
                },
            },
        },
        "runtime": {"process_peak_rss_bytes": 123456},
    }) + "\n", encoding="utf-8")
    config = {
        "runtime_budget": {"threads_per_process": 1},
        "fit_canary_runtime": {
            "path": str(canary_path),
            "sha256": adapter.sha256_file(canary_path),
        },
    }
    passed = {
        "input_manifest_path": manifest_path,
        "input_manifest_sha256": manifest_sha,
        "review_receipt_path": review_path,
        "review_receipt_sha256": review_sha,
        "universe_code_list_path": universe_path,
        "universe_code_list_sha256": "c" * 64,
        "universe_code_count": 5533,
        "universe_scope": adapter.FROZEN_UNIVERSE_SCOPE,
    }
    result = runner._fit_canary_peak_rss(
        config, passed, route_id="A_SHARE_V194_LONG_HISTORY_AUTHORITY_R1_20261024"
    )
    assert result["peak_rss_bytes"] == 123456
    assert result["fit_counts"]["real_fit_returned"] == 2
    with pytest.raises(ValueError, match="FIT_CANARY_REVIEW_DRIFT"):
        runner._fit_canary_peak_rss(
            config,
            {**passed, "review_receipt_sha256": "c" * 64},
            route_id="A_SHARE_V194_LONG_HISTORY_AUTHORITY_R1_20261024",
        )
    no_fit = json.loads(canary_path.read_text(encoding="utf-8"))
    no_fit["runtime_budget"]["fit_counts"]["real_fit_entered"] = 0
    no_fit["runtime_budget"]["fit_counts"]["real_fit_returned"] = 0
    canary_path.write_text(json.dumps(no_fit) + "\n", encoding="utf-8")
    config["fit_canary_runtime"]["sha256"] = adapter.sha256_file(canary_path)
    with pytest.raises(ValueError, match="FIT_CANARY_REAL_FIT_COUNT_INVALID"):
        runner._fit_canary_peak_rss(
            config, passed, route_id="A_SHARE_V194_LONG_HISTORY_AUTHORITY_R1_20261024"
        )


def test_fit_canary_identity_matches_model_config_and_first_fold():
    input_pass = {
        "input_manifest_path": "/frozen/manifest.json",
        "input_manifest_sha256": "a" * 64,
        "review_receipt_path": "/frozen/review.json",
        "review_receipt_sha256": "b" * 64,
        "universe_code_list_path": "/frozen/codes.csv",
        "universe_code_list_sha256": "c" * 64,
        "universe_code_count": 5533,
        "universe_scope": adapter.FROZEN_UNIVERSE_SCOPE,
    }
    frozen = {
        "identity": {
            "manifest_sha256": "a" * 64,
            "model_code_sha256": "1" * 64,
            "report_code_sha256": "2" * 64,
            "runner_code_sha256": "3" * 64,
        },
        "model_config": {"technical_features": ["tech_192"], "top_n": 50, "seed": 194},
        "splits": [{"id": "fold_01", "train_target_dates": ["2025-01-01"], "evaluation_target_dates": ["2025-02-01"]}],
        "eligible_target_dates": ["2025-01-01", "2025-02-01"],
        "evaluation_asof": "2026-10-23T00:00:00Z",
        "bootstrap": {"seed": 194},
    }
    identity = runner._fit_canary_identity(
        frozen, input_pass, route_id="route", threads_per_process=1
    )
    canary = {"fit_identity": identity}
    runner._verify_fit_canary_identity(
        canary, frozen, input_pass, route_id="route", threads_per_process=1
    )
    changed = {**frozen, "splits": [{**frozen["splits"][0], "id": "fold_02"}]}
    with pytest.raises(ValueError, match="FIT_CANARY_MODEL_FOLD_IDENTITY_DRIFT"):
        runner._verify_fit_canary_identity(
            canary, changed, input_pass, route_id="route", threads_per_process=1
        )


def test_oof_comparison_reports_only_oof_top100_and_three_selection_flags():
    codes = {f"{index:06d}.SZ" for index in range(1, 101)}
    date = "2025-01-02"
    truth = [{"target_date": date, "code": code, "label": "1"} for code in sorted(codes)]
    raw = [{"target_date": date, "code": "000001.SZ", "tech_192": "1"}]
    technical = [{"target_date": date, "code": code} for code in sorted(codes)[:50]]
    v194 = [{"target_date": date, "code": code} for code in sorted(codes)[50:]]
    daily, top100, audit = runner._selection_comparison(
        oof_dates=[date],
        truth_rows=truth,
        raw_natural_rows=raw,
        technical_rows=technical,
        v194_rows=v194,
        calendar_rows=[{"target_date": date, "truth_positive_denominator": "100"}],
        universe_codes=codes,
        fold_for_date={date: "fold_01"},
        fold_source_audit={"fold_01": {
            "any_source_state_variation_seen": False,
            "all_source_lanes_unknown": True,
        }},
    )
    assert len(top100) == 100
    assert all(set(row) == {
        "target_date", "code", "raw_formula255_selected", "technical11_l2_selected", "v194_selected"
    } for row in top100)
    assert daily[0]["raw_formula255_selected"] == 1
    assert daily[0]["raw_formula255_hits"] == 1
    assert daily[0]["technical11_l2_selected"] == 50
    assert daily[0]["v194_selected"] == 50
    assert daily[0]["technical11_l2_equals_v194"] is False
    assert audit["top100_list_rows"] == 100


def test_source_coverage_keeps_unknown_and_confirmed_absent_separate():
    row = {"target_date": "2025-01-02"}
    empty_date = {"target_date": "2025-01-03"}
    for scope, denominator in (("raw", 10), ("model", 8)):
        row[scope + "_source_state_denominator"] = str(denominator)
        empty_date[scope + "_source_state_denominator"] = "0"
        for lane in ("fupan", "stage7", "research"):
            row[f"{scope}_source_{lane}_hit_rows"] = "2"
            row[f"{scope}_source_{lane}_confirmed_absent_rows"] = "0"
            row[f"{scope}_source_{lane}_unknown_rows"] = str(denominator - 2)
            for state in ("hit", "confirmed_absent", "unknown"):
                empty_date[f"{scope}_source_{lane}_{state}_rows"] = "0"
    result = runner._source_coverage_by_year([row, empty_date])
    summary = result["by_year"]["2025"]["scopes"]["raw"]["sources"]["fupan"]
    assert summary["hit_rows"] == 2
    assert summary["confirmed_absent_rows"] == 0
    assert summary["unknown_rows"] == 8
    assert summary["fully_unknown_dates"] == 0
    assert result["by_year"]["2025"]["scopes"]["model"]["state_denominator_rows"] == 8
    assert result["source_state_semantics"].startswith("hit|confirmed_absent|unknown")


def test_daily_model_report_retains_all_dates_and_nulls_non_oof_results():
    dates = ["2025-01-02", "2025-01-03", "2025-01-06", "2025-01-07"]

    def context(date, role, eligible, reason=""):
        row = {
            "target_date": date,
            "cohort_role": role,
            "training_eligible": "true" if eligible else "false",
            "eligibility_exclusion_reason": reason,
            "technical_input_availability": "COMPUTABLE_TECHNICAL_INPUT_DAY",
            "official_calendar_parity": "CANNOT_CONFIRM",
            "truth_positive_denominator": "100",
        }
        for scope, denominator in (("raw", 10), ("model", 8)):
            row[scope + "_source_state_denominator"] = str(denominator)
            for lane in ("fupan", "stage7", "research"):
                row[f"{scope}_source_{lane}_hit_rows"] = "2"
                row[f"{scope}_source_{lane}_confirmed_absent_rows"] = "0"
                row[f"{scope}_source_{lane}_unknown_rows"] = str(denominator - 2)
        return row

    oof_row = {
        "target_date": dates[0],
        "technical11_l2_selected": 49,
        "technical11_l2_hits": 7,
        "v194_selected": 48,
        "v194_hits": 8,
        "technical11_l2_vs_v194_common": 40,
        "technical11_l2_vs_v194_new": 8,
        "technical11_l2_vs_v194_lost": 9,
        "raw_formula255_selected": 6,
        "raw_formula255_hits": 2,
    }
    rows = runner._daily_model_report_rows(
        oof_daily=[oof_row],
        coverage_rows=[
            context(dates[0], "eligible", True),
            context(dates[1], "eligible", True),
            context(dates[2], "excluded_incomplete_truth", False,
                    "INCOMPLETE_CANDIDATE_TRUTH_WHOLE_DATE_EXCLUDED"),
            context(dates[3], "diagnostic", False, "EXPOSED_DIAGNOSTIC_ONLY"),
        ],
        calendar_rows=[{"target_date": date, "truth_positive_denominator": "100"} for date in dates],
    )
    assert [row["target_date"] for row in rows] == dates
    assert rows[0]["status"] == "OOF_EVALUATED"
    assert rows[0]["baseline_id"] == "TECHNICAL11_L2_TOP50"
    assert rows[0]["selection_slots"] == 50
    assert rows[0]["baseline_selected"] == 49 and rows[0]["v194_selected"] == 48
    assert rows[0]["baseline_v194_common"] == 40
    assert rows[0]["formula255_offline_selected"] == 6
    assert rows[0]["raw_source_fupan_unknown_rows"] == 8
    assert rows[1]["status"] == "TRAINING_ONLY"
    assert rows[1]["reason"] == "TRAINING_TARGET_DATE_NOT_EVALUATED_IN_OOF"
    assert rows[1]["baseline_selected"] is None and rows[1]["v194_hits"] is None
    assert rows[2]["status"] == "EXCLUDED"
    assert rows[2]["reason"] == "INCOMPLETE_CANDIDATE_TRUTH_WHOLE_DATE_EXCLUDED"
    assert rows[2]["baseline_selected"] is None and rows[2]["formula255_offline_hits"] is None
    assert rows[3]["status"] == "DIAGNOSTIC"
    assert rows[3]["reason"] == "EXPOSED_DIAGNOSTIC_ONLY"


def test_fold_source_audit_counts_training_rows_and_records_coefficients(tmp_path: Path):
    fold = tmp_path / "fold_01"
    fold.mkdir()
    (fold / "candidate_model.json").write_text(json.dumps({
        "features": ["tech_192", "source_fupan__hit", "source_stage7__unknown"],
        "coef": [0.25, 0.0, 1e-15],
    }), encoding="utf-8")
    rows = [
        {"target_date": "2025-01-02", "source_fupan": "hit", "source_stage7": "unknown", "source_research": "unknown"},
        {"target_date": "2025-01-03", "source_fupan": "unknown", "source_stage7": "unknown", "source_research": "unknown"},
    ]
    model_module = SimpleNamespace(
        SOURCES=("source_fupan", "source_stage7", "source_research"),
        STATES=("hit", "confirmed_absent", "unknown"),
        split_rows=lambda input_rows, split: (input_rows, []),
        load=lambda path: json.loads(Path(path).read_text(encoding="utf-8")),
    )
    audit = runner._fold_source_state_audit(
        rows, [{"id": "fold_01"}], tmp_path, model_module
    )["fold_01"]
    assert audit["source_states"]["source_fupan"]["row_counts"] == {
        "hit": 1, "confirmed_absent": 0, "unknown": 1
    }
    assert audit["source_states"]["source_fupan"]["target_dates_with_state"] == {
        "hit": 1, "confirmed_absent": 0, "unknown": 1
    }
    assert audit["any_source_state_variation_seen"] is True
    assert audit["all_source_lanes_unknown"] is False
    assert audit["candidate_source_feature_coefficients"] == {
        "source_fupan__hit": 0.0, "source_stage7__unknown": 1e-15
    }
    assert audit["all_source_feature_coefficients_zero_with_tolerance_1e-12"] is True


def test_slim_daily_summary_is_name_free_idempotent_and_refuses_drift(tmp_path: Path):
    path = tmp_path / "LONG_DAILY_MODEL_COUNTS.csv"
    rows = [{
        "target_date": "2025-01-02",
        "raw_formula255_selected": 4,
        "raw_formula255_hits": 2,
        "technical11_l2_selected": 50,
        "technical11_l2_hits": 3,
        "v194_selected": 50,
        "v194_hits": 4,
    }]
    columns = list(rows[0])
    first_sha = runner._write_summary_csv_idempotent(path, rows, columns)
    assert first_sha == adapter.sha256_file(path)
    content = path.read_text(encoding="utf-8")
    assert "code" not in content.splitlines()[0]
    assert runner._write_summary_csv_idempotent(path, rows, columns) == first_sha
    changed = [{**rows[0], "v194_hits": 5}]
    with pytest.raises(ValueError, match="SLIM_DAILY_SUMMARY_EXISTS_DIFFERENT"):
        runner._write_summary_csv_idempotent(path, changed, columns)
    assert path.read_text(encoding="utf-8") == content


def test_runner_receipts_bind_pid_checkpoint_and_research_flags(tmp_path: Path):
    artifact = tmp_path / "checkpoint.json"
    artifact.write_text('{"completed":1}\n', encoding="utf-8")
    with adapter.RunnerHeartbeat(
        tmp_path / "run",
        route_id="A_SHARE_V194_LONG_HISTORY_R1_20261024",
        execution_id="A_SHARE_V194_RUNTIME_TEST_01",
        heartbeat_seconds=5,
        runtime_budget={"processes": 1, "threads_per_process": 1},
    ) as runner:
        runner.checkpoint("CANARY", artifact, {"fit_count": 0})

    started = adapter.load_json(tmp_path / "run/RUNNER_STARTED.json")
    terminal = adapter.load_json(tmp_path / "run/RUNNER_TERMINAL.json")
    events = [json.loads(line) for line in (tmp_path / "run/runtime_events.jsonl").read_text().splitlines()]
    assert started["pid"] == terminal["pid"]
    assert terminal["exit_status"] == "SUCCESS"
    assert [event["event"] for event in events] == ["RUNNER_STARTED", "CHECKPOINT", "RUNNER_TERMINAL"]
    assert all(event["research_only"] is True and event["production_allowed"] is False for event in events)
    assert events[1]["artifact_sha256"] == adapter.sha256_file(artifact)


@pytest.mark.parametrize("interrupt", [KeyboardInterrupt("stop"), SystemExit(17)])
def test_registered_runner_appends_terminal_and_reraises_base_exception(
    tmp_path: Path, monkeypatch, interrupt: BaseException,
):
    route_id = "A_SHARE_V194_LONG_HISTORY_AUTHORITY_R1_20261024"
    execution_id = "A_SHARE_V194_INTERRUPT_TEST_01"
    output = tmp_path / "output"
    config_path = tmp_path / "config.json"
    date_config, model_module, _, _ = _date_policy_fixture(tmp_path)
    config_path.write_text(json.dumps({
        "output_dir": str(output),
        **date_config,
        "runtime_budget": {
            "threads_per_process": 1,
            "total_thread_budget": 12,
            "fit_workers": 1,
            "heartbeat_seconds": 5,
        },
    }) + "\n", encoding="utf-8")
    config_sha = adapter.sha256_file(config_path)
    contract_path = tmp_path / "execution.json"
    contract_path.write_text(json.dumps({
        "route_id": route_id,
        "execution_id": execution_id,
        "run_stage": "canary",
        "run_config_path": str(config_path),
        "run_config_sha256": config_sha,
    }) + "\n", encoding="utf-8")

    registry_events = []

    def fake_register(_contract, event_type, stage, *args, decision=None, **kwargs):
        registry_events.append({"event_type": event_type, "stage": stage, "decision": decision})
        return {"event_sha256": f"event-{len(registry_events)}"}

    monkeypatch.setitem(sys.modules, "registry_bridge", SimpleNamespace(register=fake_register))
    monkeypatch.setattr(runner, "verify_independent_input_pass", lambda _config: {
        "input_manifest_sha256": "a" * 64,
        "review_receipt_sha256": "b" * 64,
        "universe_code_list_sha256": "c" * 64,
    })

    def interrupt_stage(_config, _stage, _checkpoint):
        raise interrupt

    fake_legacy = SimpleNamespace(
        m=SimpleNamespace(
            FIT_COUNTS={
                "synthetic_fit_entered": 0,
                "synthetic_fit_returned": 0,
                "real_fit_entered": 0,
                "real_fit_returned": 0,
            },
            make_splits=model_module.make_splits,
        ),
        prepare=lambda _config: None,
        execute_stage=interrupt_stage,
    )
    monkeypatch.setitem(sys.modules, "run194", fake_legacy)

    with pytest.raises(type(interrupt)):
        runner.run_registered_contract(contract_path)

    assert [row["event_type"] for row in registry_events] == ["RUN_STARTED", "TERMINAL"]
    assert registry_events[-1]["stage"] == "CANARY_FAILED"
    assert "FAILED:" + type(interrupt).__name__ in registry_events[-1]["decision"]
    terminal = adapter.load_json(
        output / "_runtime" / execution_id / "canary" / "RUNNER_TERMINAL.json"
    )
    assert terminal["exit_status"] == "FAILED"
    assert terminal["error_type"] == type(interrupt).__name__


def _date_policy_fixture(tmp_path: Path):
    dates = [f"2021-01-{day:02d}" for day in range(1, 21)]

    def make_splits(eligible_dates):
        ordered = sorted(set(eligible_dates))
        initial = len(ordered) // 2
        return [
            {
                "id": f"fold_{index // 5 + 1:02}",
                "train_target_dates": ordered[: initial + index],
                "evaluation_target_dates": ordered[initial + index : initial + index + 5],
            }
            for index in range(0, len(ordered) - initial, 5)
        ]

    splits = make_splits(dates)
    diagnostic_dates = ["2021-02-01"]
    policy_path = tmp_path / "DATE_POLICY.json"
    policy = {
        "schema": "V194_LONG_HISTORY_COMPLETE_CANDIDATE_LABEL_DATE_POLICY_V1",
        "eligible_target_dates": dates,
        "diagnostic_target_dates": diagnostic_dates,
        "planned_model_selection_top_n": 50,
        "input_build_model_fit_count": 0,
        "input_build_oof_count": 0,
        "initial_train_target_dates": splits[0]["train_target_dates"],
        "oof_date_folds": [split["evaluation_target_dates"] for split in splits],
        "oof_target_dates": [
            date for split in splits for date in split["evaluation_target_dates"]
        ],
    }
    adapter.atomic_write_json(policy_path, policy)
    manifest_path = tmp_path / "MANIFEST.json"
    manifest = {
        "eligible_target_dates": dates,
        "exposed_targets_excluded": diagnostic_dates,
        "files": {
            "date_policy": {
                "path": str(policy_path),
                "sha256": adapter.sha256_file(policy_path),
            }
        },
    }
    adapter.atomic_write_json(manifest_path, manifest)
    config = {
        "input_manifest": str(manifest_path),
        "input_manifest_sha256": adapter.sha256_file(manifest_path),
        "date_policy_path": str(policy_path),
        "date_policy_sha256": adapter.sha256_file(policy_path),
    }
    return config, SimpleNamespace(make_splits=make_splits), policy, splits


def test_date_policy_binding_checks_exact_source_and_split_dates(tmp_path: Path):
    config, model_module, policy, splits = _date_policy_fixture(tmp_path)
    bound = runner._verify_date_policy_binding(config, model_module)
    assert bound["eligible_target_dates"] == policy["eligible_target_dates"]
    assert bound["diagnostic_target_dates"] == policy["diagnostic_target_dates"]
    assert bound["expected_splits"] == splits

    frozen = {
        "eligible_target_dates": policy["eligible_target_dates"],
        "splits": splits,
        "model_config": {"top_n": 50},
        "excluded_target_dates": policy["diagnostic_target_dates"],
    }
    runner._verify_date_policy_against_frozen_plan(bound, frozen)


def test_date_policy_binding_rejects_config_hash_and_frozen_fold_drift(tmp_path: Path):
    config, model_module, policy, splits = _date_policy_fixture(tmp_path)
    with pytest.raises(ValueError, match="DATE_POLICY_CONFIG_SHA_DRIFT"):
        runner._verify_date_policy_binding(
            {**config, "date_policy_sha256": "0" * 64}, model_module
        )

    bound = runner._verify_date_policy_binding(config, model_module)
    frozen = {
        "eligible_target_dates": policy["eligible_target_dates"],
        "splits": [*splits[:-1], {**splits[-1], "evaluation_target_dates": ["drift"]}],
        "model_config": {"top_n": 50},
        "excluded_target_dates": policy["diagnostic_target_dates"],
    }
    with pytest.raises(ValueError, match="DATE_POLICY_FROZEN_SPLITS_DRIFT"):
        runner._verify_date_policy_against_frozen_plan(bound, frozen)


def test_date_policy_binding_rejects_manifest_exposed_date_drift(tmp_path: Path):
    config, model_module, _, _ = _date_policy_fixture(tmp_path)
    manifest_path = Path(config["input_manifest"])
    manifest = adapter.load_json(manifest_path)
    manifest["exposed_targets_excluded"] = ["2021-02-02"]
    adapter.atomic_write_json(manifest_path, manifest)
    config["input_manifest_sha256"] = adapter.sha256_file(manifest_path)
    with pytest.raises(ValueError, match="DATE_POLICY_DIAGNOSTIC_DATE_DRIFT"):
        runner._verify_date_policy_binding(config, model_module)
