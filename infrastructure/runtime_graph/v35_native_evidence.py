"""V3.5-native artifact-chain helpers kept outside the generic graph collector."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any


V35_ARTIFACT_SOURCE_KINDS = frozenset({"v35_artifact", "stage_latest"})
V35_EXECUTION_SOURCE_KINDS = frozenset({"v35_receipt", "stage_latest"})
_SAFETY_FLAGS = ("production_allowed", "buy_gate_updated", "orders_sent")
_NODE_ACTION_STATUSES = frozenset({"SUCCESS", "ACTION_RAN_WITH_CANNOT_CONFIRM", "FAIL"})


def _collector_module() -> Any:
    # Delayed import avoids a module cycle: collectors owns the generic path,
    # JSON and reparse primitives while this module owns only V3.5 semantics.
    from . import collectors

    return collectors


def canonical_sha(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _projection_payload(source: Mapping[str, Any], payload: Mapping[str, Any] | None, *, node_id: str) -> Mapping[str, Any] | None:
    if payload is None:
        return None
    projection = source.get("projection", "root")
    if projection == "root":
        return payload
    if projection == "model_review":
        value = payload.get("model_review")
        return value if isinstance(value, Mapping) else None
    if projection == "close_chain_node":
        close_chain = payload.get("close_chain")
        nodes = close_chain.get("nodes") if isinstance(close_chain, Mapping) else None
        if not isinstance(nodes, list):
            return None
        for row in nodes:
            if isinstance(row, Mapping) and row.get("task_id") == node_id:
                projected = dict(row)
                evidence_rows = projected.get("evidence")
                if isinstance(evidence_rows, list) and evidence_rows and isinstance(evidence_rows[0], Mapping) and "row_count" in evidence_rows[0]:
                    projected["row_count"] = evidence_rows[0]["row_count"]
                for name in _SAFETY_FLAGS:
                    if name not in projected and name in payload:
                        projected[name] = payload[name]
                return projected
        return None
    return None


def source_semantic(source: Mapping[str, Any], payload: Mapping[str, Any] | None, *, node_id: str) -> dict[str, Any] | None:
    collector = _collector_module()
    return collector._semantic_source(source, _projection_payload(source, payload, node_id=node_id))


def augment_binding_dates(semantic: dict[str, Any] | None, *, business_date: str, target_date: str | None) -> dict[str, Any] | None:
    if semantic is None:
        return None
    if semantic.get("semantic_alias") in {"a_selector_v35", "hk_d1_v35"}:
        fields = semantic.get("semantic_fields")
        if isinstance(fields, dict):
            fields.setdefault("signal_date", business_date)
            fields.setdefault("target_date", target_date or business_date)
    return semantic


def verify_integrity(
    *,
    source: Mapping[str, Any],
    artifact: Mapping[str, Any],
    artifact_path: Path,
    node_id: str,
    business_date: str,
    target_date: str | None,
    roots: Mapping[str, Path],
    read_text: Callable[[Path], str],
    path_exists: Callable[[Path], bool],
    path_lstat: Callable[[Path], object | None],
) -> tuple[bool, dict[str, Any], Mapping[str, Any] | None]:
    collector = _collector_module()
    details: dict[str, Any] = {"path": str(artifact_path)}
    expected_schema = source.get("expected_schema")
    if isinstance(expected_schema, str) and artifact.get("schema_version") != expected_schema:
        return False, {**details, "reason": "V35_SCHEMA_MISMATCH"}, None
    if any(artifact.get(name) is True for name in _SAFETY_FLAGS):
        return False, {**details, "reason": "V35_SAFETY_MISMATCH"}, None
    if source.get("artifact_role") == "node_receipt":
        date_values = [artifact.get(name) for name in ("business_date", "trade_date", "date") if artifact.get(name) is not None]
        if artifact.get("node_id") != node_id:
            return False, {**details, "reason": "V35_RECEIPT_IDENTITY_MISMATCH"}, artifact
        if not date_values or any(str(value) != business_date for value in date_values):
            return False, {**details, "reason": "V35_RECEIPT_DATE_MISMATCH"}, artifact
        details.update({"artifact_sha256": canonical_sha(artifact), "receipt_path": str(artifact_path), "artifact_role": "node_receipt"})
        return True, details, artifact
    for envelope in (artifact.get("safety"), artifact.get("close_chain"), artifact.get("model_review")):
        if isinstance(envelope, Mapping):
            safety = envelope.get("safety") if isinstance(envelope.get("safety"), Mapping) else envelope
            if any(safety.get(name) is True for name in _SAFETY_FLAGS):
                return False, {**details, "reason": "V35_SAFETY_MISMATCH"}, None
    role = str(source.get("date_role") or "business_date")
    expected_date = target_date if role == "target_date" else business_date
    if role == "target_date":
        target_values = [artifact.get(name) for name in ("trade_date", "target_date") if artifact.get(name) is not None]
        business_values = [artifact.get("signal_date")] if artifact.get("signal_date") is not None else []
        if any(str(value) != expected_date for value in target_values) or any(str(value) != business_date for value in business_values):
            return False, {**details, "reason": "V35_DATE_MISMATCH"}, None
    else:
        date_values = [artifact.get(name) for name in ("trade_date", "business_date", "review_date") if artifact.get(name) is not None]
        if any(str(value) != business_date for value in date_values):
            return False, {**details, "reason": "V35_DATE_MISMATCH"}, None
    artifact_sha = canonical_sha(artifact)
    receipt_path_value = source.get("receipt_path")
    if not isinstance(receipt_path_value, str):
        return False, {**details, "reason": "V35_RECEIPT_UNDECLARED"}, None
    receipt_path = collector._resolve_path(receipt_path_value, business_date, roots, target_date=target_date)
    if receipt_path is None or not collector._reparse_safe(receipt_path, roots, path_lstat):
        return False, {**details, "reason": "V35_RECEIPT_PATH_UNSAFE"}, None
    receipt, outcome = collector._read_mapping(receipt_path, read_text, path_exists)
    if receipt is None:
        return False, {**details, "reason": f"V35_RECEIPT_{outcome}"}, None
    for identity in ("pool_id", "source_role", "source_run_id"):
        if receipt.get(identity) is not None and artifact.get(identity) is not None and receipt.get(identity) != artifact.get(identity):
            return False, {**details, "reason": "V35_RECEIPT_IDENTITY_MISMATCH"}, receipt
    # Close-review node receipts carry a declared artifact *path* rather than
    # an artifact SHA.  The actual SHA chain is proved by the native source
    # manifest below; require the action receipt to point at this exact file.
    if source.get("artifact_role") == "bilibili_source":
        artifact_values = receipt.get("artifacts")
        if not isinstance(artifact_values, Mapping) or str(artifact_path) not in {str(value) for value in artifact_values.values()}:
            return False, {**details, "reason": "V35_NODE_RECEIPT_ARTIFACT_UNDECLARED"}, receipt
    elif receipt.get("artifact_sha256") not in (None, artifact_sha) and receipt.get("payload_sha256") != artifact_sha:
        return False, {**details, "reason": "V35_RECEIPT_SHA_MISMATCH"}, receipt
    if source.get("artifact_role") != "bilibili_source" and (
        receipt.get("artifact_sha256") not in (None, artifact_sha)
        or receipt.get("payload_sha256") not in (None, artifact_sha)
    ):
        return False, {**details, "reason": "V35_RECEIPT_SHA_MISMATCH"}, receipt
    receipt_dates = [receipt.get(name) for name in ("trade_date", "business_date", "target_date") if receipt.get(name) is not None]
    if any(str(value) != expected_date for value in receipt_dates):
        return False, {**details, "reason": "V35_RECEIPT_DATE_MISMATCH"}, receipt
    manifest_path_value = source.get("manifest_path")
    manifest_key = source.get("manifest_key")
    if not isinstance(manifest_path_value, str) or not isinstance(manifest_key, str):
        return False, {**details, "reason": "V35_MANIFEST_UNDECLARED"}, receipt
    manifest_key = str(manifest_key).replace("{date}", business_date).replace("{target_date}", target_date or business_date)
    manifest_path = collector._resolve_path(manifest_path_value, business_date, roots, target_date=target_date)
    if manifest_path is None or not collector._reparse_safe(manifest_path, roots, path_lstat):
        return False, {**details, "reason": "V35_MANIFEST_PATH_UNSAFE"}, receipt
    manifest, outcome = collector._read_mapping(manifest_path, read_text, path_exists)
    manifest_value = manifest.get(manifest_key)
    if manifest_value is None and isinstance(manifest.get("files"), Mapping):
        manifest_value = manifest["files"].get(manifest_key)
    if manifest_value != artifact_sha:
        return False, {**details, "reason": "V35_MANIFEST_SHA_MISMATCH"}, receipt
    details.update({"receipt_path": str(receipt_path), "manifest_path": str(manifest_path), "artifact_sha256": artifact_sha})
    return True, details, receipt


def read_stage_latest(
    *,
    source: Mapping[str, Any],
    pointer_path: Path,
    business_date: str,
    target_date: str | None,
    roots: Mapping[str, Path],
    read_text: Callable[[Path], str],
    path_exists: Callable[[Path], bool],
    path_lstat: Callable[[Path], object | None],
) -> tuple[bool, dict[str, Any], Mapping[str, Any] | None, Mapping[str, Any] | None]:
    collector = _collector_module()
    pointer, outcome = collector._read_mapping(pointer_path, read_text, path_exists)
    details: dict[str, Any] = {"path": str(pointer_path)}
    if pointer is None:
        return False, {**details, "reason": f"STAGE_POINTER_{outcome}"}, None, None
    if pointer.get("schema_version") != "v3_5.stage_latest.v1" or pointer.get("trade_date") != business_date or pointer.get("stage_id") != source.get("stage_id"):
        return False, {**details, "reason": "STAGE_POINTER_IDENTITY_INVALID"}, None, None
    paths = (pointer.get("artifact_path"), pointer.get("manifest_path"), pointer.get("receipt_path"))
    if not all(isinstance(value, str) and value for value in paths):
        return False, {**details, "reason": "STAGE_POINTER_PATH_INVALID"}, None, None
    artifact_path, manifest_path, receipt_path = (
        collector._resolve_path("{data_root}/" + value, business_date, roots, target_date=target_date) for value in paths
    )
    resolved = (artifact_path, manifest_path, receipt_path)
    if any(path is None or not collector._reparse_safe(path, roots, path_lstat) for path in resolved):
        return False, {**details, "reason": "STAGE_POINTER_PATH_UNSAFE"}, None, None
    artifact, artifact_outcome = collector._read_mapping(artifact_path, read_text, path_exists)
    manifest, manifest_outcome = collector._read_mapping(manifest_path, read_text, path_exists)
    receipt, receipt_outcome = collector._read_mapping(receipt_path, read_text, path_exists)
    if artifact is None or manifest is None or receipt is None:
        return False, {**details, "reason": f"STAGE_CHAIN_{artifact_outcome}_{manifest_outcome}_{receipt_outcome}"}, receipt, None
    artifact_sha, manifest_sha, receipt_sha = canonical_sha(artifact), canonical_sha(manifest), canonical_sha(receipt)
    if pointer.get("artifact_sha256") != artifact_sha or pointer.get("manifest_sha256") != manifest_sha or pointer.get("receipt_sha256") != receipt_sha:
        return False, {**details, "reason": "STAGE_CHAIN_SHA_MISMATCH"}, receipt, artifact
    if manifest.get("artifact_sha256") != artifact_sha or receipt.get("artifact_sha256") != artifact_sha or receipt.get("manifest_sha256") != manifest_sha:
        return False, {**details, "reason": "STAGE_CHAIN_LINK_MISMATCH"}, receipt, artifact
    receipt_trade_date, receipt_stage_id = receipt.get("trade_date"), receipt.get("stage_id")
    if manifest.get("trade_date") != business_date or (receipt_trade_date is not None and receipt_trade_date != business_date) or manifest.get("stage_id") != source.get("stage_id") or (receipt_stage_id is not None and receipt_stage_id != source.get("stage_id")):
        return False, {**details, "reason": "STAGE_CHAIN_DATE_MISMATCH"}, receipt, artifact
    if any(artifact.get(name) is True or manifest.get(name) is True for name in _SAFETY_FLAGS):
        return False, {**details, "reason": "STAGE_CHAIN_SAFETY_MISMATCH"}, receipt, artifact
    if manifest.get("status") != "COMPLETE" or receipt.get("status") != "COMPLETE":
        return False, {**details, "reason": "STAGE_CHAIN_STATUS_INVALID"}, receipt, artifact
    return True, {**details, "artifact_sha256": artifact_sha, "manifest_sha256": manifest_sha, "receipt_sha256": receipt_sha}, receipt, artifact


def artifact_record(
    *,
    source: Mapping[str, Any],
    path: Path,
    node_id: str,
    business_date: str,
    target_date: str | None,
    roots: Mapping[str, Path],
    read_text: Callable[[Path], str],
    path_exists: Callable[[Path], bool],
    path_lstat: Callable[[Path], object | None],
) -> tuple[bool, dict[str, Any] | None]:
    collector = _collector_module()
    if source.get("kind") == "v35_artifact":
        payload, _ = collector._read_mapping(path, read_text, path_exists)
        if payload is None:
            return False, None
        valid, _, _ = verify_integrity(
            source=source,
            artifact=payload,
            artifact_path=path,
            node_id=node_id,
            business_date=business_date,
            target_date=target_date,
            roots=roots,
            read_text=read_text,
            path_exists=path_exists,
            path_lstat=path_lstat,
        )
        if not valid:
            return False, None
        return True, augment_binding_dates(source_semantic(source, payload, node_id=node_id), business_date=business_date, target_date=target_date)
    valid, _, _, artifact = read_stage_latest(
        source=source,
        pointer_path=path,
        business_date=business_date,
        target_date=target_date,
        roots=roots,
        read_text=read_text,
        path_exists=path_exists,
        path_lstat=path_lstat,
    )
    if not valid or artifact is None:
        return False, None
    return True, augment_binding_dates(source_semantic(source, artifact, node_id=node_id), business_date=business_date, target_date=target_date)


def execution_record(
    *,
    source: Mapping[str, Any],
    path: Path,
    receipt: Mapping[str, Any],
    business_date: str,
    target_date: str | None,
    roots: Mapping[str, Path],
    read_text: Callable[[Path], str],
    path_exists: Callable[[Path], bool],
    path_lstat: Callable[[Path], object | None],
) -> dict[str, Any]:
    collector = _collector_module()
    if source.get("receipt_role") == "node_action":
        details: dict[str, Any] = {"path": str(path), "receipt": receipt}
        expected_node_id = path.stem
        if receipt.get("node_id") != expected_node_id:
            return {**details, "reason": "RECEIPT_IDENTITY_INVALID"}
        dates = [receipt[field] for field in ("business_date", "trade_date", "date") if field in receipt]
        if not dates or any(str(value) != business_date for value in dates):
            return {**details, "reason": "V35_RECEIPT_DATE_MISMATCH"}
        if any(receipt.get(name) is True for name in _SAFETY_FLAGS):
            return {**details, "reason": "V35_RECEIPT_SAFETY_MISMATCH"}
        status = str(receipt.get("status") or "").upper()
        if status not in _NODE_ACTION_STATUSES:
            return {**details, "reason": "RECEIPT_STATUS_UNRECOGNIZED"}
        if status == "FAIL":
            return {**details, "reason": "RECEIPT_FAILED", "state": "FAIL"}
        if status == "SUCCESS":
            return {**details, "reason": "RECEIPT_PASS", "state": "PASS"}
        return {**details, "reason": "RECEIPT_CANNOT_CONFIRM"}
    if source.get("kind") == "stage_latest":
        valid, stage_details, stage_receipt, _ = read_stage_latest(
            source=source,
            pointer_path=path,
            business_date=business_date,
            target_date=target_date,
            roots=roots,
            read_text=read_text,
            path_exists=path_exists,
            path_lstat=path_lstat,
        )
        return {"path": str(path), "receipt": stage_receipt or {}, "reason": "RECEIPT_PASS" if valid else str(stage_details.get("reason") or "V35_STAGE_CHAIN_INVALID"), **({"state": "PASS", "chain": stage_details} if valid else {})}
    expected_date = target_date if source.get("date_role") == "target_date" else business_date
    dates = [receipt[field] for field in ("trade_date", "business_date", "target_date") if field in receipt]
    if not dates or any(str(value) != expected_date for value in dates):
        return {"path": str(path), "receipt": receipt, "reason": "V35_RECEIPT_DATE_MISMATCH"}
    artifact_path_value, manifest_path_value, manifest_key = source.get("artifact_path"), source.get("manifest_path"), source.get("manifest_key")
    if not all(isinstance(value, str) and value for value in (artifact_path_value, manifest_path_value, manifest_key)):
        return {"path": str(path), "receipt": receipt, "reason": "V35_RECEIPT_UNDECLARED"}
    manifest_key = str(manifest_key).replace("{date}", business_date).replace("{target_date}", target_date or business_date)
    artifact_path = collector._resolve_path(artifact_path_value, business_date, roots, target_date=target_date)
    manifest_path = collector._resolve_path(manifest_path_value, business_date, roots, target_date=target_date)
    if artifact_path is None or manifest_path is None or not collector._reparse_safe(artifact_path, roots, path_lstat) or not collector._reparse_safe(manifest_path, roots, path_lstat):
        return {"path": str(path), "receipt": receipt, "reason": "V35_RECEIPT_PATH_UNSAFE"}
    artifact, artifact_outcome = collector._read_mapping(artifact_path, read_text, path_exists)
    manifest, manifest_outcome = collector._read_mapping(manifest_path, read_text, path_exists)
    if artifact is None or manifest is None:
        return {"path": str(path), "receipt": receipt, "reason": f"V35_CHAIN_{artifact_outcome}_{manifest_outcome}"}
    if any(receipt.get(identity) is not None and artifact.get(identity) is not None and receipt.get(identity) != artifact.get(identity) for identity in ("pool_id", "source_role", "source_run_id")):
        return {"path": str(path), "receipt": receipt, "reason": "V35_RECEIPT_IDENTITY_MISMATCH"}
    artifact_sha = canonical_sha(artifact)
    expected_sha = receipt.get("artifact_sha256") or receipt.get("payload_sha256") or receipt.get("source_sha256")
    if expected_sha != artifact_sha or manifest.get(manifest_key) != artifact_sha:
        return {"path": str(path), "receipt": receipt, "reason": "V35_RECEIPT_SHA_MISMATCH"}
    if any(artifact.get(name) is True for name in _SAFETY_FLAGS):
        return {"path": str(path), "receipt": receipt, "reason": "V35_RECEIPT_SAFETY_MISMATCH"}
    return {"path": str(path), "receipt": receipt, "reason": "RECEIPT_PASS", "state": "PASS"}
