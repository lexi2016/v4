"""stage_center.live_collectors: hk_minute (review candidate, not deployment)."""
from __future__ import annotations
from typing import Any, Mapping
from ._namespace import read_global as _v4_global


def _collect_hk_minute_body(_v4_scope, /, plan, *, codes, python_path, shared_root, snapshot_root, process_runner, replay_provider):
    """Use ExHQ bars and the persisted exact-stage snapshot on fixed D-1 codes.

    ExHQ is the exact minute source, but it does not prove the V3
    ``LIVE_HKCONNECT_GAINER`` trigger. The snapshot was captured before the
    cutoff by the stage node and is read here without a provider fallback.
    The runner binds both sources to the same exact D-1 Top100.
    """
    if plan.stage_id == "STAGE_1545_1555":
        # Stage 8 is a historical RT_DATA replay contract.  A live ExHQ/Futu
        # scan is not an equivalent source and must never be used as a
        # fallback when the exact replay provider is unavailable.
        return _v4_global(_v4_scope, '_collect_hk_stage8_replay')(plan, codes=codes, replay_provider=replay_provider)
    root = _v4_global(_v4_scope, '_shared_scripts_root')(shared_root)
    module = _v4_global(_v4_scope, '_load_shared_module')(root, "scripts.live_acquisition.pytdx_exhq")
    scoped_runner = _v4_global(_v4_scope, '_scoped_process_runner')(root, process_runner)
    result = module.collect_pytdx_exhq_minute(
        python_path,
        plan.trade_date,
        plan.stage_id,
        _v4_global(_v4_scope, 'list')(codes),
        market="HK_CONNECT",
        process_runner=scoped_runner,
    )
    source = _v4_global(_v4_scope, '_to_source')(result, source_id="pytdx_exhq", route="shared_pytdx_exhq_hk_exact_d1_top100", requested=_v4_global(_v4_scope, 'len')(codes))
    if not source.rows:
        return source

    # The immutable pre-capture is the only source for the active trigger.
    hk_binding = plan.universe_bindings.get("HK_CONNECT")
    return _v4_global(_v4_scope, 'refresh_hk_active_lanes')(
        source,
        codes=codes,
        python_path=python_path,
        shared_root=root,
        snapshot_root=snapshot_root,
        process_runner=process_runner,
        trade_date=plan.trade_date,
        stage_id=plan.stage_id,
        cutoff_at=_v4_global(_v4_scope, 'STAGE_BY_ID')[plan.stage_id].cutoff,
        pool_artifact_sha256=getattr(hk_binding, "sha256", None),
    )


def _refresh_hk_active_lanes_body(_v4_scope, /, source, *, codes, python_path, shared_root, snapshot_root, process_runner, trade_date, stage_id, cutoff_at, pool_artifact_sha256):
    """Rebuild the V3 active trigger from the persisted exact-stage snapshot.

    This is the recovery path after raw publication has succeeded but a
    selection publication failed. It never calls a provider or changes the
    immutable raw rows. The date, stage, cutoff and D1 code SHA must match the
    immutable pre-capture.
    """
    requested = _v4_global(_v4_scope, 'tuple')(_v4_global(_v4_scope, 'dict').fromkeys(
        _v4_global(_v4_scope, '_canonical_hk_code')(code)
        for code in codes if _v4_global(_v4_scope, '_canonical_hk_code')(code)
    ))
    active: dict[str, Mapping[str, Any]] = {}
    probe_errors: tuple[str, ...] = ()
    if snapshot_root is None or not trade_date or not stage_id or not cutoff_at:
        probe_errors = ("HK_ACTIVE_SNAPSHOT_UNAVAILABLE",)
        evidence = (
            "active_snapshot_status=PERSISTED_EXACT_STAGE_UNAVAILABLE",
            "active_snapshot_temporal_cutoff_safe=false",
        )
    else:
        from stage_center.hk_stage8 import load_hk_active_snapshot

        loaded = load_hk_active_snapshot(
            snapshot_root,
            trade_date=trade_date,
            stage_id=stage_id,
            codes=requested,
            cutoff_at=cutoff_at,
            pool_artifact_sha256=pool_artifact_sha256,
        )
        evidence = tuple(loaded.get("source_evidence") or ())
        if loaded.get("status") != "READY":
            probe_errors = tuple(loaded.get("cannot_confirm") or ("HK_ACTIVE_SNAPSHOT_UNAVAILABLE",))
            evidence += (
                "active_snapshot_status=PERSISTED_EXACT_STAGE_UNAVAILABLE",
                "active_snapshot_temporal_cutoff_safe=false",
            )
        else:
            snapshot_rows = tuple(loaded.get("rows") or ())
            active_snapshot_rows = {str(row.get("code") or ""): row for row in snapshot_rows}
            if set(active_snapshot_rows) != set(requested) or len(active_snapshot_rows) != len(requested):
                probe_errors = ("HK_ACTIVE_SNAPSHOT_FULL_COVERAGE_MISSING",)
            else:
                for code, snapshot in active_snapshot_rows.items():
                    previous = snapshot.get("prev_close_price")
                    last = snapshot.get("last_price")
                    turnover = snapshot.get("turnover")
                    volume_ratio = snapshot.get("volume_ratio")
                    pct = (
                        (_v4_global(_v4_scope, 'float')(last) / _v4_global(_v4_scope, 'float')(previous) - 1.0) * 100.0
                        if previous not in (None, 0) and last is not None
                        else None
                    )
                    if (
                        pct is not None
                        and pct > 0
                        and turnover is not None
                        and turnover >= 20_000_000
                        and volume_ratio is not None
                        and volume_ratio >= 1
                    ):
                        active[code] = snapshot
                evidence += (
                    "active_snapshot_status=FUTU_HKCONNECT_FULL_SCAN",
                    "active_snapshot_scope=EXPLICIT_REQUESTED_CODES",
                    f"active_snapshot_trade_date={trade_date}",
                    f"active_snapshot_cutoff={cutoff_at}",
                    f"active_snapshot_sha256={loaded.get('active_snapshot_sha256')}",
                    f"active_snapshot_codes_sha256={loaded.get('active_snapshot_codes_sha256')}",
                    f"active_snapshot_pool_artifact_sha256={loaded.get('active_snapshot_pool_artifact_sha256')}",
                    "active_snapshot_temporal_cutoff_safe=true",
                    f"active_snapshot_active_rows={len(active)}",
                )
                if not active:
                    probe_errors = ("HK_ACTIVE_GAINER_NO_MATCH",)
    enriched: list[dict[str, Any]] = []
    for row in source.rows:
        code = _v4_global(_v4_scope, '_canonical_hk_code')(row.get("code"))
        merged = _v4_global(_v4_scope, 'dict')(row)
        # A lane is valid only when the persisted exact-stage snapshot matched
        # the code. Never carry a D-1/static lane into the live minute copy.
        merged["candidate_lanes"] = []
        for field in ("source_universe", "data_confidence", "active_gainer_pass", "active_snapshot_status"):
            merged.pop(field, None)
        merged.pop("volume_ratio", None)
        snapshot = active.get(code)
        if snapshot is not None:
            merged["candidate_lanes"] = ["LIVE_HKCONNECT_GAINER"]
            merged["source_universe"] = "HK_CONNECT_D1_TOP100"
            merged["data_confidence"] = "STAGE_RTDATA_CONFIRMED"
            merged["active_gainer_pass"] = True
            merged["volume_ratio"] = snapshot.get("volume_ratio")
            merged["active_snapshot_status"] = "FUTU_HKCONNECT_FULL_SCAN"
        enriched.append(merged)
    cannot = _v4_global(_v4_scope, 'tuple')(_v4_global(_v4_scope, 'dict').fromkeys((*source.cannot_confirm, *probe_errors)))
    if "HK_ACTIVE_SNAPSHOT_TEMPORAL_CUTOFF_UNSAFE" in probe_errors:
        return _v4_global(_v4_scope, 'replace')(
            source,
            status="CANNOT_CONFIRM",
            rows=(),
            cannot_confirm=cannot,
            source_evidence=_v4_global(_v4_scope, 'tuple')(_v4_global(_v4_scope, 'dict').fromkeys((*source.source_evidence, *evidence))),
        )
    return _v4_global(_v4_scope, 'replace')(source, rows=_v4_global(_v4_scope, 'tuple')(enriched), cannot_confirm=cannot, source_evidence=_v4_global(_v4_scope, 'tuple')(_v4_global(_v4_scope, 'dict').fromkeys((*source.source_evidence, *evidence))))
