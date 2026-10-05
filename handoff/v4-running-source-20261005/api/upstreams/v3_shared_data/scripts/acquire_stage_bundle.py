"""Fixed one-stage A/H shared acquisition entry.

Only ``--trade-date`` and ``--stage-id`` identify work.  Code lists come from
verified store-owned universe manifests; no path, shell, Python, or code-list
argument is accepted.
"""
from __future__ import annotations

import dataclasses
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from shared_data.bundles import (
    BUNDLE_LATEST_SCHEMA_VERSION,
    BUNDLE_SCHEMA_VERSION,
    publish_bundle_receipt,
)
from shared_data.consumer import read_verified_latest
from shared_data.hashing import sha256_file, sha256_json
from shared_data.names import load_verified_hk_names
from shared_data.paths import resolve_under
from shared_data.store import StoreError
from scripts.acquire_stage_raw import resolve_futu_python
from scripts.live_acquisition.contracts import (
    STAGE_MARKETS,
    STAGE_WINDOWS,
    StageSourceResult,
    market_role,
)
from scripts.live_acquisition.futu_bridge import collect_futu_minute
from scripts.live_acquisition.orchestrator import persist_stage_result
from scripts.live_acquisition.pytdx_exhq import collect_pytdx_exhq_minute
from scripts.live_acquisition.pytdx_hq import collect_pytdx_hq_minute
from scripts.live_acquisition.universe import resolve_stage_universe

_STORE_ROOT_ENV = "V3_SHARED_DATA_STORE_ROOT"
_DEFAULT_STORE_ROOT = _PROJECT_ROOT / ".runtime" / "data"
_MARKET_TIMEOUTS = {"A_SHARE": 90, "HK_CONNECT": 180}
_FUTU_SUBSCRIPTION_LIMIT = 100


def _enrich_hk_names(store_root: Path, result: StageSourceResult) -> StageSourceResult:
    """Fill pytdx code-only names from the verified shared HK dictionary."""
    if not (store_root / "assets" / "hk_0_2" / "name_latest.json").is_file():
        return result
    names, dictionary_sha = load_verified_hk_names(store_root)
    rows = []
    for source in result.rows:
        row = dict(source)
        code = str(row.get("code") or "").strip().upper()
        if not str(row.get("name") or "").strip() or str(row.get("name")).strip().upper() == code:
            row["name"] = names.get(code, row.get("name") or code)
        rows.append(row)
    return dataclasses.replace(
        result,
        rows=rows,
        name_dictionary_sha256=dictionary_sha,
    )


def _reuse_ready_bundle(
    store_root: Path,
    trade_date: str,
    stage_id: str,
    expected_markets: tuple[str, ...],
    universes: dict[str, Any],
) -> dict[str, Any] | None:
    """Return a fully re-verified READY slot without calling a collector.

    A published READY slot is immutable.  Scheduled retries therefore verify
    the bundle receipt, both component runs and the current universe hashes,
    then reuse it.  A missing/FAILED slot returns ``None`` so the caller may
    acquire; a corrupt READY slot fails closed instead of silently recapturing.
    """
    latest_path = store_root / "bundle_latest.json"
    if not latest_path.is_file():
        return None
    try:
        latest = json.loads(latest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise StoreError("bundle_latest.json corrupt") from exc
    if (
        not isinstance(latest, dict)
        or latest.get("schema_version") != BUNDLE_LATEST_SCHEMA_VERSION
        or not isinstance(latest.get("entries"), dict)
    ):
        raise StoreError("bundle_latest.json corrupt")
    entry = latest["entries"].get(f"{trade_date}/{stage_id}")
    if entry is None or (isinstance(entry, dict) and entry.get("status") == "FAILED"):
        return None
    if not isinstance(entry, dict) or entry.get("status") != "READY":
        raise StoreError("bundle latest entry is invalid")
    try:
        receipt_path = resolve_under(store_root, str(entry["receipt_relative"]))
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError) as exc:
        raise StoreError("READY bundle receipt is unreadable") from exc
    if (
        not isinstance(receipt, dict)
        or receipt.get("schema_version") != BUNDLE_SCHEMA_VERSION
        or receipt.get("bundle_id") != entry.get("bundle_id")
        or receipt.get("idempotency_key") != entry.get("idempotency_key")
        or receipt.get("trade_date") != trade_date
        or receipt.get("stage_id") != stage_id
        or receipt.get("status") != "READY"
        or set(receipt.get("markets") or {}) != set(expected_markets)
        or any(receipt.get(key) is not False for key in (
            "production_allowed", "buy_gate_updated", "orders_sent"
        ))
    ):
        raise StoreError("READY bundle receipt identity is invalid")
    for market in expected_markets:
        evidence = receipt["markets"].get(market)
        role = market_role(market, stage_id)
        if not isinstance(evidence, dict) or evidence.get("status") != "READY":
            raise StoreError(f"READY bundle market is invalid: {market}")
        run = read_verified_latest(store_root, trade_date, role)
        if (
            evidence.get("role") != role
            or evidence.get("run_id") != run.receipt.get("run_id")
            or evidence.get("artifact_sha256") != run.receipt.get("artifact_sha256")
            or evidence.get("manifest_relative") != run.verification.get("manifest_relative")
            or evidence.get("receipt_relative") != run.verification.get("receipt_relative")
            or evidence.get("universe_codes_sha256") != universes[market].codes_sha256
            or evidence.get("universe_source_sha256") != universes[market].source_sha256
        ):
            raise StoreError(f"READY bundle market linkage is invalid: {market}")
    return {
        "ok": True,
        "already_exists": True,
        "reused": True,
        "bundle_id": receipt["bundle_id"],
        "status": "READY",
        "receipt_relative": str(entry["receipt_relative"]),
        "markets": receipt["markets"],
    }


def _market_evidence(
    market: str,
    stage_id: str,
    universe: Any,
    result: StageSourceResult,
    persistence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    evidence = {
        "market": market,
        "role": market_role(market, stage_id),
        "status": "READY" if result.status == "READ_OK" and not result.cannot_confirm else "FAILED",
        "source_status": result.status,
        "source_id": result.source_id,
        "code_count": len(universe.codes),
        "universe_codes_sha256": universe.codes_sha256,
        "universe_source_sha256": universe.source_sha256,
        "row_count": len(result.rows),
        "requested_code_count": int(result.requested_code_count or len(universe.codes)),
        "completed_code_count": int(result.completed_code_count or len(result.rows)),
        "no_data_code_count": len(result.no_data_codes),
        "no_data_codes": list(result.no_data_codes),
        "no_data_codes_sha256": sha256_json(sorted(result.no_data_codes)),
        "error": str(result.error or ""),
    }
    if persistence:
        evidence.update(
            role=persistence.get("role") or evidence["role"],
            run_id=persistence.get("run_id"),
            artifact_sha256=persistence.get("artifact_sha256"),
            manifest_relative=persistence.get("manifest_relative"),
            receipt_relative=persistence.get("receipt_relative"),
            status=persistence.get("status"),
        )
    return evidence


def _complete_result(result: StageSourceResult, expected_codes: tuple[str, ...]) -> bool:
    if result.status != "READ_OK" or result.cannot_confirm:
        return False
    actual = [str(row.get("code") or "") for row in result.rows if isinstance(row, dict)]
    if result.requested_code_count:
        return (
            result.requested_code_count == len(expected_codes)
            and result.completed_code_count == len(expected_codes)
            and len(actual) == len(set(actual))
            and set(actual).union(result.no_data_codes) == set(expected_codes)
            and not set(actual).intersection(result.no_data_codes)
        )
    return len(actual) == len(expected_codes) and set(actual) == set(expected_codes)


def _merge_a_share_results(
    expected_codes: tuple[str, ...],
    components: list[tuple[tuple[str, ...], StageSourceResult]],
) -> StageSourceResult:
    """Merge Futu SH/SZ and PyTDX-HQ BJ results in universe order."""
    rows_by_code: dict[str, dict[str, Any]] = {}
    duplicate_codes: list[str] = []
    errors: list[str] = []
    cannot_confirm: list[str] = []
    no_data_codes: list[str] = []
    statuses_ready = True
    source_ids: list[str] = []
    display_names: list[str] = []
    for partition, result in components:
        source_ids.append(result.source_id)
        display_names.append(result.display_name)
        statuses_ready = statuses_ready and result.status == "READ_OK" and not result.cannot_confirm
        if result.error:
            errors.append(f"{result.source_id}: {result.error}")
        cannot_confirm.extend(result.cannot_confirm)
        no_data_codes.extend(result.no_data_codes)
        partition_set = set(partition)
        for row in result.rows:
            code = str(row.get("code") or "").strip().upper()
            if code not in partition_set or code not in expected_codes:
                cannot_confirm.append(f"A-share collector returned out-of-partition code {code!r}")
                continue
            if code in rows_by_code:
                duplicate_codes.append(code)
                continue
            rows_by_code[code] = dict(row)

    missing = [code for code in expected_codes if code not in rows_by_code]
    no_data_codes.extend(missing)
    no_data_codes = list(dict.fromkeys(code for code in no_data_codes if code in expected_codes))
    if set(no_data_codes).intersection(rows_by_code):
        cannot_confirm.append("A-share collector returned both row and no_data evidence for one code")
    if duplicate_codes:
        cannot_confirm.append(
            "A-share collector returned duplicate codes: " + ",".join(sorted(set(duplicate_codes)))
        )
    cannot_confirm = list(dict.fromkeys(cannot_confirm))
    rows = [rows_by_code[code] for code in expected_codes if code in rows_by_code]
    complete = (
        statuses_ready
        and not missing
        and not no_data_codes
        and not cannot_confirm
        and len(rows) == len(expected_codes)
    )
    status = "READ_OK" if complete else "DATA_PARTIAL" if rows else "READ_FAILED"
    if not errors and no_data_codes:
        errors.append("missing exact A-share rows: " + ",".join(no_data_codes))
    return StageSourceResult(
        source_id="+".join(dict.fromkeys(source_ids)) or "mixed_a_share",
        display_name=" + ".join(dict.fromkeys(display_names)) or "A-share mixed collector",
        fidelity="MIXED_A_SHARE_1MIN_CUTOFF_SAFE",
        status=status,
        rows=rows,
        error="; ".join(errors)[:1200],
        cannot_confirm=cannot_confirm,
        requested_code_count=len(expected_codes),
        completed_code_count=len(rows),
        no_data_codes=no_data_codes,
    )


def run_stage_bundle(
    store_root: Path | str,
    trade_date: str,
    stage_id: str,
    python_path: Path | str,
    *,
    dry_run: bool = False,
    historical_backfill: bool = False,
    futu_collector: Callable[..., StageSourceResult] = collect_futu_minute,
    pytdx_collector: Callable[..., StageSourceResult] = collect_pytdx_exhq_minute,
    pytdx_hq_collector: Callable[..., StageSourceResult] = collect_pytdx_hq_minute,
) -> dict[str, Any]:
    """Acquire and publish both markets, or persist a retryable total failure."""
    if stage_id not in STAGE_WINDOWS:
        raise ValueError(f"unknown stage {stage_id!r}")
    store_root = Path(store_root)
    python_path = Path(python_path)
    if not python_path.is_file():
        raise ValueError(f"futu python is not a file: {python_path}")
    expected_markets = STAGE_MARKETS[stage_id]
    universes = {
        market: resolve_stage_universe(store_root, trade_date, market)
        for market in expected_markets
    }
    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "status": "VALIDATED",
            "trade_date": trade_date,
            "stage_id": stage_id,
            "markets": {
                market: {
                    "role": market_role(market, stage_id),
                    "code_count": len(universe.codes),
                    "codes_sha256": universe.codes_sha256,
                }
                for market, universe in universes.items()
            },
        }

    if not historical_backfill:
        reusable = _reuse_ready_bundle(
            store_root, trade_date, stage_id, expected_markets, universes
        )
        if reusable is not None:
            return reusable

    previous_components: dict[str, dict[str, Any]] = {}
    previous_bundle: dict[str, Any] | None = None
    if historical_backfill:
        # Freeze the current identities before any component replacement.  The
        # store and bundle writers re-check these CAS identities under lock.
        for market in expected_markets:
            role = market_role(market, stage_id)
            try:
                previous = read_verified_latest(store_root, trade_date, role)
            except StoreError:
                continue
            previous_components[market] = {
                "run_id": previous.verification["run_id"],
                "artifact_sha256": previous.verification["artifact_sha256"],
                "manifest_sha256": previous.verification["manifest_sha256"],
                "receipt_sha256": previous.verification["receipt_sha256"],
                "artifact_relative": previous.verification["artifact_relative"],
                "manifest_relative": previous.verification["manifest_relative"],
                "receipt_relative": previous.verification["receipt_relative"],
            }
        bundle_latest_path = store_root / "bundle_latest.json"
        if bundle_latest_path.is_file():
            try:
                bundle_latest = json.loads(bundle_latest_path.read_text(encoding="utf-8"))
                old_entry = bundle_latest.get("entries", {}).get(f"{trade_date}/{stage_id}")
                if isinstance(old_entry, dict) and old_entry.get("status") == "READY":
                    old_receipt_path = resolve_under(store_root, str(old_entry["receipt_relative"]))
                    previous_bundle = {
                        "bundle_id": old_entry.get("bundle_id"),
                        "idempotency_key": old_entry.get("idempotency_key"),
                        "receipt_relative": str(old_entry["receipt_relative"]),
                        "receipt_sha256": sha256_file(old_receipt_path),
                    }
            except (OSError, ValueError, KeyError, TypeError) as exc:
                raise StoreError("bundle_latest.json corrupt") from exc

    results: dict[str, StageSourceResult] = {}
    for market in expected_markets:
        universe = universes[market]
        if market == "A_SHARE":
            if historical_backfill or len(universe.codes) > _FUTU_SUBSCRIPTION_LIMIT:
                # Explicitly authorized historical recovery bypasses the live
                # Futu subscription quota.  Large live A-share universes use
                # the same dynamic-HQ path so a 100-symbol Futu subscription
                # cap cannot make the scheduled stage deterministically
                # incomplete.  The collector derives SH/SZ/BJ market IDs per
                # code and preserves authoritative universe order.
                results[market] = pytdx_hq_collector(
                    python_path,
                    trade_date,
                    stage_id,
                    list(universe.codes),
                    market=market,
                    process_runner=subprocess.run,
                    timeout_seconds=_MARKET_TIMEOUTS[market],
                )
            else:
                futu_codes = tuple(code for code in universe.codes if code.startswith(("SH.", "SZ.")))
                bj_codes = tuple(code for code in universe.codes if code.startswith("BJ."))
                components: list[tuple[tuple[str, ...], StageSourceResult]] = []
                if futu_codes:
                    components.append((futu_codes, futu_collector(
                        python_path,
                        trade_date,
                        stage_id,
                        list(futu_codes),
                        market=market,
                        process_runner=subprocess.run,
                        timeout_seconds=_MARKET_TIMEOUTS[market],
                    )))
                if bj_codes:
                    components.append((bj_codes, pytdx_hq_collector(
                        python_path,
                        trade_date,
                        stage_id,
                        list(bj_codes),
                        market=market,
                        process_runner=subprocess.run,
                        timeout_seconds=_MARKET_TIMEOUTS[market],
                    )))
                results[market] = _merge_a_share_results(universe.codes, components)
        else:
            collector = (
                pytdx_collector
                if market == "HK_CONNECT" and len(universe.codes) > _FUTU_SUBSCRIPTION_LIMIT
                else futu_collector
            )
            results[market] = collector(
                python_path,
                trade_date,
                stage_id,
                list(universe.codes),
                market=market,
                process_runner=subprocess.run,
                timeout_seconds=_MARKET_TIMEOUTS[market],
            )
        if market == "HK_CONNECT":
            results[market] = _enrich_hk_names(store_root, results[market])

    incomplete = [
        market for market in expected_markets
        if not _complete_result(results[market], universes[market].codes)
    ]
    if incomplete:
        markets = {
            market: {
                **_market_evidence(market, stage_id, universes[market], results[market]),
            }
            for market in expected_markets
        }
        error = "incomplete shared markets: " + ",".join(incomplete)
        receipt = publish_bundle_receipt(
            store_root,
            trade_date=trade_date,
            stage_id=stage_id,
            status="FAILED",
            markets=markets,
            error=error,
        )
        return {**receipt, "ok": False, "error": error, "markets": markets}

    persisted: dict[str, dict[str, Any]] = {}
    for market in expected_markets:
        persisted[market] = persist_stage_result(
            store_root,
            trade_date,
            stage_id,
            results[market],
            market=market,
            historical_backfill=historical_backfill,
            expected_previous=previous_components.get(market),
        )
        persisted[market]["role"] = market_role(market, stage_id)

    markets = {
        market: _market_evidence(
            market, stage_id, universes[market], results[market], persisted[market]
        )
        for market in expected_markets
    }
    receipt = publish_bundle_receipt(
        store_root,
        trade_date=trade_date,
        stage_id=stage_id,
        status="READY",
        markets=markets,
        historical_backfill=historical_backfill,
        expected_previous=previous_bundle,
    )
    return {**receipt, "markets": markets}


def _parse_args(argv: list[str]) -> dict[str, Any]:
    args: dict[str, Any] = {
        "trade_date": None,
        "stage_id": None,
        "dry_run": False,
        "historical_backfill": False,
    }
    value_options = {"--trade-date": "trade_date", "--stage-id": "stage_id"}
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == "--dry-run":
            args["dry_run"] = True
            index += 1
            continue
        if token == "--historical-backfill":
            args["historical_backfill"] = True
            index += 1
            continue
        key = value_options.get(token)
        if key is None:
            raise ValueError(f"unknown option or argument {token!r}")
        if index + 1 >= len(argv):
            raise ValueError(f"option {token} requires a value")
        args[key] = argv[index + 1]
        index += 2
    missing = [option for option, key in value_options.items() if args[key] is None]
    if missing:
        raise ValueError(f"missing required options: {', '.join(missing)}")
    return args


def main(argv: list[str], *, env: dict[str, str] | None = None,
         futu_collector: Callable[..., StageSourceResult] = collect_futu_minute) -> dict[str, Any]:
    env = os.environ if env is None else env
    try:
        args = _parse_args(argv)
        raw_store_root = str(env.get(_STORE_ROOT_ENV, "") or "").strip()
        store_root = Path(raw_store_root) if raw_store_root else _DEFAULT_STORE_ROOT
        return run_stage_bundle(
            store_root,
            args["trade_date"],
            args["stage_id"],
            resolve_futu_python(env),
            dry_run=bool(args["dry_run"]),
            historical_backfill=bool(args["historical_backfill"]),
            futu_collector=futu_collector,
        )
    except (ValueError, StoreError, OSError) as exc:
        return {"ok": False, "status": "FAILED", "error": str(exc)}


def _serializable(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
        return dataclasses.asdict(value)
    if isinstance(value, dict):
        return {key: _serializable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serializable(item) for item in value]
    return value


if __name__ == "__main__":
    outcome = main(sys.argv[1:])
    print(json.dumps(_serializable(outcome), ensure_ascii=False))
    sys.exit(0 if outcome.get("ok") else 1)
