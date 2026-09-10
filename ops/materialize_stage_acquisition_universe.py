"""Materialize one exact-date A-share stage-acquisition universe.

Only the local deep preselection projection is read.  This command does not
call HTTP, the V3 repository, or any of the seven physical pool readers.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Callable, Sequence

from domains.preselection import preselection
from infrastructure.data_store import NativeDataStore, _date
from infrastructure.stage_acquisition_universe_store import (
    StageAcquisitionUniverseStore,
    build_stage_acquisition_universe,
)


DEFAULT_DATA_ROOT = Path(__file__).resolve().parents[1] / ".runtime" / "data"
FULL_PRESELECTION_LIMIT = 100_000


def build_artifact(
    data_root: Path | str,
    trade_date: str,
    *,
    projection_reader: Callable[[NativeDataStore, str, int], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Call the local deep projection once and build the immutable artifact."""

    date = _date(trade_date)
    native_store = NativeDataStore(Path(data_root))
    reader = projection_reader or preselection
    projection = reader(native_store, date, FULL_PRESELECTION_LIMIT)
    return build_stage_acquisition_universe(projection, date)


def materialize_stage_acquisition_universe(
    data_root: Path | str,
    trade_date: str,
    *,
    projection_reader: Callable[[NativeDataStore, str, int], dict[str, Any]] | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Build and publish one exact-date V2 universe in an immutable store."""

    artifact = build_artifact(
        data_root,
        trade_date,
        projection_reader=projection_reader,
    )
    result = StageAcquisitionUniverseStore(Path(data_root)).publish(
        artifact,
        run_id=run_id,
    )
    return {**result, "artifact": artifact}


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
    args = parser.parse_args(argv)
    result = materialize_stage_acquisition_universe(
        args.data_root,
        args.trade_date,
        run_id=args.run_id,
    )
    print(json.dumps(_jsonable(result), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI dispatch
    raise SystemExit(main())


__all__ = [
    "DEFAULT_DATA_ROOT",
    "FULL_PRESELECTION_LIMIT",
    "StageAcquisitionUniverseStore",
    "build_artifact",
    "build_stage_acquisition_universe",
    "main",
    "materialize_stage_acquisition_universe",
]
