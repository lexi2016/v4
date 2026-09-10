"""Generate the Phase-5 governance audit from frozen, read-only inputs."""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from ops.migration.runtime_governance import build_runtime_governance_audit


REPO = Path(__file__).resolve().parents[2]
DEFAULT_GRAPH = (
    REPO
    / ".runtime"
    / "evidence"
    / "phase0"
    / "v3_current_script_task_graph_20260801"
    / "v3_current_script_task_graph_20260801.json"
)
DEFAULT_INVENTORY = (
    REPO / "contracts" / "migration" / "v35_replacement_inventory_v2.json"
)
DEFAULT_CATALOG = REPO / "contracts" / "runtime_workloads.json"
DEFAULT_OUTPUT = (
    REPO
    / "contracts"
    / "migration"
    / "phase5_runtime_governance_audit_v1.json"
)
RUNTIME_EVIDENCE_OUTPUT = (
    REPO
    / ".runtime"
    / "evidence"
    / "phase5"
    / "runtime_governance_audit_v1.json"
)


def _allowed_output(path: Path) -> Path:
    resolved = path.resolve(strict=False)
    allowed_outputs = {
        DEFAULT_OUTPUT.resolve(strict=False),
        RUNTIME_EVIDENCE_OUTPUT.resolve(strict=False),
    }
    if resolved not in allowed_outputs:
        raise ValueError("Phase-5 audit output is not an approved audit target")
    return resolved


def _validated_output(path: Path, *inputs: Path) -> Path:
    destination = _allowed_output(path)
    if destination in {source.resolve(strict=False) for source in inputs}:
        raise ValueError("Phase-5 audit output overlaps a read-only input")
    return destination


def _atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as output:
            json.dump(payload, output, ensure_ascii=False, sort_keys=True, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph", type=Path, default=DEFAULT_GRAPH)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    destination = _validated_output(
        args.output,
        args.graph,
        args.inventory,
        args.catalog,
    )
    audit = build_runtime_governance_audit(
        graph_path=args.graph,
        inventory_path=args.inventory,
        catalog_path=args.catalog,
        repo_root=REPO,
    )
    _atomic_write(destination, audit)
    print(
        json.dumps(
            {
                "output": destination.relative_to(REPO).as_posix(),
                "semantic_hash": audit["semantic_hash"],
                "status": audit["status"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
