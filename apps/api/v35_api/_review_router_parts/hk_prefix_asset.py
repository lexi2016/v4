"""apps.api.v35_api.review_router: hk_prefix_asset (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global



def _load_hk_prefix_panel_evidence(_v4_scope, requested_date, *, configured_binding, root_value):
    binding_path = _v4_global(_v4_scope, '_panel_safe_binding_path')(configured_binding)
    binding = _v4_global(_v4_scope, '_panel_read_json')(binding_path)
    if binding.get("schema_version") != "v4.hk_prefix_research.runtime_binding.v1":
        raise _v4_global(_v4_scope, 'ValueError')("runtime binding schema mismatch")
    if binding.get("asset_id") != _v4_global(_v4_scope, '_HK_PREFIX_ASSET_ID'):
        raise _v4_global(_v4_scope, 'ValueError')("runtime binding asset mismatch")
    _v4_global(_v4_scope, '_panel_safety')(binding, label="runtime binding")
    bound_root = _v4_global(_v4_scope, 'Path')(_v4_global(_v4_scope, 'str')(binding.get("root") or "")).expanduser()
    if not bound_root.is_absolute() or ".." in bound_root.parts:
        raise _v4_global(_v4_scope, 'ValueError')("runtime binding root is unsafe")
    bound_root = bound_root.resolve(strict=False)
    if root_value is not None:
        configured_root = _v4_global(_v4_scope, 'Path')(_v4_global(_v4_scope, 'str')(root_value)).expanduser()
        if not configured_root.is_absolute() or ".." in configured_root.parts:
            raise _v4_global(_v4_scope, 'ValueError')("configured historical root is unsafe")
        if configured_root.resolve(strict=False) != bound_root:
            raise _v4_global(_v4_scope, 'ValueError')("configured historical root does not match runtime binding")
    root = bound_root
    if not root.is_dir():
        raise _v4_global(_v4_scope, 'FileNotFoundError')("historical prefix asset root is absent")
    file_specs = binding.get("files")
    if not _v4_global(_v4_scope, 'isinstance')(file_specs, _v4_global(_v4_scope, 'Mapping')) or _v4_global(_v4_scope, 'set')(file_specs) != _v4_global(_v4_scope, '_HK_PREFIX_FILE_KEYS'):
        raise _v4_global(_v4_scope, 'ValueError')("runtime binding file set mismatch")
    files: dict[str, tuple[Path, str]] = {}
    for key in _v4_global(_v4_scope, 'sorted')(_v4_global(_v4_scope, '_HK_PREFIX_FILE_KEYS')):
        spec = file_specs.get(key)
        if not _v4_global(_v4_scope, 'isinstance')(spec, _v4_global(_v4_scope, 'Mapping')):
            raise _v4_global(_v4_scope, 'ValueError')("runtime binding file entry is invalid")
        relative = _v4_global(_v4_scope, 'str')(spec.get("path") or "")
        expected_sha = _v4_global(_v4_scope, '_panel_sha')(spec.get("sha256"), field=f"binding.files.{key}")
        path = _v4_global(_v4_scope, '_panel_safe_relative')(root, relative)
        if not path.is_file() or _v4_global(_v4_scope, '_panel_sha256')(path) != expected_sha:
            raise _v4_global(_v4_scope, 'ValueError')(f"fixed evidence digest mismatch: {key}")
        files[key] = (path, expected_sha)
    receipt = _v4_global(_v4_scope, '_panel_read_json')(files["receipt"][0])
    source_manifest = _v4_global(_v4_scope, '_panel_read_json')(files["source_manifest"][0])
    if receipt.get("schema_version") != _v4_global(_v4_scope, '_HK_PREFIX_ASSET_SCHEMA'):
        raise _v4_global(_v4_scope, 'ValueError')("historical receipt schema mismatch")
    if receipt.get("artifact") != _v4_global(_v4_scope, '_HK_PREFIX_ASSET_ID'):
        raise _v4_global(_v4_scope, 'ValueError')("historical receipt asset mismatch")
    if receipt.get("run_id") != binding.get("run_id"):
        raise _v4_global(_v4_scope, 'ValueError')("historical receipt run mismatch")
    if receipt.get("status") != "RESEARCH_ASSET_READY_NOT_SUPPORTED_TERMINAL_COVERAGE":
        raise _v4_global(_v4_scope, 'ValueError')("historical receipt status is not the corrected research status")
    _v4_global(_v4_scope, '_panel_safety')(receipt, label="historical receipt")
    if source_manifest.get("schema_version") != _v4_global(_v4_scope, '_HK_PREFIX_ASSET_SCHEMA'):
        raise _v4_global(_v4_scope, 'ValueError')("historical source manifest schema mismatch")
    if source_manifest.get("asset_id") != _v4_global(_v4_scope, '_HK_PREFIX_ASSET_ID'):
        raise _v4_global(_v4_scope, 'ValueError')("historical source manifest asset mismatch")
    if source_manifest.get("run_id") != binding.get("run_id"):
        raise _v4_global(_v4_scope, 'ValueError')("historical source manifest run mismatch")
    _v4_global(_v4_scope, '_panel_safety')(source_manifest, label="historical source manifest")

    source = source_manifest.get("source")
    calendar = source_manifest.get("calendar")
    derivation = source_manifest.get("derivation")
    binding_meta = source_manifest.get("binding")
    review_meta = source_manifest.get("review")
    metric_contract = source_manifest.get("metric_contract")
    if not _v4_global(_v4_scope, 'all')(_v4_global(_v4_scope, 'isinstance')(item, _v4_global(_v4_scope, 'Mapping')) for item in (source, calendar, derivation, binding_meta, review_meta, metric_contract)):
        raise _v4_global(_v4_scope, 'ValueError')("historical source manifest sections are incomplete")
    assert _v4_global(_v4_scope, 'isinstance')(source, _v4_global(_v4_scope, 'Mapping'))
    assert _v4_global(_v4_scope, 'isinstance')(calendar, _v4_global(_v4_scope, 'Mapping'))
    assert _v4_global(_v4_scope, 'isinstance')(derivation, _v4_global(_v4_scope, 'Mapping'))
    assert _v4_global(_v4_scope, 'isinstance')(binding_meta, _v4_global(_v4_scope, 'Mapping'))
    assert _v4_global(_v4_scope, 'isinstance')(review_meta, _v4_global(_v4_scope, 'Mapping'))
    assert _v4_global(_v4_scope, 'isinstance')(metric_contract, _v4_global(_v4_scope, 'Mapping'))
    if (
        metric_contract.get("version") != _v4_global(_v4_scope, '_HK_PREFIX_METRIC_CONTRACT')
        or metric_contract.get("primary_metric") != "TERMINAL_BINARY_INDICATOR"
        or metric_contract.get("delta_bounds")
        != "CASE_LOW_MINUS_CONTROL_HIGH; CASE_HIGH_MINUS_CONTROL_LOW"
        or metric_contract.get("occupancy_secondary")
        != "WINDOW_OCCUPANCY_DESCRIPTIVE_ONLY"
    ):
        raise _v4_global(_v4_scope, 'ValueError')("historical metric contract is incomplete")
    source_sha = _v4_global(_v4_scope, '_panel_sha')(source.get("sha256"), field="source.sha256")
    source_manifest_declared_sha = _v4_global(_v4_scope, '_panel_sha')(
        source.get("manifest_sha256"), field="source.manifest_sha256"
    )
    binding_sha = _v4_global(_v4_scope, '_panel_sha')(binding_meta.get("sha256"), field="binding.sha256")
    matched_sha = _v4_global(_v4_scope, '_panel_sha')(
        binding_meta.get("matched_verdict_sha256"), field="binding.matched_verdict_sha256"
    )
    calendar_receipt_sha = _v4_global(_v4_scope, '_panel_sha')(
        calendar.get("receipt_sha256"), field="calendar.receipt_sha256"
    )
    if binding_sha != files["frozen_binding"][1] or matched_sha != files["matched_verdict"][1]:
        raise _v4_global(_v4_scope, 'ValueError')("frozen binding digest does not match source manifest")
    if binding.get("source_sha256") != source_sha:
        raise _v4_global(_v4_scope, 'ValueError')("runtime binding source digest mismatch")
    if binding.get("source_manifest_declared_sha256") != source_manifest_declared_sha:
        raise _v4_global(_v4_scope, 'ValueError')("runtime binding source manifest digest mismatch")
    if binding.get("calendar_receipt_sha256") != calendar_receipt_sha:
        raise _v4_global(_v4_scope, 'ValueError')("runtime binding calendar receipt digest mismatch")
    if binding.get("binding_sha256") != binding_sha or binding.get("matched_verdict_sha256") != matched_sha:
        raise _v4_global(_v4_scope, 'ValueError')("runtime binding frozen identity digest mismatch")
    if derivation.get("2026_consumed") is not False or derivation.get("event_day_included") is not False:
        raise _v4_global(_v4_scope, 'ValueError')("historical derivation consumed a forbidden date")
    if derivation.get("event_metadata_to_extractor") is not False or derivation.get("future_labels_to_extractor") is not False:
        raise _v4_global(_v4_scope, 'ValueError')("historical derivation exposed event or future metadata")
    if derivation.get("control_threshold_status") != "UNREGISTERED_NO_SELF_TUNING":
        raise _v4_global(_v4_scope, 'ValueError')("historical control threshold status is not fixed")
    if review_meta.get("manual_review_status") != "NOT_REVIEWED":
        raise _v4_global(_v4_scope, 'ValueError')("historical manual review status changed")
    if review_meta.get("identity_results_mapping_separate") is not True:
        raise _v4_global(_v4_scope, 'ValueError')("historical identity mapping is not separated")
    if review_meta.get("llm_supplemented") is not False:
        raise _v4_global(_v4_scope, 'ValueError')("historical review was supplemented")

    full = receipt.get("full")
    if not _v4_global(_v4_scope, 'isinstance')(full, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'ValueError')("historical receipt full summary is absent")
    if _v4_global(_v4_scope, '_panel_int')(full.get("group_count"), field="receipt.full.group_count") != 24:
        raise _v4_global(_v4_scope, 'ValueError')("historical group count is not 24")
    if _v4_global(_v4_scope, '_panel_int')(full.get("series_count"), field="receipt.full.series_count") != 96:
        raise _v4_global(_v4_scope, 'ValueError')("historical series count is not 96")
    if _v4_global(_v4_scope, '_panel_int')(full.get("rows_per_series"), field="receipt.full.rows_per_series") != 60:
        raise _v4_global(_v4_scope, 'ValueError')("historical rows per series is not 60")
    receipt_states = full.get("terminal_states")
    receipt_event_counts = full.get("event_type_counts")
    if not _v4_global(_v4_scope, 'isinstance')(receipt_states, _v4_global(_v4_scope, 'Mapping')) or not _v4_global(_v4_scope, 'isinstance')(receipt_event_counts, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'ValueError')("historical receipt state summary is incomplete")
    contract_gate = receipt.get("contract_gate")
    if not _v4_global(_v4_scope, 'isinstance')(contract_gate, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'ValueError')("historical terminal coverage gate is absent")
    gate_file = _v4_global(_v4_scope, '_panel_read_json')(files["terminal_contract_gate"][0])
    if gate_file != contract_gate:
        raise _v4_global(_v4_scope, 'ValueError')("terminal coverage gate differs between receipt and evidence")
    if (
        contract_gate.get("metric_contract_version") != _v4_global(_v4_scope, '_HK_PREFIX_METRIC_CONTRACT')
        or contract_gate.get("status") != "NOT_SUPPORTED"
        or _v4_global(_v4_scope, '_panel_int')(contract_gate.get("complete_terminal_pairs"), field="gate.complete_terminal_pairs") != 16
        or _v4_global(_v4_scope, '_panel_int')(contract_gate.get("total_pairs"), field="gate.total_pairs") != 24
        or _v4_global(_v4_scope, '_panel_int')(contract_gate.get("required_complete_pairs"), field="gate.required_complete_pairs") != _v4_global(_v4_scope, '_HK_PREFIX_REQUIRED_COMPLETE_PAIRS')
        or contract_gate.get("coverage") != "16/24"
    ):
        raise _v4_global(_v4_scope, 'ValueError')("terminal coverage gate is not the fixed 16/24 result")
    metrics_file = _v4_global(_v4_scope, '_panel_read_json')(files["metrics_contract"][0])
    if (
        metrics_file.get("status") != "PASS"
        or metrics_file.get("version") != _v4_global(_v4_scope, '_HK_PREFIX_METRIC_CONTRACT')
        or metrics_file.get("primary_metric") != "TERMINAL_BINARY_INDICATOR"
        or metrics_file.get("delta_bounds")
        != "CASE_LOW_MINUS_CONTROL_HIGH; CASE_HIGH_MINUS_CONTROL_LOW"
        or metrics_file.get("warmup_terminal_policy")
        != "INDETERMINATE_NOT_KNOWN_NEGATIVE"
    ):
        raise _v4_global(_v4_scope, 'ValueError')("corrected metric evidence is incomplete")
    reuse_file = _v4_global(_v4_scope, '_panel_read_json')(files["raw_window_reuse"][0])
    if (
        reuse_file.get("status") != "PASS"
        or reuse_file.get("raw_window_bytes_reused") is not True
        or _v4_global(_v4_scope, '_panel_int')(reuse_file.get("window_file_count"), field="reuse.window_file_count") != 96
        or _v4_global(_v4_scope, '_panel_int')(reuse_file.get("window_rows"), field="reuse.window_rows") != 5760
        or _v4_global(_v4_scope, '_panel_int')(reuse_file.get("window_sha256_mismatches"), field="reuse.window_sha256_mismatches") != 0
        or reuse_file.get("raw_source_scanned") is not False
    ):
        raise _v4_global(_v4_scope, 'ValueError')("raw window reuse evidence is incomplete")
    return {
        "root": root,
        "files": files,
        "binding": binding,
        "receipt": receipt,
        "source_manifest": source_manifest,
        "source": source,
        "calendar": calendar,
        "derivation": derivation,
        "binding_meta": binding_meta,
        "source_sha": source_sha,
        "source_manifest_declared_sha": source_manifest_declared_sha,
        "binding_sha": binding_sha,
        "matched_sha": matched_sha,
        "calendar_receipt_sha": calendar_receipt_sha,
        "receipt_states": receipt_states,
        "receipt_event_counts": receipt_event_counts,
        "contract_gate": contract_gate,
    }


def _read_hk_prefix_panel_index(_v4_scope, *, root, files):
    index_path = files["anonymous_index"][0]
    with index_path.open("r", encoding="utf-8", newline="") as handle:
        index_rows = _v4_global(_v4_scope, 'list')(_v4_global(_v4_scope, 'csv').DictReader(handle))
    if not index_rows or _v4_global(_v4_scope, 'set')(index_rows[0]) != _v4_global(_v4_scope, '_HK_PREFIX_INDEX_FIELDS') or _v4_global(_v4_scope, 'len')(index_rows) != 96:
        raise _v4_global(_v4_scope, 'ValueError')("anonymous prefix index is not the fixed 96-row schema")
    expected_series = {f"SERIES_{index:03d}" for index in _v4_global(_v4_scope, 'range')(1, 97)}
    index_by_series: dict[str, Mapping[str, str]] = {}
    for row in index_rows:
        series_id = _v4_global(_v4_scope, 'str')(row.get("series_id") or "")
        if series_id in index_by_series or series_id not in expected_series:
            raise _v4_global(_v4_scope, 'ValueError')("anonymous prefix series identity is not unique")
        if _v4_global(_v4_scope, '_panel_int')(row.get("row_count"), field="anonymous.row_count") != 60:
            raise _v4_global(_v4_scope, 'ValueError')("anonymous prefix row count is not 60")
        if row.get("review_status") != "NOT_REVIEWED":
            raise _v4_global(_v4_scope, 'ValueError')("anonymous prefix review status is not NOT_REVIEWED")
        _v4_global(_v4_scope, '_panel_sha')(row.get("input_sha256"), field="anonymous.input_sha256")
        _v4_global(_v4_scope, '_panel_sha')(row.get("prefix_content_sha256"), field="anonymous.prefix_content_sha256")
        index_by_series[series_id] = row
        _v4_global(_v4_scope, '_panel_safe_relative')(root, row.get("prefix_file"))
    if _v4_global(_v4_scope, 'set')(index_by_series) != expected_series:
        raise _v4_global(_v4_scope, 'ValueError')("anonymous prefix series set mismatch")
    return {"expected_series": expected_series, "index_by_series": index_by_series}


def _read_hk_prefix_panel_identity(_v4_scope, *, files, expected_series, index_by_series, receipt_states, receipt_event_counts):
    mapping_path = files["results_mapping"][0]
    with mapping_path.open("r", encoding="utf-8", newline="") as handle:
        mapping_rows = _v4_global(_v4_scope, 'list')(_v4_global(_v4_scope, 'csv').DictReader(handle))
    if not mapping_rows or _v4_global(_v4_scope, 'set')(mapping_rows[0]) != _v4_global(_v4_scope, '_HK_PREFIX_MAPPING_FIELDS') or _v4_global(_v4_scope, 'len')(mapping_rows) != 96:
        raise _v4_global(_v4_scope, 'ValueError')("identity result mapping is not the fixed schema")
    mapping_by_series: dict[str, Mapping[str, str]] = {}
    pair_rows: dict[str, list[Mapping[str, str]]] = {}
    state_counts: dict[str, int] = {}
    state_by_event: dict[str, dict[str, int]] = {}
    event_dates: list[str] = []
    event_groups: dict[str, set[str]] = {"new_event": _v4_global(_v4_scope, 'set')(), "continuation_event": _v4_global(_v4_scope, 'set')()}
    unknown_series_count = 0
    unknown_row_count = 0
    indeterminate_series_count = 0
    indeterminate_row_count = 0
    terminal_unknown_count = 0
    terminal_indeterminate_count = 0
    source_observed_rows = 0
    source_missing_rows = 0
    for row in mapping_rows:
        series_id = _v4_global(_v4_scope, 'str')(row.get("series_id") or "")
        if series_id in mapping_by_series or series_id not in expected_series:
            raise _v4_global(_v4_scope, 'ValueError')("identity mapping series identity is not unique")
        if series_id not in index_by_series:
            raise _v4_global(_v4_scope, 'ValueError')("identity mapping has no anonymous index row")
        if row.get("input_sha256") != index_by_series[series_id].get("input_sha256"):
            raise _v4_global(_v4_scope, 'ValueError')("identity input digest does not match anonymous index")
        if row.get("prefix_content_sha256") != index_by_series[series_id].get("prefix_content_sha256"):
            raise _v4_global(_v4_scope, 'ValueError')("identity prefix digest does not match anonymous index")
        role = _v4_global(_v4_scope, 'str')(row.get("role") or "")
        event_type = _v4_global(_v4_scope, 'str')(row.get("event_type") or "")
        if role not in {"EVENT", "CONTROL_1", "CONTROL_2", "CONTROL_3"}:
            raise _v4_global(_v4_scope, 'ValueError')("identity mapping role is outside frozen contract")
        if event_type not in event_groups:
            raise _v4_global(_v4_scope, 'ValueError')("identity mapping event type is outside frozen contract")
        if _v4_global(_v4_scope, '_panel_int')(row.get("row_count"), field="identity.row_count") != 60:
            raise _v4_global(_v4_scope, 'ValueError')("identity row count is not 60")
        event_date = _v4_global(_v4_scope, 'str')(row.get("event_date") or "")
        parsed_date = _v4_global(_v4_scope, 'datetime').strptime(event_date, "%Y-%m-%d")
        if parsed_date.year > 2025:
            raise _v4_global(_v4_scope, 'ValueError')("2026 event entered historical panel")
        event_dates.append(event_date)
        state = _v4_global(_v4_scope, 'str')(row.get("terminal_state") or "")
        if state not in _v4_global(_v4_scope, '_HK_PREFIX_EXPECTED_STATES'):
            raise _v4_global(_v4_scope, 'ValueError')("identity terminal state is outside frozen contract")
        if row.get("comparison_status") != _v4_global(_v4_scope, '_HK_PREFIX_MAPPING_COMPARISON_STATUS'):
            raise _v4_global(_v4_scope, 'ValueError')("identity comparison status changed")
        unknown = _v4_global(_v4_scope, '_panel_int')(row.get("unknown_count"), field="identity.unknown_count")
        indeterminate = _v4_global(_v4_scope, '_panel_int')(row.get("indeterminate_count"), field="identity.indeterminate_count")
        known = _v4_global(_v4_scope, '_panel_int')(row.get("known_count"), field="identity.known_count")
        if indeterminate < unknown or known + indeterminate != 60:
            raise _v4_global(_v4_scope, 'ValueError')("identity determinability counts are inconsistent")
        expected_unknown = state == "UNKNOWN"
        expected_determinable = state not in {"UNKNOWN", "WARMUP"}
        if row.get("terminal_unknown") != _v4_global(_v4_scope, 'str')(expected_unknown) or row.get("terminal_determinable") != _v4_global(_v4_scope, 'str')(expected_determinable):
            raise _v4_global(_v4_scope, 'ValueError')("identity terminal determinability flags mismatch")
        lower = _v4_global(_v4_scope, '_panel_float')(row.get("terminal_lower"), field="identity.terminal_lower")
        upper = _v4_global(_v4_scope, '_panel_float')(row.get("terminal_upper"), field="identity.terminal_upper")
        if lower > upper or (expected_determinable and lower != upper) or (not expected_determinable and (lower != 0.0 or upper != 1.0)):
            raise _v4_global(_v4_scope, 'ValueError')("identity terminal interval mismatch")
        mapping_by_series[series_id] = row
        pair_rows.setdefault(_v4_global(_v4_scope, 'str')(row.get("pair_group_id") or ""), []).append(row)
        event_groups[event_type].add(_v4_global(_v4_scope, 'str')(row.get("pair_group_id") or ""))
        state_counts[state] = state_counts.get(state, 0) + 1
        by_event = state_by_event.setdefault(event_type, {})
        by_event[state] = by_event.get(state, 0) + 1
        unknown_series_count += unknown > 0
        unknown_row_count += unknown
        indeterminate_series_count += indeterminate > 0
        indeterminate_row_count += indeterminate
        terminal_unknown_count += expected_unknown
        terminal_indeterminate_count += not expected_determinable
        source_observed_rows += _v4_global(_v4_scope, '_panel_int')(row.get("source_observed_rows"), field="identity.source_observed_rows")
        source_missing_rows += _v4_global(_v4_scope, '_panel_int')(row.get("source_missing_rows"), field="identity.source_missing_rows")
    if _v4_global(_v4_scope, 'set')(mapping_by_series) != expected_series or _v4_global(_v4_scope, 'len')(pair_rows) != 24:
        raise _v4_global(_v4_scope, 'ValueError')("identity mapping series or group count mismatch")
    if {key: _v4_global(_v4_scope, 'len')(value) for key, value in event_groups.items()} != {"new_event": 20, "continuation_event": 4}:
        raise _v4_global(_v4_scope, 'ValueError')("identity event group counts mismatch")
    if _v4_global(_v4_scope, 'any')(
        _v4_global(_v4_scope, 'len')(rows) != 4 or {_v4_global(_v4_scope, 'str')(row.get("role") or "") for row in rows}
        != {"EVENT", "CONTROL_1", "CONTROL_2", "CONTROL_3"}
        for rows in pair_rows.values()
    ):
        raise _v4_global(_v4_scope, 'ValueError')("identity pair group does not have one event and three controls")
    if _v4_global(_v4_scope, 'dict')(state_counts) != {_v4_global(_v4_scope, 'str')(key): _v4_global(_v4_scope, '_panel_int')(value, field="receipt.terminal_states") for key, value in receipt_states.items()}:
        raise _v4_global(_v4_scope, 'ValueError')("identity terminal states do not match receipt")
    if {key: _v4_global(_v4_scope, 'len')(value) for key, value in event_groups.items()} != {
        _v4_global(_v4_scope, 'str')(key): _v4_global(_v4_scope, '_panel_int')(value, field="receipt.event_type_counts") for key, value in receipt_event_counts.items()
    }:
        raise _v4_global(_v4_scope, 'ValueError')("identity event groups do not match receipt")
    return {
        "mapping_by_series": mapping_by_series,
        "pair_rows": pair_rows,
        "state_counts": state_counts,
        "state_by_event": state_by_event,
        "event_dates": event_dates,
        "event_groups": event_groups,
        "unknown_series_count": unknown_series_count,
        "unknown_row_count": unknown_row_count,
        "indeterminate_series_count": indeterminate_series_count,
        "indeterminate_row_count": indeterminate_row_count,
        "terminal_unknown_count": terminal_unknown_count,
        "terminal_indeterminate_count": terminal_indeterminate_count,
        "source_observed_rows": source_observed_rows,
        "source_missing_rows": source_missing_rows,
    }


def _read_hk_prefix_panel_pairs(_v4_scope, *, files, mapping_by_series, pair_rows, event_groups, contract_gate):
    pair_field_set = {
        "pair_group_id", "event_date", "event_type", "event_series_id", "control_series_ids",
        "event_terminal_state", "event_terminal_qualifies", "event_terminal_unknown",
        "event_terminal_determinable", "event_terminal_lower", "event_terminal_upper",
        "event_terminal_indeterminate_reason", "control_terminal_qualifying_count",
        "control_terminal_unknown_count", "control_terminal_indeterminate_count",
        "control_terminal_determinable", "control_terminal_lower_mean", "control_terminal_upper_mean",
        "complete_terminal_pair", "incomplete_endpoint_roles", "terminal_case_indicator",
        "terminal_control_indicator_mean", "terminal_delta", "terminal_delta_lower",
        "terminal_delta_upper", "occupancy_case_lower_rate", "occupancy_control_lower_rate_mean",
        "occupancy_pair_lower_delta", "occupancy_case_upper_rate", "occupancy_control_upper_rate_mean",
        "occupancy_pair_upper_delta", "comparison_status", "post_outcome_used",
    }
    with files["pair_metrics"][0].open("r", encoding="utf-8", newline="") as handle:
        pair_metric_rows = _v4_global(_v4_scope, 'list')(_v4_global(_v4_scope, 'csv').DictReader(handle))
    if not pair_metric_rows or _v4_global(_v4_scope, 'set')(pair_metric_rows[0]) != pair_field_set or _v4_global(_v4_scope, 'len')(pair_metric_rows) != 24:
        raise _v4_global(_v4_scope, 'ValueError')("pair metric schema is not the corrected contract")
    complete_pair_count = 0
    pair_event_groups: dict[str, set[str]] = {"new_event": _v4_global(_v4_scope, 'set')(), "continuation_event": _v4_global(_v4_scope, 'set')()}
    terminal_deltas: list[float] = []
    terminal_delta_lowers: list[float] = []
    terminal_delta_uppers: list[float] = []
    for row in pair_metric_rows:
        pair_id = _v4_global(_v4_scope, 'str')(row.get("pair_group_id") or "")
        event_type = _v4_global(_v4_scope, 'str')(row.get("event_type") or "")
        if pair_id not in pair_rows or event_type not in pair_event_groups or pair_id in pair_event_groups[event_type]:
            raise _v4_global(_v4_scope, 'ValueError')("pair metric identity is not frozen")
        pair_event_groups[event_type].add(pair_id)
        event_id = _v4_global(_v4_scope, 'str')(row.get("event_series_id") or "")
        control_ids = [item for item in _v4_global(_v4_scope, 'str')(row.get("control_series_ids") or "").split(",") if item]
        if event_id not in mapping_by_series or _v4_global(_v4_scope, 'len')(control_ids) != 3 or _v4_global(_v4_scope, 'any')(item not in mapping_by_series for item in control_ids):
            raise _v4_global(_v4_scope, 'ValueError')("pair metric series references are invalid")
        event_mapping = mapping_by_series[event_id]
        controls_mapping = [mapping_by_series[item] for item in control_ids]
        complete_expected = event_mapping.get("terminal_determinable") == "True" and _v4_global(_v4_scope, 'all')(item.get("terminal_determinable") == "True" for item in controls_mapping)
        complete = row.get("complete_terminal_pair") == "True"
        if complete != complete_expected or row.get("comparison_status") != _v4_global(_v4_scope, '_HK_PREFIX_MAPPING_COMPARISON_STATUS') or row.get("post_outcome_used") != "False":
            raise _v4_global(_v4_scope, 'ValueError')("pair metric determinability or safety changed")
        case_low = _v4_global(_v4_scope, '_panel_float')(event_mapping.get("terminal_lower"), field="pair.case_low")
        case_high = _v4_global(_v4_scope, '_panel_float')(event_mapping.get("terminal_upper"), field="pair.case_high")
        control_lows = [_v4_global(_v4_scope, '_panel_float')(item.get("terminal_lower"), field="pair.control_low") for item in controls_mapping]
        control_highs = [_v4_global(_v4_scope, '_panel_float')(item.get("terminal_upper"), field="pair.control_high") for item in controls_mapping]
        control_low = _v4_global(_v4_scope, 'sum')(control_lows) / 3
        control_high = _v4_global(_v4_scope, 'sum')(control_highs) / 3
        lower = _v4_global(_v4_scope, '_panel_float')(row.get("terminal_delta_lower"), field="pair.terminal_delta_lower")
        upper = _v4_global(_v4_scope, '_panel_float')(row.get("terminal_delta_upper"), field="pair.terminal_delta_upper")
        if _v4_global(_v4_scope, 'abs')(lower - (case_low - control_high)) > 1e-9 or _v4_global(_v4_scope, 'abs')(upper - (case_high - control_low)) > 1e-9 or lower > upper + 1e-12:
            raise _v4_global(_v4_scope, 'ValueError')("pair metric delta bounds formula mismatch")
        if complete:
            complete_pair_count += 1
            delta = _v4_global(_v4_scope, '_panel_float')(row.get("terminal_delta"), field="pair.terminal_delta")
            if _v4_global(_v4_scope, 'abs')(delta - (case_low - control_low)) > 1e-9:
                raise _v4_global(_v4_scope, 'ValueError')("pair metric terminal delta mismatch")
            terminal_deltas.append(delta)
        elif row.get("terminal_delta") not in {"", None}:
            raise _v4_global(_v4_scope, 'ValueError')("incomplete pair exposed a terminal delta")
        terminal_delta_lowers.append(lower)
        terminal_delta_uppers.append(upper)
    if pair_event_groups != event_groups or complete_pair_count != 16 or _v4_global(_v4_scope, '_panel_int')(contract_gate.get("complete_terminal_pairs"), field="gate.complete_terminal_pairs") != complete_pair_count:
        raise _v4_global(_v4_scope, 'ValueError')("pair metric coverage does not match frozen 16/24 gate")
    return {
        "complete_pair_count": complete_pair_count,
        "terminal_deltas": terminal_deltas,
        "terminal_delta_lowers": terminal_delta_lowers,
        "terminal_delta_uppers": terminal_delta_uppers,
    }


def _read_hk_prefix_panel_windows(_v4_scope, *, root, files, index_by_series, source):
    quality_counts: dict[str, int] = {}
    total_window_rows = 0
    for series_id, index_row in index_by_series.items():
        path = _v4_global(_v4_scope, '_panel_safe_relative')(root, index_row.get("prefix_file"))
        with path.open("r", encoding="utf-8", newline="") as handle:
            rows = _v4_global(_v4_scope, 'list')(_v4_global(_v4_scope, 'csv').DictReader(handle))
        if not rows or _v4_global(_v4_scope, 'set')(rows[0]) != _v4_global(_v4_scope, '_HK_PREFIX_WINDOW_FIELDS') or _v4_global(_v4_scope, 'len')(rows) != 60:
            raise _v4_global(_v4_scope, 'ValueError')("derived prefix window schema or row count mismatch")
        if _v4_global(_v4_scope, 'any')(_v4_global(_v4_scope, 'str')(row.get("series_id") or "") != series_id for row in rows):
            raise _v4_global(_v4_scope, 'ValueError')("derived prefix window series identity mismatch")
        for row in rows:
            quality = _v4_global(_v4_scope, 'str')(row.get("quality") or "")
            if not quality:
                raise _v4_global(_v4_scope, 'ValueError')("derived prefix window quality is missing")
            quality_counts[quality] = quality_counts.get(quality, 0) + 1
            if row.get("price_basis") != source.get("price_basis"):
                raise _v4_global(_v4_scope, 'ValueError')("derived prefix price basis differs from source manifest")
        total_window_rows += _v4_global(_v4_scope, 'len')(rows)
    if total_window_rows != 5760:
        raise _v4_global(_v4_scope, 'ValueError')("derived prefix window total row count mismatch")

    test_fields = _v4_global(_v4_scope, '_panel_read_json')(files["field_isolation"][0])
    test_future = _v4_global(_v4_scope, '_panel_read_json')(files["future_isolation"][0])
    test_positive = _v4_global(_v4_scope, '_panel_read_json')(files["past_positive_control"][0])
    if test_fields.get("status") != "PASS" or test_fields.get("checked_series") != 96 or test_fields.get("checked_rows") != 5760:
        raise _v4_global(_v4_scope, 'ValueError')("field isolation evidence is not PASS")
    if test_future.get("status") != "PASS" or test_future.get("checked_series") != 96 or test_future.get("future_rows_consumed") != 0:
        raise _v4_global(_v4_scope, 'ValueError')("future isolation evidence is not PASS")
    if test_positive.get("status") != "PASS" or test_positive.get("fit_calls") != 0:
        raise _v4_global(_v4_scope, 'ValueError')("past positive control evidence is not PASS")
    # The corrected metric contract is independently materialized and
    # bound; this prevents the descriptive window occupancy from being
    # mistaken for the terminal endpoint in the panel.
    corrected_status = _v4_global(_v4_scope, '_panel_log_status')(
        files["corrected_metric_contract_log"][0],
        ("primary_metric TERMINAL_BINARY_INDICATOR", "terminal_coverage 16/24", "status NOT_SUPPORTED", "manual_review NOT_REVIEWED"),
    )
    replay_status = _v4_global(_v4_scope, '_panel_log_status')(
        files["replay_log"][0],
        ("files 96", "summary_rows 96", "errors 0"),
    )
    source_window_status = _v4_global(_v4_scope, '_panel_log_status')(
        files["source_window_replay_log"][0],
        ("total_expected_rows 5760", "total_missing 107"),
    )
    if replay_status != "PASS" or source_window_status != "PASS" or corrected_status != "PASS":
        raise _v4_global(_v4_scope, 'ValueError')("replay evidence log is not PASS")
    return {
        "quality_counts": quality_counts,
        "total_window_rows": total_window_rows,
        "corrected_status": corrected_status,
        "replay_status": replay_status,
        "source_window_status": source_window_status,
    }


def _project_hk_prefix_panel(_v4_scope, requested_date, *, evidence, index, identity, pairs, windows):
    root = evidence["root"]
    files = evidence["files"]
    binding = evidence["binding"]
    receipt = evidence["receipt"]
    source_manifest = evidence["source_manifest"]
    source = evidence["source"]
    calendar = evidence["calendar"]
    derivation = evidence["derivation"]
    binding_meta = evidence["binding_meta"]
    source_sha = evidence["source_sha"]
    source_manifest_declared_sha = evidence["source_manifest_declared_sha"]
    binding_sha = evidence["binding_sha"]
    matched_sha = evidence["matched_sha"]
    calendar_receipt_sha = evidence["calendar_receipt_sha"]
    index_by_series = index["index_by_series"]
    mapping_by_series = identity["mapping_by_series"]
    pair_rows = identity["pair_rows"]
    state_counts = identity["state_counts"]
    state_by_event = identity["state_by_event"]
    event_dates = identity["event_dates"]
    event_groups = identity["event_groups"]
    unknown_series_count = identity["unknown_series_count"]
    unknown_row_count = identity["unknown_row_count"]
    indeterminate_series_count = identity["indeterminate_series_count"]
    indeterminate_row_count = identity["indeterminate_row_count"]
    terminal_unknown_count = identity["terminal_unknown_count"]
    terminal_indeterminate_count = identity["terminal_indeterminate_count"]
    source_observed_rows = identity["source_observed_rows"]
    source_missing_rows = identity["source_missing_rows"]
    complete_pair_count = pairs["complete_pair_count"]
    terminal_deltas = pairs["terminal_deltas"]
    terminal_delta_lowers = pairs["terminal_delta_lowers"]
    terminal_delta_uppers = pairs["terminal_delta_uppers"]
    quality_counts = windows["quality_counts"]
    total_window_rows = windows["total_window_rows"]
    corrected_status = windows["corrected_status"]
    replay_status = windows["replay_status"]
    source_window_status = windows["source_window_status"]
    event_date_range = [_v4_global(_v4_scope, 'min')(event_dates), _v4_global(_v4_scope, 'max')(event_dates)]
    file_refs = [
        {"label": "output receipt", "ref": "receipt.json", "sha256": files["receipt"][1], "verification": "VERIFIED_LOCAL_COPY"},
        {"label": "source manifest", "ref": "source_manifest.json", "sha256": files["source_manifest"][1], "verification": "VERIFIED_LOCAL_COPY"},
        {"label": "frozen binding", "ref": "identity/frozen_group_binding.json", "sha256": files["frozen_binding"][1], "verification": "VERIFIED_LOCAL_COPY"},
        {"label": "matched verdict", "ref": "identity/frozen_matched_verdict.csv", "sha256": files["matched_verdict"][1], "verification": "VERIFIED_LOCAL_COPY"},
        {"label": "terminal contract gate", "ref": "tests/terminal_contract_gate.json", "sha256": files["terminal_contract_gate"][1], "verification": "VERIFIED_LOCAL_COPY"},
        {"label": "corrected metric contract", "ref": "tests/metrics_contract.json", "sha256": files["metrics_contract"][1], "verification": "VERIFIED_LOCAL_COPY"},
        {"label": "raw window reuse", "ref": "tests/raw_window_reuse.json", "sha256": files["raw_window_reuse"][1], "verification": "VERIFIED_LOCAL_COPY"},
        {"label": "paired terminal metrics", "ref": "pair_metrics.csv", "sha256": files["pair_metrics"][1], "verification": "VERIFIED_LOCAL_COPY"},
        {"label": "calendar receipt declared SHA", "ref": "source_manifest.json#calendar.receipt_sha256", "sha256": calendar_receipt_sha, "verification": "DECLARED_IN_SOURCE_MANIFEST"},
        {"label": "source data declared SHA", "ref": "source_manifest.json#source.sha256", "sha256": source_sha, "verification": "DECLARED_IN_SOURCE_MANIFEST"},
        {"label": "96-series replay", "ref": "review/replay_96_reference_review_20260914.log", "sha256": files["replay_log"][1], "verification": "VERIFIED_LOCAL_COPY"},
        {"label": "source window replay", "ref": "review/source_window_replay_review_20260914.log", "sha256": files["source_window_replay_log"][1], "verification": "VERIFIED_LOCAL_COPY"},
        {"label": "metric contract review", "ref": "review/corrected_metric_contract_review_20260914.log", "sha256": files["corrected_metric_contract_log"][1], "verification": "VERIFIED_LOCAL_COPY"},
    ]
    cannot_confirm = [_v4_global(_v4_scope, 'str')(item) for item in source_manifest.get("cannot_confirm", []) if _v4_global(_v4_scope, 'str')(item).strip()]


    return {
                "schema_version": _v4_global(_v4_scope, '_HK_PREFIX_PANEL_SCHEMA'),
                "status": "READY",
                "requested_date": requested_date,
                "asset_id": _v4_global(_v4_scope, '_HK_PREFIX_ASSET_ID'),
                "run_id": _v4_global(_v4_scope, 'str')(binding.get("run_id") or ""),
                "asset_status": _v4_global(_v4_scope, 'str')(receipt.get("status") or ""),
                "scope": {
                    "historical_prefix_only": True,
                    "event_date_range": event_date_range,
                    "max_event_year": 2025,
                    "consumed_2026": False,
                    "event_day_included": False,
                    "available_at_basis": _v4_global(_v4_scope, 'str')(derivation.get("available_at_basis") or ""),
                    "window_status": _v4_global(_v4_scope, 'str')(derivation.get("window_status") or ""),
                },
                "source": {
                    "rows": _v4_global(_v4_scope, '_panel_int')(source.get("rows"), field="source.rows"),
                    "symbols": _v4_global(_v4_scope, '_panel_int')(source.get("symbols"), field="source.symbols"),
                    "date_range": _v4_global(_v4_scope, 'list')(source.get("range") or []),
                    "schema_columns": _v4_global(_v4_scope, 'list')(source.get("schema_columns") or []),
                    "sha256": source_sha,
                    "manifest_sha256": source_manifest_declared_sha,
                    "status": _v4_global(_v4_scope, 'str')(source.get("status") or ""),
                    "price_basis": _v4_global(_v4_scope, 'str')(source.get("price_basis") or ""),
                    "price_basis_status": _v4_global(_v4_scope, 'str')(source.get("price_basis_status") or ""),
                    "volume_source_column": _v4_global(_v4_scope, 'str')(source.get("volume_source_column") or ""),
                    "volume_unit": _v4_global(_v4_scope, 'str')(source.get("volume_unit") or ""),
                },
                "calendar": {
                    "market_day_count": _v4_global(_v4_scope, '_panel_int')(calendar.get("market_day_count"), field="calendar.market_day_count"),
                    "row_count": _v4_global(_v4_scope, '_panel_int')(calendar.get("row_count"), field="calendar.row_count"),
                    "date_range": _v4_global(_v4_scope, 'list')(calendar.get("date_range") or []),
                    "source": _v4_global(_v4_scope, 'str')(calendar.get("calendar_source") or ""),
                    "certification": _v4_global(_v4_scope, 'str')(calendar.get("calendar_certification") or ""),
                    "receipt_sha256": calendar_receipt_sha,
                    "receipt_verification": "DECLARED_IN_SOURCE_MANIFEST",
                },
                "binding": {
                    "groups": 24,
                    "controls": 72,
                    "series_count": 96,
                    "rows_per_series": 60,
                    "resampled": _v4_global(_v4_scope, 'bool')(binding_meta.get("resampled")),
                    "event_type_counts": {_v4_global(_v4_scope, 'str')(key): _v4_global(_v4_scope, '_panel_int')(value, field="binding.event_type_counts") for key, value in _v4_global(_v4_scope, 'dict')(binding_meta.get("event_type_counts") or {}).items()},
                    "sha256": binding_sha,
                    "matched_verdict_sha256": matched_sha,
                },
                "export": {
                    "series_count": 96,
                    "rows_per_series": 60,
                    "total_rows": total_window_rows,
                    "event_date_range": event_date_range,
                    "event_type_counts": {key: _v4_global(_v4_scope, 'len')(value) for key, value in event_groups.items()},
                    "state_distribution": _v4_global(_v4_scope, 'dict')(_v4_global(_v4_scope, 'sorted')(state_counts.items())),
                    "state_distribution_by_event_type": {
                        key: _v4_global(_v4_scope, 'dict')(_v4_global(_v4_scope, 'sorted')(value.items())) for key, value in _v4_global(_v4_scope, 'sorted')(state_by_event.items())
                    },
                    "quality_distribution": _v4_global(_v4_scope, 'dict')(_v4_global(_v4_scope, 'sorted')(quality_counts.items())),
                    "source_observed_rows": source_observed_rows,
                    "source_missing_rows": source_missing_rows,
                    "unknown_series_count": unknown_series_count,
                    "unknown_row_count": unknown_row_count,
                    "indeterminate_series_count": indeterminate_series_count,
                    "indeterminate_row_count": indeterminate_row_count,
                    "terminal_unknown_series_count": terminal_unknown_count,
                    "terminal_indeterminate_series_count": terminal_indeterminate_count,
                    "complete_terminal_pairs": complete_pair_count,
                    "required_complete_pairs": _v4_global(_v4_scope, '_HK_PREFIX_REQUIRED_COMPLETE_PAIRS'),
                    "coverage_status": "NOT_SUPPORTED",
                    "coverage_fraction": "16/24",
                    "terminal_delta_mean": _v4_global(_v4_scope, 'sum')(terminal_deltas) / _v4_global(_v4_scope, 'len')(terminal_deltas) if terminal_deltas else None,
                    "terminal_delta_lower_mean": _v4_global(_v4_scope, 'sum')(terminal_delta_lowers) / _v4_global(_v4_scope, 'len')(terminal_delta_lowers),
                    "terminal_delta_upper_mean": _v4_global(_v4_scope, 'sum')(terminal_delta_uppers) / _v4_global(_v4_scope, 'len')(terminal_delta_uppers),
                    "warmup_is_not_no_active_setup": True,
                },
                "acceptance": {
                    "field_isolation": "PASS",
                    "future_isolation": "PASS",
                    "past_positive_control": "PASS",
                    "csv_replay": replay_status,
                    "source_window_replay": source_window_status,
                    "terminal_metric_contract": "PASS",
                    "terminal_delta_bounds": "PASS",
                    "warmup_endpoint_indeterminate": "PASS",
                    "terminal_coverage": "NOT_SUPPORTED",
                    "raw_window_bytes_reused": "PASS",
                },
                "review": {
                    "manual_review_status": "NOT_REVIEWED",
                    "conclusion_status": "NOT_SUPPORTED",
                    "comparison_status": _v4_global(_v4_scope, '_HK_PREFIX_COMPARISON_STATUS'),
                    "conclusion": "冻结历史 prefix 研究的终态可判覆盖为16/24，低于18/24；比较状态为NOT_SUPPORTED。窗口占用仅作描述，人工复核保持NOT_REVIEWED。本批不形成 alpha 或交易结论。",
                    "no_alpha_claim": True,
                    "main_effect_status": "NOT_SUPPORTED",
                    "daily_selection_separated": True,
                },
                "evidence": file_refs,
                "cannot_confirm": cannot_confirm,
                "research_only": True,
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }
def __read_hk_prefix_research_asset_body(_v4_scope, /, requested_date, *, root_value, binding_value):
    """Read the fixed, anonymous historical prefix asset for the review UI.

        This is a bounded consumer projection.  It reads only the runtime binding,
        output receipt/manifest, anonymous windows and machine evidence; identity
        rows are used for aggregate state counts and are never returned to the
        browser.  Any missing or mismatched digest fails closed with a typed
        ``CANNOT_CONFIRM`` payload.
        """
    configured_binding = binding_value or _v4_global(_v4_scope, 'os').environ.get("V4_HK_PREFIX_RESEARCH_BINDING_PATH")
    if not configured_binding:
        return _v4_global(_v4_scope, '_panel_cannot_confirm')(
            requested_date,
            ["HK_PREFIX_RESEARCH_BINDING_NOT_CONFIGURED"],
        )
    try:
        evidence = _load_hk_prefix_panel_evidence(
            _v4_scope, requested_date, configured_binding=configured_binding, root_value=root_value
        )
        index = _read_hk_prefix_panel_index(
            _v4_scope, root=evidence["root"], files=evidence["files"]
        )
        identity = _read_hk_prefix_panel_identity(
            _v4_scope,
            files=evidence["files"],
            expected_series=index["expected_series"],
            index_by_series=index["index_by_series"],
            receipt_states=evidence["receipt_states"],
            receipt_event_counts=evidence["receipt_event_counts"],
        )
        pairs = _read_hk_prefix_panel_pairs(
            _v4_scope,
            files=evidence["files"],
            mapping_by_series=identity["mapping_by_series"],
            pair_rows=identity["pair_rows"],
            event_groups=identity["event_groups"],
            contract_gate=evidence["contract_gate"],
        )
        windows = _read_hk_prefix_panel_windows(
            _v4_scope,
            root=evidence["root"],
            files=evidence["files"],
            index_by_series=index["index_by_series"],
            source=evidence["source"],
        )
        return _project_hk_prefix_panel(
            _v4_scope, requested_date, evidence=evidence, index=index, identity=identity, pairs=pairs, windows=windows
        )
    except (_v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'UnicodeError'), _v4_global(_v4_scope, 'ValueError'), _v4_global(_v4_scope, 'KeyError'), _v4_global(_v4_scope, 'TypeError'), _v4_global(_v4_scope, 'json').JSONDecodeError) as error:
        reason = _v4_global(_v4_scope, 'str')(error)
        # The public surface exposes a stable category, never arbitrary local
        # paths or parser details from a binding/evidence file.
        category = "HK_PREFIX_RESEARCH_BINDING_INVALID"
        if _v4_global(_v4_scope, 'isinstance')(error, _v4_global(_v4_scope, 'FileNotFoundError')):
            category = "HK_PREFIX_RESEARCH_EVIDENCE_MISSING"
        elif "digest" in reason.lower() or "sha" in reason.lower():
            category = "HK_PREFIX_RESEARCH_EVIDENCE_DIGEST_MISMATCH"
        return _v4_global(_v4_scope, '_panel_cannot_confirm')(requested_date, [category])
