"""ops.a_formula_increment: input_manifest (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __safe_manifest_file_body(_v4_scope, /, input_root, raw):
    if not _v4_global(_v4_scope, 'isinstance')(raw, _v4_global(_v4_scope, 'str')) or not raw or "\\" in raw or "\x00" in raw:
        raise _v4_global(_v4_scope, 'AuthorityError')("manifest file path is unsafe")
    relative = _v4_global(_v4_scope, 'Path')(raw)
    if relative.is_absolute() or ".." in relative.parts:
        raise _v4_global(_v4_scope, 'AuthorityError')(f"manifest file must be relative: {raw}")
    candidate_raw = input_root / relative
    if _v4_global(_v4_scope, '_path_has_symlink')(candidate_raw):
        raise _v4_global(_v4_scope, 'AuthorityError')(f"manifest file has symlink ancestry: {raw}")
    candidate = candidate_raw.resolve(strict=False)
    if not _v4_global(_v4_scope, '_within')(candidate, input_root):
        raise _v4_global(_v4_scope, 'AuthorityError')(f"manifest file escapes input root: {raw}")
    if _v4_global(_v4_scope, '_path_has_symlink')(input_root) or _v4_global(_v4_scope, '_path_has_symlink')(candidate):
        raise _v4_global(_v4_scope, 'AuthorityError')(f"manifest file has symlink ancestry: {raw}")
    if not candidate.is_file() or candidate.is_symlink():
        raise _v4_global(_v4_scope, 'AuthorityError')(f"manifest source file missing or not regular: {raw}")
    return candidate


def __load_input_manifest_body(_v4_scope, /, input_root, manifest_path, target_date):
    raw_root = _v4_global(_v4_scope, 'Path')(input_root).expanduser()
    raw_manifest = _v4_global(_v4_scope, 'Path')(manifest_path).expanduser()
    if _v4_global(_v4_scope, '_path_has_symlink')(raw_root) or _v4_global(_v4_scope, '_path_has_symlink')(raw_manifest):
        raise _v4_global(_v4_scope, 'AuthorityError')("offline manifest or input root has a symlinked parent")
    root = _v4_global(_v4_scope, '_resolved')(input_root)
    manifest_file = _v4_global(_v4_scope, '_resolved')(manifest_path)
    if not root.is_dir() or not manifest_file.is_file() or not _v4_global(_v4_scope, '_within')(manifest_file, root):
        raise _v4_global(_v4_scope, 'AuthorityError')("offline manifest must be a regular file inside input root")
    manifest = _v4_global(_v4_scope, '_read_json')(manifest_file)
    if manifest.get("schema") != "v4.a_formula.input_manifest.v1":
        raise _v4_global(_v4_scope, 'AuthorityError')("unsupported offline input manifest schema")
    if _v4_global(_v4_scope, 'str')(manifest.get("market", "")).upper() != "A":
        raise _v4_global(_v4_scope, 'AuthorityError')("offline manifest market must be A")
    try:
        manifest_target = _v4_global(_v4_scope, 'int')(_v4_global(_v4_scope, 'str')(manifest.get("target_date", "")).replace("-", ""))
    except (_v4_global(_v4_scope, 'TypeError'), _v4_global(_v4_scope, 'ValueError')) as error:
        raise _v4_global(_v4_scope, 'AuthorityError')("offline manifest target_date is invalid") from error
    if manifest_target != target_date:
        raise _v4_global(_v4_scope, 'AuthorityError')(f"offline manifest target_date mismatch: {manifest_target} != {target_date}")
    source = manifest.get("source")
    if not _v4_global(_v4_scope, 'isinstance')(source, _v4_global(_v4_scope, 'Mapping')) or not _v4_global(_v4_scope, 'str')(source.get("name", "")).strip():
        raise _v4_global(_v4_scope, 'AuthorityError')("offline manifest source identity is missing")
    run_id = _v4_global(_v4_scope, 'str')(manifest.get("run_id", "")).strip()
    if not run_id or not _v4_global(_v4_scope, 're').fullmatch(r"[A-Za-z0-9_.-]{1,160}", run_id):
        raise _v4_global(_v4_scope, 'AuthorityError')("offline manifest run_id is missing or unsafe")
    expected_manifest_sha = _v4_global(_v4_scope, 'str')(manifest.get("manifest_sha256", "")).strip()
    if not expected_manifest_sha or expected_manifest_sha != _v4_global(_v4_scope, '_manifest_digest')(manifest):
        raise _v4_global(_v4_scope, 'AuthorityError')("offline manifest SHA mismatch")
    files = manifest.get("files")
    if not _v4_global(_v4_scope, 'isinstance')(files, _v4_global(_v4_scope, 'list')) or not files:
        raise _v4_global(_v4_scope, 'AuthorityError')("offline manifest must list source files")
    _v4_global(_v4_scope, '_require_pass_gate')(manifest.get("coverage"), "coverage")
    _v4_global(_v4_scope, '_require_pass_gate')(manifest.get("duplicate_key_audit"), "duplicate_key_audit")
    _v4_global(_v4_scope, '_require_pass_gate')(manifest.get("future_check"), "future_check")
    if _v4_global(_v4_scope, 'int')(manifest["duplicate_key_audit"].get("duplicate_rows", 0) or 0) != 0:
        raise _v4_global(_v4_scope, 'AuthorityError')("offline manifest duplicate audit is nonzero")
    if _v4_global(_v4_scope, 'int')(manifest["future_check"].get("future_rows", 0) or 0) != 0:
        raise _v4_global(_v4_scope, 'AuthorityError')("offline manifest future audit is nonzero")
    frames: list[pd.DataFrame] = []
    file_sha_values: list[str] = []
    total_manifest_rows = 0
    for item in files:
        if not _v4_global(_v4_scope, 'isinstance')(item, _v4_global(_v4_scope, 'Mapping')):
            raise _v4_global(_v4_scope, 'AuthorityError')("offline manifest file entry must be an object")
        path = _v4_global(_v4_scope, '_safe_manifest_file')(root, item.get("path"))
        if path.suffix.lower() != ".parquet":
            raise _v4_global(_v4_scope, 'AuthorityError')(f"offline source must be parquet: {path.name}")
        actual_sha = _v4_global(_v4_scope, 'sha256_file')(path)
        expected_sha = _v4_global(_v4_scope, 'str')(item.get("sha256", "")).strip()
        if not expected_sha or actual_sha != expected_sha:
            raise _v4_global(_v4_scope, 'AuthorityError')(f"offline source SHA mismatch: {path.name}")
        try:
            frame = _v4_global(_v4_scope, 'pd').read_parquet(path)
        except _v4_global(_v4_scope, 'Exception') as error:
            raise _v4_global(_v4_scope, 'AuthorityError')(f"offline parquet unreadable: {path}") from error
        expected_rows = item.get("rows")
        if expected_rows is not None and _v4_global(_v4_scope, 'int')(expected_rows) != _v4_global(_v4_scope, 'len')(frame):
            raise _v4_global(_v4_scope, 'AuthorityError')(f"offline source row count mismatch: {path.name}")
        frames.append(frame)
        file_sha_values.append(actual_sha)
        total_manifest_rows += _v4_global(_v4_scope, 'len')(frame)
    source_sha = _v4_global(_v4_scope, 'str')(manifest.get("source_sha256", "")).strip()
    if _v4_global(_v4_scope, 'len')(file_sha_values) == 1:
        computed_source_sha = file_sha_values[0]
    else:
        computed_source_sha = _v4_global(_v4_scope, '_sha256_bytes')("\n".join(_v4_global(_v4_scope, 'sorted')(file_sha_values)).encode("ascii"))
    if not source_sha or source_sha != computed_source_sha:
        raise _v4_global(_v4_scope, 'AuthorityError')("offline source_sha256 mismatch")
    frame = _v4_global(_v4_scope, 'pd').concat(frames, ignore_index=True) if _v4_global(_v4_scope, 'len')(frames) > 1 else frames[0].copy()
    if manifest.get("coverage", {}).get("rows") is not None and _v4_global(_v4_scope, 'int')(manifest["coverage"]["rows"]) != total_manifest_rows:
        raise _v4_global(_v4_scope, 'AuthorityError')("offline coverage row count mismatch")
    expected_symbols = manifest.get("coverage", {}).get("symbols")
    if expected_symbols is not None:
        if "ts_code" not in frame.columns or _v4_global(_v4_scope, 'int')(expected_symbols) != _v4_global(_v4_scope, 'int')(frame["ts_code"].nunique()):
            raise _v4_global(_v4_scope, 'AuthorityError')("offline coverage symbol count mismatch")
    manifest["_manifest_path"] = _v4_global(_v4_scope, 'str')(manifest_file)
    manifest["_input_root"] = _v4_global(_v4_scope, 'str')(root)
    manifest["_source_files_sha256"] = file_sha_values
    manifest["_source_rows"] = total_manifest_rows
    return _v4_global(_v4_scope, '_normalize_input_frame')(frame, target_date), manifest
