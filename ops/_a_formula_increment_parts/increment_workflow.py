"""ops.a_formula_increment: increment_workflow (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __run_success_body(_v4_scope, /, *, target_date, input_root, input_manifest, data_root, return_root, selector_pointer, backtest_pointer, selector_seed, backtest_seed, contract_csv, legacy_formula_source):
    output_root = _v4_global(_v4_scope, '_safe_output_root')(data_root, return_root, selector_pointer, backtest_pointer)
    input_frame, manifest = _v4_global(_v4_scope, '_load_input_manifest')(input_root, input_manifest, target_date)
    contract_rows = _v4_global(_v4_scope, 'load_authoritative_contract_rows')(contract_csv)
    policy = _v4_global(_v4_scope, 'build_contract_policy')(contract_rows, contract_csv)
    selector_current = _v4_global(_v4_scope, '_read_seed')(selector_seed, "selector")
    backtest_current = _v4_global(_v4_scope, '_read_seed')(backtest_seed, "backtest")
    source_seed_sha = _v4_global(_v4_scope, 'sha256_file')(_v4_global(_v4_scope, '_resolved')(selector_seed))
    backtest_seed_sha = _v4_global(_v4_scope, 'sha256_file')(_v4_global(_v4_scope, '_resolved')(backtest_seed))
    history = _v4_global(_v4_scope, 'collect_increment_history')(input_frame)
    features = _v4_global(_v4_scope, 'compute_formula_features')(history)
    features = _v4_global(_v4_scope, '_backfill_increment_contract_columns')(
        features,
        selector_current,
        backtest_current,
    )
    contract_version = _v4_global(_v4_scope, 'str')(policy["contract_version"])
    features["field_contract_version"] = contract_version
    boundary = _v4_global(_v4_scope, '_audit_increment_boundary')(selector_current, _v4_global(_v4_scope, 'select_generated_increment_rows')(features, selector_current))
    if boundary["status"] != "PASS":
        raise _v4_global(_v4_scope, 'AuthorityError')(f"increment boundary failed: {boundary}")
    selector_increment = _v4_global(_v4_scope, 'filter_increment_rows')(features, selector_current, role="selector")
    backtest_increment = _v4_global(_v4_scope, 'filter_increment_rows')(features, backtest_current, role="backtest")
    if selector_increment.empty or backtest_increment.empty:
        if selector_increment.empty and backtest_increment.empty:
            selector_max = _v4_global(_v4_scope, 'int')(selector_current["trade_date"].max()) if not selector_current.empty else 0
            backtest_max = _v4_global(_v4_scope, 'int')(backtest_current["trade_date"].max()) if not backtest_current.empty else 0
            if selector_max >= target_date and backtest_max >= target_date:
                selector_history_gate = _v4_global(_v4_scope, '_audit_existing_history')(
                    selector_current,
                    selector_current,
                    role="selector_history",
                    target_date=target_date,
                    seed_sha256=source_seed_sha,
                )
                backtest_history_gate = _v4_global(_v4_scope, '_audit_existing_history')(
                    backtest_current,
                    backtest_current,
                    role="backtest_history",
                    target_date=target_date,
                    seed_sha256=backtest_seed_sha,
                )
                return {
                    "status": "READY",
                    "already_current": True,
                    "target_date": target_date,
                    "run_id": _v4_global(_v4_scope, 'str')(manifest["run_id"]),
                    "selector_pointer_ready": selector_pointer.exists(),
                    "backtest_pointer_ready": backtest_pointer.exists(),
                    "source_panel_sha256": source_seed_sha,
                    "input_manifest_sha256": _v4_global(_v4_scope, 'str')(manifest["manifest_sha256"]),
                    "contract_sha256": _v4_global(_v4_scope, 'sha256_file')(contract_csv),
                    "formula_source_sha256": _v4_global(_v4_scope, 'FORMULA_ORIGIN_SHA256'),
                    "historical_seed_health": _v4_global(_v4_scope, '_historical_seed_health')(selector_history_gate, backtest_history_gate),
                    "gates": {
                        "selector_history": selector_history_gate,
                        "backtest_history": backtest_history_gate,
                    },
                    "resource_limit_status": "CANNOT_CONFIRM_MACOS_RSS_LIMIT",
                    **_v4_global(_v4_scope, 'SAFETY_FLAGS'),
                }
        raise _v4_global(_v4_scope, 'AuthorityError')("selector/backtest increments do not both contain target rows")
    if not (selector_increment["trade_date"] == target_date).any() or not (backtest_increment["trade_date"] == target_date).any():
        raise _v4_global(_v4_scope, 'AuthorityError')("selector/backtest increment target-date coverage failed")
    selector_source = _v4_global(_v4_scope, '_append_rows')(selector_current, selector_increment, role="selector")
    backtest_source = _v4_global(_v4_scope, '_append_rows')(backtest_current, backtest_increment, role="backtest")
    _v4_global(_v4_scope, 'validate_new_selector_rows')(selector_increment, target_date, role="selector_increment")
    _v4_global(_v4_scope, 'validate_new_selector_rows')(backtest_increment, target_date, role="backtest_increment")
    selector_source_gate = _v4_global(_v4_scope, '_audit_existing_history')(
        selector_current,
        selector_source,
        role="selector_history",
        target_date=target_date,
        seed_sha256=source_seed_sha,
    )
    backtest_source_gate = _v4_global(_v4_scope, '_audit_existing_history')(
        backtest_current,
        backtest_source,
        role="backtest_history",
        target_date=target_date,
        seed_sha256=backtest_seed_sha,
    )
    historical_seed_health = _v4_global(_v4_scope, '_historical_seed_health')(selector_source_gate, backtest_source_gate)
    selector_official = _v4_global(_v4_scope, 'build_official_selector_frame')(selector_source, policy)
    selector_sidecar = _v4_global(_v4_scope, 'build_sidecar_frame')(selector_source, policy)
    official_key_sha = _v4_global(_v4_scope, '_key_sha256')(selector_official)
    sidecar_key_sha = _v4_global(_v4_scope, '_key_sha256')(selector_sidecar)
    if _v4_global(_v4_scope, 'len')(selector_official) != _v4_global(_v4_scope, 'len')(selector_sidecar) or official_key_sha != sidecar_key_sha:
        raise _v4_global(_v4_scope, 'AuthorityError')("official selector and sidecar key sets differ")
    official_gate = {
        "status": "PASS",
        "column_count": _v4_global(_v4_scope, 'int')(_v4_global(_v4_scope, 'len')(selector_official.columns)),
        "row_count": _v4_global(_v4_scope, 'int')(_v4_global(_v4_scope, 'len')(selector_official)),
        "target_rows": _v4_global(_v4_scope, 'int')((selector_official["trade_date"] == target_date).sum()),
        "sidecar_column_count": _v4_global(_v4_scope, 'int')(_v4_global(_v4_scope, 'len')(selector_sidecar.columns) - _v4_global(_v4_scope, 'len')(_v4_global(_v4_scope, 'KEY_COLUMNS'))),
    }
    if official_gate["target_rows"] < 1 or official_gate["sidecar_column_count"] != 12:
        raise _v4_global(_v4_scope, 'AuthorityError')("official selector/sidecar projection gate failed")
    run_id = _v4_global(_v4_scope, 'str')(manifest["run_id"])
    run_dir = _v4_global(_v4_scope, '_resolved')(return_root) / f"a_formula_{target_date}_{run_id}"
    if run_dir.exists():
        raise _v4_global(_v4_scope, 'AuthorityError')(f"run output already exists; refusing overwrite: {run_dir}")
    run_dir.mkdir(parents=True, mode=0o700)
    if _v4_global(_v4_scope, '_path_has_symlink')(run_dir, stop=output_root):
        raise _v4_global(_v4_scope, 'AuthorityError')("run output directory is symlinked")
    source_path = run_dir / "selector_source.parquet"
    official_path = run_dir / "selector_official.parquet"
    sidecar_path = run_dir / "selector_aux_sidecar.parquet"
    backtest_path = run_dir / "backtest_candidate.parquet"
    _v4_global(_v4_scope, '_atomic_parquet')(selector_source, source_path)
    _v4_global(_v4_scope, '_atomic_parquet')(selector_official, official_path)
    _v4_global(_v4_scope, '_atomic_parquet')(selector_sidecar, sidecar_path)
    _v4_global(_v4_scope, '_atomic_parquet')(backtest_source, backtest_path)
    for role, path in (("selector_source", source_path), ("selector_official", official_path), ("selector_sidecar", sidecar_path), ("backtest", backtest_path)):
        if not path.is_file() or _v4_global(_v4_scope, '_path_has_symlink')(path, stop=run_dir):
            raise _v4_global(_v4_scope, 'AuthorityError')(f"{role} artifact missing/unsafe after write")
    generation_source, owned_manifest, owned_receipt = _v4_global(_v4_scope, '_prepare_generation_owned_evidence')(
        run_dir,
        manifest,
        target_date=target_date,
    )
    generation_metadata = {
        "target_date": target_date,
        "run_id": run_id,
        "source": {
            **generation_source,
            "sha256": _v4_global(_v4_scope, 'str')(manifest["source_sha256"]),
        },
        "input_manifest": {
            "path": owned_manifest["path"],
            "bytes": owned_manifest["bytes"],
            # ``sha256`` is the byte digest of the JSON file.  Keep the
            # manifest's internal canonical digest separate so consumers do
            # not confuse the two provenance layers.
            "sha256": owned_manifest["sha256"],
            "manifest_sha256": _v4_global(_v4_scope, 'str')(manifest["manifest_sha256"]),
        },
        "selector_source": _v4_global(_v4_scope, '_generation_target_metadata')(source_path, output_root, "selector_source"),
        "selector_sidecar": _v4_global(_v4_scope, '_generation_target_metadata')(sidecar_path, output_root, "selector_sidecar"),
    }
    pointer_txn = _v4_global(_v4_scope, '_write_pointer_pair')(
        selector_pointer,
        backtest_pointer,
        official_path,
        backtest_path,
        output_root,
        generation_metadata,
    )
    receipt_path = run_dir / "authority-receipt.json"
    payload: dict[str, Any] = {
        "schema": _v4_global(_v4_scope, 'SCHEMA_VERSION'),
        "status": "READY",
        "target_date": target_date,
        "market": "A",
        "run_id": run_id,
        "source": manifest["source"],
        "source_sha256": manifest["source_sha256"],
        "input_manifest": _v4_global(_v4_scope, 'str')(input_manifest),
        "input_manifest_sha256": manifest["manifest_sha256"],
        "input_source_files": manifest["_source_files_sha256"],
        "input_rows": _v4_global(_v4_scope, 'int')(_v4_global(_v4_scope, 'len')(input_frame)),
        "input_symbols": _v4_global(_v4_scope, 'int')(input_frame["ts_code"].nunique()),
        "history_tail_records": _v4_global(_v4_scope, 'TAIL_RECORDS'),
        "source_seed_sha256": source_seed_sha,
        "backtest_seed_sha256": backtest_seed_sha,
        "formula_source": _v4_global(_v4_scope, 'FORMULA_SOURCE'),
        "formula_version": _v4_global(_v4_scope, 'FORMULA_VERSION'),
        "formula_source_sha256": _v4_global(_v4_scope, 'FORMULA_ORIGIN_SHA256'),
        "increment_origin_sha256": _v4_global(_v4_scope, 'INCREMENT_ORIGIN_SHA256'),
        "contract_sha256": _v4_global(_v4_scope, 'sha256_file')(contract_csv),
        "contract_origin_sha256": _v4_global(_v4_scope, 'CONTRACT_ORIGIN_SHA256'),
        "contract_version": contract_version,
        "contract_counts": {"rows": 199, "official_current": 187, "sidecar": 12},
        "coverage": {"selector_source_rows": _v4_global(_v4_scope, 'int')(_v4_global(_v4_scope, 'len')(selector_source)), "selector_official_rows": _v4_global(_v4_scope, 'int')(_v4_global(_v4_scope, 'len')(selector_official)), "target_rows": _v4_global(_v4_scope, 'int')((selector_official["trade_date"] == target_date).sum()), "symbols": _v4_global(_v4_scope, 'int')(selector_official["ts_code"].nunique())},
        "historical_seed_health": historical_seed_health,
        "gates": {"increment_boundary": boundary, "selector_source": selector_source_gate, "backtest_source": backtest_source_gate, "official_projection": official_gate, "sidecar_keys": {"status": "PASS", "rows": _v4_global(_v4_scope, 'int')(_v4_global(_v4_scope, 'len')(selector_sidecar)), "key_count": _v4_global(_v4_scope, 'int')(_v4_global(_v4_scope, 'len')(selector_sidecar)), "key_sha256": sidecar_key_sha, "source_key_sha256": official_key_sha, "columns": _v4_global(_v4_scope, 'list')(selector_sidecar.columns)}, "existing_207_column_contract": {"status": "RECORDED_FAIL_SOFT", "reason": "historical source schema may retain review/sidecar fields; official projection is separately gated"}},
        "sidecar_binding": {"status": "PASS", "market": "A", "target_date": target_date, "run_id": run_id, "input_manifest_sha256": manifest["manifest_sha256"], "source_panel_sha256": source_seed_sha, "key_count": _v4_global(_v4_scope, 'int')(_v4_global(_v4_scope, 'len')(selector_sidecar)), "key_sha256": sidecar_key_sha, "auxiliary_columns": _v4_global(_v4_scope, 'list')(policy["sidecar_columns"])},
        "artifacts": {role: {"path": _v4_global(_v4_scope, 'str')(path), "bytes": path.stat().st_size, "sha256": _v4_global(_v4_scope, 'sha256_file')(path)} for role, path in (("selector_source", source_path), ("selector_official", official_path), ("selector_aux_sidecar", sidecar_path), ("backtest", backtest_path))},
        "generation_owned_evidence": {
            "input_manifest": {key: owned_manifest[key] for key in ("path", "bytes", "sha256")},
            "sync_receipt": {key: owned_receipt[key] for key in ("path", "bytes", "sha256")},
        },
        "pointers": pointer_txn,
        "legacy_formula_source_recorded": _v4_global(_v4_scope, 'str')(legacy_formula_source or ""),
        "process": {"worker_mode": "serial", "resource_limit_status": "CANNOT_CONFIRM_MACOS_RSS_LIMIT", "network": "NOT_USED"},
        **_v4_global(_v4_scope, 'SAFETY_FLAGS'),
    }
    _v4_global(_v4_scope, '_write_receipt')(receipt_path, payload)
    payload["receipt_path"] = _v4_global(_v4_scope, 'str')(receipt_path)
    payload["receipt_sha256"] = _v4_global(_v4_scope, 'sha256_file')(receipt_path)
    payload["receipt_bytes"] = receipt_path.stat().st_size
    return payload


def _run_increment_authority_body(_v4_scope, /, *, target_date, input_root, input_manifest, data_root, return_root, selector_pointer, backtest_pointer, selector_seed, backtest_seed, contract_csv, legacy_formula_source):
    target = 0
    try:
        target = _v4_global(_v4_scope, 'int')(_v4_global(_v4_scope, 'str')(target_date).replace("-", ""))
    except (_v4_global(_v4_scope, 'TypeError'), _v4_global(_v4_scope, 'ValueError')) as error:
        return {
            "schema": _v4_global(_v4_scope, 'SCHEMA_VERSION'),
            "status": "FAILED",
            "target_date": _v4_global(_v4_scope, 'str')(target_date),
            "run_id": "unknown",
            "error_type": _v4_global(_v4_scope, 'type')(error).__name__,
            "error": f"invalid target_date: {target_date}",
            "pointers_unchanged": True,
            "resource_limit_status": "CANNOT_CONFIRM_MACOS_RSS_LIMIT",
            "network": "NOT_USED",
            **_v4_global(_v4_scope, 'SAFETY_FLAGS'),
        }
    raw_return_root = _v4_global(_v4_scope, 'Path')(return_root).expanduser()
    return_path = _v4_global(_v4_scope, '_resolved')(raw_return_root)
    run_id = "unknown"
    safe_output = False
    try:
        # Preflight all output ancestry before creating a failure receipt. A
        # caller cannot turn the formal release/state tree into a receipt sink
        # merely by sending an invalid manifest.
        _v4_global(_v4_scope, '_safe_output_root')(
            _v4_global(_v4_scope, 'Path')(data_root).expanduser(),
            raw_return_root,
            _v4_global(_v4_scope, 'Path')(selector_pointer).expanduser(),
            _v4_global(_v4_scope, 'Path')(backtest_pointer).expanduser(),
        )
        safe_output = True
        return_path.mkdir(parents=True, exist_ok=True)
        try:
            maybe_manifest = _v4_global(_v4_scope, '_read_json')(_v4_global(_v4_scope, '_resolved')(input_manifest))
            run_id = _v4_global(_v4_scope, 'str')(maybe_manifest.get("run_id", "unknown"))
        except _v4_global(_v4_scope, 'Exception'):
            pass
        return _v4_global(_v4_scope, '_run_success')(
            target_date=target,
            input_root=_v4_global(_v4_scope, 'Path')(input_root).expanduser(),
            input_manifest=_v4_global(_v4_scope, 'Path')(input_manifest).expanduser(),
            data_root=_v4_global(_v4_scope, 'Path')(data_root).expanduser(),
            return_root=return_path,
            selector_pointer=_v4_global(_v4_scope, 'Path')(selector_pointer).expanduser(),
            backtest_pointer=_v4_global(_v4_scope, 'Path')(backtest_pointer).expanduser(),
            selector_seed=_v4_global(_v4_scope, 'Path')(selector_seed).expanduser(),
            backtest_seed=_v4_global(_v4_scope, 'Path')(backtest_seed).expanduser(),
            contract_csv=_v4_global(_v4_scope, 'Path')(contract_csv).expanduser(),
            legacy_formula_source=legacy_formula_source,
        )
    except _v4_global(_v4_scope, 'Exception') as error:
        payload = {
            "schema": _v4_global(_v4_scope, 'SCHEMA_VERSION'),
            "status": "FAILED",
            "target_date": target,
            "run_id": run_id,
            "error_type": _v4_global(_v4_scope, 'type')(error).__name__,
            "error": _v4_global(_v4_scope, 'str')(error),
            "pointers_unchanged": True,
            "resource_limit_status": "CANNOT_CONFIRM_MACOS_RSS_LIMIT",
            "network": "NOT_USED",
            **_v4_global(_v4_scope, 'SAFETY_FLAGS'),
        }
        receipt_path = return_path / f"a_formula_{target}_{run_id}-failure-receipt.json"
        if not safe_output:
            return payload
        try:
            _v4_global(_v4_scope, '_write_receipt')(receipt_path, payload)
            payload["receipt_path"] = _v4_global(_v4_scope, 'str')(receipt_path)
            payload["receipt_sha256"] = _v4_global(_v4_scope, 'sha256_file')(receipt_path)
            payload["receipt_bytes"] = receipt_path.stat().st_size
        except _v4_global(_v4_scope, 'Exception') as receipt_error:
            payload["receipt_write_error"] = f"{_v4_global(_v4_scope, 'type')(receipt_error).__name__}: {receipt_error}"
        return payload
