"""stage_center.formula_margin_shadow: label_truth (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __truth_metadata_body(_v4_scope, /, labels, trade_date, cutoff):
    admission_mode = _v4_global(_v4_scope, '_admission_mode')(labels, default=None)
    if admission_mode == _v4_global(_v4_scope, 'REAL_AUTHORITY'):
        # The verified owner chain is not present in this workspace.  In
        # particular, truth_top20_codes, coverage and source strings supplied
        # by a caller are never authority evidence.
        raise _v4_global(_v4_scope, 'ShadowInvalid')("REAL_AUTHORITY_TRUTH_BLOCKED_OWNER_CONTRACT_PENDING")
    if labels.get("schema_version") not in (_v4_global(_v4_scope, 'LABEL_SCHEMA_VERSION'), None):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("label schema_version mismatch")
    if labels.get("experiment_id", _v4_global(_v4_scope, 'EXPERIMENT_ID')) != _v4_global(_v4_scope, 'EXPERIMENT_ID'):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("label experiment_id mismatch")
    if _v4_global(_v4_scope, '_exact_date')(labels.get("trade_date"), "label trade_date") != trade_date:
        raise _v4_global(_v4_scope, 'ShadowInvalid')("label trade_date mismatch")
    if labels.get("truth_scope") != _v4_global(_v4_scope, 'TRUTH_SCOPE'):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("label truth_scope is not the frozen full-universe contract")
    truth_version = _v4_global(_v4_scope, 'str')(labels.get("truth_universe_version") or "").strip()
    truth_source_version = _v4_global(_v4_scope, 'str')(labels.get("truth_source_version") or "").strip()
    truth_input_sha = labels.get("truth_input_sha256", labels.get("truth_input_sha"))
    truth_manifest_sha = labels.get("truth_manifest_sha256", labels.get("truth_manifest_sha"))
    if not truth_version or not truth_source_version:
        raise _v4_global(_v4_scope, 'ShadowInvalid')("truth universe/source version is required")
    if not _v4_global(_v4_scope, '_is_sha')(truth_input_sha) or not _v4_global(_v4_scope, '_is_sha')(truth_manifest_sha):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("truth input/manifest SHA is required")
    if labels.get("truth_complete") is not True:
        raise _v4_global(_v4_scope, 'ShadowInvalid')("truth_complete must be true")
    try:
        universe_count = _v4_global(_v4_scope, 'int')(labels.get("truth_universe_count"))
    except (_v4_global(_v4_scope, 'TypeError'), _v4_global(_v4_scope, 'ValueError')) as error:
        raise _v4_global(_v4_scope, 'ShadowInvalid')("truth_universe_count is required") from error
    if universe_count < _v4_global(_v4_scope, 'TRUTH_K'):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("truth universe has fewer than twenty members")
    try:
        coverage = _v4_global(_v4_scope, 'float')(labels.get("truth_coverage_ratio"))
    except (_v4_global(_v4_scope, 'TypeError'), _v4_global(_v4_scope, 'ValueError')) as error:
        raise _v4_global(_v4_scope, 'ShadowInvalid')("truth_coverage_ratio is required") from error
    if not _v4_global(_v4_scope, 'math').isfinite(coverage) or coverage != 1.0:
        raise _v4_global(_v4_scope, 'ShadowInvalid')("truth universe coverage is incomplete")
    tie_break = _v4_global(_v4_scope, 'str')(labels.get("truth_tie_break") or "").strip()
    gain_definition = _v4_global(_v4_scope, 'str')(labels.get("gain_definition") or "").strip()
    if tie_break != "gain_desc_then_security_id_asc":
        raise _v4_global(_v4_scope, 'ShadowInvalid')("truth tie-break must be gain_desc_then_security_id_asc")
    if gain_definition != "close/pre_close-1_raw":
        raise _v4_global(_v4_scope, 'ShadowInvalid')("truth gain definition must be close/pre_close-1_raw")
    source_artifact = _v4_global(_v4_scope, '_checked_file_artifact')(
        labels.get("truth_source_artifact"),
        "truth_source_artifact",
        expected_sha=_v4_global(_v4_scope, 'str')(truth_manifest_sha).lower(),
        required=True,
    )
    if not _v4_global(_v4_scope, 'isinstance')(source_artifact, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("truth source artifact is required")
    source_payload = _v4_global(_v4_scope, '_read_json')(_v4_global(_v4_scope, 'Path')(_v4_global(_v4_scope, 'str')(source_artifact["path"])))
    if not _v4_global(_v4_scope, 'isinstance')(source_payload, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("truth source artifact must contain an object")
    source_scope = _v4_global(_v4_scope, 'str')(source_payload.get("truth_scope") or source_payload.get("scope") or "").strip()
    if source_scope and source_scope != _v4_global(_v4_scope, 'TRUTH_SCOPE'):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("truth source artifact scope mismatch")
    universe_rows = source_payload.get("rows", source_payload.get("members", source_payload.get("universe")))
    if not _v4_global(_v4_scope, 'isinstance')(universe_rows, _v4_global(_v4_scope, 'list')):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("truth source artifact complete membership rows are required")
    if _v4_global(_v4_scope, 'len')(universe_rows) != universe_count:
        raise _v4_global(_v4_scope, 'ShadowInvalid')("truth universe count does not match the verified source artifact")
    canonical_truth_rows: list[dict[str, Any]] = []
    seen_codes: set[str] = _v4_global(_v4_scope, 'set')()
    for raw in universe_rows:
        if not _v4_global(_v4_scope, 'isinstance')(raw, _v4_global(_v4_scope, 'Mapping')):
            raise _v4_global(_v4_scope, 'ShadowInvalid')("truth universe rows must be objects")
        code = _v4_global(_v4_scope, '_canonical_code')(raw.get("security_id", raw.get("code")))
        if code in seen_codes:
            raise _v4_global(_v4_scope, 'ShadowInvalid')(f"duplicate truth universe member: {code}")
        seen_codes.add(code)
        close_price = _v4_global(_v4_scope, '_finite')(raw.get("close_price", raw.get("close")))
        pre_close = _v4_global(_v4_scope, '_finite')(raw.get("pre_close_price", raw.get("pre_close")))
        if close_price <= 0 or pre_close <= 0:
            raise _v4_global(_v4_scope, 'ShadowInvalid')(f"truth close/pre_close must be positive: {code}")
        gain = close_price / pre_close - 1.0
        declared_gain = raw.get("close_gain", raw.get("gain"))
        if declared_gain not in (None, "") and _v4_global(_v4_scope, 'abs')(_v4_global(_v4_scope, '_finite')(declared_gain) - gain) > 1e-12:
            raise _v4_global(_v4_scope, 'ShadowInvalid')(f"truth gain does not match close/pre_close: {code}")
        canonical_truth_rows.append({
            "security_id": code,
            "close_price": close_price,
            "pre_close_price": pre_close,
            "close_gain": gain,
        })
    computed_input_sha = _v4_global(_v4_scope, 'sha256_bytes')(_v4_global(_v4_scope, 'canonical_json')(canonical_truth_rows))
    if computed_input_sha != _v4_global(_v4_scope, 'str')(truth_input_sha).lower():
        raise _v4_global(_v4_scope, 'ShadowInvalid')("truth input SHA does not match verified membership/close rows")
    top20_codes = [
        row["security_id"]
        for row in _v4_global(_v4_scope, 'sorted')(
            canonical_truth_rows,
            key=lambda row: (-_v4_global(_v4_scope, 'float')(row["close_gain"]), _v4_global(_v4_scope, 'str')(row["security_id"])),
        )[:_v4_global(_v4_scope, 'TRUTH_K')]
    ]
    if _v4_global(_v4_scope, 'len')(top20_codes) != _v4_global(_v4_scope, 'TRUTH_K'):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("verified truth source produced fewer than twenty members")
    ranked_truth = _v4_global(_v4_scope, 'sorted')(
        canonical_truth_rows,
        key=lambda row: (-_v4_global(_v4_scope, 'float')(row["close_gain"]), _v4_global(_v4_scope, 'str')(row["security_id"])),
    )
    if _v4_global(_v4_scope, 'len')(ranked_truth) > _v4_global(_v4_scope, 'TRUTH_K') and ranked_truth[_v4_global(_v4_scope, 'TRUTH_K') - 1]["close_gain"] == ranked_truth[_v4_global(_v4_scope, 'TRUTH_K')]["close_gain"]:
        raise _v4_global(_v4_scope, 'ShadowInvalid')("truth Top20 boundary tie requires an authoritative source tie-break")
    declared_top20 = labels.get("truth_top20_codes")
    if declared_top20 is not None:
        if not _v4_global(_v4_scope, 'isinstance')(declared_top20, _v4_global(_v4_scope, 'list')) or [_v4_global(_v4_scope, '_canonical_code')(value) for value in declared_top20] != top20_codes:
            raise _v4_global(_v4_scope, 'ShadowInvalid')("truth_top20_codes does not match verified full-universe close ranking")
    captured_at = _v4_global(_v4_scope, '_parse_timestamp')(labels.get("labels_captured_at"), trade_date, "labels_captured_at")
    if captured_at <= cutoff:
        raise _v4_global(_v4_scope, 'ShadowInvalid')("close labels must be captured after the stage cutoff")
    if captured_at.strftime("%Y%m%d") != trade_date:
        raise _v4_global(_v4_scope, 'ShadowInvalid')("close labels are late/expired for the stage trade date")
    return (
        {
            "admission_mode": admission_mode,
            "admission_status": "ENGINEERING_ONLY",
            "hit_ready": False,
            "counts_as_forward_day": False,
            "natural_sample_count": 0,
            "truth_scope": _v4_global(_v4_scope, 'TRUTH_SCOPE'),
            "truth_universe_version": truth_version,
            "truth_source_version": truth_source_version,
            "truth_input_sha256": _v4_global(_v4_scope, 'str')(truth_input_sha).lower(),
            "truth_manifest_sha256": _v4_global(_v4_scope, 'str')(truth_manifest_sha).lower(),
            "truth_universe_count": universe_count,
            "truth_coverage_ratio": 1.0,
            "truth_top20_codes": top20_codes,
            "truth_tie_break": tie_break,
            "gain_definition": gain_definition,
            "truth_source_artifact": _v4_global(_v4_scope, 'dict')(source_artifact),
            "labels_captured_at": captured_at.isoformat(),
        },
        labels.get("rows") if _v4_global(_v4_scope, 'isinstance')(labels.get("rows"), _v4_global(_v4_scope, 'list')) else [],
        top20_codes,
    )


def __normalise_label_rows_body(_v4_scope, /, label_rows, members, top20_codes):
    member_rows = members.get("rows")
    if not _v4_global(_v4_scope, 'isinstance')(member_rows, _v4_global(_v4_scope, 'list')):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("members artifact rows are missing")
    member_codes = [_v4_global(_v4_scope, 'str')(row.get("security_id") or "") for row in member_rows]
    by_code: dict[str, Mapping[str, Any]] = {}
    for row in label_rows:
        if not _v4_global(_v4_scope, 'isinstance')(row, _v4_global(_v4_scope, 'Mapping')):
            raise _v4_global(_v4_scope, 'ShadowInvalid')("label rows must be objects")
        code = _v4_global(_v4_scope, '_canonical_code')(row.get("security_id", row.get("code")))
        if code in by_code:
            raise _v4_global(_v4_scope, 'ShadowInvalid')(f"duplicate label row: {code}")
        by_code[code] = row
    invalid: list[str] = []
    markout_invalid: list[str] = []
    normalised: list[dict[str, Any]] = []
    top20_set = _v4_global(_v4_scope, 'set')(top20_codes)
    expected_rank_by_code = {code: index + 1 for index, code in _v4_global(_v4_scope, 'enumerate')(top20_codes)}
    observed_ranks: set[int] = _v4_global(_v4_scope, 'set')()
    for member in member_rows:
        code = _v4_global(_v4_scope, 'str')(member["security_id"])
        raw = by_code.get(code)
        expected_hit = code in top20_set
        expected_rank = expected_rank_by_code.get(code)
        if raw is None:
            # Full-universe truth already determines hit membership.  A
            # missing per-D1 quote makes markout unavailable, but it must not
            # turn a verified Top20 hit into a false zero.
            markout_invalid.append(f"MISSING_CLOSE_LABEL:{code}")
            normalised.append({
                "security_id": code,
                "close_top20_rank": expected_rank,
                "hit_top20": expected_hit,
                "close_price": None,
                "close_price_source": "",
                "currency": "",
                "adjustment_mode": "",
                "invalid_reason": "MISSING_CLOSE_LABEL",
            })
            continue
        rank = raw.get("close_top20_rank")
        if rank in (None, ""):
            rank_value = expected_rank
        elif _v4_global(_v4_scope, 'isinstance')(rank, _v4_global(_v4_scope, 'bool')) or not _v4_global(_v4_scope, 'isinstance')(rank, _v4_global(_v4_scope, 'int')) or not 1 <= rank <= _v4_global(_v4_scope, 'TRUTH_K'):
            invalid.append(f"INVALID_CLOSE_TOP20_RANK:{code}")
            rank_value = None
        else:
            rank_value = rank
            if rank_value in observed_ranks:
                invalid.append(f"DUPLICATE_CLOSE_TOP20_RANK:{code}")
            observed_ranks.add(rank_value)
        if rank_value is not None and rank_value != expected_rank_by_code.get(code):
            invalid.append(f"CLOSE_TOP20_RANK_ORDER_MISMATCH:{code}")
        if rank_value is not None and not expected_hit:
            invalid.append(f"NON_TOP20_CODE_HAS_RANK:{code}")
        if raw.get("hit_top20") is not expected_hit:
            invalid.append(f"HIT_FLAG_MISMATCH:{code}")
        close_price: float | None
        try:
            close_price = _v4_global(_v4_scope, '_finite')(raw.get("close_price"))
            if close_price <= 0:
                raise _v4_global(_v4_scope, 'ShadowInvalid')("close price must be positive")
        except _v4_global(_v4_scope, 'ShadowInvalid'):
            close_price = None
            markout_invalid.append(f"MISSING_OR_INVALID_CLOSE_PRICE:{code}")
        source = _v4_global(_v4_scope, 'str')(raw.get("close_price_source") or "").strip()
        currency = _v4_global(_v4_scope, 'str')(raw.get("currency") or "").strip().upper()
        adjustment = _v4_global(_v4_scope, 'str')(raw.get("adjustment_mode") or "").strip()
        if not source or not currency or not adjustment:
            markout_invalid.append(f"CLOSE_PRICE_SEMANTICS_MISSING:{code}")
        row_payload = {
            "security_id": code,
            "close_top20_rank": rank_value,
            "hit_top20": expected_hit,
            "close_price": close_price,
            "close_price_source": source,
            "currency": currency,
            "adjustment_mode": adjustment,
        }
        row_reasons = [
            *[reason for reason in invalid if reason.endswith(f":{code}")],
            *[reason for reason in markout_invalid if reason.endswith(f":{code}")],
        ]
        if row_reasons:
            row_payload["invalid_reason"] = "|".join(row_reasons)
        normalised.append(row_payload)
    unknown = _v4_global(_v4_scope, 'sorted')(_v4_global(_v4_scope, 'set')(by_code) - _v4_global(_v4_scope, 'set')(member_codes))
    invalid.extend(f"LABEL_NOT_IN_D1_POOL:{code}" for code in unknown)
    expected_member_top20_ranks = {
        row["close_top20_rank"]
        for row in normalised
        if row.get("close_top20_rank") is not None
    }
    if _v4_global(_v4_scope, 'len')(expected_member_top20_ranks) != _v4_global(_v4_scope, 'sum')(1 for code in member_codes if code in top20_set):
        invalid.append("DUPLICATE_OR_MISSING_D1_TOP20_RANKS")
    if _v4_global(_v4_scope, 'set')(member_codes) != _v4_global(_v4_scope, 'set')(by_code):
        # Full D1 label coverage is required for markout and for explicit
        # missing-label accounting; unknown rows cannot repair a missing row.
        pass
    return normalised, invalid, markout_invalid


def _append_labels_body(_v4_scope, /, run_root, labels):
    """Append close labels after the frozen selection files exist.

    Invalid/incomplete truth is recorded as an immutable invalid ledger and is
    never converted to a zero or a negative hit.  The function never rewrites
    any selection artifact.
    """

    members, baseline, candidate, receipt = _v4_global(_v4_scope, '_read_frozen')(run_root)
    if not _v4_global(_v4_scope, 'isinstance')(labels, _v4_global(_v4_scope, 'Mapping')):
        labels = {}
    try:
        admission_mode = _v4_global(_v4_scope, '_admission_mode')(labels, default=None)
    except _v4_global(_v4_scope, 'ShadowInvalid'):
        admission_mode = None
    cutoff = _v4_global(_v4_scope, '_parse_timestamp')(receipt["cutoff_ts"], _v4_global(_v4_scope, 'str')(receipt["trade_date"]), "cutoff_ts")
    run_root_path = _v4_global(_v4_scope, 'Path')(run_root).expanduser().resolve()
    label_dir = run_root_path / "labels"
    label_path = label_dir / "labels.json"
    invalid_path = label_dir / "invalid_ledger.json"
    if label_dir.is_symlink() or label_path.is_symlink() or invalid_path.is_symlink():
        raise _v4_global(_v4_scope, 'ShadowInvalid')("label directory/artifact cannot be symlinked")
    try:
        truth, raw_rows, top20_codes = _v4_global(_v4_scope, '_truth_metadata')(labels, _v4_global(_v4_scope, 'str')(receipt["trade_date"]), cutoff)
        label_rows, invalid_reasons, markout_invalid_reasons = _v4_global(_v4_scope, '_normalise_label_rows')(raw_rows, members, top20_codes)
    except _v4_global(_v4_scope, 'ShadowInvalid') as error:
        truth = {
            "admission_mode": admission_mode,
            "truth_scope": labels.get("truth_scope"),
            "status": "CANNOT_CONFIRM",
        }
        label_rows = []
        invalid_reasons = [_v4_global(_v4_scope, 'str')(error)]
        markout_invalid_reasons = []
    status = (
        "ENGINEERING_ONLY"
        if not invalid_reasons and truth.get("admission_status") == "ENGINEERING_ONLY"
        else ("READY" if not invalid_reasons else "CANNOT_CONFIRM")
    )
    label_payload = {
        "schema_version": _v4_global(_v4_scope, 'LABEL_SCHEMA_VERSION'),
        "experiment_id": _v4_global(_v4_scope, 'EXPERIMENT_ID'),
        "trade_date": receipt["trade_date"],
        "stage": receipt["stage"],
        "cutoff_ts": receipt["cutoff_ts"],
        "admission_mode": admission_mode,
        "status": status,
        "hit_ready": status == "READY",
        "counts_as_forward_day": False,
        "natural_sample_count": 0,
        "truth": truth,
        "rows": label_rows,
        "invalid_reasons": invalid_reasons,
        "markout_invalid_reasons": markout_invalid_reasons,
        "selection_receipt_sha256": _v4_global(_v4_scope, 'sha256_file')(run_root_path / "selection_receipt.json"),
        **_v4_global(_v4_scope, 'SAFETY_FLAGS'),
    }
    label_sha = _v4_global(_v4_scope, '_immutable_json')(label_path, label_payload)
    invalid_payload = {
        "schema_version": _v4_global(_v4_scope, 'LABEL_SCHEMA_VERSION'),
        "experiment_id": _v4_global(_v4_scope, 'EXPERIMENT_ID'),
        "trade_date": receipt["trade_date"],
        "stage": receipt["stage"],
        "admission_mode": admission_mode,
        "status": status,
        "invalid_reasons": invalid_reasons,
        "markout_invalid_reasons": markout_invalid_reasons,
        "labels_sha256": label_sha,
        "recorded_after_selection_freeze": True,
        **_v4_global(_v4_scope, 'SAFETY_FLAGS'),
    }
    invalid_sha = _v4_global(_v4_scope, '_immutable_json')(invalid_path, invalid_payload)
    return {
        "status": status,
        "run_root": _v4_global(_v4_scope, 'str')(run_root_path),
        "labels_sha256": label_sha,
        "invalid_ledger_sha256": invalid_sha,
        "invalid_reasons": invalid_reasons,
        "markout_invalid_reasons": markout_invalid_reasons,
        "label_count": _v4_global(_v4_scope, 'len')(label_rows),
        "safety": _v4_global(_v4_scope, 'dict')(_v4_global(_v4_scope, 'SAFETY_FLAGS')),
    }
