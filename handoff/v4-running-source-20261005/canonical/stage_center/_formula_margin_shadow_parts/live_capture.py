"""stage_center.formula_margin_shadow: live_capture (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _capture_selector_snapshot_body(_v4_scope, /, payload_or_path, output_root):
    """Capture a real HK four-lane selector call through its opt-in hook.

    The input contains the same raw rows and verified provenance consumed by
    the selector.  This function invokes ``select_hk_four_lane`` and lets the
    hook assign ranks from the real full sorted output; callers never provide a
    hand-ranked production list.  A failed shadow capture is recorded as an
    immutable invalid ledger while the returned selector envelope remains the
    production result.
    """

    payload = _v4_global(_v4_scope, '_read_json')(payload_or_path) if _v4_global(_v4_scope, 'isinstance')(payload_or_path, (_v4_global(_v4_scope, 'Path'), _v4_global(_v4_scope, 'str'))) else payload_or_path
    if not _v4_global(_v4_scope, 'isinstance')(payload, _v4_global(_v4_scope, 'Mapping')):
        invalid = _v4_global(_v4_scope, 'record_invalid_capture')(output_root, {}, ["CAPTURE_INPUT_NOT_OBJECT"])
        return {
            "status": "CANNOT_CONFIRM",
            "capture": invalid,
            "hit_ready": False,
            "counts_as_forward_day": False,
            "natural_sample_count": 0,
            **_v4_global(_v4_scope, 'SAFETY_FLAGS'),
        }
    metadata = _v4_global(_v4_scope, 'dict')(_v4_global(_v4_scope, '_metadata_from_input')(payload))
    try:
        admission_mode = _v4_global(_v4_scope, '_admission_mode')(metadata, default=None)
        _v4_global(_v4_scope, '_validate_capture_request_static')(payload)
    except _v4_global(_v4_scope, 'ShadowInvalid') as error:
        invalid = _v4_global(_v4_scope, 'record_invalid_capture')(output_root, metadata, [_v4_global(_v4_scope, 'str')(error)])
        return {
            "status": "CANNOT_CONFIRM",
            "capture": invalid,
            "hit_ready": False,
            "counts_as_forward_day": False,
            "natural_sample_count": 0,
            **_v4_global(_v4_scope, 'SAFETY_FLAGS'),
        }
    rows = payload.get("rows")
    formula_manifest = payload.get("formula_manifest", metadata.get("formula_manifest"))
    time_evidence = payload.get("time_evidence", metadata.get("time_evidence"))
    d1_manifest = payload.get("d1_manifest", metadata.get("d1_manifest"))
    trade_date = _v4_global(_v4_scope, 'str')(metadata.get("trade_date") or "").replace("-", "")
    stage_id = _v4_global(_v4_scope, 'str')(metadata.get("stage") or metadata.get("stage_id") or "")
    raw_artifact_sha = metadata.get("raw_artifact_sha256")
    capture_result: dict[str, Any] = {}
    capture_state: dict[str, Any] = {}

    def _record(result: Mapping[str, Any]) -> None:
        capture_result.clear()
        capture_result.update(_v4_global(_v4_scope, 'dict')(result))

    def _capture_callback(
        *,
        raw_rows: Sequence[Mapping[str, Any]],
        sorted_rows: Sequence[Mapping[str, Any]],
        production_rows: Sequence[Mapping[str, Any]],
        context: Mapping[str, Any],
    ) -> None:
        try:
            shadow_payload = _v4_global(_v4_scope, 'build_selector_capture_payload')(
                metadata=metadata,
                raw_rows=raw_rows,
                sorted_rows=sorted_rows,
                production_rows=production_rows,
                formula_manifest=formula_manifest,
                time_evidence=time_evidence,
                d1_manifest=d1_manifest,
                raw_artifact_sha256=_v4_global(_v4_scope, 'str')(context.get("raw_artifact_sha256") or raw_artifact_sha or ""),
            )
            production_codes = [
                _v4_global(_v4_scope, '_canonical_code')(row.get("security_id", row.get("code")))
                for row in production_rows
                if _v4_global(_v4_scope, 'isinstance')(row, _v4_global(_v4_scope, 'Mapping'))
            ][:_v4_global(_v4_scope, 'TOP_K')]
            # Keep the production invocation and its full sorted evidence in
            # memory until the selector returns.  Freezing in the callback
            # would make an observer failure look like selector success.
            capture_state["shadow_payload"] = shadow_payload
            capture_state["production_codes"] = production_codes
            capture_state["context"] = _v4_global(_v4_scope, 'dict')(context)
        except _v4_global(_v4_scope, 'ShadowInvalid') as error:
            _record(_v4_global(_v4_scope, 'record_invalid_capture')(
                output_root,
                metadata,
                [_v4_global(_v4_scope, 'str')(error)],
                context={"hook_context": _v4_global(_v4_scope, 'dict')(context)},
            ))
        except _v4_global(_v4_scope, 'Exception') as error:  # pragma: no cover - external filesystem/runtime failures
            _record(_v4_global(_v4_scope, 'record_invalid_capture')(
                output_root,
                metadata,
                [f"CAPTURE_EXCEPTION:{error}"],
                context={"hook_context": _v4_global(_v4_scope, 'dict')(context)},
            ))

    def _capture_error(*, error: Exception, context: Mapping[str, Any]) -> None:
        _record(_v4_global(_v4_scope, 'record_invalid_capture')(
            output_root,
            metadata,
            [f"SHADOW_CALLBACK_FAILED:{error}"],
            context={"hook_context": _v4_global(_v4_scope, 'dict')(context)},
        ))

    if not _v4_global(_v4_scope, 'isinstance')(rows, _v4_global(_v4_scope, 'list')):
        invalid = _v4_global(_v4_scope, 'record_invalid_capture')(output_root, metadata, ["CAPTURE_ROWS_REQUIRED"])
        return {
            "status": "CANNOT_CONFIRM",
            "capture": invalid,
            "hit_ready": False,
            "counts_as_forward_day": False,
            "natural_sample_count": 0,
            **_v4_global(_v4_scope, 'SAFETY_FLAGS'),
        }
    if stage_id not in _v4_global(_v4_scope, 'STAGE_CUTOFFS'):
        invalid = _v4_global(_v4_scope, 'record_invalid_capture')(output_root, metadata, [f"UNSUPPORTED_STAGE:{stage_id}"])
        return {
            "status": "CANNOT_CONFIRM",
            "capture": invalid,
            "hit_ready": False,
            "counts_as_forward_day": False,
            "natural_sample_count": 0,
            **_v4_global(_v4_scope, 'SAFETY_FLAGS'),
        }
    runtime_started_at: datetime | None = None
    try:
        # The invocation itself, including engineering shadow captures, is
        # stamped by the private runtime clock.  The input JSON timestamp is
        # never used as natural-capture evidence.
        runtime_started_at = _v4_global(_v4_scope, '_validate_runtime_capture_timestamp')(
            _v4_global(_v4_scope, '_runtime_capture_timestamp')(), trade_date, stage_id
        )
        # Import lazily so the frozen shadow module remains a consumer of the
        # selector hook rather than a second selector implementation.
        from stage_center.selection import select_hk_four_lane

        selected = select_hk_four_lane(
            rows,
            trade_date,
            stage_id,
            _v4_global(_v4_scope, 'str')(raw_artifact_sha or ""),
            source_status=_v4_global(_v4_scope, 'str')(metadata.get("source_status") or "READY"),
            requested_rows=metadata.get("requested_rows"),
            missing_symbols=_v4_global(_v4_scope, 'tuple')(metadata.get("missing_symbols") or ()),
            cannot_confirm=_v4_global(_v4_scope, 'tuple')(metadata.get("cannot_confirm") or ()),
            source_evidence=_v4_global(_v4_scope, 'tuple')(metadata.get("source_evidence") or ()),
            cap_limit_yi=_v4_global(_v4_scope, 'float')(metadata.get("cap_limit_yi", 100.0)),
            shadow_capture=_capture_callback,
            shadow_context=metadata,
            shadow_capture_error=_capture_error,
        )
    except _v4_global(_v4_scope, 'Exception') as error:
        if not capture_result:
            _record(_v4_global(_v4_scope, 'record_invalid_capture')(
                output_root,
                metadata,
                [f"SELECTOR_CAPTURE_FAILED:{error}"],
                context={"stage": stage_id, "trade_date": trade_date},
            ))
        return {
            "status": "CANNOT_CONFIRM",
            "selector_error": _v4_global(_v4_scope, 'str')(error),
            "capture": _v4_global(_v4_scope, 'dict')(capture_result),
            "hit_ready": False,
            "counts_as_forward_day": False,
            "natural_sample_count": 0,
            **_v4_global(_v4_scope, 'SAFETY_FLAGS'),
        }
    if not capture_state.get("shadow_payload"):
        if not capture_result:
            _record(_v4_global(_v4_scope, 'record_invalid_capture')(
                output_root,
                metadata,
                ["SHADOW_CAPTURE_NOT_INVOKED"],
                context={"stage": stage_id, "trade_date": trade_date},
            ))
        return {
            "status": "CANNOT_CONFIRM",
            "selector_status": selected.get("selection_status"),
            "selector": selected,
            "capture": _v4_global(_v4_scope, 'dict')(capture_result),
            "hit_ready": False,
            "counts_as_forward_day": False,
            "natural_sample_count": 0,
            **_v4_global(_v4_scope, 'SAFETY_FLAGS'),
        }
    try:
        shadow_payload = _v4_global(_v4_scope, 'dict')(capture_state["shadow_payload"])
        production_codes = _v4_global(_v4_scope, 'list')(capture_state["production_codes"])
        expected_raw_sha = _v4_global(_v4_scope, 'str')(shadow_payload.get("raw_artifact_sha256") or raw_artifact_sha or "").lower()
        actual_selector = _v4_global(_v4_scope, '_validate_selector_return')(
            selected,
            shadow_payload,
            expected_raw_artifact_sha=expected_raw_sha,
        )
        for key in ("run_id", "artifact_id"):
            supplied = metadata.get(key)
            if supplied not in (None, "") and _v4_global(_v4_scope, 'str')(supplied).strip() != actual_selector[key]:
                raise _v4_global(_v4_scope, 'ShadowInvalid')(f"caller {key} does not match selector return envelope")
        if actual_selector["top10_codes"] != production_codes:
            raise _v4_global(_v4_scope, 'ShadowInvalid')("selector return Top10 does not match callback production Top10")
        # Only the post-selector envelope is authoritative.  The callback's
        # advisory context can never become a production identity.
        shadow_payload["run_id"] = actual_selector["run_id"]
        shadow_payload["artifact_id"] = actual_selector["artifact_id"]
        shadow_payload["algorithm_sha256"] = actual_selector["algorithm_sha256"]
        shadow_payload["raw_artifact_sha256"] = actual_selector["raw_artifact_sha256"]
        shadow_payload["selector_result"] = _v4_global(_v4_scope, 'dict')(selected)
        runtime_finished_at = _v4_global(_v4_scope, '_validate_runtime_capture_timestamp')(
            _v4_global(_v4_scope, '_runtime_capture_timestamp')(), trade_date, stage_id
        )
        if runtime_started_at is None:
            raise _v4_global(_v4_scope, 'ShadowInvalid')("selector runtime start receipt is missing")
        shadow_payload["capture_time_receipt"] = _v4_global(_v4_scope, '_capture_time_receipt_payload')(
            shadow_payload,
            selector_result=selected,
            selector_started_at=runtime_started_at,
            selector_finished_at=runtime_finished_at,
        )
        shadow_payload["captured_at"] = runtime_finished_at.isoformat()
        shadow_payload["time_evidence"] = {
            "source": _v4_global(_v4_scope, 'CAPTURE_TIME_SOURCE'),
            "captured_at": runtime_finished_at.isoformat(),
            "trade_date": trade_date,
            "stage": stage_id,
            "cutoff_ts": shadow_payload.get("cutoff_ts"),
        }
        # The start value is retained in the local diagnostic context for
        # tests/logging only; the immutable receipt is the completion time.
        built = _v4_global(_v4_scope, 'build_shadow')(
            shadow_payload,
            require_full_pool=True,
            require_artifacts=True,
            allow_invocation_verified=True,
        )
        if built.get("baseline", {}).get("codes") != production_codes:
            raise _v4_global(_v4_scope, 'ShadowInvalid')("frozen baseline does not equal the real selector Top10")
        if built.get("baseline", {}).get("codes") != actual_selector["top10_codes"]:
            raise _v4_global(_v4_scope, 'ShadowInvalid')("frozen baseline does not equal returned selector Top10")
        frozen = _v4_global(_v4_scope, '_freeze_snapshot_internal')(
            shadow_payload,
            output_root,
            require_full_pool=True,
            allow_invocation_verified=True,
        )
        capture_status = "ENGINEERING_ONLY" if admission_mode == _v4_global(_v4_scope, 'ENGINEERING_FIXTURE') else "READY"
        _record({
            "status": capture_status,
            "freeze_status": frozen.get("status"),
            "selector_top10_codes": production_codes,
            "capture": frozen,
        })
    except _v4_global(_v4_scope, 'ShadowInvalid') as error:
        _record(_v4_global(_v4_scope, 'record_invalid_capture')(
            output_root,
            metadata,
            [_v4_global(_v4_scope, 'str')(error)],
            context={"hook_context": _v4_global(_v4_scope, 'dict')(capture_state.get("context") or {})},
        ))
    except _v4_global(_v4_scope, 'Exception') as error:  # pragma: no cover - external filesystem/runtime failures
        _record(_v4_global(_v4_scope, 'record_invalid_capture')(
            output_root,
            metadata,
            [f"CAPTURE_EXCEPTION:{error}"],
            context={"hook_context": _v4_global(_v4_scope, 'dict')(capture_state.get("context") or {})},
        ))
    return {
        "status": capture_result.get("status") if capture_result.get("status") in {"READY", "ENGINEERING_ONLY"} else "CANNOT_CONFIRM",
        "hit_ready": capture_result.get("status") == "READY",
        "counts_as_forward_day": capture_result.get("status") == "READY",
        "natural_sample_count": 1 if capture_result.get("status") == "READY" else 0,
        "selector_status": selected.get("selection_status"),
        "production_top10_codes": [_v4_global(_v4_scope, 'str')(row.get("code")) for row in selected.get("rows", [])[:_v4_global(_v4_scope, 'TOP_K')]],
        "selector": selected,
        "capture": _v4_global(_v4_scope, 'dict')(capture_result),
        **_v4_global(_v4_scope, 'SAFETY_FLAGS'),
    }
