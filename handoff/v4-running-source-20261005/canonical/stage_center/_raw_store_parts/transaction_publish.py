"""stage_center.raw_store: transaction_publish (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _RawStore_publish_body(
    _v4_scope, /, self, *, trade_date, stage_id, market, source_id,
    source_status, rows, cannot_confirm, source_evidence, requested_rows,
    missing_symbols, window, cutoff_at, research_observation_contract=None,
):
    _v4_global(_v4_scope, '_validate_date')(trade_date)
    _v4_global(_v4_scope, '_stage')(stage_id)
    if market not in _v4_global(_v4_scope, '_stage')(stage_id).markets:
        raise _v4_global(_v4_scope, 'RawStoreError')(f"market {market!r} is not scheduled for {stage_id!r}")
    if not _v4_global(_v4_scope, 'isinstance')(source_id, _v4_global(_v4_scope, 'str')) or not source_id or "/" in source_id or "\\" in source_id:
        raise _v4_global(_v4_scope, 'RawStoreError')("source_id is unsafe")
    allow_temporal_false_observation = _v4_global(
        _v4_scope, '_allows_temporal_false_observation'
    )(
        contract=research_observation_contract,
        trade_date=trade_date,
        stage_id=stage_id,
        market=market,
        source_id=source_id,
        source_status=source_status,
        rows=rows,
        requested_rows=requested_rows,
        missing_symbols=missing_symbols,
        cannot_confirm=cannot_confirm,
        source_evidence=source_evidence,
    )
    if research_observation_contract is not None and not allow_temporal_false_observation:
        raise _v4_global(_v4_scope, 'RawStoreError')(
            "explicit HK research temporal-false publication contract mismatch"
        )
    validated, issues = _v4_global(_v4_scope, 'validate_rows')(
        rows,
        trade_date=trade_date,
        stage_id=stage_id,
        market=market,
        allow_temporal_false_observation=allow_temporal_false_observation,
    )
    status = _v4_global(_v4_scope, '_status')(source_status, validated, issues, cannot_confirm)
    normalized_source_status = {"READ_OK": "READY", "READ_FAILED": "CANNOT_CONFIRM"}.get(source_status, source_status)
    requested = _v4_global(_v4_scope, 'len')(rows) if requested_rows is None else _v4_global(_v4_scope, 'int')(requested_rows)
    if requested < 0:
        raise _v4_global(_v4_scope, 'RawStoreError')("requested_rows must be non-negative")
    missing = _v4_global(_v4_scope, 'list')(_v4_global(_v4_scope, 'dict').fromkeys(_v4_global(_v4_scope, 'str')(item) for item in missing_symbols))
    evidence = _v4_global(_v4_scope, 'list')(_v4_global(_v4_scope, 'dict').fromkeys(_v4_global(_v4_scope, 'str')(item) for item in (*source_evidence, *cannot_confirm, *issues)))
    cannot = _v4_global(_v4_scope, 'list')(_v4_global(_v4_scope, 'dict').fromkeys(_v4_global(_v4_scope, 'str')(item) for item in (*cannot_confirm, *issues)))
    source_rows = _v4_global(_v4_scope, 'len')(validated)
    coverage = _v4_global(_v4_scope, '_coverage')(requested, source_rows)
    input_sha = _v4_global(_v4_scope, 'canonical_sha')(
        {
            "source_id": source_id,
            "source_status": normalized_source_status,
            "rows": validated,
            "cannot_confirm": cannot,
            "source_evidence": evidence,
            "requested_rows": requested,
            "missing_symbols": missing,
        }
    )
    idem_key = _v4_global(_v4_scope, 'canonical_sha')(
        {
            "owner": "stage_center",
            "trade_date": trade_date,
            "stage_id": stage_id,
            "market": market,
            "source_id": source_id,
            "input_sha256": input_sha,
        }
    )
    role = self._role(stage_id, market)
    run_id = f"{trade_date}-{role.lower()}-{idem_key[:16]}"
    prefix = f"runs/{trade_date}/{role}/{run_id}"
    artifact_relative = f"{prefix}/artifact.csv"
    manifest_relative = f"{prefix}/manifest.json"
    receipt_relative = f"{prefix}/receipt.json"
    manifest: dict[str, Any]
    receipt: dict[str, Any]
    with self._lock():
        latest = self._load_latest()
        key = self._entry_key(trade_date, stage_id, market)
        existing = latest["entries"].get(key)
        if _v4_global(_v4_scope, 'isinstance')(existing, _v4_global(_v4_scope, 'Mapping')):
            if existing.get("idempotency_key") != idem_key:
                raise _v4_global(_v4_scope, 'RawStoreError')(f"raw slot conflict: {key}")
            verified = self.verify_run(trade_date, stage_id, market, _v4_global(_v4_scope, 'str')(existing.get("run_id")))
            for field in ("owner", "status", "run_id", "artifact_sha256", "manifest_sha256", "receipt_sha256"):
                if existing.get(field) != verified.get(field):
                    raise _v4_global(_v4_scope, 'RawStoreError')(f"latest pointer {field} mismatch")
            return {"ok": True, "already_exists": True, **verified}
        run_dir = _v4_global(_v4_scope, '_safe_relative')(self.root, prefix)
        if run_dir.exists():
            raise _v4_global(_v4_scope, 'RawStoreError')("immutable run path already exists without latest pointer")
        run_dir.mkdir(parents=True, exist_ok=False)
        artifact_path = _v4_global(_v4_scope, '_safe_relative')(self.root, artifact_relative)
        _v4_global(_v4_scope, '_atomic_write_csv')(
            artifact_path,
            [_v4_global(_v4_scope, '_artifact_row')(trade_date, row) for row in validated],
        )
        artifact_sha = _v4_global(_v4_scope, '_sha_file')(artifact_path)
        manifest = {
            "schema_version": _v4_global(_v4_scope, 'RAW_MANIFEST_SCHEMA_VERSION'),
            "owner": "stage_center",
            "trade_date": trade_date,
            "stage_id": stage_id,
            "market": market,
            "role": role,
            "run_id": run_id,
            "status": status,
            "source_id": source_id,
            "source_status": normalized_source_status,
            "artifact_relative": artifact_relative,
            "artifact_sha256": artifact_sha,
            "row_count": source_rows,
            "temporal_cutoff_safe": status == "READY",
            "requested_rows": requested,
            "source_rows": source_rows,
            "coverage_ratio": coverage,
            "missing_symbols": missing,
            "source_evidence": evidence,
            "cannot_confirm": cannot,
            "input_sha256": input_sha,
            "calendar": _v4_global(_v4_scope, 'calendar_provenance')(),
            **_v4_global(_v4_scope, 'SAFETY_FLAGS'),
        }
        receipt = {
            "schema_version": _v4_global(_v4_scope, 'RAW_RECEIPT_SCHEMA_VERSION'),
            "owner": "stage_center",
            "trade_date": trade_date,
            "stage_id": stage_id,
            "market": market,
            "role": role,
            "run_id": run_id,
            "status": status,
            "source_id": source_id,
            "source_status": normalized_source_status,
            "artifact_relative": artifact_relative,
            "artifact_sha256": artifact_sha,
            "manifest_sha256": _v4_global(_v4_scope, 'canonical_sha')(manifest),
            "row_count": source_rows,
            "temporal_cutoff_safe": status == "READY",
            "requested_rows": requested,
            "source_rows": source_rows,
            "coverage_ratio": coverage,
            "missing_symbols": missing,
            "source_evidence": evidence,
            "cannot_confirm": cannot,
            "input_sha256": input_sha,
            "idempotency_key": idem_key,
            "window": window,
            "cutoff_at": cutoff_at,
            "calendar": _v4_global(_v4_scope, 'calendar_provenance')(),
            **_v4_global(_v4_scope, 'SAFETY_FLAGS'),
        }
        _v4_global(_v4_scope, '_atomic_write_json')(_v4_global(_v4_scope, '_safe_relative')(self.root, manifest_relative), manifest)
        _v4_global(_v4_scope, '_atomic_write_json')(_v4_global(_v4_scope, '_safe_relative')(self.root, receipt_relative), receipt)
        verified = self._verify_run_paths(
            trade_date=trade_date,
            stage_id=stage_id,
            market=market,
            run_id=run_id,
        )
        entry = {
            "owner": "stage_center",
            "trade_date": trade_date,
            "stage_id": stage_id,
            "market": market,
            "role": role,
            "run_id": run_id,
            "status": status,
            "idempotency_key": idem_key,
            "artifact_relative": artifact_relative,
            "manifest_relative": manifest_relative,
            "receipt_relative": receipt_relative,
            "artifact_sha256": verified["artifact_sha256"],
            "manifest_sha256": verified["manifest_sha256"],
            "receipt_sha256": verified["receipt_sha256"],
            "row_count": source_rows,
            **_v4_global(_v4_scope, 'SAFETY_FLAGS'),
        }
        self._merge_latest(latest, key, entry)
        _v4_global(_v4_scope, '_atomic_write_json')(self.latest_path, latest)
        return {"ok": True, **verified}


def _RawStore_publish_bundle_body(_v4_scope, /, self, *, trade_date, stage_id, status, markets):
    _v4_global(_v4_scope, '_validate_date')(trade_date)
    _v4_global(_v4_scope, '_stage')(stage_id)
    if status not in _v4_global(_v4_scope, 'RAW_STATUSES'):
        raise _v4_global(_v4_scope, 'RawStoreError')(f"unknown bundle status {status!r}")
    expected_markets = _v4_global(_v4_scope, 'set')(_v4_global(_v4_scope, '_expected_bundle_markets')(stage_id, trade_date))
    if _v4_global(_v4_scope, 'set')(markets) != expected_markets:
        raise _v4_global(_v4_scope, 'RawStoreError')("bundle market set mismatch")
    summary_seed = {
        "schema_version": _v4_global(_v4_scope, 'RAW_BUNDLE_SCHEMA_VERSION'),
        "owner": "stage_center",
        "trade_date": trade_date,
        "stage_id": stage_id,
        "status": status,
        "markets": {key: _v4_global(_v4_scope, 'dict')(value) for key, value in _v4_global(_v4_scope, 'sorted')(markets.items())},
        "calendar": _v4_global(_v4_scope, 'calendar_provenance')(),
        **_v4_global(_v4_scope, 'SAFETY_FLAGS'),
    }
    bundle_id = f"{trade_date}-{stage_id.lower()}-{_v4_global(_v4_scope, 'canonical_sha')(summary_seed)[:16]}"
    receipt_relative = f"bundle_runs/{trade_date}/{stage_id}/{bundle_id}/receipt.json"
    key = f"{trade_date}/{stage_id}"
    receipt = {**summary_seed, "bundle_id": bundle_id, "receipt_relative": receipt_relative}
    with self._lock():
        latest = self._load_bundle_latest()
        existing = latest["entries"].get(key)
        if _v4_global(_v4_scope, 'isinstance')(existing, _v4_global(_v4_scope, 'Mapping')):
            if existing.get("bundle_id") != bundle_id:
                raise _v4_global(_v4_scope, 'RawStoreError')(f"bundle slot conflict: {key}")
            verified = self._verify_bundle(trade_date, stage_id, bundle_id)
            if existing.get("receipt_sha256") != verified["receipt_sha256"]:
                raise _v4_global(_v4_scope, 'RawStoreError')("bundle latest SHA mismatch")
            return {
                "ok": True,
                "already_exists": True,
                "status": status,
                "bundle_id": bundle_id,
                "receipt_relative": receipt_relative,
                "receipt_sha256": verified["receipt_sha256"],
                "markets": {key: _v4_global(_v4_scope, 'dict')(value) for key, value in markets.items()},
                **_v4_global(_v4_scope, 'SAFETY_FLAGS'),
            }
        receipt_path = _v4_global(_v4_scope, '_safe_relative')(self.root, receipt_relative)
        if receipt_path.exists():
            raise _v4_global(_v4_scope, 'RawStoreError')("immutable bundle path already exists without latest pointer")
        _v4_global(_v4_scope, '_atomic_write_json')(receipt_path, receipt)
        verified = self._verify_bundle(trade_date, stage_id, bundle_id)
        entries = _v4_global(_v4_scope, 'dict')(latest.get("entries", {}))
        entries[key] = {
            "owner": "stage_center",
            "trade_date": trade_date,
            "stage_id": stage_id,
            "bundle_id": bundle_id,
            "status": status,
            "receipt_relative": receipt_relative,
            "receipt_sha256": verified["receipt_sha256"],
            **_v4_global(_v4_scope, 'SAFETY_FLAGS'),
        }
        latest["entries"] = entries
        _v4_global(_v4_scope, '_atomic_write_json')(self.root / "bundle_latest.json", latest)
        return {
            "ok": status in {"READY", "PARTIAL_WITH_ROWS", "READY_EMPTY"},
            "status": status,
            "bundle_id": bundle_id,
            "receipt_relative": receipt_relative,
            "receipt_sha256": verified["receipt_sha256"],
            "markets": {key: _v4_global(_v4_scope, 'dict')(value) for key, value in markets.items()},
            **_v4_global(_v4_scope, 'SAFETY_FLAGS'),
        }


def _publish_raw_artifact_body(
    _v4_scope, /, root, *, trade_date, stage_id, market, source_id,
    source_status, rows, cannot_confirm, source_evidence, requested_rows,
    missing_symbols, window, cutoff_at, research_observation_contract=None,
):
    return _v4_global(_v4_scope, 'RawStore')(root).publish(
        trade_date=trade_date,
        stage_id=stage_id,
        market=market,
        source_id=source_id,
        source_status=source_status,
        rows=rows,
        cannot_confirm=cannot_confirm,
        source_evidence=source_evidence,
        requested_rows=requested_rows,
        missing_symbols=missing_symbols,
        window=window,
        cutoff_at=cutoff_at,
        research_observation_contract=research_observation_contract,
    )
