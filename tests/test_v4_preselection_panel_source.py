"""Exercise V4 display fallback through the real panel reader and owner bindings."""

import importlib.util
import json
import os
from pathlib import Path
import sys
from types import ModuleType

import pyarrow as pa
import pytest

from ops import research_panel_logical as logical
from ops import research_panel_qfq as owner
from ops import research_storage_pair as pair
from ops import research_storage_retention as retention


REQUEST_DATE = "20261111"
NAME_DATE = "20261030"
OWNER_NAME = "正式面板名称"
TRIAL_NAME = "未经核验名称"


@pytest.fixture
def service(monkeypatch):
    for key in ("V4_STORAGE_PAIR_ROOT", "V4_STORAGE_PAIR_DATA_ROOT"):
        monkeypatch.delenv(key, raising=False)

    # This source checkout lacks the release overlay's entity filter. The
    # exercised display projection has no dependency on filter semantics.
    contract_name = "contracts.a_share_entity_filter"
    if importlib.util.find_spec(contract_name) is None:
        dependency = ModuleType(contract_name)
        dependency.FILTER_RULE_VERSION = "test"

        def unused_filter(*args, **kwargs):
            pytest.fail("the panel name projection must not invoke the pool filter")

        dependency.filter_pool_rows = unused_filter
        monkeypatch.setitem(sys.modules, contract_name, dependency)
    path = Path(__file__).resolve().parents[1] / "apps/api/v4_api/preselection_service.py"
    spec = importlib.util.spec_from_file_location("preselection_service_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _names(name):
    return pa.table({
        "trade_date": [NAME_DATE] * 100,
        "ts_code": [f"{index:06d}.SZ" for index in range(100)],
        "name": [name] * 100,
    })


def _publish(tmp_path, monkeypatch, layout="parquet"):
    root = tmp_path.resolve()
    monkeypatch.setenv("V4_A_SHARE_HISTORY_DATA_ROOT", str(root))
    pointers = pair.pointers(root)
    cache = owner.input_path(root).parent
    cache.mkdir(parents=True)
    manifest = root / "generation.json"
    contract = dict(schema="a_share_qfq_panel_v1", generation_id="owner-generation",
                    input_sha256="b" * 64, snapshot_file_sha256="c" * 64,
                    generation_manifest_path=str(manifest), asof_date=int(REQUEST_DATE),
                    price_basis="QFQ_ASOF", volume_basis="QFQ_EVENT_VOLUME", convention="fixture")
    rows = _names(OWNER_NAME)
    metadata = {logical.META: json.dumps(contract).encode()}
    candidates = {}
    for role, pointer in pointers.items():
        pointer.parent.mkdir()
        previous = root / f"previous_{role}.parquet"
        logical.physical.write_table(rows, previous, compression="NONE")
        pointer.write_text(f"{previous}\n")
        candidates[role] = root / f"accepted_{role}.{layout}"
        if layout == "logical":
            candidates[role].write_bytes(logical.anchor_bytes(
                rows.schema.with_metadata(metadata), [logical.descriptor(previous)], rows=rows.num_rows))
        else:
            logical.physical.write_table(rows.replace_schema_metadata(metadata), candidates[role])

    owner._json(manifest, {
        **contract,
        "candidates": {role: str(path) for role, path in candidates.items()},
        "candidate_sha256": {role: owner.sha(path) for role, path in candidates.items()},
    })
    journal = cache / "qfq_publication.json"
    with owner.publication_lock(root):
        owner.publish_pair(pointers, candidates, {role: path.read_bytes() for role, path in pointers.items()}, journal)
        owner._json(cache / "qfq_expected_current.json", owner.baseline_binding(pointers))
    return root, pointers, candidates, manifest, journal


def _display_row(service):
    request = {"rows": [{"market": "A", "code": "000001"}]}
    return service._apply_v4_display_projection(request, REQUEST_DATE)["rows"][0]


def _assert_owner_name(service):
    row = _display_row(service)
    assert row["name"] == row["display_name"] == OWNER_NAME
    assert row["name_resolution"] == {
        "status": "HISTORICAL_SELECTOR_PANEL_NAME", "source_date": NAME_DATE,
    }


def _assert_no_fallback(service):
    assert _display_row(service) == {"market": "A", "code": "000001"}


def test_display_rejects_task_local_selector_redirect(service, tmp_path, monkeypatch):
    root, pointers, *_ = _publish(tmp_path, monkeypatch)
    trial = root / "trial_top200.parquet"
    logical.physical.write_table(_names(TRIAL_NAME), trial)
    pointers["selector"].write_text(f"{trial}\n")
    _assert_no_fallback(service)


@pytest.mark.parametrize("layout", ["parquet", "logical"])
def test_display_uses_owner_accepted_selector(service, tmp_path, monkeypatch, layout):
    _publish(tmp_path, monkeypatch, layout)
    _assert_owner_name(service)


def test_cached_names_cannot_bypass_changed_selector_sha(service, tmp_path, monkeypatch):
    _, _, candidates, _, _ = _publish(tmp_path, monkeypatch)
    selector = candidates["selector"]
    original = selector.stat()
    metadata = logical.physical.read_schema(selector).metadata
    _assert_owner_name(service)
    logical.physical.write_table(_names(TRIAL_NAME).replace_schema_metadata(metadata), selector)
    os.utime(selector, ns=(original.st_atime_ns, original.st_mtime_ns))
    _assert_no_fallback(service)


@pytest.mark.parametrize("broken_binding", ["producer_manifest", "pointer_sha", "publication_pending"])
def test_legacy_owner_acceptance_fails_closed(service, tmp_path, monkeypatch, broken_binding):
    _, pointers, _, manifest, journal = _publish(tmp_path, monkeypatch)
    _assert_owner_name(service)
    if broken_binding == "producer_manifest":
        value = json.loads(manifest.read_bytes())
        value["candidate_sha256"]["selector"] = "0" * 64
        owner._json(manifest, value)
    elif broken_binding == "pointer_sha":
        pointer = pointers["selector"]
        pointer.write_bytes(pointer.read_bytes() + b"\n")
    else:
        owner._json(journal, {"status": "PREPARED"})
    _assert_no_fallback(service)


def test_current_pair_wins_and_unavailable_pair_cannot_fall_back(service, tmp_path, monkeypatch):
    root, pointers, candidates, _, _ = _publish(tmp_path, monkeypatch, "logical")
    pair_root = root / "pair"
    with owner.publication_lock(root):
        pair.commit(pair_root, root, candidates)
    monkeypatch.setenv("V4_STORAGE_PAIR_ROOT", str(pair_root))
    monkeypatch.setenv("V4_STORAGE_PAIR_DATA_ROOT", str(root))
    legacy = pointers["selector"].read_bytes()
    pointers["selector"].write_text("/unaccepted_legacy_selector.parquet\n")
    _assert_owner_name(service)

    pointers["selector"].write_bytes(legacy)
    monkeypatch.setenv("V4_STORAGE_PAIR_ROOT", str(root / "unavailable_pair"))
    _assert_no_fallback(service)


@pytest.mark.parametrize("use_pair", [False, True], ids=["legacy", "pair"])
@pytest.mark.parametrize("clear_display_cache", [False, True], ids=["warm", "cold"])
def test_logical_selector_block_byte_drift_is_rejected(
    service, tmp_path, monkeypatch, use_pair, clear_display_cache,
):
    root, _, candidates, _, _ = _publish(tmp_path, monkeypatch, "logical")
    if use_pair:
        pair_root = root / "pair"
        with owner.publication_lock(root):
            pair.commit(pair_root, root, candidates)
        monkeypatch.setenv("V4_STORAGE_PAIR_ROOT", str(pair_root))
        monkeypatch.setenv("V4_STORAGE_PAIR_DATA_ROOT", str(root))
    _assert_owner_name(service)

    source_block = root / "previous_selector.parquet"
    original = logical.stamp(source_block)
    logical.physical.write_table(_names(TRIAL_NAME), source_block, compression="NONE")
    os.utime(source_block, ns=(source_block.stat().st_atime_ns, original["mtime_ns"]))
    assert logical.stamp(source_block) == original
    if clear_display_cache:
        service._A_NAME_CACHE.clear()
    _assert_no_fallback(service)


def test_unchanged_logical_selector_blocks_are_hashed_once(service, tmp_path, monkeypatch):
    root, _, _, _, _ = _publish(tmp_path, monkeypatch, "logical")
    original_digest = retention.digest
    reads = []

    def record_digest(path):
        reads.append(path)
        return original_digest(path)

    monkeypatch.setattr(retention, "digest", record_digest)
    _assert_owner_name(service)
    _assert_owner_name(service)
    assert reads == [root / "previous_selector.parquet"]


def test_large_logical_closure_never_restreams_unchanged_blocks(service, tmp_path, monkeypatch):
    root = tmp_path.resolve()
    descriptor_count = 513
    paths = [root / f"block_{index}" for index in range(descriptor_count)]
    descriptors = []
    for path in paths:
        path.write_bytes(b"test block")
        descriptors.append(dict(path=str(path), stat=logical.stamp(path), sha256=retention.digest(path)))
    monkeypatch.setattr(logical, "closure", lambda _: descriptors)
    original_digest = retention.digest
    reads = []

    def record_digest(path):
        reads.append(path)
        return original_digest(path)

    monkeypatch.setattr(retention, "digest", record_digest)
    first = service._verified_name_blocks(root / "anchor")
    assert service._verified_name_blocks(root / "anchor") == first
    assert reads == paths
