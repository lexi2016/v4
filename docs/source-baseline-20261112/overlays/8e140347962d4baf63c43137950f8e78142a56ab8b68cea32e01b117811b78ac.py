"""Read-only projection of stage selection payloads.

Extracted from ``create_app`` so the projection rules can be read, tested and
reused without the application assembly around them. The context carries the
resolved data roots; the module holds no process state.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from contracts.stages import FROZEN_STAGE_IDS, STAGE_DEFINITIONS


@dataclass(frozen=True)
class ProjectionContext:
    store: Any
    configured_selection_root: Path | None
    configured_pool_source: Any
    resolved_pool_source: Path
    configured_morning_news_root: Path | None
    morning_history_observation: Callable[..., Any]
    morning_selection_recovery_bindings: Mapping[Any, Any]


def _stage_projection_status(ctx: ProjectionContext,
    markets: Mapping[str, Mapping[str, Any]],
    fallback: Any,
) -> str:
    """Reduce market statuses without hiding a lane-level evidence gap."""
    statuses = {str(item.get("status") or "CANNOT_CONFIRM") for item in markets.values()}
    has_rows = any(int(item.get("selected_rows") or item.get("candidate_count") or 0) > 0 for item in markets.values())
    if not statuses:
        return str(fallback or "CANNOT_CONFIRM")
    if statuses == {"READY"}:
        return "READY"
    if statuses == {"READY_EMPTY"}:
        return "READY_EMPTY"
    if "CANNOT_CONFIRM" in statuses:
        return "PARTIAL_WITH_ROWS" if has_rows else "CANNOT_CONFIRM"
    if "PARTIAL_WITH_ROWS" in statuses or str(fallback) == "PARTIAL_WITH_ROWS":
        return "PARTIAL_WITH_ROWS"
    return str(fallback or "PARTIAL_WITH_ROWS")

def _legacy_hk_consumer_rows_match(ctx: ProjectionContext, rows: list[dict], bound_rows: Any) -> bool:
    """Allow only the existing consumer's exact positional order projection."""
    if not isinstance(bound_rows, list) or len(rows) != len(bound_rows):
        return False
    for position, (row, original) in enumerate(zip(rows, bound_rows), 1):
        if not isinstance(row, dict) or not isinstance(original, dict):
            return False
        if type(row.get("order")) is not int or row["order"] != position:
            return False
        if "order" in original:
            if type(original["order"]) is not int or original["order"] != position or row != original:
                return False
        elif {key: value for key, value in row.items() if key != "order"} != original:
            return False
    return True

def _legacy_hk_pit_observation(ctx: ProjectionContext,
    market_payload: Mapping[str, Any], rows: list[dict], *, trade_date: str, stage_id: str,
) -> bool:
    """Read-only compatibility for R1's PIT-only raw-status regression."""
    if (ctx.configured_selection_root is None
            or stage_id not in {"STAGE_1300_1315", "STAGE_1445_1500"}
            or market_payload.get("status") != "PARTIAL_WITH_ROWS"
            or market_payload.get("selection_status") != "PARTIAL_WITH_ROWS"
            or market_payload.get("source_status") != "CANNOT_CONFIRM"
            or market_payload.get("cannot_confirm") != ["HK_FUTU_CAPTURE_NOT_BEFORE_STAGE_CUTOFF"]
            or market_payload.get("requested_rows") != 100
            or market_payload.get("source_rows") != 100
            or market_payload.get("selected_rows") != 10 or len(rows) != 10
            or market_payload.get("missing_symbols")):
        return False
    try:
        from infrastructure.owned_io import SafeRoot
        from stage_center.selection import SelectionStore
        from ops.verify_stage_execution import validate_execution_inputs
        selection_root = Path(ctx.configured_selection_root).resolve(strict=True)
        stage_root = selection_root.parent
        bound = SelectionStore(selection_root).read_verified(trade_date, stage_id, "HK_CONNECT")
        if any(market_payload.get(key) != bound.get(key) for key in (
                "artifact_id", "run_id", "raw_artifact_sha256", "source_status", "selection_status",
                "source_rows", "requested_rows", "selected_rows", "source_evidence", "cannot_confirm")):
            return False
        if not _legacy_hk_consumer_rows_match(ctx, rows, bound.get("rows")):
            return False
        receipt_raw = SafeRoot(stage_root / "receipts").read_bytes(
            f"{trade_date}/{stage_id}/receipt.json", max_bytes=16 * 1024 * 1024)
        inputs = validate_execution_inputs(
            trade_date=trade_date, stage_id=stage_id, receipt_root=stage_root / "receipts",
            raw_root=stage_root / "raw", selection_root=selection_root,
            expected_receipt_sha256=hashlib.sha256(receipt_raw).hexdigest(),
            hk_d1_root=ctx.store.root,
            preselection_source_root=ctx.resolved_pool_source if ctx.configured_pool_source else None,
            hk_second_filter_root=ctx.store.root / "opening_second_filter",
            shared_research_root=Path(ctx.configured_morning_news_root) if ctx.configured_morning_news_root else None,
        )
        return bool(inputs["raw_artifact"]["sha256"] == market_payload["raw_artifact_sha256"]
                    and inputs["source_reconciliation"]["raw_rows"] == 100
                    and inputs["source_reconciliation"]["selected_rows"] == 10
                    and inputs["source_time_facts"]["pit_status"] == "CANNOT_CONFIRM")
    except Exception:
        return False

def _hk_morning_selection_recovery_observation(ctx: ProjectionContext,
    market_payload: Mapping[str, Any],
    rows: list[dict],
    *,
    trade_date: str,
    stage_id: str,
) -> bool:
    binding = ctx.morning_selection_recovery_bindings.get(
        (trade_date, stage_id)
    )
    if binding is None:
        return False
    evidence = market_payload.get("source_evidence")
    if not isinstance(evidence, (list, tuple)) or any(
        not isinstance(item, str) for item in evidence
    ):
        return False
    if hashlib.sha256("\n".join(evidence).encode("utf-8")).hexdigest() != binding[
        "source_evidence_sha256"
    ]:
        return False
    if (
        market_payload.get("market") != "HK_CONNECT"
        or market_payload.get("status") != "PARTIAL_WITH_ROWS"
        or market_payload.get("selection_status") != "PARTIAL_WITH_ROWS"
        or market_payload.get("source_status") != "CANNOT_CONFIRM"
        or market_payload.get("run_id") != binding["selection_run_id"]
        or market_payload.get("artifact_id") != binding["artifact_id"]
        or market_payload.get("raw_artifact_sha256") != binding["raw_artifact_sha256"]
        or market_payload.get("algorithm_id") != binding["algorithm_id"]
        or market_payload.get("algorithm_sha256") != binding["algorithm_sha256"]
        or market_payload.get("requested_rows") != 100
        or market_payload.get("source_rows") != 100
        or market_payload.get("selected_rows") != 10
        or market_payload.get("missing_symbols")
        or market_payload.get("cannot_confirm") != ["HK_ACTIVE_SNAPSHOT_UNAVAILABLE"]
        or market_payload.get("backfill_run_id") != binding["backfill_run_id"]
        or market_payload.get("selection_manifest_sha256") != binding["selection_manifest_sha256"]
        or market_payload.get("selection_receipt_sha256") != binding["selection_receipt_sha256"]
        or market_payload.get("selection_artifact_sha256") != binding["selection_artifact_sha256"]
        or market_payload.get("runner_receipt_sha256") != binding["runner_receipt_sha256"]
        or market_payload.get("selection_manifest_receipt_verified") is not True
        or market_payload.get("runner_receipt_verified") is not True
        or len(rows) != 10
        or any(
            marker not in evidence
            for marker in binding["required_evidence"]
        )
    ):
        return False
    seen_codes: set[str] = set()
    seen_ranks: set[int] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            return False
        code = str(row.get("code") or "")
        rank = row.get("rank")
        if (
            not code
            or code in seen_codes
            or isinstance(rank, bool)
            or not isinstance(rank, int)
            or rank <= 0
            or rank in seen_ranks
            or row.get("formal_eligible") is not False
            or row.get("action_level") != "NO_BUY"
            or row.get("trade_status") not in {"NO_TRADE", "WATCH_ONLY"}
            or row.get("status") != row.get("trade_status")
            or row.get("source_mode") != "HK_CONNECT_FOUR_LANE"
        ):
            return False
        seen_codes.add(code)
        seen_ranks.add(rank)
    return "HK_ACTIVE_SNAPSHOT_UNAVAILABLE" in evidence

def _hk_display_mode(ctx: ProjectionContext,
    market_payload: Mapping[str, Any],
    rows: list[dict],
    execution_market: Mapping[str, Any] | None,
    *,
    legacy_pit_observation: bool = False,
    morning_selection_recovery: bool = False,
) -> tuple[str, list[str]]:
    """Only call HK rows formal after selection and execution binding agree."""
    status = str(market_payload.get("status") or "CANNOT_CONFIRM")
    selection_status = str(market_payload.get("selection_status") or status)
    reasons = [str(item) for item in market_payload.get("cannot_confirm") or []]
    # Display PIT qualifiers without turning valid partial rows into data errors.
    reasons.extend(item.split("=", 1)[1] for item in market_payload.get("source_evidence") or []
                   if isinstance(item, str) and item.startswith("futu_pit_cannot_confirm=")
                   and item.split("=", 1)[1] in {
                       "HK_FUTU_CAPTURE_NOT_BEFORE_STAGE_CUTOFF", "HK_FUTU_FULL_CHAIN_PIT_UNVERIFIED",
                       "HK_FUTU_CAPTURE_CLOCK_UNAVAILABLE", "HK_FUTU_CAPTURE_CLOCK_DATE_MISMATCH"})
    identity_present = all(
        isinstance(market_payload.get(field), str) and market_payload.get(field)
        for field in ("artifact_id", "run_id", "raw_artifact_sha256")
    )
    requested_rows = market_payload.get("requested_rows")
    source_rows = market_payload.get("source_rows")
    selected_rows = market_payload.get("selected_rows")
    source_evidence = market_payload.get("source_evidence")
    complete_empty_evidence = (
        isinstance(requested_rows, int)
        and not isinstance(requested_rows, bool)
        and requested_rows >= 0
        and isinstance(source_rows, int)
        and not isinstance(source_rows, bool)
        and source_rows == requested_rows
        and isinstance(selected_rows, int)
        and not isinstance(selected_rows, bool)
        and selected_rows == 0
        and market_payload.get("source_status") in {"READY", "READY_EMPTY"}
        and isinstance(source_evidence, (list, tuple))
        and any(isinstance(item, str) and item.strip() for item in source_evidence)
        and not market_payload.get("missing_symbols")
        and not market_payload.get("cannot_confirm")
    )
    verified_empty = (
        status == "READY_EMPTY"
        and selection_status == "READY_EMPTY"
        and market_payload.get("source_status") in {"READY", "READY_EMPTY"}
        and identity_present
        and not rows
        and complete_empty_evidence
        and not reasons
    )
    if verified_empty:
        return "READY_EMPTY", []

    if status == "READY_EMPTY":
        if not complete_empty_evidence:
            reasons.append("HK_READY_EMPTY_INPUT_OR_SOURCE_EVIDENCE_INCOMPLETE")
        if market_payload.get("source_status") not in {"READY", "READY_EMPTY"}:
            reasons.append("HK_READY_EMPTY_SOURCE_STATUS_NOT_READY")
        if selection_status != "READY_EMPTY":
            reasons.append("HK_READY_EMPTY_SELECTION_STATUS_MISMATCH")
        if not identity_present:
            reasons.append("SELECTION_ARTIFACT_MISSING_OR_INVALID")
        return "CANNOT_CONFIRM", list(dict.fromkeys(reasons))

    if status == "CANNOT_CONFIRM" or not identity_present:
        if not reasons:
            reasons.append("SELECTION_ARTIFACT_MISSING_OR_INVALID")
        return "CANNOT_CONFIRM", reasons

    if (
        status not in {"READY", "PARTIAL_WITH_ROWS"}
        or selection_status not in {"READY", "PARTIAL_WITH_ROWS"}
        or (market_payload.get("source_status") not in {"READY", "PARTIAL_WITH_ROWS"}
            and not legacy_pit_observation
            and not morning_selection_recovery)
    ):
        reasons.append("HK_SELECTION_OR_SOURCE_STATUS_NOT_READY")
        return "CANNOT_CONFIRM", list(dict.fromkeys(reasons))

    if legacy_pit_observation:
        return "OBSERVATION_UNVERIFIED", list(dict.fromkeys(reasons + [
            "HK_LEGACY_PIT_ONLY_OBSERVATION_INPUTS_REVALIDATED",
            "HK_FULL_CHAIN_PIT_AND_FORMAL_ELIGIBILITY_CANNOT_CONFIRM",
        ]))

    if morning_selection_recovery:
        return "OBSERVATION_UNVERIFIED", list(dict.fromkeys(reasons + [
            "HK_MORNING_SELECTION_OBSERVATION_REPROJECTED",
            "HK_CAPTURE_AFTER_STAGE_CUTOFF_PIT_UNSAFE",
            "HK_FORMAL_STAGE_ELIGIBILITY_CANNOT_CONFIRM",
            "HK_NATURAL_TIME_CAPTURE_CANNOT_CONFIRM",
        ]))

    execution = execution_market if isinstance(execution_market, Mapping) else {}
    binding = execution.get("selection_binding")
    unsafe_rows = any(
        isinstance(row, Mapping) and row.get("formal_eligible") is False
        for row in rows
    )
    selection_ready = (
        status == "READY"
        and selection_status == "READY"
        and not reasons
    )
    execution_bound = binding == "BOUND_TO_VERIFIED_SELECTION"
    if selection_ready and execution_bound and rows and not unsafe_rows:
        return "FORMAL", []

    if selection_ready and not rows:
        reasons.append("HK_READY_SELECTION_HAS_NO_ROWS")

    if unsafe_rows:
        reasons.append("HK_FORMAL_ELIGIBILITY_FALSE")
    if not execution_bound:
        execution_reasons = execution.get("reasons")
        reasons.extend(str(item) for item in execution_reasons or [])
        reasons.append(f"HK_EXECUTION_SELECTION_BINDING_{binding or 'CANNOT_CONFIRM'}")
    if not selection_ready:
        reasons.append(f"HK_SELECTION_STATUS_{status}")
    return ("OBSERVATION_UNVERIFIED" if rows else "CANNOT_CONFIRM"), list(dict.fromkeys(reasons))

def project_shared_selection(ctx: ProjectionContext,
    payload: dict,
    limit: int = 50,
    *,
    ordinary_hk_display: bool = False,
) -> dict:
    source_failure = None
    if payload.get("stage_id") == "STAGE_0925":
        try:
            from infrastructure.runtime_graph.current import load_config
            from stage_center.consumer import read_a_opening_source_failure
            config = load_config()
            if Path(config["stage_selection_root"]) == ctx.configured_selection_root:
                source_failure = read_a_opening_source_failure(
                    payload, config=config,
                )
        except (OSError, ValueError, KeyError, TypeError):
            pass  # Unbound/missing evidence retains the original unknown.
    canonical_markets = dict(payload.get("markets", {}))
    hk_unknown = canonical_markets.get("HK_CONNECT")
    if isinstance(hk_unknown, Mapping) and (
        all(hk_unknown.get(key) == "CANNOT_CONFIRM"
            for key in ("status", "selection_status", "source_status"))
        and all(hk_unknown.get(key) is None for key in
                ("requested_rows", "source_rows", "selected_rows", "artifact_id", "run_id"))
        and hk_unknown.get("rows") == []
        and isinstance(hk_unknown.get("cannot_confirm"), list)
        and hk_unknown.get("selection_manifest_receipt_verified") in (None, False)
    ):
        from stage_center.consumer import _invalid_market
        hk_unknown = dict(hk_unknown)
        standard = _invalid_market("HK_CONNECT")["cannot_confirm"]
        causes = hk_unknown["cannot_confirm"]
        hk_unknown["cannot_confirm"] = [reason for reason in standard if reason not in causes] + causes
        hk_unknown["selection_manifest_receipt_verified"] = False
        canonical_markets["HK_CONNECT"] = hk_unknown
    selection_markets = canonical_markets
    frontend_markets: dict[str, dict] = {}
    unified_rows: list[dict] = []
    aliases = {"A_SHARE": "A", "HK_CONNECT": "HK"}
    execution_markets = (
        (payload.get("execution_evidence") or {}).get("markets") or {}
    )
    backfill_provenance_fields = frozenset(
        {
            "selection_mode",
            "selection_run_id",
            "backfill_run_id",
            "backfill_run_ids",
            "selection_manifest_sha256",
            "selection_receipt_sha256",
            "selection_artifact_sha256",
            "selection_manifest_receipt_verified",
            "runner_receipt_verified",
            "runner_receipt_status",
            "runner_receipt_sha256",
            "recovery_provenance",
        }
    )
    for canonical_market, market_payload in canonical_markets.items():
        alias = aliases.get(canonical_market, canonical_market)
        rows = list(market_payload.get("rows") or [])[:limit]
        if canonical_market == "A_SHARE":
            from stage_center.news_link_projection import project_news_links
            rows = project_news_links(
                rows, market_payload, trade_date=str(payload.get("trade_date") or ""),
                morning_root=ctx.configured_morning_news_root,
            )
        projected_rows = rows
        frontend_markets[alias] = {
            key: market_payload.get(key)
            for key in (
                "market",
                "RESEARCH_ONLY",
                "status",
                "selection_status",
                "artifact_id",
                "run_id",
                "algorithm_id",
                "algorithm_sha256",
                "raw_artifact_sha256",
                "source_status",
                "requested_rows",
                "source_rows",
                "selected_rows",
                "coverage_ratio",
                "source_evidence",
                "missing_symbols",
                "cannot_confirm",
                "name_authority_status",
                "name_authority_source",
                "name_authority_receipt_sha256",
                "name_authority_selector_sha256",
                "name_authority_source_sha256",
                "name_authority_selector_sha_source",
                "name_authority_pool_ids",
                "name_authority_applied_count",
                "name_authority_missing_count",
                "name_authority_error",
                "selection_mode",
                "selection_run_id",
                "backfill_run_id",
                "backfill_run_ids",
                "selection_manifest_sha256",
                "selection_receipt_sha256",
                "selection_artifact_sha256",
                "selection_manifest_receipt_verified",
                "runner_receipt_verified",
                "runner_receipt_status",
                "runner_receipt_sha256",
                "recovery_provenance",
                "superseded_source",
                "quarantined_source",
            )
            if key not in backfill_provenance_fields or key in market_payload
        }
        frontend_markets[alias]["candidate_count"] = len(rows)
        frontend_markets[alias]["rows"] = rows
        if canonical_market == "A_SHARE" and source_failure is not None:
            frontend_markets[alias].update(source_failure)
        if canonical_market == "HK_CONNECT" and ordinary_hk_display:
            history_observation = ctx.morning_history_observation(
                ctx.configured_selection_root, ctx.resolved_pool_source, market_payload, rows,
                trade_date=str(payload.get("trade_date") or ""),
                stage_id=str(payload.get("stage_id") or ""),
            )
            if history_observation:
                rows = history_observation.pop("_rows")
                projected_rows = rows
                frontend_markets[alias].update({
                    key: history_observation[key] for key in (
                        "selection_run_id", "artifact_id", "raw_artifact_sha256",
                        "algorithm_id", "algorithm_sha256", "source_evidence")
                })
                frontend_markets[alias]["run_id"] = history_observation["selection_run_id"]
                frontend_markets[alias]["rows"] = rows
                # The original formal/source failure remains independently visible.
                frontend_markets[alias]["original_formal_selection"] = {
                    key: market_payload.get(key) for key in (
                        "run_id", "artifact_id", "status", "selection_status", "source_status",
                        "raw_artifact_sha256", "cannot_confirm")
                }
                if selection_markets is canonical_markets:
                    selection_markets = dict(canonical_markets)
                selection_markets[canonical_market] = {**market_payload, "rows": []}
            display_mode, display_reasons = _hk_display_mode(ctx,
                market_payload, rows, execution_markets.get(canonical_market),
                legacy_pit_observation=_legacy_hk_pit_observation(ctx,
                    market_payload, rows, trade_date=str(payload.get("trade_date") or ""),
                    stage_id=str(payload.get("stage_id") or "")),
                morning_selection_recovery=bool(history_observation) or _hk_morning_selection_recovery_observation(ctx,
                    market_payload,
                    rows,
                    trade_date=str(payload.get("trade_date") or ""),
                    stage_id=str(payload.get("stage_id") or ""),
                ),
            )
            if history_observation:
                frontend_markets[alias].update({
                    "historical_observation": history_observation,
                    "formal_count": 0, "formal_eligible": False, "natural": False,
                    "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
                })
                display_reasons = list(dict.fromkeys(display_reasons + [
                    history_observation["label"],
                    "来源 FUTU_K_1M；历史分钟线；原时点盘口/量比/原生更新时间缺失",
                    f"实际采集 {history_observation['captured_at']}；阶段截止 {history_observation['asof_cutoff']}",
                    f"原始bar标签 {history_observation['bar_label_start']}—{history_observation['bar_label_end']}；每只{history_observation['bars_per_code']}根×100只；已排除边界bar，仅保守交集，分钟标签语义待确认",
                ]))
            frontend_markets[alias]["display_mode"] = display_mode
            frontend_markets[alias]["display_reasons"] = display_reasons
            frontend_markets[alias]["observation_count"] = (
                len(rows) if display_mode != "CANNOT_CONFIRM" else None
            )
            if display_mode == "CANNOT_CONFIRM":
                projected_rows = []
                frontend_markets[alias]["rows"] = projected_rows
                frontend_markets[alias]["candidate_count"] = None
                frontend_markets[alias]["status"] = "CANNOT_CONFIRM"
                frontend_markets[alias]["selected_rows"] = None
                if selection_markets is canonical_markets:
                    selection_markets = dict(canonical_markets)
                selection_markets[canonical_market] = {
                    **market_payload,
                    "rows": [],
                }
            elif display_mode == "OBSERVATION_UNVERIFIED":
                # These rows have a valid selection identity and source
                # status, but remain observations because formal or
                # execution evidence is incomplete. Keep their count
                # visible without promoting their eligibility or action.
                frontend_markets[alias]["status"] = "PARTIAL_WITH_ROWS"
        for row in projected_rows:
            unified_rows.append(
                {
                    **dict(row),
                    "market": alias,
                    "symbol": row.get("code"),
                    "selection_rank": row.get("rank"),
                }
            )
    a_rows = frontend_markets.get("A", {}).get("rows", [])
    hk_rows = frontend_markets.get("HK", {}).get("rows", [])
    selected_a = len(a_rows)
    hk_display_mode = frontend_markets.get("HK", {}).get("display_mode")
    selected_hk = (
        None if hk_display_mode == "CANNOT_CONFIRM"
        else len(hk_rows)
    )
    selected_total = None if selected_hk is None else selected_a + selected_hk
    stage_id = payload.get("stage_id")
    stage_definition = STAGE_DEFINITIONS.get(stage_id, {})
    stage_status = _stage_projection_status(ctx, frontend_markets, payload.get("status", "CANNOT_CONFIRM"))
    cannot_confirm: list[str] = [str(item) for item in payload.get("cannot_confirm") or []]
    for market, market_payload in frontend_markets.items():
        market_status = str(market_payload.get("status") or "CANNOT_CONFIRM")
        reasons = list(market_payload.get("cannot_confirm") or ())
        if market == "HK":
            reasons.extend(market_payload.get("display_reasons") or ())
            reasons = list(dict.fromkeys(reasons))
        if not reasons and market_status == "CANNOT_CONFIRM":
            reasons = [f"{market}_SELECTION_CANNOT_CONFIRM"]
        # A lane can have rows and still carry a hard evidence boundary.
        # Keep every lane reason visible at the stage boundary; the
        # status reducer above deliberately remains PARTIAL_WITH_ROWS.
        for reason in reasons:
            value = f"{market}:{reason}"
            if value not in cannot_confirm:
                cannot_confirm.append(value)
    result = {
        **payload,
        "status": stage_status,
        "selection_markets": selection_markets,
        "markets": frontend_markets,
        "market_summaries": frontend_markets,
        "unified_rows": unified_rows,
        "cannot_confirm": cannot_confirm,
        "stage": {
            "stage_id": stage_id,
            "label": stage_definition.get("label", stage_id),
            "window": stage_definition.get("window", ""),
            "status": stage_status,
            "display_status": (
                stage_status + "；港股历史回放观察·未验证；分钟线事后采集；缺原时点盘口、量比/原生更新时间；边界分钟未计入；不能证明原时点选股结果"
                if frontend_markets.get("HK", {}).get("historical_observation")
                else stage_status
            ),
            "cannot_confirm": cannot_confirm,
        },
        "selected_a_rows": selected_a,
        "selected_hk_rows": selected_hk,
        "selected_total_rows": selected_total,
        "selection_mode": "SHARED_STAGE_CENTER_READ_ONLY",
        "recommendation_status": "WATCH_ONLY",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    # Current names are display evidence only.  Original news/research
    # enrichment above has already finished using its original inputs.
    from domains._preselection_parts.source_validation import project_a_display_names
    return project_a_display_names(
        result, str(payload.get("trade_date") or ""), ctx.resolved_pool_source,
    )
