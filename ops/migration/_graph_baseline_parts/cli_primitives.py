"""ops.migration.graph_baseline: cli_primitives (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __difference_rows_body(_v4_scope, /, atlas_by_id, previous_by_id, *, atlas_id_field, atlas_path_field, previous_path_field, legacy_root):
    atlas_only: list[dict[str, Any]] = []
    previous_only: list[dict[str, Any]] = []
    unexplained: list[str] = []
    for identity in _v4_global(_v4_scope, 'sorted')(atlas_by_id.keys() - previous_by_id.keys()):
        record = atlas_by_id[identity]
        atlas_only.append(
            {
                atlas_id_field: identity,
                "path": _v4_global(_v4_scope, 'str')(record[atlas_path_field]),
                "reason": "ADDED_AFTER_ORPHANED_INVENTORY",
            }
        )
    for identity in _v4_global(_v4_scope, 'sorted')(previous_by_id.keys() - atlas_by_id.keys()):
        record = previous_by_id[identity]
        path = _v4_global(_v4_scope, 'str')(record[previous_path_field])
        exists = _v4_global(_v4_scope, '_legacy_file')(legacy_root, path).is_file()
        previous_only.append(
            {
                atlas_id_field: identity,
                "path": path,
                "reason": (
                    "REMOVED_FROM_CURRENT_ATLAS_BUT_PRESENT_ON_DISK"
                    if exists
                    else "REMOVED_FROM_CURRENT_ATLAS_AND_DISK"
                ),
            }
        )
    for identity in _v4_global(_v4_scope, 'sorted')(atlas_by_id.keys() & previous_by_id.keys()):
        atlas_path_value = _v4_global(_v4_scope, 'str')(atlas_by_id[identity][atlas_path_field])
        previous_path_value = _v4_global(_v4_scope, 'str')(previous_by_id[identity][previous_path_field])
        if atlas_path_value != previous_path_value:
            unexplained.append(
                f"IDENTITY_PATH_MISMATCH:{identity}:{atlas_path_value}:{previous_path_value}"
            )
    return atlas_only, previous_only, unexplained


def _main_body(_v4_scope, /):
    parser = _v4_global(_v4_scope, 'argparse').ArgumentParser(description="Build the graph-grounded V3.5 baseline v2.")
    parser.add_argument("--atlas", required=True, type=_v4_global(_v4_scope, 'Path'))
    parser.add_argument("--runtime-graph", required=True, type=_v4_global(_v4_scope, 'Path'))
    parser.add_argument("--inventory-v1", required=True, type=_v4_global(_v4_scope, 'Path'))
    parser.add_argument("--legacy-root", required=True, type=_v4_global(_v4_scope, 'Path'))
    parser.add_argument("--baseline-output", required=True, type=_v4_global(_v4_scope, 'Path'))
    parser.add_argument("--inventory-output", required=True, type=_v4_global(_v4_scope, 'Path'))
    parser.add_argument("--freeze-input-dir", type=_v4_global(_v4_scope, 'Path'))
    args = parser.parse_args()
    _v4_global(_v4_scope, 'write_graph_bundle')(
        atlas_path=args.atlas,
        runtime_graph_path=args.runtime_graph,
        inventory_v1_path=args.inventory_v1,
        legacy_root=args.legacy_root,
        baseline_output=args.baseline_output,
        inventory_output=args.inventory_output,
        freeze_input_dir=args.freeze_input_dir,
    )
