"""Isolated r21 read contracts for the frozen 18874 front end."""
from datetime import date
from hashlib import sha256
import json
import re

from starlette.responses import JSONResponse

SAFETY = {"RESEARCH_ONLY": True, "production_allowed": False, "buy_gate_updated": False,
          "orders_sent": False}
SOP_PATH = "/Users/lexi/Desktop/学习/因子工厂/research/a_share_local_panel_completion_20261024/SOP_SINGLE_STOCK_REPAIR.md"
SOP_SHA = "5fe78a058bbb227fba6c12ee9300034c51da6746deaced291369f0911039132c"
SOP_ROUTE = "/api/v4/research/single-stock-repair-sop"
TOP200_ROUTE = "/api/v4/research/a-share/top200-hit"
TOP200_SOURCES = {
    "20261126": "8be22d4310a2ea837ed93ed6fef688d0aa95df0861c8e526037a428f0dfe5ead",
    "20261127": "f812420349e8a34bee80ed1ab859611684b6a7fa2a30c49475a31a0760f3c6c7",
}
STAGES = (
    "STAGE_0925", "STAGE_0930_0935", "STAGE_0935_0940", "STAGE_0940_0945",
    "STAGE_0945_1030", "STAGE_1300_1315", "STAGE_1445_1500",
)
MANAGER = "/api/v4/manager-workbench"
MANAGER_DAY = re.compile(
    MANAGER + r"/days/(?P<day>[0-9]{8})(?:/recommendations/(?P<lane>US_MAPPING|OVERSOLD))?"
)
MANAGER_MISSING = {
    MANAGER + "/announcement-flash": "隔离端未绑定可核验的公告研究任务",
    MANAGER + "/mapping-catalog": "隔离端未绑定可核验的美股映射资料库",
    MANAGER + "/history": "隔离端未绑定所选目标日经理计划版本档案",
}
MANAGER_SCOPED_MISSING = re.compile(
    MANAGER + r"/(?:stocks/HK\.[0-9]{5}|reviews/[0-9]{8}|runs/[A-Za-z0-9_.:-]{1,180})"
)
MANAGER_LANES = {"US_MAPPING": "美股映射", "OVERSOLD": "超跌"}


def _exact_date(value):
    if not re.fullmatch(r"[0-9]{8}|[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _read_bound(path, digest, limit):
    if path.resolve(strict=True) != path or not path.is_file() or path.stat().st_size > limit:
        raise ValueError("R21_SOURCE_NOT_BOUND")
    raw = path.read_bytes()
    if len(raw) > limit or sha256(raw).hexdigest() != digest:
        raise ValueError("R21_SOURCE_HASH_MISMATCH")
    return raw


def _manager_missing(reason, data=None):
    return {"schema_version": "v4.manager_workbench.v1", "state": "CANNOT_CONFIRM",
            "data": data, "gaps": [reason], **SAFETY}


def manager_payload(path, query):
    match = MANAGER_DAY.fullmatch(path)
    if match:
        if _exact_date(match["day"]) is None:
            return None
        lane = MANAGER_LANES.get(match["lane"], "经理计划")
        return _manager_missing(
            f'{match["day"]} · 隔离端未绑定可核验的{lane}保存版本',
            {"snapshot": None, "stocks": [], "counts": None, "pagination": None},
        )
    if path in MANAGER_MISSING:
        data = None
        if path.endswith("/history") and len(requested := query.get("date", [])) == 1:
            data = {"date": requested[0], "versions": []}
        return _manager_missing(MANAGER_MISSING[path], data)
    if MANAGER_SCOPED_MISSING.fullmatch(path):
        return _manager_missing("隔离端未绑定对应保存版本或明细")
    return None


def _pct(number, total):
    return 100 * number / total if number is not None and total else None


def _pool_evidence(bound, requested, top_codes):
    expected = {
        "a_d1_premarket_pool", "a_d1_fupan_watchlist_pool", "a_d1_stage7_fenshi_review_pool",
        "a_share_research_recommendation_pool", "a_share_baimao_research_map",
        "wechat_public_account_v3_preselect",
    }
    proof = bound.proof.get(requested)
    if proof is None:
        return {"pool_count": len(expected), "missing_pool_ids": sorted(expected)}, {}
    try:
        archived = bound.page(requested, proof["count"], 0, 1)
    except (ValueError, KeyError):
        return {"pool_count": len(expected), "missing_pool_ids": sorted(expected)}, {}
    available = {}
    summaries = []
    for item in archived["pools"]:
        key = item["pool_id"]
        if key not in expected:
            continue
        symbols = {
            row["canonical_symbol"] for row in item["rows"]
            if row.get("market") == "A" and re.fullmatch(r"[0-9]{6}\.(SH|SZ|BJ)", row["canonical_symbol"])
        }
        if symbols:
            available[key] = symbols
        hits = len(symbols & top_codes) if symbols else None
        summaries.append({
            "pool_id": key, "status": item["status"], "materialized": bool(symbols),
            "partial": bool(symbols) and bool(item["cannot_confirm"]), "selected_count": len(symbols) or None,
            "hit_count": hits, "top200_coverage_pct": _pct(hits, len(top_codes)),
            "selection_hit_rate_pct": _pct(hits, len(symbols)), "source_sha256": item["source_sha256"],
        })
    union = set().union(*available.values())
    hit_count = len(union & top_codes) if available else None
    return {
        "status": "PARTIAL_POOL_COVERAGE", "selected_count": len(union) or None, "hit_count": hit_count,
        "top200_coverage_pct": _pct(hit_count, len(top_codes)),
        "selection_hit_rate_pct": _pct(hit_count, len(union)),
        "materialized_pool_count": len(available), "pool_count": len(expected),
        "missing_pool_ids": sorted(expected - available.keys()),
        "partial_pool_ids": [item["pool_id"] for item in summaries if item["partial"]],
        "source_manifest_sha256": archived["source_manifest_sha256"], "pools": summaries,
    }, available


class SevenP0Reads:
    def __init__(self, store, data, preselection):
        self.store = store
        self.root = data.parent.parent
        self.preselection = preselection

    def sop(self):
        path = self.root / "content_projection" / "p0_single_stock_repair.md"
        payload = {
            "schema_version": "v4.research.single_stock_repair_sop.v1",
            "status": "CANNOT_CONFIRM", "content": None, "source": {"path": SOP_PATH, "sha256": None},
            "cannot_confirm": ["SOP_SOURCE_READ_OR_BINDING_FAILED"], "write_policy": "read_only", **SAFETY,
        }
        try:
            raw = _read_bound(path, SOP_SHA, 256 * 1024)
            content = raw.decode("utf-8")
        except (OSError, ValueError):
            return payload
        return {**payload, "status": "READY", "content": content,
                "content_type": "text/markdown; charset=utf-8", "cannot_confirm": [],
                "source": {"path": SOP_PATH, "sha256": SOP_SHA, "size_bytes": len(raw)}}

    def top200(self, requested):
        selected = _exact_date(requested)
        if selected is None:
            return None
        iso = selected.isoformat()
        compact = iso.replace("-", "")
        payload = {
            "schema_version": "v4.research.a_share_pool_top200.v1", "requested_date": requested,
            "status": "NOT_MATERIALIZED", "selected_source_status": "NOT_MATERIALIZED",
            "date": requested, "dates": [], "top200": [], "rows": [], "safety_flags": SAFETY, **SAFETY,
        }
        expected = TOP200_SOURCES.get(compact)
        if expected is None:
            return payload if requested == compact else None
        path = self.root / "daily_e2e_20261127" / f"R21_D{iso[-2:]}_TOP200_VERIFIED.json"
        try:
            source = json.loads(_read_bound(path, expected, 512 * 1024))
            rows = self.store.get_top200(iso)
            current_receipt = (
                source.get("schema") == "R21_EXACT_DAY_ACCEPTED_UNIVERSE_TOP200_V1"
                and source.get("natural_verified") is False
            )
            prior_receipt = (
                compact == "20261126" and source.get("schema") is None
                and source.get("execution") == "READBACK_R17_ISOLATED_SEALED_EXACT_DAY"
                and source.get("source_status") == "PARTIAL"
            )
            if (
                not (current_receipt or prior_receipt)
                or source["source_date"] != iso or source["data_date"] != compact
                or source["status"] != "PARTIAL_DESCRIPTIVE"
                or source["canonical_daily_product"] is not False or source["historical_PIT"] is not False
                or any(source.get(key) is not value for key, value in SAFETY.items())
                or source["top200"] != rows or len(rows) != source["count"] or not rows
            ):
                raise ValueError("R21_TOP200_IDENTITY_CONFLICT")
        except (OSError, ValueError, KeyError):
            return {**payload, "status": "CANNOT_CONFIRM", "selected_source_status": "CANNOT_CONFIRM"}
        pool_summary, pools = _pool_evidence(self.preselection, compact, {row["symbol"] for row in rows})
        stocks = []
        for row in rows:
            hits = [key for key, members in pools.items() if row["symbol"] in members]
            stocks.append({
                "rank": row["rank"], "code": row["symbol"], "name": row["name"], "change_pct": row["pct_chg"],
                "pool_hit": bool(hits) if pools else None, "pool_memberships": hits,
                "stage_memberships": [], "stage_coverage_known": False,
            })
        entry = {
            "date": requested, "status": "PARTIAL", "a_pool": pool_summary,
            "seven_stage": {"status": "CANNOT_CONFIRM"},
            "stage_coverage": {"available": 0, "total": len(STAGES), "missing_stages": list(STAGES)},
            "top200": {"top_count": len(rows), "min_change_pct": rows[-1]["pct_chg"]},
            "stocks": stocks, "detail_status": "PARTIAL",
        }
        return {
            **payload, "status": "PARTIAL", "selected_source_status": "SAME_DAY_PARTIAL_DESCRIPTIVE",
            "dates": [entry], "latest_available_date": max(TOP200_SOURCES), "top200": rows, "rows": rows,
            "detail_projection": {"source_date": iso, "source_sha256": expected, "generation": source.get("generation"),
                                  "coverage_scope": source.get("coverage_scope"), "accepted": source.get("accepted"),
                                  "canonical_daily_product": False, "historical_PIT": False, "natural_verified": False},
        }

    def resolve(self, path, query):
        payload = None
        if path == SOP_ROUTE and not query:
            payload = self.sop()
        elif path == TOP200_ROUTE and set(query) == {"date"} and len(query["date"]) == 1:
            payload = self.top200(query["date"][0])
        elif path.startswith(MANAGER + "/"):
            payload = manager_payload(path, query)
        if payload is None:
            return None
        return JSONResponse(payload, headers={"Cache-Control": "no-store"})
