"""Materialize one exact-date A-share stage-acquisition universe.

Only the six exact-date physical A-share pool trios are read.  This command
does not call HTTP, the V3 repository, or a presentation-only projection.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Callable, Sequence

from infrastructure.data_store import NativeDataStore, _date
from contracts.a_share_instruments import A_STOCK_INSTRUMENT_CONTRACT, a_share_instrument_rejection
from infrastructure.stage_source_roots import resolve_source_root
from infrastructure.stage_acquisition_universe_contracts import (
    StrictAPreselectionSnapshot,
    build_strict_stage_acquisition_universe,
    read_strict_a_preselection_snapshot,
)
from infrastructure.stage_acquisition_universe_store import (
    StageAcquisitionUniverseStore,
    build_stage_acquisition_universe,
)
from infrastructure.stage_acquisition_universe_commit import (
    EvidenceIdentity,
    StageAcquisitionUniverseCommit,
    StrictCommitError,
)


DEFAULT_DATA_ROOT = Path(__file__).resolve().parents[1] / ".runtime" / "data"
FULL_PRESELECTION_LIMIT = 100_000
RELEASE_ID_ENV = "V35_RELEASE_ID"
LEGACY_INSTRUMENT_RELEASE_ID = "hk-ready-status-20261021-r1"
LEGACY_INSTRUMENT_CURRENT_SHA256 = "e03f8649a5c0ed27d13c00edd6e0504e701f0b8a17b0ec3ea7a70e251c9980f0"


def _resolve_release_id(release_id: str | None) -> str:
    """Resolve an explicit release identity; never infer one from the path."""

    value = release_id if release_id not in (None, "") else os.environ.get(RELEASE_ID_ENV, "")
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            f"{RELEASE_ID_ENV} or explicit release_id is required for strict publication"
        )
    return value


def build_artifact(
    data_root: Path | str,
    trade_date: str,
    *,
    projection_reader: Callable[[NativeDataStore, str, int], dict[str, Any]] | None = None,
    preselection_source_root: Path | str | None = None,
) -> dict[str, Any]:
    """Call the local deep projection once and build the immutable artifact."""

    date = _date(trade_date)
    source_root = resolve_source_root(data_root, preselection_source_root)
    native_store = NativeDataStore(source_root)
    # The presentation projection remains import-compatible for callers, but
    # stage membership must come from the six exact-date physical A pools.
    if projection_reader is None:
        snapshot = read_strict_a_preselection_snapshot(
            native_store, date, FULL_PRESELECTION_LIMIT
        )
    else:
        candidate = projection_reader(native_store, date, FULL_PRESELECTION_LIMIT)
        if not isinstance(candidate, StrictAPreselectionSnapshot):
            # Display mappings are diagnostics only.  Even an existing legacy
            # current cannot authorize a fresh successor: every injected path
            # must hand over the concrete typed snapshot and then pass the
            # physical re-read below.
            raise ValueError(
                "required A pool strict snapshot is required; "
                "arbitrary projection injection is non-authoritative"
            )
        # A caller-supplied snapshot is only a typed handoff.  Re-read all six
        # physical pools before building READY so deletion or mutation between
        # the handoff and publish cannot be hidden by an in-memory mapping.
        snapshot = read_strict_a_preselection_snapshot(
            native_store, date, FULL_PRESELECTION_LIMIT
        )
        if snapshot != candidate:
            raise ValueError(
                "stage-acquisition physical snapshot changed before materialization"
            )
    artifact = build_strict_stage_acquisition_universe(snapshot)
    if source_root.absolute() != Path(data_root).absolute():
        artifact["preselection_source_root"] = str(source_root)
    return artifact


def materialize_stage_acquisition_universe(
    data_root: Path | str,
    trade_date: str,
    *,
    projection_reader: Callable[[NativeDataStore, str, int], dict[str, Any]] | None = None,
    preselection_source_root: Path | str | None = None,
    run_id: str | None = None,
    release_id: str | None = None,
    expected_current_sha256: str | None = None,
    successor_reason: str | None = None,
) -> dict[str, Any]:
    """Build and publish one exact-date strict V3 universe in an immutable store.

    Supplying ``expected_current_sha256`` selects the explicit same-day
    successor path.  The token is the raw bytes SHA of the current pointer;
    it is never interpreted as an artifact/semantic digest.
    """

    artifact = build_artifact(
        data_root,
        trade_date,
        projection_reader=projection_reader,
        preselection_source_root=preselection_source_root,
    )
    store = StageAcquisitionUniverseCommit(Path(data_root), preselection_source_root=preselection_source_root)
    identity = EvidenceIdentity(
        owner_id="V3_5_STAGE_CENTER",
        producer_id="ops.materialize_stage_acquisition_universe",
        release_id=_resolve_release_id(release_id),
        lane_id="A_SHARE_STAGE_ACQUISITION",
    )
    if expected_current_sha256 is None:
        if successor_reason not in (None, ""):
            raise ValueError("successor_reason requires expected_current_sha256")
        try:
            result = store.publish(artifact, run_id=run_id, identity=identity)
        except StrictCommitError as error:
            legacy_identity = None
            if str(error) == "strict current evidence identity mismatch":
                # A new source release must keep its real runtime identity.
                # This exact two-pin exception reads the old immutable input
                # under its OWN identity; it never publishes under that ID.
                if (os.environ.get("V35_LEGACY_INSTRUMENT_INPUT_RELEASE_ID") != LEGACY_INSTRUMENT_RELEASE_ID
                        or os.environ.get("V35_LEGACY_INSTRUMENT_INPUT_CURRENT_SHA256") != LEGACY_INSTRUMENT_CURRENT_SHA256):
                    raise
                legacy_identity = EvidenceIdentity(
                    owner_id=identity.owner_id, producer_id=identity.producer_id,
                    release_id=LEGACY_INSTRUMENT_RELEASE_ID, lane_id=identity.lane_id,
                )
            elif str(error) != "strict exact-date current conflict":
                raise
            # Keep the verified committed input as historical authority.  A
            # family-filter rollout must not attempt a shrinking successor
            # or relabel that301-row input as a freshly published297 rows.
            # Only ordinary idempotent preparation may reuse it; explicit
            # successor/CAS publication keeps its original policy below.
            chain = store.read_current(trade_date, identity=legacy_identity or identity)
            if legacy_identity and chain["current_bytes_sha256"] != LEGACY_INSTRUMENT_CURRENT_SHA256:
                raise StrictCommitError("legacy instrument input current SHA mismatch")
            old = chain["artifact"]
            excluded = [code for code in old["codes"] if a_share_instrument_rejection(code)]
            eligible = [code for code in old["codes"] if code not in excluded]
            sources = {code: old["code_sources"][code] for code in eligible}
            if not excluded or eligible != artifact.get("codes") or sources != artifact.get("code_sources"):
                raise
            result = store._result(chain, idempotent=True)
            result["instrument_filter_reuse"] = {
                "contract": A_STOCK_INSTRUMENT_CONTRACT,
                "runtime_release_id": identity.release_id,
                "committed_input_release_id": old["release_id"],
                "diagnostic": "LEGACY_COMMITTED_INPUT_REUSED_WITH_STOCK_SELECTION_FILTER",
                "committed_input_rows": len(old["codes"]),
                "eligible_stock_rows": len(eligible),
                "excluded_codes": excluded,
                "current_unchanged": True,
                "fresh_artifact_published": False,
            }
    else:
        if not isinstance(successor_reason, str) or not successor_reason.strip():
            raise ValueError("successor_reason is required with expected_current_sha256")
        result = store.publish_successor(
            artifact,
            expected_current_sha256=expected_current_sha256,
            reason=successor_reason,
            run_id=run_id,
            identity=identity,
        )
    return {**result, "artifact": result["artifact"]}


def materialize_stage_acquisition_universe_successor(
    data_root: Path | str,
    trade_date: str,
    *,
    expected_current_sha256: str,
    reason: str,
    projection_reader: Callable[[NativeDataStore, str, int], dict[str, Any]] | None = None,
    preselection_source_root: Path | str | None = None,
    run_id: str | None = None,
    release_id: str | None = None,
) -> dict[str, Any]:
    """Materialize one explicit strict same-day append-only successor."""

    return materialize_stage_acquisition_universe(
        data_root,
        trade_date,
        projection_reader=projection_reader,
        preselection_source_root=preselection_source_root,
        run_id=run_id,
        release_id=release_id,
        expected_current_sha256=expected_current_sha256,
        successor_reason=reason,
    )


def _jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trade-date", required=True)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--preselection-source-root", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--release-id", default=os.environ.get(RELEASE_ID_ENV, ""))
    parser.add_argument("--expected-current-sha256")
    parser.add_argument("--successor-reason")
    args = parser.parse_args(argv)
    result = materialize_stage_acquisition_universe(
        args.data_root,
        args.trade_date,
        preselection_source_root=args.preselection_source_root,
        run_id=args.run_id,
        release_id=args.release_id,
        expected_current_sha256=args.expected_current_sha256,
        successor_reason=args.successor_reason,
    )
    print(json.dumps(_jsonable(result), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI dispatch
    raise SystemExit(main())


__all__ = [
    "DEFAULT_DATA_ROOT",
    "FULL_PRESELECTION_LIMIT",
    "RELEASE_ID_ENV",
    "StageAcquisitionUniverseStore",
    "build_artifact",
    "build_stage_acquisition_universe",
    "main",
    "materialize_stage_acquisition_universe",
    "materialize_stage_acquisition_universe_successor",
]
