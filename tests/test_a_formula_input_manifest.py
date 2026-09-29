from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest


def _bar(date_value: int, close: float) -> dict[str, object]:
    return {
        "year": date_value // 10000,
        "month": date_value // 100 % 100,
        "day": date_value % 100,
        "open": close - 0.2,
        "high": close + 0.2,
        "low": close - 0.4,
        "close": close,
        "amount": 1000.0,
        "vol": 100.0,
    }


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_binding(tmp_path: Path) -> tuple[Path, Path, Path, list[dict[str, str]]]:
    from ops.a_share_daily_sync import pack_hq_bar

    tdx_root = tmp_path / "accepted-days"
    relatives = [
        "vipdoc/sh/lday/sh600001.day",
        "vipdoc/sz/lday/sz000001.day",
    ]
    entries: list[dict[str, str]] = []
    copy_entries: list[dict[str, object]] = []
    for index, relative in enumerate(relatives):
        path = tdx_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(
            b"".join(
                pack_hq_bar(_bar(date_value, 10.0 + index))
                for date_value in (20260910, 20260911)
            )
        )
        digest = _sha(path)
        entries.append(
            {
                "fetch_status": "ALREADY_CURRENT",
                "path": str(tmp_path / "source-promotion" / relative),
                "relative_path": relative,
                "sha256": digest,
            }
        )
        copy_entries.append({"relative_path": relative, "sha256": digest, "bytes": path.stat().st_size})

    accepted = {
        "authority_status": "REBUILD_REQUIRED",
        "buy_gate_updated": False,
        "excluded_rebuild_candidate_count": 2,
        "files": entries,
        "orders_sent": False,
        "production_allowed": False,
        "schema_version": "v3_5.a_sync.accepted_formula_input.v1",
        "source_run_dir": str(tmp_path / "source-run"),
        "target_date": 20260911,
    }
    accepted_path = tmp_path / "manifest.json"
    accepted_raw = (json.dumps(accepted, sort_keys=True, indent=2) + "\n").encode()
    accepted_path.write_bytes(accepted_raw)
    source_receipt = tmp_path / "source-receipt.json"
    source_receipt.write_text(json.dumps({"target_date": 20260911, "status": "READY"}) + "\n")
    copy = {
        "copied_count": len(entries),
        "excluded_rebuild_candidate_count": 2,
        "files": copy_entries,
        "formal_data_changed": False,
        "full_5800_authority_pass": False,
        "manifest_sha256": hashlib.sha256(accepted_raw).hexdigest(),
        "no_source_status_rewrite": True,
        "parquet_manifest_created": False,
        "source_authority_status": "REBUILD_REQUIRED",
        "source_receipt": str(source_receipt),
        "source_receipt_sha256": _sha(source_receipt),
        "source_root": str(tmp_path / "source-root"),
        "status": "COPIED_VERIFIED_ACCEPTED_SUBSET_ONLY",
        "target_date": "20260911",
        "target_root": str(tdx_root),
    }
    copy_path = tmp_path / "copy-receipt.json"
    copy_path.write_text(json.dumps(copy, sort_keys=True, indent=2) + "\n")
    return accepted_path, copy_path, tdx_root, entries


def test_accepted_only_subset_preserves_partial_authority_and_v4_shape(tmp_path: Path) -> None:
    from ops.a_formula_input_manifest import (
        build_accepted_only_a_formula_input_manifest,
    )
    from ops.a_formula_increment import _load_input_manifest

    accepted_path, copy_path, tdx_root, entries = _make_binding(tmp_path)
    output_root = tmp_path / "input"
    result = build_accepted_only_a_formula_input_manifest(
        accepted_manifest=accepted_path,
        copy_receipt=copy_path,
        tdx_root=tdx_root,
        output_root=output_root,
        target_date="20260911",
        run_id="accepted-only-subset-test",
        selected_relative_paths=[entries[0]["relative_path"]],
    )

    assert result["status"] == "READY_ACCEPTED_ONLY"
    assert result["scope"] == "ACCEPTED_ONLY_SUBSET"
    assert result["accepted_manifest_file_count"] == 2
    assert result["selected_file_count"] == 1
    assert result["authority_status"] == "REBUILD_REQUIRED"
    assert result["full_authority_pass"] is False
    manifest = json.loads(Path(result["path"]).read_text())
    assert manifest["schema"] == "v4.a_formula.input_manifest.v1"
    assert manifest["source"]["accepted_manifest_file_count"] == 2
    assert manifest["source"]["selected_file_count"] == 1
    assert manifest["source"]["authority_status"] == "REBUILD_REQUIRED"
    assert manifest["source"]["excluded_rebuild_candidate_count"] == 2
    frame, loaded = _load_input_manifest(output_root, output_root / "manifest.json", 20260911)
    assert len(loaded["files"]) == 1
    assert set(frame["trade_date"].astype(int)) == {20260910, 20260911}


def test_accepted_only_subset_does_not_open_unselected_source(tmp_path: Path) -> None:
    from ops.a_formula_input_manifest import build_accepted_only_a_formula_input_manifest

    accepted_path, copy_path, tdx_root, entries = _make_binding(tmp_path)
    unselected = tdx_root / entries[1]["relative_path"]
    unselected.unlink()

    result = build_accepted_only_a_formula_input_manifest(
        accepted_manifest=accepted_path,
        copy_receipt=copy_path,
        tdx_root=tdx_root,
        output_root=tmp_path / "subset-input",
        target_date="20260911",
        run_id="subset-missing-unselected",
        selected_relative_paths=[entries[0]["relative_path"]],
    )

    assert result["status"] == "READY_ACCEPTED_ONLY"
    assert result["accepted_manifest_file_count"] == 2
    assert result["selected_file_count"] == 1
    assert not unselected.exists()


def test_accepted_only_subset_keeps_unselected_collection_identity_gate(tmp_path: Path) -> None:
    from ops.a_formula_input_manifest import (
        InputManifestError,
        build_accepted_only_a_formula_input_manifest,
    )

    accepted_path, copy_path, tdx_root, entries = _make_binding(tmp_path)
    (tdx_root / entries[1]["relative_path"]).unlink()
    copy = json.loads(copy_path.read_text())
    copy["files"][1]["sha256"] = "0" * 64
    copy_path.write_text(json.dumps(copy, sort_keys=True, indent=2) + "\n")

    with pytest.raises(InputManifestError, match="copy SHA differs from manifest"):
        build_accepted_only_a_formula_input_manifest(
            accepted_manifest=accepted_path,
            copy_receipt=copy_path,
            tdx_root=tdx_root,
            output_root=tmp_path / "subset-input",
            target_date="20260911",
            run_id="subset-collection-gate",
            selected_relative_paths=[entries[0]["relative_path"]],
        )


def test_accepted_only_rejects_source_sha_drift_before_parquet_write(tmp_path: Path) -> None:
    from ops.a_formula_input_manifest import (
        InputManifestError,
        build_accepted_only_a_formula_input_manifest,
    )

    accepted_path, copy_path, tdx_root, entries = _make_binding(tmp_path)
    accepted = json.loads(accepted_path.read_text())
    accepted["files"][0]["sha256"] = "0" * 64
    accepted_raw = (json.dumps(accepted, sort_keys=True, indent=2) + "\n").encode()
    accepted_path.write_bytes(accepted_raw)
    copy = json.loads(copy_path.read_text())
    copy["manifest_sha256"] = hashlib.sha256(accepted_raw).hexdigest()
    copy["files"][0]["sha256"] = "0" * 64
    copy_path.write_text(json.dumps(copy, sort_keys=True, indent=2) + "\n")

    with pytest.raises(InputManifestError, match="source SHA mismatch"):
        build_accepted_only_a_formula_input_manifest(
            accepted_manifest=accepted_path,
            copy_receipt=copy_path,
            tdx_root=tdx_root,
            output_root=tmp_path / "input",
            target_date=20260911,
            selected_relative_paths=[entries[0]["relative_path"]],
        )


def test_accepted_only_rejects_source_receipt_sha_drift_before_parquet_write(tmp_path: Path) -> None:
    from ops.a_formula_input_manifest import (
        InputManifestError,
        build_accepted_only_a_formula_input_manifest,
    )

    accepted_path, copy_path, tdx_root, entries = _make_binding(tmp_path)
    copy = json.loads(copy_path.read_text())
    copy["source_receipt_sha256"] = "0" * 64
    copy_path.write_text(json.dumps(copy, sort_keys=True, indent=2) + "\n")

    with pytest.raises(InputManifestError, match="source receipt SHA mismatch"):
        build_accepted_only_a_formula_input_manifest(
            accepted_manifest=accepted_path,
            copy_receipt=copy_path,
            tdx_root=tdx_root,
            output_root=tmp_path / "input",
            target_date=20260911,
            selected_relative_paths=[entries[0]["relative_path"]],
        )


def test_accepted_only_rejects_full_authority_claim_and_empty_scope(tmp_path: Path) -> None:
    from ops.a_formula_input_manifest import (
        InputManifestError,
        build_accepted_only_a_formula_input_manifest,
    )

    accepted_path, copy_path, tdx_root, entries = _make_binding(tmp_path)
    copy = json.loads(copy_path.read_text())
    copy["full_5800_authority_pass"] = True
    copy_path.write_text(json.dumps(copy, sort_keys=True, indent=2) + "\n")
    with pytest.raises(InputManifestError, match="formal/full authority"):
        build_accepted_only_a_formula_input_manifest(
            accepted_manifest=accepted_path,
            copy_receipt=copy_path,
            tdx_root=tdx_root,
            output_root=tmp_path / "bad-full",
            target_date=20260911,
            selected_relative_paths=[entries[0]["relative_path"]],
        )

    copy["full_5800_authority_pass"] = False
    copy_path.write_text(json.dumps(copy, sort_keys=True, indent=2) + "\n")
    with pytest.raises(InputManifestError, match="selected scope cannot be empty"):
        build_accepted_only_a_formula_input_manifest(
            accepted_manifest=accepted_path,
            copy_receipt=copy_path,
            tdx_root=tdx_root,
            output_root=tmp_path / "bad-empty",
            target_date=20260911,
            selected_relative_paths=[],
        )
