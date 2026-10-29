"""Source/config binding inside the existing A daily producer; no alternate owner."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import time
import urllib.error
import urllib.request
from zoneinfo import ZoneInfo

from ops.research_panel_factor_cache import QfqGateError, _json, _source, canonical_sha, sha

POLICY_PATH = Path(__file__).resolve().parents[1] / "contracts/a_share_daily_source_policy.json"
RESEARCH_SCHEMA = "a_share_qfq_adjustment_input_research_cache_v1"


def source_policy() -> dict:
    value = json.loads(POLICY_PATH.read_text())
    if (value.get("schema") != "a_daily_source_policy.v1" or value.get("enabled") is not True
            or value.get("source_kind") != "TDX_OFFICIAL_G4DAY"
            or value.get("earliest_slot") != "1610" or value.get("RESEARCH_ONLY") is not True
            or any(value.get(k) is not False for k in ("production_allowed", "buy_gate_updated", "orders_sent"))):
        raise QfqGateError("A_DAILY_SOURCE_POLICY_UNBOUND")
    return value


def _immutable(path: Path, value: dict) -> dict:
    if path.exists():
        if json.loads(path.read_text()) != value:
            raise QfqGateError("A_DAILY_IMMUTABLE_CONFIG_CONFLICT:" + str(path))
    else:
        _json(path, value)
    return dict(path=str(path.resolve()), sha256=sha(path))


def acquire_daily_input(target: int, receipt_root: Path, *, fetch=None, now=None, sleep=time.sleep) -> dict:
    """One dated download; verified immutable cache reuse, bounded not-ready failure."""
    policy = source_policy()
    from ops._a_share_daily_sync_parts.official_daily_package import OfficialDailyPackage, SOURCE_URL, parse_package
    from contracts.trading_calendar import load_market_calendar, previous_session, resolve_market_states, TradingDayState
    moment = now or datetime.now(timezone.utc)
    local = moment.astimezone(ZoneInfo("Asia/Shanghai"))
    if int(local.strftime("%Y%m%d")) != target or local.strftime("%H%M") < policy["earliest_slot"]:
        raise QfqGateError("OFFICIAL_DAILY_SOURCE_WAIT_WINDOW")
    calendar_ref, adapter_ref = policy["calendar"], policy["calendar_adapter"]
    calendar = load_market_calendar(_source(calendar_ref, owner="A daily calendar"))
    _source(adapter_ref, owner="A daily calendar adapter")
    if resolve_market_states(calendar, str(target))["a_share"] not in {
            TradingDayState.FULL_TRADING_DAY, TradingDayState.HALF_TRADING_DAY_AM}:
        raise QfqGateError("OFFICIAL_DAILY_TARGET_NOT_TRADING_DAY")
    previous = previous_session(calendar, str(target), market="a_share")
    root = receipt_root / "a_sync_authority/official_daily" / str(target)
    root.mkdir(parents=True, exist_ok=True)
    cached = root / "input.json"
    if cached.is_file():
        ref = dict(path=str(cached.resolve()), sha256=sha(cached))
        OfficialDailyPackage(ref, target)
        return ref
    url = SOURCE_URL.format(date=target)
    def download():
        with urllib.request.urlopen(url, timeout=30) as response:
            if response.geturl() != url:
                raise QfqGateError("OFFICIAL_DAILY_URL_REDIRECT_UNBOUND")
            return response.read(32 * 1024 * 1024 + 1)
    for attempt in range(2):
        try:
            payload = (fetch or download)()
            parse_package(payload, target)  # size/date/member/count/CRC/finite checks
            break
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if isinstance(exc, urllib.error.HTTPError):
                exc.close()
            if attempt:
                _json(root / "WAIT.json", dict(status="SOURCE_NOT_READY", target_date=target,
                      source_url=url, error_type=type(exc).__name__, attempts=2,
                      RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False))
                raise QfqGateError("OFFICIAL_DAILY_SOURCE_NOT_READY") from exc
            sleep(2)
    package = root / "packages" / (canonical_sha(dict(url=url, target=target)) + ".zip")
    package.parent.mkdir(exist_ok=True)
    # Atomic immutable source bytes; never a .day or default panel write.
    from ops.research_panel_tdx_adjustment_inputs import _save_bytes
    _save_bytes(package, payload)
    descriptor = dict(schema_version="a_sync_official_daily_input.v1", source_kind="TDX_OFFICIAL_G4DAY",
        target_date=target, source_url=url, previous_session=previous,
        package=dict(path=str(package.resolve()), sha256=sha(package)), calendar=calendar_ref,
        calendar_adapter=adapter_ref)
    ref = _immutable(cached, descriptor)
    OfficialDailyPackage(ref, target)
    return ref


def _identity(codes: list[str], date: int) -> dict:
    return dict(asof_date=date, identity_scope="Original literal provider code/market membership only; no independent permanent-issuer certification",
        symbols={c: dict(code=c, market=c[-2:], provider_request_code=c[-2:] + "." + c[:6]) for c in sorted(codes)})


def _detector(root: Path, target: int, *, current: bool) -> dict:
    from ops.research_panel_tdx_adjustment_inputs import build_fallback, _capture_coverage_end
    existing = list((root / "official_gbbq/capture_receipts").glob("*.json"))
    if current and not any(_capture_coverage_end(json.loads(p.read_text())) == target for p in existing):
        # The existing official metadata owner refreshes/parses its own source.
        build_fallback(root, {}, target, refresh_stale_capture=True)
    source = json.loads((root / "qfq_tdx_official_source.json").read_text())
    candidates = []
    for path in (root / "official_gbbq/capture_receipts").glob("*.json"):
        capture = json.loads(path.read_text())
        if _capture_coverage_end(capture) == target:
            candidates.append((capture["observed_at"], path, capture))
    if not candidates:
        raise QfqGateError("CACHE_EVENT_CAPTURE_FOR_TARGET_MISSING:" + str(target))
    _, path, capture = max(candidates, key=lambda x: x[0])
    cache_id = canonical_sha(dict(raw=capture["raw"], parser=capture["parser"], policy=source["category_policy_receipt"]))
    parsed = root / "official_gbbq" / (cache_id + ".parquet")
    receipt = parsed.with_suffix(".receipt.json")
    return dict(capture=dict(path=str(path), sha256=sha(path)), raw=capture["raw"], archive=capture["archive"],
        parser=capture["parser"], category_policy=source["category_policy_receipt"],
        derived_parquet=dict(path=str(parsed), sha256=sha(parsed)),
        derived_receipt=dict(path=str(receipt), sha256=sha(receipt)),
        observed_at=capture["observed_at"], coverage_end_date=target)


def build_cache_configuration(*, data_root: Path, tdx_root: Path, target: int, codes: list[str]) -> dict:
    """Bind actual same-date sync, one previous complete proof and original captures."""
    policy = source_policy()
    from ops.research_panel_qfq import input_path
    from ops.research_panel_factor_cache import _sync_prequery_rows, _verified_sop_skip
    root = input_path(data_root).parent
    config_root = root / "daily_source_bindings" / str(target)
    sync_path = tdx_root.parent / "receipts/a_sync_authority" / str(target) / "summary.json"
    sync = json.loads(sync_path.read_text())
    sync_ref = dict(path=str(sync_path), sha256=sha(sync_path))
    sync_rows = _sync_prequery_rows(sync_ref, target)
    # The original full same-target sync membership supplies today's literal
    # identities. Older retained non-target history never invents membership.
    codes = sorted(sync_rows)
    if not codes:
        raise QfqGateError("CACHE_CURRENT_SYNC_IDENTITY_COVERAGE_MISSING")
    for code in codes:
        row = sync_rows[code]
        if row.get("lifecycle_skip") is True and _verified_sop_skip(code, row, target, sync_ref) is None:
            raise QfqGateError("SOP_REBIND_REQUIRED:" + code)
    # Freeze source proof bytes before future reruns can replace the original summary.
    pinned_sync = _immutable(config_root / "sync" / (canonical_sha(sync) + ".json"), sync)
    cache = tdx_root.parent / "adjustment_inputs/futu_rehab"
    candidates = []
    for path in (cache / "research_carry").glob("*/*.json"):
        value = json.loads(path.read_text())
        if value.get("status") == "READY_RESEARCH_CACHE" and type(value.get("asof_date")) is int and value["asof_date"] < target:
            candidates.append((value["asof_date"], path, value))
    for path in cache.glob("*/checkpoint.json"):
        value = json.loads(path.read_text())
        states = value.get("symbols", {})
        if (type(value.get("asof_date")) is int and value["asof_date"] < target
                and value.get("finished_at") and states
                and all(r.get("status") in {"OK", "EMPTY", "ERROR", "UNSUPPORTED_MARKET", "SOP_SKIPPED"}
                        for r in states.values())
                and sum(value.get("counts", {}).values()) == len(states)):
            candidates.append((value["asof_date"], path, value))
    if not candidates:
        raise QfqGateError("CACHE_PREVIOUS_COMPLETE_PROOF_MISSING")
    prior_date, prior_path, previous = max(candidates, key=lambda x: (x[0], x[2].get("schema") == "research_factor_cache_carry_forward.v1"))
    prior_ref = _immutable(config_root / "previous" / (canonical_sha(previous) + ".json"), previous)
    if previous.get("schema") == "research_factor_cache_carry_forward.v1":
        prior_config = json.loads(_source(previous["configuration"], owner="prior completed carry config").read_text())
        prior_detector = prior_config["current_detector"]
        prior_ids = prior_config["current_identities"]
    else:
        prior_detector = _detector(root, prior_date, current=False)
        prior_ids = _immutable(config_root / "identities" / (str(prior_date) + ".json"), _identity(list(previous["symbols"]), prior_date))
    ids = _immutable(config_root / "identities" / (str(target) + ".json"), _identity(codes, target))
    descriptor = _detector(root, target, current=True)
    config = dict(schema="research_factor_cache_plan.v1", target_date=target,
        previous_metadata=prior_ref, previous_identities=prior_ids, current_identities=ids,
        prior_detector=prior_detector, current_detector=descriptor, prequery_sync_ref=pinned_sync,
        observed_provider_only_exceptions=policy["observed_provider_only_exceptions"],
        provider_only_exception_scope=policy["provider_only_exception_scope"],
        source_comparison_refs=policy["source_comparison_refs"])
    # The hash path allows input changes to form a distinct proof; no existing
    # proof is overwritten or masqueraded as fresh provider observation.
    return _immutable(config_root / "configs" / (canonical_sha(config) + ".json"), config)
