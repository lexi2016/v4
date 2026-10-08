"""Independent synthetic probe: stable bytes do not authorize a new root inode."""
from pathlib import Path
import shutil

import pytest

from stage_center import runner
from test_hk_split_date_identity_closure import (
    TARGET,
    POOL,
    _install,
    _valid_split_pool,
)


@pytest.mark.parametrize("secondary", [False, True])
def test_replaced_root_with_identical_trio_is_rejected(tmp_path, monkeypatch, secondary):
    primary, source, store = _install(tmp_path, _valid_split_pool(), secondary)
    snapshot = store.read_pool_snapshot(TARGET, POOL)
    artifact_path = source / snapshot["artifact_relative"]
    before_bytes = {
        key: (source / snapshot[key]).read_bytes()
        for key in ("artifact_relative", "manifest_relative", "receipt_relative")
    }
    old_inode = source.stat().st_ino
    original_sha = runner._sha
    replaced = False

    def replace_root_after_digest(path):
        nonlocal replaced
        digest = original_sha(path)
        if Path(path) == artifact_path and not replaced:
            replaced = True
            parked = source.with_name(source.name + "-original-inode")
            source.rename(parked)
            shutil.copytree(parked, source)
            assert source.stat().st_ino != old_inode
            assert all((source / snapshot[key]).read_bytes() == raw
                       for key, raw in before_bytes.items())
        return digest

    monkeypatch.setattr(runner, "_sha", replace_root_after_digest)
    with pytest.raises(runner.RunnerError, match="snapshot|trio|identity changed"):
        runner._validate_hk_d1(
            primary, TARGET, preselection_source_root=source if secondary else None
        )
    assert replaced
