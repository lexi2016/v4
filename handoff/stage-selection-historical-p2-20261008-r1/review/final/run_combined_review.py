"""Independent bounded review: both final candidates plus two existing-read probes.

This changes import paths only inside this synthetic worker. Author source,
harness, identity manifests and prior failure evidence stay unchanged.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import sys


EXPECTED_CLOSE = "59ac7798bcb1d54bbd11bbc61803997f36881a29cd1b82ecb663166791d5e0f2"
EXPECTED_POOL = "9f1606a977d36c063d9c650e54b9861947eb7b692e779837852e3831b7814bef"


def checked_module(module, path: Path, expected_sha: str) -> dict:
    actual_path = Path(module.__file__).resolve()
    assert actual_path == path.resolve(), (actual_path, path)
    raw = actual_path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    assert digest == expected_sha, (actual_path, digest)
    return {"module": module.__name__, "file": str(actual_path),
            "sha256": digest, "bytes": len(raw)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--close-root", type=Path, required=True)
    parser.add_argument("--historical-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    close_root = args.close_root.resolve()
    historical_root = args.historical_root.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(close_root))
    from harness import prepare

    prepare("after")  # Includes the author's full source/support identity checks.
    import infrastructure

    assert "infrastructure.preselection_pool_store" not in sys.modules
    infrastructure.__path__ = [
        str(historical_root / "after/infrastructure"),
        *list(infrastructure.__path__),
    ]
    from infrastructure import preselection_pool_store
    from ops import build_close_review

    loaded = [
        checked_module(preselection_pool_store,
                       historical_root / "after/infrastructure/preselection_pool_store.py",
                       EXPECTED_POOL),
        checked_module(build_close_review,
                       close_root / "after/canonical/ops/build_close_review.py",
                       EXPECTED_CLOSE),
    ]
    assert build_close_review.PreselectionPoolStore is preselection_pool_store.PreselectionPoolStore
    os.environ["ISSUE28_REVIEW_HISTORICAL_ROOT"] = str(historical_root)
    os.environ["ISSUE28_REVIEW_PROBE_OUTPUT"] = str(output)

    import pytest

    pytest_args = [
        "-vv", "-p", "no:cacheprovider", "--tb=short",
        str(close_root / "tests/test_close_source_pit_warning.py"),
        str(Path(__file__).with_name("test_existing_future_artifact_read.py")),
        f"--junitxml={output / 'combined.xml'}",
    ]
    result = int(pytest.main(pytest_args))
    # Recheck the product identities after execution as well.
    checked_module(preselection_pool_store,
                   historical_root / "after/infrastructure/preselection_pool_store.py",
                   EXPECTED_POOL)
    checked_module(build_close_review,
                   close_root / "after/canonical/ops/build_close_review.py",
                   EXPECTED_CLOSE)
    record = {
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "command": [sys.executable, *sys.argv],
        "cwd": str(Path.cwd()), "python": sys.version,
        "executable": sys.executable, "platform": platform.platform(),
        "pytest": importlib.metadata.version("pytest"),
        "pytest_args": pytest_args, "pytest_returncode": result,
        "loaded_candidate_modules": loaded,
        "producer_uses_candidate_pool_class": True,
        "supplied_close_cases_reexecuted": 14,
        "reviewer_authored_existing_read_cases": 2,
        "baseline_comparison_note": "Supplied before_producer comparisons use frozen close code with the new PoolStore; independent read probes explicitly load the exact before PoolStore separately.",
        "scope": "SYNTHETIC_LOCAL_COMBINED_SOURCE_AND_REAL_STORE_READBACK",
        "stage_consumer": "NOT_RUN; original explicit unused-import sentinel",
        "Mac_API_UI_natural_PIT_deploy": "NOT_RUN",
    }
    (output / "COMBINED_RUN.json").write_text(json.dumps(record, indent=2) + "\n")
    return result


if __name__ == "__main__":
    raise SystemExit(main())
