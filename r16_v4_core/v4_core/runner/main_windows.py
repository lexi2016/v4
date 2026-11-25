"""Read the existing stage owner and run its V3.5 research projection in isolation."""
from __future__ import annotations

from datetime import datetime, time, timedelta
from hashlib import sha256
import json
import math
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from v4_core.runner.evidence import EvidenceError, FileEvidence, SAFETY_FLAGS, aware_time, iso_date, mapping, require, symbol
from v4_core.runner.state import publish_json
from v4_core.strategies import stage_scoring


_SHANGHAI = ZoneInfo("Asia/Shanghai")
_STAGE_MARKETS = {"A": "A_SHARE", "HK": "HK_CONNECT"}
_A_AUCTION_ROLE = "A_SHARE_AUCTION_TRANSACTION_STAGE_0925"
_HK_AUCTION_ROLE = "HK_CONNECT_AUCTION_REFERENCE_STAGE_0925"


def _read(root: Path, relative: str, expected: str | None = None) -> FileEvidence:
    path = (root / relative).resolve()
    require(path.is_relative_to(root) and not Path(relative).is_absolute(), "STAGE_OWNER_PATH_ESCAPES_ROOT")
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise EvidenceError(f"STAGE_OWNER_FILE_UNAVAILABLE:{relative}") from exc
    digest = sha256(content).hexdigest()
    require(expected is None or expected == digest, f"STAGE_OWNER_SHA_MISMATCH:{relative}")
    return FileEvidence(relative, digest, content)


def _canonical_sha(record: dict) -> str:
    return sha256(json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _safe(record: dict, reason: str) -> None:
    require(all(record.get(key) is False for key in SAFETY_FLAGS if key != "research_only"), reason)


def _raw_role(market: str, stage: str) -> str:
    if stage == "STAGE_0925":
        return _A_AUCTION_ROLE if market == "A" else _HK_AUCTION_ROLE
    return f"{_STAGE_MARKETS[market]}_1MIN_{stage}"


def _read_raw(
    root: Path, day: str, stage: str, market: str, digest: str,
) -> tuple[list[dict[str, str]], dict]:
    raw_root = (root / "raw").resolve()
    require(raw_root.is_relative_to(root), "STAGE_RAW_ROOT_ESCAPES_OWNER")
    role = _raw_role(market, stage)
    directory = Path("runs") / day.replace("-", "") / role
    candidates = []
    for path in sorted((raw_root / directory).glob("*/manifest.json")):
        candidate = _read(raw_root, path.relative_to(raw_root).as_posix())
        manifest = mapping(candidate.json(), "STAGE_RAW_MANIFEST_INVALID")
        if manifest.get("artifact_sha256") == digest:
            candidates.append((path.parent, candidate, manifest))
    require(len(candidates) == 1, "STAGE_RAW_SOURCE_UNBOUND_OR_AMBIGUOUS")
    run, manifest_file, manifest = candidates[0]
    prefix = run.relative_to(raw_root)
    artifact = _read(raw_root, str(prefix / "artifact.csv"), digest)
    receipt_file = _read(raw_root, str(prefix / "receipt.json"))
    receipt = mapping(receipt_file.json(), "STAGE_RAW_RECEIPT_INVALID")
    require(all(record.get("market") == _STAGE_MARKETS[market] and record.get("role") == role
                and record.get("stage_id") == stage and iso_date(record.get("trade_date")) == day
                and record.get("run_id") == run.name and record.get("artifact_sha256") == digest
                for record in (manifest, receipt))
            and _canonical_sha(manifest) == receipt.get("manifest_sha256"), "STAGE_RAW_SOURCE_IDENTITY_MISMATCH")
    _safe(manifest, "STAGE_RAW_MANIFEST_UNSAFE")
    _safe(receipt, "STAGE_RAW_RECEIPT_UNSAFE")
    rows = artifact.csv()
    require(manifest.get("row_count") == receipt.get("row_count") == len(rows)
            and all(iso_date(row.get("trade_date")) == day for row in rows), "STAGE_RAW_ROWS_DATE_OR_COUNT_MISMATCH")
    return rows, {
        "artifact": artifact.identity(), "manifest": manifest_file.identity(), "receipt": receipt_file.identity(),
        "run_id": run.name, "role": role, "source_id": receipt.get("source_id"),
        "row_count": len(rows), "temporal_cutoff_safe": receipt.get("temporal_cutoff_safe") is True,
        "source_status": receipt.get("source_status"), "status": receipt.get("status"),
        "cutoff_at": receipt.get("cutoff_at"), "window": receipt.get("window"),
        "requested_rows": receipt.get("requested_rows"),
    }


def _read_selection(root: Path, day: str, stage: str, market: str, binding: dict) -> tuple[list[dict], dict]:
    selection_root = (root / "selection").resolve()
    require(selection_root.is_relative_to(root), "STAGE_SELECTION_ROOT_ESCAPES_OWNER")
    parts = {}
    for key in ("artifact", "manifest", "receipt"):
        relative = binding.get(f"{key}_relative")
        digest = binding.get(f"{key}_bytes_sha256")
        require(isinstance(relative, str) and isinstance(digest, str), f"STAGE_SELECTION_{key.upper()}_UNBOUND")
        parts[key] = _read(selection_root, relative, digest)
    run_id = binding.get("run_id")
    require(isinstance(run_id, str) and Path(run_id).name == run_id, "STAGE_SELECTION_RUN_ID_UNBOUND")
    prefix = Path("selection_runs") / day.replace("-", "") / f"{_STAGE_MARKETS[market]}_SELECTION_{stage}" / run_id
    require(all(value.path == (prefix / filename).as_posix() for value, filename in zip(
        parts.values(), ("artifact.csv", "manifest.json", "receipt.json"), strict=True,
    )), "STAGE_SELECTION_PATH_ROLE_MISMATCH")
    raw_sha = binding.get("raw_artifact_sha256")
    require(isinstance(raw_sha, str) and len(raw_sha) == 64, "STAGE_SELECTION_RAW_SHA_UNBOUND")
    manifest = mapping(parts["manifest"].json(), "STAGE_SELECTION_MANIFEST_INVALID")
    receipt = mapping(parts["receipt"].json(), "STAGE_SELECTION_RECEIPT_INVALID")
    envelope = mapping(manifest.get("selection_envelope"), "STAGE_SELECTION_ENVELOPE_INVALID")
    owner_market = _STAGE_MARKETS[market]
    for record in (manifest, receipt, envelope):
        require(record.get("market") == owner_market and record.get("stage_id") == stage
                and iso_date(record.get("trade_date")) == day and record.get("run_id") == binding.get("run_id")
                and record.get("algorithm_sha256") == binding.get("algorithm_sha256")
                and record.get("raw_artifact_sha256") == raw_sha, "STAGE_SELECTION_IDENTITY_MISMATCH")
        _safe(record, "STAGE_SELECTION_UNSAFE")
    require(manifest.get("artifact_sha256") == receipt.get("artifact_sha256") == parts["artifact"].sha256
            and receipt.get("manifest_sha256") == binding.get("manifest_canonical_sha256") == _canonical_sha(manifest)
            and binding.get("receipt_canonical_sha256") == _canonical_sha(receipt)
            and binding.get("artifact_id") == envelope.get("artifact_id"),
            "STAGE_SELECTION_ARTIFACT_OR_MANIFEST_MISMATCH")
    csv_rows = parts["artifact"].csv()
    require(binding.get("selected_rows") == envelope.get("selected_rows") == manifest.get("row_count") == len(csv_rows),
            "STAGE_SELECTION_ROW_COUNT_MISMATCH")
    rows = []
    for position, row in enumerate(csv_rows, 1):
        ticker = _stage_symbol(row.get("code"), market)
        try:
            rank, score = int(row.get("rank", "")), float(row.get("score", ""))
        except ValueError as exc:
            raise EvidenceError("STAGE_SELECTION_RANK_OR_SCORE_INVALID") from exc
        require(position == rank and math.isfinite(score), "STAGE_SELECTION_RANK_OR_SCORE_INVALID")
        rows.append({
            "symbol": ticker, "rank": rank, "stage_score": score, "owner_selection_status": row.get("status"),
            "recommendation_status": "WATCH_ONLY", "tradable": False, **SAFETY_FLAGS,
        })
    require(len({row["symbol"] for row in rows}) == len(rows), "STAGE_SELECTION_DUPLICATES")
    return rows, {
        **{key: part.identity() for key, part in parts.items()},
        "raw_artifact_sha256": raw_sha, "run_id": binding.get("run_id"),
        "algorithm_sha256": binding.get("algorithm_sha256"), "artifact_id": binding.get("artifact_id"),
        "manifest_canonical_sha256": _canonical_sha(manifest), "receipt_canonical_sha256": _canonical_sha(receipt),
        "status": envelope.get("selection_status"), "source_rows": envelope.get("source_rows"),
        "source_status": envelope.get("source_status"), "owner_schema": envelope.get("schema_version"),
        "gap_count": len(envelope.get("cannot_confirm") or []),
        "cannot_confirm": list(envelope.get("cannot_confirm") or [])[:8],
    }


def _stage_symbol(value: Any, market: str) -> str:
    if market == "A" and isinstance(value, str) and value.startswith("A.") and value[2:].isdigit():
        code = value[2:]
        exchange = "SH" if code.startswith("6") else "BJ" if code.startswith(("4", "8", "9")) else "SZ"
        value = f"{code}.{exchange}"
    return symbol(value, market)


def _price(value: Any) -> float | None:
    try:
        price = float(value)
    except (ValueError, TypeError):
        return None
    return price if math.isfinite(price) and price > 0 else None


def _strategy_projection(raw: list[dict], market: str, stage: str) -> tuple[list[dict], set[str]]:
    """Apply the already shipped V3.5 WATCH_ONLY scoring to verified raw input."""
    candidates = {}
    for row in raw:
        code = _stage_symbol(row.get("code"), market)
        last, opening, previous = (_price(row.get(key)) for key in ("last_price", "open_price", "prev_close_price"))
        if last is None or opening is None or (stage == "STAGE_0925" and previous is None):
            continue
        high, low = (_price(row.get(key)) for key in ("high_price", "low_price"))
        turnover = _price(row.get("turnover"))
        score_input = {
            "symbol": code, "name": row.get("name"), "last_price": last, "open_price": opening,
            "prev_close_price": previous, "high_price": high, "low_price": low, "turnover": turnover,
            "bid_vol1": _price(row.get("bid_vol")), "ask_vol1": _price(row.get("ask_vol")),
            "stage_window_complete": str(row.get("temporal_cutoff_safe", "")).lower() in {"1", "true"},
            "pct_chg": (last / previous - 1) * 100 if previous is not None else None,
            "stage_window_change_pct": (last / opening - 1) * 100,
            "turnover_hkd_yi": turnover / 1e8 if turnover is not None else None,
            "stage_close_position": (last - low) / (high - low) if high and low and high > low else None,
        }
        require(code not in candidates, "STAGE_RAW_DUPLICATE_SYMBOL")
        candidates[code] = score_input
    source = [candidates[code] for code in sorted(candidates)]
    ranked = (stage_scoring.rank_a_stage_rows(source, stage, limit=50) if market == "A"
              else stage_scoring.rank_hk_stage_rows(source, limit=10))
    score_key = "stage_score" if market == "A" else "stage_rtdata_score"
    return [{
        "market": market, "symbol": row["symbol"], "name": row.get("name"), "rank": int(row["stage_rank"]),
        "stage_score": row[score_key], "recommendation_status": "WATCH_ONLY", "tradable": False, **SAFETY_FLAGS,
    } for row in ranked], set(candidates)


def _expected_window(stage: str, market: str) -> tuple[time, time]:
    if stage == "STAGE_0925":
        start, end = ("09:20", "09:25") if market == "A" else ("09:15", "09:20")
    else:
        start, end = (f"{part[:2]}:{part[2:]}" for part in stage.removeprefix("STAGE_").split("_"))
    return time.fromisoformat(start), time.fromisoformat(end)


def _raw_cutoff_verified(rows: list[dict], source: dict, day: str, stage: str, market: str) -> bool:
    start, end = _expected_window(stage, market)
    if source.get("window") != f"{start:%H:%M}-{end:%H:%M}":
        return False
    try:
        cutoff = time.fromisoformat(source.get("cutoff_at"))
        drift = datetime.combine(datetime.fromisoformat(day), cutoff) - datetime.combine(datetime.fromisoformat(day), end)
        if not timedelta(0) <= drift <= timedelta(seconds=5):
            return False
        for row in rows:
            bar_time = time.fromisoformat(str(row.get("bar_time")))
            update = datetime.fromisoformat(str(row.get("update_time")))
            if update.utcoffset() is not None:
                update = update.astimezone(_SHANGHAI)
            if (not start <= bar_time <= cutoff or update.date().isoformat() != day
                    or not start <= update.time() <= cutoff
                    or str(row.get("temporal_cutoff_safe")).lower() not in {"true", "1"}):
                return False
    except (TypeError, ValueError):
        return False
    return bool(rows) and source["temporal_cutoff_safe"]


def _materialize_market(
    root: Path, day: str, stage: str, market: str, owner: dict, *, isolated: set[str] | None = None,
) -> dict:
    bindings = mapping(owner.get("selection_artifacts"), "STAGE_OWNER_SELECTION_INDEX_MISSING")
    binding = mapping(bindings.get(_STAGE_MARKETS[market]), "STAGE_OWNER_MARKET_SELECTION_UNBOUND")
    selected, selection = _read_selection(root, day, stage, market, binding)
    raw, source = _read_raw(root, day, stage, market, selection["raw_artifact_sha256"])
    codes = {_stage_symbol(row.get("code"), market) for row in raw}
    require(all(row["symbol"] in codes for row in selected), "STAGE_SELECTION_SYMBOL_NOT_IN_RAW_SOURCE")
    exclude = isolated or set()
    isolated_codes = sorted(codes & exclude)
    eligible_raw = [row for row in raw if _stage_symbol(row.get("code"), market) not in exclude]
    selected = [row for row in selected if row["symbol"] not in exclude]
    ranked, admitted = _strategy_projection(eligible_raw, market, stage)
    timed = _raw_cutoff_verified(raw, source, day, stage, market)
    covered = (type(source.get("requested_rows")) is int and source["requested_rows"] == len(raw)
               and selection["source_rows"] == len(raw))
    ready = (timed and covered and source["source_status"] == "READY" and source["status"] == "READY"
             and selection["status"] == selection["source_status"] == "READY" and selected and ranked
             and all(row["symbol"] in admitted for row in selected) and len(admitted) == len(eligible_raw))
    gaps = []
    if not timed:
        gaps.append("STAGE_RAW_TEMPORAL_CUTOFF_UNVERIFIED")
    if not covered:
        gaps.append("STAGE_RAW_COVERAGE_OR_SELECTION_COUNTS_UNVERIFIED")
    if not ready:
        gaps.append("STAGE_OWNER_INPUT_OR_SELECTION_PARTIAL")
    if len(admitted) < len(eligible_raw):
        gaps.append("STAGE_WATCH_REQUIRED_FIELDS_MISSING")
    if not selected or not ranked:
        gaps.append("STAGE_NO_ADMITTED_SELECTION_OR_WATCH_ROWS")
    return {
        "status": "READY" if ready else "PARTIAL" if selected or ranked else "CANNOT_CONFIRM",
        "source": source, "owner_selection": selection, "owner_rows": selected, "watch_rows": ranked,
        "owner_row_count": len(selected), "watch_row_count": len(ranked), "watch_input_rows": len(admitted),
        "isolated_symbols": isolated_codes,
        "cannot_confirm": gaps, **SAFETY_FLAGS,
    }


def observe_stage_receipt(root: Path, start: datetime, stage: str, asof: datetime) -> tuple[FileEvidence, dict]:
    root = root.resolve()
    day = start.date().isoformat()
    evidence = _read(root, f"receipts/{start:%Y%m%d}/{stage}/receipt.json")
    owner = mapping(evidence.json(), "STAGE_OWNER_RECEIPT_INVALID")
    require(owner.get("schema_version") == "stage_center.runner.receipt.v1"
            and iso_date(owner.get("trade_date")) == day and owner.get("stage_id") == stage
            and owner.get("runner") == "stage_center" and owner.get("dispatch_mode") == "NATURAL"
            and owner.get("due_status") == "DUE" and owner.get("write_performed") is True,
            "STAGE_OWNER_RECEIPT_NOT_NATURAL_OR_BINDING_MISMATCH")
    _safe(owner, "STAGE_OWNER_RECEIPT_UNSAFE")
    when = aware_time(owner.get("recorded_at"))
    require(start <= when <= min(asof, start + timedelta(minutes=3)), "STAGE_OWNER_RECEIPT_OUTSIDE_READBACK")
    return evidence, owner


def read_hk_selection_pit(root: Path, start: datetime, stage: str, asof: datetime, claim: dict) -> tuple[dict, list[dict]]:
    """Bind the close review claim to the natural runner, raw inputs and actual selection files."""
    root = root.resolve()
    runner_file, runner = observe_stage_receipt(root, start, stage, asof)
    result = _materialize_market(root, start.date().isoformat(), stage, "HK", runner)
    selection = result["owner_selection"]
    require(result["status"] == "READY" and claim.get("selection_manifest_receipt_verified") is True
            and claim.get("selection_mode") in (None, "NATURAL") and not claim.get("backfill_run_id")
            and not claim.get("backfill_run_ids") and not claim.get("cannot_confirm")
            and claim.get("review_evidence_status", claim.get("status")) == "READY"
            and claim.get("selection_artifact_sha256") == selection["artifact"]["sha256"]
            and claim.get("selection_manifest_sha256") == selection["manifest_canonical_sha256"]
            and claim.get("selection_receipt_sha256") == selection["receipt_canonical_sha256"]
            and claim.get("artifact_id") == selection["artifact_id"] and claim.get("run_id") == selection["run_id"]
            and claim.get("runner_receipt_sha256") in (None, runner_file.sha256)
            and claim.get("row_count") == result["owner_row_count"]
            and claim.get("source_rows") == result["source"]["row_count"],
            "HK_CLOSE_STAGE_ACTUAL_SELECTION_OR_RUNNER_PROOF_UNVERIFIED")
    return {
        "status": "READY", "runner_receipt": runner_file.identity(), "runner_recorded_at": runner["recorded_at"],
        "raw": result["source"], "selection": selection, "selected_rows": result["owner_row_count"],
    }, result["owner_rows"]


def materialize_stage_window(
    data_dir: Path, root: Path, start: datetime, stage: str, asof: datetime, *, isolated_a: set[str] | None = None,
) -> dict:
    day = start.date().isoformat()
    root = root.resolve()
    markets = ("HK",) if stage == "STAGE_1545_1555" else ("A", "HK")
    market_results: dict[str, dict] = {}
    owner_identity = {}
    try:
        owner_file, owner = observe_stage_receipt(root, start, stage, asof)
        owner_identity = owner_file.identity()
    except EvidenceError as exc:
        market_results.update({market: {"status": "CANNOT_CONFIRM", "cannot_confirm": [str(exc)]} for market in markets})
    else:
        for market in markets:
            try:
                market_results[market] = _materialize_market(
                    root, day, stage, market, owner, isolated=isolated_a if market == "A" else None,
                )
            except EvidenceError as exc:
                market_results[market] = {"status": "CANNOT_CONFIRM", "cannot_confirm": [str(exc)]}
    statuses = {result["status"] for result in market_results.values()}
    status = "READY" if statuses == {"READY"} else "CANNOT_CONFIRM" if statuses == {"CANNOT_CONFIRM"} else "PARTIAL"
    path = data_dir / "main_windows" / day / f"{stage}.json"
    output = {
        "schema": "v4_core.main_window.v1", "trade_date": day, "stage_id": stage,
        "scheduled_for": start.isoformat(), "observed_through": asof.isoformat(), "status": status,
        "source_owner_root": str(root), "owner_receipt": owner_identity, "market_results": market_results,
        "watch_strategy": "V35_WATCH_ONLY_STAGE_SCORING",
        "watch_strategy_sha256": sha256(Path(stage_scoring.__file__).read_bytes()).hexdigest(), **SAFETY_FLAGS,
    }
    digest = publish_json(path, output)
    return {
        "trade_date": day, "stage_id": stage, "status": status, "artifact": str(path), "artifact_sha256": digest,
        "owner_receipt": owner_identity,
        "markets": {market: {key: result[key] for key in (
            "status", "cannot_confirm", "owner_row_count", "watch_row_count", "isolated_symbols",
        ) if key in result} for market, result in market_results.items()},
        **SAFETY_FLAGS,
    }
