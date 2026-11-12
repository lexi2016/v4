"""Quote-only adjustment metadata cache for the original daily producer.

No historical bar API, subscription, account or trade context is used here.
Immutable response bytes plus separately dated query receipts allow checkpoint
resume; successful empty responses are distinct from unsupported/error states.
"""
from __future__ import annotations

from datetime import datetime, timezone
import fcntl
import json
import math
from pathlib import Path
import struct
import time
from typing import Any, Callable
from zoneinfo import ZoneInfo

import hashlib
import os
import tempfile


class QfqGateError(RuntimeError):
    pass


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _source(ref: dict, *, owner: str) -> Path:
    path = Path(ref["path"])
    if not path.is_absolute() or not path.is_file() or sha(path) != ref["sha256"]:
        raise QfqGateError(f"SOURCE_BINDING_FAILED:{owner}:{path}")
    return path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _capture_date() -> int:
    return int(datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d"))


def _fresh(item: dict, target: int, max_age_seconds: float) -> bool:
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(item["queried_at"])).total_seconds()
        return item.get("asof_date") == target and item.get("capture_date") == _capture_date() and 0 <= age <= max_age_seconds
    except (KeyError, ValueError, TypeError):
        return False


def _records(frame: Any) -> list[dict]:
    # pandas' JSON conversion handles native dates, numpy scalars and NaN
    # without allowing nonstandard NaN bytes into the immutable input cache.
    if hasattr(frame, "to_json"):
        return json.loads(frame.to_json(orient="records", date_format="iso", double_precision=15))
    return [dict(row) for row in frame]


def _event_rows(rows: list[dict], target: int, start: int) -> list[dict]:
    events = []
    for row in rows:
        text = str(row.get("ex_div_date", ""))
        digits = "".join(c for c in text if c.isdigit())
        if len(digits) < 8:
            raise QfqGateError("FUTU_REHAB_EX_DATE_INVALID")
        date = int(digits[:8])
        if date > target or date <= start:
            continue
        try:
            a, b = float(row["forward_adj_factorA"]), float(row["forward_adj_factorB"])
            volume_a = float(row["backward_adj_factorA"])
        except (KeyError, TypeError, ValueError) as exc:
            raise QfqGateError(f"FUTU_REHAB_AFFINE_MISSING:{date}") from exc
        if not all(math.isfinite(v) for v in (a, b, volume_a)) or min(a, volume_a) <= 0:
            raise QfqGateError(f"FUTU_REHAB_AFFINE_INVALID:{date}")
        events.append(dict(ex_date=date, a=a, b=b, volume_a=volume_a))
    events.sort(key=lambda e: e["ex_date"])
    if len({e["ex_date"] for e in events}) != len(events):
        raise QfqGateError("FUTU_REHAB_DUPLICATE_EX_DATE")
    return events


# Accepted original lifecycle projection; changing it requires a new source contract.
_LIFECYCLE_ASSET_SHA = "7403a9954d9ae915dcb99cbba03a5dd19d6b85152396c5ff0634e286cdd9357b"
_LIFECYCLE_REASON = "VERIFIED_DELISTED_NO_CURRENT_BARS"
_ACCEPTED_SOP_LITERALS = frozenset({
    "PASS_SINGLE_STOCK_TARGET_WINDOW_LIFECYCLE_CLASSIFICATION",
    "PASS_SINGLE_STOCK_TARGET_WINDOW_DELISTED_CLASSIFICATION",
    "PASS_SINGLE_STOCK_TARGET_WINDOW_LIFECYCLE_CLASSIFICATION_AFTER_QUERY_FIX",
})
_CONTROLLER_FACT_SET_SHA = "910a49e7d62fa2b5ed0ef34fffcd39f50dc91eb208126359dd61ec381a3ecd1d"
_CONTROLLER_PENDING_LITERAL = "INDEPENDENT_LINEAGE_AUDIT_RELAYED_BY_CONTROLLER; FINAL_CONSUMER_REVIEW_PENDING"
_MIRROR_CAVEAT = "CONFIRMED_WITH_MIRROR_PROVENANCE_CAVEAT"
_LIFECYCLE_ASSET_PATH = Path(__file__).with_name("a_share_lifecycle_notes.json")
_CONTROLLER_ARTIFACTS = {
    "000016.SZ": "000016_cninfo_delisting_pdf",
    "688287.SH": "688287_sse_delisting",
    "832317.BJ": "832317_cninfo_issuer_pdf",
    "833874.BJ": "833874_cninfo_notice_pdf",
    "833994.BJ": "833994_cninfo_notice_pdf",
    "920680.BJ": "920680_issuer_mirror_pdf",
    "920305.BJ": "920305_issuer_mirror",
    "600193.SH": "600193_broker_notice_mirror_pdf",
}
_TWO_BROKERS_SHA = "ef8f665560db18168cd9c0f093394fc06f10503bf73260899d1b8eee7cf9cb47"


def _fixed_lifecycle_fact(code: str, fact: dict) -> bool:
    # Bind the complete original projection, including market/event identity,
    # approval references and caveats. A matching pending literal is not proof.
    asset = json.loads(_source(dict(path=str(_LIFECYCLE_ASSET_PATH), sha256=_LIFECYCLE_ASSET_SHA),
                               owner="original lifecycle projection").read_text())
    matches = [item for item in asset.get("verified_delistings", []) if item.get("ts_code") == code]
    return len(matches) == 1 and matches[0] == fact


def _controller_quarantine_fact(code: str, fact: dict, effective: str) -> bool:
    # Consume the original controller-approved non-admission fact as-is. This
    # does not turn its mirror source or pending consumer review into PASS.
    if (code not in _CONTROLLER_ARTIFACTS
            or (code != "600193.SH" and not _fixed_lifecycle_fact(code, fact))
            or fact.get("old_market_only") is not True
            or fact.get("price_chain_admitted") is not False
            or fact.get("historical_PIT") is not False
            or fact.get("accepted_review_literal") != _CONTROLLER_PENDING_LITERAL):
        return False
    if code == "600193.SH" and (fact.get("event_type") != "DELISTING" or not fact.get("source_caveat")):
        return False
    ref = fact.get("accepted_case_result_ref")
    if not isinstance(ref, dict) or ref.get("sha256") != _CONTROLLER_FACT_SET_SHA:
        return False
    approved = json.loads(_source(ref, owner="original controller-approved lifecycle fact set").read_text())
    if (approved.get("schema") != "controller_relayed_lineage_fact_set.v1"
            or approved.get("delisting_facts", {}).get(code) != effective
            or approved.get("consumer_independent_review") != "PENDING"):
        return False
    caveat = approved.get("quality_caveats", {}).get(code)
    quality = caveat or "PRIMARY_SOURCE_BYTES_CAPTURED"
    if fact.get("source_quality") != quality:
        return False
    bound = approved.get("bound_primary_artifacts", {}).get(_CONTROLLER_ARTIFACTS[code])
    refs = fact.get("issuer_or_broker_mirror_refs" if caveat else "official_source_refs")
    if not isinstance(bound, dict) or not isinstance(refs, list) or len(refs) != 1:
        return False
    ref = refs[0]
    if (not isinstance(ref, dict) or ref.get("source_quality") != quality
            or any(ref.get(k) != bound.get(k) for k in ("path", "sha256"))):
        return False
    _source(ref, owner="original controller-bound lifecycle source bytes")
    return True


def _two_brokers_quarantine_fact(code: str, fact: dict, effective: str) -> bool:
    if (code not in ("601198.SH", "601059.SH") or not _fixed_lifecycle_fact(code, fact)
            or fact.get("accepted_review_literal") != "EXISTING_ROOT_ACCEPTED_OFFICIAL_DELISTING_FACT_NO_REAUTHOR"):
        return False
    ref = fact.get("accepted_case_result_ref")
    if not isinstance(ref, dict) or ref.get("sha256") != _TWO_BROKERS_SHA:
        return False
    approved = json.loads(_source(ref, owner="original accepted two-broker facts").read_text())
    matches = [item for item in approved.get("facts", []) if item.get("ts_code") == code]
    if len(matches) != 1:
        return False
    item = matches[0]
    if (item.get("effective_delisting_date") != effective
            or item.get("status") != "OFFICIAL_DELISTING_CONFIRMED"
            or item.get("retry_policy_for_this_workflow") != "DO_NOT_FETCH_CURRENT_BARS_ON_OR_AFTER_EFFECTIVE_DATE"
            or item.get("raw_or_qfq_price_changes") is not False
            or item.get("historical_rows") != "RETAIN" or item.get("silent_code_remap") is not False):
        return False
    refs = fact.get("official_source_refs")
    expected = dict(path=item["source_path"], sha256=item["source_sha256"], url=item["source_url"])
    if refs != [expected]:
        return False
    _source(expected, owner="original accepted exchange termination bytes")
    return True


def _sync_prequery_rows(ref: dict | None, target: int) -> dict[str, dict]:
    if ref is None:
        return {}
    summary = json.loads(_source(ref, owner="original sync prequery authority").read_text())
    if (str(summary.get("target_date")) != str(target) or not summary.get("target_keys")
            or summary.get("RESEARCH_ONLY") is not True
            or any(summary.get(k) is not False for k in ("production_allowed", "buy_gate_updated", "orders_sent"))):
        raise QfqGateError("SOP_PREQUERY_SYNC_TARGET_OR_SAFETY_INVALID")
    markets = {0: "SZ", 1: "SH", 2: "BJ"}
    def identity(row):
        suffix = markets.get(row.get("market")) if type(row.get("market")) is int else None
        symbol = str(row.get("symbol", ""))
        return symbol.zfill(6) + "." + suffix if suffix and symbol.isdigit() and len(symbol) <= 6 else None
    keys = {identity(row) for row in summary["target_keys"] if isinstance(row, dict)}
    result = {}
    for row in summary.get("symbol_reconciliation", []):
        if not isinstance(row, dict):
            continue
        code = identity(row)
        if code in keys and code is not None:
            if code in result:
                raise QfqGateError("SOP_PREQUERY_DUPLICATE_IDENTITY")
            result[code] = row
    return result


def _reviewed_policy_lifecycle_fact(code: str, row: dict, fact: dict, effective: str) -> bool:
    """Consume the exact reviewed addition; legacy fixed-asset routes stay separate."""
    if (code != "301139.SZ" or effective != "20261028"
            or fact.get("last_trading_date") != "20261027"
            or fact.get("historical_PIT") is not False):
        return False
    ref = row.get("lifecycle_policy_ref")
    if (not isinstance(ref, dict) or ref != fact.get("source_policy_ref")
            or row.get("lifecycle_asset_sha256") != ref.get("sha256")):
        return False
    path = _source(ref, owner="reviewed lifecycle source policy")
    current = Path(__file__).resolve().parents[1] / "contracts/a_share_daily_source_policy.json"
    if sha(path) != sha(current):
        return False
    policy = json.loads(path.read_bytes())
    if (policy.get("schema") != "a_daily_source_policy.v1"
            or policy.get("RESEARCH_ONLY") is not True
            or any(policy.get(k) is not False for k in ("production_allowed", "buy_gate_updated", "orders_sent"))):
        return False
    original = {k: v for k, v in fact.items() if k != "source_policy_ref"}
    if policy.get("verified_delisting_additions") != [original]:
        return False
    notice = fact.get("official_notice", {})
    if (notice.get("sha256") != "8025a2df17603df345975e66d33e7c9e845d49e57ce5c7fd96cb8faa994f47dc"
            or notice.get("url") != "https://static.cninfo.com.cn/finalpage/2026-10-28/1225629444.PDF"):
        return False
    _source(notice, owner="301139 official delisting notice")
    return True


def _verified_sop_skip(code: str, row: dict | None, target: int, sync_ref: dict | None) -> dict | None:
    if not row or (row.get("classification"), row.get("quarantine"), row.get("target_date_ready"),
                   row.get("lifecycle_skip"), row.get("reason_code")) != (
                       "QUARANTINED", True, False, True, _LIFECYCLE_REASON):
        return None
    fact = row.get("lifecycle_fact")
    if (not isinstance(fact, dict) or fact.get("ts_code") != code or fact.get("verified") is not True
            or fact.get("requires_recent_listed_A_share_bars") is not False
            or row.get("records_written") != 0):
        return None
    try:
        if fact.get("accepted_review_literal") not in _ACCEPTED_SOP_LITERALS and code != "600193.SH":
            market = {0: "SZ", 1: "SH", 2: "BJ"}.get(row.get("market")) if type(row.get("market")) is int else None
            if (code != str(row.get("symbol", "")).zfill(6) + "." + str(market)
                    or Path(row["path"]).name != code[-2:].lower() + code[:6] + ".day"
                    or row.get("source_sha256_before") != row.get("source_sha256_after")):
                return None
        effective = fact["delisting_effective_date"]
        datetime.strptime(effective, "%Y%m%d")
        if int(effective) > target:
            return None
        raw = dict(path=row["path"], sha256=row["source_sha256_after"])
        _source(raw, owner="original lifecycle raw identity")
        if row.get("lifecycle_policy_ref") is not None:
            if not _reviewed_policy_lifecycle_fact(code, row, fact, effective):
                return None
            proof_route = "REVIEWED_SOURCE_POLICY_OFFICIAL_DELISTING"
        elif row.get("lifecycle_asset_sha256") != _LIFECYCLE_ASSET_SHA:
            return None
        elif fact.get("accepted_review_literal") in _ACCEPTED_SOP_LITERALS:
            for name in ("accepted_review_ref", "accepted_case_result_ref"):
                _source(fact[name], owner="accepted original lifecycle SOP")
            proof_route = "ORIGINAL_FIXED_ASSET_SOP_VARIANT"
        elif _controller_quarantine_fact(code, fact, effective):
            proof_route = ("ORIGINAL_CONTROLLER_QUARANTINE_ONLY_WITH_MIRROR_CAVEAT"
                           if fact.get("issuer_or_broker_mirror_refs") else "ORIGINAL_CONTROLLER_QUARANTINE_ONLY_WITH_PRIMARY_BYTES")
        elif _two_brokers_quarantine_fact(code, fact, effective):
            proof_route = "ORIGINAL_ROOT_ACCEPTED_OFFICIAL_QUARANTINE_ONLY"
        else:
            return None
    except (KeyError, TypeError, ValueError, OSError, QfqGateError):
        return None
    return dict(status="SOP_SKIPPED", reason=_LIFECYCLE_REASON, asof_date=target,
                queried_at=None, capture_date=None, provider_invoked=False,
                source_sync=sync_ref, original_sync_row=row,
                lifecycle_effective_date=effective, classification="QUARANTINED", proof_route=proof_route)


def _prior_bj_capabilities(cache_root: Path, target: int) -> tuple[dict, dict | None]:
    # Exactly one prior checkpoint, loaded once. Never audit every past day.
    candidates = [p / "checkpoint.json" for p in cache_root.iterdir()
                  if p.is_dir() and len(p.name) == 8 and p.name.isdigit()
                  and int(p.name) < target and (p / "checkpoint.json").is_file()] if cache_root.exists() else []
    if not candidates:
        return {}, None
    path = max(candidates, key=lambda p: p.parent.name)
    try:
        raw = path.read_bytes()
        state = json.loads(raw)
        if state.get("asof_date") != int(path.parent.name) or not isinstance(state.get("symbols"), dict):
            return {}, None
        return state["symbols"], dict(path=str(path), sha256=hashlib.sha256(raw).hexdigest())
    except (OSError, ValueError, TypeError):
        return {}, None


def _known_prior_bj_route(code: str, prior: dict, checkpoint_ref: dict | None, target: int) -> dict | None:
    if (not code.endswith(".BJ") or not checkpoint_ref or prior.get("status") != "UNSUPPORTED_MARKET"):
        return None
    try:
        evidence = prior.get("capability_evidence")
        original = evidence.get("original") if isinstance(evidence, dict) else prior
        if not isinstance(original, dict):
            return None
        if isinstance(evidence, dict):
            protocol = dict(provider="Futu OpenD get_rehab", code_format="BJ.SIX_DIGITS",
                            return_code=-1, error_class="BJ_CODE_FORMAT_IS_WRONG")
            if evidence.get("protocol") != protocol or evidence.get("protocol_sha256") != canonical_sha(protocol):
                return None
        response_ref = original["response"]
        response = json.loads(_source(response_ref, owner="known prior BJ capability").read_text())
        error = response.get("error")
        if (response.get("source") != "Futu OpenD get_rehab" or response.get("code") != "BJ." + code[:6]
                or response.get("return_code") != -1 or not isinstance(error, str)
                or "format of code BJ." not in error or "is wrong" not in error
                or original.get("error") != error):
            return None
    except (KeyError, OSError, ValueError, TypeError, QfqGateError):
        return None
    original = {k: original.get(k) for k in ("queried_at", "capture_date", "asof_date", "response", "error")}
    protocol = dict(provider="Futu OpenD get_rehab", code_format="BJ.SIX_DIGITS",
                    return_code=-1, error_class="BJ_CODE_FORMAT_IS_WRONG")
    return dict(status="UNSUPPORTED_MARKET", reason="KNOWN_PRIOR_CAPABILITY_ROUTE_TO_EXISTING_TDX_FALLBACK",
                asof_date=target, queried_at=None, capture_date=None, provider_invoked=False,
                capability_evidence=dict(checkpoint=checkpoint_ref, original=original,
                                         protocol=protocol, protocol_sha256=canonical_sha(protocol)))


def _collect_metadata_owned(codes: list[str], *, cache_root: Path, target: int,
                     client_factory: Callable[[], Any] | None = None,
                     min_interval: float = 0.2, retries: int = 2,
                     sleep: Callable[[float], None] = time.sleep,
                     monotonic: Callable[[], float] = time.monotonic,
                     force_refresh: bool = False, max_age_seconds: float = 86400,
                     prequery_sync_ref: dict | None = None) -> dict:
    """Bounded serial metadata I/O; compute stage can independently use workers.

    The default cadence is conservative and configurable. Error details and
    return codes are retained verbatim as data, never interpreted as actions.
    Caller holds the original producer publication/ownership lock.
    """
    if min_interval < 0 or retries not in (0, 1, 2) or not 0 < max_age_seconds <= 86400:
        raise QfqGateError("FACTOR_RATE_OR_RETRY_CONFIG_INVALID")
    sync_rows = _sync_prequery_rows(prequery_sync_ref, target)
    prior_bj, prior_bj_ref = (_prior_bj_capabilities(cache_root, target)
                              if any(code.endswith(".BJ") and code in sync_rows for code in codes) else ({}, None))
    root = cache_root / str(target)
    root.mkdir(parents=True, exist_ok=True)
    checkpoint = root / "checkpoint.json"
    state = json.loads(checkpoint.read_text()) if checkpoint.is_file() else dict(asof_date=target, symbols={})
    if state.get("asof_date") != target:
        raise QfqGateError("FACTOR_CHECKPOINT_ASOF_MISMATCH")
    state.update(status="RUNNING", started_at=_now(), provider_call_count=0, provider_identity_count=0,
                 sop_skipped_count=0, known_prior_capability_count=0)
    for field in ("completed_at", "finished_at", "counts"):
        state.pop(field, None)
    _json(checkpoint, state)
    if client_factory is None:
        from futu import OpenQuoteContext
        client_factory = lambda: OpenQuoteContext(host="127.0.0.1", port=11111)
    client = None
    last_query = None
    try:
        for code in sorted(set(codes)):
            prior = state["symbols"].get(code, {})
            decision = _verified_sop_skip(code, sync_rows.get(code), target, prequery_sync_ref)
            if sync_rows.get(code, {}).get("lifecycle_skip") is True and decision is None:
                raise QfqGateError("SOP_REBIND_REQUIRED:" + code)
            if decision is not None:
                state["symbols"][code] = decision
                state["sop_skipped_count"] += 1
                _json(checkpoint, state)
                continue
            if code.endswith(".BJ") and code in sync_rows:
                try:
                    row = sync_rows[code]
                    _source(dict(path=row["path"], sha256=row["source_sha256_after"]), owner="original BJ raw identity")
                    bj_raw_valid = True
                except (KeyError, TypeError, ValueError, OSError, QfqGateError):
                    bj_raw_valid = False
                decision = _known_prior_bj_route(code, prior_bj.get(code, {}), prior_bj_ref, target) if bj_raw_valid else None
                if decision is not None:
                    state["symbols"][code] = decision
                    state["known_prior_capability_count"] += 1
                    _json(checkpoint, state)
                    continue
            if not force_refresh and prior.get("status") in ("OK", "EMPTY") and _fresh(prior, target, max_age_seconds):
                _source(prior["response"], owner=code)
                continue
            exchange = code.rsplit(".", 1)[-1]
            if exchange not in ("SH", "SZ", "BJ"):
                state["symbols"][code] = dict(status="UNSUPPORTED_MARKET", market=exchange, queried_at=None, asof_date=target, capture_date=_capture_date(),
                                                   reason="FUTU_REHAB_MARKET_NOT_SUPPORTED_BY_ADAPTER")
                _json(checkpoint, state)
                continue
            if client is None:
                try:
                    client = client_factory()
                    state.pop("context_error", None)
                except Exception as exc:
                    state["context_error"] = dict(observed_at=_now(), error=str(exc))
                    _json(checkpoint, state)
                    raise
            futu_code = exchange + "." + code.split(".", 1)[0]
            state["provider_identity_count"] += 1
            for attempt in range(retries + 1):
                if last_query is not None:
                    pause = min_interval - (monotonic() - last_query)
                    if pause > 0:
                        sleep(pause)
                last_query = monotonic()
                queried_at = _now()
                common = dict(queried_at=queried_at, asof_date=target, capture_date=_capture_date())
                state["symbols"][code] = dict(status="QUERYING", attempt=attempt + 1, **common)
                _json(checkpoint, state)
                try:
                    state["provider_call_count"] += 1
                    ret, data = client.get_rehab(futu_code)
                    if int(ret) != 0:
                        error_response = dict(source="Futu OpenD get_rehab", code=futu_code, return_code=int(ret), error=str(data))
                        error_path = root / "responses" / (canonical_sha(error_response) + ".json")
                        if not error_path.exists():
                            _json(error_path, error_response)
                        error_ref = dict(path=str(error_path), sha256=sha(error_path))
                        if exchange == "BJ" and "format of code BJ." in str(data) and "is wrong" in str(data):
                            state["symbols"][code] = dict(status="UNSUPPORTED_MARKET", response=error_ref, error=str(data),
                                                               attempts=attempt + 1, return_code=int(ret), **common)
                            break
                        raise QfqGateError(f"FUTU_GET_REHAB_RETURN_{ret}:{data}")
                    rows = _records(data)
                    # Validate the protocol even though full event selection
                    # waits for the bound raw-history start date.
                    _event_rows(rows, target, 19000101)
                    response = dict(source="Futu OpenD get_rehab", code=futu_code, return_code=int(ret), rows=rows)
                    response_path = root / "responses" / (canonical_sha(response) + ".json")
                    if not response_path.exists():
                        _json(response_path, response)
                    elif canonical_sha(json.loads(response_path.read_text())) != canonical_sha(response):
                        raise QfqGateError(f"IMMUTABLE_FACTOR_RESPONSE_CONFLICT:{response_path}")
                    ref = dict(path=str(response_path), sha256=sha(response_path))
                    state["symbols"][code] = dict(status="OK" if rows else "EMPTY", **common,
                                                       attempts=attempt + 1, response=ref, row_count=len(rows))
                    break
                except Exception as exc:
                    state["symbols"][code] = dict(status="ERROR", **common, attempts=attempt + 1, error=str(exc))
                    _json(checkpoint, state)
                    if attempt < retries:
                        sleep(min(30.0, 2.0 ** attempt))
            _json(checkpoint, state)
        counts = {name: sum(state["symbols"].get(code, {}).get("status") == name for code in set(codes))
                  for name in ("OK", "EMPTY", "UNSUPPORTED_MARKET", "SOP_SKIPPED", "ERROR", "QUERYING")}
        state["counts"] = counts
        state["requested_count"] = len(set(codes))
        state["requested_codes_sha256"] = canonical_sha(sorted(set(codes)))
        state["status"] = "FAILED" if counts["ERROR"] or counts["QUERYING"] else ("PARTIAL_EXPECTED_EXCLUSIONS" if counts["SOP_SKIPPED"] else ("PARTIAL_EXPECTED_UNSUPPORTED" if counts["UNSUPPORTED_MARKET"] else "READY"))
        state["finished_at"] = _now()
        state.pop("completed_at", None)
        if state["status"] == "READY":
            state["completed_at"] = state["finished_at"]
        _json(checkpoint, state)
        return state
    except BaseException as exc:
        state.update(status="INTERRUPTED" if isinstance(exc, (KeyboardInterrupt, SystemExit)) else "FAILED",
                     finished_at=_now(), stop_reason=str(exc))
        _json(checkpoint, state)
        raise
    finally:
        if client is not None:
            client.close()


def collect_metadata(codes: list[str], *, cache_root: Path, target: int, **options) -> dict:
    """Unique cache owner; terminal status must be inspected by the caller."""
    cache_root.mkdir(parents=True, exist_ok=True)
    with (cache_root / ".futu_rehab_owner.lock").open("a+b") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise QfqGateError("FACTOR_METADATA_OWNER_ALREADY_ACTIVE") from exc
        try:
            return _collect_metadata_owned(codes, cache_root=cache_root, target=target, **options)
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)



RESEARCH_CARRY_SCHEMA = "research_factor_cache_carry_forward.v1"
RESEARCH_CARRY_LABEL = "RESEARCH_CACHE_CARRY_FORWARD"


def _provider_original(item: dict, code: str) -> dict:
    """Validate original whole response without changing its observation dates."""
    if item.get("status") not in ("OK", "EMPTY"):
        raise QfqGateError("CACHE_ORIGINAL_STATUS_INVALID:" + code)
    for key in ("capture_date", "asof_date"):
        if type(item.get(key)) is not int:
            raise QfqGateError("CACHE_ORIGINAL_DATE_UNBOUND:" + code)
        datetime.strptime(str(item[key]), "%Y%m%d")
    observed = datetime.fromisoformat(item["queried_at"])
    if observed.tzinfo is None or int(observed.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d")) != item["capture_date"]:
        raise QfqGateError("CACHE_ORIGINAL_CAPTURE_CONFLICT:" + code)
    response = json.loads(_source(item["response"], owner="original cache " + code).read_text())
    rows = response.get("rows")
    if (response.get("source") != "Futu OpenD get_rehab" or response.get("return_code") != 0
            or response.get("code") != code[-2:] + "." + code[:6] or not isinstance(rows, list)
            or item.get("row_count") != len(rows) or item["status"] != ("OK" if rows else "EMPTY")):
        raise QfqGateError("CACHE_ORIGINAL_RESPONSE_IDENTITY_CONFLICT:" + code)
    _event_rows(rows, 99991231, 19000101)
    return item


def research_cache_plan(codes: list[str], *, target: int, config_ref: dict) -> dict:
    """Bound explicit research-only opt-in. No provider/default writes or I/O."""
    from ops.research_panel_tdx_adjustment_inputs import load_event_detector, event_invalidation
    config = json.loads(_source(config_ref, owner="research carry configuration").read_text())
    if config.get("schema") != "research_factor_cache_plan.v1" or config.get("target_date") != target:
        raise QfqGateError("CACHE_PLAN_SCHEMA_OR_TARGET_CONFLICT")
    exceptions = config.get("observed_provider_only_exceptions")
    if not isinstance(exceptions, list) or not config.get("provider_only_exception_scope"):
        raise QfqGateError("CACHE_OBSERVED_EXCEPTION_SCOPE_UNBOUND")
    for ref in config.get("source_comparison_refs", []):
        _source(ref, owner="observed provider comparison")
    previous_ref = config["previous_metadata"]
    previous = json.loads(_source(previous_ref, owner="prior cache metadata").read_text())
    start = previous["asof_date"]
    if type(start) is not int or start >= target:
        raise QfqGateError("CACHE_PREVIOUS_TARGET_CONFLICT")
    identities = [json.loads(_source(config[k], owner=k).read_text()) for k in ("previous_identities", "current_identities")]
    if (identities[0].get("asof_date") != start or identities[1].get("asof_date") != target
            or not all(isinstance(i.get("symbols"), dict) for i in identities)):
        raise QfqGateError("CACHE_IDENTITY_MANIFEST_DATE_UNBOUND")
    before = load_event_detector(config["prior_detector"], start, wanted_codes=tuple(codes))
    after = load_event_detector(config["current_detector"], target, wanted_codes=tuple(codes))
    if previous.get("schema") == RESEARCH_CARRY_SCHEMA and previous.get("detector_binding") != before["binding"]:
        raise QfqGateError("CACHE_PARENT_DETECTOR_CONFLICT")
    exceptional = set()
    for exception in exceptions:
        _source(exception["evidence"], owner="observed provider-only exception")
        exceptional.add(exception["ts_code"])
    sync_ref = config.get("prequery_sync_ref")
    sync_rows = _sync_prequery_rows(sync_ref, target)
    # A prior research snapshot retains the immutable original capability
    # evidence, so this remains one bound checkpoint rather than a day scan.
    plans = {}
    for code in sorted(set(codes)):
        decision = _verified_sop_skip(code, sync_rows.get(code), target, sync_ref)
        if sync_rows.get(code, {}).get("lifecycle_skip") is True and decision is None:
            raise QfqGateError("SOP_REBIND_REQUIRED:" + code)
        prior = previous.get("symbols", {}).get(code, {})
        if decision is None and code.endswith(".BJ") and code in sync_rows:
            row = sync_rows[code]
            try:
                _source(dict(path=row["path"], sha256=row["source_sha256_after"]), owner="BJ raw identity")
                decision = _known_prior_bj_route(code, prior, previous_ref, target)
            except (KeyError, OSError, QfqGateError):
                pass
        if decision is not None:
            plans[code] = dict(route="PREQUERY_EXCLUSION", receipt=decision)
            continue
        reasons = event_invalidation(before, after, code, start, target)
        identity = identities[1]["symbols"].get(code)
        if not identity or identity != identities[0]["symbols"].get(code):
            reasons.append("IDENTITY_CHANGED_OR_MISSING")
        if code in exceptional:
            reasons.append("OBSERVED_PROVIDER_ONLY_REVISION")
        original = prior
        if prior.get("status") == RESEARCH_CARRY_LABEL:
            # Carry-of-carry may use only a completed, bound prior proof. Its
            # original observation remains untouched; parent is independently
            # pinned in today's receipt/config.
            if (previous.get("status") != "READY_RESEARCH_CACHE" or prior.get("schema") != RESEARCH_CARRY_SCHEMA
                    or prior.get("target_date") != start or prior.get("identity_binding") != identity
                    or prior.get("provider_revision_coverage") != "CANNOT_CONFIRM"
                    or prior.get("verification", {}).get("current_detector_binding") != before["binding"]
                    or prior.get("provider_queried_for_this_record") is not False
                    or prior.get("original_provider_response") != prior.get("original_provider_receipt", {}).get("response")
                    or any(prior.get("original_" + k) != prior.get("original_provider_receipt", {}).get(k)
                           for k in ("capture_date", "asof_date", "queried_at"))
                    or prior.get("historical_PIT") is not False):
                reasons.append("PRIOR_CARRY_PROOF_INVALID")
            original = prior.get("original_provider_receipt", {})
        try:
            _provider_original(original, code)
            if original["asof_date"] > start or original["capture_date"] > start:
                raise QfqGateError("CACHE_ORIGINAL_AFTER_PRIOR_TARGET")
            response = json.loads(Path(original["response"]["path"]).read_text())
            if any(start < int(''.join(c for c in str(r["ex_div_date"]) if c.isdigit())[:8]) <= target for r in response["rows"]):
                reasons.append("CACHED_PROVIDER_EVENT_EFFECTIVE_WINDOW")
        except (KeyError, ValueError, TypeError, OSError, QfqGateError):
            reasons.append("CACHE_MISSING_OR_INVALID")
        if reasons:
            plans[code] = dict(route="REFRESH_REQUIRED", reasons=sorted(set(reasons)))
            continue
        receipt = dict(schema=RESEARCH_CARRY_SCHEMA, status=RESEARCH_CARRY_LABEL, label=RESEARCH_CARRY_LABEL,
            ts_code=code, target_date=target, original_provider_receipt=original,
            original_capture_date=original["capture_date"], original_asof_date=original["asof_date"],
            original_queried_at=original["queried_at"], original_provider_response=original["response"],
            prior_valid_through=start, parent_metadata=previous_ref, identity_binding=identity,
            configuration=config_ref, verification=dict(target_date=target,
                prior_detector_binding=before["binding"], current_detector_binding=after["binding"],
                source_coverage_end_date=after["coverage_end_date"],
                source_capture=config["current_detector"]["capture"],
                full_row_fingerprint=after["index"].get(code, {}).get("fingerprint", canonical_sha([])),
                changed_rows=False, effective_events_in_window=False,
                decision_basis="OFFICIAL_EVENT_AND_OBSERVED_CACHE_SCOPE"),
            provider_queried_for_this_record=False, provider_revision_coverage="CANNOT_CONFIRM",
            provider_revision_scope_limit=config["provider_only_exception_scope"], historical_PIT=False,
            RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)
        plans[code] = dict(route=RESEARCH_CARRY_LABEL, receipt=receipt)
    return dict(symbols=plans, detector_binding=after["binding"], configuration=config_ref)


def _same_asof_metadata_records(ref: dict, codes: list[str], target: int, config_ref: dict) -> tuple[dict, dict]:
    """Reference existing same-date observations; never change freshness or timestamps."""
    value = json.loads(_source(ref, owner="same-asof metadata descriptor").read_text())
    if (value.get("schema") != "qfq_same_asof_source_repair_v1" or value.get("asof_date") != target
            or value.get("RESEARCH_ONLY") is not True
            or any(value.get(k) is not False for k in ("production_allowed", "buy_gate_updated", "orders_sent"))):
        raise QfqGateError("SAME_ASOF_METADATA_DESCRIPTOR_INVALID")
    original = json.loads(_source(value["baseline_snapshot"], owner="committed same-date input").read_text())
    metadata = original.get("research_factor_receipts", {})
    baseline = json.loads(_source(value["baseline_receipt"], owner="committed paired metadata parent").read_text())
    from ops.research_panel_qfq import panel_contract
    for role in ("selector", "backtest"):
        bound = value["baseline_roles"][role]
        footer = panel_contract(Path(bound["path"]))
        if (baseline.get("candidates", {}).get(role) != bound["path"]
                or baseline.get("candidate_sha256", {}).get(role) != bound["sha256"]
                or footer.get("adjustment_snapshot") != value["baseline_snapshot"]
                or footer.get("generation_id") != baseline.get("generation_id")
                or footer.get("asof_date") != target):
            raise QfqGateError("SAME_ASOF_METADATA_NOT_COMMITTED_PARENT")
    old_config = json.loads(_source(metadata["configuration"], owner="original same-date metadata config").read_text())
    current = json.loads(_source(config_ref, owner="current same-date metadata config").read_text())
    if (original.get("asof_date") != target or metadata.get("asof_date") != target
            or metadata.get("status") != "READY_RESEARCH_CACHE" or current.get("target_date") != target
            or metadata.get("historical_PIT") is not False
            or metadata.get("detector_binding") != canonical_sha(old_config["current_detector"])):
        raise QfqGateError("SAME_ASOF_METADATA_PRIOR_NOT_CLOSED")
    def semantic_detector(descriptor):
        result = {}
        for key, item in descriptor.items():
            if isinstance(item, dict) and set(item) >= {"path", "sha256"}:
                _source(item, owner="same-date detector " + key)
                result[key] = {k: v for k, v in item.items() if k != "path"}
            else:
                result[key] = item
        return result
    if semantic_detector(old_config["current_detector"]) != semantic_detector(current["current_detector"]):
        raise QfqGateError("SAME_ASOF_METADATA_DETECTOR_CHANGED")
    old_ids = json.loads(_source(old_config["current_identities"], owner="old same-date identities").read_text())
    ids = json.loads(_source(current["current_identities"], owner="current same-date identities").read_text())
    evidence = json.loads(_source(value["metadata30_evidence"], owner="original D30 thirty responses").read_text())
    wanted = set(codes);records = {};provenance = {}
    if (evidence.get("baseline_snapshot") != value["baseline_snapshot"] or len(evidence.get("captures", [])) != 30
            or len({r.get("symbol") for r in evidence["captures"]}) != 30):
        raise QfqGateError("SAME_ASOF_METADATA_EXACT30_UNBOUND")
    for captured in evidence["captures"]:
        code = captured["symbol"];row = metadata.get("symbols", {}).get(code)
        if (not isinstance(row, dict) or row.get("asof_date") != target or row.get("capture_date") != target
                or old_ids.get("symbols", {}).get(code) != ids.get("symbols", {}).get(code)
                or not ids.get("symbols", {}).get(code)
                or any(captured.get(k) != row.get(k) for k in ("status", "asof_date", "capture_date", "queried_at", "response"))):
            raise QfqGateError("SAME_ASOF_METADATA_RECORD_CHANGED:" + code)
        _provider_original(row, code)
        if code in wanted:
            records[code] = dict(row)
            provenance[code] = dict(kind="ORIGINAL_SAME_DATE_RESPONSE_UNMODIFIED",
                                   source=value["baseline_snapshot"], record_sha256=canonical_sha(row))
    capability_ref = value["sdk_capability"]
    capability = json.loads(_source(capability_ref, owner="six exact SDK request rejections").read_text())
    expected = {"920003.BJ", "920029.BJ", "920100.BJ", "920187.BJ", "920208.BJ", "920699.BJ"}
    if (capability.get("schema") != "EXACT_SIX_FUTU_SDK_REQUEST_PACKER_CAPABILITY_V1"
            or capability.get("research_target_date") != target or capability.get("sdk_validation_calls") != 6
            or capability.get("source_api_family") != "Futu OpenD get_rehab"
            or any(capability.get(k) != 0 for k in ("quote_contexts_created", "network_requests", "price_bars_fetched"))
            or capability.get("historical_PIT") is not False
            or {r.get("symbol") for r in capability.get("rows", [])} != expected
            or len(capability.get("rows", [])) != 6):
        raise QfqGateError("SAME_ASOF_METADATA_SDK_SCOPE_INVALID")
    observed = datetime.fromisoformat(capability["observed_at"])
    if observed.tzinfo is None or observed > datetime.now(timezone.utc) or int(observed.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d")) != capability["capture_date"]:
        raise QfqGateError("SAME_ASOF_METADATA_SDK_TIME_INVALID")
    from futu.quote import quote_query
    from futu.common import utils, constant
    expected_sources = {str(Path(module.__file__).resolve()): sha(Path(module.__file__))
                        for module in (quote_query, utils, constant)}
    if (len(capability.get("sdk_sources", [])) != 3
            or {str(Path(source["path"]).resolve()): source["sha256"] for source in capability["sdk_sources"]} != expected_sources):
        raise QfqGateError("SAME_ASOF_METADATA_INSTALLED_SDK_SOURCE_CHANGED")
    for source in capability["sdk_sources"]:
        _source(source, owner="installed SDK request validator")
    for row in capability["rows"]:
        code = row["symbol"]
        if (row.get("request_code") != "BJ." + code[:6] or row.get("return_code") != -1
                or row.get("packed_request_is_none") is not True
                or row.get("remaining_return_values") != [0, 0]
                or "format of code " + row["request_code"] + " is wrong" not in row.get("error", "")):
            raise QfqGateError("SAME_ASOF_METADATA_SDK_DISPATCH_OR_IDENTITY_INVALID:" + code)
        if code in wanted:
            records[code] = dict(status="UNSUPPORTED_MARKET", reason="INSTALLED_SDK_REQUEST_REJECTED_BEFORE_DISPATCH",
                asof_date=target, queried_at=None, capture_date=None, provider_invoked=False,
                sdk_validation_observed_at=capability["observed_at"], sdk_validation_capture_date=capability["capture_date"],
                sdk_capability=capability_ref, sdk_request_result=row, historical_PIT=False)
            provenance[code] = dict(kind="LOCAL_INSTALLED_SDK_CAPABILITY_NOT_QUOTE_OR_PIT", source=capability_ref,
                                   record_sha256=canonical_sha(records[code]))
    return records, dict(input=ref, records=provenance, original_metadata30=value["metadata30_evidence"],
                          sdk_capability=capability_ref, capture_dates_unchanged=True,
                          invocation_network_requests=0, invocation_price_bars_fetched=0)


def collect_research_metadata(codes: list[str], *, cache_root: Path, target: int,
                              config_ref: dict, with_plan: bool = False, same_asof_metadata_ref: dict | None = None, **options):
    """Separate research output; original collector sees only refresh identities.

    Uses the existing owner lock. Default collect_metadata and _fresh are
    unchanged. An invalid full detector stops before any provider dispatch.
    """
    cache_root.mkdir(parents=True, exist_ok=True)
    with (cache_root / ".futu_rehab_owner.lock").open("a+b") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise QfqGateError("FACTOR_METADATA_OWNER_ALREADY_ACTIVE") from exc
        try:
            plan = research_cache_plan(codes, target=target, config_ref=config_ref)
            destination = cache_root / "research_carry" / str(target) / (canonical_sha(config_ref) + ".json")
            plan_sha = canonical_sha(plan)
            same_rows, same_provenance = (_same_asof_metadata_records(same_asof_metadata_ref, codes, target, config_ref)
                if same_asof_metadata_ref is not None else ({}, None))
            if destination.is_file():
                existing = json.loads(destination.read_text())
                if existing.get("plan_sha256") != plan_sha or existing.get("requested_codes") != sorted(set(codes)):
                    raise QfqGateError("CACHE_RESTART_PLAN_CONFLICT")
                if existing.get("status") == "READY_RESEARCH_CACHE":
                    for code, row in existing["symbols"].items():
                        if code in same_rows:
                            if row != same_rows[code]:
                                raise QfqGateError("CACHE_RESTART_SAME_ASOF_RECORD_CHANGED:" + code)
                        elif row.get("status") in ("OK", "EMPTY"):
                            _provider_original(row, code)
                        elif plan["symbols"][code].get("receipt") != {k: v for k, v in row.items() if k != "checked_at"}:
                            raise QfqGateError("CACHE_RESTART_PROOF_CONFLICT:" + code)
                    result = dict(existing, reused_completed_proof=True, invocation_provider_call_count=0,
                                  invocation_provider_identity_count=0)
                    return (result, plan) if with_plan else result
            refresh = [c for c, p in plan["symbols"].items() if p["route"] == "REFRESH_REQUIRED" and c not in same_rows]
            # No detector error is caught here and no full-list fallback exists.
            actual = _collect_metadata_owned(refresh, cache_root=cache_root, target=target, **options) if refresh else {}
            symbols = {}
            for code, item in plan["symbols"].items():
                symbols[code] = (dict(same_rows[code]) if code in same_rows and item["route"] == "REFRESH_REQUIRED"
                    else dict(actual["symbols"][code]) if item["route"] == "REFRESH_REQUIRED"
                    else dict(item["receipt"], checked_at=_now()))
            counts = {s: sum(r["status"] == s for r in symbols.values()) for s in sorted({r["status"] for r in symbols.values()})}
            ready = all(r["status"] in ("OK", "EMPTY", RESEARCH_CARRY_LABEL, "SOP_SKIPPED", "UNSUPPORTED_MARKET") for r in symbols.values())
            output = dict(schema=RESEARCH_CARRY_SCHEMA, asof_date=target, symbols=symbols,
                status="READY_RESEARCH_CACHE" if ready else "FAILED", requested_codes=sorted(set(codes)),
                requested_count=len(set(codes)), counts=counts, refresh_required_codes=refresh,
                plan_sha256=plan_sha, configuration=config_ref, detector_binding=plan["detector_binding"],
                provider_call_count=actual.get("provider_call_count", 0), provider_identity_count=actual.get("provider_identity_count", 0),
                invocation_provider_call_count=actual.get("provider_call_count", 0),
                invocation_provider_identity_count=actual.get("provider_identity_count", 0),
                provider_revision_coverage="CANNOT_CONFIRM",
                provider_revision_scope_limit=json.loads(_source(config_ref, owner="cache scope").read_text())["provider_only_exception_scope"],
                finished_at=_now(), historical_PIT=False,
                RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)
            if same_provenance is not None:
                output["same_asof_metadata_reuse"] = same_provenance
            _json(destination, output)
            return (output, plan) if with_plan else output
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def research_carry_events(receipt: dict, code: str, target: int, start: int, *, plan: dict) -> tuple[list[dict], str]:
    """Explicit builder seam, revalidated against the bound read-only plan."""
    expected = plan["symbols"].get(code, {}).get("receipt")
    if (expected is None or {k: v for k, v in receipt.items() if k != "checked_at"} != expected
            or receipt.get("status") != RESEARCH_CARRY_LABEL or receipt.get("target_date") != target):
        raise QfqGateError("CACHE_BUILDER_CARRY_PROOF_CONFLICT:" + code)
    original = _provider_original(receipt["original_provider_receipt"], code)
    response = json.loads(Path(original["response"]["path"]).read_text())
    return _event_rows(response["rows"], target, start), RESEARCH_CARRY_LABEL + "; provider_revision_coverage=CANNOT_CONFIRM; historical_PIT=false"
