"""stage_center.live_collectors: selection_builder_registry (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _production_selection_builders_body(_v4_scope, /, stage_id, *, research_root, morning_root):
    """Build selection transforms from the package's frozen V3 pure formulas."""
    from stage_center.selection import select_a_0925_auction, select_a_stage, select_hk_0925_second_filter, select_hk_four_lane

    top10_contract_evidence = "selection_contract=V3_TOP10_RECOMMENDATION"
    research_stages = {
        "STAGE_0930_0935",
        "STAGE_0935_0940",
        "STAGE_0940_0945",
        "STAGE_0945_1030",
        "STAGE_1300_1315",
        "STAGE_1445_1500",
    }

    def a_builder(source: SourceResult, plan: AcquisitionPlan, raw: Mapping[str, Any]) -> Mapping[str, Any]:
        if stage_id == "STAGE_0925":
            rows = [
                {
                    "code": row.get("code"),
                    "name": row.get("name") or row.get("stock_name"),
                    "stock_name": row.get("stock_name") or row.get("name"),
                    "time": row.get("update_time"),
                    "amount": row.get("turnover"),
                    "open_price": row.get("open_price"),
                    "last_price": row.get("last_price"),
                    "high_price": row.get("high_price"),
                    "low_price": row.get("low_price"),
                    "update_time": row.get("update_time"),
                    "next_validation_time": raw.get("cutoff_at"),
                    "trade_date": plan.trade_date,
                }
                for row in source.rows
            ]
            return select_a_0925_auction(rows, plan.trade_date, _v4_global(_v4_scope, 'str')(raw["artifact_sha256"]), source_status=raw["status"], requested_rows=raw["requested_rows"], missing_symbols=raw["missing_symbols"], cannot_confirm=raw["cannot_confirm"], source_evidence=_v4_global(_v4_scope, 'tuple')(_v4_global(_v4_scope, 'dict').fromkeys((*raw["source_evidence"], *source.source_evidence, top10_contract_evidence))))
        research_context = None
        context_root = research_root or raw.get("_v4_research_data_root")
        if stage_id in research_stages and context_root is None:
            raise _v4_global(_v4_scope, 'ValueError')(
                f"V4 research data root is required for {stage_id} A_SHARE"
            )
        if stage_id in research_stages:
            from stage_center.research_context import ResearchContextError, load_research_context

            try:
                research_context = load_research_context(
                    context_root,
                    trade_date=plan.trade_date,
                    stage_cutoff=_v4_global(_v4_scope, 'str')(raw.get("cutoff_at") or ""),
                    morning_root=(
                        morning_root
                        if morning_root is not None
                        else raw.get("_v4_morning_news_root")
                    ),
                )
            except ResearchContextError:
                # The runner catches ValueError and publishes a fail-closed
                # receipt.  Never fall back to a current V3.5 score or a
                # future hourly slot when the frozen V3 evidence is invalid.
                raise
        rows = []
        for index, row in _v4_global(_v4_scope, 'enumerate')(source.rows, start=1):
            # ``select_a_live_stage`` is the Windows V3 authority.  Preserve
            # the exact qmt field names and amount/price semantics rather than
            # silently switching to the older minute-bar score.
            # A raw collector row is not a formal-pool authority.  The runner
            # marks rows only after its exact-date formal attach step has
            # verified membership; inherited ``formal_eligible`` values and
            # lane evidence remain untrusted source data.
            formal_overlay_verified = _v4_global(_v4_scope, '_has_runner_verified_formal_overlay')(row)
            formal_value = row.get("formal_eligible", False)
            formal_eligible = formal_overlay_verified and _v4_global(_v4_scope, 'str')(formal_value).strip().lower() in {"true", "1", "yes"}
            lane_evidence = _v4_global(_v4_scope, 'list')(row.get("lane_evidence") or ())
            if formal_eligible:
                lane_evidence.append("A_SHARE_FORMAL_POOL")
            else:
                # The raw adapter may carry a stale formal marker.  Formal
                # identity is granted only by the exact-date authority
                # overlay, never by inherited source evidence.
                lane_evidence = [item for item in lane_evidence if item != "A_SHARE_FORMAL_POOL"]
                lane_evidence.append("STAGE_ACQUISITION_UNIVERSE")
            candidate_score = row.get("pool_score") if formal_eligible else None
            if candidate_score in (None, ""):
                candidate_score = None
            research = None
            if research_context is not None:
                code_key = _v4_global(_v4_scope, '_canonical_a_code')(row.get("code") or row.get("stock_code"))
                research = research_context.by_code.get(code_key)
                if research is None:
                    # An exact-date archive that has no entry for a candidate
                    # code cannot prove a research value.  Keep that absence
                    # visible at the stage envelope instead of allowing the
                    # selection helper's numeric defaults to look observed.
                    research_context_gap = f"RESEARCH_CONTEXT_CODE_MISSING:{code_key or row.get('code')}"
                else:
                    missing_fields = _v4_global(_v4_scope, 'tuple')(
                        field
                        # Delta is explanatory metadata, not an input to
                        # selection.py's unchanged two-score bonus formula.
                        # Its absence remains in context.cannot_confirm.
                        for field in (
                            "news_quality_score",
                            "research_quality_score",
                        )
                        if _v4_global(_v4_scope, 'getattr')(research, field) is None
                    )
                    research_context_gap = (
                        f"RESEARCH_CONTEXT_FIELDS_MISSING:{code_key or row.get('code')}:{','.join(missing_fields)}"
                        if missing_fields
                        else None
                    )
            else:
                research_context_gap = None
            rows.append({
                "code": row.get("code"),
                "name": row.get("name") or row.get("stock_name"),
                "stock_name": row.get("stock_name") or row.get("name"),
                "formal_eligible": formal_eligible,
                "formal_rank": row.get("formal_rank", "") if formal_eligible else "",
                "candidate": {"score": candidate_score},
                "qmt": {
                    "open": row.get("open_price"),
                    "lastPrice": row.get("last_price"),
                    "lastClose": row.get("prev_close_price"),
                    "high": row.get("high_price"),
                    "low": row.get("low_price"),
                    "amount": row.get("turnover"),
                    "bidVol": [row.get("bid_vol")],
                    "askVol": [row.get("ask_vol")],
                },
                "open_price": row.get("open_price"),
                "last_price": row.get("last_price"),
                "high_price": row.get("high_price"),
                "low_price": row.get("low_price"),
                "update_time": row.get("update_time"),
                "next_validation_time": raw.get("cutoff_at"),
                "trade_date": plan.trade_date,
                "stage_id": plan.stage_id,
                "lane_evidence": _v4_global(_v4_scope, 'list')(_v4_global(_v4_scope, 'dict').fromkeys((*lane_evidence, "PYTDX_EXACT_STAGE_ADAPTER"))),
                "acquisition_rank": row.get("acquisition_rank", row.get("batch_index", index)),
                "news_quality_score": research.news_quality_score if research is not None else None,
                "research_quality_score": research.research_quality_score if research is not None else None,
                "latest_research_slot": research.latest_research_slot if research is not None else "",
                "research_delta_hits": research.research_delta_hits if research is not None else None,
                "news_research_reason": "；".join(research.news_research_reason) if research is not None else "",
                "source_health": research.source_health if research is not None else "CANNOT_CONFIRM",
                "_research_context_gap": research_context_gap,
            })
        from stage_center.selection import _selection_identity_ids, select_a_live_stage
        research_evidence = research_context.source_evidence if research_context is not None else ()
        formal_overlay_supplied = _v4_global(_v4_scope, 'any')(_v4_global(_v4_scope, '_has_runner_verified_formal_overlay')(row) for row in source.rows)
        context_gaps = _v4_global(_v4_scope, 'list')(research_context.cannot_confirm if research_context is not None else ())
        if not formal_overlay_supplied:
            context_gaps.append("FORMAL_OVERLAY_CANNOT_CONFIRM")
        context_gaps.extend(
            _v4_global(_v4_scope, 'str')(row["_research_context_gap"])
            for row in rows
            if row.get("_research_context_gap")
        )
        source_status = (
            "CANNOT_CONFIRM"
            if context_gaps
            else raw["status"]
        )
        formal_evidence = (
            "formal_overlay=EXACT_DATE_AUTHORITY"
            if formal_overlay_supplied
            else "formal_overlay=CANNOT_CONFIRM"
        )
        envelope = select_a_live_stage(rows, plan.trade_date, plan.stage_id, _v4_global(_v4_scope, 'str')(raw["artifact_sha256"]), source_status=source_status, requested_rows=raw["requested_rows"], missing_symbols=raw["missing_symbols"], cannot_confirm=_v4_global(_v4_scope, 'tuple')(_v4_global(_v4_scope, 'dict').fromkeys((*raw["cannot_confirm"], *context_gaps))), source_evidence=_v4_global(_v4_scope, 'tuple')(_v4_global(_v4_scope, 'dict').fromkeys((*raw["source_evidence"], *source.source_evidence, *research_evidence, formal_evidence, top10_contract_evidence))))
        original_by_code = {
            _v4_global(_v4_scope, 'str')(row.get("code") or row.get("stock_code") or "").strip().upper(): row
            for row in rows
        }
        for selected in envelope.get("rows", ()):
            original = original_by_code.get(
                _v4_global(_v4_scope, 'str')(selected.get("code") or selected.get("stock_code") or "").strip().upper()
            )
            if original is None or not original.get("_research_context_gap"):
                continue
            # ``select_a_live_stage`` retains its historical numeric scoring
            # formula, but a missing research scalar must not be serialized as
            # an observed zero in the fail-closed envelope.
            for field in (
                "news_quality_score",
                "research_quality_score",
                "research_delta_hits",
                "latest_research_slot",
                "news_research_reason",
                "source_health",
            ):
                selected[field] = original.get(field)
            selected["research_bonus"] = None
            selected.pop("_research_context_gap", None)
        for row in rows:
            row.pop("_research_context_gap", None)
        # The projection above changes the serialized rows after
        # ``select_a_live_stage`` has initially calculated its identity.  Bind
        # the existing immutable identity helper to the final rows so the
        # publisher and reader validate exactly the bytes being published.
        artifact_id, run_id = _selection_identity_ids(
            plan.trade_date,
            plan.stage_id,
            "A_SHARE",
            _v4_global(_v4_scope, 'str')(envelope["raw_artifact_sha256"]),
            _v4_global(_v4_scope, 'str')(envelope["algorithm_sha256"]),
            _v4_global(_v4_scope, 'list')(envelope.get("rows") or ()),
        )
        envelope["artifact_id"] = artifact_id
        envelope["run_id"] = run_id
        return envelope

    def hk_builder(source: SourceResult, plan: AcquisitionPlan, raw: Mapping[str, Any]) -> Mapping[str, Any]:
        rows = []
        d1_evidence: list[str] = _v4_global(_v4_scope, 'list')(source.source_evidence)
        for row in source.rows:
            previous = _v4_global(_v4_scope, '_safe_number')(row.get("prev_close_price"))
            last = _v4_global(_v4_scope, '_safe_number')(row.get("last_price"))
            pct = ((last - previous) / previous * 100.0) if previous and last is not None else None
            # The acquisition row does not assert a lane.  The runner adds
            # D-1/second-filter metadata before invoking this transform; an
            # empty lane list therefore stays empty and cannot become a
            # fabricated LIVE_HKCONNECT_GAINER.
            rows.append({
                "code": row.get("code"),
                "name": row.get("name") or row.get("stock_name"),
                "stock_name": row.get("stock_name") or row.get("name"),
                "candidate_lanes": _v4_global(_v4_scope, 'list')(row.get("candidate_lanes") or ()),
                "candidate_bucket": row.get("candidate_bucket", ""),
                "trade_status_contract": row.get("trade_status_contract", ""),
                "second_filter_rank": row.get("second_filter_rank", ""),
                "second_filter_score": row.get("second_filter_score", ""),
                "second_filter_status": row.get("second_filter_status", ""),
                "second_filter_action_level": row.get("second_filter_action_level", ""),
                "pct_chg": pct,
                "turnover": row.get("turnover"),
                "turnover_hkd": row.get("turnover"),
                "volume_ratio": row.get("volume_ratio"),
                "turnover_rate": row.get("turnover_rate"),
                "platform_circular_market_cap_hkd_yi": row.get("platform_circular_market_cap_hkd_yi"),
                "offer_float_market_cap_hkd_yi": row.get("offer_float_market_cap_hkd_yi"),
                "stage_window_change_pct": row.get("stage_window_change_pct"),
                "open_price": row.get("open_price"),
                "last_price": row.get("last_price"),
                "high_price": row.get("high_price"),
                "low_price": row.get("low_price"),
                "update_time": row.get("update_time"),
                "next_validation_time": raw.get("cutoff_at"),
                "stage_id": plan.stage_id,
                # These fields are copied from the exact-date D-1 authority
                # by the runner. They remain selection-envelope metadata and
                # never alter the four-lane score.
                "d1_status": row.get("d1_status", row.get("strict_0_2_status", "")),
                "d1_model_id": row.get("d1_model_id", row.get("model_id", row.get("model", ""))),
                "d1_prob_active": row.get("d1_prob_active", row.get("prob_active", "")),
                "d1_rank": row.get("d1_rank", row.get("pool_rank", row.get("rank", ""))),
                "d1_score": row.get("d1_score", row.get("pool_score", row.get("score", ""))),
                "d1_source_evidence": _v4_global(_v4_scope, 'list')(row.get("d1_source_evidence") or ()),
            })
            model_id = rows[-1].get("d1_model_id")
            d1_status = rows[-1].get("d1_status")
            if model_id:
                d1_evidence.append(f"hk_d1_model_id={model_id}")
            if d1_status:
                d1_evidence.append(f"hk_d1_status={d1_status}")
            d1_evidence.extend(_v4_global(_v4_scope, 'str')(item) for item in rows[-1]["d1_source_evidence"] if _v4_global(_v4_scope, 'str')(item))
        d1_evidence = _v4_global(_v4_scope, 'list')(_v4_global(_v4_scope, 'dict').fromkeys(d1_evidence))
        # Full-market ExHQ rows alone do not prove a V3 lane.  Inactive rows
        # remain in raw acquisition for coverage, but are excluded from the
        # selection-only copy.  This preserves the old V3 behavior where the
        # live trigger defines the minute candidate set rather than allowing a
        # single inactive member to erase otherwise verified active rows.
        if stage_id == "STAGE_0925":
            active_rows = [item for item in rows if item["candidate_lanes"]]
        else:
            active_rows = [
                item
                for item in rows
                if "LIVE_HKCONNECT_GAINER" in item["candidate_lanes"]
            ]
        if not active_rows:
            if (
                rows
                and source.status == "PARTIAL_WITH_ROWS"
                and "active_snapshot_degraded_to_pytdx_observation=true"
                in source.source_evidence
            ):
                # This is the established historical observation contract: the
                # exact raw rows are useful for a Top-10 watch list even when
                # the live snapshot cutoff is unsafe.  Do not manufacture a
                # LIVE_HKCONNECT_GAINER lane or refresh the snapshot here.
                return select_hk_four_lane(
                    rows,
                    plan.trade_date,
                    plan.stage_id,
                    _v4_global(_v4_scope, 'str')(raw["artifact_sha256"]),
                    source_status="PARTIAL_WITH_ROWS",
                    requested_rows=raw.get("requested_rows", source.requested_rows),
                    missing_symbols=_v4_global(_v4_scope, 'tuple')(
                        _v4_global(_v4_scope, 'dict').fromkeys(
                            (
                                *source.missing_symbols,
                                *raw.get("missing_symbols", ()),
                            )
                        )
                    ),
                    cannot_confirm=_v4_global(_v4_scope, 'tuple')(
                        _v4_global(_v4_scope, 'dict').fromkeys(
                            (
                                *source.cannot_confirm,
                                *raw.get("cannot_confirm", ()),
                            )
                        )
                    ),
                    source_evidence=_v4_global(_v4_scope, 'tuple')(
                        _v4_global(_v4_scope, 'dict').fromkeys(
                            (
                                *raw.get("source_evidence", ()),
                                *source.source_evidence,
                                *d1_evidence,
                                top10_contract_evidence,
                                "hk_lane_authority_missing",
                                "hk_selection_mode=TDXPY_EXHQ_D1_TOP100_OBSERVATION",
                            )
                        )
                    ),
                )
            return select_hk_four_lane(
                [],
                plan.trade_date,
                plan.stage_id,
                _v4_global(_v4_scope, 'str')(raw["artifact_sha256"]),
                source_status="CANNOT_CONFIRM",
                requested_rows=raw.get("requested_rows"),
                missing_symbols=raw.get("missing_symbols", ()),
                cannot_confirm=(*raw.get("cannot_confirm", ()), "HK_LANE_EVIDENCE_MISSING"),
                source_evidence=(*raw.get("source_evidence", ()), *d1_evidence, top10_contract_evidence, "hk_lane_authority_missing"),
            )
        if _v4_global(_v4_scope, 'len')(active_rows) < _v4_global(_v4_scope, 'len')(rows):
            missing = _v4_global(_v4_scope, 'tuple')(_v4_global(_v4_scope, 'dict').fromkeys((*raw.get("missing_symbols", ()), *(_v4_global(_v4_scope, 'str')(item.get("code")) for item in rows if not item["candidate_lanes"]))))
            return select_hk_four_lane(
                active_rows,
                plan.trade_date,
                plan.stage_id,
                _v4_global(_v4_scope, 'str')(raw["artifact_sha256"]),
                source_status="PARTIAL_WITH_ROWS",
                requested_rows=raw.get("requested_rows"),
                missing_symbols=missing,
                cannot_confirm=raw.get("cannot_confirm", ()),
                source_evidence=_v4_global(_v4_scope, 'tuple')(_v4_global(_v4_scope, 'dict').fromkeys((*raw.get("source_evidence", ()), *d1_evidence, top10_contract_evidence))),
            )
        if stage_id == "STAGE_0925":
            return select_hk_0925_second_filter(rows, plan.trade_date, _v4_global(_v4_scope, 'str')(raw["artifact_sha256"]), source_status=raw["status"], requested_rows=raw["requested_rows"], missing_symbols=raw["missing_symbols"], cannot_confirm=raw["cannot_confirm"], source_evidence=_v4_global(_v4_scope, 'tuple')(_v4_global(_v4_scope, 'dict').fromkeys((*raw["source_evidence"], *d1_evidence, top10_contract_evidence))))
        final_rows = active_rows if stage_id == "STAGE_1545_1555" else rows
        return select_hk_four_lane(final_rows, plan.trade_date, plan.stage_id, _v4_global(_v4_scope, 'str')(raw["artifact_sha256"]), source_status=raw["status"], requested_rows=raw["requested_rows"], missing_symbols=raw["missing_symbols"], cannot_confirm=raw["cannot_confirm"], source_evidence=_v4_global(_v4_scope, 'tuple')(_v4_global(_v4_scope, 'dict').fromkeys((*raw["source_evidence"], *d1_evidence, top10_contract_evidence))))

    if stage_id == "STAGE_1545_1555":
        return {"HK_CONNECT": hk_builder}
    return {"A_SHARE": a_builder, "HK_CONNECT": hk_builder}
