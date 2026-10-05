"""Frozen canary allowlist (isolated acceptance tooling).

This file is the ONLY place in the repository allowed to hold the absolute
V3 canary source path and the frozen oracle pin (Sol, 2026-08-06). The formal
package ``shared_data/`` must stay free of these values.
"""
from __future__ import annotations

from pathlib import Path

from shared_data.allowlist import AllowlistRegistry, SourceSpec

CANARY_DATE = "20260716"
CANARY_ROLE = "A_SHARE_1MIN_RAW_FILE_REPLAY"
CANARY_SOURCE_ID = "v3_ashare_open_live_1min"
CANARY_STAGE = "STAGE_1445_1500"
CANARY_SOURCE_PATH = Path(
    r"C:\Users\huang\Desktop\学习\v3_system\40_artifacts\runtime_debug\20260716_ashare_open_live\ashare_open_live_1min_bars_20260716.csv"
)
ORACLE_INPUT_SHA256 = "c70c6628993fd65a402c473863cd1408989eda6747248370056e7a7f05b08697"
ORACLE_ROW_COUNT = 60720
CANARY_CANNOT_CONFIRM = (
    "A股 1分钟线来自 pytdx 历史分钟代理数据，只能用于七阶段观察/复盘，不能确认逐笔、十档、队列、撤单或实盘成交。",
    "自动获取范围限定为本地正式池/观察池，不做全市场扫描。",
)


def canary_spec() -> SourceSpec:
    return SourceSpec(
        source_id=CANARY_SOURCE_ID,
        role=CANARY_ROLE,
        trade_date=CANARY_DATE,
        market="A_SHARE",
        stages=(CANARY_STAGE,),
        cutoff_at="15:00:00",
        source_path=CANARY_SOURCE_PATH,
        collector="file_replay",
        expected_input_sha256=ORACLE_INPUT_SHA256,
        expected_row_count=ORACLE_ROW_COUNT,
        cannot_confirm=CANARY_CANNOT_CONFIRM,
        provenance={
            "companion_filename": "ashare_open_live_1min_bars_20260716.manifest.json",
        },
    )


def canary_registry() -> AllowlistRegistry:
    return AllowlistRegistry(entries={(CANARY_DATE, CANARY_ROLE): (canary_spec(),)})
