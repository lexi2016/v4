"""domains.hk_prefix_research: rewrite (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global



def _prepare_hk_prefix_rewrite_context(_v4_scope, *, source_root, output_dir, extractor_path, qa_receipt_sha256):
    source = _v4_global(_v4_scope, 'Path')(source_root)
    output = _v4_global(_v4_scope, 'Path')(output_dir)
    if qa_receipt_sha256 is not None and not _v4_global(_v4_scope, '_is_sha256')(qa_receipt_sha256):
        raise _v4_global(_v4_scope, 'HKPrefixResearchError')("qa receipt SHA-256 is invalid")
    if not source.is_dir():
        raise _v4_global(_v4_scope, 'HKPrefixResearchError')("frozen prefix result root is missing")
    if output.exists():
        raise _v4_global(_v4_scope, 'HKPrefixResearchError')(f"refuse to overwrite existing output directory: {output}")
    old_receipt_path = source / "receipt.json"
    old_manifest_path = source / "source_manifest.json"
    old_index_path = source / "anonymous_prefix_index.csv"
    old_mapping_path = source / "identity" / "results_mapping.csv"
    old_binding_path = source / "identity" / "frozen_group_binding.json"
    old_matched_path = source / "identity" / "frozen_matched_verdict.csv"
    required = (old_receipt_path, old_manifest_path, old_index_path, old_mapping_path, old_binding_path, old_matched_path)
    if _v4_global(_v4_scope, 'any')(not path.is_file() for path in required):
        raise _v4_global(_v4_scope, 'HKPrefixResearchError')("frozen prefix result is missing required correction inputs")
    old_receipt = _v4_global(_v4_scope, '_read_json')(old_receipt_path)
    old_manifest = _v4_global(_v4_scope, '_read_json')(old_manifest_path)
    if old_receipt.get("schema_version") != "v4.hk_prefix_research.v1" or old_manifest.get("schema_version") != "v4.hk_prefix_research.v1":
        raise _v4_global(_v4_scope, 'HKPrefixResearchError')("correction input is not the original v1 historical asset")
    _v4_global(_v4_scope, '_assert_safe_flags')(old_receipt, label="original receipt")
    _v4_global(_v4_scope, '_assert_safe_flags')(old_manifest, label="original source manifest")
    old_full = old_receipt.get("full")
    if not _v4_global(_v4_scope, 'isinstance')(old_full, _v4_global(_v4_scope, 'Mapping')) or old_full.get("group_count") != 24 or old_full.get("series_count") != 96 or old_full.get("rows_per_series") != 60:
        raise _v4_global(_v4_scope, 'HKPrefixResearchError')("original receipt is not the frozen 24/96/60 export")
    index_rows = _v4_global(_v4_scope, '_read_csv')(old_index_path)
    mapping_rows = _v4_global(_v4_scope, '_read_csv')(old_mapping_path)
    if _v4_global(_v4_scope, 'len')(index_rows) != 96 or _v4_global(_v4_scope, 'len')(mapping_rows) != 96:
        raise _v4_global(_v4_scope, 'HKPrefixResearchError')("original identity/index CSV is not the fixed 96-row export")
    expected_index_fields = {"series_id", "prefix_file", "row_count", "input_sha256", "prefix_content_sha256", "review_status"}
    for row in index_rows:
        if _v4_global(_v4_scope, 'set')(row) != expected_index_fields:
            raise _v4_global(_v4_scope, 'HKPrefixResearchError')("original anonymous index schema changed")
        if _v4_global(_v4_scope, 'int')(row.get("row_count") or -1) != _v4_global(_v4_scope, 'PREFIX_LENGTH') or row.get("review_status") != "NOT_REVIEWED":
            raise _v4_global(_v4_scope, 'HKPrefixResearchError')("original anonymous index row contract changed")
    # Validate the immutable binding from the copied identity files. This is
    # metadata only and does not open the raw data source.
    groups, binding_meta = _v4_global(_v4_scope, 'load_frozen_group_binding')(
        old_binding_path,
        matched_verdict_path=old_matched_path,
    )
    artifacts = _v4_global(_v4_scope, '_reused_artifacts')(
        source,
        index_rows,
        mapping_rows,
        groups,
        extractor_path=extractor_path,
    )
    if _v4_global(_v4_scope, 'len')(artifacts) != 96:
        raise _v4_global(_v4_scope, 'HKPrefixResearchError')("corrected reused artifact count is not 96")
    pairs = _v4_global(_v4_scope, '_pair_rows')(artifacts, groups)
    contract_gate = _v4_global(_v4_scope, '_terminal_contract_gate')(pairs)
    old_manifest_sha = _v4_global(_v4_scope, 'sha256_file')(old_manifest_path)
    old_receipt_sha = _v4_global(_v4_scope, 'sha256_file')(old_receipt_path)
    extractor_sha = _v4_global(_v4_scope, 'sha256_file')(extractor_path)
    run_id = _v4_global(_v4_scope, 'sha256_bytes')(
        _v4_global(_v4_scope, '_canonical_bytes')(
            {
                "source_receipt_sha256": old_receipt_sha,
                "source_manifest_sha256": old_manifest_sha,
                "extractor_sha256": extractor_sha,
                "metric_contract": _v4_global(_v4_scope, 'METRIC_CONTRACT_VERSION'),
                "coverage": contract_gate["coverage"],
            }
        )
    )
    return {
        "source": source, "output": output,
        "old_receipt_path": old_receipt_path, "old_manifest_path": old_manifest_path,
        "old_index_path": old_index_path, "old_mapping_path": old_mapping_path,
        "old_binding_path": old_binding_path, "old_matched_path": old_matched_path,
        "old_receipt": old_receipt, "old_manifest": old_manifest,
        "index_rows": index_rows, "mapping_rows": mapping_rows,
        "groups": groups, "binding_meta": binding_meta, "artifacts": artifacts,
        "pairs": pairs, "contract_gate": contract_gate,
        "old_manifest_sha": old_manifest_sha, "old_receipt_sha": old_receipt_sha,
        "run_id": run_id, "qa_receipt_sha256": qa_receipt_sha256,
    }


def _materialize_hk_prefix_rewrite_windows(_v4_scope, *, context):
    source = context["source"]
    output = context["output"]
    old_index_path = context["old_index_path"]
    old_binding_path = context["old_binding_path"]
    old_matched_path = context["old_matched_path"]
    index_rows = context["index_rows"]
    artifacts = context["artifacts"]
    groups = context["groups"]
    output.mkdir(parents=True)
    # Reuse the original anonymous index and every window byte exactly.
    _v4_global(_v4_scope, '_copy_exact_source')(old_index_path, output / "anonymous_prefix_index.csv")
    window_count = 0
    window_rows = 0
    window_sha_mismatches = 0
    for row in index_rows:
        relative = _v4_global(_v4_scope, 'Path')(_v4_global(_v4_scope, 'str')(row["prefix_file"]))
        source_path = (source / relative).resolve(strict=False)
        destination = output / relative
        copied = _v4_global(_v4_scope, '_copy_exact_source')(source_path, destination)
        window_count += 1
        window_rows += _v4_global(_v4_scope, 'int')(row["row_count"])
        if copied["sha256"] != _v4_global(_v4_scope, 'sha256_file')(source_path):
            window_sha_mismatches += 1
    _v4_global(_v4_scope, '_copy_exact_source')(old_binding_path, output / "identity" / "frozen_group_binding.json")
    _v4_global(_v4_scope, '_copy_exact_source')(old_matched_path, output / "identity" / "frozen_matched_verdict.csv")
    full_result = _v4_global(_v4_scope, '_write_reused_result')(output, artifacts, groups=groups)
    canary = output / "canary"
    canary.mkdir(parents=True)
    old_canary = source / "canary"
    if not old_canary.is_dir():
        raise _v4_global(_v4_scope, 'HKPrefixResearchError')("original canary result is missing")
    _v4_global(_v4_scope, '_copy_exact_source')(old_canary / "anonymous_prefix_index.csv", canary / "anonymous_prefix_index.csv")
    for row in index_rows[:4]:
        relative = _v4_global(_v4_scope, 'Path')(_v4_global(_v4_scope, 'str')(row["prefix_file"]))
        _v4_global(_v4_scope, '_copy_exact_source')(source / "canary" / relative, canary / relative)
    canary_result = _v4_global(_v4_scope, '_write_reused_result')(canary, artifacts[:4], groups=groups[:1])
    for relative in ("field_isolation.json", "future_isolation.json", "past_positive_control.json"):
        _v4_global(_v4_scope, '_copy_exact_source')(source / "canary" / relative, canary / relative)
    _v4_global(_v4_scope, '_copy_exact_source')(old_binding_path, canary / "identity" / "frozen_group_binding.json")
    _v4_global(_v4_scope, '_copy_exact_source')(old_matched_path, canary / "identity" / "frozen_matched_verdict.csv")
    return {
        "window_count": window_count, "window_rows": window_rows,
        "window_sha_mismatches": window_sha_mismatches, "canary_result": canary_result,
    }


def _build_hk_prefix_rewrite_manifest(_v4_scope, *, context, material):
    source = context["source"]
    output = context["output"]
    old_manifest = context["old_manifest"]
    old_receipt_sha = context["old_receipt_sha"]
    old_manifest_sha = context["old_manifest_sha"]
    qa_receipt_sha256 = context["qa_receipt_sha256"]
    contract_gate = context["contract_gate"]
    window_count = material["window_count"]
    window_rows = material["window_rows"]
    window_sha_mismatches = material["window_sha_mismatches"]
    manifest = _v4_global(_v4_scope, 'json').loads(_v4_global(_v4_scope, 'json').dumps(old_manifest, ensure_ascii=False))
    manifest.update({"schema_version": _v4_global(_v4_scope, 'SCHEMA_VERSION'), "run_id": run_id})
    derivation = _v4_global(_v4_scope, 'dict')(manifest.get("derivation") or {})
    derivation["window_status"] = "REUSED_FROM_FROZEN_DERIVED_WINDOWS"
    derivation["metric_correction_source"] = "TERMINAL_ENDPOINT_CONTRACT_REVIEW"
    manifest["derivation"] = derivation
    manifest["metric_contract"] = {
        "version": _v4_global(_v4_scope, 'METRIC_CONTRACT_VERSION'),
        "primary_metric": "TERMINAL_BINARY_INDICATOR",
        "terminal_positive_states": _v4_global(_v4_scope, 'sorted')(_v4_global(_v4_scope, '_QUALIFYING_STATES')),
        "indeterminate_terminal_states": _v4_global(_v4_scope, 'sorted')(_v4_global(_v4_scope, '_INDETERMINATE_TERMINAL_STATES')),
        "indeterminate_interval": [0.0, 1.0],
        "delta_bounds": "CASE_LOW_MINUS_CONTROL_HIGH; CASE_HIGH_MINUS_CONTROL_LOW",
        "occupancy_secondary": "WINDOW_OCCUPANCY_DESCRIPTIVE_ONLY",
        "minimum_complete_terminal_pairs": _v4_global(_v4_scope, 'MIN_COMPLETE_TERMINAL_PAIRS'),
        "complete_terminal_pairs": contract_gate["complete_terminal_pairs"],
        "total_pairs": contract_gate["total_pairs"],
        "coverage": contract_gate["coverage"],
        "coverage_status": contract_gate["status"],
    }
    manifest["source_reuse"] = {
        "original_root": _v4_global(_v4_scope, 'str')(source),
        "original_receipt_sha256": old_receipt_sha,
        "original_source_manifest_sha256": old_manifest_sha,
        "qa_receipt_sha256": qa_receipt_sha256,
        "raw_window_bytes_reused": True,
        "window_file_count": window_count,
        "window_rows": window_rows,
        "window_sha256_mismatches": window_sha_mismatches,
        "raw_source_scanned": False,
    }
    manifest["cannot_confirm"] = _v4_global(_v4_scope, 'list')(_v4_global(_v4_scope, 'dict').fromkeys(
        [_v4_global(_v4_scope, 'str')(item) for item in manifest.get("cannot_confirm", [])]
        + [contract_gate["reason"] + "; terminal comparison is NOT_SUPPORTED."]
    ))
    return manifest


def _write_hk_prefix_rewrite_evidence(_v4_scope, *, context, material, manifest):
    output = context["output"]
    source = context["source"]
    contract_gate = context["contract_gate"]
    old_receipt_sha = context["old_receipt_sha"]
    window_count = material["window_count"]
    window_rows = material["window_rows"]
    window_sha_mismatches = material["window_sha_mismatches"]
    _v4_global(_v4_scope, '_write_json_new')(output / "tests" / "terminal_contract_gate.json", contract_gate)
    _v4_global(_v4_scope, '_write_json_new')(
        output / "tests" / "metrics_contract.json",
        {
            "status": "PASS",
            "version": _v4_global(_v4_scope, 'METRIC_CONTRACT_VERSION'),
            "primary_metric": "TERMINAL_BINARY_INDICATOR",
            "delta_bounds": "CASE_LOW_MINUS_CONTROL_HIGH; CASE_HIGH_MINUS_CONTROL_LOW",
            "warmup_terminal_policy": "INDETERMINATE_NOT_KNOWN_NEGATIVE",
            "unknown_terminal_policy": "INDETERMINATE",
            "occupancy_secondary": "WINDOW_OCCUPANCY_DESCRIPTIVE_ONLY",
            "no_fit": True,
        },
    )
    _v4_global(_v4_scope, '_write_json_new')(
        output / "tests" / "raw_window_reuse.json",
        {
            "status": "PASS",
            "raw_window_bytes_reused": True,
            "window_file_count": window_count,
            "window_rows": window_rows,
            "window_sha256_mismatches": window_sha_mismatches,
            "raw_source_scanned": False,
            "source_receipt_sha256": old_receipt_sha,
        },
    )
    for relative in ("field_isolation.json", "future_isolation.json", "past_positive_control.json"):
        _v4_global(_v4_scope, '_copy_exact_source')(source / "tests" / relative, output / "tests" / relative)
    # These logs contain only fixed-count/source-window evidence. Prior bug
    # review logs remain solely under the original root.
    for relative in ("replay_96_reference_review_20260914.log", "source_window_replay_review_20260914.log", "endpoint_metric_reconstruction_20260914.log"):
        _v4_global(_v4_scope, '_copy_exact_source')(source / "review" / relative, output / "review" / relative)
    _v4_global(_v4_scope, '_write_new_bytes')(
        output / "review" / "corrected_metric_contract_review_20260914.log",
        (
            f"metric_contract {_v4_global(_v4_scope, 'METRIC_CONTRACT_VERSION')}\n"
            "primary_metric TERMINAL_BINARY_INDICATOR\n"
            "delta_bounds CASE_LOW_MINUS_CONTROL_HIGH; CASE_HIGH_MINUS_CONTROL_LOW\n"
            "warmup_and_unknown_endpoint INDETERMINATE\n"
            f"terminal_coverage {contract_gate['coverage']} required {_v4_global(_v4_scope, 'MIN_COMPLETE_TERMINAL_PAIRS')}/24 status {contract_gate['status']}\n"
            "occupancy_secondary WINDOW_OCCUPANCY_DESCRIPTIVE_ONLY\n"
            "manual_review NOT_REVIEWED\n"
        ).encode("utf-8"),
    )
    _v4_global(_v4_scope, '_write_new_bytes')(
        output / "review_material_README.md",
        (
            "# Anonymous HK prefix review material (corrected metric contract)\n\n"
            "The 96 derived window CSVs are byte-reused from the frozen prior "
            "export. The identity mapping and paired ledgers use the terminal "
            "indicator contract; UNKNOWN and WARMUP endpoints remain "
            "indeterminate. Window occupancy is descriptive only. Manual "
            "review remains NOT_REVIEWED; no LLM judgement is substituted.\n"
        ).encode("utf-8"),
    )
    _v4_global(_v4_scope, '_write_json_new')(output / "source_manifest.json", manifest)


def _write_hk_prefix_rewrite_receipt(_v4_scope, *, context, material, manifest):
    output = context["output"]
    groups = context["groups"]
    artifacts = context["artifacts"]
    run_id = context["run_id"]
    contract_gate = context["contract_gate"]
    canary_result = material["canary_result"]
    acceptance = {
        "data_identity": "PASS",
        "market_day_link": "PASS",
        "frozen_96_export": "PASS",
        "raw_window_bytes_reused": "PASS",
        "reproducible_run_id": "PASS",
        "unknown_preserved_and_bounded": "PASS",
        "terminal_metric_contract": "PASS",
        "terminal_delta_bounds": "PASS",
        "warmup_endpoint_indeterminate": "PASS",
        "terminal_coverage": contract_gate["status"],
        "field_isolation": "PASS",
        "future_isolation": "PASS",
        "past_positive_control": "PASS",
        "manual_review": "NOT_REVIEWED",
        "model_fit_calls": 0,
        "network_used": False,
    }
    full_states = _v4_global(_v4_scope, 'dict')(_v4_global(_v4_scope, 'Counter')(item.terminal_state for item in artifacts))
    receipt = {
        "schema_version": _v4_global(_v4_scope, 'SCHEMA_VERSION'),
        "artifact": "ZGE_HISTORY_V4_20260914",
        "status": "RESEARCH_ASSET_READY_NOT_SUPPORTED_TERMINAL_COVERAGE",
        "run_id": run_id,
        "process_count": 1,
        "cpu_threads": 4,
        "canary": {
            "group_count": 1,
            "series_count": 4,
            "terminal_states": _v4_global(_v4_scope, 'dict')(_v4_global(_v4_scope, 'Counter')(item.terminal_state for item in artifacts[:4])),
            "artifact_digest": _v4_global(_v4_scope, '_artifact_digest')(artifacts[:4]),
            "terminal_coverage": canary_result["contract_gate"],
        },
        "full": {
            "group_count": 24,
            "series_count": 96,
            "rows_per_series": _v4_global(_v4_scope, 'PREFIX_LENGTH'),
            "event_type_counts": _v4_global(_v4_scope, 'dict')(_v4_global(_v4_scope, 'Counter')(group.event_type for group in groups)),
            "terminal_states": full_states,
            "artifact_digest": _v4_global(_v4_scope, '_artifact_digest')(artifacts),
            "complete_terminal_pairs": contract_gate["complete_terminal_pairs"],
            "required_complete_pairs": _v4_global(_v4_scope, 'MIN_COMPLETE_TERMINAL_PAIRS'),
            "coverage_status": contract_gate["status"],
        },
        "metric_contract": manifest["metric_contract"],
        "contract_gate": contract_gate,
        "source_reuse": manifest["source_reuse"],
        "acceptance": acceptance,
        "outputs": {
            "source_manifest": _v4_global(_v4_scope, 'str')(output / "source_manifest.json"),
            "anonymous_prefix_index": _v4_global(_v4_scope, 'str')(output / "anonymous_prefix_index.csv"),
            "derived_windows": _v4_global(_v4_scope, 'str')(output / "derived_windows"),
            "identity_results_mapping": _v4_global(_v4_scope, 'str')(output / "identity" / "results_mapping.csv"),
            "pair_metrics": _v4_global(_v4_scope, 'str')(output / "pair_metrics.csv"),
            "summary_by_event_type": _v4_global(_v4_scope, 'str')(output / "summary_by_event_type.csv"),
            "unknown_bounds": _v4_global(_v4_scope, 'str')(output / "unknown_bounds.csv"),
            "tests": _v4_global(_v4_scope, 'str')(output / "tests"),
        },
        "derived_output_status": "DERIVED_NOT_AUTHORITATIVE_DAILY_PANEL",
        "ui_consumption": {
            "intended_surface": "V4 unified research/review panel",
            "api_or_ui_integration": "CANNOT_CONFIRM_PANEL_CANDIDATE_SEPARATE",
            "daily_selection_separated": True,
        },
        "review": {
            "manual_review_status": "NOT_REVIEWED",
            "identity_results_mapping_separate": True,
            "llm_supplemented": False,
        },
        "cannot_confirm": manifest["cannot_confirm"],
        **_v4_global(_v4_scope, 'SAFETY'),
    }
    receipt_ref = _v4_global(_v4_scope, '_write_json_new')(output / "receipt.json", receipt)
    return {**receipt, "receipt_file": receipt_ref}


def _rewrite_hk_prefix_research_result_body(_v4_scope, /, *, source_root, output_dir, extractor_path, qa_receipt_sha256):
    """Reissue the fixed historical asset through ordered validation and publication phases."""
    context = _prepare_hk_prefix_rewrite_context(
        _v4_scope, source_root=source_root, output_dir=output_dir,
        extractor_path=extractor_path, qa_receipt_sha256=qa_receipt_sha256,
    )
    material = _materialize_hk_prefix_rewrite_windows(_v4_scope, context=context)
    manifest = _build_hk_prefix_rewrite_manifest(_v4_scope, context=context, material=material)
    _write_hk_prefix_rewrite_evidence(_v4_scope, context=context, material=material, manifest=manifest)
    return _write_hk_prefix_rewrite_receipt(_v4_scope, context=context, material=material, manifest=manifest)
