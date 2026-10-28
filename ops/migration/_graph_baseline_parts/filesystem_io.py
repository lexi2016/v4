"""ops.migration.graph_baseline: filesystem_io (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _write_graph_bundle_body(_v4_scope, /, *, atlas_path, runtime_graph_path, inventory_v1_path, legacy_root, baseline_output, inventory_output, freeze_input_dir):
    if freeze_input_dir is not None:
        _v4_global(_v4_scope, 'freeze_graph_inputs')(
            atlas_path=atlas_path,
            runtime_graph_path=runtime_graph_path,
            inventory_v1_path=inventory_v1_path,
            legacy_root=legacy_root,
            snapshot_root=freeze_input_dir,
        )
        baseline, inventory = _v4_global(_v4_scope, 'build_graph_bundle_from_snapshot')(freeze_input_dir)
    else:
        baseline, inventory = _v4_global(_v4_scope, 'build_graph_bundle')(
            atlas_path=atlas_path,
            runtime_graph_path=runtime_graph_path,
            inventory_v1_path=inventory_v1_path,
            legacy_root=legacy_root,
        )
    _v4_global(_v4_scope, '_atomic_json')(_v4_global(_v4_scope, 'Path')(baseline_output), baseline)
    _v4_global(_v4_scope, '_atomic_json')(_v4_global(_v4_scope, 'Path')(inventory_output), inventory)
    return baseline, inventory
