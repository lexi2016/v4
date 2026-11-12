from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest


FROZEN_ORIGINAL_1700 = Path(__file__).resolve().parents[2] / "integration" / "original1700-frozen"
REAL_TDX_ROOT = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v35.local/state/research_panel_daily/tdx"
)


def _write_frozen_run_timeout_script(path: Path, *, mutation: str | None = None) -> None:
    """Replay the frozen owner summary/CSV without touching the native root."""
    path.write_text(
        f'''import csv
import json
from pathlib import Path

from ops.a_share_daily_sync import _local_history_status

FROZEN = Path({str(FROZEN_ORIGINAL_1700)!r})
RUN_DIR = None
MUTATION = {mutation!r}


def run(args):
    run_dir = Path(RUN_DIR)
    run_dir.mkdir(parents=True, exist_ok=True)
    summary = json.loads((FROZEN / "a_sync_authority__20260908__summary.json").read_text(encoding="utf-8"))
    csv_path = run_dir / "file_results.csv"
    csv_path.write_bytes((FROZEN / "file_results.csv").read_bytes())
    with csv_path.open("r", newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    reported = dict(summary)
    reported.pop("by_symbol", None)
    reported.pop("raw_response_snapshots", None)
    reported["run_dir"] = str(run_dir)
    reported["symbol_reconciliation"] = rows
    reported["reconciliation"] = dict(summary["reconciliation"])
    reported["reconciliation"]["symbols"] = rows
    reported["failures"] = [dict(failure) for failure in reported.get("failures") or []]
    if MUTATION == "RUNNING":
        for failure in reported["failures"]:
            if str(failure.get("failure_type") or "").startswith("A_SYNC_TIMEOUT:RUN"):
                failure["failure_type"] = "A_SYNC_TIMEOUT:RUNNING"
                break
    elif MUTATION == "GLOBAL":
        reported["failures"].append({{"failure_type": "A_SYNC_TIMEOUT:GLOBAL"}})
    return reported
''',
        encoding="utf-8",
    )


def _timeout_script(path: Path) -> None:
    path.write_text(
        """from pathlib import Path
RUN_DIR = None
def run(args):
    run_dir = Path(RUN_DIR)
    run_dir.mkdir(parents=True, exist_ok=True)
    return {
        'status': 'TIMEOUT',
        'exit_code': 124,
        'target_date': int(args.target_date),
        'target_count': 2,
        'accepted_count': 1,
        'quarantine_count': 0,
        'completed_count': 1,
        'pending_count': 1,
        'timeout': True,
        'timeout_scope': 'RUN',
        'progress_path': str(run_dir / 'progress.json'),
        'run_dir': str(run_dir),
        'reconciliation': {'pending_count': 1},
    }
""",
        encoding="utf-8",
    )


def test_timeout_authority_writes_cannot_confirm_and_never_materializes_formula(
    tmp_path: Path,
) -> None:
    from ops.macos_research_panel_daily import SnapshotGateError, run_windows_a_sync_authority

    script = tmp_path / "fake_timeout_sync.py"
    _timeout_script(script)
    receipt_root = tmp_path / "receipt"
    with pytest.raises(SnapshotGateError, match="stopped"):
        run_windows_a_sync_authority(
            script,
            tmp_path / "tdx",
            "20260907",
            receipt_root,
            authority_args={
                "request_deadline_seconds": 0.1,
                "symbol_budget_seconds": 0.2,
                "run_budget_seconds": 0.3,
            },
        )
    receipt = json.loads((receipt_root / "a_sync_authority.json").read_text(encoding="utf-8"))
    assert receipt["status"] == "CANNOT_CONFIRM"
    assert receipt["authority_status"] == "CANNOT_CONFIRM"
    assert receipt["first_failed_layer"] == "A_SYNC"
    assert receipt["reason_code"] == "A_SYNC_TIMEOUT"
    assert receipt["pending_count"] == 1
    assert receipt["RESEARCH_ONLY"] is True
    assert receipt["production_allowed"] is False


def test_authority_run_directory_is_target_date_bound(tmp_path: Path) -> None:
    from ops.macos_research_panel_daily import SnapshotGateError, run_windows_a_sync_authority

    script = tmp_path / "fake_timeout_sync.py"
    _timeout_script(script)
    with pytest.raises(SnapshotGateError):
        run_windows_a_sync_authority(script, tmp_path / "tdx", "20260907", tmp_path / "receipt")
    assert (tmp_path / "receipt" / "a_sync_authority" / "20260907").is_dir()
    assert not (tmp_path / "receipt" / "a_sync_authority" / "20260908").exists()



def _write_partial_sync_script(path: Path, accepted_count: int, pending_count: int = 0) -> None:
    script = r"""import csv
import hashlib
import json
from pathlib import Path
from ops.a_share_daily_sync import _local_history_status
RUN_DIR = None
ACCEPTED_COUNT = __COUNT__
PENDING_COUNT = __PENDING__
def run(args):
    root = Path(args.tdx_root)
    run_dir = Path(RUN_DIR)
    run_dir.mkdir(parents=True, exist_ok=True)
    files = sorted((root / 'vipdoc' / 'sh' / 'lday').glob('sh*.day'))
    descriptors = sorted(
        [{'code': source.stem[2:], 'market': 1, 'path': str(source.resolve())} for source in files],
        key=lambda item: (item['code'], item['market'], item['path']),
    )
    target_fingerprint = hashlib.sha256(
        json.dumps(descriptors, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
    ).hexdigest()
    with (run_dir / 'file_results.csv').open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=['path', 'fetch_status', 'status', 'classification', 'quarantine', 'source_sha256_after'])
        writer.writeheader()
        for index, source in enumerate(files):
            accepted = index < ACCEPTED_COUNT
            pending = ACCEPTED_COUNT <= index < ACCEPTED_COUNT + PENDING_COUNT
            writer.writerow({
                'path': str(source),
                'fetch_status': __FETCH_EXPR__,
                'status': __STATUS_EXPR__,
                'classification': __CLASS_EXPR__,
                'quarantine': '' if accepted or pending else 'true',
                'source_sha256_after': hashlib.sha256(source.read_bytes()).hexdigest() if accepted else '',
            })
    with (run_dir / 'file_results.csv').open(newline='', encoding='utf-8') as handle:
        emitted_rows = list(csv.DictReader(handle))
    return {
        'status': 'PASS' if ACCEPTED_COUNT == len(files) and PENDING_COUNT == 0 else 'FAILED',
        'exit_code': 0 if ACCEPTED_COUNT == len(files) and PENDING_COUNT == 0 else 2,
        'target_date': int(args.target_date),
        'target_fingerprint': target_fingerprint,
        'target_count': len(files),
        'accepted_count': ACCEPTED_COUNT,
        'quarantine_count': __QUARANTINE_EXPR__,
        'completed_count': ACCEPTED_COUNT,
        'pending_count': __PENDING_VALUE__,
        'timeout': False,
        'interrupted': False,
        'run_dir': str(run_dir),
        'symbol_reconciliation': emitted_rows,
        'reconciliation': {
            'target_count': len(files),
            'accepted_count': ACCEPTED_COUNT,
            'quarantine_count': __QUARANTINE_EXPR__,
            'pending_count': __PENDING_VALUE__,
            'symbols': emitted_rows,
        },
    }
"""
    fetch_expr = "'OK' if accepted else 'REBUILD_REQUIRED'"
    status_expr = "'UPDATED' if accepted else 'FAILED'"
    class_expr = "'ACCEPTED' if accepted else 'QUARANTINED'"
    quarantine_expr = 'len(files) - ACCEPTED_COUNT'
    if pending_count:
        fetch_expr = "'OK' if accepted else ('A_SYNC_TIMEOUT' if pending else 'REBUILD_REQUIRED')"
        status_expr = "'UPDATED' if accepted else ('CANNOT_CONFIRM' if pending else 'FAILED')"
        class_expr = "'ACCEPTED' if accepted else ('UNPROCESSED' if pending else 'QUARANTINED')"
        quarantine_expr = 'len(files) - ACCEPTED_COUNT - PENDING_COUNT'
    rendered = (
        script.replace('__COUNT__', str(accepted_count))
        .replace('__PENDING__', str(pending_count))
        .replace('__FETCH_EXPR__', fetch_expr)
        .replace('__STATUS_EXPR__', status_expr)
        .replace('__CLASS_EXPR__', class_expr)
        .replace('__QUARANTINE_EXPR__', quarantine_expr)
        .replace('__PENDING_VALUE__', str(pending_count))
    )
    path.write_text(rendered, encoding='utf-8')


def _write_synthetic_a_files(root: Path, count: int) -> None:
    from ops.a_share_daily_sync import pack_hq_bar

    bar = {
        "year": 2026,
        "month": 9,
        "day": 7,
        "open": 10.0,
        "high": 10.2,
        "low": 9.8,
        "close": 10.1,
        "amount": 1000.0,
        "vol": 100.0,
    }
    directory = root / "vipdoc" / "sh" / "lday"
    directory.mkdir(parents=True, exist_ok=True)
    prefixes = ("600", "601", "603", "605", "688", "689")
    for index in range(count):
        prefix = prefixes[index // 1000]
        code = f"{prefix}{index % 1000:03d}"
        (directory / f"sh{code}.day").write_bytes(pack_hq_bar(bar))


def test_partial_authority_keeps_original_5000_floor_for_rebuild_required(tmp_path: Path) -> None:
    from ops.macos_research_panel_daily import SnapshotGateError, run_windows_a_sync_authority

    for accepted_count, expected in ((4999, "FAIL"), (5000, "PASS")):
        root = tmp_path / f"tdx-{accepted_count}"
        _write_synthetic_a_files(root, 5001)
        script = tmp_path / f"partial-{accepted_count}.py"
        _write_partial_sync_script(script, accepted_count)
        receipt_root = tmp_path / f"receipt-{accepted_count}"
        if expected == "FAIL":
            with pytest.raises(SnapshotGateError, match="< 5000"):
                run_windows_a_sync_authority(
                    script,
                    root,
                    "20260907",
                    receipt_root,
                    minimum_target_date_files=5000,
                )
        else:
            result = run_windows_a_sync_authority(
                script,
                root,
                "20260907",
                receipt_root,
                minimum_target_date_files=5000,
            )
            manifest = json.loads(Path(result["formula_input_manifest"]).read_text(encoding="utf-8"))
            assert result["authority_status"] == "REBUILD_REQUIRED"
            assert result["accepted_count"] == 5000
            assert result["formula_input_mode"] == "ACCEPTED_ONLY"
            assert len(manifest["files"]) == 5000


def test_partial_authority_materializes_accepted_only_with_pending_and_keeps_provider_diagnostic(
    tmp_path: Path,
) -> None:
    from ops.macos_research_panel_daily import SnapshotGateError, run_windows_a_sync_authority

    root = tmp_path / "pending"
    _write_synthetic_a_files(root, 5002)
    script = tmp_path / "pending.py"
    _write_partial_sync_script(script, 5000, pending_count=1)
    result = run_windows_a_sync_authority(
        script,
        root,
        "20260907",
        tmp_path / "receipt-pending",
        minimum_target_date_files=5000,
    )
    assert result["authority_status"] == "REBUILD_REQUIRED"
    assert result["accepted_count"] == 5000
    assert result["quarantine_count"] == 1
    assert result["pending_count"] == 1
    assert result["formula_input_mode"] == "ACCEPTED_ONLY"
    manifest = json.loads(Path(result["formula_input_manifest"]).read_text(encoding="utf-8"))
    assert len(manifest["files"]) == 5000
    assert manifest["excluded_rebuild_candidate_count"] == 2
    receipt = json.loads(
        (tmp_path / "receipt-pending" / "a_sync_authority.json").read_text(encoding="utf-8")
    )
    assert receipt["pending_count"] == 1
    assert receipt["authority_status"] == "REBUILD_REQUIRED"
    pending_paths = {
        row["path"]
        for row in receipt["authority"]["symbol_reconciliation"]
        if row["classification"] == "UNPROCESSED"
    }
    assert pending_paths.isdisjoint({item["path"] for item in manifest["files"]})

    # A failed endpoint is retained as a diagnostic when a healthy provider
    # supplied an accepted subset; it is not a run-wide failure by itself.
    root = tmp_path / "healthy-failover"
    _write_synthetic_a_files(root, 2)
    script = tmp_path / "healthy-failover.py"
    _write_partial_sync_script(script, 1)
    script.write_text(
        script.read_text(encoding="utf-8").replace(
            "'pending_count': 0,",
            "'pending_count': 0, 'failed_hosts': ['h1:7709'],",
        ),
        encoding="utf-8",
    )
    result = run_windows_a_sync_authority(
        script, root, "20260907", tmp_path / "receipt-healthy-failover", minimum_target_date_files=1
    )
    assert result["authority_status"] == "REBUILD_REQUIRED"
    assert result["authority"]["failed_hosts"] == ["h1:7709"]


def test_original_public_entry_admits_frozen_run_timeout_as_accepted_only(tmp_path: Path) -> None:
    from ops.macos_research_panel_daily import run_windows_a_sync_authority

    script = tmp_path / "frozen-original-1700-timeout.py"
    _write_frozen_run_timeout_script(script)
    receipt_root = tmp_path / "receipt-frozen-original-1700"
    result = run_windows_a_sync_authority(
        script,
        REAL_TDX_ROOT,
        "20260908",
        receipt_root,
        minimum_target_date_files=5000,
    )

    assert result["status"] == "READY"
    assert result["authority_status"] == "REBUILD_REQUIRED"
    assert result["target_date"] == 20260908
    assert result["target_scope_file_count"] == 5800
    assert result["target_count"] == 5800
    assert result["accepted_count"] == 5040
    assert result["quarantine_count"] == 395
    assert result["pending_count"] == 365
    assert result["formula_input_mode"] == "ACCEPTED_ONLY"
    assert result["accepted_target_date_file_count"] == 5040
    assert result["excluded_rebuild_candidate_count"] == 760

    raw = result["authority"]
    assert raw["status"] == "TIMEOUT"
    assert raw["exit_code"] == 124
    assert raw["timeout"] is True
    assert raw["interrupted"] is False
    assert raw["timeout_scope"] == "RUN"
    assert raw["authority_status"] == "CANNOT_CONFIRM"
    assert raw["pending_count"] == 365
    assert raw["quarantine_count"] == 395
    assert raw["failures"]
    assert any(
        str(failure.get("failure_type", "")).startswith("A_SYNC_TIMEOUT:RUN")
        for failure in raw["failures"]
    )

    manifest = json.loads(Path(result["formula_input_manifest"]).read_text(encoding="utf-8"))
    assert manifest["authority_status"] == "REBUILD_REQUIRED"
    assert manifest["target_date"] == 20260908
    assert len(manifest["files"]) == 5040
    assert manifest["excluded_rebuild_candidate_count"] == 760
    assert {entry["fetch_status"] for entry in manifest["files"]} <= {
        "OK",
        "OK_WITH_SKIPPED_INVALID",
        "ALREADY_CURRENT",
        "CURRENT",
        "REVALIDATED",
        "TRUSTED_CAS_REUSE",
    }
    authority_receipt = json.loads((receipt_root / "a_sync_authority.json").read_text(encoding="utf-8"))
    assert authority_receipt["status"] == "READY"
    assert authority_receipt["authority_status"] == "REBUILD_REQUIRED"
    assert authority_receipt["authority"]["status"] == "TIMEOUT"
    assert authority_receipt["authority"]["exit_code"] == 124
    Path(result["formula_input_manifest"]).relative_to(receipt_root)


@pytest.mark.parametrize("mutation", ["RUNNING", "GLOBAL"])
def test_original_public_entry_rejects_unrecognized_timeout_scope(
    tmp_path: Path, mutation: str
) -> None:
    from ops.macos_research_panel_daily import SnapshotGateError, run_windows_a_sync_authority

    script = tmp_path / f"frozen-original-1700-timeout-{mutation.lower()}.py"
    _write_frozen_run_timeout_script(script, mutation=mutation)
    receipt_root = tmp_path / f"receipt-frozen-original-1700-timeout-{mutation.lower()}"
    with pytest.raises(SnapshotGateError, match="stopped"):
        run_windows_a_sync_authority(
            script,
            REAL_TDX_ROOT,
            "20260908",
            receipt_root,
            minimum_target_date_files=5000,
        )

    receipt = json.loads((receipt_root / "a_sync_authority.json").read_text(encoding="utf-8"))
    assert receipt["status"] == "CANNOT_CONFIRM"
    assert receipt["authority_status"] == "CANNOT_CONFIRM"
    failure_types = {
        str(failure.get("failure_type") or "")
        for failure in receipt["authority"]["failures"]
    }
    assert f"A_SYNC_TIMEOUT:{mutation}" in failure_types
    assert not list(receipt_root.rglob("manifest.json"))


def test_partial_authority_rejects_reported_date_mismatch(tmp_path: Path) -> None:
    from ops.macos_research_panel_daily import SnapshotGateError, run_windows_a_sync_authority

    root = tmp_path / "tdx-date"
    _write_synthetic_a_files(root, 2)
    script = tmp_path / "date.py"
    _write_partial_sync_script(script, 1)
    script.write_text(
        script.read_text(encoding="utf-8").replace("'target_date': int(args.target_date)", "'target_date': 20260906"),
        encoding="utf-8",
    )
    with pytest.raises(SnapshotGateError, match="date mismatch"):
        run_windows_a_sync_authority(script, root, "20260907", tmp_path / "receipt-date")


def test_partial_authority_binds_source_sha_and_accepts_revalidated_status(tmp_path: Path) -> None:
    from ops.macos_research_panel_daily import SnapshotGateError, run_windows_a_sync_authority

    root = tmp_path / "tdx-sha"
    _write_synthetic_a_files(root, 2)
    drift = tmp_path / "drift.py"
    _write_partial_sync_script(drift, 1)
    drift_text = drift.read_text(encoding="utf-8").replace(
        "    return {\n",
        "    changed = bytearray(files[0].read_bytes()); changed[4] ^= 1; files[0].write_bytes(changed)\n    return {\n",
        1,
    )
    drift.write_text(drift_text, encoding="utf-8")
    with pytest.raises(SnapshotGateError, match="SHA"):
        run_windows_a_sync_authority(drift, root, "20260907", tmp_path / "receipt-drift")

    root = tmp_path / "tdx-revalidated"
    _write_synthetic_a_files(root, 2)
    revalidated = tmp_path / "revalidated.py"
    _write_partial_sync_script(revalidated, 1)
    revalidated.write_text(
        revalidated.read_text(encoding="utf-8")
        .replace("'fetch_status': 'OK' if accepted else 'REBUILD_REQUIRED'", "'fetch_status': 'REVALIDATED' if accepted else 'REBUILD_REQUIRED'")
        .replace("'status': 'UPDATED' if accepted else 'FAILED'", "'status': 'REVALIDATED_CURRENT' if accepted else 'FAILED'"),
        encoding="utf-8",
    )
    result = run_windows_a_sync_authority(
        revalidated, root, "20260907", tmp_path / "receipt-revalidated", minimum_target_date_files=1
    )
    assert result["authority_status"] == "REBUILD_REQUIRED"
    assert result["accepted_count"] == 1
    assert result["formula_input_mode"] == "ACCEPTED_ONLY"


def test_authority_rejects_contradictory_native_row_tuple(tmp_path: Path) -> None:
    from ops.macos_research_panel_daily import SnapshotGateError, run_windows_a_sync_authority

    root = tmp_path / "contradictory-row"
    _write_synthetic_a_files(root, 2)
    script = tmp_path / "contradictory-row.py"
    _write_partial_sync_script(script, 1)
    script.write_text(
        script.read_text(encoding="utf-8").replace(
            "'fetch_status': 'OK' if accepted else 'REBUILD_REQUIRED'",
            "'fetch_status': 'REBUILD_REQUIRED' if accepted else 'REBUILD_REQUIRED'",
        ),
        encoding="utf-8",
    )
    with pytest.raises(SnapshotGateError, match="unknown row classification"):
        run_windows_a_sync_authority(script, root, "20260907", tmp_path / "receipt-contradictory")


def test_authority_cross_checks_nested_rows_and_counts(tmp_path: Path) -> None:
    from ops.macos_research_panel_daily import SnapshotGateError, run_windows_a_sync_authority

    root = tmp_path / "nested-drift"
    _write_synthetic_a_files(root, 2)
    script = tmp_path / "nested-drift.py"
    _write_partial_sync_script(script, 1)
    original = script.read_text(encoding="utf-8")
    original = original.replace(
        "    return {\n",
        "    with (run_dir / 'file_results.csv').open(newline='', encoding='utf-8') as handle:\n"
        "        emitted_rows = list(csv.DictReader(handle))\n"
        "    return {\n",
        1,
    )
    original = original.replace(
        "'symbol_reconciliation': emitted_rows,\n"
        "        'reconciliation': {\n"
        "            'target_count': len(files),\n"
        "            'accepted_count': ACCEPTED_COUNT,\n"
        "            'quarantine_count': len(files) - ACCEPTED_COUNT,\n"
        "            'pending_count': 0,\n"
        "            'symbols': emitted_rows,\n"
        "        },",
        "'symbol_reconciliation': emitted_rows,\n"
        "        'reconciliation': {'target_count': 999, 'accepted_count': ACCEPTED_COUNT, "
        "'quarantine_count': len(files) - ACCEPTED_COUNT, 'pending_count': 0, "
        "'symbols': emitted_rows},",
    )
    script.write_text(original, encoding="utf-8")
    with pytest.raises(SnapshotGateError, match="nested reconciliation metric mismatch"):
        run_windows_a_sync_authority(script, root, "20260907", tmp_path / "receipt-nested")

    root = tmp_path / "nested-row-drift"
    _write_synthetic_a_files(root, 2)
    script = tmp_path / "nested-row-drift.py"
    _write_partial_sync_script(script, 1)
    original = script.read_text(encoding="utf-8").replace(
        "    return {\n",
        "    with (run_dir / 'file_results.csv').open(newline='', encoding='utf-8') as handle:\n"
        "        emitted_rows = list(csv.DictReader(handle))\n"
        "    return {\n",
        1,
    ).replace(
        "'symbol_reconciliation': emitted_rows,\n"
        "        'reconciliation': {\n"
        "            'target_count': len(files),\n"
        "            'accepted_count': ACCEPTED_COUNT,\n"
        "            'quarantine_count': len(files) - ACCEPTED_COUNT,\n"
        "            'pending_count': 0,\n"
        "            'symbols': emitted_rows,\n"
        "        },",
        "'symbol_reconciliation': emitted_rows,\n"
        "        'reconciliation': {'target_count': len(files), 'accepted_count': ACCEPTED_COUNT, "
        "'quarantine_count': len(files) - ACCEPTED_COUNT, 'pending_count': 0, 'symbols': []},",
    )
    script.write_text(original, encoding="utf-8")
    with pytest.raises(SnapshotGateError, match="nested reconciliation rows mismatch"):
        run_windows_a_sync_authority(script, root, "20260907", tmp_path / "receipt-nested-rows")


def test_authority_rejects_missing_nested_reconciliation_members(tmp_path: Path) -> None:
    from ops.macos_research_panel_daily import SnapshotGateError, run_windows_a_sync_authority

    root = tmp_path / "nested-missing-symbols"
    _write_synthetic_a_files(root, 2)
    script = tmp_path / "nested-missing-symbols.py"
    _write_partial_sync_script(script, 2)
    original = script.read_text(encoding="utf-8").replace(
        "'symbol_reconciliation': emitted_rows,\n"
        "        'reconciliation': {\n"
        "            'target_count': len(files),\n"
        "            'accepted_count': ACCEPTED_COUNT,\n"
        "            'quarantine_count': len(files) - ACCEPTED_COUNT,\n"
        "            'pending_count': 0,\n"
        "            'symbols': emitted_rows,\n"
        "        },",
        "'reconciliation': {\n"
        "            'target_count': 999,\n"
        "            'accepted_count': 999,\n"
        "            'quarantine_count': 0,\n"
        "            'pending_count': 0,\n"
        "        },",
    )
    script.write_text(original, encoding="utf-8")
    with pytest.raises(SnapshotGateError, match="missing required fields: symbols"):
        run_windows_a_sync_authority(script, root, "20260907", tmp_path / "receipt-nested-missing-symbols")


def test_authority_reads_global_failure_from_progress_but_keeps_symbol_timeout_local(
    tmp_path: Path,
) -> None:
    from ops.macos_research_panel_daily import SnapshotGateError, run_windows_a_sync_authority

    root = tmp_path / "progress-global"
    _write_synthetic_a_files(root, 2)
    script = tmp_path / "progress-global.py"
    _write_partial_sync_script(script, 1)
    original = script.read_text(encoding="utf-8").replace(
        "'symbol_reconciliation': emitted_rows,\n"
        "        'reconciliation': {\n"
        "            'target_count': len(files),\n"
        "            'accepted_count': ACCEPTED_COUNT,\n"
        "            'quarantine_count': len(files) - ACCEPTED_COUNT,\n"
        "            'pending_count': 0,\n"
        "            'symbols': emitted_rows,\n"
        "        },",
        "'progress': {'failed_hosts': ['h1:7709'], 'global_failure': True},\n"
        "        'symbol_reconciliation': emitted_rows,\n"
        "        'reconciliation': {\n"
        "            'target_count': len(files),\n"
        "            'accepted_count': ACCEPTED_COUNT,\n"
        "            'quarantine_count': len(files) - ACCEPTED_COUNT,\n"
        "            'pending_count': 0,\n"
        "            'symbols': emitted_rows,\n"
        "        },",
    )
    script.write_text(original, encoding="utf-8")
    with pytest.raises(SnapshotGateError, match="global provider failure"):
        run_windows_a_sync_authority(script, root, "20260907", tmp_path / "receipt-progress-global")

    root = tmp_path / "symbol-timeout"
    _write_synthetic_a_files(root, 2)
    script = tmp_path / "symbol-timeout.py"
    _write_partial_sync_script(script, 1)
    original = script.read_text(encoding="utf-8").replace(
        "'symbol_reconciliation': emitted_rows,\n"
        "        'reconciliation': {\n"
        "            'target_count': len(files),\n"
        "            'accepted_count': ACCEPTED_COUNT,\n"
        "            'quarantine_count': len(files) - ACCEPTED_COUNT,\n"
        "            'pending_count': 0,\n"
        "            'symbols': emitted_rows,\n"
        "        },",
        "'timeout_scope': 'SYMBOL',\n"
        "        'failures': [{'failure_type': 'A_SYNC_TIMEOUT:SYMBOL'}],\n"
        "        'symbol_reconciliation': emitted_rows,\n"
        "        'reconciliation': {\n"
        "            'target_count': len(files),\n"
        "            'accepted_count': ACCEPTED_COUNT,\n"
        "            'quarantine_count': len(files) - ACCEPTED_COUNT,\n"
        "            'pending_count': 0,\n"
        "            'symbols': emitted_rows,\n"
        "        },",
    )
    script.write_text(original, encoding="utf-8")
    result = run_windows_a_sync_authority(
        script, root, "20260907", tmp_path / "receipt-symbol-timeout", minimum_target_date_files=1
    )
    assert result["authority_status"] == "REBUILD_REQUIRED"
    assert result["accepted_count"] == 1


def test_partial_authority_reuses_native_history_validator(tmp_path: Path) -> None:
    from ops.a_share_daily_sync import pack_hq_bar
    from ops.macos_research_panel_daily import SnapshotGateError, run_windows_a_sync_authority

    root = tmp_path / "malformed-history"
    _write_synthetic_a_files(root, 2)
    malformed = root / "vipdoc" / "sh" / "lday" / "sh600000.day"
    malformed.write_bytes(
        pack_hq_bar({
            "year": 2026,
            "month": 8,
            "day": 0,
            "open": 10.0,
            "high": 10.2,
            "low": 9.8,
            "close": 10.1,
            "amount": 1000.0,
            "vol": 100.0,
        })
        + malformed.read_bytes()
    )
    script = tmp_path / "malformed-history.py"
    _write_partial_sync_script(script, 1)
    with pytest.raises(SnapshotGateError, match="native history validation"):
        run_windows_a_sync_authority(script, root, "20260907", tmp_path / "receipt-malformed-history")


@pytest.mark.parametrize("mutation,expected", [("extra", "canonical scope drift"), ("sha", "source SHA drift")])
def test_full_sync_rechecks_frozen_scope_and_source_hashes(
    tmp_path: Path, mutation: str, expected: str
) -> None:
    from ops.macos_research_panel_daily import SnapshotGateError, run_windows_a_sync_authority

    root = tmp_path / f"full-drift-{mutation}"
    _write_synthetic_a_files(root, 2)
    script = tmp_path / f"full-drift-{mutation}.py"
    _write_partial_sync_script(script, 2)
    text = script.read_text(encoding="utf-8")
    if mutation == "extra":
        text = text.replace(
            "    with (run_dir / 'file_results.csv').open",
            "    (root / 'vipdoc' / 'sh' / 'lday' / 'sh600999.day').write_bytes(files[0].read_bytes())\n"
            "    with (run_dir / 'file_results.csv').open",
        )
    else:
        text = text.replace(
            "    return {\n",
            "    changed = bytearray(files[0].read_bytes()); changed[4] ^= 1; files[0].write_bytes(changed)\n"
            "    return {\n",
            1,
        )
    script.write_text(text, encoding="utf-8")
    with pytest.raises(SnapshotGateError, match=expected):
        run_windows_a_sync_authority(script, root, "20260907", tmp_path / f"receipt-full-{mutation}")
