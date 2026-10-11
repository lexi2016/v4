# -*- coding: utf-8 -*-
"""WeChat article performance helpers.

The default appendix command binds a prior trusted article archive and the
current article package to exact-date rows from the currently configured
scheduler panels and their receipts. The explicit legacy command retains the
older V3 observation-pool calculation.

All outputs are descriptive research observations: RESEARCH_ONLY /
WATCH_ONLY / NO_BUY_GATE. This module reads panels but does not change pools,
BUY gates, selector pointers, or trading state.
"""
from __future__ import annotations

import importlib.util
import csv
import hashlib
import io
import json
import math
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from pathlib import PureWindowsPath

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wechat_common import (  # noqa: E402
    WORK_ROOT, RUNS_DIR, DATA_LAYER_INTERFACE, BOUNDARY,
    normalize_date, safe_run_path, validate_run_dir, _reject_symlink_components,
)


def _load_data_interface() -> object:
    spec = importlib.util.spec_from_file_location("data_layer_interface_for_yesterday", DATA_LAYER_INTERFACE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def current_selector_panel_path() -> str:
    return _load_data_interface().get_current_selector_panel_path()


def _date8(value: object) -> str:
    try:
        return normalize_date(value, label="run date")
    except (TypeError, ValueError):
        return ""


def _run_dates(run_dir: Path) -> tuple[str, str]:
    """Read article/effective dates without using filesystem mtime."""
    try:
        run_dir = validate_run_dir(run_dir)
    except (OSError, ValueError):
        return "", ""
    article_date = effective_date = ""
    try:
        research_path = safe_run_path(run_dir, "article_research.json", must_exist=True, label="article research")
    except FileNotFoundError:
        research_path = None
    except (OSError, ValueError):
        return "", ""
    if research_path is not None and research_path.is_file():
        try:
            research = json.loads(research_path.read_text(encoding="utf-8-sig"))
            article = research.get("article", {}) if isinstance(research, dict) else {}
            article_date = _date8(article.get("target_date"))
            effective_date = _date8(article.get("effective_trade_date"))
        except (OSError, ValueError, json.JSONDecodeError):
            pass
    try:
        manifest_path = safe_run_path(run_dir, "wechat_v3_preselect_manifest.json", must_exist=True, label="V3 manifest")
    except FileNotFoundError:
        manifest_path = None
    except (OSError, ValueError):
        return "", ""
    if manifest_path is not None and manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
            if isinstance(manifest, dict):
                article_date = article_date or _date8(manifest.get("article_publish_date") or manifest.get("signal_date"))
                effective_date = effective_date or _date8(manifest.get("effective_trade_date"))
        except (OSError, ValueError, json.JSONDecodeError):
            pass
    if not article_date:
        match = re.search(r"(20\d{6})", run_dir.name)
        article_date = match.group(1) if match else ""
    return article_date, effective_date


def find_previous_run_dir(
    current_run_dir: Path,
    current_article_date: str = "",
    current_effective_trade_date: str = "",
) -> Path | None:
    """Find the newest run strictly before the current article/effective dates.

    Directory mtime and a bare directory-name sort are not date semantics: a
    future or same-day article can be copied into the run directory later and
    would otherwise be selected as "yesterday".  Both dates are therefore
    compared independently whenever the current run provides them.
    """
    current_run_dir = validate_run_dir(current_run_dir)
    current_article_date = _date8(current_article_date)
    current_effective_trade_date = _date8(current_effective_trade_date)
    if not current_article_date and not current_effective_trade_date:
        current_article_date, current_effective_trade_date = _run_dates(current_run_dir)

    candidates: list[tuple[Path, str, str]] = []
    runs_root = Path(RUNS_DIR)
    if runs_root.is_symlink() or not runs_root.is_dir():
        return None
    try:
        _reject_symlink_components(runs_root, "runs root")
    except (OSError, ValueError):
        return None
    for run_dir in sorted(runs_root.iterdir()):
        if run_dir.is_symlink() or not run_dir.is_dir() or not re.match(r"^20\d{6}(?:_|$)", run_dir.name):
            continue
        try:
            _reject_symlink_components(run_dir, "candidate run")
        except (OSError, ValueError):
            continue
        if run_dir == current_run_dir:
            continue
        try:
            manifest_path = safe_run_path(run_dir, "wechat_v3_preselect_manifest.json", must_exist=True, label="candidate manifest")
        except (OSError, ValueError, FileNotFoundError):
            continue
        article_date, effective_date = _run_dates(run_dir)
        if not article_date:
            continue
        if current_article_date and (not article_date or article_date >= current_article_date):
            continue
        if current_effective_trade_date and (not effective_date or effective_date >= current_effective_trade_date):
            continue
        candidates.append((run_dir, article_date, effective_date))
    if not candidates:
        return None
    return max(candidates, key=lambda item: (item[1], item[2], item[0].name))[0]


def resolve_run_artifact(run_dir: Path, manifest_value: str | Path) -> Path:
    """Resolve a manifest artifact copied from Windows onto macOS.

    Historical manifests store absolute Windows paths.  The run-local copy is
    authoritative after migration, so try direct/native and run-relative
    spellings before falling back to the Windows basename.
    """

    run_dir = validate_run_dir(run_dir)
    raw = str(manifest_value or "").strip()
    if not raw:
        raise ValueError("manifest artifact path is empty")
    if "\x00" in raw or ".." in Path(raw).parts or ".." in PureWindowsPath(raw).parts:
        raise ValueError("manifest artifact traversal is not allowed")

    direct = Path(raw)
    pointer_suffixes = {".txt", ".pointer", ".ptr", ".path"}
    if direct.suffix.lower() in pointer_suffixes and not PureWindowsPath(raw).drive:
        pointer = safe_run_path(run_dir, raw, must_exist=True, label="manifest pointer")
        if pointer.is_symlink():
            raise ValueError("manifest pointer must not be a symlink")
        target_raw = pointer.read_text(encoding="utf-8-sig").strip()
        if not target_raw or ".." in Path(target_raw).parts or ".." in PureWindowsPath(target_raw).parts:
            raise ValueError("manifest pointer target is unsafe")
        if PureWindowsPath(target_raw).drive:
            basename = PureWindowsPath(target_raw).name
            if not basename:
                raise ValueError("manifest pointer target has no basename")
            return safe_run_path(run_dir, basename, must_exist=True, label="manifest artifact")
        if Path(target_raw).is_absolute():
            raise ValueError("manifest pointer target must be run-local or Windows-origin")
        return safe_run_path(pointer.parent, target_raw, must_exist=True, label="manifest artifact")

    if PureWindowsPath(raw).drive:
        basename = PureWindowsPath(raw).name
        if not basename:
            raise ValueError("Windows manifest path has no basename")
        return safe_run_path(run_dir, basename, must_exist=True, label="manifest artifact")
    return safe_run_path(run_dir, raw, must_exist=True, label="manifest artifact")


def load_pool_and_guard(yesterday_run_dir: Path) -> dict:
    import pandas as pd

    yesterday_run_dir = validate_run_dir(yesterday_run_dir)
    manifest_path = safe_run_path(yesterday_run_dir, "wechat_v3_preselect_manifest.json", must_exist=True, label="yesterday manifest")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    pool_path = resolve_run_artifact(yesterday_run_dir, manifest["wechat_pool"])
    guard_path = resolve_run_artifact(yesterday_run_dir, manifest["outputs"]["guard_pass"])
    pool = pd.read_csv(pool_path, encoding="utf-8-sig")
    guard = pd.read_csv(guard_path, encoding="utf-8-sig")
    guard_codes = set(guard["ts_code"].astype(str)) if "ts_code" in guard.columns else set()
    return {
        "manifest": manifest,
        "effective_trade_date": str(manifest.get("effective_trade_date", "")),
        "pool": pool,
        "guard_codes": guard_codes,
    }


def build_yesterday_performance(
    yesterday_run_dir: Path,
    panel_path: str | None = None,
    obs_date: str = "",
) -> dict:
    """返回昨日 run 选股在观察日涨跌幅的统计结果。

    panel 默认取最新研究面板；obs_date 默认取昨日 run 的 effective_trade_date。
    面板最新 trade_date < obs_date 时返回 PANEL_LAG，不编造涨幅。
    """
    import pandas as pd

    loaded = load_pool_and_guard(yesterday_run_dir)
    pool = loaded["pool"]
    if obs_date:
        obs_date = normalize_date(obs_date, label="observation date")
    if loaded["effective_trade_date"]:
        loaded["effective_trade_date"] = normalize_date(loaded["effective_trade_date"], label="effective trade date")
    obs_date = obs_date or loaded["effective_trade_date"]
    panel_path = panel_path or current_selector_panel_path()
    panel_raw = str(panel_path or "").strip()
    if not panel_raw or "\x00" in panel_raw or ".." in Path(panel_raw).parts or ".." in PureWindowsPath(panel_raw).parts:
        raise ValueError("selector panel path is unsafe")
    if PureWindowsPath(panel_raw).drive:
        panel_path = str(resolve_run_artifact(yesterday_run_dir, panel_raw))
    else:
        panel_candidate = Path(panel_raw)
        if panel_candidate.is_symlink() or panel_candidate.resolve(strict=False) == Path("/etc/hosts"):
            raise ValueError("selector panel must be a non-symlink local file")
        _reject_symlink_components(panel_candidate, "selector panel")
        panel_path = str(panel_candidate.resolve(strict=False))
    if not Path(panel_path).is_file():
        raise FileNotFoundError(panel_path)

    panel = pd.read_parquet(panel_path, columns=["trade_date", "ts_code", "name", "pct_chg"])
    panel["trade_date"] = panel["trade_date"].astype(str)
    panel["ts_code"] = panel["ts_code"].astype(str)

    available_dates = set(panel["trade_date"].unique())
    if obs_date not in available_dates:
        return {
            "status": "PANEL_LAG",
            "obs_date": obs_date,
            "panel_latest_date": max(available_dates) if available_dates else "",
            "note": "面板尚未覆盖观察日，未编造涨幅；等面板更新后重跑",
            "boundary": BOUNDARY,
        }

    obs = panel[panel["trade_date"] == obs_date][["ts_code", "name", "pct_chg"]].copy()
    obs = obs.drop_duplicates(subset="ts_code")

    # 全文池 join（A/BJ 取 pct_chg；HK 恒 NaN 标记 HK_OUT_OF_PANEL）
    pool_cols = ["ts_code", "name"] + [c for c in pool.columns if c in ("hit_count", "wechat_hit_count")]
    work = pool[pool_cols].copy()
    work["ts_code"] = work["ts_code"].astype(str)
    merged = work.merge(obs, on="ts_code", how="left", suffixes=("", "_panel"))
    merged["market"] = merged["ts_code"].str.split(".").str[-1]
    merged["guard_pass"] = merged["ts_code"].isin(loaded["guard_codes"])
    merged["source"] = merged.apply(
        lambda r: "PANEL_PCT" if r["market"] in ("SH", "SZ", "BJ") and pd.notna(r["pct_chg"])
        else ("HK_OUT_OF_PANEL" if r["market"] == "HK" else "PANEL_MISSING"),
        axis=1,
    )

    a_bj = merged[merged["market"].isin(["SH", "SZ", "BJ"])]
    matched = a_bj[a_bj["pct_chg"].notna()]
    pcts = matched["pct_chg"].astype(float)
    up = int((pcts > 0).sum())
    down = int((pcts < 0).sum())
    flat = int((pcts == 0).sum())
    top5 = matched.nlargest(5, "pct_chg")[["ts_code", "name", "pct_chg"]].to_dict("records")
    bottom5 = matched.nsmallest(5, "pct_chg")[["ts_code", "name", "pct_chg"]].to_dict("records")

    guard_rows = matched[matched["guard_pass"]]

    result = {
        "status": "OK",
        "obs_date": obs_date,
        "panel_path": str(panel_path),
        "yesterday_run_dir": str(yesterday_run_dir),
        "yesterday_article_publish_date": str(loaded["manifest"].get("article_publish_date", "")),
        "pool_total": int(len(pool)),
        "a_bj_total": int(len(a_bj)),
        "matched": int(len(matched)),
        "match_rate": round(len(matched) / len(a_bj) * 100, 1) if len(a_bj) else 0.0,
        "summary": {
            "mean_pct": round(float(pcts.mean()), 2) if len(pcts) else None,
            "median_pct": round(float(pcts.median()), 2) if len(pcts) else None,
            "up": up,
            "down": down,
            "flat": flat,
        },
        "guard_pass_total": int(len(guard_rows)),
        "top5": top5,
        "bottom5": bottom5,
        "full_rows": merged[
            ["ts_code", "name", "hit_count" if "hit_count" in merged.columns else "wechat_hit_count",
             "pct_chg", "guard_pass", "source"]
        ].rename(columns={"hit_count" if "hit_count" in merged.columns else "wechat_hit_count": "hit_count"}).to_dict("records"),
        "boundary": BOUNDARY,
    }
    return result


def render_yesterday_markdown(result: dict) -> str:
    if result.get("status") == "PANEL_LAG":
        return (
            f"## 昨日选股今日表现（观察日 {result['obs_date']}）\n\n"
            f"> 面板最新交易日 {result.get('panel_latest_date')} 尚未覆盖观察日，未编造涨幅；"
            f"等面板更新后重跑。\n"
        )
    lines = [
        f"## 昨日选股今日表现（观察日 {result['obs_date']}）",
        "",
        f"- 昨日文章 {result.get('yesterday_article_publish_date', '')} 选股 {result['pool_total']} 只（A/BJ {result['a_bj_total']}），"
        f"观察日匹配 {result['matched']}/{result['a_bj_total']}（{result['match_rate']}%）",
        f"- 涨跌：↑{result['summary']['up']} / ↓{result['summary']['down']} / 平{result['summary']['flat']}；"
        f"平均 {result['summary']['mean_pct']}%，中位数 {result['summary']['median_pct']}%",
        f"- 优先观察队列（guard_pass）{result['guard_pass_total']} 只表现见下表",
        "",
    ]
    if result["top5"]:
        lines.append("### 涨幅前 5")
        lines.append("| 代码 | 名称 | 涨跌幅% |")
        lines.append("| --- | --- | --- |")
        for r in result["top5"]:
            lines.append(f"| {r['ts_code']} | {r['name']} | {r['pct_chg']:.2f} |")
        lines.append("")
    if result["bottom5"]:
        lines.append("### 跌幅前 5")
        lines.append("| 代码 | 名称 | 涨跌幅% |")
        lines.append("| --- | --- | --- |")
        for r in result["bottom5"]:
            lines.append(f"| {r['ts_code']} | {r['name']} | {r['pct_chg']:.2f} |")
        lines.append("")
    lines.append("### 优先观察队列（guard_pass）")
    lines.append("| 代码 | 名称 | 提及 | 涨跌幅% |")
    lines.append("| --- | --- | --- | --- |")
    for r in result["full_rows"]:
        if r["guard_pass"]:
            pct = f"{r['pct_chg']:.2f}" if not _is_missing_number(r["pct_chg"]) else "-"
            lines.append(f"| {r['ts_code']} | {r['name']} | {r['hit_count']} | {pct} |")
    lines.append("")
    lines.append("_RESEARCH_ONLY / WATCH_ONLY / NO_BUY_GATE；数据来自本地研究面板，非实时行情。_")
    return "\n".join(lines)


def embed_yesterday_markdown(review_path: Path, block: str) -> None:
    """把昨日表现块前置到 master_controller_review.md 的 '## 结论先行' 之后。"""
    review_path = Path(review_path)
    if review_path.is_symlink() or ".." in review_path.parts or review_path.resolve(strict=False) == Path("/etc/hosts"):
        raise ValueError("review path must not be a symlink or traversal path")
    _reject_symlink_components(review_path, "review path")
    text = review_path.read_text(encoding="utf-8-sig")
    marker = "## 结论先行"
    idx = text.find(marker)
    if idx < 0:
        review_path.write_text(block + "\n\n" + text, encoding="utf-8-sig")
        return
    insert_at = text.find("\n##", idx + len(marker))
    if insert_at < 0:
        insert_at = len(text)
    review_path.write_text(text[:insert_at] + "\n\n" + block.strip() + "\n" + text[insert_at:], encoding="utf-8-sig")


class PerformanceAppendixError(ValueError):
    """Raised when a prior-article appendix input cannot be safely bound."""


def _is_missing_number(value: object) -> bool:
    if value is None:
        return True
    try:
        return bool(math.isnan(float(value)))
    except (TypeError, ValueError, OverflowError):
        return False


def _positive_finite_number(value: object) -> bool:
    if isinstance(value, bool):
        return False
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return False
    return math.isfinite(number) and number > 0


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _json_no_duplicate_keys(payload: bytes, *, label: str) -> dict:
    def pairs_no_duplicates(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise PerformanceAppendixError(f"{label} contains duplicate JSON keys")
            value[key] = item
        return value

    try:
        result = json.loads(payload.decode("utf-8-sig"), object_pairs_hook=pairs_no_duplicates)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PerformanceAppendixError(f"{label} is not valid UTF-8 JSON") from exc
    if not isinstance(result, dict):
        raise PerformanceAppendixError(f"{label} must be a JSON object")
    return result


def _checked_read_path(value: str | Path, *, label: str, must_exist: bool = True) -> Path:
    raw = str(value or "").strip()
    if not raw or "\x00" in raw or ".." in Path(raw).parts or ".." in PureWindowsPath(raw).parts:
        raise PerformanceAppendixError(f"unsafe {label}")
    path = Path(raw)
    if path.is_symlink():
        raise PerformanceAppendixError(f"{label} must not be a symlink")
    try:
        _reject_symlink_components(path, label)
    except (OSError, ValueError) as exc:
        raise PerformanceAppendixError(str(exc)) from exc
    resolved = path.resolve(strict=False)
    if must_exist and not resolved.exists():
        raise FileNotFoundError(f"{label} does not exist: {resolved}")
    return resolved


def _load_prior_article_mentions(article_dir_value: str | Path) -> dict:
    article_dir = _checked_read_path(article_dir_value, label="prior article archive")
    if not article_dir.is_dir():
        raise PerformanceAppendixError("prior article archive must be a directory")
    receipt_path = article_dir / "IMPORT_RECEIPT.json"
    summary_path = article_dir / "summary.json"
    mentions_path = article_dir / "mentions.csv"
    for path, label in ((receipt_path, "prior IMPORT_RECEIPT.json"),
                        (summary_path, "prior summary.json"),
                        (mentions_path, "prior mentions.csv")):
        if path.is_symlink():
            raise PerformanceAppendixError(f"{label} must not be a symlink")
        _reject_symlink_components(path, label)
        if not path.is_file():
            raise FileNotFoundError(f"{label} is missing: {path}")

    receipt_bytes = receipt_path.read_bytes()
    summary_bytes = summary_path.read_bytes()
    mentions_bytes = mentions_path.read_bytes()
    receipt = _json_no_duplicate_keys(receipt_bytes, label="IMPORT_RECEIPT.json")
    summary = _json_no_duplicate_keys(summary_bytes, label="summary.json")
    binding = receipt.get("binding")
    acceptance = receipt.get("local_acceptance")
    if not isinstance(binding, dict) or not isinstance(acceptance, dict):
        raise PerformanceAppendixError("prior archive receipt lacks binding or local acceptance")
    if receipt.get("status") != "REPORT_AND_STRUCTURED_ARCHIVED":
        raise PerformanceAppendixError("prior archive is not structurally archived")
    if (binding.get("package_identity_status") != "VERIFIED"
            or binding.get("package_sha256_status") != "VERIFIED"
            or binding.get("package_sha256_declared") != binding.get("package_sha256_observed")
            or acceptance.get("input_binding_valid") is not True
            or acceptance.get("structure_valid") is not True):
        raise PerformanceAppendixError("prior archive does not have a trusted package/input binding")

    package_id = str(binding.get("package_id") or "")
    input_digest = str(binding.get("input_digest") or "")
    article_date = normalize_date(binding.get("article_date"), label="prior article date")
    published_at = str(binding.get("published_at") or "")
    try:
        published_dt = datetime.fromisoformat(published_at)
    except ValueError as exc:
        raise PerformanceAppendixError("prior published_at must be ISO-8601") from exc
    if published_dt.tzinfo is None or published_dt.utcoffset() is None:
        raise PerformanceAppendixError("prior published_at must include its timezone")
    if published_dt.strftime("%Y%m%d") != article_date:
        raise PerformanceAppendixError("prior article date differs from timezone-aware published_at")
    if not package_id or not re.fullmatch(r"[0-9a-f]{64}", input_digest):
        raise PerformanceAppendixError("prior package_id/input_digest is missing or invalid")
    if (summary.get("package_id") != package_id
            or summary.get("input_digest") != input_digest
            or summary.get("url") != binding.get("article_url")
            or normalize_date(summary.get("article_date"), label="summary article date") != article_date):
        raise PerformanceAppendixError("prior summary identity does not match its import receipt")
    if any(summary.get(flag) is not False for flag in
           ("production_allowed", "buy_gate_updated", "orders_sent")):
        raise PerformanceAppendixError("prior summary safety flags must all be false")

    archive_files = receipt.get("archived_files")
    summary_record = archive_files.get("summary") if isinstance(archive_files, dict) else None
    if (not isinstance(summary_record, dict)
            or summary_record.get("sha256") != _sha256_bytes(summary_bytes)):
        raise PerformanceAppendixError("summary.json bytes do not match the trusted archive receipt")

    mentions_sha = _sha256_bytes(mentions_bytes)
    archive_files = receipt.get("archived_files")
    mention_receipt = archive_files.get("mentions") if isinstance(archive_files, dict) else None
    summary_hashes = summary.get("artifact_sha256")
    if (not isinstance(mention_receipt, dict)
            or mention_receipt.get("sha256") != mentions_sha
            or not isinstance(summary_hashes, dict)
            or summary_hashes.get("mentions.csv") != mentions_sha):
        raise PerformanceAppendixError("mentions.csv bytes do not match the trusted archive receipt and summary")

    try:
        text = mentions_bytes.decode("utf-8-sig")
    except UnicodeError as exc:
        raise PerformanceAppendixError("mentions.csv is not UTF-8") from exc
    parsed_mentions = list(csv.DictReader(io.StringIO(text, newline="")))
    reader = iter(parsed_mentions)
    required_headers = {"market", "code", "name", "source_index", "entity_id"}
    fieldnames = csv.DictReader(io.StringIO(text, newline="")).fieldnames
    if not fieldnames or not required_headers.issubset(set(fieldnames)):
        raise PerformanceAppendixError("mentions.csv does not have the required listing identity fields")

    code_patterns = {
        "A": re.compile(r"^\d{6}\.(?:SH|SZ)$"),
        "BJ": re.compile(r"^\d{6}\.BJ$"),
        "HK": re.compile(r"^\d{5}\.HK$"),
    }
    rows_by_listing: dict[tuple[str, str], dict] = {}
    issuer_by_listing: dict[tuple[str, str], str] = {}
    for row in reader:
        market = str(row.get("market") or "").strip().upper()
        code = str(row.get("code") or "").strip().upper()
        name = " ".join(str(row.get("name") or "").split())
        entity_id = str(row.get("entity_id") or "").strip()
        source_index = str(row.get("source_index") or "").strip()
        if market not in code_patterns or not code_patterns[market].fullmatch(code):
            raise PerformanceAppendixError(f"invalid market-qualified listing code: {market}/{code}")
        if not name or not entity_id or not source_index:
            raise PerformanceAppendixError(f"mention row lacks name/entity/source identity for {code}")
        key = (market, code)
        if key in rows_by_listing:
            item = rows_by_listing[key]
            if item["name"] != name or issuer_by_listing[key] != entity_id:
                raise PerformanceAppendixError(f"conflicting company identity for listing code {code}")
            item["mention_rows"] += 1
            item["source_indices"].add(source_index)
        else:
            rows_by_listing[key] = {
                "market": market,
                "code": code,
                "name": name,
                "entity_id": entity_id,
                "mention_rows": 1,
                "source_indices": {source_index},
            }
            issuer_by_listing[key] = entity_id

    rows = []
    for key in sorted(rows_by_listing):
        item = rows_by_listing[key]
        item["source_indices"] = sorted(item["source_indices"])
        rows.append(item)
    counts = {market: sum(row["market"] == market for row in rows) for market in ("A", "BJ", "HK")}
    claimed_counts = summary.get("mentions_counts")
    if not isinstance(claimed_counts, dict) or sum(counts.values()) != len(rows):
        raise PerformanceAppendixError("prior summary mention counts are missing")
    for market in ("A", "BJ", "HK"):
        if claimed_counts.get(market) != sum(row.get("market") == market for row in parsed_mentions):
            raise PerformanceAppendixError(f"mentions.csv {market} count differs from the prior summary")

    return {
        "article_dir": str(article_dir),
        "receipt": receipt,
        "receipt_sha256": _sha256_bytes(receipt_bytes),
        "summary": summary,
        "summary_sha256": _sha256_bytes(summary_bytes),
        "mentions_sha256": mentions_sha,
        "package_id": package_id,
        "input_digest": input_digest,
        "package_sha256": binding.get("package_sha256_observed"),
        "manifest_sha256": binding.get("frozen_manifest_sha256_observed"),
        "article_url": binding.get("article_url"),
        "article_title": binding.get("article_title"),
        "article_date": article_date,
        "published_at": published_at,
        "chat_claimed_complete": acceptance.get("chat_claimed_complete") is True,
        "chat_report_status": summary.get("status"),
        "mention_rows": len(parsed_mentions),
        "unique_listings": len(rows),
        "listing_counts": counts,
        "mentions": rows,
    }


def _calendar_day_status(calendar: dict, market_key: str, observation_date: str) -> str:
    try:
        target = datetime.strptime(observation_date, "%Y%m%d").date()
        year = int(calendar.get("year"))
        market = calendar.get("markets", {}).get(market_key)
        official = calendar.get("official_sources", [])
    except (TypeError, ValueError, AttributeError):
        return "CANNOT_CONFIRM_CALENDAR"
    if (calendar.get("schema_version") != f"v3_5.market_calendar_{year}.v1"
            or calendar.get("timezone") != "Asia/Shanghai"
            or target.year != year
            or not isinstance(market, dict)
            or not any(isinstance(item, dict) and item.get("market") == market_key for item in official)):
        return "CANNOT_CONFIRM_CALENDAR"
    if target.weekday() >= 5:
        return "NON_TRADING_DAY"
    for period in market.get("holiday_periods", []):
        try:
            start = datetime.strptime(str(period.get("start")), "%Y%m%d").date()
            end = datetime.strptime(str(period.get("end")), "%Y%m%d").date()
        except (TypeError, ValueError, AttributeError):
            return "CANNOT_CONFIRM_CALENDAR"
        if start <= target <= end:
            return "NON_TRADING_DAY"
    if observation_date in market.get("half_days", []):
        return "HALF_TRADING_DAY"
    return "FULL_TRADING_DAY"


def _load_runtime_config_evidence(evidence_value: str | Path) -> dict:
    evidence_path = _checked_read_path(evidence_value, label="loaded scheduler runtime evidence")
    payload = _json_no_duplicate_keys(evidence_path.read_bytes(), label="runtime pointer discovery")
    if (payload.get("exit_code") != 0
            or payload.get("source") != "launchctl print current loaded scheduler environment"):
        raise PerformanceAppendixError("runtime evidence does not prove the loaded scheduler environment")
    bindings = payload.get("bindings")
    pointer_targets = payload.get("pointer_targets")
    selector_key = "V35_RESEARCH_PANEL_A_SELECTOR_POINTER"
    receipt_key = "V35_RESEARCH_PANEL_RECEIPT_ROOT"
    hk_root_key = "V35_RESEARCH_PANEL_HK_ASSET_ROOT"
    if (not isinstance(bindings, dict) or not isinstance(pointer_targets, dict)
            or any(not isinstance(bindings.get(key), str) or not bindings[key]
                   for key in (selector_key, receipt_key, hk_root_key))
            or not isinstance(pointer_targets.get(selector_key), str)
            or not pointer_targets[selector_key]):
        raise PerformanceAppendixError("runtime evidence omits the configured selector, receipt, or HK asset binding")
    pointer_path = _checked_read_path(bindings[selector_key], label="configured selector pointer")
    receipt_root = _checked_read_path(bindings[receipt_key], label="configured panel receipt root")
    hk_asset_root = _checked_read_path(bindings[hk_root_key], label="configured HK asset root")
    if not pointer_path.is_file() or not receipt_root.is_dir() or not hk_asset_root.is_dir():
        raise PerformanceAppendixError("a configured runtime path is missing")
    pointer_bytes = pointer_path.read_bytes()
    target_raw = pointer_bytes.decode("utf-8-sig").strip()
    expected_target = str(pointer_targets[selector_key]).strip()
    if not target_raw or str(Path(target_raw).resolve(strict=False)) != str(Path(expected_target).resolve(strict=False)):
        raise PerformanceAppendixError("selector pointer bytes differ from the loaded-runtime discovery evidence")
    panel_path = _checked_read_path(target_raw, label="configured selector panel")
    return {
        "evidence_path": str(evidence_path),
        "evidence_sha256": _sha256_bytes(evidence_path.read_bytes()),
        "evidence_observed_at": payload.get("observed_at"),
        "evidence_source": payload.get("source"),
        "bindings": {
            selector_key: str(pointer_path),
            receipt_key: str(receipt_root),
            hk_root_key: str(hk_asset_root),
        },
        "selector_pointer_path": str(pointer_path),
        "pointer_targets": {selector_key: str(panel_path)},
        "selector_pointer_sha256": _sha256_bytes(pointer_bytes),
        "selector_panel_path": str(panel_path),
        "selector_panel_sha256": _sha256_bytes(panel_path.read_bytes()) if panel_path.is_file() else None,
        "receipt_root": str(receipt_root),
        "hk_asset_root": str(hk_asset_root),
    }


def _load_current_package_binding(receipt_value: str | Path) -> dict:
    receipt_path = _checked_read_path(receipt_value, label="current package receipt")
    receipt_bytes = receipt_path.read_bytes()
    receipt = _json_no_duplicate_keys(receipt_bytes, label="current package receipt")
    if receipt.get("status") != "PACKAGE_READY":
        raise PerformanceAppendixError("current package receipt is not PACKAGE_READY")
    package_id = str(receipt.get("package_id") or "")
    input_digest = str(receipt.get("input_digest") or "")
    article_date = normalize_date(receipt.get("article_date"), label="current package article date")
    published_at = str(receipt.get("published_at") or "")
    try:
        published_dt = datetime.fromisoformat(published_at)
    except ValueError as exc:
        raise PerformanceAppendixError("current package published_at must be ISO-8601") from exc
    if published_dt.tzinfo is None or published_dt.utcoffset() is None:
        raise PerformanceAppendixError("current package published_at must include its timezone")
    if published_dt.strftime("%Y%m%d") != article_date:
        raise PerformanceAppendixError("current package article date differs from timezone-aware published_at")
    if not package_id or not re.fullmatch(r"[0-9a-f]{64}", input_digest):
        raise PerformanceAppendixError("current package_id/input_digest is missing or invalid")
    if any(receipt.get(flag) is not False for flag in ("production_allowed", "buy_gate_updated", "orders_sent")):
        raise PerformanceAppendixError("current package safety flags must all be false")
    zip_record = receipt.get("zip")
    if not isinstance(zip_record, dict) or not re.fullmatch(r"[0-9a-f]{64}", str(zip_record.get("sha256") or "")):
        raise PerformanceAppendixError("current package receipt lacks a frozen ZIP SHA-256")
    zip_path_value = str(zip_record.get("path") or "")
    zip_path = Path(zip_path_value)
    if not zip_path.is_absolute():
        zip_path = receipt_path.parent / zip_path
    zip_sha256_observed = None
    if zip_path.exists() or zip_path.is_symlink():
        checked_zip = _checked_read_path(zip_path, label="current frozen package ZIP")
        if not checked_zip.is_file():
            raise PerformanceAppendixError("current frozen package ZIP is not a regular file")
        zip_sha256_observed = _sha256_bytes(checked_zip.read_bytes())
        if zip_sha256_observed != zip_record["sha256"]:
            raise PerformanceAppendixError("current frozen ZIP bytes differ from PACKAGE_RECEIPT.json")
        from wechat_chat_handoff import HandoffError, _validate_package_zip
        try:
            frozen = _validate_package_zip(
                checked_zip, source_run=None, package_id=package_id,
                declared_sha=zip_record["sha256"], observed_sha=zip_sha256_observed,
            )
        except (HandoffError, OSError, ValueError) as exc:
            raise PerformanceAppendixError(f"current frozen package is invalid: {exc}") from exc
        expected = {
            "input_digest": input_digest, "article_date": article_date,
            "article_url": receipt.get("original_url"), "published_at": published_at,
            "package_manifest_sha256_observed": receipt.get("manifest_sha256"),
        }
        if (frozen.get("package_identity_status") != "VERIFIED"
                or any(frozen.get(key) != value for key, value in expected.items())
                or _sha256_bytes(checked_zip.read_bytes()) != zip_sha256_observed):
            raise PerformanceAppendixError("current receipt identity differs from the frozen ZIP")
    return {
        "receipt_path": str(receipt_path),
        "receipt_sha256": _sha256_bytes(receipt_bytes),
        "status": receipt["status"],
        "package_id": package_id,
        "input_digest": input_digest,
        "article_date": article_date,
        "published_at": published_at,
        "article_url": receipt.get("original_url"),
        "manifest_sha256": receipt.get("manifest_sha256"),
        "zip_path": str(zip_path),
        "zip_sha256_declared": zip_record["sha256"],
        "zip_sha256_observed": zip_sha256_observed,
        "zip_sha256_reobserved": zip_sha256_observed is not None,
    }


def _previous_market_session(calendar: dict, market_key: str, observation_date: str) -> str:
    try:
        target = datetime.strptime(observation_date, "%Y%m%d").date()
    except ValueError:
        return ""
    # Market calendars can contain multi-day closures. Search by calendar date,
    # accepting only a session explicitly open in the same official calendar.
    for days_back in range(1, 32):
        candidate = target - timedelta(days=days_back)
        if candidate.year != target.year:
            return ""
        candidate_text = candidate.strftime("%Y%m%d")
        state = _calendar_day_status(calendar, market_key, candidate_text)
        if state in ("FULL_TRADING_DAY", "HALF_TRADING_DAY"):
            return candidate_text
        if state == "CANNOT_CONFIRM_CALENDAR":
            return ""
    return ""


def _safe_asset_relative(root: Path, relative: object, *, label: str) -> Path:
    raw = str(relative or "").strip()
    if not raw or "\x00" in raw or Path(raw).is_absolute() or ".." in Path(raw).parts:
        raise PerformanceAppendixError(f"unsafe {label} relative path")
    return _checked_read_path(root / raw, label=label)


def _read_hk_receipt_and_panel(asset_root: Path, receipt_root: Path, trade_date: str,
                               receipt_facts: dict | None = None) -> dict:
    receipt_path = _checked_read_path(receipt_root / f"hk-{trade_date}.json", label=f"HK {trade_date} receipt")
    receipt_bytes = receipt_path.read_bytes()
    receipt_sha256 = _sha256_bytes(receipt_bytes)
    if receipt_facts is not None:
        receipt_facts.update(receipt_path=str(receipt_path), receipt_sha256=receipt_sha256)
    receipt = _json_no_duplicate_keys(receipt_bytes, label=f"HK {trade_date} receipt")
    if receipt_facts is not None:
        receipt_facts.update(
            receipt_status=receipt.get("status"),
            receipt_rows=receipt.get("row_count"),
            universe_count=receipt.get("universe_count"),
            target_date=receipt.get("target_date"),
        )
    authority = receipt.get("authority")
    if (receipt.get("status") != "READY" or receipt.get("target_date") != trade_date
            or not isinstance(authority, dict) or authority.get("status") != "READY"
            or authority.get("target_date") != trade_date or authority.get("through_date") != trade_date
            or any(receipt.get(flag) is not False for flag in ("production_allowed", "buy_gate_updated", "orders_sent"))
            or any(authority.get(flag) is not False for flag in ("production_allowed", "buy_gate_updated", "orders_sent"))):
        raise PerformanceAppendixError(f"HK {trade_date} receipt is not an exact-date read-only READY receipt")
    manifest_path = _safe_asset_relative(asset_root, authority.get("manifest_relative"),
                                         label=f"HK {trade_date} panel manifest")
    manifest_bytes = manifest_path.read_bytes()
    manifest = _json_no_duplicate_keys(manifest_bytes, label=f"HK {trade_date} panel manifest")
    panel_sha = str(authority.get("panel_sha256") or "")
    manifest_panel_sha = str(manifest.get("panel_sha256") or "")
    if (manifest.get("asset_schema_version") != "v3_shared_data.hk_0_2_panel_asset.v2"
            or manifest.get("increment_contract") != "tdx_vipdoc_71_day_daily_append.v1"
            or panel_sha != manifest_panel_sha
            or not re.fullmatch(r"[0-9a-f]{64}", panel_sha)
            or any(manifest.get(flag) is not False for flag in ("production_allowed", "buy_gate_updated", "orders_sent"))):
        raise PerformanceAppendixError(f"HK {trade_date} manifest failed the panel lineage/safety check")
    panel_path = _safe_asset_relative(asset_root, manifest.get("panel_relative"),
                                      label=f"HK {trade_date} panel parquet")
    panel_bytes_sha = _sha256_bytes(panel_path.read_bytes())
    if panel_bytes_sha != panel_sha:
        raise PerformanceAppendixError(f"HK {trade_date} panel parquet SHA differs from receipt and manifest")
    return {
        "date": trade_date,
        "receipt": receipt,
        "receipt_path": str(receipt_path),
        "receipt_sha256": receipt_sha256,
        "manifest": manifest,
        "manifest_path": str(manifest_path),
        "manifest_sha256": _sha256_bytes(manifest_bytes),
        "panel_path": str(panel_path),
        "panel_sha256": panel_sha,
        "panel_rows": int(receipt.get("row_count", 0)),
        "universe_count": receipt.get("universe_count"),
    }


def _read_hk_date_rows(panel_path: Path, trade_date: str) -> list[dict]:
    import pandas as pd

    frame = pd.read_parquet(
        panel_path,
        columns=["trade_date", "code_norm", "ts_code", "close", "pre_close", "pct_chg"],
        filters=[("trade_date", "==", int(trade_date))],
        engine="pyarrow",
    )
    frame["trade_date"] = frame["trade_date"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(8)
    frame = frame[frame["trade_date"] == trade_date]
    rows = frame.to_dict("records")
    return rows


def _index_rows_by_code(rows: list[dict]) -> tuple[dict[str, dict], set[str]]:
    indexed: dict[str, dict] = {}
    duplicates: set[str] = set()
    for row in rows:
        code = str(row.get("code_norm") or "").strip().upper()
        if not re.fullmatch(r"HK\.\d{5}", code):
            continue
        if code in indexed:
            duplicates.add(code)
        else:
            indexed[code] = row
    for code in duplicates:
        indexed.pop(code, None)
    return indexed, duplicates


def _build_a_bj_panel_probe(runtime: dict, observation_date: str) -> tuple[dict, dict[str, dict]]:
    receipt_path = _checked_read_path(
        Path(runtime["receipt_root"]) / f"a-{observation_date}.json",
        label=f"A/BJ {observation_date} panel receipt",
    )
    receipt_bytes = receipt_path.read_bytes()
    receipt = _json_no_duplicate_keys(receipt_bytes, label=f"A/BJ {observation_date} panel receipt")
    receipt_status = receipt.get("status")
    sync = receipt.get("sync") if isinstance(receipt.get("sync"), dict) else {}
    sync_authority = sync.get("authority") if isinstance(sync.get("authority"), dict) else {}
    probe = {
        "status": "CANNOT_CONFIRM",
        "binding_status": "CANNOT_CONFIRM",
        "receipt_status": receipt_status,
        "receipt_path": str(receipt_path),
        "receipt_sha256": _sha256_bytes(receipt_bytes),
        "receipt_row_count": receipt.get("row_count"),
        "receipt_target_date_file_count": receipt.get("target_date_file_count"),
        "receipt_target_count": receipt.get("target_count"),
        "receipt_accepted_count": receipt.get("accepted_count"),
        "receipt_coverage_rate": receipt.get("coverage_rate"),
        "sync_authority_status": sync_authority.get("authority_status"),
        "selector_pointer_path": runtime.get("selector_pointer_path"),
        "selector_pointer_sha256": runtime.get("selector_pointer_sha256"),
        "selector_panel_path": runtime.get("selector_panel_path"),
        "selector_panel_sha256": None,
        "exact_date_rows": None,
        "exact_date_unique_codes": None,
        "duplicate_codes": [],
    }
    try:
        if receipt_status not in ("READY", "PARTIAL"):
            probe["reason"] = f"A/BJ {observation_date} receipt status {receipt_status!r} is not READY or PARTIAL."
            return probe, {}
        panel_path = _checked_read_path(Path(runtime["selector_panel_path"]), label="configured selector panel")
        panel_bytes = panel_path.read_bytes()
        panel_sha256 = _sha256_bytes(panel_bytes)
        probe.update(selector_panel_path=str(panel_path), selector_panel_sha256=panel_sha256)
        formula = receipt.get("formula")
        if not isinstance(formula, dict):
            probe["reason"] = "A/BJ receipt is missing its formula selector binding."
            return probe, {}
        formula_selector = _checked_read_path(formula.get("selector"), label="A/BJ receipt selector path")
        exact_binding = (
            receipt.get("target_date") == observation_date
            and formula.get("target_date") in (observation_date, int(observation_date))
            and str(formula_selector) == str(panel_path)
            and receipt.get("selector_sha256") == panel_sha256
            and formula.get("selector_sha256") == panel_sha256
            and formula.get("status") == "READY"
            and receipt.get("production_allowed") is False
            and receipt.get("buy_gate_updated") is False
            and receipt.get("orders_sent") is False
        )
        probe["formula_status"] = formula.get("status")
        if not exact_binding:
            probe["reason"] = "A/BJ receipt does not bind the current configured exact-date selector panel."
            return probe, {}

        import pandas as pd

        frame = pd.read_parquet(
            panel_path,
            columns=["trade_date", "ts_code", "name", "close", "pre_close", "pct_chg", "market_type"],
            engine="pyarrow",
        )
        frame["trade_date"] = frame["trade_date"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(8)
        frame["ts_code"] = frame["ts_code"].astype(str).str.strip().str.upper()
        frame = frame[frame["trade_date"] == observation_date]
        duplicate_codes = set(frame.loc[frame["ts_code"].duplicated(keep=False), "ts_code"].tolist())
        rows_by_code = {}
        for row in frame.to_dict("records"):
            code = row["ts_code"]
            if code not in duplicate_codes:
                rows_by_code[code] = row
        probe.update(
            exact_date_rows=len(frame),
            exact_date_unique_codes=frame["ts_code"].nunique(),
            duplicate_codes=sorted(duplicate_codes),
        )
        expected_count = receipt.get("row_count")
        if isinstance(expected_count, bool) or not isinstance(expected_count, int) or expected_count != len(frame):
            probe["reason"] = (
                f"A/BJ receipt row_count {expected_count!r} differs from exact-date parquet rows {len(frame)}; "
                "no A/BJ price rows are released."
            )
            probe["binding_error"] = "ROW_COUNT_MISMATCH"
            return probe, {}
        probe.update(
            status="PARTIAL_RECEIPT_EXACT_ROWS_OBSERVED" if receipt_status == "PARTIAL" else "EXACT_ROWS_OBSERVED",
            binding_status="BOUND",
            reason=(
                "The receipt is PARTIAL; only unique exact-date rows that reconcile are usable, and the receipt "
                "coverage and sync authority remain separately disclosed."
                if receipt_status == "PARTIAL" else
                "Per-code exact-date rows are used only after matching the configured pointer and receipt."
            ),
        )
        return probe, rows_by_code
    except (OSError, PerformanceAppendixError, ImportError, ValueError, RuntimeError) as exc:
        probe["reason"] = f"{type(exc).__name__}: {exc}"
        return probe, {}

def _build_hk_panel_probe(runtime: dict, observation_date: str, prior_session_date: str,
                          calendar_status: dict) -> tuple[dict, dict, dict, dict]:
    receipt_root_value = str(runtime.get("receipt_root") or "")
    current_receipt_path = str(Path(receipt_root_value) / f"hk-{observation_date}.json") if receipt_root_value else ""
    previous_receipt_path = str(Path(receipt_root_value) / f"hk-{prior_session_date}.json") if receipt_root_value else ""
    probe = {
        "status": "CANNOT_CONFIRM",
        "binding_status": "CANNOT_CONFIRM",
        "target_date": observation_date,
        "previous_hk_session_date": prior_session_date,
        "calendar_status": calendar_status.get("HK"),
        "current_receipt_path": current_receipt_path,
        "current_receipt_status": "CANNOT_CONFIRM",
        "previous_receipt_path": previous_receipt_path,
        "previous_receipt_status": "CANNOT_CONFIRM",
        "missing_previous_receipt_date": prior_session_date,
        "missing_previous_receipt_path": previous_receipt_path,
        "parent_panel_sha256_matches": False,
        "corporate_action_adjustment_status": "NOT_VERIFIED",
    }
    current_receipt_facts: dict = {}
    try:
        asset_root = _checked_read_path(runtime["hk_asset_root"], label="configured HK asset root")
        receipt_root = _checked_read_path(runtime["receipt_root"], label="configured panel receipt root")
        current = _read_hk_receipt_and_panel(
            asset_root, receipt_root, observation_date, receipt_facts=current_receipt_facts,
        )
    except (OSError, PerformanceAppendixError, ValueError, RuntimeError) as exc:
        if current_receipt_facts:
            probe.update(
                current_receipt_path=current_receipt_facts.get("receipt_path", current_receipt_path),
                current_receipt_sha256=current_receipt_facts.get("receipt_sha256"),
                current_receipt_status=current_receipt_facts.get("receipt_status", "CANNOT_CONFIRM"),
                current_receipt_rows=current_receipt_facts.get("receipt_rows"),
                current_universe_count=current_receipt_facts.get("universe_count"),
                current_receipt_target_date=current_receipt_facts.get("target_date"),
                current_receipt_read_status="READ_OK_BINDING_FAILED",
            )
        probe["reason"] = f"{type(exc).__name__}: {exc}"
        if not current_receipt_facts:
            probe["missing_current_receipt_date"] = observation_date
        return probe, {}, {}, {}

    probe.update(
        current_receipt_path=current["receipt_path"],
        current_receipt_sha256=current["receipt_sha256"],
        current_receipt_status=current["receipt"].get("status"),
        current_receipt_rows=current["panel_rows"],
        current_universe_count=current["universe_count"],
        current_manifest_path=current["manifest_path"],
        current_manifest_sha256=current["manifest_sha256"],
        current_panel_path=current["panel_path"],
        current_panel_sha256=current["panel_sha256"],
    )
    try:
        previous = _read_hk_receipt_and_panel(asset_root, receipt_root, prior_session_date)
    except (OSError, PerformanceAppendixError, ValueError, RuntimeError) as exc:
        probe["previous_receipt_status"] = "MISSING_OR_INVALID"
        probe["reason"] = f"{type(exc).__name__}: {exc}"
        probe["missing_previous_receipt_date"] = prior_session_date
        probe["missing_previous_receipt_path"] = previous_receipt_path
        return probe, {}, {}, {}

    probe.update(
        previous_receipt_path=previous["receipt_path"],
        previous_receipt_sha256=previous["receipt_sha256"],
        previous_receipt_status=previous["receipt"].get("status"),
        previous_receipt_rows=previous["panel_rows"],
        previous_manifest_path=previous["manifest_path"],
        previous_manifest_sha256=previous["manifest_sha256"],
        previous_panel_path=previous["panel_path"],
        previous_panel_sha256=previous["panel_sha256"],
    )
    try:
        if current["manifest"].get("parent_panel_sha256") != previous["panel_sha256"]:
            probe["reason"] = "Current HK panel does not link to the exact previous-session panel SHA."
            return probe, {}, {}, {}
        current_rows = _read_hk_date_rows(Path(current["panel_path"]), observation_date)
        current_previous_rows = _read_hk_date_rows(Path(current["panel_path"]), prior_session_date)
        previous_rows = _read_hk_date_rows(Path(previous["panel_path"]), prior_session_date)
        if len(current_rows) != current["panel_rows"] or len(previous_rows) != previous["panel_rows"]:
            probe["reason"] = "HK exact-date parquet row counts differ from their receipts."
            return probe, {}, {}, {}
        current_by_code, current_duplicates = _index_rows_by_code(current_rows)
        current_previous_by_code, current_previous_duplicates = _index_rows_by_code(current_previous_rows)
        previous_by_code, previous_duplicates = _index_rows_by_code(previous_rows)
        native = current["manifest"].get("native_observation", {})
        price_meta = (native.get("fields") or {}).get("price", {}) if isinstance(native, dict) else {}
        probe.update({
            "status": "VERIFIED_EXACT_DATE_PANEL_CHAIN",
            "binding_status": "BOUND",
            "parent_panel_sha256_matches": True,
            "current_rows_by_code": len(current_by_code),
            "previous_rows_by_code": len(previous_by_code),
            "duplicate_codes": {
                "current": sorted(current_duplicates),
                "current_panel_previous_date": sorted(current_previous_duplicates),
                "previous_panel": sorted(previous_duplicates),
            },
            "native_session_finality": native.get("session_finality"),
            "native_price_transform": price_meta.get("transform"),
            "native_currency_status": price_meta.get("currency_status"),
            "reason": (
                "Uses the configured HK asset panel only. Each observed listing requires current and prior-session "
                "rows to reconcile through the parent panel; provider finality and corporate-action adjustment remain unverified."
            ),
        })
        return probe, current_by_code, current_previous_by_code, previous_by_code
    except (OSError, PerformanceAppendixError, ImportError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        probe["reason"] = f"{type(exc).__name__}: {exc}"
        return probe, {}, {}, {}

def _count_market_rows(rows: list[dict], market: str, source_probe: dict) -> dict:
    relevant = [row for row in rows if row["market"] == market]
    observed = [row for row in relevant if row["status"].startswith("OBSERVED_")]
    unavailable = [row for row in relevant if row["status"] == "CANNOT_CONFIRM"]
    if not relevant:
        status = "NO_MENTIONS"
    elif all(row["status"] == "NO_TRADING_SESSION" for row in relevant):
        status = "NO_TRADING_SESSION"
    elif unavailable and observed:
        status = "PARTIAL_DATA"
    elif unavailable:
        status = "CANNOT_CONFIRM"
    else:
        status = "OBSERVED_ALL_ARCHIVED_LISTINGS"
    return {
        "status": status,
        "mentioned_listings": len(relevant),
        "observed_listings": len(observed),
        "cannot_confirm_listings": len(unavailable),
        "coverage_pct": round(len(observed) / len(relevant) * 100.0, 1) if relevant else None,
        "source_status": source_probe.get("status"),
    }


def build_prior_mentions_performance_appendix(
    *,
    prior_article_dir: str | Path,
    current_package_receipt: str | Path,
    observation_date: str,
    runtime_config_evidence: str | Path | None,
    calendar_json: str | Path,
) -> dict:
    """Build a separate appendix bound to both article packages and live data receipts."""
    observation_date = normalize_date(observation_date, label="observation date")
    article = _load_prior_article_mentions(prior_article_dir)
    current_package = _load_current_package_binding(current_package_receipt)
    try:
        previous_published = datetime.fromisoformat(article["published_at"])
        current_published = datetime.fromisoformat(current_package["published_at"])
    except ValueError as exc:
        raise PerformanceAppendixError("article package publication timestamps must be ISO-8601") from exc
    if current_published <= previous_published:
        raise PerformanceAppendixError("the selected prior article was not published before the current package")
    calendar_path = _checked_read_path(calendar_json, label="market calendar")
    calendar_bytes = calendar_path.read_bytes()
    calendar = _json_no_duplicate_keys(calendar_bytes, label="market calendar")
    calendar_sha = _sha256_bytes(calendar_bytes)
    calendar_status = {
        "A": _calendar_day_status(calendar, "a_share", observation_date),
        "BJ": _calendar_day_status(calendar, "a_share", observation_date),
        "HK": _calendar_day_status(calendar, "hk_securities", observation_date),
    }
    try:
        article_date = datetime.strptime(article["article_date"], "%Y%m%d").date()
        obs_date = datetime.strptime(observation_date, "%Y%m%d").date()
    except ValueError as exc:
        raise PerformanceAppendixError("invalid prior article or observation date") from exc
    if article_date >= obs_date:
        raise PerformanceAppendixError("prior article date must be strictly before the observation date")
    date_gap = (obs_date - article_date).days
    article_relation = "EXACT_PREVIOUS_CALENDAR_DAY" if date_gap == 1 else "OLDER_ARTICLE_DATE_EXPLICITLY_SHOWN"
    runtime = None
    runtime_error = None
    if runtime_config_evidence:
        try:
            runtime = _load_runtime_config_evidence(runtime_config_evidence)
        except (OSError, PerformanceAppendixError, ValueError) as exc:
            runtime_error = f"{type(exc).__name__}: {exc}"
    all_rows = []
    by_market = {market: [] for market in ("A", "BJ", "HK")}
    for source in article["mentions"]:
        market = source["market"]
        day_state = calendar_status[market]
        metric_mode = "CLOSE_TO_PRE_CLOSE" if market in ("A", "BJ") else "RAW_CLOSE_TO_PRIOR_SESSION_CLOSE"
        denominator = "(close / pre_close - 1) * 100" if market in ("A", "BJ") else "(current close / prior HK session close - 1) * 100"
        row = {
            "market": market,
            "code": source["code"],
            "name": source["name"],
            "entity_id": source["entity_id"],
            "mention_rows": source["mention_rows"],
            "source_indices": source["source_indices"],
            "observation_date": observation_date,
            "calendar_status": day_state,
            "metric_mode": metric_mode,
            "metric_definition": denominator,
            "pct_chg_close": None,
            "close": None,
            "pre_close": None,
            "prior_session_date": None,
            "prior_session_close": None,
            "as_of": None,
            "source": None,
        }
        if day_state == "NON_TRADING_DAY":
            row.update({"status": "NO_TRADING_SESSION", "reason": "The official calendar marks the market closed on the observation date."})
        elif day_state not in ("FULL_TRADING_DAY", "HALF_TRADING_DAY"):
            row.update({"status": "CANNOT_CONFIRM", "reason": "The configured market calendar cannot confirm this observation session."})
        elif runtime is None:
            row.update({"status": "CANNOT_CONFIRM", "reason": runtime_error or "No loaded scheduler runtime evidence was provided."})
        elif market in ("A", "BJ"):
            # A and BJ share the current configured selector-ready panel, but
            # each archive listing remains independently validated.
            row["source"] = "V35_CONFIGURED_SELECTOR_READY_PANEL"
            row["source_path"] = runtime["selector_panel_path"]
            row["source_sha256"] = runtime["selector_panel_sha256"]
            row["source_receipt_path"] = str(Path(runtime["receipt_root"]) / f"a-{observation_date}.json")
            try:
                if "_a_panel_cache" not in locals():
                    try:
                        a_probe, a_rows_by_code = _build_a_bj_panel_probe(runtime, observation_date)
                    except (OSError, PerformanceAppendixError, ImportError, ValueError, RuntimeError) as exc:
                        a_probe, a_rows_by_code = ({
                            "status": "CANNOT_CONFIRM", "binding_status": "CANNOT_CONFIRM",
                            "reason": f"{type(exc).__name__}: {exc}",
                        }, {})
                    _a_panel_cache = (a_probe, a_rows_by_code)
                else:
                    a_probe, a_rows_by_code = _a_panel_cache
                if a_probe.get("receipt_sha256"):
                    row["source_receipt_sha256"] = a_probe["receipt_sha256"]
                exact_row = a_rows_by_code.get(source["code"])
                expected_type = "BJ" if market == "BJ" else "A_SHARE"
                if exact_row is None:
                    reason = a_probe.get("reason") or "No unique exact-date selector row exists for this listing code."
                    if source["code"] in a_probe.get("duplicate_codes", []):
                        reason = "The configured selector panel has duplicate exact-date rows for this listing code."
                    row.update({"status": "CANNOT_CONFIRM", "reason": reason})
                elif str(exact_row.get("market_type") or "").upper() != expected_type:
                    row.update({"status": "CANNOT_CONFIRM", "reason": "Exact-date panel market_type does not match the archived listing market."})
                elif not _positive_finite_number(exact_row.get("close")) or not _positive_finite_number(exact_row.get("pre_close")):
                    row.update({"status": "CANNOT_CONFIRM", "reason": "Exact-date panel close/pre_close is missing or invalid."})
                elif _is_missing_number(exact_row.get("pct_chg")):
                    row.update({"status": "CANNOT_CONFIRM", "reason": "Exact-date panel pct_chg is missing or invalid."})
                else:
                    close = float(exact_row["close"])
                    pre_close = float(exact_row["pre_close"])
                    calculated = (close / pre_close - 1.0) * 100.0
                    reported = float(exact_row["pct_chg"])
                    if not math.isclose(calculated, reported, rel_tol=1e-6, abs_tol=1e-4):
                        row.update({"status": "CANNOT_CONFIRM", "reason": "Panel pct_chg does not reconcile with exact-date close/pre_close."})
                    else:
                        row.update({
                            "status": "OBSERVED_EXACT_PANEL_CLOSE_TO_PRE_CLOSE",
                            "close": close,
                            "pre_close": pre_close,
                            "pct_chg_close": round(calculated, 6),
                            "panel_pct_chg": reported,
                            "source_receipt_status": a_probe["receipt_status"],
                            "source_receipt_coverage_rate": a_probe["receipt_coverage_rate"],
                            "source_sync_authority_status": a_probe["sync_authority_status"],
                            "reason": a_probe["reason"],
                        })
            except (OSError, PerformanceAppendixError, ImportError, ValueError, RuntimeError) as exc:
                row.update({"status": "CANNOT_CONFIRM", "reason": f"{type(exc).__name__}: {exc}"})
        else:
            row["source"] = "V35_CONFIGURED_HK_ASSET_PANEL"
            prior_session = _previous_market_session(calendar, "hk_securities", observation_date)
            row["prior_session_date"] = prior_session or None
            if not prior_session:
                row.update({"status": "CANNOT_CONFIRM", "reason": "The market calendar could not identify the previous HK session."})
            else:
                try:
                    if "_hk_panel_cache" not in locals():
                        try:
                            _hk_probe, hk_rows, hk_current_prev_rows, hk_prior_rows = _build_hk_panel_probe(
                                runtime, observation_date, prior_session, calendar_status
                            )
                        except (OSError, PerformanceAppendixError, ImportError, ValueError, RuntimeError, KeyError, TypeError) as exc:
                            _hk_probe, hk_rows, hk_current_prev_rows, hk_prior_rows = ({
                                "status": "CANNOT_CONFIRM", "binding_status": "CANNOT_CONFIRM",
                                "reason": f"{type(exc).__name__}: {exc}",
                            }, {}, {}, {})
                        _hk_panel_cache = (_hk_probe, hk_rows, hk_current_prev_rows, hk_prior_rows)
                    else:
                        _hk_probe, hk_rows, hk_current_prev_rows, hk_prior_rows = _hk_panel_cache
                    if _hk_probe.get("current_receipt_path"):
                        row["source_receipt_path"] = _hk_probe["current_receipt_path"]
                    if _hk_probe.get("current_receipt_sha256"):
                        row["source_receipt_sha256"] = _hk_probe["current_receipt_sha256"]
                    if _hk_probe.get("current_manifest_sha256"):
                        row["source_manifest_sha256"] = _hk_probe["current_manifest_sha256"]
                    if _hk_probe.get("current_panel_sha256"):
                        row["source_sha256"] = _hk_probe["current_panel_sha256"]
                    code_norm = "HK." + source["code"].split(".", 1)[0]
                    current_row = hk_rows.get(code_norm)
                    current_previous_row = hk_current_prev_rows.get(code_norm)
                    prior_row = hk_prior_rows.get(code_norm)
                    if current_row is None or current_previous_row is None or prior_row is None:
                        row.update({"status": "CANNOT_CONFIRM", "reason": _hk_probe.get("reason") or "The configured HK panel chain lacks a unique current and prior-session row for this listing."})
                    else:
                        raw_prices = (current_row.get("close"), current_row.get("pre_close"),
                                      prior_row.get("close"), current_previous_row.get("close"))
                        if not all(_positive_finite_number(value) for value in raw_prices):
                            raise PerformanceAppendixError("HK panel close or prior-session close is missing or invalid.")
                        close, panel_pre_close, prior_close, current_panel_prior_close = map(float, raw_prices)
                        reported = float(current_row["pct_chg"])
                        calculated = (close / prior_close - 1.0) * 100.0
                        if not (math.isfinite(calculated) and math.isfinite(reported)
                                and math.isclose(prior_close, current_panel_prior_close, rel_tol=1e-7, abs_tol=1e-5)
                                and math.isclose(prior_close, panel_pre_close, rel_tol=1e-7, abs_tol=1e-5)
                                and math.isclose(calculated, reported, rel_tol=1e-6, abs_tol=1e-4)):
                            row.update({"status": "CANNOT_CONFIRM", "reason": "HK current pre_close, parent-panel prior close, and pct_chg do not reconcile."})
                        else:
                            native_price = _hk_probe.get("native_price_transform")
                            row.update({
                                "status": "OBSERVED_RAW_CLOSE_TO_PRIOR_SESSION_CLOSE",
                                "close": close,
                                "pre_close": None,
                                "panel_pre_close_crosscheck": panel_pre_close,
                                "prior_session_close": prior_close,
                                "pct_chg_close": round(calculated, 6),
                                "panel_pct_chg": reported,
                                "source_receipt_status": _hk_probe["current_receipt_status"],
                                "source_previous_receipt_status": _hk_probe["previous_receipt_status"],
                                "native_price_transform": native_price,
                                "corporate_action_adjustment_status": "NOT_VERIFIED",
                                "includes_dividends": False,
                                "reason": (
                                    "Raw close-price change only; no verified corporate-action/adjustment factor or dividend total return. "
                                    "Current panel pre_close was checked against the previous session close in both linked panels."
                                ),
                            })
                except (OSError, PerformanceAppendixError, ImportError, ValueError, RuntimeError, KeyError, TypeError) as exc:
                    row.update({"status": "CANNOT_CONFIRM", "reason": f"{type(exc).__name__}: {exc}"})
        all_rows.append(row)
        by_market[market].append(row)

    a_probe = _a_panel_cache[0] if "_a_panel_cache" in locals() else {
        "status": "CANNOT_CONFIRM", "binding_status": "CANNOT_CONFIRM",
        "reason": runtime_error or "No valid exact-date A/BJ panel binding was available.",
    }
    hk_probe = _hk_panel_cache[0] if "_hk_panel_cache" in locals() else {
        "status": "CANNOT_CONFIRM", "binding_status": "CANNOT_CONFIRM",
        "reason": runtime_error or "No valid exact-date HK receipt/asset panel chain was available.",
    }
    market_probes = {"A": a_probe, "BJ": a_probe, "HK": hk_probe}
    market_summaries = {market: _count_market_rows(all_rows, market, market_probes[market])
                        for market in ("A", "BJ", "HK")}
    observed_total = sum(item["observed_listings"] for item in market_summaries.values())
    overall_status = ("OBSERVED_ALL_ARCHIVED_LISTINGS" if all_rows and observed_total == len(all_rows)
                      else ("PARTIAL_DATA" if observed_total else "CANNOT_CONFIRM"))
    return {
        "schema_version": "wechat-prior-mentions-performance-v2",
        "status": overall_status,
        "created_at": datetime.now().astimezone().isoformat(),
        "source_article": {
            "article_url": article["article_url"],
            "article_title": article["article_title"],
            "article_date": article["article_date"],
            "published_at": article["published_at"],
            "article_relation_to_observation": article_relation,
            "calendar_days_before_observation": date_gap,
            "package_id": article["package_id"],
            "input_digest": article["input_digest"],
            "trusted_package_sha256": article["package_sha256"],
            "frozen_manifest_sha256": article["manifest_sha256"],
            "import_receipt_sha256": article["receipt_sha256"],
            "summary_sha256": article["summary_sha256"],
            "mentions_csv_sha256": article["mentions_sha256"],
            "archive_structure_status": article["receipt"].get("status"),
            "chat_report_status": article["chat_report_status"],
            "chat_claimed_complete": article["chat_claimed_complete"],
            "mentions_scope": "Every unique market-qualified listing code present in the archived mentions.csv; semantic completeness remains separate.",
        },
        "current_package_binding": current_package,
        "observation": {
            "date": observation_date,
            "mode": "CLOSE_TO_CLOSE",
            "calendar_timezone": calendar.get("timezone"),
            "calendar_path": str(calendar_path),
            "calendar_sha256": calendar_sha,
            "market_sessions": calendar_status,
            "previous_hk_session_date": _previous_market_session(calendar, "hk_securities", observation_date),
        },
        "metric_contract": {
            "a_bj_close_to_close": "(close / pre_close - 1) * 100; exact-date close and pre_close are checked against panel pct_chg.",
            "hk_raw_close_to_previous_session_close": "(current close / previous HK session close - 1) * 100; the previous-session denominator is checked against current-panel pre_close and the parent panel.",
            "intraday_asof": "(last_price_asof / pre_close - 1) * 100; must include an exact timezone-aware as_of and source; not used here.",
            "universe": "Deduplicate by (market, listing code); include every unique listing in the archived mentions.csv.",
            "hk_adjustment": "HK values are raw unadjusted close-price movement, do not include dividends, and corporate-action adjustment is not verified.",
            "interpretation": "Descriptive single-session price change only; not a strategy, portfolio, recommendation, or trading return.",
        },
        "runtime_configuration": runtime or {
            "status": "CANNOT_CONFIRM",
            "error": runtime_error or "No loaded scheduler runtime evidence was provided.",
        },
        "source_data_probe": {"markets": market_probes},
        "mention_rows": article["mention_rows"],
        "unique_listings": len(all_rows),
        "market_summary": market_summaries,
        "rows": all_rows,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def render_prior_mentions_performance_appendix(result: dict) -> str:
    source = result["source_article"]
    observation = result["observation"]
    current_package = result["current_package_binding"]
    runtime = result.get("runtime_configuration", {})
    a_probe = result["source_data_probe"]["markets"]["A"]
    hk_probe = result["source_data_probe"]["markets"]["HK"]
    if a_probe.get("receipt_target_date_file_count") is not None:
        a_coverage = a_probe.get("receipt_coverage_rate")
        a_coverage_text = f"{float(a_coverage):.6f}" if _positive_finite_number(a_coverage) or a_coverage == 0 else "CANNOT_CONFIRM"
        a_binding_note = (
            "面板与receipt绑定失败，所有A/BJ行情均CANNOT_CONFIRM。"
            if a_probe.get("binding_status") != "BOUND" else
            "只使用唯一exact-date行并逐行复算。"
        )
        a_disclosure = (
            f"receipt {a_probe.get('receipt_path', 'CANNOT_CONFIRM')} SHA-256 {a_probe.get('receipt_sha256', 'CANNOT_CONFIRM')} "
            f"状态 {a_probe.get('receipt_status', 'CANNOT_CONFIRM')}；target_date_file_count "
            f"{a_probe.get('receipt_target_date_file_count')}/{a_probe.get('receipt_target_count')} "
            f"(coverage_rate={a_coverage_text})；receipt row_count {a_probe.get('receipt_row_count', 'CANNOT_CONFIRM')}；"
            f"sync authority {a_probe.get('sync_authority_status', 'CANNOT_CONFIRM')}；binding {a_probe.get('binding_status', 'CANNOT_CONFIRM')}。"
            f"{a_probe.get('receipt_target_date_file_count')}/{a_probe.get('receipt_target_count')}是面板覆盖统计，"
            f"不是{result.get('unique_listings', 'CANNOT_CONFIRM')}只代码的匹配率。{a_binding_note}"
        )
    else:
        a_disclosure = (
            f"运行配置 evidence {runtime.get('evidence_path', 'CANNOT_CONFIRM')}；selector pointer "
            f"{a_probe.get('selector_pointer_path', 'CANNOT_CONFIRM')}；receipt "
            f"{a_probe.get('receipt_path', 'CANNOT_CONFIRM')} SHA-256 {a_probe.get('receipt_sha256', 'CANNOT_CONFIRM')}；"
            f"状态 {a_probe.get('receipt_status', a_probe.get('status'))}；binding {a_probe.get('binding_status', 'CANNOT_CONFIRM')}；"
            f"{a_probe.get('reason', 'A/BJ receipt coverage is not available.')}"
        )
    hk_missing_prior = (
        f"；前一交易日回执 {hk_probe.get('missing_previous_receipt_date')} "
        f"{hk_probe.get('missing_previous_receipt_path')} 状态 {hk_probe.get('previous_receipt_status')}"
        if hk_probe.get('missing_previous_receipt_date') else ""
    )
    lines = [
        f"### 前篇公众号提及股票的今日表现（观察附录；前篇文章日 {source['article_date']}；观察日 {observation['date']}）",
        "",
        f"- 状态：{result['status']}；A/BJ日历 {observation['market_sessions']['A']}；HK日历 {observation['market_sessions']['HK']}；HK前一交易日 {observation.get('previous_hk_session_date') or 'CANNOT_CONFIRM'}。",
        f"- 前篇来源：{source['article_title']}；真实发布时间 {source['published_at']}；文章日 {source['article_date']}；与观察日关系 {source['article_relation_to_observation']}。",
        f"- 前篇输入绑定：package {source['package_id']}；input_digest {source['input_digest']}；可信ZIP SHA-256 {source['trusted_package_sha256']}；mentions.csv SHA-256 {source['mentions_csv_sha256']}。",
        f"- 本篇外部绑定：package {current_package['package_id']}；input_digest {current_package['input_digest']}；PACKAGE_RECEIPT SHA-256 {current_package['receipt_sha256']}；ZIP SHA-256 {current_package['zip_sha256_declared']}。",
        f"- 前篇归档 mentions.csv 含 {result['mention_rows']} 行，按市场和上市代码去重为 {result['unique_listings']} 只：A {result['market_summary']['A']['mentioned_listings']}、BJ {result['market_summary']['BJ']['mentioned_listings']}、HK {result['market_summary']['HK']['mentioned_listings']}。Chat completeness={str(source['chat_claimed_complete']).lower()}，summary 状态 {source['chat_report_status']}；本表只覆盖归档中的代码，不能证明全文语义完整。",
        "- 口径：A/BJ按已配置精确日期面板的 (close / pre_close - 1) × 100%，并核对面板 pct_chg；HK用当前收盘除以前一港股交易日收盘再减一，并核对当前 pre_close、父面板前收和面板 pct_chg。盘中值必须有精确时区化 as_of 和来源；本次未使用盘中值。",
        "- HK特别说明：只表示原始、未复权收盘价变化，不含分红；公司行动和复权因子未获验证，且提供方未证明该日最终性。因此不称为官方日涨幅或总回报。",
        "- 解释边界：这是全部归档上市代码的单日描述性价格变化，不是策略或组合收益、推荐或 BUY 信号；不按涨跌筛选，不用缺值填0。",
        "",
        "### 按市场覆盖",
        "",
        "| 市场 | 归档代码数 | 有观察值 | 覆盖率 | 状态 |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    for market, label in (("A", "A股"), ("BJ", "北交所"), ("HK", "港股")):
        summary = result["market_summary"][market]
        coverage = f"{summary['coverage_pct']}%" if summary["coverage_pct"] is not None else "—"
        lines.append(
            f"| {label} | {summary['mentioned_listings']} | {summary['observed_listings']} | {coverage} | {summary['status']} |"
        )
    lines.extend([
        "",
        "数据来源与缺口说明：",
        f"- A/BJ：{a_disclosure}",
        f"- HK：当前receipt {hk_probe.get('current_receipt_path', 'CANNOT_CONFIRM')} SHA-256 {hk_probe.get('current_receipt_sha256', 'CANNOT_CONFIRM')}；状态 {hk_probe.get('current_receipt_status', hk_probe.get('status'))}；当前面板 SHA {hk_probe.get('current_panel_sha256', 'CANNOT_CONFIRM')}；前序面板 SHA {hk_probe.get('previous_panel_sha256', 'CANNOT_CONFIRM')}；父面板 SHA 链匹配 {hk_probe.get('parent_panel_sha256_matches', False)}；binding {hk_probe.get('binding_status', 'CANNOT_CONFIRM')}；公司行动/复权核验 {hk_probe.get('corporate_action_adjustment_status', 'NOT_VERIFIED')}{hk_missing_prior}。",
        "",
        "### 全部归档上市代码",
        "",
        "| 市场 | 代码 | 名称 | 提及行 | 前一基准价 | 观察日收盘 | 价格变动% | 状态或缺口 |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | --- |",
    ])
    for row in result["rows"]:
        close = f"{row['close']:.4f}" if row.get("close") is not None else "—"
        prior_value = row.get("prior_session_close") if row["market"] == "HK" else row.get("pre_close")
        prior_price = f"{prior_value:.4f}" if prior_value is not None else "—"
        pct = f"{row['pct_chg_close']:+.2f}" if row["pct_chg_close"] is not None else "—"
        state = row["status"]
        if row["status"] == "CANNOT_CONFIRM" or row["status"] == "NO_TRADING_SESSION":
            if row.get("reason"):
                state += ": " + row["reason"].replace("|", "/")
        elif row.get("reason") and row["market"] == "HK":
            state += ": raw unadjusted price movement; adjustment not verified"
        lines.append(
            f"| {row['market']} | {row['code']} | {row['name']} | {row['mention_rows']} | {prior_price} | {close} | {pct} | {state} |"
        )
    lines.extend([
        "",
        f"市场日历 SHA-256：{observation['calendar_sha256']}。运行指针发现文件 SHA-256：{runtime.get('evidence_sha256', 'CANNOT_CONFIRM')}。完整逐行值、路径及校验状态见同身份绑定的 JSON 附录。",
        "没有有效价格观察不表示0%收益；失败绑定的行情字段保持null。",
        "",
        "RESEARCH_ONLY / WATCH_ONLY / NO_BUY_GATE；production_allowed=false、buy_gate_updated=false、orders_sent=false。",
    ])
    return "\n".join(lines) + "\n"


def _write_immutable_version(out_dir: Path, name: str, payload: bytes) -> tuple[str, str]:
    # Reuse the existing create-only publisher: no following dangling symlinks,
    # no truncation of old versions, and no check-then-write overwrite race.
    from wechat_chat_handoff import HandoffError, _write_if_same
    if Path(name).name != name or name in ("", ".", ".."):
        raise PerformanceAppendixError("output name must be an immediate filename")
    digest = _sha256_bytes(payload)
    path = out_dir / name
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file():
            raise PerformanceAppendixError(f"output path is not a regular file: {path}")
        if _sha256_bytes(path.read_bytes()) != digest:
            path = out_dir / f"{Path(name).stem}.{digest[:12]}{Path(name).suffix}"
    try:
        _write_if_same(path, payload, label="immutable performance appendix")
    except (HandoffError, OSError, ValueError) as exc:
        raise PerformanceAppendixError(str(exc)) from exc
    return path.name, digest


def _run_appendix_cli(argv: list[str]) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="按可信归档和当前 scheduler 配置生成前篇公众号逐股表现附录")
    parser.add_argument("--prior-article-dir", required=True, help="已有 articles/<article>/ 归档目录")
    parser.add_argument("--current-package-receipt", required=True, help="本篇 PACKAGE_RECEIPT.json，用于附录外部身份绑定")
    parser.add_argument("--obs-date", required=True, help="YYYYMMDD；由调用方按真实市场日历确定")
    parser.add_argument("--runtime-config-evidence", required=True, help="launchctl 当前已加载 scheduler 环境的只读发现回执")
    parser.add_argument("--calendar-json", required=True, help="正式市场日历合同 JSON")
    parser.add_argument("--out-dir", required=True, help="输出到本地 append-only evidence 目录")
    args = parser.parse_args(argv)
    out_dir = _checked_read_path(args.out_dir, label="appendix output directory", must_exist=False)
    out_dir.mkdir(parents=True, exist_ok=True)
    if out_dir.is_symlink():
        raise PerformanceAppendixError("appendix output directory must not be a symlink")
    result = build_prior_mentions_performance_appendix(
        prior_article_dir=args.prior_article_dir,
        current_package_receipt=args.current_package_receipt,
        observation_date=args.obs_date,
        runtime_config_evidence=args.runtime_config_evidence,
        calendar_json=args.calendar_json,
    )
    markdown = render_prior_mentions_performance_appendix(result)
    json_bytes = (json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    markdown_bytes = markdown.encode("utf-8")
    json_name, json_sha = _write_immutable_version(out_dir, "performance_appendix.json", json_bytes)
    md_name, md_sha = _write_immutable_version(out_dir, "performance_appendix.md", markdown_bytes)
    script_path = Path(__file__).resolve()
    receipt = {
        "receipt_version": "wechat-prior-mentions-performance-receipt-v1",
        "status": "GENERATED_" + result["status"],
        "appendix_json": json_name,
        "appendix_json_sha256": json_sha,
        "appendix_markdown": md_name,
        "appendix_markdown_sha256": md_sha,
        "generator_path": str(script_path),
        "generator_sha256": _sha256_bytes(script_path.read_bytes()),
        "source_package_id": result["source_article"]["package_id"],
        "source_input_digest": result["source_article"]["input_digest"],
        "source_import_receipt_sha256": result["source_article"]["import_receipt_sha256"],
        "source_mentions_csv_sha256": result["source_article"]["mentions_csv_sha256"],
        "current_package_id": result["current_package_binding"]["package_id"],
        "current_input_digest": result["current_package_binding"]["input_digest"],
        "current_package_receipt_sha256": result["current_package_binding"]["receipt_sha256"],
        "current_package_zip_sha256": result["current_package_binding"]["zip_sha256_declared"],
        "observation_date": result["observation"]["date"],
        "calendar_sha256": result["observation"]["calendar_sha256"],
        "runtime_pointer_evidence_sha256": result["runtime_configuration"].get("evidence_sha256"),
        "source_data_probe": result["source_data_probe"],
        "market_summary": result["market_summary"],
        "generated_at": result["created_at"],
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    receipt_bytes = (json.dumps(receipt, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    receipt_name, receipt_sha = _write_immutable_version(out_dir, "PERFORMANCE_APPENDIX_RECEIPT.json", receipt_bytes)
    print(json.dumps({
        "status": result["status"],
        "receipt": str(out_dir / receipt_name),
        "receipt_sha256": receipt_sha,
        "appendix_markdown": str(out_dir / md_name),
        "appendix_json": str(out_dir / json_name),
        "mentions": result["unique_listings"],
        "observed": sum(v["observed_listings"] for v in result["market_summary"].values()),
        "market_summary": result["market_summary"],
        "boundary": ["RESEARCH_ONLY", "WATCH_ONLY", "NO_BUY_GATE"],
    }, ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "appendix":
        try:
            return _run_appendix_cli(argv[1:])
        except (PerformanceAppendixError, OSError, ValueError, RuntimeError) as exc:
            print(json.dumps({"status": "ERROR", "error": str(exc)}, ensure_ascii=False))
            return 2
    if argv and argv[0] == "legacy":
        argv = argv[1:]
    return _main_legacy(argv)


def _main_legacy(argv: list[str]) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="昨日选股今日表现（本地研究面板优先）")
    parser.add_argument("--legacy-v3", action="store_true", help="显式进入旧 V3 run/pool 路线")
    parser.add_argument("--yesterday-run-dir", required=True)
    parser.add_argument("--panel", default="")
    parser.add_argument("--obs-date", default="")
    parser.add_argument("--out-dir", default="")
    args = parser.parse_args(argv)

    yesterday_run_dir = validate_run_dir(args.yesterday_run_dir)
    if not (yesterday_run_dir / "wechat_v3_preselect_manifest.json").is_file():
        print(json.dumps({"status": "ERROR", "error": f"no manifest in {yesterday_run_dir}"}, ensure_ascii=False))
        return 2

    result = build_yesterday_performance(yesterday_run_dir, args.panel or None, args.obs_date)
    out_dir = safe_run_path(
        yesterday_run_dir,
        args.out_dir if args.out_dir else "baimao_reader_out",
        label="yesterday output directory",
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    json_output = safe_run_path(out_dir, "yesterday_performance.json", label="yesterday JSON output")
    markdown_output = safe_run_path(out_dir, "yesterday_performance.md", label="yesterday markdown output")
    json_output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8-sig")
    markdown_output.write_text(
        render_yesterday_markdown(result), encoding="utf-8-sig")
    print(json.dumps({"status": result["status"], "obs_date": result.get("obs_date"),
                      "matched": result.get("matched"), "guard_pass_total": result.get("guard_pass_total")},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
