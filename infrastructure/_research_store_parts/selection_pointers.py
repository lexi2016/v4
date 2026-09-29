"""infrastructure.research_store: selection_pointers (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _ResearchSelectionStore__validate_manifest_body(_v4_scope, /, cls, value):
    if not _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'Mapping')) or _v4_global(_v4_scope, 'set')(value) != {
        "schema_version",
        "namespace",
        "entries",
    }:
        raise _v4_global(_v4_scope, 'ValueError')("invalid selection manifest")
    if value.get("schema_version") != "v3_5.selection_manifest.v1" or value.get("namespace") != cls._SELECTION_ROOT:
        raise _v4_global(_v4_scope, 'ValueError')("invalid selection manifest namespace")
    entries = value.get("entries")
    if not _v4_global(_v4_scope, 'isinstance')(entries, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'ValueError')("invalid selection manifest entries")
    for relative, digest in entries.items():
        if not _v4_global(_v4_scope, 'isinstance')(relative, _v4_global(_v4_scope, 'str')) or not (
            relative.startswith(f"{cls._SELECTION_ROOT}/")
            or relative.startswith(f"{cls._RECEIPT_ROOT}/")
        ):
            raise _v4_global(_v4_scope, 'ValueError')("selection manifest path escapes namespace")
        if not _v4_global(_v4_scope, '_SHA256').fullmatch(_v4_global(_v4_scope, 'str')(digest or "")):
            raise _v4_global(_v4_scope, 'ValueError')("invalid selection manifest SHA")


def _ResearchSelectionStore__receipt_body(_v4_scope, /, cls, payload, artifact_relative, artifact_sha):
    return {
        "schema_version": "v3_5.selection_receipt.v1",
        "contract_id": _v4_global(_v4_scope, 'SELECTION_CONTRACT_ID'),
        "target_trade_date": payload["target_trade_date"],
        "source_date": payload["source_date"],
        "run_id": payload["run_id"],
        "origin": payload["origin"],
        "payload_path": artifact_relative,
        "payload_sha256": artifact_sha,
        "status": payload["status"],
        "counts": _v4_global(_v4_scope, 'dict')(payload["counts"]),
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _ResearchSelectionStore__current_pointer_body(_v4_scope, /, cls, payload, *, artifact_relative, artifact_sha, receipt_relative, receipt_sha, manifest_relative, manifest_sha):
    body = {
        "schema_version": "v3_5.selection_current_pointer.v1",
        "namespace": cls._SELECTION_ROOT,
        "target_trade_date": payload["target_trade_date"],
        "run_id": payload["run_id"],
        "generated_at": payload["generated_at"],
        "artifact_path": artifact_relative,
        "artifact_sha256": artifact_sha,
        "receipt_path": receipt_relative,
        "receipt_sha256": receipt_sha,
        "manifest_path": manifest_relative,
        "manifest_sha256": manifest_sha,
    }
    return {**body, "pointer_semantic_hash": cls._canonical_sha(body)}


def _ResearchSelectionStore__validate_current_body(_v4_scope, /, cls, value, *, target_trade_date):
    fields = {
        "schema_version",
        "namespace",
        "target_trade_date",
        "run_id",
        "generated_at",
        "artifact_path",
        "artifact_sha256",
        "receipt_path",
        "receipt_sha256",
        "manifest_path",
        "manifest_sha256",
        "pointer_semantic_hash",
    }
    if not _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'Mapping')) or _v4_global(_v4_scope, 'set')(value) != fields:
        raise _v4_global(_v4_scope, 'ValueError')("invalid selection current pointer")
    selected = _v4_global(_v4_scope, '_date')(_v4_global(_v4_scope, 'str')(value.get("target_trade_date") or ""))
    if target_trade_date is not None and selected != target_trade_date:
        raise _v4_global(_v4_scope, 'ValueError')("selection current target date mismatch")
    run_id = value.get("run_id")
    if not _v4_global(_v4_scope, 'isinstance')(run_id, _v4_global(_v4_scope, 'str')) or not cls._RUN_ID.fullmatch(run_id):
        raise _v4_global(_v4_scope, 'ValueError')("invalid selection current run_id")
    if value.get("schema_version") != "v3_5.selection_current_pointer.v1" or value.get("namespace") != cls._SELECTION_ROOT:
        raise _v4_global(_v4_scope, 'ValueError')("invalid selection current namespace")
    if value.get("artifact_path") != cls._artifact_relative(selected, run_id) or value.get("receipt_path") != cls._receipt_relative(selected, run_id):
        raise _v4_global(_v4_scope, 'ValueError')("invalid selection current paths")
    if value.get("manifest_path") != cls._run_manifest_relative(selected, run_id):
        raise _v4_global(_v4_scope, 'ValueError')("invalid selection current manifest path")
    for field in ("artifact_sha256", "receipt_sha256", "manifest_sha256"):
        if not _v4_global(_v4_scope, '_SHA256').fullmatch(_v4_global(_v4_scope, 'str')(value.get(field) or "")):
            raise _v4_global(_v4_scope, 'ValueError')("invalid selection current SHA")
    body = {key: item for key, item in value.items() if key != "pointer_semantic_hash"}
    if value.get("pointer_semantic_hash") != cls._canonical_sha(body):
        raise _v4_global(_v4_scope, 'ValueError')("invalid selection current semantic hash")


def _ResearchSelectionStore__validate_global_current_body(_v4_scope, /, cls, value):
    fields = {
        "schema_version",
        "namespace",
        "target_trade_date",
        "current_path",
        "run_id",
        "artifact_sha256",
        "pointer_semantic_hash",
    }
    if not _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'Mapping')) or _v4_global(_v4_scope, 'set')(value) != fields:
        raise _v4_global(_v4_scope, 'ValueError')("invalid selection global current pointer")
    target = _v4_global(_v4_scope, '_date')(_v4_global(_v4_scope, 'str')(value.get("target_trade_date") or ""))
    run_id = value.get("run_id")
    if not _v4_global(_v4_scope, 'isinstance')(run_id, _v4_global(_v4_scope, 'str')) or not cls._RUN_ID.fullmatch(run_id):
        raise _v4_global(_v4_scope, 'ValueError')("invalid selection global current run_id")
    if value.get("schema_version") != "v3_5.selection_global_current.v1" or value.get("namespace") != cls._SELECTION_ROOT:
        raise _v4_global(_v4_scope, 'ValueError')("invalid selection global current namespace")
    if value.get("current_path") != f"{cls._SELECTION_ROOT}/{target}/current.json" or not _v4_global(_v4_scope, '_SHA256').fullmatch(_v4_global(_v4_scope, 'str')(value.get("artifact_sha256") or "")):
        raise _v4_global(_v4_scope, 'ValueError')("invalid selection global current target")
    body = {key: item for key, item in value.items() if key != "pointer_semantic_hash"}
    if value.get("pointer_semantic_hash") != cls._canonical_sha(body):
        raise _v4_global(_v4_scope, 'ValueError')("invalid selection global current semantic hash")


def _ResearchSelectionStore__pointer_value_body(_v4_scope, /, document, pointer):
    if pointer == "":
        return document
    if not _v4_global(_v4_scope, 'isinstance')(pointer, _v4_global(_v4_scope, 'str')) or not pointer.startswith("/"):
        raise _v4_global(_v4_scope, 'ValueError')("invalid selection source JSON pointer")
    current = document
    for raw_part in pointer[1:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if _v4_global(_v4_scope, 'isinstance')(current, _v4_global(_v4_scope, 'list')):
            try:
                current = current[_v4_global(_v4_scope, 'int')(part)]
            except (_v4_global(_v4_scope, 'ValueError'), _v4_global(_v4_scope, 'IndexError')) as error:
                raise _v4_global(_v4_scope, 'ValueError')("selection source JSON pointer missing") from error
        elif _v4_global(_v4_scope, 'isinstance')(current, _v4_global(_v4_scope, 'Mapping')) and part in current:
            current = current[part]
        else:
            raise _v4_global(_v4_scope, 'ValueError')("selection source JSON pointer missing")
    return current
