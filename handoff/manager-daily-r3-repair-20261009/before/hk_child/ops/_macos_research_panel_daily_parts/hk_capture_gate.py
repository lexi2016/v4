"""HK capture, manifest, panel, and security-master authority gate."""
from __future__ import annotations

from ._namespace import read_global as _v4_global


def run_hk_capture_gate(
    _v4_scope,
    /,
    *,
    target_date,
    args,
    authority_paths,
    python_executable,
):
    """Run the existing HK owner chain against one immutable Futu capture."""
    target = target_date
    capture_manifest_path = args.receipt_root / "hk_capture" / target / (
        f"{target}-{_v4_global(_v4_scope, 'os').getpid()}-"
        f"{_v4_global(_v4_scope, 'os').urandom(12).hex()}.json"
    )
    env = _v4_global(_v4_scope, 'os').environ
    ensure_module = _v4_global(_v4_scope, 'importlib').import_module(
        "ops.ensure_hk_security_master"
    )
    asset_root = args.hk_asset_root.expanduser().resolve()
    store_root = asset_root.parent.parent
    package_root = _v4_global(_v4_scope, 'Path')(
        authority_paths["--hk-updater-script"]
    ).expanduser().resolve().parents[1]
    membership_result = {}

    def publish_membership(capture):
        membership_result.update(ensure_module.ensure_hk_security_master(
            store_root=store_root,
            universe_root=store_root,
            shared_package_root=package_root,
            trade_date=target,
            futu_python=python_executable,
            capture=capture,
            membership_only=True,
        ))

    previous_capture_path = env.get("V35_HK_CAPTURE_PATH")
    previous_capture_run_id = env.get("V35_HK_CAPTURE_RUN_ID")
    env["V35_HK_CAPTURE_PATH"] = str(capture_manifest_path)
    env["V35_HK_CAPTURE_RUN_ID"] = capture_manifest_path.stem
    try:
        collector = _v4_global(_v4_scope, 'importlib').import_module(
            "ops._macos_research_panel_daily_parts.hk_market_capture"
        )
        collected = collector._collect_hk_futu_rows_body(
            _v4_scope,
            target,
            context_factory=None,
            batch_size=200,
            minimum_universe_count=600,
            required_coverage_ratio=0.0,
            membership_ready_callback=publish_membership,
        )
    finally:
        if previous_capture_path is None:
            env.pop("V35_HK_CAPTURE_PATH", None)
        else:
            env["V35_HK_CAPTURE_PATH"] = previous_capture_path
        if previous_capture_run_id is None:
            env.pop("V35_HK_CAPTURE_RUN_ID", None)
        else:
            env["V35_HK_CAPTURE_RUN_ID"] = previous_capture_run_id

    reported_capture_path = (
        collected.get("capture_manifest_path")
        if _v4_global(_v4_scope, 'isinstance')(collected, _v4_global(_v4_scope, 'Mapping'))
        else None
    )
    if not reported_capture_path:
        raise _v4_global(_v4_scope, 'SnapshotGateError')(
            "HK collector did not return its exact capture manifest path"
        )
    reported_capture_path = _v4_global(_v4_scope, 'Path')(str(reported_capture_path)).expanduser()
    if reported_capture_path.is_symlink():
        raise _v4_global(_v4_scope, 'SnapshotGateError')(
            "HK capture manifest path must not be a symlink"
        )
    capture_manifest_path = reported_capture_path.resolve()
    try:
        capture_manifest_path.relative_to(args.receipt_root.expanduser().resolve())
    except ValueError as error:
        raise _v4_global(_v4_scope, 'SnapshotGateError')(
            "HK collector returned a capture path outside receipt root"
        ) from error

    capture = None
    try:
        envelope = _v4_global(_v4_scope, 'json').loads(
            capture_manifest_path.read_bytes().decode("utf-8-sig")
        )
        envelope_data = envelope if _v4_global(_v4_scope, 'isinstance')(
            envelope, _v4_global(_v4_scope, 'Mapping')
        ) else {}
        candidate = envelope_data.get("capture")
        if not _v4_global(_v4_scope, 'isinstance')(
            candidate, _v4_global(_v4_scope, 'Mapping')
        ):
            raise _v4_global(_v4_scope, 'SnapshotGateError')(
                "HK capture manifest capture payload is invalid"
            )
        raw_reference = envelope_data.get("capture_relative_path") or envelope_data.get(
            "capture_path"
        )
        if (
            not _v4_global(_v4_scope, 'isinstance')(raw_reference, _v4_global(_v4_scope, 'str'))
            or not raw_reference
            or _v4_global(_v4_scope, 'Path')(raw_reference).is_absolute()
        ):
            raise _v4_global(_v4_scope, 'SnapshotGateError')(
                "HK capture raw path must be relative"
            )
        raw_unresolved = capture_manifest_path.parent / raw_reference
        if raw_unresolved.is_symlink():
            raise _v4_global(_v4_scope, 'SnapshotGateError')(
                "HK capture raw path must not be a symlink"
            )
        raw_path = raw_unresolved.resolve()
        try:
            raw_path.relative_to(capture_manifest_path.parent.resolve())
        except ValueError as error:
            raise _v4_global(_v4_scope, 'SnapshotGateError')(
                "HK capture raw path escapes manifest root"
            ) from error
        raw_bytes = raw_path.read_bytes()
        raw_candidate = _v4_global(_v4_scope, 'json').loads(raw_bytes.decode("utf-8-sig"))
        raw_sha256 = _v4_global(_v4_scope, 'hashlib').sha256(raw_bytes).hexdigest()
        valid_manifest = (
            raw_candidate == candidate
            and envelope_data.get("schema_version")
            == "v3.macos.research_panel_hk_capture_manifest.v1"
            and envelope_data.get("status") == "READY"
            and envelope_data.get("target_date") == target
            and envelope_data.get("capture_raw_sha256") == raw_sha256
            and envelope_data.get("capture_sha256") == candidate.get("capture_sha256")
            and envelope_data.get("codes") == candidate.get("codes")
        )
        if not valid_manifest:
            raise _v4_global(_v4_scope, 'SnapshotGateError')(
                "HK capture manifest is invalid or stale"
            )
        capture = candidate
    except (
        _v4_global(_v4_scope, 'OSError'),
        _v4_global(_v4_scope, 'UnicodeError'),
        _v4_global(_v4_scope, 'json').JSONDecodeError,
        _v4_global(_v4_scope, 'TypeError'),
        _v4_global(_v4_scope, 'ValueError'),
    ) as error:
        raise _v4_global(_v4_scope, 'SnapshotGateError')(
            "HK capture manifest cannot be confirmed"
        ) from error
    if not _v4_global(_v4_scope, 'isinstance')(
        capture, _v4_global(_v4_scope, 'Mapping')
    ):
        raise _v4_global(_v4_scope, 'SnapshotGateError')(
            "HK panel capture missing after collector"
        )
    membership_authority = membership_result.get("universe_authority")
    if (
        membership_result.get("capture_sha256") != capture.get("capture_sha256")
        or not _v4_global(_v4_scope, 'isinstance')(
            membership_authority, _v4_global(_v4_scope, 'Mapping')
        )
        or membership_authority.get("capture_sha256") != capture.get("capture_sha256")
        or membership_authority.get("capture_run_id") != capture.get("capture_run_id")
    ):
        raise _v4_global(_v4_scope, 'SnapshotGateError')(
            "HK membership publication identity differs from final capture"
        )

    ensure_module._validated_capture(capture, trade_date=target, panel_sha256=None)
    source_payload = capture["source_payload"]
    expected_panel_codes = set(capture["codes"]) - set(source_payload["excluded_codes"])
    if (
        not _v4_global(_v4_scope, 'isinstance')(collected, _v4_global(_v4_scope, 'Mapping'))
        or collected.get("target_date") != target
        or collected.get("rows") != capture["rows"]
        or collected.get("source_sha256") != capture["source_sha256"]
    ):
        raise _v4_global(_v4_scope, 'SnapshotGateError')(
            "HK snapshot coverage mismatch: collector rows differ from capture manifest"
        )
    packed = _v4_global(_v4_scope, 'pack_hk_day')(
        args.hk_tdx_root,
        capture["rows"],
        target_date=target,
        minimum_rows=600,
        expected_codes=expected_panel_codes,
    )

    packed_day_root = args.hk_tdx_root.expanduser().resolve() / "vipdoc" / "ds" / "lday"
    expected_day_names = {f"71#{code[3:]}.day" for code in expected_panel_codes}
    packed_files = packed.get("files") if _v4_global(
        _v4_scope, 'isinstance'
    )(packed, _v4_global(_v4_scope, 'Mapping')) else None
    if not _v4_global(_v4_scope, 'isinstance')(packed_files, _v4_global(_v4_scope, 'list')):
        raise _v4_global(_v4_scope, 'SnapshotGateError')(
            "HK packed panel file ledger missing"
        )
    packed_paths = set()
    for item in packed_files:
        if (
            not _v4_global(_v4_scope, 'isinstance')(item, _v4_global(_v4_scope, 'Mapping'))
            or not item.get("path")
        ):
            raise _v4_global(_v4_scope, 'SnapshotGateError')(
                "HK packed panel file ledger invalid"
            )
        path = _v4_global(_v4_scope, 'Path')(str(item["path"])).expanduser().resolve()
        try:
            path.relative_to(packed_day_root)
        except ValueError as error:
            raise _v4_global(_v4_scope, 'SnapshotGateError')(
                "HK packed panel file escapes TDX root"
            ) from error
        if not path.is_file():
            raise _v4_global(_v4_scope, 'SnapshotGateError')(
                "HK packed panel file missing"
            )
        packed_paths.add(path)
    actual_day_names = {path.name for path in packed_paths}
    if len(packed_paths) != len(packed_files) or actual_day_names != expected_day_names:
        raise _v4_global(_v4_scope, 'SnapshotGateError')(
            "HK packed panel code set mismatch: "
            f"actual={len(actual_day_names)},expected={len(expected_day_names)}"
        )

    stale_files = []
    orphan_files = []
    for path in sorted(packed_day_root.glob("*.day")):
        if not path.is_file() or path.name in expected_day_names:
            continue
        entry = {
            "path": str(path),
            "size_bytes": path.stat().st_size,
            "sha256": _v4_global(_v4_scope, 'hashlib').sha256(path.read_bytes()).hexdigest(),
        }
        bucket = (
            stale_files
            if path.name.startswith("71#")
            and path.name[3:-4].isdigit()
            and len(path.name[3:-4]) == 5
            else orphan_files
        )
        bucket.append(entry)

    authority = _v4_global(_v4_scope, 'run_hk_0_2_authority')(
        authority_paths["--hk-updater-script"],
        python_executable,
        authority_paths["--hk-asset-root"],
        args.hk_tdx_root,
        target,
    )
    panel_sha256 = authority.get("panel_sha256")
    if not ensure_module._is_sha256(panel_sha256):
        raise _v4_global(_v4_scope, 'SnapshotGateError')("HK panel authority SHA invalid")
    if authority.get("through_date_code_count") != len(expected_panel_codes):
        raise _v4_global(_v4_scope, 'SnapshotGateError')(
            "HK panel and Futu capture universe coverage mismatch"
        )
    panel_sha256 = ensure_module._read_verified_hk_panel_authority(
        asset_root=asset_root,
        package_root=package_root,
        authority=authority,
        trade_date=target,
    )
    try:
        manifest = _v4_global(_v4_scope, 'json').loads(
            (asset_root / str(authority["manifest_relative"])).read_text(encoding="utf-8")
        )
        panel_path = (asset_root / str(manifest["panel_relative"])).resolve()
        panel_path.relative_to(asset_root)
        panel_rows = _v4_global(_v4_scope, '_panel_frame')(panel_path)
    except Exception as error:
        raise _v4_global(_v4_scope, 'SnapshotGateError')(
            "HK panel authority parquet unreadable"
        ) from error
    raw_codes = [
        row.get("code_norm")
        for row in panel_rows
        if _v4_global(_v4_scope, '_compact_datetime')(row.get("trade_date_compact")) == target
    ]
    normalized_codes = [
        f"HK.{digits[-5:].zfill(5)}"
        if (digits := "".join(character for character in str(value or "") if character.isdigit()))
        else ""
        for value in raw_codes
    ]
    panel_codes = set(normalized_codes)
    if not raw_codes or any(not code for code in normalized_codes) or len(panel_codes) != len(raw_codes):
        raise _v4_global(_v4_scope, 'SnapshotGateError')(
            "HK panel authority target code_norm invalid"
        )
    verified_panel_sha256 = ensure_module._read_verified_hk_panel_authority(
        asset_root=asset_root,
        package_root=package_root,
        authority=authority,
        trade_date=target,
    )
    if verified_panel_sha256.lower() != panel_sha256.lower():
        raise _v4_global(_v4_scope, 'SnapshotGateError')(
            "HK panel SHA changed during code-set binding"
        )
    if panel_codes != expected_panel_codes:
        raise _v4_global(_v4_scope, 'SnapshotGateError')(
            f"HK panel code set mismatch: actual={len(panel_codes)},expected={len(expected_panel_codes)}"
        )
    panel_binding_sha256 = ensure_module._panel_capture_binding_sha256(
        capture, panel_sha256
    )
    security_master = ensure_module.ensure_hk_security_master(
        store_root=store_root,
        universe_root=store_root,
        shared_package_root=package_root,
        trade_date=target,
        futu_python=python_executable,
        capture=capture,
        panel_sha256=panel_sha256,
        panel_binding_sha256=panel_binding_sha256,
    )
    if security_master.get("panel_capture_binding_sha256") != panel_binding_sha256:
        raise _v4_global(_v4_scope, 'SnapshotGateError')(
            "HK panel capture binding SHA mismatch"
        )
    return {
        **collected,
        **packed,
        "authority": authority,
        "security_master": security_master,
        "panel_capture_binding_sha256": panel_binding_sha256,
        "source_sha256": collected["source_sha256"],
        "persistent_stale_files": stale_files,
        "persistent_orphan_files": orphan_files,
        "persistent_out_of_scope_count": len(stale_files) + len(orphan_files),
    }
