"""stage_center.selection: store_publication (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _SelectionStore_publish_body(_v4_scope, /, self, envelope, *, market):
    data = _v4_global(_v4_scope, 'dict')(envelope)
    required = {"trade_date", "stage_id", "raw_artifact_sha256", "algorithm_sha256", "rows", "selection_status"}
    if not required.issubset(data):
        raise _v4_global(_v4_scope, 'SelectionError')("selection envelope fields missing")
    trade_date = _v4_global(_v4_scope, '_validate_date')(_v4_global(_v4_scope, 'str')(data["trade_date"]))
    stage_id = _v4_global(_v4_scope, 'str')(data["stage_id"])
    _v4_global(_v4_scope, '_validate_market')(stage_id, market)
    if data.get("market") != market:
        raise _v4_global(_v4_scope, 'SelectionError')("selection envelope market mismatch")
    _v4_global(_v4_scope, '_validate_sha')(_v4_global(_v4_scope, 'str')(data["raw_artifact_sha256"]), "raw_artifact_sha256")
    if data.get("algorithm_id") != _v4_global(_v4_scope, 'SELECTION_ALGORITHM_ID'):
        raise _v4_global(_v4_scope, 'SelectionError')("selection algorithm binding mismatch")
    if _v4_global(_v4_scope, 'any')(data.get(flag) is not False for flag in _v4_global(_v4_scope, 'SAFETY_FLAGS')):
        raise _v4_global(_v4_scope, 'SelectionError')("selection safety flag must be false")
    rows = _v4_global(_v4_scope, 'list')(data.get("rows") or [])
    envelope_schema = _v4_global(_v4_scope, 'str')(data.get("schema_version") or _v4_global(_v4_scope, 'SELECTION_SCHEMA_VERSION'))
    if envelope_schema not in _v4_global(_v4_scope, 'SELECTION_SCHEMA_VERSIONS'):
        raise _v4_global(_v4_scope, 'SelectionError')("selection envelope schema mismatch")
    # New envelopes are explicitly v2, but ``artifact.csv`` stays a
    # fixed v1 projection for the old V3 verifier.  Full card evidence is
    # bound into the manifest/receipt envelope and selection identity.
    artifact_fields = _v4_global(_v4_scope, 'SELECTION_ARTIFACT_FIELDS_V1')
    artifact_rows = _v4_global(_v4_scope, '_artifact_rows')(rows, fields=artifact_fields)
    algorithm_sha = _v4_global(_v4_scope, 'str')(data["algorithm_sha256"])
    if algorithm_sha not in _v4_global(_v4_scope, 'ALGORITHM_SHA_ALLOWLIST'):
        raise _v4_global(_v4_scope, 'SelectionError')("selection algorithm binding mismatch")
    if algorithm_sha in {_v4_global(_v4_scope, 'A_SHARE_LIVE_ALGORITHM_SHA256'), _v4_global(_v4_scope, 'LEGACY_A_SHARE_LIVE_ALGORITHM_SHA256')} and market != "A_SHARE":
        raise _v4_global(_v4_scope, 'SelectionError')("live algorithm is restricted to A_SHARE")
    if algorithm_sha in {_v4_global(_v4_scope, 'A_SHARE_LIVE_ALGORITHM_SHA256'), _v4_global(_v4_scope, 'LEGACY_A_SHARE_LIVE_ALGORITHM_SHA256')} and not _v4_global(_v4_scope, 'any')(
        "formula=windows_v3_live_stage_quality_score" in _v4_global(_v4_scope, 'str')(item)
        for item in data.get("source_evidence") or ()
    ):
        raise _v4_global(_v4_scope, 'SelectionError')("live algorithm evidence missing")
    identity_payload = {
        "identity": self._key(trade_date, stage_id, market),
        "raw_artifact_sha256": data["raw_artifact_sha256"],
        "algorithm_sha256": algorithm_sha,
        "rows": rows,
    }
    authority_hashes = _v4_global(_v4_scope, 'tuple')(
        _v4_global(_v4_scope, 'str')(item)
        for item in data.get("source_evidence") or ()
        if _v4_global(_v4_scope, 'any')(
            _v4_global(_v4_scope, 'str')(item).startswith(prefix)
            for prefix in (
                "a_d1_premarket_pool_sha256=",
                "a_research_panel_receipt_sha256=",
                "a_research_panel_selector_sha256=",
            )
        )
    )
    if authority_hashes:
        identity_payload["authority_source_hashes"] = _v4_global(_v4_scope, 'list')(_v4_global(_v4_scope, 'dict').fromkeys(authority_hashes))
    input_sha = _v4_global(_v4_scope, '_canonical_sha')(identity_payload)
    role = self._role(stage_id, market)
    expected_artifact_id, expected_run_id = _v4_global(_v4_scope, '_selection_identity_ids')(
        trade_date,
        stage_id,
        market,
        _v4_global(_v4_scope, 'str')(data["raw_artifact_sha256"]),
        algorithm_sha,
        rows,
    )
    if data.get("run_id") not in (None, expected_run_id) or data.get("artifact_id") not in (None, expected_artifact_id):
        raise _v4_global(_v4_scope, 'SelectionError')("selection identity mismatch")
    run_id = expected_run_id
    artifact_id = expected_artifact_id
    data["run_id"] = run_id
    data["artifact_id"] = artifact_id
    idem_key = _v4_global(_v4_scope, '_canonical_sha')({"identity": self._key(trade_date, stage_id, market), "raw_artifact_sha256": data["raw_artifact_sha256"], "algorithm_sha256": algorithm_sha, "input_sha256": input_sha})
    data["source_evidence"] = _v4_global(_v4_scope, 'list')(data.get("source_evidence") or [])
    data["cannot_confirm"] = _v4_global(_v4_scope, 'list')(data.get("cannot_confirm") or [])
    prefix = f"selection_runs/{trade_date}/{role}/{run_id}"
    artifact_relative = f"{prefix}/artifact.csv"
    manifest_relative = f"{prefix}/manifest.json"
    receipt_relative = f"{prefix}/receipt.json"
    with self._lock():
        latest = self._latest()
        key = self._key(trade_date, stage_id, market)
        existing = latest["entries"].get(key)
        if _v4_global(_v4_scope, 'isinstance')(existing, _v4_global(_v4_scope, 'Mapping')):
            if existing.get("idempotency_key") != idem_key:
                raise _v4_global(_v4_scope, 'SelectionError')(f"selection slot conflict: {key}")
            verified = self._verify_run(trade_date, stage_id, market, _v4_global(_v4_scope, 'str')(existing.get("run_id")))
            if verified["envelope"] != data:
                raise _v4_global(_v4_scope, 'SelectionError')("selection idempotency payload mismatch")
            return _v4_global(_v4_scope, 'dict')(data)
        run_dir = _v4_global(_v4_scope, '_safe_relative')(self.root, prefix)
        if run_dir.exists():
            raise _v4_global(_v4_scope, 'SelectionError')("immutable selection run path already exists without latest pointer")
        run_dir.mkdir(parents=True, exist_ok=False)
        artifact_path = _v4_global(_v4_scope, '_safe_relative')(self.root, artifact_relative)
        _v4_global(_v4_scope, '_atomic_write_csv')(artifact_path, artifact_rows, fields=artifact_fields)
        artifact_sha = _v4_global(_v4_scope, '_sha_file')(artifact_path)
        manifest = {
            "schema_version": _v4_global(_v4_scope, 'SELECTION_MANIFEST_SCHEMA_VERSION'),
            "owner": "stage_center",
            "trade_date": trade_date,
            "stage_id": stage_id,
            "market": market,
            "role": role,
            "run_id": run_id,
            "artifact_relative": artifact_relative,
            "artifact_sha256": artifact_sha,
            "row_count": _v4_global(_v4_scope, 'len')(rows),
            "selection_status": data["selection_status"],
            "raw_artifact_sha256": data["raw_artifact_sha256"],
            "algorithm_id": _v4_global(_v4_scope, 'SELECTION_ALGORITHM_ID'),
            "algorithm_sha256": algorithm_sha,
            "selection_envelope": data,
            "calendar": _v4_global(_v4_scope, 'calendar_provenance')(),
            **_v4_global(_v4_scope, 'SAFETY_FLAGS'),
        }
        receipt = {
            "schema_version": _v4_global(_v4_scope, 'SELECTION_RECEIPT_SCHEMA_VERSION'),
            "owner": "stage_center",
            "trade_date": trade_date,
            "stage_id": stage_id,
            "market": market,
            "role": role,
            "run_id": run_id,
            "artifact_relative": artifact_relative,
            "artifact_sha256": artifact_sha,
            "manifest_sha256": _v4_global(_v4_scope, '_canonical_sha')(manifest),
            "row_count": _v4_global(_v4_scope, 'len')(rows),
            "selection_status": data["selection_status"],
            "raw_artifact_sha256": data["raw_artifact_sha256"],
            "algorithm_id": _v4_global(_v4_scope, 'SELECTION_ALGORITHM_ID'),
            "algorithm_sha256": algorithm_sha,
            "idempotency_key": idem_key,
            "calendar": _v4_global(_v4_scope, 'calendar_provenance')(),
            **_v4_global(_v4_scope, 'SAFETY_FLAGS'),
        }
        _v4_global(_v4_scope, '_atomic_write_json')(_v4_global(_v4_scope, '_safe_relative')(self.root, manifest_relative), manifest)
        _v4_global(_v4_scope, '_atomic_write_json')(_v4_global(_v4_scope, '_safe_relative')(self.root, receipt_relative), receipt)
        verified = self._verify_run(trade_date, stage_id, market, run_id)
        entries = _v4_global(_v4_scope, 'dict')(latest.get("entries", {}))
        entries[key] = {
            "owner": "stage_center",
            "trade_date": trade_date,
            "stage_id": stage_id,
            "market": market,
            "role": role,
            "run_id": run_id,
            "artifact_relative": artifact_relative,
            "artifact_sha256": artifact_sha,
            "manifest_sha256": verified["manifest_sha256"],
            "receipt_sha256": verified["receipt_sha256"],
            "idempotency_key": idem_key,
            **_v4_global(_v4_scope, 'SAFETY_FLAGS'),
        }
        latest["entries"] = entries
        _v4_global(_v4_scope, '_atomic_write_json')(self.latest_path, latest)
        return _v4_global(_v4_scope, 'dict')(data)
