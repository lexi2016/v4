"""ops.a_formula_input_manifest: manifest_generation (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _build_a_formula_input_manifest_body(_v4_scope, /, *, sync_receipt, tdx_root, output_root, target_date, run_id):
    """Materialize and return one exact-date V4 input manifest."""

    target = _v4_global(_v4_scope, '_date')(target_date, "target_date")
    tdx = _v4_global(_v4_scope, '_resolved_root')(_v4_global(_v4_scope, 'Path')(tdx_root), "TDX root")
    output = _v4_global(_v4_scope, '_resolved_root')(_v4_global(_v4_scope, 'Path')(output_root), "input output root")
    _v4_global(_v4_scope, '_ensure_distinct_roots')(tdx, output)
    if output.exists() and _v4_global(_v4_scope, 'any')(output.iterdir()):
        raise _v4_global(_v4_scope, 'InputManifestError')("input output root must be empty; refusing mixed-generation writes")
    output.mkdir(parents=True, exist_ok=True)
    if _v4_global(_v4_scope, '_has_symlink_ancestor')(output):
        raise _v4_global(_v4_scope, 'InputManifestError')("input output root has symlink ancestry")
    receipt, receipt_raw, receipt_sha = _v4_global(_v4_scope, '_read_sync_receipt')(_v4_global(_v4_scope, 'Path')(sync_receipt), target)
    admitted = _v4_global(_v4_scope, '_receipt_files')(receipt, tdx_root=tdx, target_date=target)
    chosen_run_id = run_id or f"a-sync-{target}"
    if not _v4_global(_v4_scope, '_RUN_ID').fullmatch(chosen_run_id):
        raise _v4_global(_v4_scope, 'InputManifestError')("run_id is missing or unsafe")

    file_entries: list[dict[str, Any]] = []
    source_day_entries: list[dict[str, Any]] = []
    all_keys: set[tuple[str, int]] = _v4_global(_v4_scope, 'set')()
    total_rows = 0
    target_rows = 0
    for relative, market, source_path in admitted:
        frame = _v4_global(_v4_scope, '_frame_for_day_file')(source_path, relative, market, target)
        keys = _v4_global(_v4_scope, 'set')(_v4_global(_v4_scope, 'zip')(frame["ts_code"].astype(_v4_global(_v4_scope, 'str')), frame["trade_date"].astype(_v4_global(_v4_scope, 'int'))))
        if all_keys.intersection(keys):
            raise _v4_global(_v4_scope, 'InputManifestError')(f"duplicate source keys across files: {relative}")
        all_keys.update(keys)
        parquet_relative = _v4_global(_v4_scope, 'Path')("files") / f"{_v4_global(_v4_scope, 'Path')(relative).stem}.parquet"
        destination = output / parquet_relative
        rows, parquet_sha = _v4_global(_v4_scope, '_write_parquet')(frame, destination)
        source_sha = _v4_global(_v4_scope, '_sha256_file')(source_path)
        source_bytes = source_path.stat().st_size
        file_entries.append(
            {
                "path": parquet_relative.as_posix(),
                "sha256": parquet_sha,
                "rows": rows,
                "source_day_path": relative,
                "source_day_sha256": source_sha,
                "source_day_bytes": source_bytes,
                "target_date_rows": _v4_global(_v4_scope, 'int')((frame["trade_date"] == _v4_global(_v4_scope, 'int')(target)).sum()),
            }
        )
        source_day_entries.append(
            {
                "path": relative,
                "sha256": source_sha,
                "bytes": source_bytes,
                "rows": rows,
                "target_date_rows": _v4_global(_v4_scope, 'int')((frame["trade_date"] == _v4_global(_v4_scope, 'int')(target)).sum()),
            }
        )
        total_rows += rows
        target_rows += _v4_global(_v4_scope, 'int')((frame["trade_date"] == _v4_global(_v4_scope, 'int')(target)).sum())

    parquet_shas = [_v4_global(_v4_scope, 'str')(item["sha256"]) for item in file_entries]
    source_sha = parquet_shas[0] if _v4_global(_v4_scope, 'len')(parquet_shas) == 1 else _v4_global(_v4_scope, '_sha256_bytes')("\n".join(_v4_global(_v4_scope, 'sorted')(parquet_shas)).encode("ascii"))
    manifest: dict[str, Any] = {
        "schema": _v4_global(_v4_scope, 'SCHEMA'),
        "market": "A",
        "target_date": target,
        "run_id": chosen_run_id,
        "source": {
            "name": "a_sync_day_files",
            "version": "v1",
            "sync_receipt_path": _v4_global(_v4_scope, 'str')(_v4_global(_v4_scope, 'Path')(sync_receipt).expanduser().resolve()),
            "sync_receipt_sha256": receipt_sha,
            "tdx_root": _v4_global(_v4_scope, 'str')(tdx),
            "network": "NOT_USED",
        },
        "source_sha256": source_sha,
        "source_day_files": source_day_entries,
        "files": file_entries,
        "coverage": {
            "status": "PASS",
            "rows": total_rows,
            "symbols": _v4_global(_v4_scope, 'len')(admitted),
            "files": _v4_global(_v4_scope, 'len')(admitted),
            "target_date_rows": target_rows,
        },
        "duplicate_key_audit": {"status": "PASS", "duplicate_rows": 0},
        "future_check": {"status": "PASS", "future_rows": 0},
        "safety": {"network": "NOT_USED", "formal_data_write": False},
    }
    manifest["manifest_sha256"] = _v4_global(_v4_scope, '_manifest_sha')(manifest)
    manifest_path = output / "manifest.json"
    if manifest_path.exists() or manifest_path.is_symlink():
        raise _v4_global(_v4_scope, 'InputManifestError')("refusing to overwrite input manifest")
    manifest_path.write_bytes((_v4_global(_v4_scope, 'json').dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8"))
    return {
        "status": "READY",
        "schema": _v4_global(_v4_scope, 'SCHEMA'),
        "target_date": target,
        "run_id": chosen_run_id,
        "path": _v4_global(_v4_scope, 'str')(manifest_path),
        "bytes": manifest_path.stat().st_size,
        "sha256": _v4_global(_v4_scope, '_sha256_file')(manifest_path),
        "manifest_sha256": manifest["manifest_sha256"],
        "source_sha256": source_sha,
        "files": _v4_global(_v4_scope, 'len')(file_entries),
        "rows": total_rows,
        "target_date_rows": target_rows,
        "sync_receipt_sha256": receipt_sha,
        "sync_receipt_bytes": _v4_global(_v4_scope, 'len')(receipt_raw),
        "network": "NOT_USED",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
