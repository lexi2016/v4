"""stage_center.formula_margin_shadow: evaluation (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __markout_for_codes_body(_v4_scope, /, rows, label_by_code, codes):
    values: list[float] = []
    invalid: list[str] = []
    for code in codes:
        member = _v4_global(_v4_scope, 'next')((row for row in rows if _v4_global(_v4_scope, 'str')(row.get("security_id")) == _v4_global(_v4_scope, 'str')(code)), None)
        label = label_by_code.get(_v4_global(_v4_scope, 'str')(code))
        if member is None or label is None:
            invalid.append(f"MISSING_MARKOUT_ROW:{code}")
            continue
        try:
            stage_price = _v4_global(_v4_scope, '_finite')(member.get("stage_price"))
            close_price = _v4_global(_v4_scope, '_finite')(label.get("close_price"))
        except _v4_global(_v4_scope, 'ShadowInvalid'):
            invalid.append(f"MISSING_MARKOUT_PRICE:{code}")
            continue
        if stage_price <= 0 or close_price <= 0:
            invalid.append(f"INVALID_MARKOUT_PRICE:{code}")
            continue
        if _v4_global(_v4_scope, 'str')(member.get("currency")) != _v4_global(_v4_scope, 'str')(label.get("currency")):
            invalid.append(f"MARKOUT_CURRENCY_MISMATCH:{code}")
            continue
        if _v4_global(_v4_scope, 'str')(member.get("adjustment_mode")) != _v4_global(_v4_scope, 'str')(label.get("adjustment_mode")):
            invalid.append(f"MARKOUT_ADJUSTMENT_MISMATCH:{code}")
            continue
        values.append(close_price / stage_price - 1.0)
    return values, invalid


def _evaluate_run_body(_v4_scope, /, run_root):
    """Evaluate one frozen unit; labels are never used to rebuild a candidate."""

    members, baseline, candidate, receipt = _v4_global(_v4_scope, '_read_frozen')(run_root)
    label_path = _v4_global(_v4_scope, 'Path')(run_root).expanduser().resolve() / "labels" / "labels.json"
    if not label_path.is_file() or label_path.is_symlink():
        return {
            "status": "CANNOT_CONFIRM",
            "trade_date": receipt.get("trade_date"),
            "stage": receipt.get("stage"),
            "invalid_reasons": ["LABELS_NOT_APPENDED_AFTER_FREEZE"],
        }
    labels = _v4_global(_v4_scope, '_read_json')(label_path)
    ledger_path = _v4_global(_v4_scope, 'Path')(run_root).expanduser().resolve() / "labels" / "invalid_ledger.json"
    if not ledger_path.is_file() or ledger_path.is_symlink():
        return {
            "status": "CANNOT_CONFIRM",
            "trade_date": receipt.get("trade_date"),
            "stage": receipt.get("stage"),
            "invalid_reasons": ["LABEL_INVALID_LEDGER_MISSING"],
        }
    ledger = _v4_global(_v4_scope, '_read_json')(ledger_path)
    if not _v4_global(_v4_scope, 'isinstance')(ledger, _v4_global(_v4_scope, 'Mapping')) or ledger.get("labels_sha256") != _v4_global(_v4_scope, 'sha256_file')(label_path):
        return {
            "status": "CANNOT_CONFIRM",
            "trade_date": receipt.get("trade_date"),
            "stage": receipt.get("stage"),
            "invalid_reasons": ["LABEL_HASH_MISMATCH"],
        }
    if not _v4_global(_v4_scope, 'isinstance')(labels, _v4_global(_v4_scope, 'Mapping')) or labels.get("selection_receipt_sha256") != _v4_global(_v4_scope, 'sha256_file')(_v4_global(_v4_scope, 'Path')(run_root).expanduser().resolve() / "selection_receipt.json"):
        return {
            "status": "CANNOT_CONFIRM",
            "trade_date": receipt.get("trade_date"),
            "stage": receipt.get("stage"),
            "invalid_reasons": ["LABEL_SELECTION_RECEIPT_BINDING_MISMATCH"],
        }
    label_status = labels.get("status") if _v4_global(_v4_scope, 'isinstance')(labels, _v4_global(_v4_scope, 'Mapping')) else None
    if not _v4_global(_v4_scope, 'isinstance')(labels, _v4_global(_v4_scope, 'Mapping')) or label_status not in {"READY", "ENGINEERING_ONLY"}:
        return {
            "status": "CANNOT_CONFIRM",
            "trade_date": receipt.get("trade_date"),
            "stage": receipt.get("stage"),
            "invalid_reasons": _v4_global(_v4_scope, 'list')(labels.get("invalid_reasons", [])) if _v4_global(_v4_scope, 'isinstance')(labels, _v4_global(_v4_scope, 'Mapping')) else ["LABEL_PAYLOAD_INVALID"],
        }
    label_by_code = {_v4_global(_v4_scope, 'str')(row.get("security_id")): row for row in labels.get("rows", []) if _v4_global(_v4_scope, 'isinstance')(row, _v4_global(_v4_scope, 'Mapping'))}
    truth = labels.get("truth") if _v4_global(_v4_scope, 'isinstance')(labels.get("truth"), _v4_global(_v4_scope, 'Mapping')) else {}
    top20 = _v4_global(_v4_scope, 'set')(_v4_global(_v4_scope, 'str')(code) for code in truth.get("truth_top20_codes", []))
    baseline_codes = [_v4_global(_v4_scope, 'str')(code) for code in baseline.get("codes", [])]
    candidate_codes = [_v4_global(_v4_scope, 'str')(code) for code in candidate.get("codes", [])]
    baseline_hits = _v4_global(_v4_scope, 'sum')(code in top20 for code in baseline_codes)
    candidate_hits = _v4_global(_v4_scope, 'sum')(code in top20 for code in candidate_codes)
    pool_codes = {_v4_global(_v4_scope, 'str')(row.get("security_id")) for row in members.get("rows", [])}
    pool_truth = _v4_global(_v4_scope, 'len')(pool_codes & top20)
    entered = _v4_global(_v4_scope, 'sorted')(_v4_global(_v4_scope, 'set')(candidate_codes) - _v4_global(_v4_scope, 'set')(baseline_codes))
    exited = _v4_global(_v4_scope, 'sorted')(_v4_global(_v4_scope, 'set')(baseline_codes) - _v4_global(_v4_scope, 'set')(candidate_codes))
    member_rows = members.get("rows", [])
    baseline_markout, baseline_markout_invalid = _v4_global(_v4_scope, '_markout_for_codes')(member_rows, label_by_code, baseline_codes)
    candidate_markout, candidate_markout_invalid = _v4_global(_v4_scope, '_markout_for_codes')(member_rows, label_by_code, candidate_codes)
    entered_markout, entered_invalid = _v4_global(_v4_scope, '_markout_for_codes')(member_rows, label_by_code, entered)
    exited_markout, exited_invalid = _v4_global(_v4_scope, '_markout_for_codes')(member_rows, label_by_code, exited)
    return {
        "status": _v4_global(_v4_scope, 'str')(label_status),
        "admission_mode": labels.get("admission_mode"),
        "hit_ready": label_status == "READY",
        "counts_as_forward_day": False,
        "natural_sample_count": 0,
        "trade_date": receipt["trade_date"],
        "stage": receipt["stage"],
        "truth_scope": truth.get("truth_scope"),
        "baseline_hit_count": baseline_hits,
        "candidate_hit_count": candidate_hits,
        "delta_hit_count": candidate_hits - baseline_hits,
        "d1_pool_truth_count": pool_truth,
        "d1_pool_recall": pool_truth / _v4_global(_v4_scope, 'TRUTH_K'),
        "baseline_codes": baseline_codes,
        "candidate_codes": candidate_codes,
        "entered_codes": entered,
        "exited_codes": exited,
        "markout": {
            "status": "READY" if not (baseline_markout_invalid + candidate_markout_invalid) else "CANNOT_CONFIRM",
            "baseline": _v4_global(_v4_scope, '_summary')(baseline_markout),
            "candidate": _v4_global(_v4_scope, '_summary')(candidate_markout),
            "entered": _v4_global(_v4_scope, '_summary')(entered_markout),
            "exited": _v4_global(_v4_scope, '_summary')(exited_markout),
            "invalid_reasons": baseline_markout_invalid + candidate_markout_invalid + entered_invalid + exited_invalid,
        },
    }


def _evaluate_runs_body(_v4_scope, /, run_roots):
    units = [_v4_global(_v4_scope, 'evaluate_run')(root) for root in run_roots]
    valid = [unit for unit in units if unit.get("status") == "READY"]
    engineering = [unit for unit in units if unit.get("status") == "ENGINEERING_ONLY"]
    invalid = [unit for unit in units if unit.get("status") not in {"READY", "ENGINEERING_ONLY"}]
    planned = _v4_global(_v4_scope, 'len')(units)
    valid_count = _v4_global(_v4_scope, 'len')(valid)
    baseline_hits = _v4_global(_v4_scope, 'sum')(_v4_global(_v4_scope, 'int')(unit["baseline_hit_count"]) for unit in valid)
    candidate_hits = _v4_global(_v4_scope, 'sum')(_v4_global(_v4_scope, 'int')(unit["candidate_hit_count"]) for unit in valid)
    denominator = _v4_global(_v4_scope, 'TOP_K') * valid_count
    recall_denominator = _v4_global(_v4_scope, 'TRUTH_K') * valid_count
    changed_in = _v4_global(_v4_scope, 'sum')(_v4_global(_v4_scope, 'len')(unit.get("entered_codes", [])) for unit in valid)
    changed_out = _v4_global(_v4_scope, 'sum')(_v4_global(_v4_scope, 'len')(unit.get("exited_codes", [])) for unit in valid)
    engineering_changed_in = _v4_global(_v4_scope, 'sum')(_v4_global(_v4_scope, 'len')(unit.get("entered_codes", [])) for unit in engineering)
    engineering_changed_out = _v4_global(_v4_scope, 'sum')(_v4_global(_v4_scope, 'len')(unit.get("exited_codes", [])) for unit in engineering)
    required_capacity = _v4_global(_v4_scope, 'math').ceil(0.05 * _v4_global(_v4_scope, 'TOP_K') * planned)
    all_truth_hits = _v4_global(_v4_scope, 'sum')(_v4_global(_v4_scope, 'int')(unit.get("d1_pool_truth_count", 0)) for unit in valid)
    result: dict[str, Any] = {
        "experiment_id": _v4_global(_v4_scope, 'EXPERIMENT_ID'),
        "truth_scope": _v4_global(_v4_scope, 'TRUTH_SCOPE'),
        "planned_units": planned,
        "valid_units": valid_count,
        "engineering_units": _v4_global(_v4_scope, 'len')(engineering),
        "invalid_units": _v4_global(_v4_scope, 'len')(invalid),
        "natural_sample_count": _v4_global(_v4_scope, 'sum')(_v4_global(_v4_scope, 'int')(unit.get("natural_sample_count", 0)) for unit in valid),
        "invalid_reasons": [reason for unit in invalid for reason in unit.get("invalid_reasons", [])],
        "fixed_p10_denominator": denominator if valid_count else None,
        "fixed_recall20_denominator": recall_denominator if valid_count else None,
        "baseline_hit_count": baseline_hits if valid_count else None,
        "candidate_hit_count": candidate_hits if valid_count else None,
        "delta_hit_count": (candidate_hits - baseline_hits) if valid_count else None,
        "baseline_p_at_10": baseline_hits / denominator if denominator else None,
        "candidate_p_at_10": candidate_hits / denominator if denominator else None,
        "delta_p_points": (candidate_hits - baseline_hits) / denominator if denominator else None,
        "baseline_recall_at_20": baseline_hits / recall_denominator if recall_denominator else None,
        "candidate_recall_at_20": candidate_hits / recall_denominator if recall_denominator else None,
        "d1_pool_recall_at_20": all_truth_hits / recall_denominator if recall_denominator else None,
        "selection_ceiling_at_20": all_truth_hits / recall_denominator if recall_denominator else None,
        "changed_in_count": changed_in,
        "changed_out_count": changed_out,
        "engineering_changed_in_count": engineering_changed_in,
        "engineering_changed_out_count": engineering_changed_out,
        "capacity_required_for_5pp": required_capacity,
        "capacity_status": (
            "INSUFFICIENT_INTERVENTION_CAPACITY_FOR_5PP"
            if changed_in < required_capacity
            else "CAPACITY_REACHED_FOR_5PP_REVIEW"
        ),
        "units": units,
        **_v4_global(_v4_scope, 'SAFETY_FLAGS'),
    }
    if invalid or not valid_count:
        result["evaluation_status"] = "CANNOT_CONFIRM" if invalid or not engineering else "ENGINEERING_ONLY"
    else:
        result["evaluation_status"] = "READY"
    # Stages are reported independently while the aggregate remains the only
    # verdict; no best-stage selection is allowed.
    by_stage: dict[str, list[dict[str, Any]]] = {}
    by_date: dict[str, list[dict[str, Any]]] = {}
    for unit in valid:
        by_stage.setdefault(_v4_global(_v4_scope, 'str')(unit["stage"]), []).append(unit)
        by_date.setdefault(_v4_global(_v4_scope, 'str')(unit["trade_date"]), []).append(unit)
    result["by_stage"] = {
        stage: {
            "units": _v4_global(_v4_scope, 'len')(items),
            "baseline_hits": _v4_global(_v4_scope, 'sum')(_v4_global(_v4_scope, 'int')(item["baseline_hit_count"]) for item in items),
            "candidate_hits": _v4_global(_v4_scope, 'sum')(_v4_global(_v4_scope, 'int')(item["candidate_hit_count"]) for item in items),
            "delta_hits": _v4_global(_v4_scope, 'sum')(_v4_global(_v4_scope, 'int')(item["delta_hit_count"]) for item in items),
        }
        for stage, items in _v4_global(_v4_scope, 'sorted')(by_stage.items())
    }
    result["by_trade_date"] = {
        trade_date: {
            "units": _v4_global(_v4_scope, 'len')(items),
            "baseline_hits": _v4_global(_v4_scope, 'sum')(_v4_global(_v4_scope, 'int')(item["baseline_hit_count"]) for item in items),
            "candidate_hits": _v4_global(_v4_scope, 'sum')(_v4_global(_v4_scope, 'int')(item["candidate_hit_count"]) for item in items),
            "delta_hits": _v4_global(_v4_scope, 'sum')(_v4_global(_v4_scope, 'int')(item["delta_hit_count"]) for item in items),
        }
        for trade_date, items in _v4_global(_v4_scope, 'sorted')(by_date.items())
    }
    return result
