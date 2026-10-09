"""stage_center.runner: runner_receipts (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _StageCenterRunner__prepare_hk_active_snapshots_body(_v4_scope, /, self, trade_date, evaluated_at, *, stage_id, historical_backfill):
    """Delegate the Stage-8-only 15:50 immutable pre-capture.

        The universe loader keeps the existing V4 verified-pool validator at
        the boundary.  On HK-open/Connect-closed days it may use the newest
        earlier verified D-1 membership, preserving the original source date
        and SHA; quotes remain exact to the observation date.
        """

    loaded_binding: StageUniverseBinding | None = None

    def universe_loader() -> tuple[Path, tuple[str, ...], str]:
        nonlocal loaded_binding
        if self.config.hk_d1_root is None:
            raise _v4_global(_v4_scope, 'RunnerError')("production HK D1 Top100 root is required for Stage 8 pre-capture")
        binding = _v4_global(_v4_scope, '_build_hk_stage_binding')(
            self.config.hk_d1_root,
            trade_date,
            preselection_source_root=self.config.preselection_source_root,
        )
        loaded_binding = binding
        return (
            _v4_global(_v4_scope, 'Path')(_v4_global(_v4_scope, '_evidence_value')(binding.evidence, "hk_d1_json") or self.config.hk_d1_root),
            binding.codes,
            binding.sha256,
        )

    from stage_center.hk_stage8 import prepare_due_snapshot, prepare_hk_active_snapshot

    results = prepare_due_snapshot(
        self.config,
        trade_date,
        evaluated_at,
        stage_id=stage_id,
        historical_backfill=historical_backfill,
        universe_loader=universe_loader,
        snapshot_preparer=prepare_hk_active_snapshot,
    )
    if loaded_binding is not None:
        source_trade_date = _v4_global(_v4_scope, '_evidence_value')(
            loaded_binding.evidence, "hk_d1_source_trade_date"
        ) or trade_date
        source_signal_date = _v4_global(_v4_scope, '_evidence_value')(
            loaded_binding.evidence, "hk_d1_source_signal_date"
        )
        for item in results:
            item.update({
                "hk_d1_source_trade_date": source_trade_date,
                "hk_d1_source_signal_date": source_signal_date,
                "hk_d1_source_sha256": loaded_binding.sha256,
                "hk_observation_trade_date": trade_date,
                "source_evidence": _v4_global(_v4_scope, 'list')(loaded_binding.evidence),
            })
    return results


def _StageCenterRunner__write_receipt_body(_v4_scope, /, self, payload, trade_date, stage_id):
    result = {"schema_version": "stage_center.runner.receipt.v1", "runner": "stage_center", **_v4_global(_v4_scope, '_deadline').before_receipt(payload), **_v4_global(_v4_scope, 'SAFETY_FLAGS')}
    scope = getattr(self, "_execution_scope", None)
    if scope is not None:
        result = scope.merge(result, trade_date, stage_id)
    if self.config.backfill_run_id:
        result.update(
            {
                "mode": "BACKFILL",
                "backfill_run_id": self.config.backfill_run_id,
                "latest_updated": False,
                "current_updated": False,
                "namespace": {
                    "raw_root": _v4_global(_v4_scope, 'str')(self.config.raw_root),
                    "selection_root": _v4_global(_v4_scope, 'str')(self.config.selection_root),
                    "receipt_root": _v4_global(_v4_scope, 'str')(self.config.receipt_root),
                },
            }
        )
    _attach_selection_artifact_bindings(_v4_scope, self, result, trade_date, stage_id)
    _archive_owner_receipt(self, result, trade_date, stage_id)
    receipt_path = self._receipt_path(trade_date, stage_id)
    _v4_global(_v4_scope, '_atomic_json')(receipt_path, result)
    _v4_global(_v4_scope, '_deadline').receipt_written(receipt_path, result)
    return result


class _ExecutionScope:
    """Internal scope on a copied original runner, never a second producer.

    The dispatcher owns the original slot lock and budget. All original inner
    receipt writes and outer deadline rewrites share this merge contract.
    """

    def __init__(self, markets, prior, attempt_count, origin):
        from copy import deepcopy
        self.markets = tuple(markets)
        self.prior = deepcopy(prior)
        self.attempt_count = attempt_count
        self.origin = origin

    def merge(self, payload, trade_date, stage_id):
        from copy import deepcopy
        if (trade_date != self.prior["trade_date"] or stage_id != self.prior["stage_id"]):
            raise ValueError("recovery receipt slot changed")
        result = {**deepcopy(self.prior), **deepcopy(payload)}
        old_markets = self.prior.get("markets") or {}
        new_markets = payload.get("markets") or {}
        # Never take a sibling from an error payload, an empty projection, or
        # a fresh candidate binding. Preserve its original complete object.
        result["markets"] = {
            **deepcopy(old_markets),
            **{m: deepcopy(new_markets[m]) for m in self.markets if m in new_markets},
        }
        for field in ("input_bindings", "selection_artifacts", "selection_binding_errors"):
            old = self.prior.get(field) or {}
            new = payload.get(field) or {}
            result[field] = {
                **{m: deepcopy(value) for m, value in old.items() if m not in self.markets},
                **{m: deepcopy(new[m]) for m in self.markets if m in new},
            }
        result["node_attempt_count"] = self.attempt_count
        result["execution_pending"] = payload.get("execution_pending", False)
        result["execution_markets"] = list(self.markets)
        result["execution_origin"] = self.origin
        result["execution_status"] = payload.get("execution_status", payload.get("status", "CANNOT_CONFIRM"))
        for key, value in self.prior.items():
            if key.startswith(("repair_recovery_", "dependency_rearm_")):
                result[key] = deepcopy(value)
        if "A_SHARE" not in self.markets and "A_SHARE" in old_markets:
            for key in ("candidate_current_sha256", "candidate_run_id"):
                if key in self.prior:
                    result[key] = deepcopy(self.prior[key])
        # Successful execution is not automatically a successful whole stage.
        # Real failures retain their original status/reason and retry semantics.
        if result.get("status") in {"READY", "READY_EMPTY", "NOOP_ALREADY_VERIFIED"}:
            states = {str(lane.get("selection_status", lane.get("status", "CANNOT_CONFIRM")))
                      for lane in result["markets"].values()}
            if not states <= {"READY", "READY_EMPTY", "NOOP_ALREADY_VERIFIED"}:
                result["status"] = "PARTIAL_WITH_ROWS"
        return result


def scoped_recovery_runner(runner, *, markets, prior_receipt, attempt_count, origin):
    """Bind a per-call market scope to the same runner, config and stores.

    No new roots, collectors, selectors or retry budgets are introduced. The
    caller must already own the slot lock; this function does not authorize a
    run. The original receipt is archived byte-for-byte before its reservation.
    """
    from copy import copy
    import hashlib
    import json
    from infrastructure.owned_io import SafeRoot

    if tuple(markets) not in {("A_SHARE",), ("HK_CONNECT",)}:
        raise ValueError("recovery requires one existing market lane")
    path = runner._receipt_path(prior_receipt["trade_date"], prior_receipt["stage_id"])
    io = SafeRoot(path.parent)
    raw = io.read_bytes(path.name)
    if json.loads(raw) != prior_receipt:
        raise ValueError("recovery receipt changed before scoping")
    digest = hashlib.sha256(raw).hexdigest()
    relative = f"attempt_evidence/preserved-{digest}/PRIOR_RECEIPT.json"
    try:
        io.write_bytes(relative, raw, require_absent=True)
    except FileExistsError:
        if io.read_bytes(relative) != raw:
            raise ValueError("preserved recovery receipt conflict")
    scoped = copy(runner)
    scoped._execution_scope = _ExecutionScope(markets, prior_receipt, attempt_count, origin)
    return scoped


def _owner_write_time():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _candidate_input_bindings(candidate, hk_binding, markets, *, a_candidate_missing):
    """Copy verified input identities without inventing file-byte digests.

    CandidateInput's three unsuffixed hashes are canonical JSON digests;
    strict v3 separately exposes the original file-byte hashes. A plan-only
    HK candidate is never recorded as an A acquisition trio.
    """
    bindings = {}
    if "A_SHARE" in markets and not a_candidate_missing:
        item = {
            "schema_version": "stage_center.runner.input_binding.v1",
            "kind": "A_SHARE_STAGE_ACQUISITION_UNIVERSE",
            "binding_scope": "INPUT_VALIDATED_FOR_THIS_INVOCATION",
            "trade_date": candidate.trade_date,
            "run_id": candidate.run_id,
            "current_relative": candidate.current_relative,
            "current_bytes_sha256": candidate.current_sha256,
            "artifact_canonical_sha256": candidate.artifact_sha256,
            "manifest_canonical_sha256": candidate.manifest_sha256,
            "receipt_canonical_sha256": candidate.receipt_sha256,
            "row_count": len(candidate.codes),
            "source_evidence": list(candidate.source_evidence),
        }
        for name in ("artifact_bytes_sha256", "manifest_bytes_sha256",
                     "receipt_bytes_sha256", "commit_marker_bytes_sha256",
                     "commit_id", "digest_mode", "strict_schema"):
            value = getattr(candidate, name, None)
            if value is not None:
                item[name] = value
        bindings["A_SHARE"] = item
    if "HK_CONNECT" in markets and hk_binding is not None:
        bindings["HK_CONNECT"] = {
            "schema_version": "stage_center.runner.input_binding.v1",
            "kind": "HK_CONNECT_D1_TOP100",
            "binding_scope": "INPUT_VALIDATED_FOR_THIS_INVOCATION",
            "trade_date": hk_binding.trade_date,
            "run_id": hk_binding.source_run_id,
            "artifact_bytes_sha256": hk_binding.sha256,
            "row_count": len(hk_binding.codes),
            "source_evidence": list(hk_binding.evidence),
            "trio_status": "NOT_EXPOSED_BY_STAGE_UNIVERSE_BINDING",
        }
    return bindings


def _selection_artifact_binding(store, trade_date, stage_id, market, original):
    """Bind the original store's exact run; never follow a declared root."""
    import hashlib
    import json
    from pathlib import PurePosixPath
    from infrastructure.owned_io import SafeRoot

    verified = store._verify_run(trade_date, stage_id, market, original["run_id"])
    identity = ("run_id", "artifact_id", "algorithm_sha256", "raw_artifact_sha256", "selected_rows")
    if any(verified["envelope"].get(key) != original.get(key) for key in identity):
        raise ValueError("receipt selection identity differs from original store")
    artifact_relative = verified["artifact_relative"]
    prefix = str(PurePosixPath(artifact_relative).parent)
    manifest_relative, receipt_relative = prefix + "/manifest.json", prefix + "/receipt.json"
    io = SafeRoot(store.root)
    artifact_raw = io.read_bytes(artifact_relative)
    manifest_raw = io.read_bytes(manifest_relative)
    receipt_raw = io.read_bytes(receipt_relative)
    artifact_sha = hashlib.sha256(artifact_raw).hexdigest()
    manifest, receipt = json.loads(manifest_raw), json.loads(receipt_raw)
    canonical = lambda value: hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()
    if (artifact_sha != verified["artifact_sha256"]
            or canonical(manifest) != verified["manifest_sha256"]
            or canonical(receipt) != verified["receipt_sha256"]):
        raise ValueError("selection trio changed after original store verification")
    return {
        "schema_version": "stage_center.runner.selection_binding.v1",
        **{key: original[key] for key in identity},
        "artifact_relative": artifact_relative,
        "manifest_relative": manifest_relative,
        "receipt_relative": receipt_relative,
        "artifact_bytes_sha256": artifact_sha,
        "manifest_bytes_sha256": hashlib.sha256(manifest_raw).hexdigest(),
        "receipt_bytes_sha256": hashlib.sha256(receipt_raw).hexdigest(),
        "manifest_canonical_sha256": verified["manifest_sha256"],
        "receipt_canonical_sha256": verified["receipt_sha256"],
    }


def _attach_selection_artifact_bindings(_v4_scope, self, result, trade_date, stage_id):
    from copy import deepcopy

    scope = getattr(self, "_execution_scope", None)
    active = set(scope.markets) if scope is not None else set(result.get("markets") or {})
    # A scoped retry preserves every byte of a sibling's existing binding.
    result["selection_artifacts"] = {
        market: deepcopy(value) for market, value in (result.get("selection_artifacts") or {}).items()
        if market not in active
    }
    result["selection_binding_errors"] = {
        market: deepcopy(value) for market, value in (result.get("selection_binding_errors") or {}).items()
        if market not in active
    }
    for market, original in (result.get("markets") or {}).items():
        if market not in active or not isinstance(original, dict) or not original.get("run_id"):
            continue
        try:
            store = _v4_global(_v4_scope, 'SelectionStore')(self.config.selection_root)
            result["selection_artifacts"][market] = _selection_artifact_binding(
                store, trade_date, stage_id, market, original
            )
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
            # Evidence failure does not erase an existing calculated result.
            result["selection_binding_errors"][market] = str(error)


def _archive_owner_receipt(self, result, trade_date, stage_id):
    """Append original owner evidence before replacing the existing pointer.

    This is owner-written history, not an independent execution attestation.
    Rewrites get their real current write time; old times are never backfilled.
    """
    import hashlib
    import json
    import re
    from infrastructure.owned_io import SafeRoot

    if (not re.fullmatch(r"\d{8}", trade_date)
            or not re.fullmatch(r"STAGE_\d{4}(?:_\d{4})?", stage_id)
            or result.get("trade_date") != trade_date or result.get("stage_id") != stage_id):
        raise ValueError("receipt archive date/stage identity mismatch")
    result.pop("receipt_history", None)
    result["recorded_at"] = _owner_write_time()
    result["record_time_source"] = "OWNER_WRITE_CLOCK_UTC"
    raw = (json.dumps(result, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    relative = f"{trade_date}/{stage_id}/attempt_evidence/recorded-{digest}/RECEIPT.json"
    io = SafeRoot(self.config.receipt_root)
    try:
        io.write_bytes(relative, raw, require_absent=True)
    except FileExistsError:
        if io.read_bytes(relative) != raw:
            raise ValueError("immutable owner receipt archive conflict")
    if io.read_bytes(relative) != raw:
        raise ValueError("immutable owner receipt archive readback differs")
    result["receipt_history"] = {
        "schema_version": "stage_center.runner.history_ref.v1",
        "relative_path": relative,
        "sha256": digest,
    }
