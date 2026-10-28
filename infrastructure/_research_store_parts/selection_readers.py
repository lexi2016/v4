"""infrastructure.research_store: selection_readers (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _ResearchSelectionStore__read_date_current_snapshot_body(_v4_scope, /, self, target_trade_date):
    relative = self._date_current_relative(target_trade_date)
    path = self._path(relative)
    if not path.is_file():
        if path.exists():
            raise _v4_global(_v4_scope, 'ValueError')("selection current pointer is not a file")
        return None, None
    raw = path.read_bytes()
    try:
        value = _v4_global(_v4_scope, 'json').loads(raw.decode("utf-8"))
    except (_v4_global(_v4_scope, 'UnicodeDecodeError'), _v4_global(_v4_scope, 'json').JSONDecodeError) as error:
        raise _v4_global(_v4_scope, 'ValueError')("selection current pointer is invalid JSON") from error
    self._validate_current(value, target_trade_date=target_trade_date)
    return value, _v4_global(_v4_scope, 'hashlib').sha256(raw).hexdigest()


def _ResearchSelectionStore__read_run_body(_v4_scope, /, self, target_trade_date, run_id):
    if not self._RUN_ID.fullmatch(run_id):
        raise _v4_global(_v4_scope, 'ValueError')("invalid selection run_id")
    artifact_relative = self._artifact_relative(target_trade_date, run_id)
    receipt_relative = self._receipt_relative(target_trade_date, run_id)
    run_manifest_relative = self._run_manifest_relative(target_trade_date, run_id)
    artifact_path = self._path(artifact_relative)
    receipt_path = self._path(receipt_relative)
    if not artifact_path.is_file() or not receipt_path.is_file():
        raise _v4_global(_v4_scope, 'ValueError')("selection artifact or receipt is missing")
    payload = self._read(artifact_relative)
    artifact_sha = self._raw_sha(artifact_path)
    manifest = self._manifest()
    run_manifest_path = self._path(run_manifest_relative)
    if not run_manifest_path.is_file():
        raise _v4_global(_v4_scope, 'ValueError')("selection run manifest is missing")
    run_manifest = self._read(run_manifest_relative)
    self._validate_manifest(run_manifest)
    run_manifest_sha = self._raw_sha(run_manifest_path)
    if (
        run_manifest["entries"].get(artifact_relative) != artifact_sha
        or manifest["entries"].get(artifact_relative) != artifact_sha
        or manifest["entries"].get(run_manifest_relative) != run_manifest_sha
    ):
        raise _v4_global(_v4_scope, 'ValueError')("selection artifact manifest mismatch")
    receipt = self._read(receipt_relative)
    receipt_sha = self._raw_sha(receipt_path)
    if (
        run_manifest["entries"].get(receipt_relative) != receipt_sha
        or manifest["entries"].get(receipt_relative) != receipt_sha
        or receipt != self._receipt(payload, artifact_relative, artifact_sha)
    ):
        raise _v4_global(_v4_scope, 'ValueError')("selection receipt manifest mismatch")
    if _v4_global(_v4_scope, 'validate_selection_research_product')(payload) != target_trade_date or payload.get("run_id") != run_id:
        raise _v4_global(_v4_scope, 'ValueError')("selection artifact identity mismatch")
    self._verify_product_sources(payload)
    self._assert_source_scope_not_invalidated(payload, artifact_sha)
    return payload


def _ResearchSelectionStore__read_current_run_body(_v4_scope, /, self, target_trade_date, current, *, current_sha256):
    """Read a current target only after checking every pointer SHA binding."""

    run_id = _v4_global(_v4_scope, 'str')(current["run_id"])
    payload = self._read_run(target_trade_date, run_id)
    artifact_path = self._path(_v4_global(_v4_scope, 'str')(current["artifact_path"]))
    receipt_path = self._path(_v4_global(_v4_scope, 'str')(current["receipt_path"]))
    manifest_path = self._path(_v4_global(_v4_scope, 'str')(current["manifest_path"]))
    actual = {
        "artifact_sha256": self._raw_sha(artifact_path),
        "receipt_sha256": self._raw_sha(receipt_path),
        "manifest_sha256": self._raw_sha(manifest_path),
    }
    for field, digest in actual.items():
        if current.get(field) != digest:
            raise _v4_global(_v4_scope, 'ValueError')(f"selection current {field} binding mismatch")
    if current.get("target_trade_date") != target_trade_date:
        raise _v4_global(_v4_scope, 'ValueError')("selection current target date mismatch")
    if current.get("run_id") != payload.get("run_id") or current.get("generated_at") != payload.get("generated_at"):
        raise _v4_global(_v4_scope, 'ValueError')("selection current run identity binding mismatch")
    if current_sha256 is not None:
        current_path = self._path(self._date_current_relative(target_trade_date))
        if self._raw_sha(current_path) != current_sha256:
            raise _v4_global(_v4_scope, 'ValueError')("selection current pointer changed during read")
    global_path = self._path(self._CURRENT_RELATIVE)
    if global_path.is_file():
        global_current = self._read(self._CURRENT_RELATIVE)
        self._validate_global_current(global_current)
        if global_current.get("target_trade_date") == target_trade_date:
            if (
                global_current.get("run_id") != current.get("run_id")
                or global_current.get("artifact_sha256") != current.get("artifact_sha256")
            ):
                raise _v4_global(_v4_scope, 'ValueError')("selection global current binding mismatch")
    elif global_path.exists():
        raise _v4_global(_v4_scope, 'ValueError')("selection global current pointer is not a file")
    return payload


def _ResearchSelectionStore_read_exact_body(_v4_scope, /, self, target_trade_date):
    target_trade_date = _v4_global(_v4_scope, '_date')(target_trade_date)
    current, current_sha256 = self._read_date_current_snapshot(target_trade_date)
    if current is None:
        prefix = f"{self._SELECTION_ROOT}/{target_trade_date}/"
        if _v4_global(_v4_scope, 'any')(_v4_global(_v4_scope, 'str')(path).startswith(prefix) for path in self._manifest()["entries"]):
            raise _v4_global(_v4_scope, 'ValueError')("selection artifact exists without current pointer")
        return None
    return self._read_current_run(
        target_trade_date,
        current,
        current_sha256=current_sha256,
    )


def _ResearchSelectionStore_read_exact_with_lineage_body(_v4_scope, /, self, target_trade_date):
    target_trade_date = _v4_global(_v4_scope, '_date')(target_trade_date)
    current, current_sha256 = self._read_date_current_snapshot(target_trade_date)
    if current is None:
        prefix = f"{self._SELECTION_ROOT}/{target_trade_date}/"
        if _v4_global(_v4_scope, 'any')(_v4_global(_v4_scope, 'str')(path).startswith(prefix) for path in self._manifest()["entries"]):
            raise _v4_global(_v4_scope, 'ValueError')("selection artifact exists without current pointer")
        return None, None
    payload = self._read_current_run(
        target_trade_date,
        current,
        current_sha256=current_sha256,
    )
    manifest_path = self._path(_v4_global(_v4_scope, 'str')(current["manifest_path"]))
    lineage = {
        "artifact_path": current["artifact_path"],
        "artifact_sha256": current["artifact_sha256"],
        "receipt_path": current["receipt_path"],
        "receipt_sha256": current["receipt_sha256"],
        "manifest_path": current["manifest_path"],
        "manifest_sha256": self._raw_sha(manifest_path),
        "current_path": self._date_current_relative(target_trade_date),
        "current_sha256": current_sha256,
        "run_id": current["run_id"],
        "target_trade_date": target_trade_date,
    }
    return payload, lineage
