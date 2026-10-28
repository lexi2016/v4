"""ops.a_formula_increment: history_audit (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __approved_history_gap_keys_body(_v4_scope, /, role, seed_sha256, observed):
    """Read frozen evidence; no path, row-count or same-window substitution."""
    contract_role = _v4_global(_v4_scope, 'HISTORY_CONTRACT_ROLE_ALIASES').get(role)
    if contract_role is None:
        raise _v4_global(_v4_scope, 'AuthorityError')(f"{role} historical role is not approved")
    raw = _v4_global(_v4_scope, 'SafeRoot')(_v4_global(_v4_scope, '_PROJECT_ROOT')).read_bytes("contracts/a_known_history_gaps.json", max_bytes=256 * 1024)
    if _v4_global(_v4_scope, 'hashlib').sha256(raw).hexdigest() != _v4_global(_v4_scope, 'APPROVED_HISTORY_CONTRACT_SHA256'):
        raise _v4_global(_v4_scope, 'AuthorityError')("approved historical gap contract SHA mismatch")
    contract = _v4_global(_v4_scope, 'json').loads(raw)
    if contract.get("schema") != "v4.a_known_history_gaps.v1":
        raise _v4_global(_v4_scope, 'AuthorityError')("approved historical gap contract schema mismatch")
    entries = contract.get("seeds")
    if not _v4_global(_v4_scope, 'isinstance')(entries, _v4_global(_v4_scope, 'list')) or {e.get("role") for e in entries} != {"selector", "backtest"} or _v4_global(_v4_scope, 'len')(entries) != 2:
        raise _v4_global(_v4_scope, 'AuthorityError')("approved historical gap roles mismatch")
    approved = _v4_global(_v4_scope, 'next')((e for e in entries if e["role"] == contract_role), None)
    known_seed = _v4_global(_v4_scope, 'any')(e.get("seed_sha256") == seed_sha256 for e in entries)
    if observed or known_seed:
        if approved is None or approved.get("seed_sha256") != seed_sha256:
            raise _v4_global(_v4_scope, 'AuthorityError')(f"{role} historical anomaly seed SHA not approved")
        items = approved.get("keys", [])
        expected = {(_v4_global(_v4_scope, 'str')(k["ts_code"]), _v4_global(_v4_scope, 'int')(k["trade_date"])) for k in items}
        if _v4_global(_v4_scope, 'len')(expected) != 354 or _v4_global(_v4_scope, 'len')(items) != _v4_global(_v4_scope, 'len')(expected):
            raise _v4_global(_v4_scope, 'AuthorityError')("approved historical gap key contract invalid")
        if observed != expected:
            raise _v4_global(_v4_scope, 'AuthorityError')(f"{role} historical anomaly keys mismatch: "
                                 f"extra={_v4_global(_v4_scope, 'sorted')(observed - expected)[:5]}, missing={_v4_global(_v4_scope, 'sorted')(expected - observed)[:5]}")
    else:
        expected = _v4_global(_v4_scope, 'set')()  # a different clean seed obtains no historical exception
    return {"contract_sha256": _v4_global(_v4_scope, 'APPROVED_HISTORY_CONTRACT_SHA256'),
            "contract_role": contract_role,
            "approved_key_count": _v4_global(_v4_scope, 'len')(expected),
            "observed_key_count": _v4_global(_v4_scope, 'len')(observed),
            "key_sha256": _v4_global(_v4_scope, 'hashlib').sha256(_v4_global(_v4_scope, 'json').dumps(_v4_global(_v4_scope, 'sorted')(observed), separators=(",", ":")).encode()).hexdigest(),
            "status": "EXACT_SEED_AND_KEYS_MATCH" if observed else "NO_EXCEPTION_USED"}


def __audit_existing_history_body(_v4_scope, /, current, combined, *, role, target_date, seed_sha256):
    """Prove append-only retention without re-gating known old HK anomalies.

    Only rows introduced by the current run are validated by the strict
    selector/backtest gates.  Existing rows must remain present with the same
    logical key/value content.  Known historical HK/HK_FUND close-range rows
    are reported as an unresolved health gap; any other historical structural
    issue still fails closed.
    """

    required = _v4_global(_v4_scope, 'list')(_v4_global(_v4_scope, 'KEY_COLUMNS')) + ["open", "high", "low", "close"]
    missing = _v4_global(_v4_scope, 'sorted')(_v4_global(_v4_scope, 'set')(required) - _v4_global(_v4_scope, 'set')(current.columns))
    if missing:
        raise _v4_global(_v4_scope, 'AuthorityError')(f"{role} existing history missing required columns: {','.join(missing)}")
    missing_combined = _v4_global(_v4_scope, 'sorted')(_v4_global(_v4_scope, 'set')(required) - _v4_global(_v4_scope, 'set')(combined.columns))
    if missing_combined:
        raise _v4_global(_v4_scope, 'AuthorityError')(f"{role} appended history missing required columns: {','.join(missing_combined)}")
    if current.duplicated(_v4_global(_v4_scope, 'list')(_v4_global(_v4_scope, 'KEY_COLUMNS'))).any() or combined.duplicated(_v4_global(_v4_scope, 'list')(_v4_global(_v4_scope, 'KEY_COLUMNS'))).any():
        raise _v4_global(_v4_scope, 'AuthorityError')(f"{role} history contains duplicate keys")

    current_dates = _v4_global(_v4_scope, 'pd').to_numeric(current["trade_date"], errors="coerce")
    combined_dates = _v4_global(_v4_scope, 'pd').to_numeric(combined["trade_date"], errors="coerce")
    if current_dates.isna().any() or combined_dates.isna().any():
        raise _v4_global(_v4_scope, 'AuthorityError')(f"{role} history contains invalid trade_date values")
    if current_dates.gt(target_date).any() or combined_dates.gt(target_date).any():
        raise _v4_global(_v4_scope, 'AuthorityError')(f"{role} history contains future rows")
    if current["ts_code"].astype(_v4_global(_v4_scope, 'str')).str.strip().eq("").any() or combined["ts_code"].astype(_v4_global(_v4_scope, 'str')).str.strip().eq("").any():
        raise _v4_global(_v4_scope, 'AuthorityError')(f"{role} history contains blank ts_code")

    numeric = current[["open", "high", "low", "close"]].apply(_v4_global(_v4_scope, 'pd').to_numeric, errors="coerce")
    nonpositive_or_non_numeric = numeric.isna().any(axis=1) | numeric.le(0).any(axis=1)
    high_low_bad = numeric["high"].lt(numeric["low"])
    close_outside = numeric["close"].gt(numeric["high"]) | numeric["close"].lt(numeric["low"])
    external_market = current["ts_code"].map(_v4_global(_v4_scope, '_external_market'))
    gap_min, gap_max = _v4_global(_v4_scope, 'KNOWN_HISTORICAL_GAP_DATE_RANGE')
    known_gap = (
        external_market.notna()
        & close_outside
        & ~nonpositive_or_non_numeric
        & ~high_low_bad
        & current_dates.between(gap_min, gap_max)
    )
    unexpected = (nonpositive_or_non_numeric | high_low_bad | close_outside) & ~known_gap
    if unexpected.any():
        sample = [
            {"ts_code": _v4_global(_v4_scope, 'str')(code), "trade_date": _v4_global(_v4_scope, 'int')(day)}
            for code, day in current.loc[unexpected, _v4_global(_v4_scope, 'list')(_v4_global(_v4_scope, 'KEY_COLUMNS'))].head(5).itertuples(index=False, name=None)
        ]
        raise _v4_global(_v4_scope, 'AuthorityError')(f"{role} existing history structural gate failed: {sample}")

    observed_gap_keys = {(_v4_global(_v4_scope, 'str')(code), _v4_global(_v4_scope, 'int')(day)) for code, day in
                         current.loc[known_gap, _v4_global(_v4_scope, 'list')(_v4_global(_v4_scope, 'KEY_COLUMNS'))].itertuples(index=False, name=None)}
    gap_binding = _v4_global(_v4_scope, '_approved_history_gap_keys')(role, seed_sha256, observed_gap_keys)

    columns = _v4_global(_v4_scope, 'list')(current.columns)
    current_for_hash, combined_for_hash = _v4_global(_v4_scope, '_align_retention_hash_frames')(current, combined, columns)
    current_hashes = _v4_global(_v4_scope, '_retention_hash_table')(current_for_hash, columns)
    combined_hashes = _v4_global(_v4_scope, '_retention_hash_table')(combined_for_hash, columns)
    joined = current_hashes.merge(
        combined_hashes,
        on=_v4_global(_v4_scope, 'list')(_v4_global(_v4_scope, 'KEY_COLUMNS')),
        how="left",
        sort=False,
        validate="one_to_one",
        suffixes=("_current", "_combined"),
    )
    missing_mask = joined["_retention_hash_combined"].isna()
    changed_mask = (joined["_retention_hash_current"] != joined["_retention_hash_combined"]).fillna(False)
    missing_keys = [
        _v4_global(_v4_scope, 'list')(key)
        for key in joined.loc[missing_mask, _v4_global(_v4_scope, 'list')(_v4_global(_v4_scope, 'KEY_COLUMNS'))].head(5).itertuples(index=False, name=None)
    ]
    changed_keys = [
        _v4_global(_v4_scope, 'list')(key)
        for key in joined.loc[changed_mask, _v4_global(_v4_scope, 'list')(_v4_global(_v4_scope, 'KEY_COLUMNS'))].head(5).itertuples(index=False, name=None)
    ]
    if missing_mask.any() or changed_mask.any():
        details = {
            "missing_keys": missing_keys,
            "changed_keys": changed_keys,
        }
        raise _v4_global(_v4_scope, 'AuthorityError')(f"{role} existing history retention failed: {details}")
    before_digest = _v4_global(_v4_scope, '_hash_table_digest')(current_hashes, columns)
    after_digest = _v4_global(_v4_scope, '_hash_table_digest')(joined, columns, hash_column="_retention_hash_combined")
    if before_digest != after_digest:
        raise _v4_global(_v4_scope, 'AuthorityError')(f"{role} existing history logical value digest changed")

    gap_reports: list[dict[str, Any]] = []
    for market in _v4_global(_v4_scope, 'KNOWN_HISTORICAL_GAP_MARKETS'):
        market_rows = known_gap & external_market.eq(market)
        if not market_rows.any():
            continue
        dates = current.loc[market_rows, "trade_date"].astype(_v4_global(_v4_scope, 'int'))
        gap_reports.append(
            {
                "status": "CANNOT_CONFIRM",
                "resolution": "RECORDED_NOT_REPAIRED",
                "market": market,
                "rows": _v4_global(_v4_scope, 'int')(market_rows.sum()),
                "expected_reference_rows": _v4_global(_v4_scope, 'int')(_v4_global(_v4_scope, 'KNOWN_HISTORICAL_GAP_COUNTS')[market]),
                "date_range": [_v4_global(_v4_scope, 'int')(dates.min()), _v4_global(_v4_scope, 'int')(dates.max())],
                "seed_sha256": seed_sha256,
                "reason": "pre-existing close outside high/low is retained and excluded from the new A increment gate",
            }
        )
    return {
        "status": "PASS",
        "role": role,
        "target_date": _v4_global(_v4_scope, 'int')(target_date),
        "existing_rows": _v4_global(_v4_scope, 'int')(_v4_global(_v4_scope, 'len')(current)),
        "existing_rows_retained": _v4_global(_v4_scope, 'int')(_v4_global(_v4_scope, 'len')(current)),
        "existing_rows_value_sha256_before": before_digest,
        "existing_rows_value_sha256_after": after_digest,
        "logical_hash_algorithm": "pandas.hash_pandas_object.v1",
        "seed_sha256": _v4_global(_v4_scope, 'str')(seed_sha256),
        "known_historical_gaps": gap_reports,
        "known_historical_gap_binding": gap_binding,
        "historical_health": "CANNOT_CONFIRM",
        "full_seed_health": "CANNOT_CONFIRM",
        "retention_scope": "logical key/value retention; physical parquet bytes are not required",
    }


def __historical_seed_health_body(_v4_scope, /, *audits):
    """Keep seed health explicitly unresolved outside this increment scope."""

    gaps: list[dict[str, Any]] = []
    roles: dict[str, Any] = {}
    for audit in audits:
        role = _v4_global(_v4_scope, 'str')(audit.get("role", "unknown"))
        roles[role] = {
            "seed_sha256": _v4_global(_v4_scope, 'str')(audit.get("seed_sha256", "")),
            "existing_rows": _v4_global(_v4_scope, 'int')(audit.get("existing_rows", 0)),
            "retained_rows": _v4_global(_v4_scope, 'int')(audit.get("existing_rows_retained", 0)),
            "known_historical_gaps": audit.get("known_historical_gaps", []),
        }
        gaps.extend(audit.get("known_historical_gaps", []))
    return {
        "status": "CANNOT_CONFIRM",
        "reason": "historical seed health is outside the new A increment scope; retained rows are not re-authorized as a full-seed health claim",
        "known_historical_gaps": gaps,
        "roles": roles,
    }
