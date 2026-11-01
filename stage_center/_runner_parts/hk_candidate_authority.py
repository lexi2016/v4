"""stage_center.runner: hk_candidate_authority (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __attach_hk_authority_body(_v4_scope, /, source, *, d1_root, second_root, preselection_source_root, trade_date, stage_id, hk_binding):
    """Overlay only exact D-1/second-filter fields onto acquired HK rows.

    Fixed-pool acquisition rows alone do not prove a V3 lane.  D-1 contributes
    membership/metadata only; live minute lanes must come from the separate
    code-bounded snapshot probe.  The 09:25 second-filter is the sole explicit
    pre-open lane source.
    """
    if (
        hk_binding is not None
        and hk_binding.role == "HK_CONNECT_D1_TOP100_PRIOR_VERIFIED_OBSERVATION"
    ):
        d1_path, d1_payload, d1_sha = _v4_global(_v4_scope, '_read_bound_prior_hk_d1_payload')(
            hk_binding,
            d1_root=d1_root,
            preselection_source_root=preselection_source_root,
        )
    else:
        if hk_binding is not None:
            _v4_global(_v4_scope, '_validated_hk_binding_evidence')(hk_binding, trade_date)
        d1_path, d1_sha = _v4_global(_v4_scope, '_validate_hk_d1')(
            d1_root, trade_date, preselection_source_root=preselection_source_root
        )
        if hk_binding is not None and d1_sha != hk_binding.sha256:
            raise _v4_global(_v4_scope, 'RunnerError')("HK D1 exact binding SHA changed before authority overlay")
        d1_payload = _v4_global(_v4_scope, 'json').loads(d1_path.read_text(encoding="utf-8"))
    d1_rows = d1_payload.get("rows", d1_payload.get("data")) or []
    authority: dict[str, Mapping[str, Any]] = {}
    for row in d1_rows:
        if not _v4_global(_v4_scope, 'isinstance')(row, _v4_global(_v4_scope, 'Mapping')):
            continue
        code = _v4_global(_v4_scope, '_normal_code')("HK_CONNECT", row.get("code") or row.get("ts_code") or row.get("stock_code"))
        authority[code] = row
    second: dict[str, Mapping[str, Any]] = {}
    if stage_id == "STAGE_0925" or stage_id in _v4_global(_v4_scope, 'HK_CONTINUATION_STAGES'):
        if second_root is None:
            if stage_id == "STAGE_0925":
                raise _v4_global(_v4_scope, 'RunnerError')("HK 09:25 second-filter root is required")
        else:
            try:
                csv_path, _acceptance, _sha_value = _v4_global(_v4_scope, '_validate_hk_second_filter')(second_root, trade_date)
            except _v4_global(_v4_scope, 'RunnerError'):
                # The continuation lane is an optional overlay for ordinary
                # stages.  A missing/stale exact-date artifact must not make
                # the live stage unusable, and it must never be replaced by
                # a previous date.  STAGE_0925 remains hard-gated below.
                if stage_id == "STAGE_0925":
                    raise
            else:
                with csv_path.open("r", encoding="utf-8-sig", newline="") as stream:
                    for row in _v4_global(_v4_scope, 'csv').DictReader(stream):
                        code = _v4_global(_v4_scope, '_normal_code')("HK_CONNECT", row.get("code") or row.get("ts_code") or row.get("stock_code"))
                        second[code] = row
    rows: list[dict[str, Any]] = []
    payload_model_id = (
        d1_payload.get("model_id")
        or d1_payload.get("model")
        or d1_payload.get("model_name")
        or d1_payload.get("selected_strategy")
        or ""
    )
    payload_d1_status = _v4_global(_v4_scope, 'str')(d1_payload.get("status") or "")

    def _first_present(*values: Any) -> Any:
        for value in values:
            if value not in (None, ""):
                return value
        return ""

    for raw in source.rows:
        code = _v4_global(_v4_scope, '_normal_code')("HK_CONNECT", raw.get("code"))
        merged = _v4_global(_v4_scope, 'dict')(raw)
        base = authority.get(code)
        if base:
            for key, value in base.items():
                if key not in {"code", "ts_code", "stock_code", "candidate_lanes", "source_universe", "lane", "membership_gate_ids"} and value not in (None, ""):
                    merged.setdefault(key, value)
            # D-1 is an exact-date name authority.  Quote bridges may encode
            # a missing name as the symbol itself; treat that placeholder as
            # empty so the authority can replace it.  If the exact authority
            # row has no name, retain a genuinely useful quote name and only
            # fall back to the canonical code when no name exists anywhere.
            authority_name = _v4_global(_v4_scope, 'next')(
                (
                    base.get(key)
                    for key in ("name", "stock_name", "security_name", "display_name")
                    if not _v4_global(_v4_scope, '_is_code_display_name')(base.get(key), code)
                ),
                None,
            )
            if not _v4_global(_v4_scope, '_is_code_display_name')(authority_name, code):
                merged["name"] = authority_name
                merged["stock_name"] = authority_name
            else:
                quote_name = _v4_global(_v4_scope, 'next')(
                    (
                        merged.get(key)
                        for key in ("name", "stock_name", "security_name", "display_name")
                        if not _v4_global(_v4_scope, '_is_code_display_name')(merged.get(key), code)
                    ),
                    code,
                )
                merged["name"] = quote_name
                merged["stock_name"] = quote_name
            merged["d1_status"] = payload_d1_status
            merged["d1_model_id"] = _first_present(
                base.get("model_id"),
                base.get("model"),
                base.get("model_name"),
                base.get("selected_strategy"),
                base.get("weekly_tuning_selected_strategy"),
                payload_model_id,
            )
            merged["d1_prob_active"] = _first_present(
                base.get("prob_active"),
                base.get("probability"),
                base.get("prob_active_score"),
                base.get("score_prob_active"),
                base.get("pool_score"),
            )
            merged["d1_rank"] = _first_present(base.get("pool_rank"), base.get("rank"), base.get("d1_rank"))
            merged["d1_score"] = _first_present(base.get("pool_score"), base.get("score"), base.get("d1_score"))
            merged["d1_source_evidence"] = _v4_global(_v4_scope, 'list')(base.get("source_evidence") or ()) if _v4_global(_v4_scope, 'isinstance')(base.get("source_evidence"), (_v4_global(_v4_scope, 'list'), _v4_global(_v4_scope, 'tuple'))) else []
            if base.get("pool_version"):
                merged["d1_source_evidence"].append(f"hk_d1_pool_version={base['pool_version']}")
            if d1_payload.get("source_sha256"):
                merged["d1_source_evidence"].append(f"hk_d1_source_sha256={d1_payload['source_sha256']}")
        else:
            # A full-market quote row can legitimately have no D-1 metadata;
            # never leave the UI with an empty name in that case.
            quote_name = _v4_global(_v4_scope, 'next')(
                (
                    merged.get(key)
                    for key in ("name", "stock_name", "security_name", "display_name")
                    if not _v4_global(_v4_scope, '_is_code_display_name')(merged.get(key), code)
                ),
                code,
            )
            merged["name"] = quote_name
            merged["stock_name"] = quote_name
        # The active lane is a separate exact live-trigger assertion.  The
        # three static lanes are accepted only from this exact D-1 row;
        # copying arbitrary adapter/static labels would recreate the old bug
        # where a static pool became a realtime recommendation.
        live_lanes = [
            _v4_global(_v4_scope, 'str')(item)
            for item in (raw.get("candidate_lanes") or ())
            if _v4_global(_v4_scope, 'str')(item) == "LIVE_HKCONNECT_GAINER"
        ]
        static_lanes = [
            _v4_global(_v4_scope, 'str')(item)
            for item in (base.get("candidate_lanes") or ())
            if _v4_global(_v4_scope, 'str')(item) in _v4_global(_v4_scope, 'HK_STATIC_LANES')
        ] if base else []
        merged["candidate_lanes"] = _v4_global(_v4_scope, 'list')(_v4_global(_v4_scope, 'dict').fromkeys([*live_lanes, *static_lanes]))
        if code in second:
            second_row = second[code]
            for key, value in second_row.items():
                if key not in {"code", "ts_code", "stock_code"} and value not in (None, ""):
                    merged.setdefault(key, value)
            merged["candidate_lanes"] = _v4_global(_v4_scope, 'list')(_v4_global(_v4_scope, 'dict').fromkeys([*(merged.get("candidate_lanes") or ()), "PREOPEN_AUCTION_CONTINUATION"]))
        rows.append(merged)
    evidence = _v4_global(_v4_scope, 'list')(source.source_evidence)
    evidence.extend(
        (
            "hk_d1_status=STRICT_0_2_READY",
            f"hk_d1_json_sha256={d1_sha}",
            "hk_d1_membership=exact_date_top100",
        )
    )
    if payload_model_id:
        evidence.append(f"hk_d1_model_id={payload_model_id}")
    return _v4_global(_v4_scope, 'replace')(source, rows=_v4_global(_v4_scope, 'tuple')(rows), source_evidence=_v4_global(_v4_scope, 'tuple')(_v4_global(_v4_scope, 'dict').fromkeys(evidence)))
