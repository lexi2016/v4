"""stage_center.selection: store_verification (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _SelectionStore__verify_run_body(_v4_scope, /, self, trade_date, stage_id, market, run_id):
    role = self._role(stage_id, market)
    if not _v4_global(_v4_scope, '_ROLE_RE').fullmatch(run_id):
        raise _v4_global(_v4_scope, 'SelectionError')("selection run_id is unsafe")
    prefix = f"selection_runs/{trade_date}/{role}/{run_id}"
    run_dir = _v4_global(_v4_scope, '_safe_relative')(self.root, prefix)
    artifact_path = _v4_global(_v4_scope, '_safe_relative')(self.root, f"{prefix}/artifact.csv")
    manifest_path = _v4_global(_v4_scope, '_safe_relative')(self.root, f"{prefix}/manifest.json")
    receipt_path = _v4_global(_v4_scope, '_safe_relative')(self.root, f"{prefix}/receipt.json")
    if not run_dir.is_dir() or not _v4_global(_v4_scope, 'all')(path.is_file() for path in (artifact_path, manifest_path, receipt_path)):
        raise _v4_global(_v4_scope, 'SelectionError')("selection run trio incomplete")
    manifest = _v4_global(_v4_scope, '_read_json')(manifest_path)
    receipt = _v4_global(_v4_scope, '_read_json')(receipt_path)
    if manifest.get("schema_version") != _v4_global(_v4_scope, 'SELECTION_MANIFEST_SCHEMA_VERSION') or receipt.get("schema_version") != _v4_global(_v4_scope, 'SELECTION_RECEIPT_SCHEMA_VERSION'):
        raise _v4_global(_v4_scope, 'SelectionError')("selection manifest/receipt schema mismatch")
    for payload, label in ((manifest, "manifest"), (receipt, "receipt")):
        if payload.get("owner") != "stage_center" or payload.get("trade_date") != trade_date or payload.get("stage_id") != stage_id or payload.get("market") != market or payload.get("run_id") != run_id:
            raise _v4_global(_v4_scope, 'SelectionError')(f"selection {label} identity mismatch")
        if _v4_global(_v4_scope, 'any')(payload.get(flag) is not False for flag in _v4_global(_v4_scope, 'SAFETY_FLAGS')):
            raise _v4_global(_v4_scope, 'SelectionError')(f"selection {label} safety flag must be false")
    expected_artifact = f"{prefix}/artifact.csv"
    if manifest.get("artifact_relative") != expected_artifact or receipt.get("artifact_relative") != expected_artifact:
        raise _v4_global(_v4_scope, 'SelectionError')("selection artifact path mismatch")
    actual_artifact_sha = _v4_global(_v4_scope, '_sha_file')(artifact_path)
    if manifest.get("artifact_sha256") != actual_artifact_sha or receipt.get("artifact_sha256") != actual_artifact_sha:
        raise _v4_global(_v4_scope, 'SelectionError')("selection artifact SHA mismatch")
    with artifact_path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = _v4_global(_v4_scope, 'csv').DictReader(stream)
        artifact_fields = _v4_global(_v4_scope, 'tuple')(reader.fieldnames or ())
        if artifact_fields not in (_v4_global(_v4_scope, 'SELECTION_ARTIFACT_FIELDS_V1'), _v4_global(_v4_scope, 'SELECTION_ARTIFACT_FIELDS_V2')):
            raise _v4_global(_v4_scope, 'SelectionError')("selection artifact fields mismatch")
        artifact_rows = _v4_global(_v4_scope, '_decode_artifact_rows')(_v4_global(_v4_scope, 'list')(reader), fields=artifact_fields)
    envelope = manifest.get("selection_envelope")
    if not _v4_global(_v4_scope, 'isinstance')(envelope, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'SelectionError')("selection envelope missing")
    envelope_schema = _v4_global(_v4_scope, 'str')(envelope.get("schema_version") or "")
    if envelope_schema not in _v4_global(_v4_scope, 'SELECTION_SCHEMA_VERSIONS'):
        raise _v4_global(_v4_scope, 'SelectionError')("selection envelope schema mismatch")
    expected_projection_fields = _v4_global(_v4_scope, '_artifact_fields_for_schema')(envelope_schema)
    if envelope_schema == _v4_global(_v4_scope, 'SELECTION_SCHEMA_VERSION_V1') and artifact_fields != expected_projection_fields:
        raise _v4_global(_v4_scope, 'SelectionError')("selection artifact/schema version mismatch")
    if envelope_schema == _v4_global(_v4_scope, 'SELECTION_SCHEMA_VERSION') and artifact_fields not in (
        expected_projection_fields,
        _v4_global(_v4_scope, 'SELECTION_ARTIFACT_FIELDS_V2'),
    ):
        raise _v4_global(_v4_scope, 'SelectionError')("selection artifact/schema version mismatch")
    expected_rows = _v4_global(_v4_scope, '_decode_artifact_rows')(
        _v4_global(_v4_scope, '_artifact_rows')(_v4_global(_v4_scope, 'list')(envelope.get("rows") or []), fields=artifact_fields),
        fields=artifact_fields,
    )
    if expected_rows != artifact_rows:
        raise _v4_global(_v4_scope, 'SelectionError')("selection artifact rows mismatch")
    if manifest.get("row_count") != _v4_global(_v4_scope, 'len')(artifact_rows) or receipt.get("row_count") != _v4_global(_v4_scope, 'len')(artifact_rows):
        raise _v4_global(_v4_scope, 'SelectionError')("selection row_count mismatch")
    if receipt.get("manifest_sha256") != _v4_global(_v4_scope, '_canonical_sha')(manifest):
        raise _v4_global(_v4_scope, 'SelectionError')("selection manifest SHA mismatch")
    manifest_algorithm = manifest.get("algorithm_sha256")
    receipt_algorithm = receipt.get("algorithm_sha256")
    if manifest_algorithm not in _v4_global(_v4_scope, 'ALGORITHM_SHA_ALLOWLIST') or receipt_algorithm != manifest_algorithm:
        raise _v4_global(_v4_scope, 'SelectionError')("selection algorithm SHA mismatch")
    if envelope.get("algorithm_sha256") != manifest_algorithm:
        raise _v4_global(_v4_scope, 'SelectionError')("selection envelope algorithm SHA mismatch")
    if manifest.get("raw_artifact_sha256") != envelope.get("raw_artifact_sha256") or receipt.get("raw_artifact_sha256") != envelope.get("raw_artifact_sha256"):
        raise _v4_global(_v4_scope, 'SelectionError')("selection raw artifact SHA mismatch")
    expected_artifact_id, expected_run_id = _v4_global(_v4_scope, '_selection_identity_ids')(
        trade_date,
        stage_id,
        market,
        _v4_global(_v4_scope, 'str')(envelope.get("raw_artifact_sha256") or ""),
        manifest_algorithm,
        _v4_global(_v4_scope, 'list')(envelope.get("rows") or []),
    )
    if envelope.get("artifact_id") != expected_artifact_id or envelope.get("run_id") != expected_run_id or run_id != expected_run_id:
        raise _v4_global(_v4_scope, 'SelectionError')("selection identity mismatch")
    if envelope.get("selection_status") not in _v4_global(_v4_scope, 'SELECTION_STATUSES'):
        raise _v4_global(_v4_scope, 'SelectionError')("selection status mismatch")
    return {
        "envelope": _v4_global(_v4_scope, 'dict')(envelope),
        "owner": "stage_center",
        "trade_date": trade_date,
        "stage_id": stage_id,
        "market": market,
        "role": role,
        "run_id": run_id,
        "artifact_relative": expected_artifact,
        "artifact_sha256": actual_artifact_sha,
        "manifest_sha256": _v4_global(_v4_scope, '_canonical_sha')(manifest),
        "receipt_sha256": _v4_global(_v4_scope, '_canonical_sha')(receipt),
        "idempotency_key": receipt.get("idempotency_key"),
    }
