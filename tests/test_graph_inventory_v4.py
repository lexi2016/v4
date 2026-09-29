from __future__ import annotations

import copy
import hashlib
import json
import shutil
import sys
from pathlib import Path

import pytest
import ops.migration.graph_inventory_v4 as graph_inventory_v4


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ops.migration.collect_v3_graph_readonly import (  # noqa: E402
    LegacyGraphSafetyError,
    collect_graph_readonly,
)
from ops.migration.graph_inventory_v4 import (  # noqa: E402
    GraphInventoryError,
    _atomic_json_pair,
    _atlas_authority,
    build_inventory_v4,
)


def _write_fake_builder(path: Path, *, mutate_source: bool = False) -> None:
    source_mutation = "source.write_text('tampered', encoding='utf-8')" if mutate_source else ""
    path.write_text(
        f'''\
import argparse
import json
import sys
from pathlib import Path

def publish_runtime_topology(payload, runtime_root, **kwargs):
    Path(runtime_root).mkdir(parents=True, exist_ok=True)
    (Path(runtime_root) / 'MUTATION').write_text('legacy write', encoding='utf-8')

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--date')
    parser.add_argument('--api-base')
    parser.add_argument('--output-dir')
    args = parser.parse_args()
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    if not sys.dont_write_bytecode:
        raise AssertionError('bytecode protection released before main')
    (out / 'bytecode_guard.json').write_text(json.dumps({{'bytecode_writes_disabled': sys.dont_write_bytecode}}), encoding='utf-8')
    source = Path(__file__).with_name('source.py')
    {source_mutation}
    graph = {{
        'schema_version': 'v3_current_script_task_graph.v1',
        'counts': {{'python_parse_errors': 0, 'graph_nodes': 1, 'graph_edges': 0}},
        'graph': {{'nodes': [{{'id': 'node:one'}}], 'edges': []}},
        'findings': [],
    }}
    (out / f'v3_current_script_task_graph_{{args.date}}.json').write_text(json.dumps(graph), encoding='utf-8')
    (out / f'v3_current_script_task_graph_{{args.date}}.mmd').write_text('graph TD', encoding='utf-8')
    (out / f'V3_CURRENT_SCRIPT_TASK_GRAPH_{{args.date}}.md').write_text('# graph', encoding='utf-8')
    publish_runtime_topology({{'nodes': [{{'id': 'node:one'}}]}}, Path(__file__).parents[1] / '.runtime' / 'v3_runtime_graph' / 'topology')
    return 0
''',
        encoding="utf-8",
    )


def test_collector_sinks_legacy_topology_and_fails_closed_on_sentinel_drift(tmp_path: Path) -> None:
    legacy_root = tmp_path / "legacy"
    builder = legacy_root / "_ops" / "builder.py"
    builder.parent.mkdir(parents=True)
    source = builder.with_name("source.py")
    source.write_text("SOURCE = 1\n", encoding="utf-8")
    _write_fake_builder(builder)
    output = tmp_path / "evidence" / "normal"

    receipt = collect_graph_readonly(
        legacy_root=legacy_root,
        builder_path=builder,
        output_dir=output,
        date="20260802",
        atlas_source_paths=[source],
        expected_builder_sha256=hashlib.sha256(builder.read_bytes()).hexdigest(),
        evidence_root=tmp_path / "evidence",
    )

    assert receipt["success"] is True
    assert receipt["topology_sink"]["invoked"] is True
    assert receipt["safety"]["bytecode_writes_disabled"] is True
    assert json.loads((output / "bytecode_guard.json").read_text(encoding="utf-8"))["bytecode_writes_disabled"] is True
    assert not (legacy_root / ".runtime" / "v3_runtime_graph" / "topology").exists()
    assert not (builder.parent / "__pycache__").exists()
    assert (output / "collection_receipt.json").is_file()
    with pytest.raises(LegacyGraphSafetyError, match="OUTPUT_DIR_NOT_FRESH"):
        collect_graph_readonly(
            legacy_root=legacy_root,
            builder_path=builder,
            output_dir=output,
            date="20260802",
            atlas_source_paths=[source],
            expected_builder_sha256=hashlib.sha256(builder.read_bytes()).hexdigest(),
            evidence_root=tmp_path / "evidence",
        )

    _write_fake_builder(builder, mutate_source=True)
    failed_output = tmp_path / "evidence" / "tampered"
    with pytest.raises(LegacyGraphSafetyError, match="LEGACY_SENTINEL_CHANGED"):
        collect_graph_readonly(
            legacy_root=legacy_root,
            builder_path=builder,
            output_dir=failed_output,
            date="20260802",
            atlas_source_paths=[source],
            expected_builder_sha256=hashlib.sha256(builder.read_bytes()).hexdigest(),
            evidence_root=tmp_path / "evidence",
        )
    assert not (failed_output / "collection_receipt.json").exists()


def test_inventory_v4_is_deterministic_and_rejects_structural_identity_drift(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    inventory = json.loads((ROOT / "contracts/migration/v35_replacement_inventory_v3.json").read_text(encoding="utf-8"))
    baseline = json.loads((ROOT / "contracts/migration/v3_graph_baseline_v2.json").read_text(encoding="utf-8"))
    previous_path = ROOT / ".runtime/evidence/phase0/v3_current_script_task_graph_20260801/v3_current_script_task_graph_20260801.json"
    fresh_path = ROOT / ".runtime/evidence/task2/20260802-real-gate-final-15da08fb/v3_current_script_task_graph_20260802.json"
    previous = json.loads(previous_path.read_text(encoding="utf-8"))
    fresh = json.loads(fresh_path.read_text(encoding="utf-8"))
    atlas_root = Path(r"C:\Users\huang\Desktop\学习\v3_system\90_ops\status\v3_full_program_atlas_012")
    atlas_hashes, atlas_sources = _atlas_authority(atlas_root)
    common = {
        "previous_graph": previous,
        "previous_graph_raw_sha256": hashlib.sha256(previous_path.read_bytes()).hexdigest(),
        "graph_raw_sha256": hashlib.sha256(fresh_path.read_bytes()).hexdigest(),
        "atlas_semantic_hash": "912718015fba24d47dcac919b5720139666e3b5dfdf8e72a2236019badcdd033",
        "atlas_authority_sha256": atlas_hashes,
        "atlas_source_paths": atlas_sources,
        "builder_raw_sha256": "c96e2d340b880c8e2e810f5ad3bf1651963dbc4bf0e3f12eddaca8e8f1ce9a60",
        "test_source_sha256": "79a9bb8f8186a98491617e4322ae210d4e0e0260bbdd81450d67ee43f3cf6f9e",
    }

    first = build_inventory_v4(inventory, baseline, fresh, **common)
    second = build_inventory_v4(inventory, baseline, fresh, **common)
    assert first["semantic_hash"] == second["semantic_hash"]
    assert first["counts"] == {"sources": 336, "entrypoints": 90, "runtime_tasks": 69, "features": 11}
    assert first["unexplained_differences"] == []

    drifted = copy.deepcopy(fresh)
    drifted["graph"]["nodes"].append({"id": "timeline_node:unexpected"})
    with pytest.raises(GraphInventoryError, match="UNEXPLAINED_STRUCTURAL_DIFFERENCE"):
        build_inventory_v4(inventory, baseline, drifted, **common)

    bad_inventory = copy.deepcopy(inventory)
    bad_inventory["claims"]["ready_to_replace"] = True
    with pytest.raises(GraphInventoryError, match="INVENTORY_V3_TERMINAL_SEMANTIC_INVALID"):
        build_inventory_v4(bad_inventory, baseline, fresh, **common)
    bad_baseline = copy.deepcopy(baseline)
    bad_baseline["safety"]["production_allowed"] = True
    with pytest.raises(GraphInventoryError, match="BASELINE_V2_SEMANTIC_CONTRACT_INVALID"):
        build_inventory_v4(inventory, bad_baseline, fresh, **common)
    with pytest.raises(GraphInventoryError, match="PREVIOUS_GRAPH_SHA_INVALID"):
        build_inventory_v4(inventory, baseline, fresh, **{**common, "previous_graph_raw_sha256": "0" * 64})
    fake_atlas = tmp_path / "bad-atlas"
    fake_atlas.mkdir()
    (fake_atlas / "files.jsonl").write_text("", encoding="utf-8")
    (fake_atlas / "entrypoints.json").write_text("[]", encoding="utf-8")
    (fake_atlas / "validation.json").write_text(json.dumps({"schema_version": "v3_program_atlas.validation.v1", "status": "FAIL"}), encoding="utf-8")
    with monkeypatch.context() as patched:
        patched.setattr(
            graph_inventory_v4,
            "EXPECTED_ATLAS_AUTHORITY_RAW_SHA256",
            {name: hashlib.sha256((fake_atlas / name).read_bytes()).hexdigest() for name in ("files.jsonl", "entrypoints.json", "validation.json")},
        )
        with pytest.raises(GraphInventoryError, match="ATLAS_VALIDATION_INVALID"):
            _atlas_authority(fake_atlas)

    drifted_atlas = tmp_path / "raw-drift-atlas"
    drifted_atlas.mkdir()
    for name in ("files.jsonl", "entrypoints.json", "validation.json"):
        shutil.copy2(atlas_root / name, drifted_atlas / name)
    lines = (drifted_atlas / "files.jsonl").read_text(encoding="utf-8").splitlines()
    first_record = json.loads(lines[0])
    first_record["path"] = "_ops/pinned-raw-sha-drift.py"
    lines[0] = json.dumps(first_record, ensure_ascii=False, separators=(",", ":"))
    (drifted_atlas / "files.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(GraphInventoryError, match="ATLAS_AUTHORITY_RAW_SHA_DRIFT"):
        _atlas_authority(drifted_atlas)

    first_target = tmp_path / "inventory.json"
    second_target = tmp_path / "receipt.json"
    first_target.write_bytes(b"original-inventory")
    original_first = first_target.read_bytes()
    failed_once = False

    def fail_second_replace(source: Path, destination: Path) -> None:
        nonlocal failed_once
        if destination == second_target and not failed_once:
            failed_once = True
            raise OSError("injected second replace failure")
        source.replace(destination)

    with pytest.raises(OSError, match="injected second replace failure"):
        _atomic_json_pair(first_target, {"new": 1}, second_target, {"new": 2}, replace_fn=fail_second_replace)
    assert first_target.read_bytes() == original_first
    assert not second_target.exists()
