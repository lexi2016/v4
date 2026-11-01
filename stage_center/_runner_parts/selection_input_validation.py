"""stage_center.runner: selection_input_validation (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __validate_formal_input_body(_v4_scope, /, root, trade_date):
    csv_path, manifest_path = _v4_global(_v4_scope, '_required_formal_paths')(root, trade_date)
    try:
        manifest = _v4_global(_v4_scope, 'json').loads(manifest_path.read_text(encoding="utf-8-sig"))
    except (_v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'UnicodeError'), _v4_global(_v4_scope, 'ValueError')) as error:
        raise _v4_global(_v4_scope, 'RunnerError')("V3 formal manifest unreadable") from error
    if manifest.get("trade_date") != trade_date or manifest.get("status") not in {"FORMAL_CONFIRMED", "FORMAL_READY"}:
        raise _v4_global(_v4_scope, 'RunnerError')("V3 formal pool identity/status mismatch")
    with csv_path.open("r", encoding="utf-8-sig", newline="") as stream:
        rows = _v4_global(_v4_scope, 'list')(_v4_global(_v4_scope, 'csv').DictReader(stream))
    eligible = [row for row in rows if _v4_global(_v4_scope, 'str')(row.get("eligible_for_formal_pool") or "").lower() in {"true", "1", "yes"}]
    if not eligible:
        raise _v4_global(_v4_scope, 'RunnerError')("V3 formal pool has no eligible rows")
    raw_codes = [_v4_global(_v4_scope, 'str')(row.get("ts_code") or row.get("stock_code") or "").strip().upper() for row in eligible]
    normalized_codes = [f"A.{match.group(1)}" for raw in raw_codes if (match := _v4_global(_v4_scope, 're').search(r"(\d{6})", raw))]
    if _v4_global(_v4_scope, 'len')(normalized_codes) != _v4_global(_v4_scope, 'len')(eligible) or _v4_global(_v4_scope, 'len')(_v4_global(_v4_scope, 'set')(normalized_codes)) != _v4_global(_v4_scope, 'len')(normalized_codes):
        raise _v4_global(_v4_scope, 'RunnerError')("V3 formal pool eligible membership must be non-empty and unique")
    if _v4_global(_v4_scope, 'int')(manifest.get("row_count", -1)) != _v4_global(_v4_scope, 'len')(rows):
        raise _v4_global(_v4_scope, 'RunnerError')("V3 formal pool manifest row_count mismatch")
    manifest_sha = manifest.get("csv_sha256")
    if not _v4_global(_v4_scope, 'isinstance')(manifest_sha, _v4_global(_v4_scope, 'str')) or _v4_global(_v4_scope, 're').fullmatch(r"[0-9a-fA-F]{64}", manifest_sha) is None:
        raise _v4_global(_v4_scope, 'RunnerError')("V3 formal csv_sha256 must be a 64-hex digest")
    actual_sha = _v4_global(_v4_scope, '_sha')(csv_path)
    if manifest_sha.lower() != actual_sha:
        raise _v4_global(_v4_scope, 'RunnerError')("V3 formal pool CSV SHA mismatch")
    if _v4_global(_v4_scope, 'any')(manifest.get(flag) is not False for flag in _v4_global(_v4_scope, 'SAFETY_FLAGS')):
        raise _v4_global(_v4_scope, 'RunnerError')("V3 formal pool safety flag must be false")
    return csv_path, manifest_path, actual_sha


def __formal_selection_codes_body(_v4_scope, /, root, trade_date):
    csv_path, _manifest_path, csv_sha = _v4_global(_v4_scope, '_validate_formal_input')(root, trade_date)
    codes: set[str] = _v4_global(_v4_scope, 'set')()
    with csv_path.open("r", encoding="utf-8-sig", newline="") as stream:
        for row in _v4_global(_v4_scope, 'csv').DictReader(stream):
            if _v4_global(_v4_scope, 'str')(row.get("eligible_for_formal_pool") or "").lower() not in {"true", "1", "yes"}:
                continue
            raw = _v4_global(_v4_scope, 'str')(row.get("ts_code") or row.get("stock_code") or "").strip().upper()
            match = _v4_global(_v4_scope, 're').search(r"(\d{6})", raw)
            if match:
                codes.add(f"A.{match.group(1)}")
    if not codes:
        raise _v4_global(_v4_scope, 'RunnerError')("V3 formal selection code set is empty")
    return codes, csv_sha


def __find_exact_file_body(_v4_scope, /, root, trade_date, basename):
    if root.is_file():
        return root
    candidates = (
        root / basename,
        root / "preselection_pools" / trade_date / basename,
        root / trade_date / basename,
        root / "universes" / trade_date / basename,
        root / ".runtime" / "data" / "universes" / trade_date / basename,
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise _v4_global(_v4_scope, 'RunnerError')(f"exact-date input missing: {basename}")


def __validate_exact_selection_inputs_body(_v4_scope, /, config, trade_date, stage_id, *, market, hk_binding):
    """Validate only the exact inputs owned by one market lane.

    The stage has one shared candidate clock but two independently publishable
    market lanes.  A missing HK artifact must therefore be represented on the
    HK lane instead of aborting an otherwise valid A-share lane.  ``market``
    is optional for compatibility with callers that want the whole-stage
    aggregate validation; the runner itself always validates per market.
    """
    evidence: list[str] = []
    if config.injected_test_mode:
        return _v4_global(_v4_scope, 'tuple')(evidence)
    requested = (market,) if market is not None else _v4_global(_v4_scope, '_stage_markets')(stage_id)
    unknown = _v4_global(_v4_scope, 'set')(requested) - {"A_SHARE", "HK_CONNECT"}
    if unknown:
        raise _v4_global(_v4_scope, 'RunnerError')(f"unknown exact-input market(s): {_v4_global(_v4_scope, 'sorted')(unknown)!r}")
    if "A_SHARE" in requested:
        if stage_id in _v4_global(_v4_scope, 'V3_RESEARCH_STAGES') and config.v4_research_data_root is None:
            raise _v4_global(_v4_scope, 'RunnerError')(
                f"V4 research data root is required for {stage_id} A_SHARE"
            )
        if stage_id in _v4_global(_v4_scope, 'V3_RESEARCH_STAGES'):
            if config.v4_morning_news_root is None:
                raise _v4_global(_v4_scope, 'RunnerError')(
                    f"V4 morning-news root is required for {stage_id} A_SHARE"
                )
            evidence.append(f"v4_research_data_root={config.v4_research_data_root}")
            evidence.append(f"v4_morning_news_root={config.v4_morning_news_root}")
        # Formal/name metadata are optional overlays, not the acquisition
        # authority. A's strict current pointer remains mandatory in _run_one.
        if config.v3_formal_root is None:
            evidence.append("a_formal_overlay_unavailable=ROOT_NOT_BOUND")
        else:
            try:
                formal_csv, formal_manifest, formal_sha = _v4_global(_v4_scope, '_validate_formal_input')(config.v3_formal_root, trade_date)
                evidence.extend((f"formal_csv={formal_csv}", f"formal_manifest={formal_manifest}", f"formal_csv_sha256={formal_sha}"))
            except (_v4_global(_v4_scope, 'RunnerError'), _v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'ValueError')) as error:
                evidence.append(f"a_formal_overlay_unavailable={error}")
        if config.a_research_panel_receipt_root is None:
            evidence.append("a_name_overlay_unavailable=ROOT_NOT_BOUND")
        else:
            try:
                _mapping, panel_evidence = _v4_global(_v4_scope, '_a_selector_name_map')(
                    candidate_root=config.candidate_acquisition_root,
                    research_panel_receipt_root=config.a_research_panel_receipt_root,
                    trade_date=trade_date,
                )
                evidence.extend(panel_evidence)
            except (_v4_global(_v4_scope, 'RunnerError'), _v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'ValueError')) as error:
                evidence.append(f"a_name_overlay_unavailable={error}")
    if "HK_CONNECT" in requested:
        if config.hk_d1_root is None:
            raise _v4_global(_v4_scope, 'RunnerError')("production HK D1 root is required")
        if hk_binding is None:
            d1_path, d1_sha = _v4_global(_v4_scope, '_validate_hk_d1')(
                config.hk_d1_root,
                trade_date,
                preselection_source_root=config.preselection_source_root,
            )
            evidence.extend((f"hk_d1_json={d1_path}", f"hk_d1_sha256={d1_sha}"))
        else:
            evidence.extend(
                _v4_global(_v4_scope, '_validated_hk_binding_evidence')(hk_binding, trade_date)
            )
        evidence.append("hk_acquisition_scope=EXACT_D1_TOP100")
        # The opening auction is the only stage whose membership is bound to
        # the exact 09:20 second-filter.  Later minute stages use the verified
        # D-1 membership and its code-bounded live snapshot, so they must not be
        # blocked by a missing pre-open artifact.
        if stage_id == "STAGE_0925":
            if config.hk_second_filter_root is None:
                raise _v4_global(_v4_scope, 'RunnerError')("production HK second-filter root is required for STAGE_0925")
            second_csv, second_acceptance, second_sha = _v4_global(_v4_scope, '_validate_hk_second_filter')(config.hk_second_filter_root, trade_date)
            evidence.extend((f"hk_second_filter_csv={second_csv}", f"hk_second_filter_acceptance={second_acceptance}", f"hk_second_filter_csv_sha256={second_sha}"))
        if stage_id == "STAGE_1545_1555":
            if config.hk_stage_replay_root is None:
                raise _v4_global(_v4_scope, 'RunnerError')("production HK Stage8 replay root is required for STAGE_1545_1555")
            evidence.append(f"hk_stage_replay_root={config.hk_stage_replay_root}")
    return _v4_global(_v4_scope, 'tuple')(evidence)


def __selection_source_body(_v4_scope, /, source, *, market, membership):
    if membership is None:
        return source
    rows = _v4_global(_v4_scope, 'tuple')(row for row in source.rows if _v4_global(_v4_scope, '_normal_code')(market, _v4_global(_v4_scope, 'getattr')(row, "get", lambda *_: None)("code")) in membership)
    observed = {_v4_global(_v4_scope, '_normal_code')(market, row.get("code")) for row in source.rows}
    missing = _v4_global(_v4_scope, 'tuple')(_v4_global(_v4_scope, 'sorted')(membership - observed))
    status = source.status
    if not rows:
        status = "CANNOT_CONFIRM"
    elif status == "READY" and (missing or _v4_global(_v4_scope, 'len')(rows) < _v4_global(_v4_scope, 'len')(membership)):
        status = "PARTIAL_WITH_ROWS"
    return _v4_global(_v4_scope, 'replace')(source, status=status, rows=rows, requested_rows=_v4_global(_v4_scope, 'len')(membership), missing_symbols=_v4_global(_v4_scope, 'tuple')(_v4_global(_v4_scope, 'dict').fromkeys((*source.missing_symbols, *missing))), cannot_confirm=_v4_global(_v4_scope, 'tuple')(source.cannot_confirm) + (("SELECTION_MEMBERSHIP_INTERSECTION_EMPTY",) if not rows else ()))
