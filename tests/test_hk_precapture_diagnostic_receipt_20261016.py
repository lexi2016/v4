from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

import ops.run_stage_center_nodes as nodes


SHANGHAI = nodes.SHANGHAI
TRADE_DATE = "20261016"
STAGE_ID = "STAGE_0945_1030"
PRECAPTURE_NODE = "PRECAPTURE_STAGE_0945_1030"


def test_precapture_attempt_receipt_survives_compact_stdout(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        nodes,
        "_calendar_gate",
        lambda *_args, **_kwargs: {"status": "ELIGIBLE", "trade_date": TRADE_DATE},
    )

    class Runner:
        def _prepare_hk_active_snapshots(self, *_args, **_kwargs):
            return [{
                "status": "PARTIAL_WITH_ROWS",
                "requested_rows": 100,
                "returned_rows": 100,
                "eligible_rows_count": 99,
                "excluded_rows_count": 1,
                "exclusions": [{"code": "HK.02723", "reason": "wrong_trade_date"}],
                "provider_started_at": "2026-10-16T10:29:10.100000+08:00",
                "provider_finished_at": "2026-10-16T10:29:20.200000+08:00",
                "write_performed": True,
            }]

    result = nodes.run_nodes(
        {"receipt_root": str(tmp_path)},
        trade_date=TRADE_DATE,
        evaluated_at=datetime(2026, 10, 16, 10, 29, 30, tzinfo=SHANGHAI),
        explicit_node=PRECAPTURE_NODE,
        runner=Runner(),
    )

    node = result["nodes"][0]
    assert node["status"] == "PRECAPTURE_PARTIAL_WITH_ROWS"
    receipt_path = Path(node["diagnostic_receipt_path"])
    receipt_bytes = receipt_path.read_bytes()
    receipt = json.loads(receipt_bytes)
    assert receipt_path.parent == tmp_path / TRADE_DATE / STAGE_ID / "precapture_attempts"
    assert receipt["schema"] == "stage_center.hk_precapture_diagnostic.v1"
    assert receipt["authorizes_selection"] is False
    assert receipt["grants_retry"] is False
    assert receipt["pre_captures"][0]["eligible_rows_count"] == 99
    assert receipt["pre_captures"][0]["excluded_rows_count"] == 1
    assert node["diagnostic_receipt_sha256"] == hashlib.sha256(receipt_bytes).hexdigest()
    assert not (tmp_path / TRADE_DATE / STAGE_ID / "receipt.json").exists()

    # Other due-stage failures can push the scheduler envelope past its 4095-byte limit.
    compact_input = {**result, "nodes": [
        node,
        *[
            {
                "stage_id": f"OLDER_{index}",
                "status": "CANNOT_CONFIRM",
                "error": "x" * 512,
                "markets": {"HK_CONNECT": {"status": "CANNOT_CONFIRM", "first_error": "y" * 120}},
            }
            for index in range(5)
        ],
    ]}
    nodes._print_json(compact_input)
    stdout_payload = json.loads(capsys.readouterr().out)
    assert stdout_payload["output_truncated"] is True
    compact_precapture = stdout_payload["nodes"][0]["precapture_diagnostic"]
    assert compact_precapture["diagnostic_receipt_path"] == str(receipt_path)
    assert compact_precapture["diagnostic_receipt_sha256"] == node["diagnostic_receipt_sha256"]
    assert compact_precapture["capture_status"] == "PARTIAL_WITH_ROWS"
    assert compact_precapture["requested_rows"] == 100
    assert compact_precapture["eligible_rows_count"] == 99
    assert compact_precapture["excluded_rows_count"] == 1
    assert compact_precapture["exclusions"] == [{"code": "HK.02723", "reason": "wrong_trade_date"}]
    assert compact_precapture["provider_started_at"] == "2026-10-16T10:29:10.100000+08:00"
    assert compact_precapture["provider_finished_at"] == "2026-10-16T10:29:20.200000+08:00"
