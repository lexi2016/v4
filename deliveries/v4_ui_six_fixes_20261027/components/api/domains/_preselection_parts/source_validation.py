"""domains.preselection: source_validation (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __restore_flat_migration_contract_body(_v4_scope, /, payload):
    """Project the one-time flat import back into the old V3 pool contract.

    This is a read-only compatibility projection.  It does not claim that a
    partial migration is canonical and it never fabricates candidate rows.
    """
    pools = payload.get("pools") or []
    if _v4_global(_v4_scope, 'len')(pools) != 1 or pools[0].get("pool_id") != "legacy_partial_migration":
        return payload

    rows = _v4_global(_v4_scope, 'list')(payload.get("rows") or pools[0].get("rows") or [])
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        pool_id = _v4_global(_v4_scope, 'str')(row.get("pool_id") or "")
        if pool_id:
            grouped.setdefault(pool_id, []).append(row)

    restored_pools = []
    pool_ids = [pool_id for pool_id in _v4_global(_v4_scope, '_POOL_ORDER') if grouped.get(pool_id)]
    pool_ids.extend(_v4_global(_v4_scope, 'sorted')(_v4_global(_v4_scope, 'set')(grouped) - _v4_global(_v4_scope, 'set')(pool_ids)))
    for pool_id in pool_ids:
        pool_rows = grouped[pool_id]
        markets = {_v4_global(_v4_scope, '_market')(row) for row in pool_rows}
        restored_pools.append({
            "pool_id": pool_id,
            "display_name": _v4_global(_v4_scope, '_POOL_NAMES').get(pool_id, pool_id),
            "market": markets.pop() if _v4_global(_v4_scope, 'len')(markets) == 1 else "MIXED",
            "pool_size": _v4_global(_v4_scope, 'len')(pool_rows),
            "returned_rows": _v4_global(_v4_scope, 'len')(pool_rows),
            "rows": pool_rows,
        })

    main_rows = grouped.get("a_d1_premarket_pool", [])
    all_a_rows = _v4_global(_v4_scope, '_dedupe_by_symbol')(
        row for pool_id in pool_ids if pool_id != "hkconnect_d1_top100"
        for row in grouped.get(pool_id, [])
        if _v4_global(_v4_scope, '_market')(row) == "A"
    )
    main_symbols = {_v4_global(_v4_scope, 'str')(row.get("symbol") or row.get("code") or "") for row in main_rows}
    source_only_rows = [
        row for row in all_a_rows
        if _v4_global(_v4_scope, 'str')(row.get("symbol") or row.get("code") or "") not in main_symbols
    ]
    hk_rows = _v4_global(_v4_scope, '_dedupe_by_symbol')(row for row in rows if _v4_global(_v4_scope, '_market')(row) == "HK")

    restored = _v4_global(_v4_scope, 'dict')(payload)
    restored.update({
        "pools": restored_pools,
        "unified_rows": _v4_global(_v4_scope, 'list')(main_rows),
        "a_source_only_rows": source_only_rows,
        "a_all_pool_rows": all_a_rows,
        "market_totals": {"A": _v4_global(_v4_scope, 'len')(all_a_rows), "HK": _v4_global(_v4_scope, 'len')(hk_rows)},
        "hk_pool_version": "0.2" if grouped.get("hkconnect_d1_top100") else None,
        "hk_pool_role": "D_MINUS_1_MODEL_TOP100" if grouped.get("hkconnect_d1_top100") else None,
    })
    return restored


def __ensure_source_contract_body(_v4_scope, /, row):
    """Fill the evidenced old-V3 source fields without changing row values."""

    source_tag, source_suffix, source_lane = _v4_global(_v4_scope, '_pool_source_metadata')(row)
    if not row.get("display_name") and source_suffix:
        stock_name = _v4_global(_v4_scope, 'str')(row.get("stock_name") or row.get("name") or row.get("symbol") or "")
        row["display_name"] = f"{stock_name}{source_suffix}"
    if not _v4_global(_v4_scope, '_metadata_values')(row.get("source_tag")) and source_tag:
        row["source_tag"] = source_tag
    if not _v4_global(_v4_scope, '_metadata_values')(row.get("source_tags")) and source_suffix:
        row["source_tags"] = source_suffix
    if not _v4_global(_v4_scope, '_metadata_values')(row.get("source_lanes")) and source_lane:
        row["source_lanes"] = source_lane


def __merge_source_contract_body(_v4_scope, /, target, incoming):
    """Merge provenance while keeping the first row's rank, score, and name."""

    _v4_global(_v4_scope, '_ensure_source_contract')(target)
    incoming_row = _v4_global(_v4_scope, 'dict')(incoming)
    _v4_global(_v4_scope, '_ensure_source_contract')(incoming_row)
    for field in ("source_tags", "source_lanes", "source_trace"):
        values = _v4_global(_v4_scope, '_ordered_metadata_values')(
            [*_v4_global(_v4_scope, '_metadata_values')(target.get(field)), *_v4_global(_v4_scope, '_metadata_values')(incoming_row.get(field))]
        )
        if values:
            target[field] = " / ".join(values)


def project_a_display_names(response, trade_date, pool_root):
    """Project exact-date names over every display array without touching inputs."""
    import os
    import re
    from copy import deepcopy
    from pathlib import Path
    from stage_center.consumer import StageSelectionConsumer, _normalize_a_code, _valid_name
    from upstreams.v3_shared_data.shared_data.a_share_security_master import load_current_display_names
    from upstreams.v3_shared_data.shared_data.store import StoreError

    output = deepcopy(response)
    authority = StageSelectionConsumer(Path(pool_root), a_name_pool_root=Path(pool_root))._load_a_name_authority(trade_date)
    current, manifest, current_error = {}, {}, None
    configured_root = os.environ.get("V4_MANAGER_SECURITY_MASTER_ROOT")
    if configured_root:
        try:
            current, manifest = load_current_display_names(configured_root, trade_date)
        except (StoreError, OSError, ValueError, KeyError, TypeError) as error:
            current_error = str(error)
    else:
        current_error = "V4_MANAGER_SECURITY_MASTER_ROOT is not configured"
    conflicted = set(authority.get("conflicted_codes") or [])
    pool_mapping = authority.get("mapping") or {}
    applied, missing = set(), set()

    def project(row):
        if not isinstance(row, dict):
            return row
        if row.get("market") not in (None, "A", "A_SHARE") or str(row.get("symbol") or "").startswith("HK."):
            return row
        if any(row.get(field) not in (None, "", trade_date) for field in ("trade_date", "target_date")):
            return row
        codes = {_normalize_a_code(row.get(field)) for field in ("symbol", "stock_code", "code", "ts_code") if row.get(field)}
        codes.discard("")
        if len(codes) != 1:
            return row
        canonical = next(iter(codes))
        code = canonical[2:]
        if canonical in conflicted:
            missing.add(canonical)
            return row
        observed = current.get(code)
        pool_name = pool_mapping.get(canonical)
        if observed and pool_name is not None and re.sub(r"\s+", "", pool_name) != re.sub(r"\s+", "", observed["name"]):
            conflicted.add(canonical)
            missing.add(canonical)
            return row
        name = observed["name"] if observed else pool_mapping.get(canonical)
        # Current display evidence takes precedence over placeholder aliases only.
        # Existing genuine names outside this batch remain their original snapshot.
        invalid = any(not _valid_name(row.get(field), canonical) for field in ("name", "stock_name"))
        display = str(row.get("display_name") or "")
        display_base = re.split(r"[（(]", display, maxsplit=1)[0]
        invalid = invalid or not _valid_name(display_base, canonical)
        if not invalid:
            return row
        if not name:
            missing.add(canonical)
            return row
        suffix_match = re.search(r"([（(].*)$", display)
        suffix = suffix_match.group(1) if suffix_match else ""
        if not suffix:
            tags = row.get("source_tags")
            if isinstance(tags, str):
                suffix = "".join(re.findall(r"[（(][^）)]*[）)]", tags))
        row.update(name=name, stock_name=name, display_name=name + suffix)
        if observed:
            row["display_identity"] = dict(ts_code=observed["ts_code"], source_kind="DISPLAY_NAME_ONLY",
                observation_date=trade_date, run_id=manifest["run_id"], evidence_sha256=observed["evidence_sha256"],
                raw_ts_code=row.get("ts_code"), selector_certified=False, pit_certified=False)
        else:
            row["display_identity"] = dict(source_kind="EXACT_DATE_VERIFIED_POOL_NAME",
                observation_date=trade_date, source_sha256=authority.get("source_sha256"),
                receipt_sha256=authority.get("receipt_sha256"))
        applied.add(canonical)
        return row

    for key in ("rows", "unified_rows", "a_source_only_rows", "a_all_pool_rows"):
        if isinstance(output.get(key), list):
            output[key] = [project(row) for row in output[key]]
    for pool in output.get("pools") or []:
        if isinstance(pool, dict) and isinstance(pool.get("rows"), list):
            pool["rows"] = [project(row) for row in pool["rows"]]
    output["display_name_authority"] = dict(source_kind="DISPLAY_NAME_ONLY", observation_date=trade_date,
        run_id=manifest.get("run_id"), current_row_count=len(current), applied_codes=sorted(applied),
        missing_codes=sorted(missing), conflicted_codes=sorted(conflicted), current_error=current_error,
        pool_audit=authority.get("pool_audit"), pool_verification_status=authority.get("verification_status"),
        selector_certified=False, pit_certified=False)
    return output
