"""Read-only preimage/postimage check. Does not apply patches or stop services."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--mode", choices=("before", "after"), default="before")
    args = parser.parse_args()
    root = args.root.expanduser().resolve(strict=True)
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    failures = []
    changes = manifest.get("changes")
    if not isinstance(changes, list) or not changes:
        raise ValueError("manifest must contain non-empty changes")
    for change in changes:
        relative = PurePosixPath(change["path"])
        if relative.is_absolute() or ".." in relative.parts or "\\" in str(relative):
            raise ValueError("unsafe manifest path")
        target = root.joinpath(*relative.parts)
        part = root
        unsafe = False
        for component in relative.parts:
            part = part / component
            if part.is_symlink():
                unsafe = True
                break
        expected = change[args.mode]
        if unsafe:
            failures.append({"path": str(relative), "reason": "SYMLINK"})
        elif expected is None:
            if target.exists():
                failures.append({"path": str(relative), "reason": "EXPECTED_ABSENT"})
        elif not target.is_file():
            failures.append({"path": str(relative), "reason": "MISSING_FILE"})
        else:
            raw = target.read_bytes()
            if len(raw) != expected["bytes"] or hashlib.sha256(raw).hexdigest() != expected["sha256"]:
                failures.append({"path": str(relative), "reason": "BYTES_OR_SHA_DRIFT"})
    print(json.dumps({"status": "PASS" if not failures else "DRIFT_STOP", "mode": args.mode,
                      "checked": len(changes), "failures": failures, "writes": 0}, ensure_ascii=False))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
