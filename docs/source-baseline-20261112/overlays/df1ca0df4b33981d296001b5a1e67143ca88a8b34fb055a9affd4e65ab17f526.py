from __future__ import annotations

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from shared_research.collector import GROUPS, collect


def _panel(path: Path) -> Path:
    pq.write_table(
        pa.table(
            {
                "trade_date": ["20260812", "20260812"],
                "ts_code": ["300750.SZ", "600519.SH"],
                "name": ["宁德时代", "贵州茅台"],
            }
        ),
        path,
    )
    return path


def _cli(command: list[str], **_: object) -> object:
    group_id = command[command.index("--group-id") + 1]
    payload = {
        "success": True,
        "count": 1,
        "topics_brief": [
            {
                "topic_id": f"topic-{group_id}",
                "create_time": "2026-08-13T08:20:00.000+0800",
                "title": "宁德时代固态电池产业链更新",
                "content": "宁德时代（300750）固态电池产业链取得进展，正文足够长用于原 V3 有效主题判断。"
                * 3,
                "group": {"group_id": group_id},
            }
        ],
    }
    return type(
        "Completed",
        (),
        {"returncode": 0, "stdout": json.dumps(payload, ensure_ascii=False), "stderr": ""},
    )()


def test_collect_preserves_v3_summary_shape_and_is_single_writer(tmp_path: Path) -> None:
    state = tmp_path / "state"
    result = collect(
        state_root=state,
        trade_date="20260813",
        slot="0830",
        cli=tmp_path / "zsxq-cli",
        selector_panel=_panel(tmp_path / "panel.parquet"),
        process_runner=_cli,
    )

    summary = json.loads(Path(result["paths"]["summary"]).read_text(encoding="utf-8"))
    assert result["status"] == "READY"
    assert result["topic_count"] == len(GROUPS)
    assert summary["effective_topic_count"] == len(GROUPS)
    assert summary["effective_topics"][0]["companies"][0] == {
        "name": "宁德时代",
        "code": "300750.SZ",
        "source": "explicit_code",
    }
    assert result["production_allowed"] is False
    assert result["buy_gate_updated"] is False
    assert result["orders_sent"] is False

    reused = collect(
        state_root=state,
        trade_date="20260813",
        slot="0830",
        cli=tmp_path / "zsxq-cli",
        selector_panel=tmp_path / "missing.parquet",
        process_runner=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("refetched")),
    )
    assert reused["reused"] is True
    assert reused["run_id"] == result["run_id"]


def test_collect_never_uses_cookie_or_windows_command(tmp_path: Path) -> None:
    seen: list[list[str]] = []

    def runner(command: list[str], **kwargs: object) -> object:
        seen.append(command)
        return _cli(command, **kwargs)

    collect(
        state_root=tmp_path / "state",
        trade_date="20260813",
        slot="0830",
        cli=tmp_path / "zsxq-cli",
        selector_panel=_panel(tmp_path / "panel.parquet"),
        process_runner=runner,
    )

    flat = " ".join(part for command in seen for part in command[1:])
    assert "powershell" not in flat.casefold()
    assert "cookie" not in flat.casefold()
    assert "C:\\" not in flat
    assert all(command[0] == str(tmp_path / "zsxq-cli") for command in seen)
