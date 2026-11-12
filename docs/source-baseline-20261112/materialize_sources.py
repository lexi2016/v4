"""Verify or reconstruct selected review sources; never creates a runnable release."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]


def relative_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or not path.parts or any(p in ("..", ".git") for p in path.parts):
        raise ValueError(f"unsafe relative path: {value}")
    return path


def read_matrix() -> dict:
    matrix = json.loads((HERE / "SOURCE_MATRIX.json").read_text())
    for role, reference in list(matrix["roles"].items()):
        source = HERE / relative_path(reference["matrix_path"])
        if not source.resolve().is_relative_to(HERE):
            raise ValueError("role matrix escapes source entry")
        payload = source.read_bytes()
        if hashlib.sha256(payload).hexdigest() != reference["sha256"]:
            raise ValueError(f"role matrix hash drift: {role}")
        matrix["roles"][role] = json.loads(payload)
    return matrix


def selected_sources(matrix: dict, role: str):
    for row in matrix["roles"][role]["selected"]:
        source = REPO / relative_path(row["repository_path"])
        if not source.resolve().is_relative_to(REPO) or not source.is_file():
            raise ValueError(f"source missing or escapes repository: {row['repository_path']}")
        payload = source.read_bytes()
        if hashlib.sha256(payload).hexdigest() != row["sha256"]:
            raise ValueError(f"source hash drift: {row['repository_path']}")
        yield relative_path(row["path"]), payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", help="One role from SOURCE_MATRIX.json")
    parser.add_argument("--out", type=Path, help="New external directory; must not exist")
    args = parser.parse_args()
    matrix = read_matrix()
    roles = [args.role] if args.role else list(matrix["roles"])
    if any(role not in matrix["roles"] for role in roles):
        parser.error("unknown role")
    if args.out and not args.role:
        parser.error("--out requires exactly one --role")
    if args.out:
        destination = args.out.resolve()
        if destination.exists() or destination.is_relative_to(REPO):
            parser.error("output must be a new external directory")
        # Verify every selected source before creating any output.
        rows = list(selected_sources(matrix, args.role))
        destination.mkdir(parents=True)
        for path, payload in rows:
            target = destination / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
        print(json.dumps({"role": args.role, "selected_sources": len(rows), "status": "REVIEW_SOURCES_ONLY_NOT_DEPLOYED"}))
    else:
        counts = {role: sum(1 for _ in selected_sources(matrix, role)) for role in roles}
        print(json.dumps({"status": "SOURCE_HASHES_MATCH", "roles": counts}))


if __name__ == "__main__":
    main()
