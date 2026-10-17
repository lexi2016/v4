#!/usr/bin/env python3
"""Invoke only the pinned runtime release-identity validator."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import plistlib
import subprocess
import sys

from prepare_candidate import (
    CANDIDATE_RELEASE,
    LIVE_PLIST,
    SOURCE_RELEASE,
    STAGED_PLIST,
)


PYTHON = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python")
VALIDATOR_CODE = r'''
import json
import infrastructure.scheduling.dispatcher as dispatcher
print("module_file=" + dispatcher.__file__)
print("module_cached=" + str(dispatcher.__cached__))
if "entry_count" not in dispatcher.validate_release_identity.__code__.co_consts:
    raise RuntimeError("LOADED_VALIDATOR_DOES_NOT_CHECK_ENTRY_COUNT")
try:
    print("identity=" + json.dumps(dispatcher.validate_release_identity(), sort_keys=True))
except Exception as exc:
    print("raised=" + type(exc).__name__ + " " + str(exc))
    raise
'''


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", required=True, choices=("source", "candidate"))
    target = parser.parse_args().target
    if target == "source":
        app = SOURCE_RELEASE / "app"
        plist_path = LIVE_PLIST
        expected_error = "RELEASE_INVENTORY_MISMATCH"
    else:
        app = CANDIDATE_RELEASE / "app"
        plist_path = STAGED_PLIST
        expected_error = ""

    plist = plistlib.loads(plist_path.read_bytes())
    env = os.environ.copy()
    env.update({key: str(value) for key, value in plist["EnvironmentVariables"].items()})
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONNOUSERSITE"] = "1"
    result = subprocess.run(
        [str(PYTHON), "-B", "-c", VALIDATOR_CODE],
        cwd=app,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    print(f"target={target}")
    print(f"python={PYTHON}")
    print(f"cwd={app}")
    print(result.stdout, end="")
    if expected_error:
        return 0 if result.returncode != 0 and expected_error in result.stdout else 1
    return 0 if result.returncode == 0 and "identity={" in result.stdout else 1


if __name__ == "__main__":
    sys.exit(main())
