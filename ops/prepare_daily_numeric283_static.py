#!/usr/bin/env python3
"""Prepare the pinned, nonactive static delta for the daily numeric-283 card."""

from __future__ import annotations

import csv
import difflib
import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any


CONTRACT_PATH = Path("/Users/lexi/Desktop/学习/因子工厂/research/daily_numeric283_panel_integration_20261029_r1/INTEGRATION_CONTRACT.json")
HANDOFF = Path(__file__).resolve().parent
HANDOFF = Path("/Users/lexi/Desktop/学习/因子工厂/research/daily_numeric283_panel_integration_20261029_r1/worktree/docs/handoffs/daily_numeric283_20261029")
EXPECTED_OUTPUT_DIR = CONTRACT_PATH.parent / "prepared" / "daily_numeric283_20261029_r2"
INPUT_ROOT = Path("/Users/lexi/Desktop/学习/因子工厂/research/kuansong151_formula_daily_20261029_r1/today_all_a/numeric_filters_v1_r1")
SOURCE_DAILY = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/a-chain-completion-20261029-r1-api/research-panel/daily.html")
SOURCE_STATIC_MANIFEST = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/a-chain-completion-20261029-r1-api/research-panel-assets.json")
EXPECTED_GROUP_COUNTS = {"original": 37, "nav_smallk": 163, "nav_pullback": 130, "nav_breakout": 31}
EXPECTED_SOURCE_SHA = {
    "FINAL_NUMERIC_CANDIDATES.csv": "55a65b75d3a03fd767a44d61da8d3d909cbe6c37450fe9796d82980a99a4fefe",
    "SUMMARY.json": "42bb85e7ee759804e8f950dbd8d1d7887fb3e2709c1fa7f4aaf284a4f95f8385",
    "EFFECTIVE_RESULTS_R5_INDEX.json": "8136398ddb939cdc41d95a39f683cd40aa0432b8632660b4956786a5429fa944",
    "review/R5_FINAL_REVIEW.md": "0d59702dad87c39af0347433b30b0d2df490b3a2aa24ebd038df39aa7f822724",
}
EXPECTED_CONTRACT_SHA = "be5a3e6dd28661c2c27622e7d96d0012fb280bbb49cb753578cb72e5336f9839"
EXPECTED_LINKS_SHA = "badc8e0941f2e345c89d92b790c963bddb0f4dc9c8867eede011943735641d2d"
EXPECTED_STATIC_SHA = "73410703548f29fdfad2d7a3d1fd7bde21b79f3c44d6933def01d5b1836cc516"
EXPECTED_DATA_DATE = "20261028"
EXPECTED_OBSERVATION_DATE = "20261029"
EXPECTED_GENERATION = "31d40c5900ced1b2ff637cfbeaa73688ad921d713e3ea748f83ccbca84463c29"
JS_NAME = "numeric283-panel.js"
JSON_NAME = "numeric283-candidates.json"
CARD_ANCHOR = '<details id="r19Card"'
SCRIPT_TAG = f'<script src="{JS_NAME}"></script>'


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def must_pin(path: Path, expected: str, label: str) -> bytes:
    if not path.is_file() or path.is_symlink():
        raise RuntimeError(f"{label}: expected a regular file")
    raw = path.read_bytes()
    actual = sha(raw)
    if actual != expected:
        raise RuntimeError(f"{label}: SHA drift; expected={expected} actual={actual}")
    return raw


def build_payload(contract: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    input_pins = {Path(item["path"]).name if "/" not in item["path"] else item["path"].split("/numeric_filters_v1_r1/", 1)[1]: item["sha256"] for item in contract["input_pins"]}
    for relative, expected in EXPECTED_SOURCE_SHA.items():
        if input_pins.get(relative) != expected:
            raise RuntimeError(f"contract input pin changed: {relative}")
        must_pin(INPUT_ROOT / relative, expected, f"approved input {relative}")

    urls_path = INPUT_ROOT / "delivery/FINAL_DELIVERY_URLS.json"
    urls_raw = must_pin(urls_path, EXPECTED_LINKS_SHA, "delivery links")
    urls = json.loads(urls_raw)
    for key in ("index", "csv", "main", "sop"):
        if not isinstance(urls.get(key), str) or not urls[key].startswith("https://drive.google.com/file/d/"):
            raise RuntimeError(f"invalid pinned Drive link: {key}")

    csv_path = INPUT_ROOT / "FINAL_NUMERIC_CANDIDATES.csv"
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames
        expected_fields = ["symbol", "display_name", "groups", "pending_groups", "latest_new_anchor", "reasons", "risk_clear"]
        if fields != expected_fields:
            raise RuntimeError("approved CSV column order changed")
        rows = list(reader)
    if len(rows) != 283 or len({row["symbol"] for row in rows}) != 283:
        raise RuntimeError("approved CSV is not exactly 283 unique rows")

    group_counts = {group: 0 for group in EXPECTED_GROUP_COUNTS}
    for row in rows:
        memberships = [token for token in row["groups"].split("|") if token]
        if not memberships or len(memberships) != len(set(memberships)) or any(group not in group_counts for group in memberships):
            raise RuntimeError(f"unexpected candidate group membership: {row['symbol']}")
        for group in memberships:
            group_counts[group] += 1
        if len(row["symbol"]) != 9 or row["symbol"][6:] not in {".SZ", ".SH", ".BJ"}:
            raise RuntimeError(f"invalid symbol: {row['symbol']}")
        if not row["latest_new_anchor"].isdigit() or len(row["latest_new_anchor"]) != 8:
            raise RuntimeError(f"invalid anchor date: {row['symbol']}")
    if group_counts != EXPECTED_GROUP_COUNTS:
        raise RuntimeError(f"group counts changed: {group_counts}")
    if contract["scope_count"] != 283 or contract["data_date"] != EXPECTED_DATA_DATE or contract["observation_date"] != EXPECTED_OBSERVATION_DATE or contract["source_generation"] != EXPECTED_GENERATION:
        raise RuntimeError("frozen contract identity changed")

    payload = {
        "schema_version": "v4.numeric283.daily.v1",
        "data_date": EXPECTED_DATA_DATE,
        "observation_date": EXPECTED_OBSERVATION_DATE,
        "source_generation": EXPECTED_GENERATION,
        "source_csv_sha256": EXPECTED_SOURCE_SHA["FINAL_NUMERIC_CANDIDATES.csv"],
        "source_summary_sha256": EXPECTED_SOURCE_SHA["SUMMARY.json"],
        "source_effective_index_sha256": EXPECTED_SOURCE_SHA["EFFECTIVE_RESULTS_R5_INDEX.json"],
        "source_review_sha256": EXPECTED_SOURCE_SHA["review/R5_FINAL_REVIEW.md"],
        "unique_count": 283,
        "group_counts": group_counts,
        "rows": rows,
    }
    receipt = {
        "status": "PREPARED_STATIC_DELTA",
        "input_csv": str(csv_path),
        "input_csv_sha256": EXPECTED_SOURCE_SHA["FINAL_NUMERIC_CANDIDATES.csv"],
        "summary_sha256": EXPECTED_SOURCE_SHA["SUMMARY.json"],
        "effective_index_sha256": EXPECTED_SOURCE_SHA["EFFECTIVE_RESULTS_R5_INDEX.json"],
        "independent_review_sha256": EXPECTED_SOURCE_SHA["review/R5_FINAL_REVIEW.md"],
        "delivery_urls_sha256": EXPECTED_LINKS_SHA,
        "data_date": EXPECTED_DATA_DATE,
        "observation_date": EXPECTED_OBSERVATION_DATE,
        "source_generation": EXPECTED_GENERATION,
        "unique_count": 283,
        "group_counts_overlap": group_counts,
        "missing_display_name_symbols": [row["symbol"] for row in rows if not row["display_name"]],
        "pending_only_rows_added": 0,
        "formula_recomputed": False,
        "chart_or_futu_review": False,
        "research_only": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
        "drive_urls": urls,
    }
    return payload, receipt


def build_card(urls: dict[str, str]) -> str:
    return f'''<style>
.daily-numeric283-card{{margin:18px 0;padding:18px;border:2px solid #69c7bf;border-radius:12px;background:#122131;color:#e8edf6}}
.daily-numeric283-card h2{{margin-top:0}}
.daily-numeric283-card label{{display:inline-flex;gap:8px;align-items:center;margin:8px 14px 8px 0}}
.daily-numeric283-card input,.daily-numeric283-card select,.daily-numeric283-card button{{padding:7px;max-width:100%}}
.daily-numeric283-card .numeric283-controls{{display:flex;flex-wrap:wrap;align-items:center;gap:8px}}
.daily-numeric283-card .numeric283-table-wrap{{max-height:540px;overflow:auto;border:1px solid #34475b;border-radius:8px}}
.daily-numeric283-card table{{width:100%;border-collapse:collapse}}
.daily-numeric283-card th,.daily-numeric283-card td{{padding:8px;text-align:left;border-bottom:1px solid #34475b;overflow-wrap:anywhere}}
.daily-numeric283-card th{{position:sticky;top:0;background:#1c3043}}
.daily-numeric283-card a{{color:#9ed8ff}}
.daily-numeric283-card [hidden]{{display:none!important}}
@media(max-width:680px){{.daily-numeric283-card{{padding:12px}}.daily-numeric283-card .numeric283-table-wrap{{max-height:65vh}}}}
</style>
<section id="dailyNumeric283Panel" class="daily-numeric283-card" aria-labelledby="dailyNumeric283Title">
<h2 id="dailyNumeric283Title">数值候选名单 · 283只</h2>
<p><strong>名单日期：2026-10-28；观察日期：2026-10-29。</strong> 这是同日静态快照，不会自动切换到后续日期。名单用于研究筛选，图形复核待进行。</p>
<p>分组人数：原始公式 37 · 小K 163 · 回踩 130 · 突破 31。分组有交叉，人数不相加；本卡只列283只最终候选，不补入待处理名单。</p>
<div class="numeric283-controls">
<label for="dailyNumeric283Group">分组筛选 <select id="dailyNumeric283Group"><option value="all">全部（283）</option><option value="original">原始公式（37）</option><option value="nav_smallk">小K（163）</option><option value="nav_pullback">回踩（130）</option><option value="nav_breakout">突破（31）</option></select></label>
<label for="dailyNumeric283Search">代码或名称 <input id="dailyNumeric283Search" type="search" autocomplete="off" placeholder="搜索当前名单"></label>
<button id="dailyNumeric283Download" type="button">下载当前结果 CSV</button>
</div>
<p id="dailyNumeric283Status" role="status" aria-live="polite">正在读取固定日期名单…</p>
<p id="dailyNumeric283Count">—</p>
<div class="numeric283-table-wrap"><table><thead><tr><th scope="col">代码</th><th scope="col">名称</th><th scope="col">通过组</th><th scope="col">其他待核组 / 原因</th><th scope="col">关键K锚点</th><th scope="col">数据日 / 观察日</th><th scope="col">来源 / 图审状态</th></tr></thead><tbody id="dailyNumeric283Rows"></tbody></table></div>
<details><summary>来源、日期和边界</summary><p>数据来自已交付的 FINAL_NUMERIC_CANDIDATES.csv；日期、代次和文件哈希绑定在本卡静态数据中。空缺名称显示为“名称待核”。这不是图表复核结论，也不改动原有日更分组或研究池。</p>
<p><a href="{urls['csv']}" target="_blank" rel="noopener">打开原始 CSV ↗</a> · <a href="{urls['index']}" target="_blank" rel="noopener">交付索引 ↗</a> · <a href="{urls['main']}" target="_blank" rel="noopener">主交付 ↗</a> · <a href="{urls['sop']}" target="_blank" rel="noopener">逐股复核 SOP ↗</a></p>
<p>来源 CSV SHA-256：<code>{EXPECTED_SOURCE_SHA['FINAL_NUMERIC_CANDIDATES.csv']}</code><br>生成代次：<code>{EXPECTED_GENERATION}</code></p></details>
</section>'''


def build_static(contract: dict[str, Any], payload: dict[str, Any], receipt: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    manifest_raw = must_pin(SOURCE_STATIC_MANIFEST, EXPECTED_STATIC_SHA, "base static asset manifest")
    base_manifest = json.loads(manifest_raw)
    base_files = base_manifest.get("files")
    if base_manifest.get("schema_version") != "research_panel.assets.v1" or not isinstance(base_files, list) or len(base_files) != 452:
        raise RuntimeError("base static asset manifest schema/count changed")
    if contract["static_root"] != str(SOURCE_DAILY.parent) or contract["static_manifest"] != str(SOURCE_STATIC_MANIFEST) or contract["static_asset_count"] != 452:
        raise RuntimeError("static source path/count changed from frozen contract")

    by_path: dict[str, bytes] = {}
    for entry in base_files:
        relative = Path(entry["path"])
        if relative.is_absolute() or ".." in relative.parts or str(relative) in by_path:
            raise RuntimeError(f"unsafe or duplicate static path: {relative}")
        source = SOURCE_DAILY.parent / relative
        raw = must_pin(source, entry["sha256"], f"base static asset {relative}")
        by_path[str(relative)] = raw

    before = by_path.get("daily.html")
    if before is None:
        raise RuntimeError("base manifest lacks daily.html")
    before_text = before.decode("utf-8")
    if before_text.count(CARD_ANCHOR) != 1 or before_text.count("</body>") != 1:
        raise RuntimeError("daily panel insertion anchors changed")
    if JS_NAME in before_text or JSON_NAME in before_text:
        raise RuntimeError("numeric-283 assets are already referenced in the base daily page")

    card = build_card(receipt["drive_urls"])
    after_text = before_text.replace(CARD_ANCHOR, card + CARD_ANCHOR, 1)
    after_text = after_text.replace("</body>", SCRIPT_TAG + "</body>", 1)
    if after_text.replace(SCRIPT_TAG, "", 1).replace(card, "", 1) != before_text:
        raise RuntimeError("only the additive card and script tag may change daily.html")
    after = after_text.encode("utf-8")
    js_raw = (HANDOFF / JS_NAME).read_bytes()
    json_raw = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    builder_raw = Path(__file__).read_bytes()

    new_paths = {JS_NAME, JSON_NAME}
    if new_paths.intersection(by_path):
        raise RuntimeError("numeric-283 asset name already exists in the base manifest")
    final_entries = [dict(entry) for entry in base_files if entry["path"] != "daily.html"]
    final_entries.extend([
        {"path": "daily.html", "sha256": sha(after)},
        {"path": JS_NAME, "sha256": sha(js_raw)},
        {"path": JSON_NAME, "sha256": sha(json_raw)},
    ])
    final_entries.sort(key=lambda entry: entry["path"])
    candidate_manifest = {"schema_version": "research_panel.assets.v1", "source_only": False, "files": final_entries}
    manifest_candidate_raw = (json.dumps(candidate_manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")

    updated_receipt = dict(receipt)
    updated_receipt.update({
        "status": "PREPARED_STATIC_DELTA",
        "output_dir": str(output_dir),
        "task_scope_contract_sha256": EXPECTED_CONTRACT_SHA,
        "static_builder_source_path": str(Path(__file__).resolve()),
        "static_builder_source_sha256": sha(builder_raw),
        "base_static_manifest": str(SOURCE_STATIC_MANIFEST),
        "base_static_manifest_sha256": EXPECTED_STATIC_SHA,
        "base_asset_count": 452,
        "candidate_asset_count": 454,
        "unchanged_existing_asset_count": 451,
        "changed_existing_assets": ["daily.html"],
        "added_assets": [JS_NAME, JSON_NAME],
        "daily_html_before_sha256": sha(before),
        "daily_html_after_sha256": sha(after),
        "js_sha256": sha(js_raw),
        "json_sha256": sha(json_raw),
        "candidate_static_manifest_sha256": sha(manifest_candidate_raw),
        "prior_asset_bytes_preserved": True,
        "prior_r19_markup_preserved_by_additive_insert": True,
    })
    patch = "".join(difflib.unified_diff(before_text.splitlines(True), after_text.splitlines(True), fromfile="base/daily.html", tofile="candidate/daily.html"))

    output_dir.mkdir(parents=True, exist_ok=False)
    (output_dir / JSON_NAME).write_bytes(json_raw)
    (output_dir / "daily.html.prepared").write_bytes(after)
    (output_dir / "daily.html.patch").write_text(patch, encoding="utf-8")
    (output_dir / "research-panel-assets.numeric283.json").write_bytes(manifest_candidate_raw)
    (output_dir / "STATIC_CANDIDATE_RECEIPT.json").write_text(json.dumps(updated_receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return updated_receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if not sys.dont_write_bytecode or not sys.flags.no_user_site:
        raise RuntimeError("run with the configured interpreter using -I -B")
    output_dir = args.output_dir.expanduser().resolve(strict=False)
    if output_dir != EXPECTED_OUTPUT_DIR.resolve(strict=False):
        raise RuntimeError(f"output directory outside the frozen prepared path: {output_dir}")
    if output_dir.exists():
        raise FileExistsError(f"refusing to overwrite prepared output: {output_dir}")
    contract_raw = must_pin(CONTRACT_PATH, EXPECTED_CONTRACT_SHA, "R3 integration contract")
    contract = json.loads(contract_raw)
    if contract.get("schema") != "V4_ORIGINAL_DAILY_NUMERIC283_INTEGRATION_V1_R3":
        raise RuntimeError("contract schema is not R3")
    if contract.get("candidate_identity") != "v4-daily-numeric283-20261029-r2-api":
        raise RuntimeError("nonactive candidate identity changed")
    payload, receipt = build_payload(contract)
    summary = build_static(contract, payload, receipt, output_dir)
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
