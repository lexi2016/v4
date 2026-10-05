"""Materialize the approved non-dispatchable registrations into the catalog."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from infrastructure.scheduling.catalog import load_workload_catalog
from ops.migration.task_registration import build_catalog_with_task_registrations


REPO = Path(__file__).resolve().parents[2]
CATALOG = REPO / "contracts" / "runtime_workloads.json"
AUDIT = REPO / "contracts" / "migration" / "phase5_runtime_governance_audit_v1.json"


def _load(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid registration input: {path.name}") from error
    if not isinstance(payload, dict):
        raise ValueError(f"invalid registration input: {path.name}")
    return payload


def _atomic_write(path: Path, payload: dict) -> None:
    if path.resolve(strict=True) != CATALOG.resolve(strict=True):
        raise ValueError("registration output must be the runtime catalog")
    handle, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as output:
            json.dump(payload, output, ensure_ascii=False, sort_keys=True, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        load_workload_catalog(Path(temporary))
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main() -> None:
    catalog = build_catalog_with_task_registrations(_load(CATALOG), _load(AUDIT))
    _atomic_write(CATALOG, catalog)
    print(
        json.dumps(
            {
                "catalog": CATALOG.relative_to(REPO).as_posix(),
                "schema_version": catalog["schema_version"],
                "task_registration_count": len(catalog["task_registrations"]),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
