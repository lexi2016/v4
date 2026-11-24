"""Generate the HK-only overlay for one of the three pinned runtime roles."""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
from pathlib import Path

from ops.hk_day_uint32_preflight import (
    _pack_hk_day_uint32,
    _validate_pending_hk_sessions,
    _verify_hk_packed_panel,
)


LEGACY_PANEL_PATH = Path("ops/macos_research_panel_daily.py")
LEGACY_PANEL_SHA256 = "3562ce9bec5b84625fa744502043a7ffe7aea666bcd955fdce48398f7074543c"
HK_UPDATER_PATH = Path("shared_data/hk_0_2.py")
HK_UPDATER_PREIMAGE_SHA256 = {
    "child-updater": "45a5091cb26800b7ccf8d7c3c75b680e951d492ac8ceb5f30b80a1ff9a6eebac",
    "shared-updater": "6dde013afb9140728ec60bfc160976caf2e4e10ea181b984d5b1a6e5f33689a1",
}


_PACK_HK_WRAPPER = '''def pack_hk_day(destination: Path | str, rows: Iterable[Mapping[str, Any]], *, target_date: str, minimum_rows: int = 600, expected_codes: set[str] | None = None) -> dict[str, Any]:
    return _pack_hk_day_uint32(
        destination, rows, target_date=target_date, minimum_rows=minimum_rows,
        expected_codes=expected_codes, record_struct=HK_DAY_STRUCT,
        path_type=Path, rows_as_dicts=_rows, normalize_date=_date,
        validate_rows=_validate_rows, build_record=_hk_record,
        atomic_write=_atomic_write, grouped_result=_grouped_result,
        gate_error=SnapshotGateError, safety_flags=SAFETY_FLAGS,
    )
'''


def render_legacy_hk_day_module(preimage: bytes) -> bytes:
    """Bind the complete patched behavior to the existing child module pin."""
    if hashlib.sha256(preimage).hexdigest() != LEGACY_PANEL_SHA256:
        raise ValueError("legacy HK child module preimage SHA mismatch")

    def replace_once(old: str, new: str) -> None:
        nonlocal source
        if source.count(old) != 1:
            raise ValueError("legacy HK child patch anchor mismatch")
        source = source.replace(old, new, 1)

    source = preimage.decode("utf-8")
    start = source.index("def pack_hk_day(")
    stop = source.index("\n\ndef validate_snapshot(", start)
    replacement = "\n\n".join((
        inspect.getsource(_pack_hk_day_uint32).rstrip(),
        inspect.getsource(_verify_hk_packed_panel).rstrip(),
        _PACK_HK_WRAPPER.rstrip(),
    ))
    source = source[:start] + replacement + source[stop:]

    # Preserve Futu's raw field before the legacy float conversion and provide
    # the source's exact eligible membership separately from the rows to pack.
    replace_once(
        '                "volume": int(round(volume)),\n',
        '                "volume": source["volume"],\n',
    )
    replace_once(
        '        "universe_count": len(codes),\n',
        '        "universe_count": len(codes),\n'
        '        "expected_price_codes": [code for code in codes if code not in excluded],\n',
    )
    replace_once(
        '        packed = pack_hk_day(args.hk_tdx_root, collected["rows"], target_date=target, minimum_rows=600)\n',
        '        packed = pack_hk_day(\n'
        '            args.hk_tdx_root, collected["rows"], target_date=target, minimum_rows=600,\n'
        '            expected_codes=set(collected["expected_price_codes"]),\n'
        '        )\n',
    )
    replace_once(
        """        authority = run_hk_0_2_authority(
            authority_paths["--hk-updater-script"],
            python_executable,
            authority_paths["--hk-asset-root"],
            args.hk_tdx_root,
            target,
        )
        return {**collected, **packed, "authority": authority, "source_sha256": collected["source_sha256"]}
""",
        """        updater = authority_paths["--hk-updater-script"]
        asset_root = authority_paths["--hk-asset-root"]
        try:
            authority = run_hk_0_2_authority(updater, python_executable, asset_root, args.hk_tdx_root, target)
            if authority.get("through_date_code_count") != packed["packed_code_count"]:
                raise SnapshotGateError("HK authority exact-date coverage mismatch")
            _verify_hk_packed_panel(asset_root, updater, authority, target, packed["packed_codes"])
        except Exception as error:
            error.hk_pack_evidence = {
                key: packed[key] for key in ("expected_code_count", "packable_code_count", "packed_code_count",
                                            "new_day_write_count", "quarantine", "coverage_rate")
            }
            raise
        return {
            **collected, **packed, "authority": authority, "source_sha256": collected["source_sha256"],
            "source_coverage_rate": collected["coverage_rate"],
            "membership_packed_coverage_rate": packed["packed_code_count"] / collected["universe_count"],
        }
""",
    )
    replace_once(
        '            lanes[lane] = _receipt(Path(receipt_root), lane, target_date, {"status": "FAILED", "error": str(error), "coverage_rate": 0.0, "sha256": "", "runner_called": True, "receipt_written": True})\n',
        '            failure = {"status": "FAILED", "error": str(error), "coverage_rate": 0.0, "sha256": "", "runner_called": True, "receipt_written": True}\n'
        '            if lane == "HK" and hasattr(error, "hk_pack_evidence"):\n'
        '                failure["hk_pack_preflight"] = error.hk_pack_evidence\n'
        '            lanes[lane] = _receipt(Path(receipt_root), lane, target_date, failure)\n',
    )
    replace_once(
        """    completed = subprocess.run(argv, shell=False, check=True, capture_output=True, text=True)
    try:
        outcome = json.loads(completed.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError) as error:
        raise SnapshotGateError("HK authority output is not JSON") from error
    if outcome.get("status") != "READY" or _date(outcome.get("through_date")) != target:
        raise SnapshotGateError(f"HK authority through-date postcondition failed: {outcome}")
""",
        """    completed = subprocess.run(argv, shell=False, check=False, capture_output=True, text=True)
    try:
        outcome = json.loads(completed.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError) as error:
        raise SnapshotGateError("HK authority output is not JSON") from error
    if not isinstance(outcome, dict) or _date(outcome.get("through_date")) != target:
        raise SnapshotGateError("HK authority through-date identity mismatch")
    if any(outcome.get(key) is not False for key in SAFETY_FLAGS):
        raise SnapshotGateError("HK authority safety flags invalid")
    if completed.returncode != 0 or outcome.get("status") != "READY":
        detail = outcome.get("error") if outcome.get("status") == "FAILED" else None
        raise SnapshotGateError(f"HK authority failed: {str(detail or 'updater exit/status mismatch')[:1000]}")
""",
    )
    compile(source, str(LEGACY_PANEL_PATH), "exec")
    return source.encode("utf-8")


def render_legacy_hk_updater_module(preimage: bytes, *, role: str) -> bytes:
    """Keep the original updater, gating its one append before staging."""
    if hashlib.sha256(preimage).hexdigest() != HK_UPDATER_PREIMAGE_SHA256[role]:
        raise ValueError(f"legacy HK updater preimage SHA mismatch: {role}")
    source = preimage.decode("utf-8")
    function = "def update_hk_0_2_panel_from_vipdoc("
    after_dedup = '    increment = increment.drop_duplicates(["trade_date_compact", "code_norm"], keep="last")\n'
    start = source.index(function)
    run_end = source.index("\n\ndef ", start + len(function))
    if source.count(function) != 1 or source[start:run_end].count(after_dedup) != 1:
        raise ValueError(f"legacy HK updater patch anchor mismatch: {role}")
    run = source[start:run_end].replace(after_dedup, after_dedup + """    _validate_pending_hk_sessions(
        increment, after_date=current_max, through_date=through_date,
        minimum_code_count=minimum_code_count,
        minimum_positive_coverage_rate=minimum_positive_coverage_rate,
        store_error=StoreError,
    )
""", 1)
    source = (
        source[:start] + inspect.getsource(_validate_pending_hk_sessions).rstrip()
        + "\n\n\n" + run + source[run_end:]
    )
    compile(source, str(HK_UPDATER_PATH), "exec")
    return source.encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legacy-app-root", type=Path, required=True, help="source root of the selected runtime role")
    parser.add_argument("--overlay-root", type=Path, required=True)
    parser.add_argument("--role", choices=("child", *HK_UPDATER_PREIMAGE_SHA256), default="child")
    args = parser.parse_args()
    role = args.role
    relative = LEGACY_PANEL_PATH if role == "child" else HK_UPDATER_PATH
    source = args.legacy_app_root / relative
    if source.is_symlink():
        raise ValueError("legacy HK role preimage is a symlink")
    preimage = source.read_bytes()
    patched = (
        render_legacy_hk_day_module(preimage) if role == "child"
        else render_legacy_hk_updater_module(preimage, role=role)
    )
    args.overlay_root.mkdir(exist_ok=False)
    destination = args.overlay_root / relative
    destination.parent.mkdir()
    destination.write_bytes(patched)
    print(json.dumps({
        "role": role,
        "path": str(relative),
        "preimage_sha256": hashlib.sha256(preimage).hexdigest(),
        "overlay_sha256": hashlib.sha256(patched).hexdigest(),
        "overlay_root": str(args.overlay_root),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
