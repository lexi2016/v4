#!/usr/bin/env python3
"""Prepare the pinned, nonactive static delta for the daily numeric-283 card."""

from __future__ import annotations

import csv
import difflib
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


CONTRACT_PATH = Path("/Users/lexi/Desktop/学习/因子工厂/research/daily_numeric283_panel_integration_20261029_r1/CHART_FIX_CONTRACT.json")
HANDOFF = Path(__file__).resolve().parent
HANDOFF = Path("/Users/lexi/Desktop/学习/因子工厂/research/daily_numeric283_panel_integration_20261029_r1/worktree/docs/handoffs/daily_numeric283_20261029")
EXPECTED_OUTPUT_DIR = CONTRACT_PATH.parent / "prepared" / "chart_r3"
INPUT_ROOT = Path("/Users/lexi/Desktop/学习/因子工厂/research/kuansong151_formula_daily_20261029_r1/today_all_a/numeric_filters_v1_r1")
SOURCE_DAILY = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/v4-daily-numeric283-20261029-r2-api/research-panel/daily.html")
SOURCE_STATIC_MANIFEST = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/v4-daily-numeric283-20261029-r2-api/research-panel-assets.json")
EXPECTED_GROUP_COUNTS = {"original": 37, "nav_smallk": 163, "nav_pullback": 130, "nav_breakout": 31}
EXPECTED_SOURCE_SHA = {
    "FINAL_NUMERIC_CANDIDATES.csv": "55a65b75d3a03fd767a44d61da8d3d909cbe6c37450fe9796d82980a99a4fefe",
    "SUMMARY.json": "42bb85e7ee759804e8f950dbd8d1d7887fb3e2709c1fa7f4aaf284a4f95f8385",
    "EFFECTIVE_RESULTS_R5_INDEX.json": "8136398ddb939cdc41d95a39f683cd40aa0432b8632660b4956786a5429fa944",
    "review/R5_FINAL_REVIEW.md": "0d59702dad87c39af0347433b30b0d2df490b3a2aa24ebd038df39aa7f822724",
}
EXPECTED_CONTRACT_SHA = "807afdb6256cda9c68383a643229c15f1f969167184d282923b85ac3a93e42bf"
EXPECTED_STATIC_SHA = "83ca13ccd0f19b90b01ab32e9dba389e39c2da92302bdd445af522306c382825"
EXPECTED_STATIC_PINS = {
    "daily.html": "4728aa71cc75ff2425801849f696bde56b47046ab478e3522a6d456cdf52cc39",
    "numeric283-panel.js": "b028d49c5cc3f1110820ae73fcade869ddafc83af48f8e9bbf21b86ba22a6d25",
    "numeric283-candidates.json": "6c8f5ed6f46db818c3943deda02b78d3e04441c9f5630d290f56bb62e1c58dea",
    "r19-chart.js": "e66cbc2994b9ddcf13941323b9eb1dc9358e06ef902897d0226a2f2b862f3061",
    "r19-results.js": "c01c498f7e1765640c223b20481f21814318bbe82a341b531f2d54be2c365d55",
}
EXPECTED_CHART_JS_NAME = "numeric283-chart.js"
EXPECTED_CHART_PROFILE = "V4_DAILY_NUMERIC283_CHART_20261029_R1"
EXPECTED_CHART_NAMESPACE = "ACTIVE_MA_USER_20261021_V1"
EXPECTED_SOURCE_ARTIFACT_SHA = "28e577a67e5b5b00a04ac181632d7e1e4e6cc0e4f34e1283f69d28896ec893fb"
EXPECTED_DATA_DATE = "20261028"
EXPECTED_OBSERVATION_DATE = "20261029"
EXPECTED_GENERATION = "31d40c5900ced1b2ff637cfbeaa73688ad921d713e3ea748f83ccbca84463c29"
JS_NAME = "numeric283-panel.js"
JSON_NAME = "numeric283-candidates.json"
SCRIPT_TAG = f'<script src="{JS_NAME}"></script>'


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


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
    if contract.get("scope_count") != 283 or contract.get("data_date") != EXPECTED_DATA_DATE or contract.get("observation_date") != EXPECTED_OBSERVATION_DATE or contract.get("source_generation") != EXPECTED_GENERATION:
        raise RuntimeError("frozen chart contract identity changed")

    csv_path = INPUT_ROOT / "FINAL_NUMERIC_CANDIDATES.csv"
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != ["symbol", "display_name", "groups", "pending_groups", "latest_new_anchor", "reasons", "risk_clear"]:
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
        if not re.fullmatch(r"\d{6}\.(SH|SZ|BJ)", row["symbol"]):
            raise RuntimeError(f"invalid symbol: {row['symbol']}")
        if not row["latest_new_anchor"].isdigit() or len(row["latest_new_anchor"]) != 8:
            raise RuntimeError(f"invalid anchor date: {row['symbol']}")
    if group_counts != EXPECTED_GROUP_COUNTS:
        raise RuntimeError(f"group counts changed: {group_counts}")

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
    payload_raw = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    base_payload_raw = must_pin(SOURCE_DAILY.parent / JSON_NAME, EXPECTED_STATIC_PINS[JSON_NAME], "existing numeric-283 payload")
    if payload_raw != base_payload_raw:
        raise RuntimeError("approved source rows differ from the already pinned static membership")
    receipt = {
        "status": "PREPARED_STATIC_DELTA",
        "input_csv": str(csv_path),
        "input_csv_sha256": EXPECTED_SOURCE_SHA["FINAL_NUMERIC_CANDIDATES.csv"],
        "summary_sha256": EXPECTED_SOURCE_SHA["SUMMARY.json"],
        "effective_index_sha256": EXPECTED_SOURCE_SHA["EFFECTIVE_RESULTS_R5_INDEX.json"],
        "independent_review_sha256": EXPECTED_SOURCE_SHA["review/R5_FINAL_REVIEW.md"],
        "data_date": EXPECTED_DATA_DATE,
        "observation_date": EXPECTED_OBSERVATION_DATE,
        "source_generation": EXPECTED_GENERATION,
        "source_artifact_sha256": EXPECTED_SOURCE_ARTIFACT_SHA,
        "unique_count": 283,
        "group_counts_overlap": group_counts,
        "missing_display_name_symbols": [row["symbol"] for row in rows if not row["display_name"]],
        "membership_reused_without_recomputation": True,
        "formula_recomputed": False,
        "chart_review_completed": False,
        "research_only": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    return payload, receipt


def build_chart_markup() -> str:
    return f'''<style>
.daily-numeric283-card .numeric283-table-wrap table{{min-width:1040px}}
.daily-numeric283-card .numeric283-table-wrap td:nth-child(1),.daily-numeric283-card .numeric283-table-wrap td:nth-child(5),.daily-numeric283-card .numeric283-table-wrap td:nth-child(6),.daily-numeric283-card .numeric283-chart-trigger{{white-space:nowrap}}
.daily-numeric283-chart{{margin:16px 0;padding:12px;border:1px solid #466179;border-radius:8px;background:#0d1727;color:#e8edf6;scroll-margin-top:18px}}
.daily-numeric283-chart canvas{{display:block;width:100%;height:620px;touch-action:none}}
.daily-numeric283-chart-controls{{display:flex;flex-wrap:wrap;align-items:center;gap:8px}}
.daily-numeric283-chart [hidden]{{display:none!important}}
</style>
<div id="dailyNumeric283ChartPanel" class="daily-numeric283-chart" hidden>
<h3 id="dailyNumeric283ChartTitle">283只候选历史图</h3>
<p id="dailyNumeric283ChartStatus" role="status" aria-live="polite">请点击候选代码或名称读取固定D20261028历史。</p>
<p>参考线使用存储的 ACTIVE_MA_USER_20261021_V1 白线、黄线、BBI 与 J 字段；此命名空间不表示原始云端51变量/22绘图等价。</p>
<div id="numeric283chart85Panel">
<div class="numeric283-chart-controls"><button id="numeric283prevWindow" type="button">前移</button><button id="numeric283nextWindow" type="button">后移</button><button data-numeric283-window="60" type="button">60行</button><button data-numeric283-window="180" type="button">180行</button><label>历史光标 <select id="numeric283dateSelect"></select></label><input id="numeric283panRange" type="range" min="0" value="0"><label hidden><input id="numeric283showSignals" type="checkbox">信号</label><select id="numeric283signalFilter" hidden><option value="all">all</option></select></div>
<canvas id="numeric283chart" aria-label="数值候选 ACTIVE_MA 历史价格、成交量与参考线图"></canvas><p id="numeric283chartReadout"></p>
</div><p id="numeric283chart85Unknown" hidden></p>
</div>'''


def derive_chart_renderer(source: bytes) -> bytes:
    text = source.decode("utf-8")
    replacements = (
        ("window.R19Chart", "window.Numeric283Chart", 1),
        ("document.getElementById('r19'+id)", "document.getElementById('numeric283'+id)", 1),
        ("[data-r19-window]", "[data-numeric283-window]", 2),
        ("b.dataset.r19Window", "b.dataset.numeric283Window", 2),
    )
    for before, after, expected_count in replacements:
        if text.count(before) != expected_count:
            raise RuntimeError(f"pinned chart renderer transform anchor changed: {before}")
        text = text.replace(before, after)
    if "window.R19Chart" in text or "getElementById('r19'+id)" in text or "data-r19-window" in text:
        raise RuntimeError("numeric-283 chart renderer retained an R19 namespace binding")
    return ("// Derived from the pinned R19 chart85 renderer; DOM and JS namespace isolated for numeric-283.\n"
            + text + "\nwindow.Numeric283Chart.bind();\n").encode("utf-8")


def build_static(contract: dict[str, Any], payload: dict[str, Any], receipt: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    manifest_raw = must_pin(SOURCE_STATIC_MANIFEST, EXPECTED_STATIC_SHA, "R2 base static asset manifest")
    base_manifest = json.loads(manifest_raw)
    base_files = base_manifest.get("files")
    if base_manifest.get("schema_version") != "research_panel.assets.v1" or not isinstance(base_files, list) or len(base_files) != 454:
        raise RuntimeError("R2 base static asset manifest schema/count changed")
    if contract.get("static_root") != str(SOURCE_DAILY.parent) or contract.get("static_manifest") != str(SOURCE_STATIC_MANIFEST) or contract.get("static_asset_count") != 454:
        raise RuntimeError("static source path/count changed from frozen chart contract")
    contract_static_pins = contract.get("static_file_pins", {})
    if contract_static_pins != EXPECTED_STATIC_PINS:
        raise RuntimeError("static source pins changed from frozen chart contract")

    by_path: dict[str, bytes] = {}
    for entry in base_files:
        relative = Path(entry["path"])
        if relative.is_absolute() or ".." in relative.parts or str(relative) in by_path:
            raise RuntimeError(f"unsafe or duplicate static path: {relative}")
        raw = must_pin(SOURCE_DAILY.parent / relative, entry["sha256"], f"R2 static asset {relative}")
        by_path[str(relative)] = raw
    for relative, expected in EXPECTED_STATIC_PINS.items():
        if relative not in by_path or sha(by_path[relative]) != expected:
            raise RuntimeError(f"contract-pinned static input changed: {relative}")

    before = by_path.get("daily.html")
    if before is None:
        raise RuntimeError("R2 manifest lacks daily.html")
    before_text = before.decode("utf-8")
    if (before_text.count('<section id="dailyNumeric283Panel"') != 1
            or before_text.count('<details id="r19Card"') != 1
            or before_text.count('<script src="numeric283-panel.js"></script>') != 1
            or before_text.count("</body>") != 1
            or EXPECTED_CHART_JS_NAME in before_text
            or "id=\"dailyNumeric283ChartPanel\"" in before_text):
        raise RuntimeError("R2 daily-panel insertion anchors changed")
    panel_start = before_text.index('<section id="dailyNumeric283Panel"')
    panel_end = before_text.index("</section>", panel_start)
    chart_markup = build_chart_markup()
    after_text = before_text[:panel_end] + chart_markup + before_text[panel_end:]
    panel_script = f'<script src="{JS_NAME}"></script>'
    chart_script = f'<script src="{EXPECTED_CHART_JS_NAME}"></script>'
    after_text = after_text.replace(panel_script, chart_script + panel_script, 1)
    if after_text.replace(chart_script, "", 1).replace(chart_markup, "", 1) != before_text:
        raise RuntimeError("only the chart pane and derived renderer script may change daily.html")
    after = after_text.encode("utf-8")
    js_raw = (HANDOFF / JS_NAME).read_bytes()
    json_raw = by_path[JSON_NAME]
    chart_js_raw = derive_chart_renderer(by_path["r19-chart.js"])
    builder_raw = Path(__file__).read_bytes()

    if EXPECTED_CHART_JS_NAME in by_path:
        raise RuntimeError("numeric-283 chart renderer already exists in R2 base manifest")
    final_entries = []
    for entry in base_files:
        path = entry["path"]
        digest = entry["sha256"]
        if path == "daily.html":
            digest = sha(after)
        elif path == JS_NAME:
            digest = sha(js_raw)
        final_entries.append({"path": path, "sha256": digest})
    final_entries.append({"path": EXPECTED_CHART_JS_NAME, "sha256": sha(chart_js_raw)})
    final_entries.sort(key=lambda entry: entry["path"])
    candidate_manifest = {"schema_version": "research_panel.assets.v1", "source_only": False, "files": final_entries}
    manifest_candidate_raw = (json.dumps(candidate_manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")

    updated_receipt = dict(receipt)
    updated_receipt.update({
        "output_dir": str(output_dir),
        "task_scope_contract_sha256": EXPECTED_CONTRACT_SHA,
        "chart_profile": EXPECTED_CHART_PROFILE,
        "chart_signal_namespace": EXPECTED_CHART_NAMESPACE,
        "static_builder_source_path": str(Path(__file__).resolve()),
        "static_builder_source_sha256": sha(builder_raw),
        "base_static_manifest": str(SOURCE_STATIC_MANIFEST),
        "base_static_manifest_sha256": EXPECTED_STATIC_SHA,
        "base_asset_count": 454,
        "candidate_asset_count": 455,
        "unchanged_existing_asset_count": 452,
        "changed_existing_assets": ["daily.html", JS_NAME],
        "added_assets": [EXPECTED_CHART_JS_NAME],
        "daily_html_before_sha256": sha(before),
        "daily_html_after_sha256": sha(after),
        "panel_js_sha256": sha(js_raw),
        "chart_js_sha256": sha(chart_js_raw),
        "json_sha256": sha(json_raw),
        "candidate_static_manifest_sha256": sha(manifest_candidate_raw),
        "prior_asset_bytes_preserved": True,
        "prior_r19_markup_preserved": True,
        "r19_chart_source_sha256": EXPECTED_STATIC_PINS["r19-chart.js"],
        "chart_renderer_isolated_namespace": True,
        "chart_renderer_controls_bound": True,
    })
    patch = "".join(difflib.unified_diff(before_text.splitlines(True), after_text.splitlines(True), fromfile="r2/daily.html", tofile="chart-r1/daily.html"))

    output_dir.mkdir(parents=True, exist_ok=False)
    (output_dir / JSON_NAME).write_bytes(json_raw)
    (output_dir / "daily.html.prepared").write_bytes(after)
    (output_dir / "daily.html.patch").write_text(patch, encoding="utf-8")
    (output_dir / EXPECTED_CHART_JS_NAME).write_bytes(chart_js_raw)
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
    contract_raw = must_pin(CONTRACT_PATH, EXPECTED_CONTRACT_SHA, "chart-fix contract")
    contract = json.loads(contract_raw)
    if contract.get("schema") != "V4_NUMERIC283_CLICK_CHART_FIX_R1":
        raise RuntimeError("contract schema is not CHART_FIX_R1")
    if contract.get("candidate_identity") != "v4-daily-numeric283-chart-20261029-r3-api":
        raise RuntimeError("chart candidate identity changed")
    payload, receipt = build_payload(contract)
    summary = build_static(contract, payload, receipt, output_dir)
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
