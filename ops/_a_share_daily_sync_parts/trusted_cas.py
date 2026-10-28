"""ops.a_share_daily_sync: trusted_cas (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __trusted_cas_read_json_body(_v4_scope, /, path, expected_sha256, label):
    path = _v4_global(_v4_scope, 'Path')(path)
    if not path.is_absolute() or _v4_global(_v4_scope, '_path_has_symlink_component')(path) or not path.is_file():
        raise _v4_global(_v4_scope, 'ValueError')(f"A_SYNC_TRUSTED_CAS_INVALID_PATH:{label}")
    observed_sha = _v4_global(_v4_scope, '_file_sha256')(path)
    if observed_sha != expected_sha256:
        raise _v4_global(_v4_scope, 'ValueError')(f"A_SYNC_TRUSTED_CAS_SHA_DRIFT:{label}")
    try:
        payload = _v4_global(_v4_scope, 'json').loads(path.read_text(encoding="utf-8"))
    except (_v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'UnicodeDecodeError'), _v4_global(_v4_scope, 'json').JSONDecodeError) as error:
        raise _v4_global(_v4_scope, 'ValueError')(f"A_SYNC_TRUSTED_CAS_INVALID_JSON:{label}") from error
    if not _v4_global(_v4_scope, 'isinstance')(payload, _v4_global(_v4_scope, 'dict')):
        raise _v4_global(_v4_scope, 'ValueError')(f"A_SYNC_TRUSTED_CAS_OBJECT_REQUIRED:{label}")
    return payload


def __trusted_cas_map_body(_v4_scope, /, payload, *, label, expected_count):
    """Read one accepted CAS stage without rescanning it per target symbol."""
    apply = payload.get("apply") if _v4_global(_v4_scope, 'isinstance')(payload.get("apply"), _v4_global(_v4_scope, 'Mapping')) else payload
    candidate = apply.get("candidate_sha256_per_symbol")
    after = apply.get("after_sha256_per_symbol")
    before = apply.get("native_before_sha256_per_symbol")
    symbols = apply.get("applied_symbols")
    if not _v4_global(_v4_scope, 'isinstance')(candidate, _v4_global(_v4_scope, 'Mapping')) or not _v4_global(_v4_scope, 'isinstance')(after, _v4_global(_v4_scope, 'Mapping')) or not _v4_global(_v4_scope, 'isinstance')(before, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'ValueError')(f"A_SYNC_TRUSTED_CAS_MISSING_MAP:{label}")
    if not _v4_global(_v4_scope, 'isinstance')(symbols, _v4_global(_v4_scope, 'list')) or _v4_global(_v4_scope, 'len')(symbols) != expected_count:
        raise _v4_global(_v4_scope, 'ValueError')(f"A_SYNC_TRUSTED_CAS_COUNT_MISMATCH:{label}")
    symbol_set = {_v4_global(_v4_scope, 'str')(symbol) for symbol in symbols}
    if _v4_global(_v4_scope, 'len')(symbol_set) != expected_count or _v4_global(_v4_scope, 'set')(candidate) != symbol_set or _v4_global(_v4_scope, 'set')(after) != symbol_set or _v4_global(_v4_scope, 'set')(before) != symbol_set:
        raise _v4_global(_v4_scope, 'ValueError')(f"A_SYNC_TRUSTED_CAS_SYMBOL_SET_MISMATCH:{label}")
    indexed: dict[str, dict[str, Any]] = {}
    for raw_symbol in _v4_global(_v4_scope, 'sorted')(symbol_set):
        symbol = _v4_global(_v4_scope, 'str')(raw_symbol)
        candidate_sha = _v4_global(_v4_scope, '_trusted_cas_sha256')(candidate.get(symbol), f"{label}.{symbol}.candidate")
        after_sha = _v4_global(_v4_scope, '_trusted_cas_sha256')(after.get(symbol), f"{label}.{symbol}.after")
        before_sha = _v4_global(_v4_scope, '_trusted_cas_sha256')(before.get(symbol), f"{label}.{symbol}.before")
        if candidate_sha != after_sha:
            raise _v4_global(_v4_scope, 'ValueError')(f"A_SYNC_TRUSTED_CAS_AFTER_MISMATCH:{label}:{symbol}")
        indexed[symbol] = {
            "symbol": symbol,
            "candidate_after_sha256": candidate_sha,
            "native_before_sha256": before_sha,
            "receipt_path": _v4_global(_v4_scope, 'str')(payload.get("_receipt_path") or ""),
            "receipt_sha256": _v4_global(_v4_scope, 'str')(payload.get("_receipt_sha256") or ""),
            "cohort": label,
        }
    return indexed, {symbol: _v4_global(_v4_scope, 'str')(symbol) for symbol in _v4_global(_v4_scope, 'sorted')(symbol_set)}


def __trusted_cas_load_inputs_body(_v4_scope, /, path_value, target_int, expected_target_fingerprint):
    """Load reviewed CAS references once; ignore them for an uncovered date."""
    if path_value in (None, ""):
        return None
    path = _v4_global(_v4_scope, 'Path')(path_value).expanduser()
    if not path.is_absolute() or _v4_global(_v4_scope, '_path_has_symlink_component')(path) or not path.is_file():
        raise _v4_global(_v4_scope, 'ValueError')(f"A_SYNC_TRUSTED_CAS_INPUTS_PATH_INVALID:{path}")
    config_sha = _v4_global(_v4_scope, '_file_sha256')(path)
    if config_sha is None:
        raise _v4_global(_v4_scope, 'ValueError')("A_SYNC_TRUSTED_CAS_INPUTS_SHA_UNAVAILABLE")
    try:
        config = _v4_global(_v4_scope, 'json').loads(path.read_text(encoding="utf-8"))
    except (_v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'UnicodeDecodeError'), _v4_global(_v4_scope, 'json').JSONDecodeError) as error:
        raise _v4_global(_v4_scope, 'ValueError')("A_SYNC_TRUSTED_CAS_INPUTS_INVALID_JSON") from error
    if not _v4_global(_v4_scope, 'isinstance')(config, _v4_global(_v4_scope, 'dict')) or config.get("schema_version") != "v3_5.a_sync.trusted_cas_inputs.v1":
        raise _v4_global(_v4_scope, 'ValueError')("A_SYNC_TRUSTED_CAS_INPUTS_SCHEMA_MISMATCH")
    # A global environment variable may remain installed for a later date. It
    # is deliberately inert when the receipt's exact target date is absent.
    if _v4_global(_v4_scope, 'str')(config.get("target_date") or "") != _v4_global(_v4_scope, 'str')(target_int):
        return None
    if _v4_global(_v4_scope, 'str')(config.get("target_date")) != _v4_global(_v4_scope, 'TRUSTED_CAS_TARGET_DATE'):
        raise _v4_global(_v4_scope, 'ValueError')("A_SYNC_TRUSTED_CAS_TARGET_DATE_MISMATCH")
    config_fingerprint = _v4_global(_v4_scope, 'str')(config.get("target_fingerprint") or "").lower()
    if _v4_global(_v4_scope, 'len')(config_fingerprint) != 64 or _v4_global(_v4_scope, 'any')(char not in "0123456789abcdef" for char in config_fingerprint):
        raise _v4_global(_v4_scope, 'ValueError')("A_SYNC_TRUSTED_CAS_TARGET_FINGERPRINT_INVALID")
    if expected_target_fingerprint is not None and config_fingerprint != _v4_global(_v4_scope, 'str')(expected_target_fingerprint).lower():
        raise _v4_global(_v4_scope, 'ValueError')("A_SYNC_TRUSTED_CAS_TARGET_FINGERPRINT_MISMATCH")
    if config.get("rule_id") != _v4_global(_v4_scope, 'TRUSTED_CAS_RULE_ID') or _v4_global(_v4_scope, 'str')(config.get("rule_version")) != _v4_global(_v4_scope, 'TRUSTED_CAS_RULE_VERSION'):
        raise _v4_global(_v4_scope, 'ValueError')("A_SYNC_TRUSTED_CAS_RULE_MISMATCH")
    if config.get("field_rule_id") != _v4_global(_v4_scope, 'FIELD_RULE_ID') or _v4_global(_v4_scope, 'str')(config.get("field_rule_version")) != _v4_global(_v4_scope, 'FIELD_RULE_VERSION'):
        raise _v4_global(_v4_scope, 'ValueError')("A_SYNC_TRUSTED_CAS_FIELD_RULE_MISMATCH")
    if not _v4_global(_v4_scope, '_trusted_cas_safety_ok')(config):
        raise _v4_global(_v4_scope, 'ValueError')("A_SYNC_TRUSTED_CAS_SAFETY_MISMATCH")

    old_spec = config.get("old4662")
    new_spec = config.get("new483")
    if not _v4_global(_v4_scope, 'isinstance')(old_spec, _v4_global(_v4_scope, 'Mapping')) or not _v4_global(_v4_scope, 'isinstance')(new_spec, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'ValueError')("A_SYNC_TRUSTED_CAS_COHORT_CONFIG_MISSING")
    old_expected = _v4_global(_v4_scope, 'int')(old_spec.get("expected_count", 0))
    new_expected = _v4_global(_v4_scope, 'int')(new_spec.get("expected_count", 0))
    if old_expected != 4662 or new_expected != 483:
        raise _v4_global(_v4_scope, 'ValueError')("A_SYNC_TRUSTED_CAS_COHORT_COUNT_MISMATCH")

    old_ref = old_spec.get("integration_receipt")
    if not _v4_global(_v4_scope, 'isinstance')(old_ref, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'ValueError')("A_SYNC_TRUSTED_CAS_OLD_RECEIPT_REF_MISSING")
    old_path = _v4_global(_v4_scope, 'Path')(_v4_global(_v4_scope, 'str')(old_ref.get("path") or ""))
    old_sha = _v4_global(_v4_scope, '_trusted_cas_sha256')(old_ref.get("sha256"), "old4662.receipt")
    old_receipt = _v4_global(_v4_scope, '_trusted_cas_read_json')(old_path, old_sha, "old4662.receipt")
    old_receipt["_receipt_path"] = _v4_global(_v4_scope, 'str')(old_path)
    old_receipt["_receipt_sha256"] = old_sha
    if old_receipt.get("schema_version") != "v3_5.static_cas.parent_native_integration.v1" or old_receipt.get("status") != "APPLIED_RECONCILED_AWAITING_INDEPENDENT_INTEGRATION_REVIEW":
        raise _v4_global(_v4_scope, 'ValueError')("A_SYNC_TRUSTED_CAS_OLD_RECEIPT_STATUS_INVALID")
    if _v4_global(_v4_scope, 'int')(old_receipt.get("applied_count", -1)) != old_expected or _v4_global(_v4_scope, 'int')(old_receipt.get("native_after_sha_match_count", -1)) != old_expected:
        raise _v4_global(_v4_scope, 'ValueError')("A_SYNC_TRUSTED_CAS_OLD_RECEIPT_COUNT_INVALID")
    if not _v4_global(_v4_scope, '_trusted_cas_safety_ok')(old_receipt):
        raise _v4_global(_v4_scope, 'ValueError')("A_SYNC_TRUSTED_CAS_OLD_RECEIPT_SAFETY_INVALID")
    old_entries: dict[str, dict[str, Any]] = {}
    stage_refs = old_receipt.get("stage_receipts")
    if not _v4_global(_v4_scope, 'isinstance')(stage_refs, _v4_global(_v4_scope, 'list')) or _v4_global(_v4_scope, 'len')(stage_refs) != 2:
        raise _v4_global(_v4_scope, 'ValueError')("A_SYNC_TRUSTED_CAS_OLD_STAGE_REFS_INVALID")
    for stage_ref in stage_refs:
        if not _v4_global(_v4_scope, 'isinstance')(stage_ref, _v4_global(_v4_scope, 'Mapping')):
            raise _v4_global(_v4_scope, 'ValueError')("A_SYNC_TRUSTED_CAS_OLD_STAGE_REF_INVALID")
        stage_path = _v4_global(_v4_scope, 'Path')(_v4_global(_v4_scope, 'str')(stage_ref.get("path") or ""))
        stage_sha = _v4_global(_v4_scope, '_trusted_cas_sha256')(stage_ref.get("sha256"), "old4662.stage")
        stage = _v4_global(_v4_scope, '_trusted_cas_read_json')(stage_path, stage_sha, "old4662.stage")
        stage["_receipt_path"] = _v4_global(_v4_scope, 'str')(stage_path)
        stage["_receipt_sha256"] = stage_sha
        if stage.get("schema_version") != "v3_5.static_byte_cas.staged_stage_receipt.v1" or stage.get("status") != "APPLIED":
            raise _v4_global(_v4_scope, 'ValueError')("A_SYNC_TRUSTED_CAS_OLD_STAGE_STATUS_INVALID")
        stage_count = _v4_global(_v4_scope, 'int')(stage.get("stage_member_count", -1))
        stage_entries, _ = _v4_global(_v4_scope, '_trusted_cas_map')(stage, label="old4662", expected_count=stage_count)
        if stage_count <= 0 or _v4_global(_v4_scope, 'set')(old_entries) & _v4_global(_v4_scope, 'set')(stage_entries):
            raise _v4_global(_v4_scope, 'ValueError')("A_SYNC_TRUSTED_CAS_OLD_STAGE_OVERLAP")
        summaries = stage.get("member_summaries")
        if not _v4_global(_v4_scope, 'isinstance')(summaries, _v4_global(_v4_scope, 'list')) or _v4_global(_v4_scope, 'len')(summaries) != stage_count:
            raise _v4_global(_v4_scope, 'ValueError')("A_SYNC_TRUSTED_CAS_OLD_MEMBER_SUMMARY_INVALID")
        summary_by = {_v4_global(_v4_scope, 'str')(row.get("symbol")): row for row in summaries if _v4_global(_v4_scope, 'isinstance')(row, _v4_global(_v4_scope, 'Mapping'))}
        if _v4_global(_v4_scope, 'len')(summary_by) != stage_count or not _v4_global(_v4_scope, 'set')(stage_entries).issubset(summary_by):
            raise _v4_global(_v4_scope, 'ValueError')("A_SYNC_TRUSTED_CAS_OLD_MEMBER_SUMMARY_SCOPE_INVALID")
        for symbol, entry in stage_entries.items():
            summary = summary_by[symbol]
            record_count = summary.get("record_count")
            if (
                _v4_global(_v4_scope, 'str')(summary.get("candidate_sha256")) != entry["candidate_after_sha256"]
                or _v4_global(_v4_scope, 'str')(summary.get("native_path")) == ""
                or not _v4_global(_v4_scope, 'isinstance')(record_count, _v4_global(_v4_scope, 'int'))
                or record_count <= 0
            ):
                raise _v4_global(_v4_scope, 'ValueError')(f"A_SYNC_TRUSTED_CAS_OLD_MEMBER_SUMMARY_BINDING:{symbol}")
            entry["native_path"] = _v4_global(_v4_scope, 'str')(_v4_global(_v4_scope, 'Path')(_v4_global(_v4_scope, 'str')(summary["native_path"])).resolve())
            entry["candidate_path"] = _v4_global(_v4_scope, 'str')(summary.get("candidate_path") or "")
            entry["record_count"] = _v4_global(_v4_scope, 'int')(record_count)
        old_entries.update(stage_entries)
    if _v4_global(_v4_scope, 'len')(old_entries) != old_expected:
        raise _v4_global(_v4_scope, 'ValueError')("A_SYNC_TRUSTED_CAS_OLD_INDEX_COUNT_INVALID")

    new_refs = {
        key: new_spec.get(key)
        for key in ("native_apply_result", "candidate_manifest", "cohort_review")
    }
    if _v4_global(_v4_scope, 'any')(not _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'Mapping')) for value in new_refs.values()):
        raise _v4_global(_v4_scope, 'ValueError')("A_SYNC_TRUSTED_CAS_NEW_RECEIPT_REF_MISSING")
    new_paths = {key: _v4_global(_v4_scope, 'Path')(_v4_global(_v4_scope, 'str')(value.get("path") or "")) for key, value in new_refs.items()}
    new_shas = {key: _v4_global(_v4_scope, '_trusted_cas_sha256')(value.get("sha256"), f"new483.{key}") for key, value in new_refs.items()}
    new_result = _v4_global(_v4_scope, '_trusted_cas_read_json')(new_paths["native_apply_result"], new_shas["native_apply_result"], "new483.native_apply_result")
    new_result["_receipt_path"] = _v4_global(_v4_scope, 'str')(new_paths["native_apply_result"])
    new_result["_receipt_sha256"] = new_shas["native_apply_result"]
    if new_result.get("schema_version") != "v35.remaining_ohlc_integration.executor_receipt.v1" or new_result.get("status") != "APPLIED_RECONCILED_AWAITING_SCHEDULER_RESTORE" or new_result.get("pass_signal") is not True or new_result.get("native_integration_status") != "APPLIED_RECONCILED":
        raise _v4_global(_v4_scope, 'ValueError')("A_SYNC_TRUSTED_CAS_NEW_RECEIPT_STATUS_INVALID")
    if not _v4_global(_v4_scope, '_trusted_cas_safety_ok')(new_result) or _v4_global(_v4_scope, 'int')((new_result.get("apply") or {}).get("applied_count", -1)) != new_expected:
        raise _v4_global(_v4_scope, 'ValueError')("A_SYNC_TRUSTED_CAS_NEW_RECEIPT_SAFETY_OR_COUNT_INVALID")
    checks = new_result.get("checks")
    if not _v4_global(_v4_scope, 'isinstance')(checks, _v4_global(_v4_scope, 'Mapping')) or checks.get("independent_cohort_review_receipt_sha256") != new_shas["cohort_review"] or checks.get("candidate_manifest_sha256") != new_shas["candidate_manifest"]:
        raise _v4_global(_v4_scope, 'ValueError')("A_SYNC_TRUSTED_CAS_NEW_RECEIPT_BINDING_INVALID")
    review = _v4_global(_v4_scope, '_trusted_cas_read_json')(new_paths["cohort_review"], new_shas["cohort_review"], "new483.cohort_review")
    verdict = review.get("verdict")
    oracles = review.get("cohort_oracles")
    bound = review.get("bound_artifacts")
    bound_manifest = bound.get("candidate_manifest") if _v4_global(_v4_scope, 'isinstance')(bound, _v4_global(_v4_scope, 'Mapping')) else None
    if (
        review.get("schema_version") != "v35.remaining_ohlc.cohort_review.v2"
        or review.get("reviewer") != "a_ohlc_canary_review"
        or not _v4_global(_v4_scope, 'isinstance')(verdict, _v4_global(_v4_scope, 'Mapping'))
        or verdict.get("REVIEWED") != "PASS"
        or verdict.get("overall") != "PASS_FROZEN_COHORT_AND_INTEGRATION_METADATA_ONLY"
        or not _v4_global(_v4_scope, 'isinstance')(oracles, _v4_global(_v4_scope, 'Mapping'))
        or oracles.get("all_oracles_pass") is not True
        or oracles.get("candidate_pass_symbols") != new_expected
        or not _v4_global(_v4_scope, 'isinstance')(bound, _v4_global(_v4_scope, 'Mapping'))
        or not _v4_global(_v4_scope, 'isinstance')(bound_manifest, _v4_global(_v4_scope, 'Mapping'))
        or bound_manifest.get("sha256") != new_shas["candidate_manifest"]
    ):
        raise _v4_global(_v4_scope, 'ValueError')("A_SYNC_TRUSTED_CAS_COHORT_REVIEW_INVALID")
    manifest = _v4_global(_v4_scope, '_trusted_cas_read_json')(new_paths["candidate_manifest"], new_shas["candidate_manifest"], "new483.candidate_manifest")
    candidates = manifest.get("candidates")
    if manifest.get("schema_version") != "v3_5.remaining_ohlc_cohort.candidate_manifest.v1" or manifest.get("candidate_count") != new_expected or not _v4_global(_v4_scope, 'isinstance')(candidates, _v4_global(_v4_scope, 'list')) or _v4_global(_v4_scope, 'len')(candidates) != new_expected:
        raise _v4_global(_v4_scope, 'ValueError')("A_SYNC_TRUSTED_CAS_CANDIDATE_MANIFEST_INVALID")
    manifest_by: dict[str, Mapping[str, Any]] = {}
    for candidate in candidates:
        if not _v4_global(_v4_scope, 'isinstance')(candidate, _v4_global(_v4_scope, 'Mapping')):
            raise _v4_global(_v4_scope, 'ValueError')("A_SYNC_TRUSTED_CAS_CANDIDATE_ROW_INVALID")
        symbol = _v4_global(_v4_scope, 'str')(candidate.get("symbol") or "")
        if not symbol or symbol in manifest_by or candidate.get("status") != "CANDIDATE_PASS" or candidate.get("strict_gate_status") != "PASS":
            raise _v4_global(_v4_scope, 'ValueError')("A_SYNC_TRUSTED_CAS_CANDIDATE_ROW_NOT_ACCEPTED")
        candidate_sha = _v4_global(_v4_scope, '_trusted_cas_sha256')(candidate.get("candidate_sha256"), f"new483.{symbol}.candidate")
        after_sha = _v4_global(_v4_scope, '_trusted_cas_sha256')(candidate.get("after_sha256"), f"new483.{symbol}.after")
        native_before_sha = _v4_global(_v4_scope, '_trusted_cas_sha256')(candidate.get("native_before_sha256"), f"new483.{symbol}.before")
        gate_results = candidate.get("gate_results")
        if (
            candidate_sha != after_sha
            or not _v4_global(_v4_scope, 'isinstance')(gate_results, _v4_global(_v4_scope, 'Mapping'))
            or gate_results.get("full_candidate_gate") is not True
            or not _v4_global(_v4_scope, 'isinstance')(candidate.get("native_path"), _v4_global(_v4_scope, 'str'))
        ):
            raise _v4_global(_v4_scope, 'ValueError')(f"A_SYNC_TRUSTED_CAS_CANDIDATE_BINDING_INVALID:{symbol}")
        manifest_by[symbol] = {
            "symbol": symbol,
            "candidate_after_sha256": candidate_sha,
            "native_before_sha256": native_before_sha,
            "native_path": _v4_global(_v4_scope, 'str')(_v4_global(_v4_scope, 'Path')(candidate["native_path"]).resolve()),
            "candidate_path": _v4_global(_v4_scope, 'str')(candidate.get("candidate_path") or ""),
            "cohort": "new483",
            "receipt_path": _v4_global(_v4_scope, 'str')(new_paths["native_apply_result"]),
            "receipt_sha256": new_shas["native_apply_result"],
            "cohort_review_path": _v4_global(_v4_scope, 'str')(new_paths["cohort_review"]),
            "cohort_review_sha256": new_shas["cohort_review"],
            "candidate_manifest_path": _v4_global(_v4_scope, 'str')(new_paths["candidate_manifest"]),
            "candidate_manifest_sha256": new_shas["candidate_manifest"],
            "record_count": _v4_global(_v4_scope, 'int')(candidate.get("native_record_count", 0)),
        }
        if manifest_by[symbol]["record_count"] <= 0:
            raise _v4_global(_v4_scope, 'ValueError')(f"A_SYNC_TRUSTED_CAS_CANDIDATE_RECORD_COUNT_INVALID:{symbol}")
    new_entries: dict[str, dict[str, Any]] = {}
    new_apply = new_result.get("apply")
    if not _v4_global(_v4_scope, 'isinstance')(new_apply, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'ValueError')("A_SYNC_TRUSTED_CAS_NEW_APPLY_MISSING")
    for stage_name in ("canary", "remainder"):
        stage = new_apply.get(stage_name)
        if not _v4_global(_v4_scope, 'isinstance')(stage, _v4_global(_v4_scope, 'Mapping')):
            raise _v4_global(_v4_scope, 'ValueError')("A_SYNC_TRUSTED_CAS_NEW_STAGE_MISSING")
        stage_entries, _ = _v4_global(_v4_scope, '_trusted_cas_map')(stage, label="new483", expected_count=_v4_global(_v4_scope, 'int')(stage.get("applied_count", -1)))
        if _v4_global(_v4_scope, 'set')(new_entries) & _v4_global(_v4_scope, 'set')(stage_entries):
            raise _v4_global(_v4_scope, 'ValueError')("A_SYNC_TRUSTED_CAS_NEW_STAGE_OVERLAP")
        for symbol, stage_entry in stage_entries.items():
            manifest_entry = manifest_by.get(symbol)
            if manifest_entry is None or manifest_entry["candidate_after_sha256"] != stage_entry["candidate_after_sha256"] or manifest_entry["native_before_sha256"] != stage_entry["native_before_sha256"]:
                raise _v4_global(_v4_scope, 'ValueError')(f"A_SYNC_TRUSTED_CAS_NEW_MANIFEST_BINDING:{symbol}")
            new_entries[symbol] = _v4_global(_v4_scope, 'dict')(manifest_entry)
    if _v4_global(_v4_scope, 'len')(new_entries) != new_expected:
        raise _v4_global(_v4_scope, 'ValueError')("A_SYNC_TRUSTED_CAS_NEW_INDEX_COUNT_INVALID")
    if _v4_global(_v4_scope, 'set')(old_entries) & _v4_global(_v4_scope, 'set')(new_entries):
        raise _v4_global(_v4_scope, 'ValueError')("A_SYNC_TRUSTED_CAS_COHORT_OVERLAP")
    indexed = _v4_global(_v4_scope, 'dict')(old_entries)
    indexed.update(new_entries)
    return {
        "schema_version": config["schema_version"],
        "config_path": _v4_global(_v4_scope, 'str')(path),
        "config_sha256": config_sha,
        "target_date": _v4_global(_v4_scope, 'str')(target_int),
        "target_fingerprint": _v4_global(_v4_scope, 'str')(config.get("target_fingerprint") or ""),
        "rule_id": _v4_global(_v4_scope, 'TRUSTED_CAS_RULE_ID'),
        "rule_version": _v4_global(_v4_scope, 'TRUSTED_CAS_RULE_VERSION'),
        "field_rule_id": _v4_global(_v4_scope, 'FIELD_RULE_ID'),
        "field_rule_version": _v4_global(_v4_scope, 'FIELD_RULE_VERSION'),
        "entries": indexed,
        "cohort_counts": {"old4662": _v4_global(_v4_scope, 'len')(old_entries), "new483": _v4_global(_v4_scope, 'len')(new_entries), "total": _v4_global(_v4_scope, 'len')(indexed)},
    }


def __trusted_cas_local_reuse_body(_v4_scope, /, index, target, target_int, current_sha, history, history_failure, field_violations):
    """Return a receipt-bound no-provider reuse only after strict local gates."""
    if not _v4_global(_v4_scope, 'isinstance')(index, _v4_global(_v4_scope, 'Mapping')) or _v4_global(_v4_scope, 'str')(index.get("target_date")) != _v4_global(_v4_scope, 'str')(target_int):
        return None
    if history_failure is not None or field_violations or not history or _v4_global(_v4_scope, 'day_int')(_v4_global(_v4_scope, 'dict')(history[-1])) != target_int:
        return None
    valid, _reason = _v4_global(_v4_scope, 'valid_hq_bar')(_v4_global(_v4_scope, 'dict')(history[-1]))
    if not valid or not current_sha:
        return None
    # Re-read the file identity after the full history scan so a concurrent
    # native mutation cannot be accepted under the digest captured before the
    # scan.
    verified_sha = _v4_global(_v4_scope, '_file_sha256')(_v4_global(_v4_scope, 'Path')(target.path))
    if verified_sha is None or verified_sha.lower() != current_sha.lower():
        return None
    entry = (index.get("entries") or {}).get(_v4_global(_v4_scope, 'str')(target.code))
    if not _v4_global(_v4_scope, 'isinstance')(entry, _v4_global(_v4_scope, 'Mapping')):
        return None
    if _v4_global(_v4_scope, 'str')(_v4_global(_v4_scope, 'Path')(_v4_global(_v4_scope, 'str')(entry.get("native_path") or "")).resolve()) != _v4_global(_v4_scope, 'str')(_v4_global(_v4_scope, 'Path')(target.path).resolve()):
        return None
    candidate_sha = _v4_global(_v4_scope, 'str')(entry.get("candidate_after_sha256") or "").lower()
    if _v4_global(_v4_scope, 'len')(candidate_sha) != 64 or verified_sha.lower() != candidate_sha:
        return None
    expected_record_count = entry.get("record_count")
    if not _v4_global(_v4_scope, 'isinstance')(expected_record_count, _v4_global(_v4_scope, 'int')) or expected_record_count <= 0 or _v4_global(_v4_scope, 'len')(history) != expected_record_count:
        return None
    if _v4_global(_v4_scope, 'str')(entry.get("cohort") or "") not in {"old4662", "new483"}:
        return None
    return entry
