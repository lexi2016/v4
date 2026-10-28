"""stage_center.formula_margin_shadow: row_scoring (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __bucket_weight_body(_v4_scope, /, row):
    derived: int | None = None
    if "candidate_bucket" in row:
        derived = {
            "SMALLCAP_DEMON_MAIN": 2,
            "FOUR_LANE_OBSERVATION": 1,
        }.get(_v4_global(_v4_scope, 'str')(row.get("candidate_bucket") or ""), 0)
    if "bucket_weight" in row:
        value = row.get("bucket_weight")
        if _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'bool')):
            raise _v4_global(_v4_scope, 'ShadowInvalid')("bucket_weight cannot be bool")
        try:
            numeric = _v4_global(_v4_scope, 'int')(value)
        except (_v4_global(_v4_scope, 'TypeError'), _v4_global(_v4_scope, 'ValueError')) as error:
            raise _v4_global(_v4_scope, 'ShadowInvalid')("bucket_weight must be an integer") from error
        if numeric not in (0, 1, 2):
            raise _v4_global(_v4_scope, 'ShadowInvalid')("bucket_weight is outside hk comparator domain")
        if derived is not None and numeric != derived:
            raise _v4_global(_v4_scope, 'ShadowInvalid')("bucket_weight conflicts with candidate_bucket")
        return numeric
    if "candidate_bucket" not in row:
        raise _v4_global(_v4_scope, 'ShadowInvalid')("candidate_bucket/bucket_weight is required")
    return _v4_global(_v4_scope, 'int')(derived)


def _hk_legacy_stage_sort_key_body(_v4_scope, /, row):
    """The frozen production comparator used for the HK shadow baseline.

    This is a read-only parity copy.  It intentionally does not call or
    modify the production selection module, so the shadow cannot become a
    second production selector.
    """

    bucket_weight = _v4_global(_v4_scope, '_bucket_weight')(row)
    no_trade_gate = _v4_global(_v4_scope, '_no_trade_gate')(row)
    stage_score = _v4_global(_v4_scope, '_finite')(row.get("stage_score"))
    # The production comparator's ``or`` behavior is part of the frozen
    # comparator contract.  Snapshot validation still requires the fields to
    # exist and be finite so a missing sorting input cannot be disguised.
    pct_raw = _v4_global(_v4_scope, '_finite')(row.get("pct_chg"))
    volume_raw = _v4_global(_v4_scope, '_finite')(row.get("volume_ratio"))
    pct_chg = pct_raw or -999.0
    volume_ratio = volume_raw or 0.0
    return bucket_weight, no_trade_gate, stage_score, pct_chg, volume_ratio


def __normalise_row_body(_v4_scope, /, row, cutoff):
    if not _v4_global(_v4_scope, 'isinstance')(row, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("snapshot rows must be objects")
    code = _v4_global(_v4_scope, '_canonical_code')(row.get("security_id", row.get("code")))
    if _v4_global(_v4_scope, 'type')(row.get("eligible")) is not _v4_global(_v4_scope, 'bool'):
        raise _v4_global(_v4_scope, 'ShadowInvalid')(f"{code}: eligible must be an explicit bool")
    if "selection_eligible" in row:
        if _v4_global(_v4_scope, 'type')(row.get("selection_eligible")) is not _v4_global(_v4_scope, 'bool'):
            raise _v4_global(_v4_scope, 'ShadowInvalid')(f"{code}: selection_eligible must be an explicit bool")
        if row.get("selection_eligible") is not row.get("eligible"):
            raise _v4_global(_v4_scope, 'ShadowInvalid')(f"{code}: selection_eligible/eligible disagree")
    lane_value = row.get("lane", row.get("lane_labels"))
    lane = _v4_global(_v4_scope, '_lane_labels')(lane_value)
    score = _v4_global(_v4_scope, '_row_score')(row)
    if "stage_score" not in row and "production_score" in row:
        # Preserve the explicit alias but make the canonical score visible.
        row = {**row, "stage_score": score}
    comparator = _v4_global(_v4_scope, 'hk_legacy_stage_sort_key')(row)
    raw_rank = row.get("production_rank")
    if row["eligible"]:
        if _v4_global(_v4_scope, 'isinstance')(raw_rank, _v4_global(_v4_scope, 'bool')) or not _v4_global(_v4_scope, 'isinstance')(raw_rank, _v4_global(_v4_scope, 'int')) or raw_rank < 1:
            raise _v4_global(_v4_scope, 'ShadowInvalid')(f"{code}: eligible row needs positive production_rank")
        rank: int | None = raw_rank
    else:
        if raw_rank not in (None, ""):
            raise _v4_global(_v4_scope, 'ShadowInvalid')(f"{code}: ineligible row must not carry production_rank")
        rank = None
    result: dict[str, Any] = {
        "security_id": code,
        "code": code,
        "eligible": _v4_global(_v4_scope, 'bool')(row["eligible"]),
        "lane": _v4_global(_v4_scope, 'list')(lane),
        "stage_score": score,
        "production_score": score,
        "production_rank": rank,
        "comparator_key": _v4_global(_v4_scope, 'list')(comparator),
        "pre_score_key": _v4_global(_v4_scope, 'list')(comparator[:2]),
        "comparator_version": _v4_global(_v4_scope, 'COMPARATOR_VERSION'),
        "f1_state": _v4_global(_v4_scope, '_formula_state')(row, "f1_state"),
        "f2_state": _v4_global(_v4_scope, '_formula_state')(row, "f2_state"),
        "f3_state": _v4_global(_v4_scope, '_formula_state')(row, "f3_state"),
        "f4_state": _v4_global(_v4_scope, '_formula_state')(row, "f4_state"),
        **_v4_global(_v4_scope, '_validate_price')(row, cutoff),
    }
    for optional in (
        "name",
        "candidate_bucket",
        "trade_status_contract",
        "trade_status",
        "pct_chg",
        "volume_ratio",
        "formal_eligible",
        "selection_eligible",
    ):
        if optional in row:
            result[optional] = row[optional]
    result["formula_any_H"] = _v4_global(_v4_scope, 'any')(result[f"f{i}_state"] == "H" for i in _v4_global(_v4_scope, 'range')(1, 5))
    return result


def __validate_rows_body(_v4_scope, /, rows, cutoff, *, require_full_pool):
    if not _v4_global(_v4_scope, 'isinstance')(rows, _v4_global(_v4_scope, 'Sequence')) or _v4_global(_v4_scope, 'isinstance')(rows, (_v4_global(_v4_scope, 'str'), _v4_global(_v4_scope, 'bytes'))):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("rows must be a sequence")
    if _v4_global(_v4_scope, 'len')(rows) < _v4_global(_v4_scope, 'TOP_K'):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("at least ten D1 members are required")
    if require_full_pool and _v4_global(_v4_scope, 'len')(rows) != _v4_global(_v4_scope, 'POOL_LIMIT'):
        raise _v4_global(_v4_scope, 'ShadowInvalid')(f"full D1 Top100 is required; got {_v4_global(_v4_scope, 'len')(rows)} rows")
    normalised = [_v4_global(_v4_scope, '_normalise_row')(row, cutoff) for row in rows]
    codes = [row["security_id"] for row in normalised]
    if _v4_global(_v4_scope, 'len')(_v4_global(_v4_scope, 'set')(codes)) != _v4_global(_v4_scope, 'len')(codes):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("duplicate security_id in D1 snapshot")
    eligible = [row for row in normalised if row["eligible"]]
    if _v4_global(_v4_scope, 'len')(eligible) < _v4_global(_v4_scope, 'TOP_K'):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("fewer than ten eligible production rows")
    ranks = [row["production_rank"] for row in eligible]
    if _v4_global(_v4_scope, 'sorted')(ranks) != _v4_global(_v4_scope, 'list')(_v4_global(_v4_scope, 'range')(1, _v4_global(_v4_scope, 'len')(eligible) + 1)):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("eligible production_rank must be contiguous from one")
    eligible.sort(key=lambda item: _v4_global(_v4_scope, 'int')(item["production_rank"]))
    for previous, current in _v4_global(_v4_scope, 'zip')(eligible, eligible[1:]):
        if _v4_global(_v4_scope, 'tuple')(previous["comparator_key"]) < _v4_global(_v4_scope, 'tuple')(current["comparator_key"]):
            raise _v4_global(_v4_scope, 'ShadowInvalid')("production_rank conflicts with hk_legacy_stage_sort_key")
    return normalised


def __derive_candidate_body(_v4_scope, /, eligible):
    ordered = [_v4_global(_v4_scope, 'dict')(row) for row in _v4_global(_v4_scope, 'sorted')(eligible, key=lambda item: _v4_global(_v4_scope, 'int')(item["production_rank"]))]
    baseline = ordered[:_v4_global(_v4_scope, 'TOP_K')]
    rank10 = baseline[-1]
    by_rank = {_v4_global(_v4_scope, 'int')(row["production_rank"]): row for row in ordered}
    rank10_class = _v4_global(_v4_scope, '_equivalence_class')(rank10)
    gaps: list[float] = []
    gap_pairs: list[dict[str, Any]] = []
    for rank in _v4_global(_v4_scope, 'range')(6, 15):
        left = by_rank.get(rank)
        right = by_rank.get(rank + 1)
        if left is None or right is None:
            continue
        if _v4_global(_v4_scope, '_equivalence_class')(left) != rank10_class or _v4_global(_v4_scope, '_equivalence_class')(right) != rank10_class:
            continue
        left_score = _v4_global(_v4_scope, '_finite')(left["stage_score"])
        right_score = _v4_global(_v4_scope, '_finite')(right["stage_score"])
        gap = left_score - right_score
        if gap < 0:
            raise _v4_global(_v4_scope, 'ShadowInvalid')("score order conflict inside rank10 equivalent class")
        gaps.append(gap)
        gap_pairs.append({"upper_rank": rank, "lower_rank": rank + 1, "gap": gap})
    if not gaps:
        raise _v4_global(_v4_scope, 'ShadowInvalid')("no valid rank6..15 score gap in rank10 equivalent class")
    tau = _v4_global(_v4_scope, 'float')(_v4_global(_v4_scope, 'statistics').median(gaps))
    if not _v4_global(_v4_scope, 'math').isfinite(tau) or tau < 0:
        raise _v4_global(_v4_scope, 'ShadowInvalid')("tau is not finite/non-negative")
    ambiguous = [
        row
        for row in ordered
        if _v4_global(_v4_scope, '_equivalence_class')(row) == rank10_class
        and _v4_global(_v4_scope, 'abs')(_v4_global(_v4_scope, '_finite')(row["stage_score"]) - _v4_global(_v4_scope, '_finite')(rank10["stage_score"])) <= tau
    ]
    ambiguous_codes = {_v4_global(_v4_scope, 'str')(row["security_id"]) for row in ambiguous}
    reordered_ambiguous = _v4_global(_v4_scope, 'sorted')(
        ambiguous,
        key=lambda row: (not _v4_global(_v4_scope, 'bool')(row["formula_any_H"]), _v4_global(_v4_scope, 'int')(row["production_rank"])),
    )
    candidate_order = _v4_global(_v4_scope, 'list')(ordered)
    replacements = _v4_global(_v4_scope, 'iter')(reordered_ambiguous)
    for index, row in _v4_global(_v4_scope, 'enumerate')(candidate_order):
        if _v4_global(_v4_scope, 'str')(row["security_id"]) in ambiguous_codes:
            candidate_order[index] = _v4_global(_v4_scope, 'next')(replacements)
    candidate = candidate_order[:_v4_global(_v4_scope, 'TOP_K')]
    baseline_codes = {_v4_global(_v4_scope, 'str')(row["security_id"]) for row in baseline}
    candidate_codes = {_v4_global(_v4_scope, 'str')(row["security_id"]) for row in candidate}
    for row in candidate_order:
        code = _v4_global(_v4_scope, 'str')(row["security_id"])
        row["baseline_selected"] = code in baseline_codes
        row["candidate_selected"] = code in candidate_codes
        if row["baseline_selected"] and row["candidate_selected"]:
            reason = "BASELINE_AND_CANDIDATE"
        elif row["candidate_selected"]:
            reason = "FORMULA_ANY_H_IN_AMBIGUOUS_CLASS"
        elif row["baseline_selected"]:
            reason = "BASELINE_ONLY"
        elif code in ambiguous_codes:
            reason = "AMBIGUOUS_STABLE_REORDER_OUTSIDE_TOP10"
        else:
            reason = "OUTSIDE_AMBIGUOUS_CLASS"
        row["selection_reason"] = reason
        row["ambiguous"] = code in ambiguous_codes
    details = {
        "rank10_code": _v4_global(_v4_scope, 'str')(rank10["security_id"]),
        "rank10_equivalence_class": {
            "lane": _v4_global(_v4_scope, 'list')(rank10_class[0]),
            "pre_score_key": _v4_global(_v4_scope, 'list')(rank10_class[1:]),
        },
        "tau": tau,
        "tau_zero_tie_only": tau == 0.0,
        "gap_pairs": gap_pairs,
        "ambiguous_codes": _v4_global(_v4_scope, 'sorted')(ambiguous_codes),
        "baseline_codes": [_v4_global(_v4_scope, 'str')(row["security_id"]) for row in baseline],
        "candidate_codes": [_v4_global(_v4_scope, 'str')(row["security_id"]) for row in candidate],
        "changed_in": _v4_global(_v4_scope, 'sorted')(candidate_codes - baseline_codes),
        "changed_out": _v4_global(_v4_scope, 'sorted')(baseline_codes - candidate_codes),
    }
    return candidate_order, details
