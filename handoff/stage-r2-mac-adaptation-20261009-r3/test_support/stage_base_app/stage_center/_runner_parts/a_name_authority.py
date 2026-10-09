"""stage_center.runner: a_name_authority (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __a_selector_name_map_body(_v4_scope, /, *, candidate_root, research_panel_receipt_root, trade_date):
    """Read the exact signal-date A selector panel, fail-closed on drift."""
    pool_path = _v4_global(_v4_scope, '_a_d1_premarket_pool_path')(candidate_root, trade_date)
    try:
        pool = _v4_global(_v4_scope, 'json').loads(pool_path.read_text(encoding="utf-8-sig"))
    except (_v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'UnicodeError'), _v4_global(_v4_scope, 'ValueError')) as error:
        raise _v4_global(_v4_scope, 'RunnerError')("A D-1 premarket pool unreadable") from error
    if not _v4_global(_v4_scope, 'isinstance')(pool, _v4_global(_v4_scope, 'Mapping')) or pool.get("target_date") != trade_date:
        raise _v4_global(_v4_scope, 'RunnerError')("A D-1 premarket pool target_date mismatch")
    if pool.get("status") != "V192_CANDIDATE_READY" or pool.get("stage_selection_eligible") is not True:
        raise _v4_global(_v4_scope, 'RunnerError')("A D-1 premarket pool status/eligibility mismatch")
    if _v4_global(_v4_scope, 'any')(pool.get(flag) is not False for flag in _v4_global(_v4_scope, 'SAFETY_FLAGS')):
        raise _v4_global(_v4_scope, 'RunnerError')("A D-1 premarket pool safety flags must be false")
    pool_rows = pool.get("rows", pool.get("data"))
    if not _v4_global(_v4_scope, 'isinstance')(pool_rows, _v4_global(_v4_scope, 'list')) or not pool_rows:
        raise _v4_global(_v4_scope, 'RunnerError')("A D-1 premarket pool rows missing")
    signal_dates = {
        _v4_global(_v4_scope, 'str')(row.get("signal_date") or row.get("trade_date") or "").replace("-", "")
        for row in pool_rows
        if _v4_global(_v4_scope, 'isinstance')(row, _v4_global(_v4_scope, 'Mapping'))
    }
    signal_dates.discard("")
    if _v4_global(_v4_scope, 'len')(signal_dates) != 1:
        raise _v4_global(_v4_scope, 'RunnerError')("A D-1 premarket pool signal_date is ambiguous")
    signal_date = _v4_global(_v4_scope, 'next')(_v4_global(_v4_scope, 'iter')(signal_dates))
    if not _v4_global(_v4_scope, 're').fullmatch(r"\d{8}", signal_date) or signal_date >= trade_date:
        raise _v4_global(_v4_scope, 'RunnerError')("A D-1 premarket pool signal_date is not prior to target")
    receipt_path = _v4_global(_v4_scope, '_a_research_receipt_path')(research_panel_receipt_root, signal_date)
    try:
        receipt = _v4_global(_v4_scope, 'json').loads(receipt_path.read_text(encoding="utf-8-sig"))
    except (_v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'UnicodeError'), _v4_global(_v4_scope, 'ValueError')) as error:
        raise _v4_global(_v4_scope, 'RunnerError')("A research-panel receipt unreadable") from error
    if not _v4_global(_v4_scope, 'isinstance')(receipt, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'RunnerError')("A research-panel receipt status must be READY")
    if receipt.get("status") == "READY":
        receipt_payload: Mapping[str, Any] = receipt
        receipt_date = _v4_global(_v4_scope, 'str')(receipt.get("target_date") or "").replace("-", "")
        if receipt_date != signal_date:
            raise _v4_global(_v4_scope, 'RunnerError')("A research-panel receipt target_date mismatch")
    elif receipt.get("status") == "ATTEMPTED":
        receipt_date = _v4_global(_v4_scope, 'str')(receipt.get("target_date") or "").replace("-", "")
        if receipt_date != signal_date:
            raise _v4_global(_v4_scope, 'RunnerError')("A research-panel receipt target_date mismatch")
        lanes = receipt.get("lanes")
        receipt_payload = lanes.get("A") if _v4_global(_v4_scope, 'isinstance')(lanes, _v4_global(_v4_scope, 'Mapping')) else None
        if not _v4_global(_v4_scope, 'isinstance')(receipt_payload, _v4_global(_v4_scope, 'Mapping')) or receipt_payload.get("status") != "READY":
            raise _v4_global(_v4_scope, 'RunnerError')("A research-panel A lane status must be READY")
        lane_date = _v4_global(_v4_scope, 'str')(receipt_payload.get("target_date") or "").replace("-", "")
        if lane_date != signal_date:
            raise _v4_global(_v4_scope, 'RunnerError')("A research-panel A lane target_date mismatch")
    else:
        raise _v4_global(_v4_scope, 'RunnerError')("A research-panel receipt status must be READY")
    if _v4_global(_v4_scope, 'any')(receipt.get(flag) is not False for flag in _v4_global(_v4_scope, 'SAFETY_FLAGS')):
        raise _v4_global(_v4_scope, 'RunnerError')("A research-panel receipt safety flags must be false")
    if _v4_global(_v4_scope, 'any')(receipt_payload.get(flag) is not False for flag in _v4_global(_v4_scope, 'SAFETY_FLAGS')):
        raise _v4_global(_v4_scope, 'RunnerError')("A research-panel A lane safety flags must be false")
    formula = receipt_payload.get("formula")
    if not _v4_global(_v4_scope, 'isinstance')(formula, _v4_global(_v4_scope, 'Mapping')) or formula.get("status") != "READY":
        raise _v4_global(_v4_scope, 'RunnerError')("A research-panel formula status must be READY")
    formula_date = _v4_global(_v4_scope, 'str')(formula.get("target_date") or "").replace("-", "")
    if formula_date != signal_date:
        raise _v4_global(_v4_scope, 'RunnerError')("A research-panel formula target_date mismatch")
    selector_value = formula.get("selector")
    if not _v4_global(_v4_scope, 'isinstance')(selector_value, _v4_global(_v4_scope, 'str')) or not selector_value.startswith("/"):
        raise _v4_global(_v4_scope, 'RunnerError')("A research-panel selector parquet path missing")
    selector_path = _v4_global(_v4_scope, 'Path')(selector_value).expanduser().resolve()
    receipt_root = _v4_global(_v4_scope, 'Path')(research_panel_receipt_root).expanduser().resolve()
    if receipt_root.name == "receipts" and receipt_root.parent.name == "research_panel_daily":
        authority_root = receipt_root.parent.parent
    else:
        authority_root = receipt_root.parent
    try:
        selector_path.relative_to(authority_root)
    except _v4_global(_v4_scope, 'ValueError') as error:
        raise _v4_global(_v4_scope, 'RunnerError')("A research-panel selector parquet outside authority root") from error
    if not selector_path.is_file():
        raise _v4_global(_v4_scope, 'RunnerError')("A research-panel selector parquet missing")
    declared_sha = _v4_global(_v4_scope, 'str')(
        formula.get("selector_sha256")
        or receipt_payload.get("selector_sha256")
        or receipt.get("selector_sha256")
        or ""
    )
    if declared_sha:
        if not _v4_global(_v4_scope, 're').fullmatch(r"[0-9a-fA-F]{64}", declared_sha) or _v4_global(_v4_scope, '_sha')(selector_path).lower() != declared_sha.lower():
            raise _v4_global(_v4_scope, 'RunnerError')("A research-panel selector parquet SHA mismatch")
    try:
        import pyarrow.parquet as parquet

        schema = parquet.read_schema(selector_path)
    except _v4_global(_v4_scope, 'Exception') as error:
        raise _v4_global(_v4_scope, 'RunnerError')("A research-panel selector parquet unreadable") from error
    required = {"trade_date", "name"}
    column_names = _v4_global(_v4_scope, 'set')(schema.names)
    if not required.issubset(column_names) or not ({"ts_code", "raw_code"} & column_names):
        raise _v4_global(_v4_scope, 'RunnerError')("A research-panel selector parquet name schema missing")
    code_columns = [column for column in ("ts_code", "raw_code") if column in column_names]
    read_columns = ["trade_date", *code_columns, "name"]
    if "stock_name" in column_names:
        read_columns.append("stock_name")
    try:
        table = parquet.read_table(
            selector_path,
            columns=read_columns,
            filters=[("trade_date", "=", signal_date)],
        )
        records = table.to_pylist()
    except _v4_global(_v4_scope, 'Exception') as error:
        raise _v4_global(_v4_scope, 'RunnerError')("A research-panel selector parquet unreadable") from error
    if not records:
        raise _v4_global(_v4_scope, 'RunnerError')("A research-panel selector parquet is empty")
    panel_dates = {_v4_global(_v4_scope, 'str')(row.get("trade_date") or "").replace("-", "") for row in records}
    if panel_dates != {signal_date}:
        raise _v4_global(_v4_scope, 'RunnerError')("A research-panel selector parquet max trade_date mismatch")
    mapping: dict[str, str] = {}
    for row in records:
        row_date = _v4_global(_v4_scope, 'str')(row.get("trade_date") or "").replace("-", "")
        if row_date != signal_date:
            continue
        raw_code = row.get("ts_code") or row.get("raw_code")
        code = _v4_global(_v4_scope, '_normal_code')("A_SHARE", raw_code)
        name = _v4_global(_v4_scope, 'str')(row.get("name") or row.get("stock_name") or "").strip()
        if not code or not name or name == code or name == _v4_global(_v4_scope, 'str')(raw_code or "").strip():
            continue
        previous = mapping.get(code)
        if previous is not None and previous != name:
            raise _v4_global(_v4_scope, 'RunnerError')(f"A research-panel selector name conflict: {code}")
        mapping[code] = name
    if not mapping:
        raise _v4_global(_v4_scope, 'RunnerError')("A research-panel selector code-name map is empty")
    evidence = (
        f"a_d1_premarket_pool_json={pool_path}",
        f"a_d1_premarket_pool_sha256={_v4_global(_v4_scope, '_sha')(pool_path)}",
        f"a_research_panel_receipt={receipt_path}",
        f"a_research_panel_receipt_sha256={_v4_global(_v4_scope, '_sha')(receipt_path)}",
        f"a_research_panel_signal_date={signal_date}",
        f"a_research_panel_selector={selector_path}",
        f"a_research_panel_selector_sha256={_v4_global(_v4_scope, '_sha')(selector_path)}",
    )
    return mapping, evidence


def __attach_a_name_authority_body(_v4_scope, /, source, *, candidate_root, research_panel_receipt_root, trade_date):
    mapping, evidence = _v4_global(_v4_scope, '_a_selector_name_map')(
        candidate_root=_v4_global(_v4_scope, 'Path')(candidate_root),
        research_panel_receipt_root=_v4_global(_v4_scope, 'Path')(research_panel_receipt_root),
        trade_date=trade_date,
    )
    enriched: list[dict[str, Any]] = []
    fallback_codes: list[str] = []
    for raw in source.rows:
        merged = _v4_global(_v4_scope, 'dict')(raw)
        code = _v4_global(_v4_scope, '_normal_code')("A_SHARE", raw.get("code"))
        name = mapping.get(code)
        if not name:
            # A missing authority label is not a display name. Keep the
            # candidate and its ordering fields, but clear provider/code
            # placeholders so downstream consumers can fail closed.
            name = None
            fallback_codes.append(code)
        merged["code"] = code
        merged["name"] = name
        merged["stock_name"] = name
        enriched.append(merged)
    if fallback_codes:
        evidence = (*evidence, *(
            f"name_authority_missing={code}" for code in _v4_global(_v4_scope, 'sorted')(_v4_global(_v4_scope, 'set')(fallback_codes))
        ))
    cannot_confirm = source.cannot_confirm
    status = source.status
    if fallback_codes:
        cannot_confirm = _v4_global(_v4_scope, 'tuple')(_v4_global(_v4_scope, 'dict').fromkeys((*cannot_confirm, "NAME_AUTHORITY_CODE_NOT_FOUND")))
        if not enriched or source.status == "CANNOT_CONFIRM":
            status = "CANNOT_CONFIRM"
        elif source.status == "READY":
            status = "PARTIAL_WITH_ROWS"
    return _v4_global(_v4_scope, 'replace')(
        source,
        status=status,
        rows=_v4_global(_v4_scope, 'tuple')(enriched),
        cannot_confirm=cannot_confirm,
        source_evidence=_v4_global(_v4_scope, 'tuple')(_v4_global(_v4_scope, 'dict').fromkeys((*source.source_evidence, *evidence))),
    )
