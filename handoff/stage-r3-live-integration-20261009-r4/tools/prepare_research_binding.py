#!/usr/bin/env python3
"""Prepare one reviewed R3 read binding; write only a new isolated output tree."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

sys.dont_write_bytecode = True
CURRENT_API_APP_SHA256 = "5d344dfe902db37f81e06d1d401e9a7e20ae910d8f7647b732ae2b3ba4f019e5"
REVIEWED_AFTER_SHA256 = {
    "apps/api/v35_api/app.py": "a51b927e98e23ccdd33a849644abfa544232809aab29c2e7223969cc2308d0b8",
    "stage_center/consumer.py": "16f004edb60ab256993f02ec4df36caa5d2cb3aa55bff643834c3119ec86d207",
    "stage_center/execution_evidence.py": "1be96e736fda2863f6f8ff2315e8879a98499bbd30f5a911b46423c4dc6f094b",
    "stage_center/research_read_binding.py": "c33a1452df34c7dcc7fc96e61b1177079c54c467164b7cb957d773f2d2e0ba05",
}
_APP = "apps/api/v35_api/app.py"
_JSON = "stage_center/approved_research_read.json"
_SIDECAR = "stage_center/approved_research_read.sha256"
_FLAGS = {"RESEARCH_ONLY": True, "production_allowed": False,
          "buy_gate_updated": False, "orders_sent": False}


class PreparationError(ValueError):
    pass


def _check(condition, code):
    if not condition:
        raise PreparationError(code)


def _path(value, *, directory=False):
    path = Path(value).expanduser()
    _check(path.is_absolute() and ".." not in path.parts, "ABSOLUTE_PATH_REQUIRED")
    _check(not any(item.is_symlink() for item in (path, *path.parents)), "SYMLINK_PATH_REJECTED")
    if directory:
        _check(path.is_dir(), "DIRECTORY_MISSING")
    return path


def _read(path):
    path = _path(path)
    before = path.lstat()
    _check(stat.S_ISREG(before.st_mode) and before.st_size <= 8 * 1024 * 1024, "REGULAR_FILE_REQUIRED")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    try:
        actual = os.fstat(fd)
        _check((actual.st_dev, actual.st_ino) == (before.st_dev, before.st_ino)
               and stat.S_ISREG(actual.st_mode), "SOURCE_CHANGED_DURING_OPEN")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            raw = stream.read(8 * 1024 * 1024 + 1)
        after = os.fstat(fd)
        _check(len(raw) <= 8 * 1024 * 1024 and
               (actual.st_size, actual.st_mtime_ns) == (after.st_size, after.st_mtime_ns), "SOURCE_CHANGED_DURING_READ")
    finally:
        os.close(fd)
    _path(path)
    return raw


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _json(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def _inside(path, root):
    return path == root or root in path.parents


def _history_observation(root):
    latest = root / "selection_latest.json"
    runs = root / "selection_runs"
    _path(runs, directory=True)
    dates = sorted(item.name for item in runs.iterdir()
                   if len(item.name) == 8 and item.name.isdigit() and not item.is_symlink() and item.is_dir())
    return {"root": str(root), "selection_dates": dates, "selection_date_count": len(dates),
            "selection_latest_sha256": _sha(_read(latest))}


_BUILD = r'''
import importlib, json, sys, types
from pathlib import Path
sys.dont_write_bytecode = True
source, after, manifest, history = map(Path, sys.argv[1:])
sys.path.insert(0, str(source))
package = types.ModuleType("stage_center")
package.__path__ = [str(after / "stage_center"), str(source / "stage_center")]
sys.modules["stage_center"] = package
reader = importlib.import_module("stage_center.research_read_binding")
if Path(reader.__file__).absolute() != after / "stage_center/research_read_binding.py":
    raise RuntimeError("READER_MODULE_PATH_MISMATCH")
document = reader.build_research_read_binding(manifest_path=manifest, history_root=history, api_after_root=after)
print(json.dumps(document, ensure_ascii=False, sort_keys=True, allow_nan=False))
'''


def prepare_research_read_binding(*, manifest_path, history_root, api_after_root, api_source_root, output_root):
    """Verify fixed sources/evidence, then emit the two exact candidate delta rows.

    ``api_source_root`` is the unchanged current API tree used for original
    helper imports. ``api_after_root`` contains the four reviewed R4 API delta
    files. Neither tree, the immutable research run, nor Stage history is edited.
    """
    manifest = _path(manifest_path)
    history = _path(history_root, directory=True)
    after, source = _path(api_after_root, directory=True), _path(api_source_root, directory=True)
    output = _path(output_root)
    _check(not output.exists() and output.parent.is_dir(), "NEW_OUTPUT_WITH_EXISTING_PARENT_REQUIRED")
    for root in (history, source, after, manifest.parent.parent):
        _check(not _inside(output, root) and not _inside(root, output), "OUTPUT_OVERLAPS_READ_SOURCE")
    current_sha = _sha(_read(source / _APP))
    _check(current_sha == CURRENT_API_APP_SHA256, "CURRENT_API_PREIMAGE_SHA_MISMATCH")
    observed = {name: _sha(_read(after / name)) for name in REVIEWED_AFTER_SHA256}
    _check(observed == REVIEWED_AFTER_SHA256, "REVIEWED_API_AFTER_SHA_MISMATCH")
    for name in (_JSON, _SIDECAR):
        _check(not os.path.lexists(source / name) and not os.path.lexists(after / name), "BINDING_PREIMAGE_MUST_BE_ABSENT")
    history_before = _history_observation(history)
    command = [sys.executable, "-B", "-c", _BUILD, str(source), str(after), str(manifest), str(history)]
    child = subprocess.run(command, cwd=after, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                           capture_output=True, text=True)
    if child.returncode:
        # Preserve exact execution failure locally without printing a path-rich
        # traceback through an API endpoint. The CLI caller receives the reason.
        last = child.stderr.strip().splitlines()[-1] if child.stderr.strip() else "NO_CHILD_ERROR_DETAIL"
        raise PreparationError("BINDING_VERIFICATION_FAILED:" + last)
    try:
        document = json.loads(child.stdout)
    except (ValueError, TypeError) as error:
        raise PreparationError("BINDING_VERIFIER_OUTPUT_INVALID") from error
    _check(isinstance(document, dict) and document.get("schema_version") == "stage_center.approved_research_read_binding.v1",
           "BINDING_SCHEMA_INVALID")
    for root in (Path(document["candidate_source_manifest_path"]).parent,
                 Path(document["source_map_path"]).parent):
        _check(not _inside(output, root) and not _inside(root, output), "OUTPUT_OVERLAPS_READ_SOURCE")
    _check(_sha(_read(source / _APP)) == current_sha
           and {name: _sha(_read(after / name)) for name in observed} == observed
           and _history_observation(history) == history_before, "READ_INPUT_CHANGED_DURING_PREPARATION")
    config_raw = _json(document)
    sidecar_raw = (_sha(config_raw) + "\n").encode("ascii")
    files = [{"path": name, "before_sha256": None, "after_sha256": _sha(raw),
              "before_mode": None, "after_mode": "0644"}
             for name, raw in ((_JSON, config_raw), (_SIDECAR, sidecar_raw))]
    proof = {
        "schema_version": "V4_STAGE_RESEARCH_READ_PREPARATION_V1", "status": "PREPARED_NOT_DEPLOYED",
        "files": files, "output_root": str(output), "history": history_before,
        "history_root_preserved": True, "history_latest_unchanged_during_preparation": True,
        "api_source_root": str(source), "current_api_app_sha256": current_sha,
        "api_after_root": str(after), "reviewed_api_after_sha256": observed,
        "binding_sha256": _sha(config_raw), "binding_evidence": document,
        "generator_sha256": _sha(_read(Path(__file__).absolute())),
        "preparation_scope": "PINNED_MANIFEST_OWNER_HISTORY_ORIGINAL_SELECTION_STORE_READ_ONLY",
        "candidate_preparation_only": True, "integrated": False, "deployed": False,
        "natural_verified": False, "execution_verified": False, **_FLAGS,
    }
    output.mkdir(mode=0o755)
    (output / "stage_center").mkdir(mode=0o755)
    for name, raw in ((_JSON, config_raw), (_SIDECAR, sidecar_raw), ("PREPARATION_PROOF.json", _json(proof))):
        target = output / name
        with target.open("xb") as stream:
            stream.write(raw)
        target.chmod(0o644)
        _check(_read(target) == raw, "GENERATED_FILE_READBACK_MISMATCH")
    return {"status": proof["status"], "output_root": str(output), "files": files,
            "proof_path": str(output / "PREPARATION_PROOF.json"),
            "proof_sha256": _sha(_read(output / "PREPARATION_PROOF.json"))}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest-path", required=True)
    parser.add_argument("--history-root", required=True)
    parser.add_argument("--api-after-root", required=True)
    parser.add_argument("--api-source-root", required=True)
    parser.add_argument("--output-root", required=True)
    args = parser.parse_args(argv)
    try:
        result = prepare_research_read_binding(**vars(args))
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({"status": "PREPARATION_FAILED", "error": str(error), "deployed": False,
                          "natural_verified": False, **_FLAGS}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
