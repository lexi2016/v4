"""Read, verify and project one stage-workbench response.

Split out of ``create_app``: the branches below were closures over the
configured roots and the consumer; they now take an explicit
``StageWorkbenchContext`` so the runtime dependency is visible.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from fastapi import HTTPException

from apps.api.v4_api.projection import ProjectionContext, project_shared_selection
from contracts.trading_safety import TRADING_SAFETY_FLAGS
from stage_center.research_read_binding import ResearchReadError


@dataclass(frozen=True)
class StageWorkbenchContext:
    approved_research_reader: Any
    shared_selection_consumer: Any
    configured_selection_root: Any
    stage_runner: Any
    projection: ProjectionContext
    approved_exact_stage_backfills: Mapping[Any, Any]
    morning_binding_by_date_stage: Mapping[Any, Any]
    quarantine_hk_auction_pool_mismatch: Callable[..., Any]
    hk_morning_override: Callable[..., Any]
    r8_override: Callable[..., Any]
    r9_override: Callable[..., Any]
    scoped_selection_root: Callable[..., Any]
    new_scoped_consumer: Callable[..., Any]


def read_stage_workbench(
    ctx: StageWorkbenchContext,
    selected: str,
    stage: str,
    limit: int,
    market: str | None,
    backfill_run_id: str | None,
) -> dict:
    response = _research_binding_response(ctx, selected, stage, limit, market, backfill_run_id)
    if response is not None:
        return response
    if market is not None or backfill_run_id is not None:
        return _exact_backfill_response(ctx, selected, stage, limit, market, backfill_run_id)
    response = _ordinary_selection_response(ctx, selected, stage, limit, market, backfill_run_id)
    if response is not None:
        return response
    return ctx.stage_runner.read_workbench(selected, stage, limit)


def _research_binding_response(
    ctx: StageWorkbenchContext,
    selected: str,
    stage: str,
    limit: int,
    market: str | None,
    backfill_run_id: str | None,
) -> dict | None:
    # The optional release-owned binding handles only its exact approved
    # date/stage/run. All ordinary history and legacy exact bindings below
    # retain their original configured root and verification contract.
    morning_binding = ctx.morning_binding_by_date_stage.get(
        (selected, stage)
    )
    is_exact_morning_backfill = (
        market == "HK_CONNECT"
        and isinstance(morning_binding, Mapping)
        and morning_binding.get("backfill_run_id") == backfill_run_id
    )
    if (
        ctx.approved_research_reader is not None
        and ((market is None) == (backfill_run_id is None))
        and not is_exact_morning_backfill
    ):
        try:
            research_payload = ctx.approved_research_reader.get(
                selected, stage, markets=None if market is None else (market,),
                backfill_run_id=backfill_run_id,
            )
        except ResearchReadError as error:
            # The optional research package covers BOTH A and HK. Its
            # rejected A is never authenticated by this fallback: read the
            # independent ordinary A trio through the unchanged verifier.
            if (selected, stage) == ("20261009", "STAGE_0930_0935") and (
                market is None and backfill_run_id is None
                and ctx.shared_selection_consumer is not None
            ):
                ordinary = ctx.shared_selection_consumer.get(
                    selected, stage, markets=("A_SHARE",), allow_backfill=True
                )
                a_market = (ordinary.get("markets") or {}).get("A_SHARE")
                if isinstance(a_market, Mapping) and (
                    a_market.get("selection_manifest_receipt_verified") is True
                    and int(a_market.get("selected_rows") or 0) > 0
                    and len(a_market.get("rows") or []) == a_market["selected_rows"]
                ):
                    from stage_center.consumer import _invalid_market_with_reason
                    denied = _invalid_market_with_reason(
                        "HK_CONNECT", "APPROVED_RESEARCH_BINDING_INVALID"
                    )
                    denied["cannot_confirm"].append(str(error))
                    result = dict(ordinary)
                    result["markets"] = {"A_SHARE": a_market, "HK_CONNECT": denied}
                    result.update(artifact_id=None, bundle_artifact_id=None, run_id=None)
                    result["optional_override_failure"] = {
                        "scope": ["A_SHARE", "HK_CONNECT"],
                        "reason": str(error),
                        "fallback": "INDEPENDENT_VERIFIED_ORDINARY_A_TRIO_ONLY",
                        "rejected_research_A_used": False,
                    }
                    execution = dict(ordinary.get("execution_evidence") or {})
                    execution_markets = dict(execution.get("markets") or {})
                    execution_markets["HK_CONNECT"] = {
                        "status": "CANNOT_CONFIRM", "execution_verified": False,
                        "natural_verified": False,
                        "cannot_confirm": list(denied["cannot_confirm"]),
                    }
                    execution.update(markets=execution_markets,
                                     execution_verified=False, natural_verified=False)
                    result["execution_evidence"] = execution
                    return project_shared_selection(ctx.projection, result, limit, ordinary_hk_display=True)
            raise HTTPException(status_code=409, detail="approved research read binding is unavailable or invalid") from error
        if research_payload is not None:
            response = project_shared_selection(ctx.projection, research_payload, limit, ordinary_hk_display=True)
            # The existing HK display intentionally withholds a formal
            # selected count. Verified research rows still make this
            # exact composed response partial when its other lane fails.
            if research_payload.get("status") == "PARTIAL_WITH_ROWS":
                response["status"] = "PARTIAL_WITH_ROWS"
                response["stage"].update(status="PARTIAL_WITH_ROWS", display_status="PARTIAL_WITH_ROWS")
            if market is not None:
                response.update(market=market, selection_mode="HISTORICAL_BACKFILL_READ_ONLY",
                                response_source="SHARED_STAGE_CENTER_BACKFILL")
            return response
    return None


def _exact_backfill_response(
    ctx: StageWorkbenchContext,
    selected: str,
    stage: str,
    limit: int,
    market: str | None,
    backfill_run_id: str | None,
) -> dict | None:
        if market is None or backfill_run_id is None:
            raise HTTPException(status_code=422, detail="market and backfill_run_id must be supplied together")
        binding = ctx.approved_exact_stage_backfills.get(
            (selected, stage, market, backfill_run_id)
        )
        if binding is None:
            raise HTTPException(status_code=404, detail="backfill selection identity is unavailable")
        if ctx.configured_selection_root is None or ctx.shared_selection_consumer is None:
            raise HTTPException(status_code=404, detail="backfill selection namespace is unavailable")

        scoped_root = ctx.scoped_selection_root(
            ctx.configured_selection_root, backfill_run_id
        )
        backfill_consumer = ctx.new_scoped_consumer(
            scoped_root,
            ctx.shared_selection_consumer,
        )
        try:
            envelope = backfill_consumer.store.read_verified(selected, stage, market)
            latest = backfill_consumer.store._latest()
            entry = latest.get("entries", {}).get(
                backfill_consumer.store._key(selected, stage, market)
            )
            payload = backfill_consumer.get(selected, stage, markets=(market,))
        except (OSError, ValueError, TypeError, KeyError) as error:
            raise HTTPException(status_code=409, detail="backfill selection identity is invalid") from error

        market_payload = (payload.get("markets") or {}).get(market)
        if not isinstance(entry, Mapping) or not isinstance(market_payload, Mapping):
            raise HTTPException(status_code=409, detail="backfill selection identity is invalid")
        morning_binding = ctx.morning_binding_by_date_stage.get(
            (selected, stage)
        )
        is_morning_observation = (
            market == "HK_CONNECT"
            and isinstance(morning_binding, Mapping)
            and morning_binding.get("backfill_run_id") == backfill_run_id
        )
        rows = (
            envelope.get("rows") or []
            if is_morning_observation
            else market_payload.get("rows") or []
        )
        source_evidence = envelope.get("source_evidence") or []
        cannot_confirm = envelope.get("cannot_confirm") or []
        expected_identity = {
            "trade_date": selected,
            "stage_id": stage,
            "market": market,
            "run_id": binding["selection_run_id"],
            "artifact_id": binding["artifact_id"],
            "raw_artifact_sha256": binding["raw_artifact_sha256"],
            "algorithm_id": binding["algorithm_id"],
            "algorithm_sha256": binding["algorithm_sha256"],
            "selection_status": binding["selection_status"],
            "source_status": binding["source_status"],
        }
        if any(envelope.get(field) != expected for field, expected in expected_identity.items()):
            raise HTTPException(status_code=409, detail="backfill selection identity is invalid")
        if (
            entry.get("run_id") != binding["selection_run_id"]
            or entry.get("manifest_sha256") != binding["selection_manifest_sha256"]
            or entry.get("receipt_sha256") != binding["selection_receipt_sha256"]
            or entry.get("artifact_sha256") != binding["selection_artifact_sha256"]
            or len(rows) != binding["selected_rows"]
            or len(envelope.get("rows") or []) != binding["selected_rows"]
            or envelope.get("selected_rows") != binding["selected_rows"]
            or envelope.get("source_rows") != binding["source_rows"]
            or not isinstance(cannot_confirm, list)
            or len(cannot_confirm) != binding["cannot_confirm_count"]
            or not isinstance(source_evidence, list)
            or any(not isinstance(marker, str) for marker in source_evidence)
            or any(marker not in source_evidence for marker in binding["required_evidence"])
            or (
                binding.get("requested_rows") is not None
                and (
                    envelope.get("requested_rows") != binding["requested_rows"]
                    or (
                        not is_morning_observation
                        and market_payload.get("requested_rows")
                        != binding["requested_rows"]
                    )
                    or binding["requested_rows"] - binding["source_rows"]
                    != binding.get("missing_rows")
                    or binding.get("missing_rows")
                    != len(binding.get("missing_codes") or ())
                )
            )
            or (
                binding.get("source_evidence_sha256") is not None
                and hashlib.sha256(
                    "\n".join(source_evidence).encode("utf-8")
                ).hexdigest()
                != binding["source_evidence_sha256"]
            )
            or any(envelope.get(flag) is not False for flag in TRADING_SAFETY_FLAGS)
            or any(
                not isinstance(row, Mapping)
                or row.get("formal_eligible") is not False
                or row.get("action_level") != "NO_BUY"
                or row.get("trade_status") not in {"NO_TRADE", "WATCH_ONLY"}
                or row.get("status") != row.get("trade_status")
                or row.get("source_mode") != "HK_CONNECT_FOUR_LANE"
                for row in rows
            )
        ):
            raise HTTPException(status_code=409, detail="backfill selection safety or SHA binding is invalid")

        runner_receipt_verified, runner_receipt_sha256 = (
            backfill_consumer._verify_backfill_runner_receipt(
                trade_date=selected,
                stage_id=stage,
                market=market,
                backfill_run_id=backfill_run_id,
                envelope=envelope,
            )
        )
        if (
            runner_receipt_verified is not True
            or runner_receipt_sha256 != binding["runner_receipt_sha256"]
        ):
            raise HTTPException(status_code=409, detail="backfill runner receipt identity is invalid")

        if is_morning_observation:
            from stage_center.selection import SelectionStore

            try:
                original = SelectionStore(ctx.configured_selection_root)._verify_run(
                    selected,
                    stage,
                    "HK_CONNECT",
                    morning_binding["selection_run_id"],
                )
            except (OSError, ValueError, TypeError, KeyError) as error:
                raise HTTPException(
                    status_code=409,
                    detail="original morning selection identity is invalid",
                ) from error
            original_envelope = original.get("envelope")
            if (
                not isinstance(original_envelope, Mapping)
                or original.get("manifest_sha256")
                != morning_binding["original_manifest_sha256"]
                or original.get("receipt_sha256")
                != morning_binding["original_receipt_sha256"]
                or original.get("artifact_sha256")
                != morning_binding["selection_artifact_sha256"]
                or any(
                    original_envelope.get(field) != envelope.get(field)
                    for field in (
                        "run_id",
                        "artifact_id",
                        "raw_artifact_sha256",
                        "algorithm_id",
                        "algorithm_sha256",
                        "rows",
                    )
                )
            ):
                raise HTTPException(
                    status_code=409,
                    detail="morning observation differs from original selection",
                )
            market_payload.update(
                {
                    "market": "HK_CONNECT",
                    "status": envelope["selection_status"],
                    "selection_status": envelope["selection_status"],
                    "source_status": envelope["source_status"],
                    "artifact_id": envelope["artifact_id"],
                    "run_id": envelope["run_id"],
                    "algorithm_id": envelope["algorithm_id"],
                    "algorithm_sha256": envelope["algorithm_sha256"],
                    "raw_artifact_sha256": envelope["raw_artifact_sha256"],
                    "requested_rows": envelope["requested_rows"],
                    "source_rows": envelope["source_rows"],
                    "selected_rows": envelope["selected_rows"],
                    "coverage_ratio": envelope["coverage_ratio"],
                    "source_evidence": list(source_evidence),
                    "missing_symbols": list(envelope.get("missing_symbols") or []),
                    "cannot_confirm": list(cannot_confirm),
                    "rows": list(envelope["rows"]),
                }
            )
            market_payload.update(
            {
                "selection_mode": "BACKFILL",
                "backfill_run_id": backfill_run_id,
                "backfill_run_ids": [backfill_run_id],
                "selection_manifest_sha256": binding["selection_manifest_sha256"],
                "selection_receipt_sha256": binding["selection_receipt_sha256"],
                "selection_artifact_sha256": binding["selection_artifact_sha256"],
                "selection_manifest_receipt_verified": True,
                "runner_receipt_verified": True,
                "runner_receipt_status": "VERIFIED",
                "runner_receipt_sha256": runner_receipt_sha256,
                "recovery_provenance": {
                    "mode": "BACKFILL",
                    "backfill_run_id": backfill_run_id,
                    "selection_manifest_receipt_verified": True,
                    "runner_receipt_verified": True,
                    "runner_receipt_status": "VERIFIED",
                    "runner_receipt_sha256": runner_receipt_sha256,
                },
            }
        )
        if binding.get("requested_rows") is not None and not is_morning_observation:
            market_payload.update(
                {
                    "target_pool_sha256": binding["pool_artifact_sha256"],
                    "candidate_receipt_sha256": binding["candidate_receipt_sha256"],
                    "candidate_manifest_sha256": binding["candidate_manifest_sha256"],
                    "candidate_source_evidence_sha256": binding[
                        "source_evidence_sha256"
                    ],
                    "candidate_source_coverage": {
                        "requested_rows": binding["requested_rows"],
                        "observed_rows": binding["source_rows"],
                        "missing_rows": binding["missing_rows"],
                        "missing_codes": list(binding["missing_codes"]),
                        "missing_reason_by_code": dict(
                            binding["missing_reason_by_code"]
                        ),
                    },
                }
            )
        response = project_shared_selection(ctx.projection,
            payload, limit, ordinary_hk_display=True
        )
        response.update(
            {
                "mode": "BACKFILL",
                "backfill_run_id": backfill_run_id,
                "market": market,
                "selection_mode": "HISTORICAL_BACKFILL_READ_ONLY",
                "response_source": "SHARED_STAGE_CENTER_BACKFILL",
                "RESEARCH_ONLY": True,
                "write_performed": False,
                **TRADING_SAFETY_FLAGS,
            }
        )
        return response


def _ordinary_selection_response(
    ctx: StageWorkbenchContext,
    selected: str,
    stage: str,
    limit: int,
    market: str | None,
    backfill_run_id: str | None,
) -> dict | None:
    if ctx.shared_selection_consumer is not None:
        hk_morning_recovery_slot = (
            selected == "20261016"
            and (selected, stage)
            in ctx.morning_binding_by_date_stage
        )
        payload = ctx.shared_selection_consumer.get(
            selected, stage, allow_backfill=not hk_morning_recovery_slot
        )
        payload = ctx.quarantine_hk_auction_pool_mismatch(
            payload, selected, stage
        )
        hk_morning_override = ctx.hk_morning_override(
            payload, selected, stage, limit
        )
        if hk_morning_override is not None:
            return project_shared_selection(ctx.projection,
                hk_morning_override, limit, ordinary_hk_display=True
            )
        r8_override = ctx.r8_override(
            payload, selected, stage, limit
        )
        if r8_override is not None:
            return project_shared_selection(ctx.projection,
                r8_override, limit, ordinary_hk_display=True
            )
        r9_override = ctx.r9_override(
            payload, selected, stage, limit
        )
        if r9_override is not None:
            return project_shared_selection(ctx.projection,
                r9_override, limit, ordinary_hk_display=True
            )
        if selected == "20260924" and stage == "STAGE_0930_0935":
            day24_run_id = "1d3ab9f9bd3a44c3811bf1fed2b74108"
            day24_binding_key = (
                selected,
                stage,
                "HK_CONNECT",
                day24_run_id,
            )
            if day24_binding_key in ctx.approved_exact_stage_backfills:
                try:
                    # The route validated this date and stage before reaching
                    # here, so the module read is called without re-entering it.
                    exact_hk = read_stage_workbench(
                        ctx, selected, stage, limit, "HK_CONNECT", day24_run_id,
                    )
                except HTTPException as error:
                    a_market = (payload.get("markets") or {}).get("A_SHARE")
                    if error.status_code != 409 or not isinstance(a_market, Mapping) or not (
                        a_market.get("selection_manifest_receipt_verified") is True
                        and int(a_market.get("selected_rows") or 0) > 0
                        and len(a_market.get("rows") or []) == a_market["selected_rows"]
                    ):
                        raise
                    from stage_center.consumer import _invalid_market_with_reason
                    denied = _invalid_market_with_reason(
                        "HK_CONNECT", "EXACT_TARGET_HK_BINDING_INVALID"
                    )
                    denied["cannot_confirm"].append(str(error.detail))
                    denied["recovery_provenance"] = {
                        "mode": "BACKFILL_BINDING_REJECTED",
                        "backfill_run_id": day24_run_id,
                        "source": "DAY24_EXACT_HK_OVERRIDE",
                        "http_status": error.status_code,
                    }
                    result = dict(payload)
                    markets = dict(payload.get("markets") or {})
                    markets["HK_CONNECT"] = denied
                    result.update(markets=markets, artifact_id=None,
                                  bundle_artifact_id=None, run_id=None)
                    execution = dict(payload.get("execution_evidence") or {})
                    execution_markets = dict(execution.get("markets") or {})
                    execution_markets["HK_CONNECT"] = {
                        "status": "CANNOT_CONFIRM", "execution_verified": False,
                        "natural_verified": False,
                        "cannot_confirm": list(denied["cannot_confirm"]),
                    }
                    execution.update(markets=execution_markets,
                                     execution_verified=False, natural_verified=False)
                    result["execution_evidence"] = execution
                    return project_shared_selection(ctx.projection, result, limit, ordinary_hk_display=True)
                exact_markets = exact_hk.get("selection_markets")
                exact_market = (
                    exact_markets.get("HK_CONNECT")
                    if isinstance(exact_markets, Mapping)
                    else None
                )
                exact_execution = exact_hk.get("execution_evidence")
                exact_execution_markets = (
                    exact_execution.get("markets")
                    if isinstance(exact_execution, Mapping)
                    else None
                )
                exact_execution_market = (
                    exact_execution_markets.get("HK_CONNECT")
                    if isinstance(exact_execution_markets, Mapping)
                    else None
                )
                if not isinstance(exact_market, Mapping):
                    raise HTTPException(
                        status_code=409,
                        detail="approved market-scoped backfill identity is invalid",
                    )

                canonical_markets = dict(payload.get("markets") or {})
                a_market = canonical_markets.get("A_SHARE") or {}
                canonical_markets["HK_CONNECT"] = dict(exact_market)
                for market_payload in canonical_markets.values():
                    if isinstance(market_payload, dict):
                        market_payload["RESEARCH_ONLY"] = True
                payload = dict(payload)
                payload["RESEARCH_ONLY"] = True
                payload["markets"] = canonical_markets
                # A and HK retain their own verified source identities; this
                # read-only composition does not claim a shared bundle.
                payload["artifact_id"] = None
                payload["bundle_artifact_id"] = None
                payload["run_id"] = None
                payload["market_readback_bindings"] = {
                    "scope": "DATE_STAGE_MARKET_SCOPED_READ_ONLY",
                    "trade_date": selected,
                    "stage_id": stage,
                    "markets": {
                        "A_SHARE": {
                            "source": "SHARED_STAGE_CENTER_CURRENT_SELECTION",
                            "run_id": a_market.get("run_id"),
                            "requested_rows": a_market.get("requested_rows"),
                            "source_rows": a_market.get("source_rows"),
                            "selected_rows": a_market.get("selected_rows"),
                        },
                        "HK_CONNECT": {
                            "source": "APPROVED_STAGE_CENTER_BACKFILL",
                            "backfill_run_id": day24_run_id,
                            "run_id": exact_market.get("run_id"),
                            "requested_rows": exact_market.get("requested_rows"),
                            "source_rows": exact_market.get("source_rows"),
                            "selected_rows": exact_market.get("selected_rows"),
                            "runner_receipt_sha256": exact_market.get(
                                "runner_receipt_sha256"
                            ),
                        },
                    },
                    "single_bundle_artifact_id": None,
                }

                combined_execution = dict(
                    payload.get("execution_evidence") or {}
                )
                combined_execution_markets = dict(
                    combined_execution.get("markets") or {}
                )
                if isinstance(exact_execution_market, Mapping):
                    combined_execution_markets["HK_CONNECT"] = dict(
                        exact_execution_market
                    )
                else:
                    # The scoped selection path has independently verified
                    # the runner receipt even though this consumer does not
                    # expose the matching execution-market detail row.
                    # Keep that binding visible without claiming natural or
                    # formal execution verification.
                    runner_verified = exact_market.get(
                        "runner_receipt_verified"
                    ) is True
                    combined_execution_markets["HK_CONNECT"] = {
                        "status": "SELECTION_REFERENCES_PARTIALLY_BOUND_EXECUTION_UNVERIFIED",
                        "selection_binding": (
                            "BOUND_TO_VERIFIED_SELECTION"
                            if runner_verified
                            else "CANNOT_CONFIRM"
                        ),
                        "runner_receipt_verified": runner_verified,
                        "runner_receipt_sha256": exact_market.get(
                            "runner_receipt_sha256"
                        ),
                        "execution_verified": False,
                        "natural_verified": False,
                        "cannot_confirm": [
                            "HK_BACKFILL_EXECUTION_MARKET_DETAILS_NOT_EXPOSED_BY_SELECTION_CONSUMER"
                        ],
                    }
                combined_execution["markets"] = combined_execution_markets
                combined_execution[
                    "scope"
                ] = "READ_ONLY_MARKET_SCOPED_SELECTION_COMPOSITION"
                combined_execution[
                    "status"
                ] = "SELECTION_REFERENCES_PARTIALLY_BOUND_EXECUTION_UNVERIFIED"
                combined_execution["execution_verified"] = False
                combined_execution["natural_verified"] = False
                combined_execution.pop("observed_sha256", None)
                combined_execution.pop("receipt_sha256_binding", None)
                # Reasons from the ordinary, unscoped aggregate cannot
                # describe this A+HK composition: keep uncertainty on each
                # market entry and only assert the shared-receipt gap here.
                combined_execution["cannot_confirm"] = [
                    "NO_SINGLE_A_HK_EXECUTION_RECEIPT_FOR_MARKET_SCOPED_READBACK"
                ]
                payload["execution_evidence"] = combined_execution
        return project_shared_selection(ctx.projection,
            payload,
            limit,
            ordinary_hk_display=True,
        )
    return None
