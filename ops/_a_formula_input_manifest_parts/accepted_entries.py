"""ops.a_formula_input_manifest: accepted_entries (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __accepted_only_entries_body(_v4_scope, /, *, accepted_manifest, copy_receipt, tdx_root, target_date, selected_relative_paths):
    """Validate the immutable accepted-only .day binding before parquet writes."""
    accepted, accepted_raw, accepted_sha, accepted_path = _v4_global(_v4_scope, '_read_json_object')(
        accepted_manifest, "accepted-only manifest"
    )
    copy, _copy_raw, copy_sha, copy_path = _v4_global(_v4_scope, '_read_json_object')(
        copy_receipt, "accepted-only copy receipt"
    )
    if accepted.get("schema_version") != _v4_global(_v4_scope, 'ACCEPTED_ONLY_SOURCE_SCHEMA'):
        raise _v4_global(_v4_scope, 'InputManifestError')("accepted-only manifest schema mismatch")
    if _v4_global(_v4_scope, '_date')(accepted.get("target_date"), "accepted-only target_date") != target_date:
        raise _v4_global(_v4_scope, 'InputManifestError')("accepted-only manifest target_date mismatch")
    if _v4_global(_v4_scope, 'str')(accepted.get("authority_status") or "").upper() != "REBUILD_REQUIRED":
        raise _v4_global(_v4_scope, 'InputManifestError')("accepted-only manifest must retain authority_status=REBUILD_REQUIRED")
    excluded = accepted.get("excluded_rebuild_candidate_count")
    if not _v4_global(_v4_scope, 'isinstance')(excluded, _v4_global(_v4_scope, 'int')) or _v4_global(_v4_scope, 'isinstance')(excluded, _v4_global(_v4_scope, 'bool')) or excluded <= 0:
        raise _v4_global(_v4_scope, 'InputManifestError')("accepted-only manifest excluded count is invalid")
    for flag in ("production_allowed", "buy_gate_updated", "orders_sent"):
        if accepted.get(flag) is not False:
            raise _v4_global(_v4_scope, 'InputManifestError')(f"accepted-only manifest safety flag is not false: {flag}")
    accepted_files = accepted.get("files")
    if not _v4_global(_v4_scope, 'isinstance')(accepted_files, _v4_global(_v4_scope, 'list')) or not accepted_files:
        raise _v4_global(_v4_scope, 'InputManifestError')("accepted-only manifest has no explicit files")
    if (
        ("/Library/Application Support/" in _v4_global(_v4_scope, 'str')(tdx_root) or "/releases/" in _v4_global(_v4_scope, 'str')(tdx_root))
        and not _v4_global(_v4_scope, 'is_v4_formula_state_path')(tdx_root)
    ):
        raise _v4_global(_v4_scope, 'InputManifestError')("accepted-only TDX root cannot target formal Application Support/release")

    accepted_by_relative: dict[str, dict[str, Any]] = {}
    for index, item in _v4_global(_v4_scope, 'enumerate')(accepted_files):
        if not _v4_global(_v4_scope, 'isinstance')(item, _v4_global(_v4_scope, 'Mapping')):
            raise _v4_global(_v4_scope, 'InputManifestError')(f"accepted-only manifest file {index} is not an object")
        relative = item.get("relative_path")
        if (
            not _v4_global(_v4_scope, 'isinstance')(relative, _v4_global(_v4_scope, 'str'))
            or "\x00" in relative
            or "\\" in relative
            or not _v4_global(_v4_scope, '_DAY_PATH').fullmatch(relative)
        ):
            raise _v4_global(_v4_scope, 'InputManifestError')(f"accepted-only manifest path is unsafe: {relative!r}")
        if relative in accepted_by_relative:
            raise _v4_global(_v4_scope, 'InputManifestError')(f"accepted-only manifest path is duplicated: {relative}")
        source_path = item.get("path")
        if not _v4_global(_v4_scope, 'isinstance')(source_path, _v4_global(_v4_scope, 'str')) or not source_path or not _v4_global(_v4_scope, 'Path')(source_path).is_absolute():
            raise _v4_global(_v4_scope, 'InputManifestError')(f"accepted-only manifest source path is not absolute: {relative}")
        source_posix = _v4_global(_v4_scope, 'Path')(source_path).as_posix()
        if _v4_global(_v4_scope, 'Path')(source_path).name != _v4_global(_v4_scope, 'Path')(relative).name or not source_posix.endswith("/" + relative):
            raise _v4_global(_v4_scope, 'InputManifestError')(f"accepted-only manifest source basename mismatch: {relative}")
        digest = _v4_global(_v4_scope, 'str')(item.get("sha256") or "").lower()
        if not _v4_global(_v4_scope, '_SHA256').fullmatch(digest):
            raise _v4_global(_v4_scope, 'InputManifestError')(f"accepted-only manifest SHA is invalid: {relative}")
        fetch_status = _v4_global(_v4_scope, 'str')(item.get("fetch_status") or "").upper()
        if not fetch_status or _v4_global(_v4_scope, 'any')(token in fetch_status for token in ("FAILED", "QUARANTINE", "CANNOT_CONFIRM")):
            raise _v4_global(_v4_scope, 'InputManifestError')(f"accepted-only manifest file is not accepted: {relative}")
        accepted_by_relative[relative] = {
            "relative_path": relative,
            "source_path": source_path,
            "sha256": digest,
            "fetch_status": fetch_status,
        }

    if copy.get("schema_version") not in (None, "v3_5.a_sync.accepted_formula_input.copy_receipt.v1"):
        # The historical copy receipt predates a schema key.  If a future
        # receipt adds one, accept only the known binding rather than guessing.
        raise _v4_global(_v4_scope, 'InputManifestError')("accepted-only copy receipt schema mismatch")
    if copy.get("status") != _v4_global(_v4_scope, 'ACCEPTED_ONLY_COPY_STATUS'):
        raise _v4_global(_v4_scope, 'InputManifestError')("accepted-only copy receipt status is not accepted-only")
    if _v4_global(_v4_scope, '_date')(copy.get("target_date"), "accepted-only copy target_date") != target_date:
        raise _v4_global(_v4_scope, 'InputManifestError')("accepted-only copy target_date mismatch")
    if _v4_global(_v4_scope, 'str')(copy.get("source_authority_status") or "").upper() != "REBUILD_REQUIRED":
        raise _v4_global(_v4_scope, 'InputManifestError')("accepted-only copy must retain source authority status")
    if copy.get("manifest_sha256") != accepted_sha:
        raise _v4_global(_v4_scope, 'InputManifestError')("accepted-only copy receipt is not bound to manifest bytes")
    if copy.get("excluded_rebuild_candidate_count") != excluded:
        raise _v4_global(_v4_scope, 'InputManifestError')("accepted-only excluded count mismatch")
    if copy.get("formal_data_changed") is not False or copy.get("full_5800_authority_pass") is not False:
        raise _v4_global(_v4_scope, 'InputManifestError')("accepted-only copy receipt claims formal/full authority")
    if copy.get("no_source_status_rewrite") is not True:
        raise _v4_global(_v4_scope, 'InputManifestError')("accepted-only copy receipt does not preserve source status")
    source_receipt_sha = _v4_global(_v4_scope, 'str')(copy.get("source_receipt_sha256") or "").lower()
    if not _v4_global(_v4_scope, '_SHA256').fullmatch(source_receipt_sha):
        raise _v4_global(_v4_scope, 'InputManifestError')("accepted-only source receipt SHA is invalid")
    source_receipt_raw = copy.get("source_receipt")
    if not _v4_global(_v4_scope, 'isinstance')(source_receipt_raw, _v4_global(_v4_scope, 'str')) or not source_receipt_raw:
        raise _v4_global(_v4_scope, 'InputManifestError')("accepted-only source receipt path is missing")
    source_receipt_path = _v4_global(_v4_scope, '_resolved_regular')(_v4_global(_v4_scope, 'Path')(source_receipt_raw), "accepted-only source receipt")
    if _v4_global(_v4_scope, '_sha256_file')(source_receipt_path) != source_receipt_sha:
        raise _v4_global(_v4_scope, 'InputManifestError')("accepted-only source receipt SHA mismatch")
    copy_files = copy.get("files")
    if not _v4_global(_v4_scope, 'isinstance')(copy_files, _v4_global(_v4_scope, 'list')) or _v4_global(_v4_scope, 'len')(copy_files) != _v4_global(_v4_scope, 'len')(accepted_by_relative):
        raise _v4_global(_v4_scope, 'InputManifestError')("accepted-only copy file count does not match accepted manifest")
    copy_by_relative: dict[str, dict[str, Any]] = {}
    for index, item in _v4_global(_v4_scope, 'enumerate')(copy_files):
        if not _v4_global(_v4_scope, 'isinstance')(item, _v4_global(_v4_scope, 'Mapping')):
            raise _v4_global(_v4_scope, 'InputManifestError')(f"accepted-only copy file {index} is not an object")
        relative = item.get("relative_path")
        if not _v4_global(_v4_scope, 'isinstance')(relative, _v4_global(_v4_scope, 'str')) or not _v4_global(_v4_scope, '_DAY_PATH').fullmatch(relative) or relative in copy_by_relative:
            raise _v4_global(_v4_scope, 'InputManifestError')(f"accepted-only copy path is invalid or duplicated: {relative!r}")
        digest = _v4_global(_v4_scope, 'str')(item.get("sha256") or "").lower()
        byte_count = item.get("bytes")
        if not _v4_global(_v4_scope, '_SHA256').fullmatch(digest) or not _v4_global(_v4_scope, 'isinstance')(byte_count, _v4_global(_v4_scope, 'int')) or _v4_global(_v4_scope, 'isinstance')(byte_count, _v4_global(_v4_scope, 'bool')) or byte_count <= 0:
            raise _v4_global(_v4_scope, 'InputManifestError')(f"accepted-only copy identity is invalid: {relative}")
        copy_by_relative[relative] = {"sha256": digest, "bytes": byte_count}
    if _v4_global(_v4_scope, 'set')(copy_by_relative) != _v4_global(_v4_scope, 'set')(accepted_by_relative):
        raise _v4_global(_v4_scope, 'InputManifestError')("accepted-only copy path scope differs from accepted manifest")
    for relative, entry in accepted_by_relative.items():
        copied = copy_by_relative[relative]
        if copied["sha256"] != entry["sha256"]:
            raise _v4_global(_v4_scope, 'InputManifestError')(f"accepted-only copy SHA differs from manifest: {relative}")

    # Validate the requested subset only after both complete metadata sets have
    # been compared.  This preserves the full manifest/copy-receipt identity
    # gate while keeping unselected source members out of the read/hash/decode
    # loop below.
    if selected_relative_paths is None:
        selected = None
        relatives_to_check = _v4_global(_v4_scope, 'sorted')(accepted_by_relative)
    else:
        selected = _v4_global(_v4_scope, 'list')(selected_relative_paths)
        if not selected:
            raise _v4_global(_v4_scope, 'InputManifestError')("accepted-only selected scope cannot be empty")
        for relative in selected:
            if not _v4_global(_v4_scope, 'isinstance')(relative, _v4_global(_v4_scope, 'str')) or not _v4_global(_v4_scope, '_DAY_PATH').fullmatch(relative):
                raise _v4_global(_v4_scope, 'InputManifestError')(f"accepted-only selected path is invalid: {relative!r}")
        if _v4_global(_v4_scope, 'len')(selected) != _v4_global(_v4_scope, 'len')(_v4_global(_v4_scope, 'set')(selected)):
            raise _v4_global(_v4_scope, 'InputManifestError')("accepted-only selected scope contains duplicates")
        for relative in selected:
            if relative not in accepted_by_relative:
                raise _v4_global(_v4_scope, 'InputManifestError')(f"accepted-only selected path is outside accepted set: {relative}")
        relatives_to_check = selected

    copied_count = copy.get("copied_count")
    if copied_count != _v4_global(_v4_scope, 'len')(accepted_by_relative):
        raise _v4_global(_v4_scope, 'InputManifestError')("accepted-only copied_count does not match explicit files")
    receipt_root_raw = copy.get("target_root")
    if not _v4_global(_v4_scope, 'isinstance')(receipt_root_raw, _v4_global(_v4_scope, 'str')) or not receipt_root_raw:
        raise _v4_global(_v4_scope, 'InputManifestError')("accepted-only copy target_root is missing")
    receipt_root = _v4_global(_v4_scope, '_resolved_root')(_v4_global(_v4_scope, 'Path')(receipt_root_raw), "accepted-only copy target root")
    if receipt_root != tdx_root:
        raise _v4_global(_v4_scope, 'InputManifestError')("accepted-only copy target_root differs from supplied TDX root")

    checked: list[dict[str, Any]] = []
    for relative in relatives_to_check:
        entry = accepted_by_relative[relative]
        source = _v4_global(_v4_scope, '_resolved_regular')(tdx_root / relative, "accepted-only source file")
        if not _v4_global(_v4_scope, '_inside')(tdx_root, source):
            raise _v4_global(_v4_scope, 'InputManifestError')(f"accepted-only source escapes TDX root: {relative}")
        actual_sha = _v4_global(_v4_scope, '_sha256_file')(source)
        if actual_sha != entry["sha256"]:
            raise _v4_global(_v4_scope, 'InputManifestError')(
                f"accepted-only source SHA mismatch: {relative}: expected={entry['sha256']}:actual={actual_sha}"
            )
        actual_bytes = source.stat().st_size
        if actual_bytes != copy_by_relative[relative]["bytes"]:
            raise _v4_global(_v4_scope, 'InputManifestError')(f"accepted-only source byte count mismatch: {relative}")
        if actual_bytes == 0 or actual_bytes % _v4_global(_v4_scope, 'DAY_STRUCT').size:
            raise _v4_global(_v4_scope, 'InputManifestError')(f"accepted-only source .day shape is invalid: {relative}")
        rows = _v4_global(_v4_scope, 'read_hq_day_bars')(source)
        if not rows:
            raise _v4_global(_v4_scope, 'InputManifestError')(f"accepted-only source is empty: {relative}")
        previous = 0
        target_seen = False
        for row in rows:
            valid, reason = _v4_global(_v4_scope, 'valid_hq_bar')(row)
            if not valid:
                raise _v4_global(_v4_scope, 'InputManifestError')(f"accepted-only source bar invalid ({relative}): {reason}")
            row_date = _v4_global(_v4_scope, 'int')(row["year"]) * 10000 + _v4_global(_v4_scope, 'int')(row["month"]) * 100 + _v4_global(_v4_scope, 'int')(row["day"])
            _v4_global(_v4_scope, '_date')(row_date, f"accepted-only source {relative} bar")
            if row_date <= previous:
                raise _v4_global(_v4_scope, 'InputManifestError')(f"accepted-only source dates are not strictly increasing: {relative}")
            if row_date > _v4_global(_v4_scope, 'int')(target_date):
                raise _v4_global(_v4_scope, 'InputManifestError')(f"accepted-only source contains future bar: {relative}:{row_date}")
            previous = row_date
            target_seen = target_seen or row_date == _v4_global(_v4_scope, 'int')(target_date)
        if not target_seen:
            raise _v4_global(_v4_scope, 'InputManifestError')(f"accepted-only source has no exact target-date row: {relative}")
        checked.append({"relative": relative, "market": relative.split("/", 2)[1], "path": source, "source_entry": entry})
    return accepted, copy, accepted_sha, copy_sha, checked, _v4_global(_v4_scope, 'len')(accepted_by_relative), accepted_path, copy_path


def _build_accepted_only_a_formula_input_manifest_body(_v4_scope, /, *, accepted_manifest, copy_receipt, tdx_root, output_root, target_date, run_id, selected_relative_paths):
    """Materialize an explicit accepted-only .day set without full-authority relabeling."""
    target = _v4_global(_v4_scope, '_date')(target_date, "target_date")
    tdx = _v4_global(_v4_scope, '_resolved_root')(_v4_global(_v4_scope, 'Path')(tdx_root), "TDX root")
    output = _v4_global(_v4_scope, '_resolved_root')(_v4_global(_v4_scope, 'Path')(output_root), "input output root")
    _v4_global(_v4_scope, '_ensure_distinct_roots')(tdx, output)
    if output.exists() and _v4_global(_v4_scope, 'any')(output.iterdir()):
        raise _v4_global(_v4_scope, 'InputManifestError')("input output root must be empty; refusing mixed-generation writes")
    output.mkdir(parents=True, exist_ok=True)
    if _v4_global(_v4_scope, '_has_symlink_ancestor')(output):
        raise _v4_global(_v4_scope, 'InputManifestError')("input output root has symlink ancestry")
    accepted, copy, accepted_sha, copy_sha, admitted, accepted_count, accepted_path, copy_path = _v4_global(_v4_scope, '_accepted_only_entries')(
        accepted_manifest=accepted_manifest,
        copy_receipt=copy_receipt,
        tdx_root=tdx,
        target_date=target,
        selected_relative_paths=selected_relative_paths,
    )
    if selected_relative_paths is None:
        scope = "ACCEPTED_ONLY_FULL"
    else:
        scope = "ACCEPTED_ONLY_SUBSET"
    chosen_run_id = run_id or f"a-sync-{target}-accepted-only"
    if not _v4_global(_v4_scope, '_RUN_ID').fullmatch(chosen_run_id):
        raise _v4_global(_v4_scope, 'InputManifestError')("run_id is missing or unsafe")

    file_entries: list[dict[str, Any]] = []
    source_day_entries: list[dict[str, Any]] = []
    all_keys: set[tuple[str, int]] = _v4_global(_v4_scope, 'set')()
    total_rows = 0
    target_rows = 0
    for item in admitted:
        relative, market, source_path = item["relative"], item["market"], item["path"]
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
                "accepted_fetch_status": item["source_entry"]["fetch_status"],
            }
        )
        total_rows += rows
        target_rows += _v4_global(_v4_scope, 'int')((frame["trade_date"] == _v4_global(_v4_scope, 'int')(target)).sum())

    parquet_shas = [_v4_global(_v4_scope, 'str')(item["sha256"]) for item in file_entries]
    source_sha = parquet_shas[0] if _v4_global(_v4_scope, 'len')(parquet_shas) == 1 else _v4_global(_v4_scope, '_sha256_bytes')("\n".join(_v4_global(_v4_scope, 'sorted')(parquet_shas)).encode("ascii"))
    excluded = _v4_global(_v4_scope, 'int')(accepted["excluded_rebuild_candidate_count"])
    selected_count = _v4_global(_v4_scope, 'len')(file_entries)
    source_receipt_sha = _v4_global(_v4_scope, 'str')(copy["source_receipt_sha256"]).lower()
    manifest: dict[str, Any] = {
        "schema": _v4_global(_v4_scope, 'SCHEMA'),
        "market": "A",
        "target_date": target,
        "run_id": chosen_run_id,
        "authority_status": "REBUILD_REQUIRED",
        "full_authority_pass": False,
        "scope": scope,
        "source": {
            "name": "a_sync_accepted_only_day_files",
            "version": "v1",
            "scope": scope,
            "accepted_manifest_path": _v4_global(_v4_scope, 'str')(accepted_path),
            "accepted_manifest_sha256": accepted_sha,
            "accepted_manifest_file_count": accepted_count,
            "selected_file_count": selected_count,
            "copy_receipt_path": _v4_global(_v4_scope, 'str')(copy_path),
            "copy_receipt_sha256": copy_sha,
            "source_receipt_path": _v4_global(_v4_scope, 'str')(copy["source_receipt"]),
            "source_receipt_sha256": source_receipt_sha,
            "authority_status": "REBUILD_REQUIRED",
            "excluded_rebuild_candidate_count": excluded,
            "tdx_root": _v4_global(_v4_scope, 'str')(tdx),
            "network": "NOT_USED",
        },
        "source_sha256": source_sha,
        "source_day_files": source_day_entries,
        "files": file_entries,
        "coverage": {
            "status": "PASS",
            "scope": scope,
            "authority_status": "REBUILD_REQUIRED",
            "full_authority_pass": False,
            "accepted_manifest_files": accepted_count,
            "excluded_rebuild_candidate_count": excluded,
            "rows": total_rows,
            "symbols": selected_count,
            "files": selected_count,
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
        "status": "READY_ACCEPTED_ONLY",
        "schema": _v4_global(_v4_scope, 'SCHEMA'),
        "target_date": target,
        "run_id": chosen_run_id,
        "path": _v4_global(_v4_scope, 'str')(manifest_path),
        "bytes": manifest_path.stat().st_size,
        "sha256": _v4_global(_v4_scope, '_sha256_file')(manifest_path),
        "manifest_sha256": manifest["manifest_sha256"],
        "source_sha256": source_sha,
        "scope": scope,
        "accepted_manifest_sha256": accepted_sha,
        "copy_receipt_sha256": copy_sha,
        "source_receipt_sha256": source_receipt_sha,
        "accepted_manifest_file_count": accepted_count,
        "selected_file_count": selected_count,
        "excluded_rebuild_candidate_count": excluded,
        "authority_status": "REBUILD_REQUIRED",
        "full_authority_pass": False,
        "files": selected_count,
        "rows": total_rows,
        "target_date_rows": target_rows,
        "network": "NOT_USED",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
