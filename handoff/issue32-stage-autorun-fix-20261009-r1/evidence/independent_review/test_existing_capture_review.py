"""Independent exact-date reuse probes; synthetic imports/data, never a runtime canary."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tests'))
from hk_prepare_support import file_bytes, load_ensure, load_master, publish


@pytest.mark.parametrize('owner', ['actual', 'canonical'])
@pytest.mark.parametrize('capture', [
    '2026-10-09T00:01:00+08:00',
    '2026-09-30T17:00:00+08:00',
    '2026-10-08T10:00:00',
])
def test_existing_master_reuse_rejects_wrong_or_unzoned_capture(monkeypatch, tmp_path, owner, capture):
    master = load_master(monkeypatch, owner)
    store = tmp_path / 'store'
    publish(master, store, captured_at=capture)
    before = file_bytes(store)
    ensure = load_ensure(monkeypatch, owner, master)
    with pytest.raises(ValueError):
        ensure.ensure_hk_security_master(
            store_root=store, universe_root=tmp_path / 'universe',
            shared_package_root=tmp_path, trade_date='20261008',
            futu_python=tmp_path / 'python', reuse_only=True,
        )
    assert file_bytes(store) == before, 'Rejected reuse must leave original evidence unchanged'
