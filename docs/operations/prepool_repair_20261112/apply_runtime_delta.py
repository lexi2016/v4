"""Apply/reverse only the two reviewed inline deltas on an inactive Main clone.

No manifest, owner, service, data, gate, or permission is changed here. The
controller owns release assembly, independent review, activation and backfill.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import tempfile
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-root", required=True, type=Path)
    parser.add_argument("--action", choices=("check", "apply", "verify", "rollback"), default="check")
    args = parser.parse_args()
    delta = json.loads(Path(__file__).with_name("RUNTIME_DELTA.json").read_text())
    changes = []
    for relative, change in delta["files"].items():
        target = args.app_root / relative
        raw = target.read_bytes()
        reverse = args.action in {"verify", "rollback"}
        expected = change["after_sha256" if reverse else "before_sha256"]
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError(f"PREIMAGE_SHA_MISMATCH:{relative}")
        result = raw.decode("utf-8")
        edits = list(reversed(change["edits"])) if reverse else change["edits"]
        for edit in edits:
            before, after = (edit["after"], edit["before"]) if reverse else (edit["before"], edit["after"])
            if result.count(before) != 1:
                raise ValueError(f"EXACT_EDIT_PREIMAGE_MISMATCH:{relative}")
            result = result.replace(before, after, 1)
        after_bytes = result.encode("utf-8")
        expected_after = change["before_sha256" if reverse else "after_sha256"]
        if hashlib.sha256(after_bytes).hexdigest() != expected_after:
            raise ValueError(f"POSTIMAGE_SHA_MISMATCH:{relative}")
        compile(result, str(target), "exec")
        changes.append((target, after_bytes, stat.S_IMODE(target.stat().st_mode)))
    if args.action in {"apply", "rollback"}:
        if args.app_root.resolve() == Path(delta["origin_app_root"]).resolve():
            raise ValueError("ORIGIN_MAIN_IS_READ_ONLY:use_an_inactive_clone")
        for target, content, mode in changes:
            descriptor, temporary = tempfile.mkstemp(prefix=".prepool-delta-", dir=target.parent)
            try:
                with os.fdopen(descriptor, "wb") as output:
                    output.write(content)
                    output.flush()
                    os.fsync(output.fileno())
                os.chmod(temporary, mode)
                os.replace(temporary, target)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
    print(json.dumps({"status": "PASS", "action": args.action, "files": list(delta["files"]),
        "RESEARCH_ONLY": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False}))


if __name__ == "__main__":
    main()
