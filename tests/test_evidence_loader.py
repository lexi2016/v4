from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from apps.api.v4_api.evidence import loader

# Oracle copied from the pre-migration literal in apps/api/v4_api/app.py.
ORACLE = {
    ("20260924", "STAGE_1445_1500"): "d0c64a11d1b833ace8ae0a6105ea04e27d15bb2cf694f7dfdc08900f56213753",
    ("20260930", "STAGE_0930_0935"): "ca23560921e64600f616d1db1a69feb504e63d0ccdd578232babe5212c149cc4",
    ("20260930", "STAGE_0935_0940"): "522d6515dd35add084793c1f01d1c8bb1fd62b3d263e7d54359590549ef4db59",
    ("20260930", "STAGE_0940_0945"): "6cf31b1fdb49737a73e8a9657b94c6f1ff4de9b8f3c398eccb59e37db42b0194",
    ("20260930", "STAGE_0945_1030"): "3316c2abe88388e6faf59c314b2801a2fc8d93b11cbe68826303e18a13600a92",
    ("20260930", "STAGE_1300_1315"): "42ad12f2953b2cbae8fcc9594067af54b01e15a7af2134ecc761246c7ae656fe",
    ("20260930", "STAGE_1445_1500"): "2821b24a4be12d0aa199d1e8e60d8cc7a5a1367211e67cbb9c677da72b4a8888",
    ("20260930", "STAGE_1545_1555"): "6e63ea8d3ebf1839a53e3c738f494a6ba9d622447d6d86d6b2cfdda5fa2c33d8",
    ("20261005", "STAGE_0930_0935"): "e9318ba27b8fa90b2f0d03c0fa52f6171676ee88b4e42607ed8567740ceb572d",
    ("20261005", "STAGE_0935_0940"): "84ef7159af547b908f220c2f8dddeb226a61c2f882c504e0f79b9629e3857d86",
    ("20261005", "STAGE_0940_0945"): "843f65f610dff7be1c223d7e6a8ff4e6bb7d90b7a42f99c671946667b750c68b",
    ("20261005", "STAGE_0945_1030"): "cd50cd6c9492de8d5e0bc9893e1dc8639a4b05ffc4164f7818d935c354b158b8",
    ("20261005", "STAGE_1300_1315"): "c010adbfd20d70a8e742af04b19f819ac96edcfe8b936fd529f7a6d40e94e8c9",
    ("20261005", "STAGE_1445_1500"): "1665f1e3d7bc06efa1cfc88844e8ca777ed262aa11b6c1353cd35e0464f97ff1",
    ("20261005", "STAGE_1545_1555"): "d71ab63d6a1059b6ca23561c1c042a5c833c7f82fe64f74abefaca4ffc0f37e6",
}


def test_dataset_matches_pre_migration_oracle():
    loaded = loader.tuple_keyed("hk_r8_observation_mode")
    assert loaded == ORACLE
    assert all(isinstance(key, tuple) and len(key) == 2 for key in loaded)
    assert set(loaded) == set(ORACLE)


def test_hit_miss_and_type_semantics_match_the_literal():
    loaded = loader.tuple_keyed("hk_r8_observation_mode")
    assert loaded.get(("20260930", "STAGE_0930_0935")) == ORACLE[("20260930", "STAGE_0930_0935")]
    assert loaded.get(("20260930", "STAGE_0925")) is None
    with pytest.raises(TypeError):
        loaded.get(["20260930", "STAGE_0930_0935"])  # list keys stay unhashable, as before


def test_unknown_dataset_is_rejected():
    with pytest.raises(loader.EvidenceDatasetError) as error:
        loader.tuple_keyed("not_a_dataset")
    assert "not_in_manifest" in str(error.value)


def _staged(tmp_path: Path, mutate, *, keep_sha: bool = False) -> None:
    source = loader.EVIDENCE_DIR
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    data = json.loads((source / "hk_r8_observation_mode.json").read_text(encoding="utf-8"))
    mutate(manifest, data)
    (tmp_path / "hk_r8_observation_mode.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if not keep_sha:
        digest = hashlib.sha256((tmp_path / "hk_r8_observation_mode.json").read_bytes()).hexdigest()
        manifest["datasets"][0]["sha256"] = digest
    (tmp_path / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _point_at(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(loader, "EVIDENCE_DIR", tmp_path)
    monkeypatch.setattr(loader, "MANIFEST_PATH", tmp_path / "manifest.json")
    monkeypatch.setattr(loader, "_manifest_cache", None)


def test_sha_mismatch_is_rejected(tmp_path: Path, monkeypatch):
    def mutate(manifest, data):
        manifest["datasets"][0]["sha256"] = "0" * 64
    _staged(tmp_path, mutate, keep_sha=True)
    _point_at(tmp_path, monkeypatch)
    with pytest.raises(loader.EvidenceDatasetError) as error:
        loader.tuple_keyed("hk_r8_observation_mode")
    assert "sha256" in str(error.value)


def test_entry_count_mismatch_is_rejected(tmp_path: Path, monkeypatch):
    def mutate(manifest, data):
        manifest["datasets"][0]["entry_count"] = 1
    _staged(tmp_path, mutate, keep_sha=True)
    _point_at(tmp_path, monkeypatch)
    with pytest.raises(loader.EvidenceDatasetError) as error:
        loader.tuple_keyed("hk_r8_observation_mode")
    assert "entry_count" in str(error.value)


# --- C2: HK afterfact R9 stage rows -----------------------------------------

ORACLE_PATH = Path("tests/fixtures/evidence_oracle/hk_afterfact_r9_stage_rows.json")


def _untag(value):
    if isinstance(value, dict) and value.get("__type__") == "tuple":
        return tuple(_untag(item) for item in value["items"])
    if isinstance(value, dict) and value.get("__type__") == "list":
        return [_untag(item) for item in value["items"]]
    if isinstance(value, dict) and value.get("__type__") == "dict":
        return {key: _untag(item) for key, item in value["items"].items()}
    return value


def _assert_same_types(left, right, path="") -> None:
    assert type(left) is type(right), f"{path}: {type(left)} != {type(right)}"
    if isinstance(left, dict):
        assert set(left) == set(right), path
        for key in left:
            _assert_same_types(left[key], right[key], f"{path}.{key}")
    elif isinstance(left, (tuple, list)):
        assert len(left) == len(right), path
        for index, (a, b) in enumerate(zip(left, right)):
            _assert_same_types(a, b, f"{path}[{index}]")


def test_r9_stage_rows_match_the_type_tagged_oracle():
    oracle = json.loads(ORACLE_PATH.read_text(encoding="utf-8"))
    expected = tuple(_untag(row) for row in oracle["rows"])
    loaded = loader.row_dicts("hk_afterfact_r9_stage_rows")
    assert loaded == expected
    _assert_same_types(loaded, expected)


def test_r9_stage_rows_restore_tuple_and_dict_columns():
    loaded = loader.row_dicts("hk_afterfact_r9_stage_rows")
    assert len(loaded) == 87
    assert len(loaded[0]) == 26
    for row in loaded:
        assert isinstance(row["missing_codes"], tuple)
        assert isinstance(row["missing_evidence_markers"], tuple)
        assert isinstance(row["missing_reason_by_code"], dict)


def test_r9_stage_rows_reject_unexpected_column(tmp_path: Path, monkeypatch):
    def mutate(manifest, data):
        data["rows"][0]["__extra__"] = "x"
        data["rows"] = [data["rows"][0]]

    _staged_rows(tmp_path, mutate)
    _point_at(tmp_path, monkeypatch)
    with pytest.raises(loader.EvidenceDatasetError) as error:
        loader.row_dicts("hk_afterfact_r9_stage_rows")
    assert "row_columns" in str(error.value)


def _staged_rows(tmp_path: Path, mutate) -> None:
    source = loader.EVIDENCE_DIR
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    data = json.loads((source / "hk_afterfact_r9_stage_rows.json").read_text(encoding="utf-8"))
    mutate(manifest, data)
    (tmp_path / "hk_afterfact_r9_stage_rows.json").write_text(
        json.dumps(data, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
    )
    digest = hashlib.sha256((tmp_path / "hk_afterfact_r9_stage_rows.json").read_bytes()).hexdigest()
    for entry in manifest["datasets"]:
        if entry["name"] == "hk_afterfact_r9_stage_rows":
            entry["sha256"] = digest
            entry["entry_count"] = len(data["rows"])
    (tmp_path / "manifest.json").write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
