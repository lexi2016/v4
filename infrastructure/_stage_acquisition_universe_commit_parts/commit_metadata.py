"""infrastructure.stage_acquisition_universe_commit: commit_metadata (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __manifest_body(_v4_scope, /, artifact, identity, date, run, artifact_raw, artifact_canonical, artifact_size):
    return {
        "schema_version": _v4_global(_v4_scope, 'STRICT_MANIFEST_SCHEMA'),
        "role": _v4_global(_v4_scope, 'STRICT_ROLE'),
        "trade_date": date,
        "run_id": run,
        "status": artifact["status"],
        "row_count": artifact["row_count"],
        "codes_sha256": artifact["codes_sha256"],
        "source_pool_provenance_sha256": artifact["source_pool_provenance_sha256"],
        "artifact_relative": _v4_global(_v4_scope, '_paths')(date, run)["artifact"],
        "artifact_bytes_sha256": artifact_raw,
        "artifact_canonical_sha256": artifact_canonical,
        "artifact_size_bytes": artifact_size,
        "digest_mode": _v4_global(_v4_scope, 'DIGEST_MODE'),
        **_v4_global(_v4_scope, '_identity_fields')(identity),
        **{name: False for name in _v4_global(_v4_scope, '_FLAGS')},
    }


def __receipt_body(_v4_scope, /, artifact, manifest, identity, date, run, artifact_raw, artifact_canonical, manifest_raw, manifest_canonical, manifest_size):
    paths = _v4_global(_v4_scope, '_paths')(date, run)
    return {
        "schema_version": _v4_global(_v4_scope, 'STRICT_RECEIPT_SCHEMA'),
        "role": _v4_global(_v4_scope, 'STRICT_ROLE'),
        "trade_date": date,
        "run_id": run,
        "status": artifact["status"],
        "row_count": artifact["row_count"],
        "codes_sha256": artifact["codes_sha256"],
        "source_pool_provenance_sha256": artifact["source_pool_provenance_sha256"],
        "artifact_relative": paths["artifact"],
        "manifest_relative": paths["manifest"],
        "artifact_bytes_sha256": artifact_raw,
        "artifact_canonical_sha256": artifact_canonical,
        "manifest_bytes_sha256": manifest_raw,
        "manifest_canonical_sha256": manifest_canonical,
        "manifest_size_bytes": manifest_size,
        "digest_mode": _v4_global(_v4_scope, 'DIGEST_MODE'),
        **_v4_global(_v4_scope, '_identity_fields')(identity),
        **{name: False for name in _v4_global(_v4_scope, '_FLAGS')},
    }


def __commit_preimage_body(_v4_scope, /, artifact, manifest, receipt, identity, date, run, hashes, *, predecessor, supersession):
    paths = _v4_global(_v4_scope, '_paths')(date, run)
    return {
        "schema_version": _v4_global(_v4_scope, 'STRICT_COMMIT_SCHEMA'),
        "role": _v4_global(_v4_scope, 'STRICT_ROLE'),
        "trade_date": date,
        "run_id": run,
        "status": _v4_global(_v4_scope, 'COMMIT_STATUS'),
        "artifact_relative": paths["artifact"],
        "manifest_relative": paths["manifest"],
        "receipt_relative": paths["receipt"],
        "current_relative": paths["current"],
        "artifact_bytes_sha256": hashes["artifact_bytes_sha256"],
        "artifact_canonical_sha256": hashes["artifact_canonical_sha256"],
        "manifest_bytes_sha256": hashes["manifest_bytes_sha256"],
        "manifest_canonical_sha256": hashes["manifest_canonical_sha256"],
        "receipt_bytes_sha256": hashes["receipt_bytes_sha256"],
        "receipt_canonical_sha256": hashes["receipt_canonical_sha256"],
        "predecessor": _v4_global(_v4_scope, 'dict')(predecessor) if predecessor is not None else None,
        "supersession": _v4_global(_v4_scope, 'dict')(supersession) if supersession is not None else None,
        "digest_mode": _v4_global(_v4_scope, 'DIGEST_MODE'),
        **_v4_global(_v4_scope, '_identity_fields')(identity),
        **{name: False for name in _v4_global(_v4_scope, '_FLAGS')},
    }


def __current_body(_v4_scope, /, artifact, identity, date, run, hashes, commit_id, marker_raw, marker_canonical, marker_size, *, predecessor):
    paths = _v4_global(_v4_scope, '_paths')(date, run)
    return {
        "schema_version": _v4_global(_v4_scope, 'STRICT_CURRENT_SCHEMA'),
        "role": _v4_global(_v4_scope, 'STRICT_ROLE'),
        "trade_date": date,
        "run_id": run,
        "status": artifact["status"],
        "row_count": artifact["row_count"],
        "codes_sha256": artifact["codes_sha256"],
        "source_pool_provenance_sha256": artifact["source_pool_provenance_sha256"],
        "artifact_relative": paths["artifact"],
        "manifest_relative": paths["manifest"],
        "receipt_relative": paths["receipt"],
        "commit_marker_relative": paths["commit"],
        "artifact_bytes_sha256": hashes["artifact_bytes_sha256"],
        "artifact_canonical_sha256": hashes["artifact_canonical_sha256"],
        "manifest_bytes_sha256": hashes["manifest_bytes_sha256"],
        "manifest_canonical_sha256": hashes["manifest_canonical_sha256"],
        "receipt_bytes_sha256": hashes["receipt_bytes_sha256"],
        "receipt_canonical_sha256": hashes["receipt_canonical_sha256"],
        "commit_id": commit_id,
        "commit_marker_bytes_sha256": marker_raw,
        "commit_marker_canonical_sha256": marker_canonical,
        "commit_marker_size_bytes": marker_size,
        "previous_commit_id": (
            predecessor.get("commit_id") if predecessor is not None else None
        ),
        "previous_current_bytes_sha256": (
            predecessor.get("current_bytes_sha256") if predecessor is not None else None
        ),
        "predecessor": _v4_global(_v4_scope, 'dict')(predecessor) if predecessor is not None else None,
        "digest_mode": _v4_global(_v4_scope, 'DIGEST_MODE'),
        **_v4_global(_v4_scope, '_identity_fields')(identity),
        **{name: False for name in _v4_global(_v4_scope, '_FLAGS')},
    }
