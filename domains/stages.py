"""Native eight-stage orchestration with frozen V3 scoring behavior."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable, Mapping, Protocol

from contracts.stages import STAGE_CONTRACT_VERSION, STAGE_DEFINITIONS
from domains.opening_second_filter import apply_a_share_v11_adapter
from domains.stage_scoring import rank_a_stage_rows, rank_hk_stage_rows
from infrastructure.data_store import _date, _sha256
from infrastructure.stage_store import StageStore, _assert_safe_tree


Projector = Callable[[Mapping[str, Any]], dict[str, Any]]


class InputProducer(Protocol):
    def produce(self, trade_date: str, stage_id: str) -> Mapping[str, Any]: ...


class OpeningSecondFilterReader(Protocol):
    def read(self, trade_date: str) -> dict[str, Any] | None: ...


CODE_SIGNATURE = _sha256(
    {
        "contract": STAGE_CONTRACT_VERSION,
        "selection_mode": "V3_5_NATIVE_STAGE_SCORE_V1",
        "safety": "WATCH_ONLY",
    }
)


class StageRunner:
    def __init__(
        self,
        store: StageStore,
        projector: Projector | None = None,
        input_producer: InputProducer | None = None,
        opening_second_filter_store: OpeningSecondFilterReader | None = None,
    ) -> None:
        self.store = store
        self.projector = projector or _project_watch_only
        self.input_producer = input_producer
        self.opening_second_filter_store = opening_second_filter_store

    def ensure(self, trade_date: str, stage_id: str, *, force: bool = False) -> dict[str, Any]:
        trade_date = _date(trade_date)
        if stage_id not in STAGE_DEFINITIONS:
            raise ValueError("unknown stage_id")
        if force and self.input_producer is not None:
            refresh = getattr(self.input_producer, "refresh", None)
            if callable(refresh):
                try:
                    refresh(trade_date, stage_id)
                except Exception as error:
                    # Keep any prior artifact for audit, but do not publish it
                    # as the result of a failed explicit source refresh.
                    return _ensure_blocked(
                        trade_date,
                        stage_id,
                        f"STAGE_INPUT_REFRESH_BLOCKED: {type(error).__name__}: {error}",
                    )
        try:
            payload, input_sha = self.store.read_input(trade_date, stage_id)
        except FileNotFoundError:
            if self.input_producer is None:
                return _ensure_blocked(trade_date, stage_id, "STAGE_INPUT_MISSING")
            try:
                self.input_producer.produce(trade_date, stage_id)
                payload, input_sha = self.store.read_input(trade_date, stage_id)
            except Exception as error:
                return _ensure_blocked(
                    trade_date,
                    stage_id,
                    f"STAGE_INPUT_PRODUCTION_BLOCKED: {type(error).__name__}: {error}",
                )
        except ValueError as error:
            return _ensure_blocked(trade_date, stage_id, f"STAGE_INPUT_INVALID: {error}")

        run_id = _sha256({"input_sha256": input_sha, "code_signature": CODE_SIGNATURE})[:24]
        try:
            try:
                existing = self.store.read_latest(trade_date, stage_id)
            except ValueError:
                if not force:
                    raise
                existing = None
            if existing is not None and existing["run_id"] == run_id and not force:
                return _ensure_result(existing, "ALREADY_COMPLETE")
            output = self.projector(payload)
            output = _finalize_output(output, payload, run_id, input_sha)
            published = self.store.publish(
                trade_date=trade_date,
                stage_id=stage_id,
                run_id=run_id,
                input_sha256=input_sha,
                code_signature=CODE_SIGNATURE,
                output=output,
                force=force,
            )
            return _ensure_result(published, published["ensure_status"])
        except Exception as error:
            failure_path = self.store.record_failure(
                trade_date=trade_date,
                stage_id=stage_id,
                run_id=run_id,
                input_sha256=input_sha,
                error=error,
            )
            return {
                "ok": False,
                "ensure_status": "STAGE_RUN_FAILED",
                "trade_date": trade_date,
                "stage_id": stage_id,
                "run_id": run_id,
                "failure_receipt_path": failure_path,
                "cannot_confirm": [f"{type(error).__name__}: {error}"],
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }

    def read_workbench(self, trade_date: str, stage_id: str, limit: int = 10) -> dict[str, Any]:
        trade_date = _date(trade_date)
        if stage_id not in STAGE_DEFINITIONS:
            raise ValueError("unknown stage_id")
        if not 1 <= int(limit) <= 50:
            raise ValueError("limit must be between 1 and 50")
        try:
            latest = self.store.read_latest(trade_date, stage_id)
        except ValueError as error:
            return _blocked_workbench(trade_date, stage_id, "DATA_BLOCKED_ARTIFACT_INVALID", str(error))
        if latest is None:
            try:
                reference = self.store.read_reference_workbench(trade_date, stage_id)
            except ValueError as error:
                return _blocked_workbench(
                    trade_date,
                    stage_id,
                    "DATA_BLOCKED_REFERENCE_INVALID",
                    str(error),
                )
            if reference is not None:
                reference = self._attach_opening_second_filter(
                    trade_date,
                    stage_id,
                    reference,
                )
                return _limit_reference_workbench(reference, int(limit))
            try:
                self.store.read_input(trade_date, stage_id)
            except FileNotFoundError:
                return _blocked_workbench(
                    trade_date,
                    stage_id,
                    "DATA_BLOCKED_INPUT_MISSING",
                    "V3.5-owned stage input has not been imported.",
                )
            except ValueError as error:
                return _blocked_workbench(trade_date, stage_id, "DATA_BLOCKED_INPUT_INVALID", str(error))
            return _blocked_workbench(
                trade_date,
                stage_id,
                "STAGE_NOT_MATERIALIZED",
                "Stage input exists but the native stage run has not completed.",
            )
        try:
            reference = self.store.read_reference_workbench(trade_date, stage_id)
        except ValueError:
            reference = None
        if reference is not None and stage_id == "STAGE_0925":
            latest = _merge_0925_source_reference(latest, reference)
        if stage_id == "STAGE_0925" and self.opening_second_filter_store is not None:
            merged_latest = deepcopy(latest)
            merged_latest["artifact"] = self._attach_opening_second_filter(
                trade_date,
                stage_id,
                merged_latest["artifact"],
            )
            latest = merged_latest
        return _limit_workbench(latest, int(limit))

    def _attach_opening_second_filter(
        self,
        trade_date: str,
        stage_id: str,
        workbench: Mapping[str, Any],
    ) -> dict[str, Any]:
        if stage_id != "STAGE_0925" or self.opening_second_filter_store is None:
            return deepcopy(dict(workbench))
        artifact = self.opening_second_filter_store.read(trade_date)
        if artifact is None:
            return deepcopy(dict(workbench))
        return _merge_v11_champion(workbench, artifact)


def _merge_0925_source_reference(
    native: Mapping[str, Any],
    reference: Mapping[str, Any],
) -> dict[str, Any]:
    """Expose legacy facts only as diagnostics, never as native stage truth."""
    merged = deepcopy(native)
    artifact = merged.get("artifact", merged)
    artifact.pop("source_status_reference", None)
    reference_markets = reference.get("markets") if isinstance(reference, Mapping) else None
    reference_a = reference_markets.get("A") if isinstance(reference_markets, Mapping) else None
    reference_source_rows = reference_a.get("source_rows") if isinstance(reference_a, Mapping) else None
    if (
        isinstance(reference_source_rows, bool)
        or not isinstance(reference_source_rows, int)
        or reference_source_rows < 0
    ):
        artifact["legacy_reference_diagnostic"] = {
            "reference_available": False,
            "status": "INVALID_REFERENCE",
        }
        return merged
    artifact["legacy_reference_diagnostic"] = {
        "reference_available": True,
        "a_source_rows": reference_source_rows,
    }
    native_markets = artifact.get("markets")
    native_a = native_markets.get("A") if isinstance(native_markets, Mapping) else None
    cannot_confirm_items = artifact.get("sidebar", {}).get("cannot_confirm_items", [])
    has_no_auction_evidence = any(
        isinstance(item, Mapping)
        and item.get("reason") == "PYTDX_MINUTE_REPLAY_HAS_NO_CALL_AUCTION_EVIDENCE"
        for item in cannot_confirm_items
    ) if isinstance(cannot_confirm_items, list) else False
    selected_a_rows = int(artifact.get("selected_a_rows") or 0)
    if (
        isinstance(native_a, Mapping)
        and native_a.get("source_status") == "CANNOT_CONFIRM"
        and has_no_auction_evidence
        and selected_a_rows == 0
    ):
        requested_rows = int(native_a.get("requested_rows") or 0)
        source_rows = int(native_a.get("source_rows") or 0)
        candidate_count = int(native_a.get("candidate_count") or 0)
        artifact["stage"]["display_status"] = (
            f"A-share upstream pool {requested_rows}; same-cutoff 09:25 evidence "
            f"{source_rows}; candidate {candidate_count}; selected {selected_a_rows}."
        )
    return merged


def _merge_v11_champion(
    workbench: Mapping[str, Any],
    v11: Mapping[str, Any],
) -> dict[str, Any]:
    """Project the graph-authoritative v1.1 Top20 into the stage workbench."""
    merged = deepcopy(dict(workbench))
    existing_rows = [
        row
        for row in merged.get("unified_rows", [])
        if isinstance(row, Mapping) and row.get("market") == "A"
    ]
    a_rows = apply_a_share_v11_adapter(existing_rows)
    status_labels = {
        "AUCTION_SECOND_FILTER_PRIORITY": "09:20竞价优先观察",
        "AUCTION_SECOND_FILTER_WATCH": "09:20竞价观察",
        "AUCTION_SECOND_FILTER_LOW_PRIORITY": "09:20低优先级观察",
        "AUCTION_HIGH_OPEN_NO_CHASE": "09:20高开不追",
    }
    hk_rows = []
    for source in v11.get("rows", []):
        status = str(source.get("second_filter_status") or "")
        hk_rows.append(
            {
                **deepcopy(dict(source)),
                "symbol": str(source.get("code") or ""),
                "market": "HK",
                "score": source.get("auction_score"),
                "current_change_pct": source.get("auction_ref_gap_pct"),
                "stage_display_decision": status_labels.get(status, "09:20竞价观察"),
                "next_validation_time": "09:35",
                "data_level": "AUCTION_SECOND_FILTER_READY",
                "recommendation_status": "WATCH_ONLY",
                "model_id": v11["model_id"],
                "model_version": v11["version"],
            }
        )
    merged["unified_rows"] = [*a_rows, *hk_rows]
    merged["stage_groups"] = [
        {"market": "A", "label": "A股", "rows": a_rows},
        {"market": "HK", "label": "港股通", "rows": hk_rows},
    ]
    markets = merged.setdefault("markets", {})
    hk_market = markets.setdefault("HK", {"label": "港股通"})
    hk_market.update(
        {
            "candidate_count": len(hk_rows),
            "source_rows": int(v11.get("preselect_row_count") or len(hk_rows)),
            "requested_rows": int(v11.get("preselect_row_count") or len(hk_rows)),
            "source_status": v11["status"],
            "data_level": "V1_1_CUTOFF_SAFE_TOP20",
        }
    )
    a_market = markets.setdefault("A", {"label": "A股"})
    a_market["candidate_count"] = len(a_rows)
    merged["selected_a_rows"] = len(a_rows)
    merged["selected_hk_rows"] = len(hk_rows)
    merged["selected_total_rows"] = len(a_rows) + len(hk_rows)
    merged["opening_second_filter"] = {
        "schema_version": v11["schema_version"],
        "model_id": v11["model_id"],
        "version": v11["version"],
        "champion_contract": v11["champion_contract"],
        "status": v11["status"],
        "signal_cutoff": v11["signal_cutoff"],
        "publication_time": v11["publication_time"],
        "row_count": len(hk_rows),
        "markets": {
            "A": {
                "refresh_time": "09:25",
                "strategy": "a_share_v1_1_price_volume_adapter",
                "row_count": len(a_rows),
            },
            "HK": {
                "refresh_time": "09:20",
                "strategy": "old_v3_rule_guardrail_with_hardcap_and_0920_reference_layer",
                "row_count": len(hk_rows),
            },
        },
        "source_evidence": deepcopy(v11["source_evidence"]),
        "recommendation_status": "WATCH_ONLY",
    }
    evidence_item = {
        "path": f"opening_second_filter/{v11['trade_date']}/STAGE_0925.json",
        "sha256": str(v11["source_evidence"]["source_output_sha256"]),
        "label": "港股通开盘二筛 v1.1",
        "status": v11["status"],
    }
    startup = merged.setdefault("startup_ensure", {})
    startup_evidence = startup.setdefault("source_evidence", [])
    if evidence_item not in startup_evidence:
        startup_evidence.append(deepcopy(evidence_item))
    sidebar = merged.setdefault("sidebar", {})
    sidebar_evidence = sidebar.setdefault("evidence_sources", [])
    if evidence_item not in sidebar_evidence:
        sidebar_evidence.append(deepcopy(evidence_item))
    merged["selection_mode"] = "V1_1_CHAMPION_DUAL_MARKET"
    merged["response_source"] = "V3_5_NATIVE_STAGE_SNAPSHOT_WITH_V1_1_CHAMPION"
    merged["production_allowed"] = False
    merged["buy_gate_updated"] = False
    merged["orders_sent"] = False
    merged["recommendation_status"] = "WATCH_ONLY_BACKTEST_GATED"
    _assert_safe_tree(merged)
    return merged


def _project_watch_only(payload: Mapping[str, Any]) -> dict[str, Any]:
    trade_date = str(payload["trade_date"])
    stage_id = str(payload["stage_id"])
    cutoff_reached = bool(payload["cutoff_reached"])
    market_status = payload["market_status"]
    rows_by_market = payload["rows"]
    source_summary = payload.get("source_summary", {})
    evidence_gaps = (
        list(source_summary.get("cannot_confirm", []))
        if isinstance(source_summary, Mapping)
        else []
    )
    a_rows = (
        rank_a_stage_rows(rows_by_market["A"], stage_id, limit=50)
        if cutoff_reached and market_status["A"] != "CLOSED"
        else []
    )
    hk_rows = (
        rank_hk_stage_rows(rows_by_market["HK"], limit=10)
        if cutoff_reached and market_status["HK"] != "CLOSED"
        else []
    )
    if not cutoff_reached:
        stage_status = "PENDING_CUTOFF_NOT_REACHED"
        display_status = "当前阶段尚未到触发时间；不展示提前生成或旧产物候选。"
    elif any(value == "CANNOT_CONFIRM" for value in market_status.values()):
        stage_status = "PARTIAL_WITH_WATCH_ROWS"
        if "PYTDX_MINUTE_REPLAY_HAS_NO_CALL_AUCTION_EVIDENCE" in evidence_gaps:
            display_status = (
                "pytdx 分钟回放不包含 09:25 集合竞价证据；"
                "A股竞价候选不伪造，港股行保持 WATCH_ONLY。"
            )
        else:
            display_status = "阶段输入部分可确认；仅展示 WATCH_ONLY 观察行。"
    elif all(value == "CLOSED" for value in market_status.values()):
        stage_status = "MARKET_CLOSED_NO_BUY"
        display_status = "市场休市；不生成交易建议。"
    else:
        stage_status = "READY_WITH_WATCH_ROWS"
        display_status = "阶段证据已物化；输出仅用于 WATCH_ONLY 观察。"

    cannot_confirm = []
    for market, status in market_status.items():
        if status != "READY":
            cannot_confirm.append(
                {
                    "item_id": f"{trade_date}-{stage_id}-{market}",
                    "scope": market,
                    "reason": status,
                    "description": f"{market} market stage evidence is {status}.",
                    "source_path": "",
                }
            )
    for gap in evidence_gaps:
        cannot_confirm.append(
            {
                "item_id": f"{trade_date}-{stage_id}-SOURCE-{len(cannot_confirm) + 1}",
                "scope": "SOURCE",
                "reason": str(gap),
                "description": str(gap),
                "source_path": "",
            }
        )
    a_rows = [{**row, "trade_date": trade_date, "stage_id": stage_id, "market": "A"} for row in a_rows]
    hk_rows = [{**row, "trade_date": trade_date, "stage_id": stage_id, "market": "HK"} for row in hk_rows]
    unified_rows = [*a_rows, *hk_rows]
    return {
        "ok": True,
        "schema_version": "v3_stage_workbench.v2",
        "module_card": {
            "module_id": "eight_stage_selection",
            "display_name": "八阶段选股",
            "owner_file": "apps/web/src/App.vue",
            "primary_api": "GET /api/v3/workbench/stage",
            "write_policy": "read_only",
            "date_stage_policy": "single date + stage context for A股, 港股通, evidence sidebar",
        },
        "trade_date": trade_date,
        "stage": {
            "stage_id": stage_id,
            "label": STAGE_DEFINITIONS[stage_id]["label"],
            "window": STAGE_DEFINITIONS[stage_id]["window"],
            "status": stage_status,
            "display_status": display_status,
            "same_context_required": True,
        },
        "markets": {
            "A": {
                "label": "A股",
                "candidate_count": len(a_rows),
                "source_rows": len(rows_by_market["A"]),
                "requested_rows": int(source_summary.get("requested_A", len(rows_by_market["A"])))
                if isinstance(source_summary, Mapping)
                else len(rows_by_market["A"]),
                "source_status": market_status["A"],
                "data_level": "WATCH_ONLY",
            },
            "HK": {
                "label": "港股通",
                "candidate_count": len(hk_rows),
                "source_rows": len(rows_by_market["HK"]),
                "requested_rows": int(source_summary.get("requested_HK", len(rows_by_market["HK"])))
                if isinstance(source_summary, Mapping)
                else len(rows_by_market["HK"]),
                "source_status": market_status["HK"],
                "data_level": "WATCH_ONLY",
            },
        },
        "startup_ensure": {
            "status": "STAGE_ARTIFACTS_READY",
            "source_evidence": deepcopy(payload["source_evidence"]),
        },
        "stage_groups": [
            {"market": "A", "label": "A股", "rows": a_rows},
            {"market": "HK", "label": "港股通", "rows": hk_rows},
        ],
        "selected_a_rows": len(a_rows),
        "selected_hk_rows": len(hk_rows),
        "selected_total_rows": len(unified_rows),
        "unified_rows": unified_rows,
        "opening_second_filter": {
            "schema_version": "v3_5.native_stage_score.v1",
            "status": "NATIVE_STAGE_SCORE_READY",
            "stage_id": stage_id,
            "recommendation_status": "WATCH_ONLY",
        },
        "sidebar": {
            "timeline": [],
            "evidence_sources": deepcopy(payload["source_evidence"]),
            "cannot_confirm_items": cannot_confirm,
        },
        "empty_state": {
            "A": "" if a_rows else "当前阶段 A股无可确认 WATCH_ONLY 候选。",
            "HK": "" if hk_rows else "当前阶段港股通无可确认 WATCH_ONLY 候选。",
        },
        "selection_mode": "V3_5_NATIVE_STAGE_SCORE_V1",
        "recommendation_status": "WATCH_ONLY_BACKTEST_GATED",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _finalize_output(
    output: Mapping[str, Any],
    input_payload: Mapping[str, Any],
    run_id: str,
    input_sha: str,
) -> dict[str, Any]:
    if not isinstance(output, Mapping):
        raise ValueError("stage projector must return an object")
    result = deepcopy(dict(output))
    if (
        result.get("schema_version") != "v3_stage_workbench.v2"
        or result.get("trade_date") != input_payload["trade_date"]
        or not isinstance(result.get("stage"), Mapping)
        or result["stage"].get("stage_id") != input_payload["stage_id"]
    ):
        raise ValueError("stage projector output identity mismatch")
    for key in ("production_allowed", "buy_gate_updated", "orders_sent"):
        if result.get(key) is not False:
            raise ValueError("stage projector changed a trading safety boundary")
    if result.get("recommendation_status") != "WATCH_ONLY_BACKTEST_GATED":
        raise ValueError("stage projector changed recommendation semantics")
    rows = result.get("unified_rows")
    if not isinstance(rows, list) or any(
        not isinstance(row, Mapping) or row.get("recommendation_status") != "WATCH_ONLY"
        for row in rows
    ):
        raise ValueError("stage projector returned non-WATCH_ONLY rows")
    grouped_rows = []
    groups = result.get("stage_groups")
    if not isinstance(groups, list):
        raise ValueError("stage projector returned invalid groups")
    for group in groups:
        if not isinstance(group, Mapping) or not isinstance(group.get("rows"), list):
            raise ValueError("stage projector returned invalid group rows")
        grouped_rows.extend(group["rows"])
    if any(
        not isinstance(row, Mapping) or row.get("recommendation_status") != "WATCH_ONLY"
        for row in grouped_rows
    ):
        raise ValueError("stage projector returned unsafe grouped rows")
    _assert_safe_tree(result)
    result["materialized_snapshot"] = {
        "schema_version": "v3_5.stage_snapshot.v1",
        "run_id": run_id,
        "input_sha256": input_sha,
        "code_signature": CODE_SIGNATURE,
        "write_policy": "native_stage_snapshot_only",
        "buy_gate_effect": "none",
        "live_order_effect": "none",
    }
    result["response_source"] = "V3_5_NATIVE_STAGE_SNAPSHOT"
    return result


def _limit_workbench(latest: Mapping[str, Any], limit: int) -> dict[str, Any]:
    output = deepcopy(latest["artifact"])
    output["unified_rows"] = _limit_rows_per_market(output.get("unified_rows", []), limit)
    for group in output.get("stage_groups", []):
        if isinstance(group, dict):
            group["rows"] = group.get("rows", [])[:limit]
    output["snapshot_path"] = latest["artifact_path"]
    output["run_receipt"] = {
        "run_id": latest["run_id"],
        "manifest_path": latest["manifest_path"],
        "receipt_path": latest["receipt_path"],
    }
    return output


def _limit_reference_workbench(reference: Mapping[str, Any], limit: int) -> dict[str, Any]:
    output = deepcopy(dict(reference))
    output["unified_rows"] = _limit_rows_per_market(output.get("unified_rows", []), limit)
    output["reference_snapshot"] = True
    return output


def _limit_rows_per_market(rows: Any, limit: int) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    selected: list[dict[str, Any]] = []
    for market in ("A", "HK"):
        market_rows = [
            row
            for row in rows
            if isinstance(row, dict) and row.get("market") == market
        ]
        selected.extend(market_rows[:limit])
    return selected


def _ensure_result(published: Mapping[str, Any], status: str) -> dict[str, Any]:
    return {
        "ok": True,
        "ensure_status": status,
        "trade_date": published["artifact"]["trade_date"],
        "stage_id": published["artifact"]["stage"]["stage_id"],
        "run_id": published["run_id"],
        "artifact_path": published["artifact_path"],
        "manifest_path": published["manifest_path"],
        "receipt_path": published["receipt_path"],
        "selected_total_rows": published["artifact"]["selected_total_rows"],
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _ensure_blocked(trade_date: str, stage_id: str, reason: str) -> dict[str, Any]:
    return {
        "ok": False,
        "ensure_status": reason.split(":", 1)[0],
        "trade_date": trade_date,
        "stage_id": stage_id,
        "cannot_confirm": [reason],
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _blocked_workbench(trade_date: str, stage_id: str, status: str, reason: str) -> dict[str, Any]:
    return {
        "ok": False,
        "schema_version": "v3_stage_workbench.v2",
        "trade_date": trade_date,
        "stage": {
            "stage_id": stage_id,
            "label": STAGE_DEFINITIONS[stage_id]["label"],
            "window": STAGE_DEFINITIONS[stage_id]["window"],
            "status": status,
            "display_status": reason,
            "same_context_required": True,
        },
        "markets": {
            "A": {"label": "A股", "candidate_count": 0, "source_rows": 0, "source_status": status},
            "HK": {"label": "港股通", "candidate_count": 0, "source_rows": 0, "source_status": status},
        },
        "stage_groups": [],
        "selected_a_rows": 0,
        "selected_hk_rows": 0,
        "selected_total_rows": 0,
        "unified_rows": [],
        "sidebar": {
            "timeline": [],
            "evidence_sources": [],
            "cannot_confirm_items": [{"reason": status, "description": reason, "source_path": ""}],
        },
        "empty_state": {"A": reason, "HK": reason},
        "selection_mode": "V3_5_NATIVE_STAGE_SCORE_V1",
        "recommendation_status": "WATCH_ONLY_BACKTEST_GATED",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
