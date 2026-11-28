"""Read one saved owner F10 snapshot as of the selected Shanghai observation date."""
from datetime import date, datetime, time
from hashlib import sha256
import json
from math import isfinite
from pathlib import Path
import re
from urllib.parse import parse_qs
from zoneinfo import ZoneInfo

from v4_core.decoupled.static_projection import read_member

from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from .annotated_workbench_reads import checked_json
from .seven_p0_reads import SAFETY

SNAPSHOT_SHA256 = "fa1bec3ddfcd0dd7facff0edfafa9d8e8187a75c54ac67cc8956475c1601fa3c"
SNAPSHOT = Path(__file__).resolve().parents[1] / "home/data/r21_pre_d30/f10"
ROUTE = re.compile(r"/api/v4/research/workbench/f10-reference/(?P<symbol>[0-9]{6}\.(?:SH|SZ|BJ))")
SHA = re.compile(r"[0-9a-f]{64}")
SCHEMA = "R21_WORKBENCH_F10_REFERENCE_V1"
SHANGHAI = ZoneInfo("Asia/Shanghai")
FINANCIAL_TEXT = ("report_period", "revenue_text", "net_profit_text")
FINANCIAL_NUMBER = ("holder_count", "eps", "bps", "roe_pct")
RECOVERY_ROOT = Path(__file__).resolve().parents[1] / "f10_recovery_20261128" / "evidence"
RECOVERY_INDEX_SHA256 = "8ec9e35c3a1ace94f2c739833fc4e0711a00aa7158781bdb122a63ff0f6193eb"



def iso_date(value):
    if isinstance(value, str) and re.fullmatch(r"[0-9]{8}|[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def bounded_text(value, max_length):
    return value.strip() if isinstance(value, str) and 0 < len(value.strip()) <= max_length else None


def safe(value):
    return all(value.get(key) is flag for key, flag in SAFETY.items())


def source_details(stock, cutoff, financials):
    """Use only literal source labels from the hashed owner 最新提示 text."""
    text = stock.get("source_text")
    if not isinstance(text, str) or len(text) > 64_000 or sha256(text.encode()).hexdigest() != stock.get("source_text_sha256"):
        raise ValueError("F10_SOURCE_TEXT_SHA_CONFLICT")
    result = {"main_business": None, "shareholder_record_date": None, "report_disclosure_date": None}
    if (stock.get("category") or {}).get("name") != "最新提示":
        return result
    business, holder_dates = set(), set()
    for raw in text.splitlines()[:100]:
        line = raw.strip(" ｜|\t")
        if match := re.fullmatch(r"★主营业务\s*[:：]\s*([^★｜|]{1,320})", line):
            business.add(match[1].strip())
        if match := re.match(r"★股东户数变化\s*[:：]\s*(?:截止|截至)(\d{4}-\d{2}-\d{2})[,，]\s*"
                             r"(?:公司)?股东(?:人数|数)\s*(\d{1,9})(?=[户人,，\s]|$)", line):
            reported = iso_date(match[1])
            if reported and int(match[2]) == financials.get("holder_count"):
                if reported > cutoff:
                    raise ValueError("F10_SHAREHOLDER_DATE_AFTER_CUTOFF")
                holder_dates.add(reported.isoformat())
    if len(business) == 1:
        result["main_business"] = business.pop() or None
    if len(holder_dates) == 1:
        result["shareholder_record_date"] = holder_dates.pop()
    return result


def snapshot_fields(stock, cutoff):
    financials = stock.get("financials") or {}
    projected_financials = {key: bounded_text(financials.get(key), 64) for key in FINANCIAL_TEXT}
    projected_financials.update({
        key: x if type(x := financials.get(key)) in (int, float) and isfinite(x) else None
        for key in FINANCIAL_NUMBER
    })
    projected = {}
    for key, text in (("source_updated_date", stock.get("source_updated_date")),
                      ("finance_updated_date", stock.get("finance_updated_date")),
                      ("report_period", financials.get("report_period"))):
        stamp = iso_date(text)
        if stamp and stamp > cutoff:
            raise ValueError("F10_FIELD_DATE_AFTER_CUTOFF")
        projected[key] = stamp.isoformat() if stamp else None
    projected_financials["report_period"] = projected.pop("report_period")
    industry = stock.get("industry") or {}
    code = industry.get("tdx_finance_industry_code")
    concepts = stock.get("concepts")
    return {
        **projected,
        "symbol": stock["symbol"], "name": bounded_text(stock.get("name"), 64),
        "captured_at": stock["captured_at"], "status": "OBSERVED",
        "financials": projected_financials,
        "concept_status": stock.get("concept_status") if stock.get("concept_status") == "OBSERVED" else None,
        "concepts": [{"name": name} for entry in concepts[:120]
                     if isinstance(entry, dict) and (name := bounded_text(entry.get("name"), 64))]
                    if isinstance(concepts, list) else [],
        "industry": {"name": bounded_text(industry.get("name"), 64),
                     "tdx_finance_industry_code": code if type(code) is int else None},
        "source_detail": source_details(stock, cutoff, projected_financials),
        "source_text_sha256": stock["source_text_sha256"],
        "historical_PIT": False,
    }


def captured_financial_period(stock, cutoff):
    """Find the period printed on the same raw lines as revenue and net profit."""
    finance = stock["financials"]
    periods = set()
    for field, label in (("revenue_text", "营业总收入(元)"), ("net_profit_text", "净利润(元)")):
        if not finance.get(field):
            continue
        pattern = (r"(?m)^\s*｜\s*(\d{4}-\d{2}-\d{2})[^｜\r\n]*"
                   + re.escape(label) + r"\s*[:：]\s*" + re.escape(finance[field]) + r"(?=[^\S\r\n]|｜|$)")
        dates = {iso_date(match) for match in re.findall(pattern, stock["source_text"])}
        if len(dates) != 1 or None in dates:
            return None
        periods.update(dates)
    if len(periods) != 1:
        return None
    period = periods.pop()
    if period > cutoff:
        raise ValueError("F10_STATEMENT_PERIOD_AFTER_CUTOFF")
    return period.isoformat()


def bounded_recovery(root, symbol, cutoff):
    index_path = root / "index.json"
    index = checked_json(index_path, RECOVERY_INDEX_SHA256, 8192)
    if index.get("schema") != "v4.r21.bounded_f10_index.v1" or not (day := iso_date(index.get("captured_on"))):
        raise ValueError("F10_RECOVERY_INDEX_CONFLICT")
    if day > cutoff.date():
        return None

    receipt_path = root / "capture_receipt.json"
    checkpoint_path = root / "scope_checkpoint.json"
    receipt = checked_json(receipt_path, index["receipt_sha256"], 16384)
    checkpoint = checked_json(checkpoint_path, index["checkpoint_sha256"], 16384)
    if (receipt.get("schema") != "v4.r21.bounded_f10_recovery.v1" or not safe(receipt)
            or receipt.get("historical_PIT") is not False or receipt.get("captured_on") != index["captured_on"]
            or receipt.get("authoring") != "EXPLICIT_OBSERVATIONS_ONLY"
            or checkpoint.get("schema") != "v4.r21.bounded_f10_scope.v1"
            or checkpoint.get("capture_receipt_sha256") != index["receipt_sha256"]
            or any(checkpoint[key] != receipt[key] for key in
                   ("source_manifest_sha256", "source_page_sha256", "target_preselection_date", "selection_signal_date"))):
        raise ValueError("F10_RECOVERY_RECEIPT_CONFLICT")

    item = receipt["items"].get(symbol)
    if item is None or item.get("status") != "OBSERVED":
        return None
    captured_at = datetime.fromisoformat(item["captured_at"])
    if captured_at.tzinfo is None or captured_at > cutoff:
        return None
    if (captured_at.astimezone(SHANGHAI).date() != day or item.get("captured_on") != index["captured_on"]
            or checkpoint["members"].get(symbol) != item["preselection_membership"]):
        raise ValueError("F10_RECOVERY_MEMBER_SCOPE_CONFLICT")
    digest = item["sha256"]
    relative = f"stocks/{symbol}/{digest}.json"
    if not SHA.fullmatch(digest) or item["relative"] != relative:
        raise ValueError("F10_RECOVERY_STOCK_PATH_CONFLICT")
    stock_path = root / relative
    stock = checked_json(stock_path, digest, 512 * 1024)
    if (stock.get("symbol") != symbol or stock.get("exchange") != symbol[-2:] or stock.get("status") != "OBSERVED"
            or stock.get("historical_PIT") is not False or not safe(stock) or stock.get("captured_at") != item["captured_at"]):
        raise ValueError("F10_RECOVERY_STOCK_CONFLICT")
    projected = snapshot_fields(stock, day)
    # The latest numeric column can represent a separate indicator observation
    # (e.g. 11/19), while turnover and profit explicitly describe 09/30.
    projected["financials"]["indicator_reference_period"] = projected["financials"]["report_period"]
    projected["financials"]["report_period"] = captured_financial_period(stock, day)
    return captured_at, {
        "receipt_source_date": day.isoformat(), "index_sha256": RECOVERY_INDEX_SHA256,
        "receipt": {"path": str(receipt_path), "sha256": index["receipt_sha256"]},
        "checkpoint": {"path": str(checkpoint_path), "sha256": index["checkpoint_sha256"]},
        "stock_ref": {"path": str(stock_path), "sha256": digest},
        "receipt_generation": index["checkpoint_sha256"], "f10": projected,
        "receipt_source_kind": "ISOLATED_NATIVE_TDX_RECOVERY",
    }


class F10ReferenceReads:
    def __init__(self, app, *, clock=None, recovery_root=RECOVERY_ROOT, snapshot=SNAPSHOT, snapshot_sha256=SNAPSHOT_SHA256):
        self.app = app
        self.snapshot = Path(snapshot)
        self.snapshot_sha256 = snapshot_sha256
        self.recovery_root = Path(recovery_root)
        self.clock = clock or (lambda: datetime.now(SHANGHAI))

    def read(self, symbol, selected):
        now = self.clock().astimezone(SHANGHAI)
        cutoff = min(now, datetime.combine(selected, time.max, SHANGHAI))
        payload = {"schema": SCHEMA, "symbol": symbol, "asof_date": selected.isoformat(),
                   "asof_cutoff": cutoff.isoformat(), "historical_PIT": False, **SAFETY}
        if selected > now.date():
            return {**payload, "status": "CANNOT_CONFIRM", "reason": "F10_ASOF_IN_FUTURE"}
        recovered = None
        try:
            recovered = bounded_recovery(self.recovery_root, symbol, cutoff)
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            # Keep existing verified owner data available if local evidence is missing or corrupt.
            pass
        try:
            manifest = read_member(self.snapshot, "manifest.json", self.snapshot_sha256, 256 * 1024)
            if manifest.get("schema") != "v4.r21.f10_projection.v1":
                raise ValueError("F10_ISOLATED_SNAPSHOT_SCHEMA")
            ref = manifest["shards"].get(symbol[:4])
            saved = read_member(self.snapshot, ref["file"], ref["sha256"], 5 * 1024 * 1024) if ref else {}
            record = saved.get(symbol, {})
            date_bound = selected.strftime("%Y%m%d")
            conflicting = any(item <= date_bound for item in
                              (*manifest["global_conflict_dates"], *record.get("conflict_dates", ())))
            observations, failures = [], []
            if recovered is not None:
                observations.append(recovered)
            for stamp, day, value in record.get("rows", ()):
                observed_at = datetime.fromisoformat(stamp)
                if day <= date_bound and observed_at <= cutoff:
                    (failures if "failure" in value else observations).append((observed_at, value))
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            if recovered is not None:
                return {**payload, **recovered[1], "status": "OBSERVED", "owner_receipt_search_status": "PARTIAL"}
            return {**payload, "status": "CANNOT_CONFIRM", "reason": "F10_OWNER_INDEX_UNAVAILABLE"}
        if not observations:
            recorded = {}
            if failures:
                _, latest = max(failures, key=lambda item: item[0])
                recorded = {"verified_failed_attempts": len(failures), "latest_failure": latest["failure"]}
            reason = ("F10_OWNER_RECEIPT_GAP" if conflicting else
                      "F10_PRIOR_ATTEMPTS_FAILED" if recorded else "F10_SAVED_SNAPSHOT_NOT_FOUND")
            return {**payload, **recorded, "status": "CANNOT_CONFIRM", "reason": reason}
        _, newest = max(observations, key=lambda item: (item[0], item[1]["receipt_source_date"]))
        return {**payload, **newest, "status": "OBSERVED", "index_sha256": newest.get("index_sha256", manifest["source_index_sha256"]),
                "owner_receipt_search_status": "PARTIAL" if conflicting else "CHECKED"}

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["method"] in ("GET", "HEAD"):
            match = ROUTE.fullmatch(scope["path"])
            if match:
                params = parse_qs(scope["query_string"].decode("latin-1"), keep_blank_values=True)
                asof = params.get("asof", [])
                selected = iso_date(asof[0]) if set(params) == {"asof"} and len(asof) == 1 else None
                if selected is None or selected.isoformat() != asof[0]:
                    response = JSONResponse({"status": "CANNOT_CONFIRM", "reason": "F10_ASOF_DATE_REQUIRED", **SAFETY}, status_code=422)
                else:
                    result = await run_in_threadpool(self.read, match["symbol"], selected)
                    response = JSONResponse(result, headers={"Cache-Control": "no-store"})
                if scope["method"] == "HEAD":
                    response.body = b""
                return await response(scope, receive, send)
        return await self.app(scope, receive, send)
