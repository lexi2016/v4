"""apps.api.v35_api.review_router: hk_projection (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __project_hk_review_body(_v4_scope, /, trade_date, source):
    """Project a verified Review Core DTO without re-verifying its evidence."""
    reasons = _v4_global(_v4_scope, '_strings')(source.get("cannot_confirm"))
    source_date = _v4_global(_v4_scope, 'str')(source.get("trade_date") or "")
    source_role = _v4_global(_v4_scope, 'str')(source.get("role") or "")
    artifact = source.get("artifact")
    if source_date != trade_date:
        reasons.append(f"HK_REVIEW_CORE_DATE_MISMATCH:{source_date or 'missing'}:{trade_date}")
        artifact = None
    if source_role != _v4_global(_v4_scope, 'HK_CLOSE_REVIEW_V1'):
        reasons.append(f"HK_REVIEW_CORE_ROLE_MISMATCH:{source_role or 'missing'}")
        artifact = None

    artifact_map = artifact if _v4_global(_v4_scope, 'isinstance')(artifact, _v4_global(_v4_scope, 'Mapping')) else None
    artifact_status = _v4_global(_v4_scope, 'str')(
        (artifact_map or {}).get("status") or source.get("status") or "CANNOT_CONFIRM"
    )
    mapped_status = _v4_global(_v4_scope, '_STATUS_MAP').get(artifact_status, "CANNOT_CONFIRM")
    if artifact_map is None:
        mapped_status = "CANNOT_CONFIRM"
        reasons.append(_v4_global(_v4_scope, 'HK_REVIEW_CORE_UNAVAILABLE'))
    if mapped_status == "CANNOT_CONFIRM" and _v4_global(_v4_scope, 'HK_REVIEW_CORE_UNAVAILABLE') not in reasons:
        reasons.append(_v4_global(_v4_scope, 'HK_REVIEW_CORE_UNAVAILABLE'))
    reasons = _v4_global(_v4_scope, 'list')(_v4_global(_v4_scope, 'dict').fromkeys(reasons))

    if artifact_map is None:
        models = {"0.2_prob_active": _v4_global(_v4_scope, '_unavailable_metric')()}
        stage_union = _v4_global(_v4_scope, '_unavailable_metric')()
        close_top20: list[Any] = []
        top20_attribution: list[Any] = []
        missing_stages: list[str] = []
        row_counts: dict[str, Any] = {}
    else:
        raw_models = artifact_map.get("models")
        models = _v4_global(_v4_scope, 'deepcopy')(_v4_global(_v4_scope, 'dict')(raw_models)) if _v4_global(_v4_scope, 'isinstance')(raw_models, _v4_global(_v4_scope, 'Mapping')) else {}
        models.setdefault("0.2_prob_active", _v4_global(_v4_scope, '_unavailable_metric')())
        raw_stage_union = artifact_map.get("stage_union")
        if not _v4_global(_v4_scope, 'isinstance')(raw_stage_union, _v4_global(_v4_scope, 'Mapping')) and _v4_global(_v4_scope, 'isinstance')(artifact_map.get("kpi"), _v4_global(_v4_scope, 'Mapping')):
            raw_stage_union = artifact_map["kpi"].get("stage_union")
        stage_union = (
            _v4_global(_v4_scope, 'deepcopy')(_v4_global(_v4_scope, 'dict')(raw_stage_union))
            if _v4_global(_v4_scope, 'isinstance')(raw_stage_union, _v4_global(_v4_scope, 'Mapping'))
            else _v4_global(_v4_scope, '_unavailable_metric')()
        )
        close_top20 = (
            _v4_global(_v4_scope, 'deepcopy')(artifact_map.get("close_top20"))
            if _v4_global(_v4_scope, 'isinstance')(artifact_map.get("close_top20"), _v4_global(_v4_scope, 'list'))
            else []
        )
        top20_attribution = (
            _v4_global(_v4_scope, 'deepcopy')(artifact_map.get("top20_attribution"))
            if _v4_global(_v4_scope, 'isinstance')(artifact_map.get("top20_attribution"), _v4_global(_v4_scope, 'list'))
            else []
        )
        missing_stages = _v4_global(_v4_scope, '_strings')(artifact_map.get("missing_stages"))
        if not missing_stages:
            missing_stages = _v4_global(_v4_scope, '_strings')(artifact_map.get("missing_stage_roles"))
        row_counts = (
            _v4_global(_v4_scope, 'deepcopy')(_v4_global(_v4_scope, 'dict')(artifact_map.get("row_counts")))
            if _v4_global(_v4_scope, 'isinstance')(artifact_map.get("row_counts"), _v4_global(_v4_scope, 'Mapping'))
            else {}
        )
        reasons = _v4_global(_v4_scope, 'list')(_v4_global(_v4_scope, 'dict').fromkeys(reasons + _v4_global(_v4_scope, '_strings')(artifact_map.get("cannot_confirm"))))

    source_sha = _v4_global(_v4_scope, 'str')(source.get("artifact_sha256") or "")
    review = {
        "schema_version": _v4_global(_v4_scope, 'str')((artifact_map or {}).get("schema_version") or _v4_global(_v4_scope, 'HK_CLOSE_REVIEW_V1')),
        "artifact_role": _v4_global(_v4_scope, 'str')((artifact_map or {}).get("role") or source_role or _v4_global(_v4_scope, 'HK_CLOSE_REVIEW_V1')),
        "artifact_version": _v4_global(_v4_scope, 'str')((artifact_map or {}).get("version") or _v4_global(_v4_scope, 'HK_CLOSE_REVIEW_V1')),
        "trade_date": trade_date,
        "status": mapped_status,
        "artifact_status": artifact_status,
        "source_role": source_role or _v4_global(_v4_scope, 'HK_CLOSE_REVIEW_V1'),
        "source_run_id": _v4_global(_v4_scope, 'str')(source.get("run_id") or ""),
        "source_sha256": source_sha,
        "artifact_sha256": source_sha,
        "manifest_sha256": _v4_global(_v4_scope, 'str')(source.get("manifest_sha256") or ""),
        "receipt_sha256": _v4_global(_v4_scope, 'str')(source.get("receipt_sha256") or ""),
        "paths": _v4_global(_v4_scope, 'deepcopy')(_v4_global(_v4_scope, 'dict')(source.get("paths"))) if _v4_global(_v4_scope, 'isinstance')(source.get("paths"), _v4_global(_v4_scope, 'Mapping')) else {},
        "row_counts": row_counts,
        "models": models,
        "stage_union": stage_union,
        "close_top20": close_top20,
        "top20_attribution": top20_attribution,
        "missing_stages": missing_stages,
        "cannot_confirm": reasons,
        "source_merge_role": "SOURCE_ONLY",
        "stage_selection_eligible": False,
        "reference_snapshot": False,
        **_v4_global(_v4_scope, '_SAFETY_FLAGS'),
    }
    return review


def __hk_parent_body(_v4_scope, /, trade_date, source):
    review = _v4_global(_v4_scope, '_project_hk_review')(trade_date, source)
    return {
        "market": "HK",
        "display_name": "港股通复盘",
        "trade_date": trade_date,
        "status": review["status"],
        "artifact_status": review["artifact_status"],
        "artifact_role": review["artifact_role"],
        "artifact_version": review["artifact_version"],
        "source_role": _v4_global(_v4_scope, 'str')(source.get("role") or _v4_global(_v4_scope, 'HK_CLOSE_REVIEW_V1')),
        "source_merge_role": "SOURCE_ONLY",
        "source_run_id": review["source_run_id"],
        "source_sha256": review["source_sha256"],
        "artifact_sha256": review["artifact_sha256"],
        "manifest_sha256": review["manifest_sha256"],
        "receipt_sha256": review["receipt_sha256"],
        "model_selection_review": review,
        **_v4_global(_v4_scope, '_SAFETY_FLAGS'),
    }


def __native_hk_parent_body(_v4_scope, /, trade_date, reference):
    """Project a strictly verified V3.5 native close-review artifact."""
    digest = _v4_global(_v4_scope, '_sha256')(reference)
    reference_snapshot = _v4_global(_v4_scope, 'bool')(reference.get("reference_snapshot"))
    review = _v4_global(_v4_scope, 'deepcopy')(_v4_global(_v4_scope, 'dict')(reference))
    review.update(
        {
            "artifact_role": "V3_5_NATIVE_CLOSE_MODEL",
            "artifact_version": "v3_5.close_review.v1",
            "artifact_status": _v4_global(_v4_scope, 'str')(reference.get("status") or "CANNOT_CONFIRM"),
            "source_role": "V3_5_NATIVE_CLOSE_MODEL",
            "source_merge_role": "V35_NATIVE_REVIEW_STORE",
            "source_sha256": _v4_global(_v4_scope, 'str')(reference.get("close_source_sha256") or digest),
            "artifact_sha256": digest,
            "manifest_sha256": "",
            "receipt_sha256": "",
            "stage_selection_eligible": False,
            "reference_snapshot": reference_snapshot,
            **_v4_global(_v4_scope, '_SAFETY_FLAGS'),
        }
    )
    return {
        "market": "HK",
        "display_name": "港股通复盘",
        "trade_date": trade_date,
        "status": review.get("status", "CANNOT_CONFIRM"),
        "artifact_status": review["artifact_status"],
        "artifact_role": review["artifact_role"],
        "artifact_version": review["artifact_version"],
        "source_role": review["source_role"],
        "source_merge_role": review["source_merge_role"],
        "source_run_id": "",
        "source_sha256": review["source_sha256"],
        "artifact_sha256": review["artifact_sha256"],
        "manifest_sha256": review["manifest_sha256"],
        "receipt_sha256": review["receipt_sha256"],
        "model_selection_review": review,
        **_v4_global(_v4_scope, '_SAFETY_FLAGS'),
    }


def __native_hk_invalid_parent_body(_v4_scope, /, trade_date, error):
    review = {
        "schema_version": "v3_5.close_review.v1",
        "trade_date": trade_date,
        "status": "CANNOT_CONFIRM",
        "artifact_status": "CANNOT_CONFIRM",
        "artifact_role": "V3_5_NATIVE_CLOSE_MODEL",
        "artifact_version": "v3_5.close_review.v1",
        "source_role": "V3_5_NATIVE_CLOSE_MODEL",
        "source_merge_role": "V35_NATIVE_REVIEW_STORE",
        "models": {"0.2_prob_active": _v4_global(_v4_scope, '_unavailable_metric')()},
        "stages": {},
        "stage_union": _v4_global(_v4_scope, '_unavailable_metric')(),
        "kpi": {},
        "row_counts": {},
        "close_top20": [],
        "model_rows": [],
        "stage_rows": [],
        "top20_attribution": [],
        "missing_stages": [],
        "cannot_confirm": [f"V35_NATIVE_CLOSE_REVIEW_INVALID:{_v4_global(_v4_scope, 'type')(error).__name__}: {error}"],
        "source_sha256": "",
        "artifact_sha256": "",
        "manifest_sha256": "",
        "receipt_sha256": "",
        "reference_snapshot": False,
        "stage_selection_eligible": False,
        **_v4_global(_v4_scope, '_SAFETY_FLAGS'),
    }
    return {
        "market": "HK",
        "display_name": "港股通复盘",
        "trade_date": trade_date,
        "status": "CANNOT_CONFIRM",
        "artifact_status": "CANNOT_CONFIRM",
        "artifact_role": review["artifact_role"],
        "artifact_version": review["artifact_version"],
        "source_role": review["source_role"],
        "source_merge_role": review["source_merge_role"],
        "source_run_id": "",
        "source_sha256": "",
        "artifact_sha256": "",
        "manifest_sha256": "",
        "receipt_sha256": "",
        "model_selection_review": review,
        **_v4_global(_v4_scope, '_SAFETY_FLAGS'),
    }


def __native_hk_review_body(_v4_scope, /, data_root, trade_date):
    """Return (parent, present) and never bridge around a present invalid artifact."""
    store = _v4_global(_v4_scope, 'ReviewStore')(data_root)
    artifact_path = store.root / "close_reviews" / f"{trade_date}.json"
    if not artifact_path.is_file():
        return None, False
    try:
        reference = store.read_reference(trade_date)
    except (_v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'ValueError')) as error:
        return _v4_global(_v4_scope, '_native_hk_invalid_parent')(trade_date, error), True
    if reference is None:
        return _v4_global(_v4_scope, '_native_hk_invalid_parent')(trade_date, _v4_global(_v4_scope, 'ValueError')("native artifact is absent")), True
    return _v4_global(_v4_scope, '_native_hk_parent')(trade_date, reference), True
