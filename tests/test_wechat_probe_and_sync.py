from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import uuid
from pathlib import Path

import pytest

from infrastructure.preselection_pool_store import PreselectionPoolStore
from ops.wechat_preselection_sync import WechatSyncError, sync_wechat_preselection
from ops.wechat_probe import probe_wechat_account


EFFECTIVE_DATE = "20260821"
SIGNAL_DATE = "20260820"
SELECTOR_DATE = "20260818"
V35_CONTRACT = "V3_WECHAT_PRESELECT_TO_V35_EXACT_EFFECTIVE_DATE_V1"


@pytest.fixture
def allowed_root() -> Path:
    root = (
        Path.home()
        / "Documents"
        / "Codex"
        / f"v35-stage-selection-candidate-{os.getpid()}-{uuid.uuid4().hex}"
    )
    root.mkdir(parents=True)
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)
        shutil.rmtree(_output_root(root), ignore_errors=True)


def _output_root(root: Path) -> Path:
    return root.parent / f"{root.name}-output"


def _write_wechat_pair(root: Path, *, effective_date: str = EFFECTIVE_DATE) -> tuple[Path, Path]:
    day = root / effective_date
    day.mkdir(parents=True, exist_ok=True)
    fields = [
        "ts_code",
        "name",
        "trade_date",
        "publish_date",
        "wechat_v3_preselect_rank",
        "candidate_score",
        "v3_match",
        "formal_pool_write",
        "buy_gate_write",
        "wechat_pool_lane",
        "wechat_source_ref",
    ]
    rows = [
        {
            "ts_code": "000001.SZ",
            "name": "平安银行",
            "trade_date": SELECTOR_DATE,
            "publish_date": "2026-08-20",
            "wechat_v3_preselect_rank": "1",
            "candidate_score": "5.5",
            "v3_match": "True",
            "formal_pool_write": "False",
            "buy_gate_write": "False",
            "wechat_pool_lane": "research_lane_observation_preselect",
            "wechat_source_ref": "https://example.invalid/wechat/one",
        },
        {
            "ts_code": "600000.SH",
            "name": "浦发银行",
            "trade_date": SELECTOR_DATE,
            "publish_date": SIGNAL_DATE,
            "wechat_v3_preselect_rank": "2",
            "candidate_score": "4.25",
            "v3_match": "True",
            "formal_pool_write": "False",
            "buy_gate_write": "False",
            "wechat_pool_lane": "research_lane_observation_preselect",
            "wechat_source_ref": "https://example.invalid/wechat/two",
        },
    ]
    rows_path = day / "wechat_rows.csv"
    with rows_path.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    manifest = {
        "status": "WECHAT_V3_PRESELECT_READY",
        "signal_date": SIGNAL_DATE,
        "article_publish_date": SIGNAL_DATE,
        "target_date": SIGNAL_DATE,
        "effective_trade_date": effective_date,
        "selector_score_date": SELECTOR_DATE,
        "target_validation": {
            "status": "TARGET_DATE_CHECK_PASS",
            "target_date": SIGNAL_DATE,
            "date_match": True,
            "title_match": True,
            "allow_mismatch": False,
        },
        "score_scope": "wechat_pool_ts_codes_only",
        "counts": {
            "wechat_unique_codes": len(rows),
            "v3_matched_codes": len(rows),
            "v3_unmatched_codes": 0,
        },
        "boundary": {
            "lane": "research_lane_observation_preselect",
            "formal_pool_write": False,
            "buy_gate_write": False,
        },
        "v35_input_contract": V35_CONTRACT,
        "v35_input": {
            "effective_trade_date": effective_date,
            "selector_score_date": SELECTOR_DATE,
            "source_signal_date": SIGNAL_DATE,
            "source_rows_count": len(rows),
            "source_rows_sha256": hashlib.sha256(rows_path.read_bytes()).hexdigest(),
            "source_manifest_sha256": hashlib.sha256(b"publisher-manifest").hexdigest(),
            "source_fields": fields,
        },
    }
    manifest_path = day / "wechat_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return manifest_path, rows_path


@pytest.mark.parametrize(
    ("payload", "expected_status"),
    (
        (("", 0, "TimeoutError: profile unavailable"), "PROBE_UNAVAILABLE"),
        (("<html>环境异常 verify</html>", 200, ""), "PROBE_BLOCKED"),
        (("var msg_title=\"今日观察\"; https://mp.weixin.qq.com/s/AbC_123", 200, ""), "PROBE_FOUND"),
    ),
)
def test_profile_probe_three_typed_states_are_fail_closed(
    allowed_root: Path,
    payload: tuple[str, int, str],
    expected_status: str,
) -> None:
    receipt_path = allowed_root / f"{expected_status}.json"
    result = probe_wechat_account(
        biz="candidate-biz",
        fetcher=lambda *_args, **_kwargs: payload,
        receipt_path=receipt_path,
    )
    assert result["status"] == expected_status
    assert result["hint_only"] is True
    assert result["url_required"] is True
    assert result["no_run"] is True
    assert result["no_publish"] is True
    assert result["no_run_created"] is True
    assert result["publish"] is False
    assert result["exact_url"] is None
    assert json.loads(receipt_path.read_text(encoding="utf-8")) == result


def test_probe_found_cli_is_nonzero_hint_exit(allowed_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "ops.wechat_probe._fetch_profile",
        lambda *_args, **_kwargs: (
            'var msg_title="今日观察"; https://mp.weixin.qq.com/s/AbC_123',
            200,
            "",
        ),
    )
    from ops import wechat_probe

    assert wechat_probe.main(["--out", str(allowed_root)]) == 2


def test_probe_body_limit_is_fail_closed(allowed_root: Path) -> None:
    from ops import wechat_probe

    body = "x" * (wechat_probe.MAX_PROFILE_BODY_BYTES + 1)
    result = probe_wechat_account(
        fetcher=lambda *_args, **_kwargs: (body, 200, ""),
        receipt_path=allowed_root / "oversized.json",
    )
    assert result["status"] == "PROBE_UNAVAILABLE"
    assert "too large" in result["note"].lower()


def test_probe_rejects_unscoped_or_symlink_output(allowed_root: Path, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="allowed|scope"):
        probe_wechat_account(
            fetcher=lambda *_args, **_kwargs: ("", 200, ""),
            receipt_path=Path.home() / "Desktop" / "probe.json",
        )
    symlink = allowed_root / "probe-link.json"
    symlink.symlink_to(tmp_path / "outside.json")
    with pytest.raises(ValueError, match="symlink"):
        probe_wechat_account(
            fetcher=lambda *_args, **_kwargs: ("", 200, ""),
            receipt_path=symlink,
        )


def test_missing_exact_pair_is_cannot_confirm_without_writes(allowed_root: Path) -> None:
    output = _output_root(allowed_root)
    result = sync_wechat_preselection(
        EFFECTIVE_DATE,
        input_root=allowed_root / "active-input",
        data_root=output / "data",
        receipt_path=output / "receipt.json",
    )
    assert result["status"] == "CANNOT_CONFIRM"
    assert result["cannot_confirm"] == ["WECHAT_EXACT_DATE_INPUT_MISSING"]
    assert result["artifact_created"] is False
    assert result["no_run"] is True
    assert result["no_publish"] is True
    assert all(result[key] is False for key in ("production_allowed", "buy_gate_updated", "orders_sent"))
    assert not (output / "data").exists()


def test_sync_rejects_receipt_inside_read_only_input_root(allowed_root: Path) -> None:
    with pytest.raises(WechatSyncError, match="receipt|input root"):
        sync_wechat_preselection(
            EFFECTIVE_DATE,
            input_root=allowed_root,
            data_root=_output_root(allowed_root) / "data",
            receipt_path=allowed_root / "receipt.json",
        )


@pytest.mark.parametrize(
    "field", ("signal_date", "article_publish_date", "selector_score_date", "effective_trade_date")
)
def test_sync_rejects_impossible_calendar_dates(allowed_root: Path, field: str) -> None:
    manifest_path, _ = _write_wechat_pair(allowed_root)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest[field] = "20260230"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(WechatSyncError, match="date|trade-date"):
        sync_wechat_preselection(
            EFFECTIVE_DATE,
            input_root=allowed_root,
            data_root=_output_root(allowed_root) / "data",
        )


@pytest.mark.parametrize(
    ("field", "value"), (("date_match", False), ("title_match", False), ("allow_mismatch", True))
)
def test_sync_requires_target_identity_booleans(allowed_root: Path, field: str, value: bool) -> None:
    manifest_path, _ = _write_wechat_pair(allowed_root)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["target_validation"][field] = value
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(WechatSyncError, match="target"):
        sync_wechat_preselection(
            EFFECTIVE_DATE,
            input_root=allowed_root,
            data_root=_output_root(allowed_root) / "data",
        )


def test_sync_requires_target_date_equal_signal_date(allowed_root: Path) -> None:
    manifest_path, _ = _write_wechat_pair(allowed_root)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["target_validation"]["target_date"] = "20260819"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(WechatSyncError, match="target"):
        sync_wechat_preselection(
            EFFECTIVE_DATE,
            input_root=allowed_root,
            data_root=_output_root(allowed_root) / "data",
        )


@pytest.mark.parametrize(
    "mutation",
    (
        lambda manifest: manifest.pop("v35_input"),
        lambda manifest: manifest["v35_input"].update(source_rows_count=99),
        lambda manifest: manifest["v35_input"].update(source_rows_sha256="0" * 64),
        lambda manifest: manifest["v35_input"].update(source_manifest_sha256=""),
        lambda manifest: manifest.update(v35_input_contract="wrong"),
    ),
)
def test_sync_requires_v35_contract_and_hashes(allowed_root: Path, mutation) -> None:
    manifest_path, _ = _write_wechat_pair(allowed_root)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    mutation(manifest)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(WechatSyncError, match="v35|hash|contract"):
        sync_wechat_preselection(
            EFFECTIVE_DATE,
            input_root=allowed_root,
            data_root=_output_root(allowed_root) / "data",
        )


def test_sync_rejects_unsuffixed_code_without_inference(allowed_root: Path) -> None:
    manifest_path, rows_path = _write_wechat_pair(allowed_root)
    rows_path.write_text(
        rows_path.read_text(encoding="utf-8-sig").replace("000001.SZ", "000001"),
        encoding="utf-8-sig",
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["v35_input"]["source_rows_sha256"] = hashlib.sha256(rows_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(WechatSyncError, match="code|identity"):
        sync_wechat_preselection(
            EFFECTIVE_DATE,
            input_root=allowed_root,
            data_root=_output_root(allowed_root) / "data",
        )


def test_exact_pair_materializes_and_reuse_is_not_new_artifact(allowed_root: Path) -> None:
    _write_wechat_pair(allowed_root)
    data_root = _output_root(allowed_root) / "data"
    first = sync_wechat_preselection(EFFECTIVE_DATE, input_root=allowed_root, data_root=data_root)
    second = sync_wechat_preselection(EFFECTIVE_DATE, input_root=allowed_root, data_root=data_root)
    assert first["status"] == "READY"
    assert first["reused"] is False
    assert first["artifact_created"] is True
    assert second["status"] == "READY"
    assert second["reused"] is True
    assert second["artifact_created"] is False
    artifact = PreselectionPoolStore(data_root).read_pool(
        EFFECTIVE_DATE, "wechat_public_account_v3_preselect"
    )
    assert len(artifact["rows"]) == 2
    assert artifact["source_role"] == "VERIFIED_WECHAT_RESEARCH"
    assert all(artifact[key] is False for key in ("production_allowed", "buy_gate_updated", "orders_sent"))


def test_conflicting_materialization_is_rejected(allowed_root: Path) -> None:
    _write_wechat_pair(allowed_root)
    data_root = _output_root(allowed_root) / "data"
    sync_wechat_preselection(EFFECTIVE_DATE, input_root=allowed_root, data_root=data_root)
    rows_path = allowed_root / EFFECTIVE_DATE / "wechat_rows.csv"
    rows_path.write_text(
        rows_path.read_text(encoding="utf-8-sig").replace(",5.5,", ",99.0,"),
        encoding="utf-8-sig",
    )
    manifest_path = allowed_root / EFFECTIVE_DATE / "wechat_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["v35_input"]["source_rows_sha256"] = hashlib.sha256(rows_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(WechatSyncError, match="conflicting"):
        sync_wechat_preselection(EFFECTIVE_DATE, input_root=allowed_root, data_root=data_root)


def test_sync_rejects_input_symlink_and_unscoped_roots(allowed_root: Path, tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _write_wechat_pair(source)
    link = allowed_root / "input-link"
    link.symlink_to(source, target_is_directory=True)
    with pytest.raises(WechatSyncError, match="symlink|scope"):
        sync_wechat_preselection(
            EFFECTIVE_DATE,
            input_root=link,
            data_root=_output_root(allowed_root) / "data",
        )
    with pytest.raises(WechatSyncError, match="allowed|scope"):
        sync_wechat_preselection(
            EFFECTIVE_DATE,
            input_root=Path.home() / "Desktop",
            data_root=_output_root(allowed_root) / "data",
        )


def test_formal_20260821_pair_canary_is_read_only_and_ready_90(allowed_root: Path) -> None:
    formal_input = (
        Path.home()
        / "Library"
        / "Application Support"
        / "com.lexi.v35.local"
        / "state"
        / "data"
        / "preselection_pools"
    )
    manifest_path = formal_input / EFFECTIVE_DATE / "wechat_manifest.json"
    rows_path = formal_input / EFFECTIVE_DATE / "wechat_rows.csv"
    if not manifest_path.is_file() or not rows_path.is_file():
        pytest.skip("formal 20260821 WeChat pair is not present")
    before = {path: path.read_bytes() for path in (manifest_path, rows_path)}
    result = sync_wechat_preselection(
        EFFECTIVE_DATE,
        input_root=formal_input,
        data_root=allowed_root / "data",
        receipt_path=allowed_root / "canary-receipt.json",
    )
    assert result["status"] == "READY"
    assert result["row_count"] == 90
    assert result["artifact_created"] is True
    assert {path: path.read_bytes() for path in (manifest_path, rows_path)} == before
