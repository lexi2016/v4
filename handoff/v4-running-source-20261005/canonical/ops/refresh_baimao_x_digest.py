"""Refresh the V3.5-owned Baimao/Serenity X mirror digest.

This is a bounded port of V3's research-only mirror fetch.  It uses the same
three fixed mirrors and keyword groups, writes only below ``data_root``, and
never changes pools, BUY gates, broker state, or orders.

Oracle SHA-256:
C8908753D0BE5D1E786B0EA4A88372BE93AD2F8AA77C67768B54E5960270FEBE
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Callable
from urllib.error import URLError
from urllib.request import Request, urlopen

from infrastructure.data_store import NativeDataStore


MIRROR_URLS = (
    "https://1ms.news/x",
    "https://flash-filling.com/thread/2070790270447178012",
    "https://www.mirrormedia.mg/external/amp/setn_1864836",
)
Fetcher = Callable[[str, int], str]


def _fetch(url: str, timeout: int) -> str:
    request = Request(
        url, headers={"User-Agent": "Mozilla/5.0 baimao-x-research-only"}
    )
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 fixed mirrors
        raw = response.read(1_000_000)
    return raw.decode("utf-8", errors="ignore")


def _has(text: str, *keywords: str) -> bool:
    lowered = text.lower()
    return any(keyword.lower() in lowered for keyword in keywords)


def _focus_tags(text: str) -> list[str]:
    tags = []
    for keyword, label in (
        ("agility", "Agility Robotics"),
        ("unitree", "Unitree"),
        ("宇树", "宇树科技"),
        ("harmonic", "Harmonic Drive"),
        ("sivers", "Sivers"),
        ("poet", "POET"),
        ("cerebras", "Cerebras"),
        ("robot", "机器人"),
        ("机器人", "机器人"),
        ("dfb", "DFB 激光器"),
        ("inp", "InP 激光器"),
        ("laser", "激光器"),
    ):
        if keyword.lower() in text.lower() and label not in tags:
            tags.append(label)
    return tags


def _items(text: str, source_url: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    groups = (
        (
            ("agility", "unitree", "宇树", "robot", "机器人"),
            "机器人整机",
            "Agility Robotics / Unitree 是当前机器人线索核心",
            "镜像源命中机器人整机关键词；仅作为研究提醒，仍需核验整机进展、场景验证与产业链映射。",
            "HIGH",
        ),
        (
            ("harmonic", "schaeffler", "vishay", "谐波", "减速器", "sensor", "actuator"),
            "机器人零部件",
            "零部件侧继续跟踪减速器、传感器、轴承和执行器",
            "整机之外需继续验证量产瓶颈；Harmonic Drive、Schaeffler、Vishay 等只作为映射线索。",
            "HIGH",
        ),
        (
            ("sivers", "inp", "dfb", "laser", "激光器", "optical amplifier"),
            "光子学 / 激光器",
            "Sivers、InP/DFB 激光器和 optical amplifier 是上游瓶颈线",
            "镜像源命中光子学关键词；用于跟踪 AI 光互连、机器人感知和上游产能瓶颈。",
            "MEDIUM",
        ),
        (
            ("poet", "shortage", "capacity", "2028", "2029", "短缺", "产能"),
            "供应短缺",
            "POET / 激光器产能紧张继续作为供给侧验证",
            "关注供应商集中、产能释放节奏和短缺延续风险；不能替代公司公告、订单和交付验证。",
            "MEDIUM",
        ),
        (
            ("cerebras", "openai", "capex", "hyperscaler", "compute", "算力"),
            "算力供给 / AI capex",
            "Cerebras、OpenAI 与 hyperscaler capex 用于验证算力供给瓶颈",
            "继续核验上游供给、客户占用产能和资本开支韧性；不能直接外推 A 股买点。",
            "MEDIUM",
        ),
    )
    for keywords, theme, title, summary, importance in groups:
        if _has(text, *keywords):
            rows.append(
                {
                    "published_at": "CANNOT_CONFIRM",
                    "theme": theme,
                    "title_cn": title,
                    "summary_cn": summary,
                    "source_url": source_url,
                    "importance": importance,
                }
            )
    if not rows:
        rows.append(
            {
                "published_at": "CANNOT_CONFIRM",
                "theme": "白毛 X 自动抓取",
                "title_cn": "自动刷新完成，未命中本地主题词",
                "summary_cn": "镜像页面已抓取，但需要人工打开 X 原文复核是否存在新增主题。",
                "source_url": source_url,
                "importance": "LOW",
            }
        )
    return rows[:6]


def refresh_baimao_x_digest(
    *,
    data_root: Path,
    business_date: str,
    slot: str,
    timeout: int = 15,
    fetcher: Fetcher | None = None,
) -> dict:
    datetime.strptime(business_date, "%Y%m%d")
    if slot not in {"0930", "1130", "1530", "2030"}:
        raise ValueError("Baimao X slot is not in the V3 schedule")
    hits: list[dict[str, str]] = []
    for url in MIRROR_URLS:
        try:
            text = (fetcher or _fetch)(url, timeout)
        except (OSError, URLError, TimeoutError):
            continue
        if _has(text, "aleabitoreddit", "agility", "unitree", "robot", "serenity", "白毛"):
            hits.append({"url": url, "text": text[:20_000]})
    generated = datetime.now().astimezone().isoformat(timespec="seconds")
    combined = "\n".join(hit["text"] for hit in hits)
    if hits:
        status = "REFRESHED_FROM_MIRRORS"
        headline = "白毛 X 镜像源已刷新；按 V3 原五组研究线索展示。"
        items = _items(combined, hits[0]["url"])
        cannot_confirm = ["CANNOT_CONFIRM_X_OFFICIAL_FULL_FEED"]
    else:
        status = "FETCH_FAILED"
        headline = "白毛 X 镜像源本次未返回可确认内容。"
        items = _items("", "")
        cannot_confirm = [
            "CANNOT_CONFIRM_X_MIRROR_FETCH",
            "CANNOT_CONFIRM_X_OFFICIAL_FULL_FEED",
        ]
    payload = {
        "schema_version": "v3_5.baimao_x_digest.v1",
        "ok": bool(hits),
        "status": status,
        "business_date": business_date,
        "trade_date": business_date,
        "slot": slot,
        "account": {
            "display_name": "白毛 / Serenity",
            "handle": "@aleabitoreddit",
            "profile_url": "https://x.com/aleabitoreddit",
        },
        "generated_at": generated,
        "fetched_at": generated,
        "source_mode": "mirror_pages_no_official_x_api",
        "headline": headline,
        "focus_tags": _focus_tags(combined)[:12],
        "items": items,
        "cannot_confirm": cannot_confirm,
        "source_hits": [
            {"url": hit["url"], "length": len(hit["text"])} for hit in hits
        ],
        "read_only_boundary": "RESEARCH_ONLY_NOT_BUY_ADVICE",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    store = NativeDataStore(Path(data_root))
    dated = f"baimao_x/{business_date}/{slot}/baimao_x_digest.json"
    store._write(dated, payload)
    store._write("baimao_x/latest_baimao_x_digest.json", payload)
    graph_status = "READY" if hits else "ACTION_RAN_WITH_CANNOT_CONFIRM"
    store._write(
        f"runtime_graph/evidence/node_action_status/{business_date}/baimao_x_refresh.json",
        {
            "schema_version": "v3_5.runtime_graph_node_receipt.v1",
            "node_id": "baimao_x_refresh",
            "status": graph_status,
            "effective_status": graph_status,
            "business_date": business_date,
            "trade_date": business_date,
            "slot": slot,
            "artifact_path": dated,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        },
    )
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh V3.5 Baimao X digest")
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--slot", required=True)
    parser.add_argument("--timeout", type=int, default=15)
    args = parser.parse_args()
    result = refresh_baimao_x_digest(
        data_root=args.data_root,
        business_date=args.date,
        slot=args.slot,
        timeout=args.timeout,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "REFRESHED_FROM_MIRRORS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
