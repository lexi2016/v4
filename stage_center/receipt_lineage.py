"""Owner-write provenance using existing receipt and SelectionStore contracts.

These records bind files, not independently attest a natural invocation.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import PurePosixPath

from infrastructure.owned_io import SafeRoot
from .selection import SelectionStore


def _raw(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def bind_owner_receipt(result, *, receipt_root, selection_root, trade_date, stage_id):
    result = dict(result)
    result.pop("receipt_history", None)
    result["recorded_at"] = datetime.now(timezone.utc).isoformat()
    result["record_time_source"] = "OWNER_WRITE_CLOCK_UTC"
    result["selection_artifacts"] = {}
    store = SelectionStore(selection_root)
    keys = ("run_id", "artifact_id", "algorithm_sha256", "raw_artifact_sha256", "selected_rows")
    for market, lane in (result.get("markets") or {}).items():
        if not isinstance(lane, dict) or not lane.get("run_id"):
            continue
        try:
            verified = store._verify_run(trade_date, stage_id, market, lane["run_id"])
            if any(lane.get(k) != verified["envelope"].get(k) for k in keys):
                raise ValueError("owner selection reference differs")
            parent = PurePosixPath(verified["artifact_relative"]).parent
            paths = dict(artifact_relative=verified["artifact_relative"],
                         manifest_relative=str(parent / "manifest.json"), receipt_relative=str(parent / "receipt.json"))
            raw = {key: SafeRoot(selection_root).read_bytes(path) for key, path in paths.items()}
            hashes = {key.replace("_relative", "_bytes_sha256"): hashlib.sha256(value).hexdigest() for key, value in raw.items()}
            hashes.update({key + "_canonical_sha256": hashlib.sha256(_raw(json.loads(raw[key + "_relative"]))).hexdigest()
                           for key in ("manifest", "receipt")})
            if (verified["artifact_sha256"] != hashes["artifact_bytes_sha256"]
                    or verified["manifest_sha256"] != hashes["manifest_canonical_sha256"]
                    or verified["receipt_sha256"] != hashes["receipt_canonical_sha256"]):
                raise ValueError("selection changed during owner write")
            result["selection_artifacts"][market] = {
                "schema_version": "stage_center.runner.selection_binding.v1",
                **{k: lane[k] for k in keys}, **paths, **hashes,
                "trade_date": trade_date, "stage_id": stage_id, "market": market,
            }
        except (OSError, ValueError, TypeError, KeyError, AttributeError, UnicodeError):
            result["selection_artifacts"][market] = {"status": "SELECTION_TRIO_NOT_BOUND_AT_OWNER_WRITE"}
    raw = _raw(result)
    sha = hashlib.sha256(raw).hexdigest()
    relative = f"{trade_date}/{stage_id}/attempt_evidence/recorded-{sha}/RECEIPT.json"
    io = SafeRoot(receipt_root)
    io.write_bytes(relative, raw, require_absent=True)
    result["receipt_history"] = {"schema_version": "stage_center.runner.history_ref.v1", "relative_path": relative, "sha256": sha}
    return result
