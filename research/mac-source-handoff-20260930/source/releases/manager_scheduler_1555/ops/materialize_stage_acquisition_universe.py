"""Materialize one exact-date A-share stage-acquisition universe.

Only the local deep preselection projection is read.  This command does not
call HTTP, the V3 repository, or any of the seven physical pool readers.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Callable, Sequence

from infrastructure.data_store import NativeDataStore, _date
from infrastructure.stage_acquisition_universe_contracts import (
    StrictAPreselectionSnapshot,
    read_strict_a_preselection_snapshot,
)
from infrastructure.stage_acquisition_universe_store import (
    StageAcquisitionUniverseStore,
    build_stage_acquisition_universe,
)
from infrastructure.stage_acquisition_universe_commit import EvidenceIdentity


DEFAULT_DATA_ROOT = Path(__file__).resolve().parents[1] / ".runtime" / "data"
FULL_PRESELECTION_LIMIT = 100_000
RELEASE_ID_ENV = "V35_RELEASE_ID"


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
) -> dict[str, Any]:
    """Call the local deep projection once and build the immutable artifact."""

    date = _date(trade_date)
    native_store = NativeDataStore(Path(data_root))
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
    return build_stage_acquisition_universe(snapshot, date)


def materialize_stage_acquisition_universe(
    data_root: Path | str,
    trade_date: str,
    *,
    projection_reader: Callable[[NativeDataStore, str, int], dict[str, Any]] | None = None,
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
    )
    store = StageAcquisitionUniverseStore(Path(data_root))
    identity = EvidenceIdentity(
        owner_id="V3_5_STAGE_CENTER",
        producer_id="ops.materialize_stage_acquisition_universe",
        release_id=_resolve_release_id(release_id),
        lane_id="A_SHARE_STAGE_ACQUISITION",
    )
    if expected_current_sha256 is None:
        if successor_reason not in (None, ""):
            raise ValueError("successor_reason requires expected_current_sha256")
        result = store.publish(artifact, run_id=run_id, identity=identity)
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
    run_id: str | None = None,
    release_id: str | None = None,
) -> dict[str, Any]:
    """Materialize one explicit strict same-day append-only successor."""

    return materialize_stage_acquisition_universe(
        data_root,
        trade_date,
        projection_reader=projection_reader,
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
    parser.add_argument("--run-id")
    parser.add_argument("--release-id", default=os.environ.get(RELEASE_ID_ENV, ""))
    parser.add_argument("--expected-current-sha256")
    parser.add_argument("--successor-reason")
    args = parser.parse_args(argv)
    result = materialize_stage_acquisition_universe(
        args.data_root,
        args.trade_date,
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
