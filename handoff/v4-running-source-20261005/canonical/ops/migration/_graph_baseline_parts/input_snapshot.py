"""ops.migration.graph_baseline: input_snapshot (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __snapshot_input_paths_body(_v4_scope, /, *, atlas_path, inventory_v1):
    paths = {
        _v4_global(_v4_scope, '_relative_path')(row["path"], context="Atlas snapshot source")
        for row in _v4_global(_v4_scope, '_load_jsonl')(atlas_path / "files.jsonl")
        if row.get("scan_mode", "included") == "included"
    }
    for row in inventory_v1.get("sources", []):
        paths.add(
            _v4_global(_v4_scope, '_relative_path')(row.get("old_source"), context="inventory snapshot source")
        )
    for row in inventory_v1.get("entrypoints", []):
        for evidence in row.get("source_evidence", []):
            if _v4_global(_v4_scope, 'isinstance')(evidence, _v4_global(_v4_scope, 'Mapping')) and _v4_global(_v4_scope, 'isinstance')(evidence.get("path"), _v4_global(_v4_scope, 'str')):
                paths.add(
                    _v4_global(_v4_scope, '_relative_path')(
                        evidence["path"], context="entrypoint snapshot source"
                    )
                )
    return _v4_global(_v4_scope, 'sorted')(paths)




def __validate_input_snapshot_body(_v4_scope, /, snapshot_root):
    snapshot_root = _v4_global(_v4_scope, 'Path')(snapshot_root)
    manifest = _v4_global(_v4_scope, '_load_json')(snapshot_root / "snapshot_manifest.json")
    if (
        not _v4_global(_v4_scope, 'isinstance')(manifest, _v4_global(_v4_scope, 'Mapping'))
        or manifest.get("schema_version") != _v4_global(_v4_scope, 'INPUT_SNAPSHOT_SCHEMA')
    ):
        raise _v4_global(_v4_scope, 'GraphBaselineError')("unknown frozen input snapshot schema")
    semantic_hash = manifest.get("semantic_hash")
    if not _v4_global(_v4_scope, '_is_sha256')(semantic_hash):
        raise _v4_global(_v4_scope, 'GraphBaselineError')("invalid frozen input snapshot semantic hash")
    unhashed = {
        key: _v4_global(_v4_scope, 'deepcopy')(value)
        for key, value in manifest.items()
        if key != "semantic_hash"
    }
    if _v4_global(_v4_scope, '_digest_bytes')(_v4_global(_v4_scope, '_canonical_bytes')(unhashed)) != semantic_hash:
        raise _v4_global(_v4_scope, 'GraphBaselineError')("frozen input snapshot semantic hash mismatch")
    files = manifest.get("files")
    if not _v4_global(_v4_scope, 'isinstance')(files, _v4_global(_v4_scope, 'list')) or not files:
        raise _v4_global(_v4_scope, 'GraphBaselineError')("frozen input snapshot files are missing")
    for row in files:
        if not _v4_global(_v4_scope, 'isinstance')(row, _v4_global(_v4_scope, 'Mapping')):
            raise _v4_global(_v4_scope, 'GraphBaselineError')("invalid frozen input snapshot row")
        target = _v4_global(_v4_scope, '_snapshot_file')(snapshot_root, row.get("path"))
        exists = target.is_file()
        if exists != row.get("exists"):
            raise _v4_global(_v4_scope, 'GraphBaselineError')("frozen input existence mismatch")
        if exists:
            if (
                not _v4_global(_v4_scope, '_is_sha256')(row.get("sha256"))
                or _v4_global(_v4_scope, '_digest_file')(target) != row["sha256"]
                or target.stat().st_size != row.get("size")
            ):
                raise _v4_global(_v4_scope, 'GraphBaselineError')("frozen input hash mismatch")
        elif row.get("sha256") is not None or row.get("size") is not None:
            raise _v4_global(_v4_scope, 'GraphBaselineError')("invalid missing frozen input row")
    return _v4_global(_v4_scope, 'dict')(manifest)
