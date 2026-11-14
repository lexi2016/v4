"""Exercise the narrowly patched storage and historical attestation seams."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tempfile


def must_fail(function, exception, code):
    try:
        function()
    except exception as error:
        assert str(error) == code, error
        return
    raise AssertionError("Expected " + code)


def check_store():
    from v4.manager_workbench.contracts import canonical, digest
    from v4.manager_workbench.store import StorageConflict, StorageUnavailable, WorkbenchStore

    with tempfile.TemporaryDirectory(prefix="v4-rollback-check-") as directory:
        owner = WorkbenchStore(Path(directory).resolve())
        body = {"context": {}, "batches": []}
        sha = digest(body)
        owner.save_checkpoint("legacy", "LOAD_INPUTS", body)
        assert owner.load_input(sha) is None
        owner.reuse_input_checkpoint("legacy", "legacy", sha, body)
        checkpoint = owner.root / "checkpoints/legacy/LOAD_INPUTS.json"
        assert checkpoint.read_bytes() == canonical(body)
        companion = owner.root / "input_snapshots" / (sha + ".json")
        assert companion.read_bytes() == canonical(body)

        owner.reuse_input_checkpoint("child", "legacy", sha, body)
        assert owner.load_input_checkpoint("child") == (body, sha)
        before = owner.root / "checkpoints/child/LOAD_INPUTS.json"
        identity = before.stat()
        owner.reuse_input_checkpoint("child", "child", sha, body)
        assert before.stat() == identity
        conflicting = {"context": {"changed": True}, "batches": []}
        owner.save_checkpoint("other", "LOAD_INPUTS", conflicting)
        must_fail(lambda: owner.reuse_input_checkpoint("other", "legacy", sha, body),
                  StorageConflict, "INPUT_CHECKPOINT_COLLISION")
        companion.unlink()
        must_fail(lambda: owner.load_input_checkpoint("child"), StorageUnavailable,
                  "INPUT_SNAPSHOT_MISSING")
        must_fail(lambda: owner.reuse_input_checkpoint("child", "child", sha, body),
                  StorageUnavailable, "INPUT_SNAPSHOT_MISSING")
        assert not companion.exists()


def check_historical_manifest(config_path):
    from infrastructure.manager_input_attestation import PublicationError, _MAIN_RESEARCH_FILES, _release_manifest

    config = json.loads(config_path.read_bytes())
    history = config["research_historical_owner_bindings"]
    corrected = next(item for item in history if item["release_id"] == "v4-v192-source-binding-20261112-r3-main")

    def manifest(binding, *, historical=False):
        return _release_manifest(Path(binding["app_root"]), binding["release_id"],
                                 binding["manifest_sha256"], _MAIN_RESEARCH_FILES,
                                 manifest_path=binding.get("manifest_path"), historical=historical)

    for binding in history:
        result = manifest(binding, historical=True)
        assert result["release_id"] == binding["release_id"]
    assert len(manifest(corrected, historical=True)["application_inventory"]["entries"]) == 1039
    must_fail(lambda: manifest(corrected), PublicationError, "RESEARCH_RELEASE_INVENTORY_INVALID")
    must_fail(lambda: manifest({**corrected, "manifest_sha256": "a" * 64}, historical=True),
              PublicationError, "RESEARCH_RELEASE_MANIFEST_SHA_MISMATCH")
    must_fail(lambda: manifest({**corrected, "release_id": "unrelated"}, historical=True),
              PublicationError, "RESEARCH_RELEASE_IDENTITY_MISMATCH")
    for binding in (config["research_owner_binding"], config["research_transition_owner_binding"]):
        assert manifest(binding)["release_id"] == binding["release_id"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("app", type=Path)
    parser.add_argument("check", choices=("store", "stage"))
    args = parser.parse_args()
    sys.path.insert(0, str(args.app))
    if args.check == "store":
        check_store()
    else:
        check_historical_manifest(args.app / "stage_center_tick_config.json")
    print("PASS", args.check, args.app)
