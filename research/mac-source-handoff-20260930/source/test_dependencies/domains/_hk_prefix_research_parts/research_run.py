"""domains.hk_prefix_research: research_run (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global



def _prepare_hk_prefix_run_context(_v4_scope, *, source_path, source_manifest_path, source_sha256, calendar_path, parity_path, binding_path, matched_verdict_path, extractor_path, output, calendar_receipt_path, calendar_code_path):
    source = _v4_global(_v4_scope, 'Path')(source_path)
    source_manifest = _v4_global(_v4_scope, 'Path')(source_manifest_path)
    binding = _v4_global(_v4_scope, 'Path')(binding_path)
    extractor = _v4_global(_v4_scope, 'Path')(extractor_path)
    asset = _v4_global(_v4_scope, 'load_historical_hk_0_2_research_asset')(
        source,
        source_manifest_path=source_manifest,
        expected_sha256=source_sha256,
    )
    calendar = _v4_global(_v4_scope, 'load_frozen_market_calendar')(
        calendar_path,
        parity_path,
        receipt_path=calendar_receipt_path,
        code_path=calendar_code_path,
    )
    groups, binding_meta = _v4_global(_v4_scope, 'load_frozen_group_binding')(
        binding,
        matched_verdict_path=matched_verdict_path,
    )
    scan = _v4_global(_v4_scope, '_load_scan_function')(extractor)
    manifest = _v4_global(_v4_scope, '_manifest_identity')(
        asset,
        calendar,
        binding_meta,
        source_path=source,
        source_manifest_path=source_manifest,
        binding_path=binding,
        extractor_path=extractor,
        extractor_sha256=_v4_global(_v4_scope, 'sha256_file')(extractor),
    )
    run_id = _v4_global(_v4_scope, 'sha256_bytes')(
        _v4_global(_v4_scope, '_canonical_bytes')(
            {
                "source_sha256": asset.source_sha256,
                "source_manifest_sha256": _v4_global(_v4_scope, 'sha256_file')(source_manifest),
                "calendar_sha256": calendar.calendar_sha256,
                "parity_sha256": calendar.parity_sha256,
                "binding_sha256": _v4_global(_v4_scope, 'sha256_file')(binding),
                "matched_sha256": _v4_global(_v4_scope, 'sha256_file')(matched_verdict_path),
                "extractor_sha256": _v4_global(_v4_scope, 'sha256_file')(extractor),
                "prefix_length": _v4_global(_v4_scope, 'PREFIX_LENGTH'),
                "rules": manifest["extractor"]["reference_rules"],
            }
        )
    )
    manifest["run_id"] = run_id
    return {
        "source": source, "source_manifest": source_manifest, "binding": binding,
        "extractor": extractor, "asset": asset, "calendar": calendar,
        "groups": groups, "binding_meta": binding_meta, "scan": scan,
        "manifest": manifest, "run_id": run_id, "matched_verdict_path": matched_verdict_path,
    }


def _materialize_hk_prefix_canary(_v4_scope, *, context, output):
    asset = context["asset"]
    calendar = context["calendar"]
    groups = context["groups"]
    scan = context["scan"]
    manifest = context["manifest"]
    binding = context["binding"]
    matched_verdict_path = context["matched_verdict_path"]
    canary_artifacts = _v4_global(_v4_scope, '_group_artifacts')(
        asset.frame, calendar, groups, scan=scan, group_limit=1
    )
    if _v4_global(_v4_scope, 'len')(canary_artifacts) != 4:
        raise _v4_global(_v4_scope, 'HKPrefixResearchError')("one-group canary did not produce four series")
    canary_root = output / "canary"
    canary_result = _v4_global(_v4_scope, '_write_artifact_set')(
        canary_root, canary_artifacts, groups=groups[:1], write_identity=True
    )
    canary_field = _v4_global(_v4_scope, '_field_check')(canary_artifacts)
    canary_future = _v4_global(_v4_scope, '_future_isolation_check')(canary_artifacts, scan=scan)
    canary_positive = _v4_global(_v4_scope, '_positive_control_check')(scan)
    _v4_global(_v4_scope, '_write_json_new')(canary_root / "field_isolation.json", canary_field)
    _v4_global(_v4_scope, '_write_json_new')(canary_root / "future_isolation.json", canary_future)
    _v4_global(_v4_scope, '_write_json_new')(canary_root / "past_positive_control.json", canary_positive)
    _v4_global(_v4_scope, '_write_json_new')(canary_root / "source_manifest.json", manifest)
    _v4_global(_v4_scope, '_copy_exact_source')(binding, canary_root / "identity" / "frozen_group_binding.json")
    _v4_global(_v4_scope, '_copy_exact_source')(_v4_global(_v4_scope, 'Path')(matched_verdict_path), canary_root / "identity" / "frozen_matched_verdict.csv")
    _v4_global(_v4_scope, '_write_json_new')(
        canary_root / "README.json",
        {
            "status": "CANARY_PASS",
            "group_count": 1,
            "series_count": 4,
            "anonymous_review_status": "NOT_REVIEWED",
            "identity_results_mapping": "identity/results_mapping.csv",
            **_v4_global(_v4_scope, 'SAFETY'),
        },
    )
    return {"canary_artifacts": canary_artifacts, "canary_result": canary_result}


def _materialize_hk_prefix_full_run(_v4_scope, *, context, output):
    asset = context["asset"]
    calendar = context["calendar"]
    groups = context["groups"]
    scan = context["scan"]
    manifest = context["manifest"]
    binding = context["binding"]
    matched_verdict_path = context["matched_verdict_path"]
    full_artifacts = _v4_global(_v4_scope, '_group_artifacts')(asset.frame, calendar, groups, scan=scan)
    if _v4_global(_v4_scope, 'len')(full_artifacts) != 96:
        raise _v4_global(_v4_scope, 'HKPrefixResearchError')("full frozen export did not produce 96 series")
    full_result = _v4_global(_v4_scope, '_write_artifact_set')(
        output, full_artifacts, groups=groups, write_identity=True
    )
    contract_gate = full_result["contract_gate"]
    manifest["metric_contract"] = {
        **manifest["metric_contract"],
        "complete_terminal_pairs": contract_gate["complete_terminal_pairs"],
        "total_pairs": contract_gate["total_pairs"],
        "coverage": contract_gate["coverage"],
        "coverage_status": contract_gate["status"],
    }
    field_check = _v4_global(_v4_scope, '_field_check')(full_artifacts)
    future_check = _v4_global(_v4_scope, '_future_isolation_check')(full_artifacts, scan=scan)
    positive_check = _v4_global(_v4_scope, '_positive_control_check')(scan)
    _v4_global(_v4_scope, '_write_json_new')(output / "tests" / "field_isolation.json", field_check)
    _v4_global(_v4_scope, '_write_json_new')(output / "tests" / "future_isolation.json", future_check)
    _v4_global(_v4_scope, '_write_json_new')(output / "tests" / "past_positive_control.json", positive_check)
    _v4_global(_v4_scope, '_write_json_new')(output / "tests" / "terminal_contract_gate.json", contract_gate)
    _v4_global(_v4_scope, '_write_json_new')(
        output / "tests" / "metrics_contract.json",
        {
            "status": "PASS",
            "version": _v4_global(_v4_scope, 'METRIC_CONTRACT_VERSION'),
            "primary_metric": "TERMINAL_BINARY_INDICATOR",
            "terminal_states": {
                "qualifying": _v4_global(_v4_scope, 'sorted')(_v4_global(_v4_scope, '_QUALIFYING_STATES')),
                "indeterminate": _v4_global(_v4_scope, 'sorted')(_v4_global(_v4_scope, '_INDETERMINATE_TERMINAL_STATES')),
                "non_qualifying_known": _v4_global(_v4_scope, 'sorted')(
                    _v4_global(_v4_scope, '_KNOWN_STATES') - _v4_global(_v4_scope, '_QUALIFYING_STATES') - _v4_global(_v4_scope, '_INDETERMINATE_TERMINAL_STATES')
                ),
            },
            "indeterminate_interval": [0.0, 1.0],
            "delta_bounds": "CASE_LOW_MINUS_CONTROL_HIGH; CASE_HIGH_MINUS_CONTROL_LOW",
            "warmup_terminal_policy": "INDETERMINATE_NOT_KNOWN_NEGATIVE",
            "occupancy_secondary": "WINDOW_OCCUPANCY_DESCRIPTIVE_ONLY",
            "no_fit": True,
        },
    )
    _v4_global(_v4_scope, '_write_json_new')(output / "source_manifest.json", manifest)
    _v4_global(_v4_scope, '_copy_exact_source')(binding, output / "identity" / "frozen_group_binding.json")
    _v4_global(_v4_scope, '_copy_exact_source')(_v4_global(_v4_scope, 'Path')(matched_verdict_path), output / "identity" / "frozen_matched_verdict.csv")
    _v4_global(_v4_scope, '_write_new_bytes')(
        output / "review_material_README.md",
        (
            "# Anonymous HK prefix review material\n\n"
            "The `derived_windows/` CSVs contain exactly the reference whitelist "
            "and no event/control identity or future outcome. `identity/` carries "
            "the separate mapping/results ledger. Manual review status is "
            "`NOT_REVIEWED`; no LLM judgement is substituted.\n"
        ).encode("utf-8"),
    )
    return {"full_artifacts": full_artifacts, "full_result": full_result, "contract_gate": contract_gate}


def _write_hk_prefix_run_receipt(_v4_scope, *, context, canary, full, output):
    groups = context["groups"]
    manifest = context["manifest"]
    run_id = context["run_id"]
    canary_artifacts = canary["canary_artifacts"]
    canary_result = canary["canary_result"]
    full_artifacts = full["full_artifacts"]
    contract_gate = full["contract_gate"]
    acceptance = {
        "data_identity": "PASS",
        "market_day_link": "PASS",
        "frozen_96_export": "PASS",
        "reproducible_run_id": "PASS",
        "unknown_preserved_and_bounded": "PASS",
        "future_isolation": "PASS",
        "past_positive_control": "PASS",
        "terminal_metric_contract": "PASS",
        "terminal_delta_bounds": "PASS",
        "warmup_endpoint_indeterminate": "PASS",
        "terminal_coverage": contract_gate["status"],
        "manual_review": "NOT_REVIEWED",
        "model_fit_calls": 0,
        "network_used": False,
    }
    receipt = {
        "schema_version": _v4_global(_v4_scope, 'SCHEMA_VERSION'),
        "artifact": "ZGE_HISTORY_V4_20260914",
        "status": "RESEARCH_ASSET_READY_NOT_SUPPORTED_TERMINAL_COVERAGE",
        "run_id": run_id,
        "process_count": 1,
        "cpu_threads": 4,
        "canary": {
            "group_count": 1,
            "series_count": _v4_global(_v4_scope, 'len')(canary_artifacts),
            "terminal_states": _v4_global(_v4_scope, 'dict')(_v4_global(_v4_scope, 'Counter')(item.terminal_state for item in canary_artifacts)),
            "artifact_digest": _v4_global(_v4_scope, '_artifact_digest')(canary_artifacts),
        },
        "full": {
            "group_count": _v4_global(_v4_scope, 'len')(groups),
            "series_count": _v4_global(_v4_scope, 'len')(full_artifacts),
            "rows_per_series": _v4_global(_v4_scope, 'PREFIX_LENGTH'),
            "event_type_counts": _v4_global(_v4_scope, 'dict')(_v4_global(_v4_scope, 'Counter')(group.event_type for group in groups)),
            "terminal_states": _v4_global(_v4_scope, 'dict')(_v4_global(_v4_scope, 'Counter')(item.terminal_state for item in full_artifacts)),
            "artifact_digest": _v4_global(_v4_scope, '_artifact_digest')(full_artifacts),
            "complete_terminal_pairs": contract_gate["complete_terminal_pairs"],
            "required_complete_pairs": _v4_global(_v4_scope, 'MIN_COMPLETE_TERMINAL_PAIRS'),
            "coverage_status": contract_gate["status"],
        },
        "metric_contract": manifest["metric_contract"],
        "contract_gate": contract_gate,
        "acceptance": acceptance,
        "outputs": {
            "source_manifest": _v4_global(_v4_scope, 'str')(output / "source_manifest.json"),
            "anonymous_prefix_index": _v4_global(_v4_scope, 'str')(output / "anonymous_prefix_index.csv"),
            "derived_windows": _v4_global(_v4_scope, 'str')(output / "derived_windows"),
            "identity_results_mapping": _v4_global(_v4_scope, 'str')(output / "identity" / "results_mapping.csv"),
            "pair_metrics": _v4_global(_v4_scope, 'str')(output / "pair_metrics.csv"),
            "unknown_bounds": _v4_global(_v4_scope, 'str')(output / "unknown_bounds.csv"),
            "tests": _v4_global(_v4_scope, 'str')(output / "tests"),
        },
        "derived_output_status": "DERIVED_NOT_AUTHORITATIVE_DAILY_PANEL",
        "ui_consumption": {
            "intended_surface": "V4 unified research/review panel",
            "api_or_ui_integration": "CANNOT_CONFIRM_PANEL_CANDIDATE_SEPARATE",
            "required_owner_path_for_future_integration": "apps/api/v35_api/review_router.py and apps/web review surface candidate",
        },
        "cannot_confirm": manifest["cannot_confirm"]
        + ["No API/UI/natural execution verification was performed in this bounded writer batch."],
        **_v4_global(_v4_scope, 'SAFETY'),
    }
    receipt_ref = _v4_global(_v4_scope, '_write_json_new')(output / "receipt.json", receipt)
    return {**receipt, "receipt_file": receipt_ref}


def _run_hk_prefix_research_body(_v4_scope, /, *, source_path, source_manifest_path, source_sha256, calendar_path, parity_path, binding_path, matched_verdict_path, extractor_path, output_dir, calendar_receipt_path, calendar_code_path, cpu_threads):
    """Run the frozen HK research workflow in validation, canary, and full-run phases."""
    if _v4_global(_v4_scope, 'int')(cpu_threads) != 4:
        raise _v4_global(_v4_scope, 'HKPrefixResearchError')("this bounded run requires cpu_threads=4")
    output = _v4_global(_v4_scope, 'Path')(output_dir)
    if output.exists():
        raise _v4_global(_v4_scope, 'HKPrefixResearchError')(f"refuse to overwrite existing output directory: {output}")
    output.mkdir(parents=True)
    context = _prepare_hk_prefix_run_context(
        _v4_scope, source_path=source_path, source_manifest_path=source_manifest_path,
        source_sha256=source_sha256, calendar_path=calendar_path, parity_path=parity_path,
        binding_path=binding_path, matched_verdict_path=matched_verdict_path, extractor_path=extractor_path,
        output=output, calendar_receipt_path=calendar_receipt_path, calendar_code_path=calendar_code_path,
    )
    canary = _materialize_hk_prefix_canary(_v4_scope, context=context, output=output)
    full = _materialize_hk_prefix_full_run(_v4_scope, context=context, output=output)
    return _write_hk_prefix_run_receipt(_v4_scope, context=context, canary=canary, full=full, output=output)
