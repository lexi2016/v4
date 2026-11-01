"""Exact HK override and observation reads.

These five readers were closures inside ``create_app``. They now take an
explicit ``HkVerifyContext`` so their store, consumer and evidence
dependencies are visible at the call site.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from fastapi import HTTPException


@dataclass(frozen=True)
class HkVerifyContext:
    configured_selection_root: Any
    shared_selection_consumer: Any
    read_workbench: Callable[..., dict]
    morning_binding_by_date_stage: Mapping[Any, Any]
    r8_binding_by_date_stage: Mapping[Any, Any]
    r8_pool_evidence: Any
    r9_binding_by_date_stage: Mapping[Any, Any]
    r9_legacy_stale_lane_identities: Any
    r9_legacy_stale_pool_contracts: Any
    r9_pool_evidence: Any


def quarantine_known_hk_auction_pool_mismatch(
    ctx: HkVerifyContext,
    payload: dict, trade_date: str, stage_id: str
) -> dict:
    """Hide only the pinned 10/05 auction artifact proven to use the wrong D1 pool."""
    if (
        trade_date != "20261005"
        or stage_id != "STAGE_0925"
        or ctx.shared_selection_consumer is None
    ):
        return payload
    market = (payload.get("markets") or {}).get("HK_CONNECT")
    if not isinstance(market, Mapping):
        return payload
    try:
        key = ctx.shared_selection_consumer.store._key(trade_date, stage_id, "HK_CONNECT")
        entry = ctx.shared_selection_consumer.store._latest().get("entries", {}).get(key)
    except (OSError, ValueError, TypeError, KeyError):
        return payload
    source_evidence = list(market.get("source_evidence") or ())
    required_source = {
        "candidate_current_sha256=f45233cd1d30d04a8e89c3a08ba8dab4ff63f1d787809b3323307f6f96cb5901",
        "hk_d1_json_sha256=f45233cd1d30d04a8e89c3a08ba8dab4ff63f1d787809b3323307f6f96cb5901",
        "hk_d1_source_trade_date=20260930",
        "hk_observation_trade_date=20261005",
    }
    if (
        not isinstance(entry, Mapping)
        or entry.get("trade_date") != trade_date
        or entry.get("stage_id") != stage_id
        or entry.get("market") != "HK_CONNECT"
        or entry.get("run_id") != "run-6a45f94febaf762962082e81"
        or entry.get("artifact_sha256") != "abea293be53b9114f2835ed94d6e52bdc33a54debe51891f102edcb05102357d"
        or entry.get("manifest_sha256") != "25398bdf783d2916aa8aa64c0581071d99d8c7a85ebbdb8b6fbc3b4dbed08177"
        or entry.get("receipt_sha256") != "8bed1cd1e889cea9fa26c107c159018c2b1614aa0d54029ef1c483c8da0e40dc"
        or market.get("run_id") != entry.get("run_id")
        or not required_source.issubset(set(source_evidence))
    ):
        return payload

    quarantined = dict(market)
    quarantined_rows = list(market.get("rows") or ())
    reasons = list(market.get("cannot_confirm") or ())
    if "HK_D1_TARGET_POOL_MISMATCH" not in reasons:
        reasons.append("HK_D1_TARGET_POOL_MISMATCH")
    quarantined.update(
        {
            "status": "CANNOT_CONFIRM",
            "selection_status": "CANNOT_CONFIRM",
            "selected_rows": None,
            "rows": [],
            "cannot_confirm": reasons,
            "quarantined_source": {
                "status": "CANNOT_CONFIRM",
                "reason": "HK_D1_TARGET_POOL_MISMATCH",
                "artifact_sha256": entry["artifact_sha256"],
                "manifest_sha256": entry["manifest_sha256"],
                "receipt_sha256": entry["receipt_sha256"],
                "artifact_relative": entry.get("artifact_relative"),
                "run_id": entry["run_id"],
                "source_selected_rows": len(quarantined_rows),
                "source_requested_rows": market.get("requested_rows"),
                "source_rows": market.get("source_rows"),
                "source_evidence": source_evidence,
                "source_pool_sha256": "f45233cd1d30d04a8e89c3a08ba8dab4ff63f1d787809b3323307f6f96cb5901",
                "target_pool_sha256": "8799c7ef056981549204ece5958222acad92204bfbf9ba5f12ef26bae57dad01",
                "rows_retained_in_verified_source_artifact": True,
            },
        }
    )
    markets = dict(payload.get("markets") or {})
    markets["HK_CONNECT"] = quarantined
    result = dict(payload)
    result["markets"] = markets
    return result


def read_exact_target_hk_override(
    ctx: HkVerifyContext,
    payload: dict,
    trade_date: str,
    stage_id: str,
    limit: int,
    binding: Mapping[str, Any],
    *,
    source_label: str,
    target_pool_sha256: str,
    superseded_source_reason: str | None = None,
) -> dict:
    try:
        exact = ctx.read_workbench(
            date=trade_date,
            stage=stage_id,
            limit=limit,
            market="HK_CONNECT",
            backfill_run_id=binding["backfill_run_id"],
        )
    except HTTPException as error:
        # These frozen historical composite reads have independently verified
        # A-share trios. An invalid HK override must not hide that A lane;
        # the explicit HK read above still rejects its invalid binding.
        if error.status_code != 409 or (trade_date, stage_id) not in {
            ('20260918', 'STAGE_0930_0935'),
            ('20260918', 'STAGE_0935_0940'),
            ('20260918', 'STAGE_0940_0945'),
            ('20260918', 'STAGE_0945_1030'),
            ('20260918', 'STAGE_1300_1315'),
            ('20260918', 'STAGE_1445_1500'),
            ('20260922', 'STAGE_0935_0940'),
            ('20260922', 'STAGE_0940_0945'),
            ('20260922', 'STAGE_0945_1030'),
            ('20260924', 'STAGE_0930_0935'),
            ('20260924', 'STAGE_1445_1500'),
            ('20260929', 'STAGE_0930_0935'),
            ('20260929', 'STAGE_0935_0940'),
            ('20260929', 'STAGE_0940_0945'),
            ('20260929', 'STAGE_0945_1030'),
            ('20260929', 'STAGE_1300_1315'),
            ('20260929', 'STAGE_1445_1500'),
            ('20260930', 'STAGE_0930_0935'),
            ('20260930', 'STAGE_0935_0940'),
            ('20260930', 'STAGE_0940_0945'),
            ('20260930', 'STAGE_0945_1030'),
            ('20260930', 'STAGE_1300_1315'),
            ('20260930', 'STAGE_1445_1500'),
        }:
            raise
        markets = dict(payload.get("markets") or {})
        a_market = markets.get("A_SHARE")
        if not isinstance(a_market, Mapping) or not (
            a_market.get("selection_manifest_receipt_verified") is True
            and int(a_market.get("selected_rows") or 0) > 0
        ):
            raise
        from stage_center.consumer import _invalid_market_with_reason
        denied = _invalid_market_with_reason(
            "HK_CONNECT", "EXACT_TARGET_HK_BINDING_INVALID"
        )
        denied["cannot_confirm"].append(str(error.detail))
        denied["recovery_provenance"] = {
            "mode": "BACKFILL_BINDING_REJECTED",
            "backfill_run_id": binding["backfill_run_id"],
            "source": source_label,
            "http_status": error.status_code,
        }
        markets["HK_CONNECT"] = denied
        result = dict(payload)
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
        return result
    exact_markets = exact.get("selection_markets")
    exact_hk = exact_markets.get("HK_CONNECT") if isinstance(exact_markets, Mapping) else None
    if not isinstance(exact_hk, Mapping):
        raise HTTPException(status_code=409, detail="approved exact-target HK candidate is unavailable")

    markets = dict(payload.get("markets") or {})
    prior_hk = markets.get("HK_CONNECT")
    hk_market = dict(exact_hk)
    if isinstance(prior_hk, Mapping) and prior_hk.get("run_id") != hk_market.get("run_id"):
        superseded_source = {
            "status": "SUPERSEDED_BY_EXACT_TARGET_D1_RESEARCH_CANDIDATE",
            "displayed_as_valid_observation": False,
            "artifact_id": prior_hk.get("artifact_id"),
            "run_id": prior_hk.get("run_id"),
            "raw_artifact_sha256": prior_hk.get("raw_artifact_sha256"),
            "requested_rows": prior_hk.get("requested_rows"),
            "source_rows": prior_hk.get("source_rows"),
            "selected_rows": prior_hk.get("selected_rows"),
            "source_evidence": list(prior_hk.get("source_evidence") or ()),
        }
        if superseded_source_reason is not None:
            superseded_source["replacement_reason"] = superseded_source_reason
            superseded_source["target_pool_sha256"] = target_pool_sha256
        hk_market["superseded_source"] = superseded_source
    markets["HK_CONNECT"] = hk_market
    result = dict(payload)
    result.update(
        {
            "markets": markets,
            "RESEARCH_ONLY": True,
            "artifact_id": None,
            "bundle_artifact_id": None,
            "run_id": None,
            "market_readback_bindings": {
                "scope": "DATE_STAGE_MARKET_SCOPED_READ_ONLY",
                "trade_date": trade_date,
                "stage_id": stage_id,
                "markets": {
                    "HK_CONNECT": {
                        "source": source_label,
                        "backfill_run_id": binding["backfill_run_id"],
                        "run_id": hk_market.get("run_id"),
                        "requested_rows": hk_market.get("requested_rows"),
                        "source_rows": hk_market.get("source_rows"),
                        "selected_rows": hk_market.get("selected_rows"),
                        "raw_artifact_sha256": hk_market.get("raw_artifact_sha256"),
                        "selection_manifest_sha256": hk_market.get("selection_manifest_sha256"),
                        "runner_receipt_sha256": hk_market.get("runner_receipt_sha256"),
                        "target_pool_sha256": target_pool_sha256,
                    }
                },
                "single_bundle_artifact_id": None,
            },
        }
    )
    if binding.get("requested_rows") is not None:
        result["market_readback_bindings"]["markets"]["HK_CONNECT"].update(
            {
                "candidate_batch_receipt_sha256": binding[
                    "candidate_batch_receipt_sha256"
                ],
                "candidate_receipt_sha256": binding[
                    "candidate_receipt_sha256"
                ],
                "candidate_manifest_sha256": binding[
                    "candidate_manifest_sha256"
                ],
                "candidate_source_evidence_sha256": binding[
                    "source_evidence_sha256"
                ],
                "missing_rows": binding["missing_rows"],
                "missing_codes": list(binding["missing_codes"]),
                "missing_reason_by_code": dict(
                    binding["missing_reason_by_code"]
                ),
            }
        )
    prior_execution = dict(payload.get("execution_evidence") or {})
    execution_markets = dict(prior_execution.get("markets") or {})
    exact_execution = exact.get("execution_evidence")
    exact_execution_markets = (
        exact_execution.get("markets") if isinstance(exact_execution, Mapping) else None
    )
    exact_execution_hk = (
        exact_execution_markets.get("HK_CONNECT")
        if isinstance(exact_execution_markets, Mapping)
        else None
    )
    if isinstance(exact_execution_hk, Mapping):
        execution_markets["HK_CONNECT"] = dict(exact_execution_hk)
    else:
        execution_markets["HK_CONNECT"] = {
            "status": "SELECTION_REFERENCES_PARTIALLY_BOUND_EXECUTION_UNVERIFIED",
            "selection_binding": "BOUND_TO_VERIFIED_SELECTION",
            "runner_receipt_verified": hk_market.get("runner_receipt_verified") is True,
            "runner_receipt_sha256": hk_market.get("runner_receipt_sha256"),
            "execution_verified": False,
            "natural_verified": False,
            "cannot_confirm": [
                "HK_BACKFILL_EXECUTION_MARKET_DETAILS_NOT_EXPOSED_BY_SELECTION_CONSUMER"
            ],
        }
    prior_execution.update(
        {
            "markets": execution_markets,
            "scope": "READ_ONLY_MARKET_SCOPED_SELECTION_COMPOSITION",
            "status": "SELECTION_REFERENCES_PARTIALLY_BOUND_EXECUTION_UNVERIFIED",
            "execution_verified": False,
            "natural_verified": False,
            "cannot_confirm": [
                "NO_SINGLE_A_HK_EXECUTION_RECEIPT_FOR_MARKET_SCOPED_READBACK"
            ],
        }
    )
    prior_execution.pop("observed_sha256", None)
    prior_execution.pop("receipt_sha256_binding", None)
    result["execution_evidence"] = prior_execution
    return result


def read_r8_exact_target_hk_override(
    ctx: HkVerifyContext,
    payload: dict, trade_date: str, stage_id: str, limit: int
) -> dict | None:
    binding = ctx.r8_binding_by_date_stage.get((trade_date, stage_id))
    if binding is None:
        return None
    return read_exact_target_hk_override(ctx,
        payload,
        trade_date,
        stage_id,
        limit,
        binding,
        source_label="APPROVED_EXACT_TARGET_D1_AFTERFACT_CANDIDATE_R8",
        target_pool_sha256=ctx.r8_pool_evidence[trade_date]["pool_sha256"],
    )


def read_r9_exact_target_hk_override(
    ctx: HkVerifyContext,
    payload: dict, trade_date: str, stage_id: str, limit: int
) -> dict | None:
    binding = ctx.r9_binding_by_date_stage.get((trade_date, stage_id))
    if binding is None:
        return None
    markets = payload.get("markets")
    prior_hk = markets.get("HK_CONNECT") if isinstance(markets, Mapping) else None
    rows = prior_hk.get("rows") if isinstance(prior_hk, Mapping) else None
    legacy_stale = ctx.r9_legacy_stale_lane_identities.get(
        (trade_date, stage_id)
    )
    replace_for_legacy_pool_mismatch = False
    if isinstance(prior_hk, Mapping):
        # R9 may repair a missing lane or replace a verified nonempty lane
        # only when its exact pool provenance proves it belongs to a
        # different target pool. Preserve an effective ordinary result
        # when it is already bound to this date's target pool. If the
        # consumer found this exact R9 backfill run because no ordinary
        # lane existed, apply the exact route binding without marking that
        # same candidate as a superseded source.
        if prior_hk.get("backfill_run_id") == binding["backfill_run_id"]:
            replace_existing = True
        elif (
            rows == []
            and prior_hk.get("status") == "CANNOT_CONFIRM"
            and prior_hk.get("selected_rows") in (None, 0)
        ):
            replace_existing = True
        elif isinstance(rows, list) and rows and legacy_stale is not None:
            legacy_contract = ctx.r9_legacy_stale_pool_contracts.get(trade_date)
            target_pool = ctx.r9_pool_evidence.get(trade_date)
            evidence = prior_hk.get("source_evidence")

            def marker_values(name: str) -> list[str]:
                prefix = f"{name}="
                return [
                    marker.partition("=")[2]
                    for marker in evidence
                    if isinstance(marker, str) and marker.startswith(prefix)
                ] if isinstance(evidence, list) else []

            def marker_matches(name: str, expected: str | None) -> bool:
                values = marker_values(name)
                return values == ([expected] if expected is not None else [])

            try:
                latest = ctx.shared_selection_consumer.store._latest()
                latest_key = ctx.shared_selection_consumer.store._key(
                    trade_date, stage_id, "HK_CONNECT"
                )
                current_entry = latest.get("entries", {}).get(latest_key)
            except (AttributeError, OSError, ValueError, TypeError, KeyError):
                current_entry = None

            observation_count = prior_hk.get("observation_count")
            selected_rows = prior_hk.get("selected_rows")
            count_evidence = (
                observation_count
                if isinstance(observation_count, int)
                and not isinstance(observation_count, bool)
                else selected_rows
            )
            count_matches = (
                isinstance(count_evidence, int)
                and not isinstance(count_evidence, bool)
                and count_evidence == legacy_stale["observation_count"]
                and len(rows) == count_evidence
                and (
                    observation_count is None
                    or observation_count == count_evidence
                )
                and (selected_rows is None or selected_rows == count_evidence)
            )
            entry_matches = isinstance(current_entry, Mapping) and all(
                current_entry.get(field) == expected
                for field, expected in (
                    ("trade_date", trade_date),
                    ("stage_id", stage_id),
                    ("market", "HK_CONNECT"),
                    ("run_id", legacy_stale["run_id"]),
                    ("artifact_sha256", legacy_stale["selection_artifact_sha256"]),
                    ("manifest_sha256", legacy_stale["selection_manifest_sha256"]),
                    ("receipt_sha256", legacy_stale["selection_receipt_sha256"]),
                )
            ) and all(
                current_entry.get(flag) is False
                for flag in ("production_allowed", "buy_gate_updated", "orders_sent")
            )
            target_matches = (
                isinstance(target_pool, Mapping)
                and binding.get("pool_artifact_sha256") == target_pool.get("pool_sha256")
                and binding.get("pool_path") == target_pool.get("pool_path")
                and binding.get("pool_signal_date") == target_pool.get("signal_date")
                and target_pool.get("source_date") == trade_date
                and target_pool.get("pool_sha256") != legacy_contract.get("pool_sha256")
            ) if isinstance(legacy_contract, Mapping) else False
            legacy_source_matches = (
                isinstance(legacy_contract, Mapping)
                and marker_matches("hk_d1_sha256", legacy_contract.get("pool_sha256"))
                and marker_matches("hk_d1_json_sha256", legacy_contract.get("pool_sha256"))
                and marker_matches("hk_d1_json", legacy_contract.get("pool_path"))
                and marker_matches(
                    "hk_d1_source_trade_date",
                    legacy_contract.get("source_trade_date"),
                )
                and marker_matches(
                    "hk_d1_source_signal_date",
                    legacy_contract.get("source_signal_date"),
                )
                and marker_matches(
                    "hk_d1_binding_sha256",
                    legacy_contract.get("binding_sha256"),
                )
            )
            optional_display_mode = prior_hk.get("display_mode")
            replace_for_legacy_pool_mismatch = all(
                (
                    trade_date in ctx.r9_legacy_stale_pool_contracts,
                    prior_hk.get("run_id") == legacy_stale["run_id"],
                    prior_hk.get("artifact_id") == legacy_stale["artifact_id"],
                    prior_hk.get("raw_artifact_sha256") == legacy_stale["raw_artifact_sha256"],
                    prior_hk.get("status") in {"READY", "PARTIAL_WITH_ROWS"},
                    prior_hk.get("selection_status", "PARTIAL_WITH_ROWS")
                    in {"READY", "PARTIAL_WITH_ROWS"},
                    optional_display_mode in (None, "OBSERVATION_UNVERIFIED"),
                    prior_hk.get("requested_rows") == legacy_stale["requested_rows"],
                    prior_hk.get("source_rows") == legacy_stale["source_rows"],
                    entry_matches,
                    target_matches,
                    legacy_source_matches,
                    count_matches,
                )
            )
            replace_existing = replace_for_legacy_pool_mismatch
        elif (
            isinstance(rows, list)
            and rows
            and prior_hk.get("status") in {"READY", "PARTIAL_WITH_ROWS"}
            and prior_hk.get("selected_rows") == len(rows)
        ):
            source_evidence = prior_hk.get("source_evidence")
            pool_markers = [
                marker.partition("=")[2]
                for marker in source_evidence
                if isinstance(marker, str)
                and marker.startswith("historical_pool_artifact_sha256=")
            ] if isinstance(source_evidence, list) else []
            existing_pool_sha256 = pool_markers[0] if len(pool_markers) == 1 else ""
            is_sha256 = (
                len(existing_pool_sha256) == 64
                and all(character in "0123456789abcdefABCDEF" for character in existing_pool_sha256)
            )
            replace_existing = (
                is_sha256
                and existing_pool_sha256.lower()
                != str(binding["pool_artifact_sha256"]).lower()
            )
        else:
            replace_existing = False
        if not replace_existing:
            return None
    return read_exact_target_hk_override(ctx,
        payload,
        trade_date,
        stage_id,
        limit,
        binding,
        source_label=(
            "APPROVED_MONTH_HK_EXACT_TARGET_D1_AFTERFACT_R9_LEGACY_POOL_REPAIR"
            if replace_for_legacy_pool_mismatch
            else "APPROVED_MONTH_HK_EXACT_TARGET_D1_AFTERFACT_R9"
        ),
        target_pool_sha256=binding["pool_artifact_sha256"],
        superseded_source_reason=(
            "EXACT_PINNED_LEGACY_HK_D1_POOL_MISMATCH"
            if replace_for_legacy_pool_mismatch
            else None
        ),
    )


def read_hk_morning_selection_recovery_override(
    ctx: HkVerifyContext,
    payload: dict,
    trade_date: str,
    stage_id: str,
    limit: int,
) -> dict | None:
    binding = ctx.morning_binding_by_date_stage.get(
        (trade_date, stage_id)
    )
    if binding is None:
        return None
    try:
        from stage_center.selection import SelectionStore

        if ctx.configured_selection_root is None:
            return None
        store = SelectionStore(ctx.configured_selection_root)
        original = store.read_verified(trade_date, stage_id, "HK_CONNECT")
        verified = store._verify_run(
            trade_date, stage_id, "HK_CONNECT", binding["selection_run_id"]
        )
        if not isinstance(original, Mapping):
            return None
        original_rows = original.get("rows")
        if (
            original.get("run_id") != binding["selection_run_id"]
            or original.get("artifact_id") != binding["artifact_id"]
            or original.get("raw_artifact_sha256") != binding["raw_artifact_sha256"]
            or original.get("algorithm_id") != binding["algorithm_id"]
            or original.get("algorithm_sha256") != binding["algorithm_sha256"]
            or original.get("source_status") != "CANNOT_CONFIRM"
            or original.get("selection_status") != "PARTIAL_WITH_ROWS"
            or original.get("requested_rows") != 100
            or original.get("source_rows") != 100
            or original.get("selected_rows") != 10
            or original.get("missing_symbols")
            or original.get("cannot_confirm") != ["HK_ACTIVE_SNAPSHOT_UNAVAILABLE"]
            or not isinstance(original_rows, list)
            or len(original_rows) != 10
        ):
            return None
        if (
            verified.get("manifest_sha256") != binding["original_manifest_sha256"]
            or verified.get("receipt_sha256") != binding["original_receipt_sha256"]
            or verified.get("artifact_sha256") != binding["selection_artifact_sha256"]
        ):
            return None
        markets = payload.get("markets")
        prior_hk = markets.get("HK_CONNECT") if isinstance(markets, Mapping) else None
        if isinstance(prior_hk, Mapping) and any(
            prior_hk.get(field) not in (None, expected)
            for field, expected in (
                ("run_id", binding["selection_run_id"]),
                ("artifact_id", binding["artifact_id"]),
                ("raw_artifact_sha256", binding["raw_artifact_sha256"]),
            )
        ):
            return None
        # The ordinary consumer hides rows for CANNOT_CONFIRM. Reattach the
        # verified exact identity only for supersession comparison; the
        # exact backfill route supplies the displayed observation rows.
        payload = dict(payload)
        markets = dict(markets or {})
        markets["HK_CONNECT"] = {
            "market": "HK_CONNECT",
            "status": original["selection_status"],
            "selection_status": original["selection_status"],
            "source_status": original["source_status"],
            "artifact_id": original["artifact_id"],
            "run_id": original["run_id"],
            "raw_artifact_sha256": original["raw_artifact_sha256"],
            "requested_rows": original["requested_rows"],
            "source_rows": original["source_rows"],
            "selected_rows": original["selected_rows"],
            "source_evidence": list(original.get("source_evidence") or []),
            "missing_symbols": list(original.get("missing_symbols") or []),
            "cannot_confirm": list(original.get("cannot_confirm") or []),
            "rows": list(original_rows),
        }
        payload["markets"] = markets
        result = read_exact_target_hk_override(ctx,
            payload,
            trade_date,
            stage_id,
            limit,
            {
                "backfill_run_id": binding["backfill_run_id"],
                # The candidate is an exact selection-row projection; it does
                # not claim a new full-pool acquisition or missing-code list.
                "requested_rows": None,
            },
            source_label="HK_MORNING_PRECAPTURE_OBSERVATION_REPROJECTION_R1",
            target_pool_sha256="78646320d1140bb574b6aee66c9bd6b51f57ca0797fd96e4f2775e245a57efd8",
        )
        result["markets"]["HK_CONNECT"]["trade_date"] = trade_date
        result["markets"]["HK_CONNECT"]["stage_id"] = stage_id
        return result
    except (OSError, ValueError, TypeError, KeyError):
        return None
    except HTTPException as error:
        if error.status_code in {404, 409}:
            return None
        raise
