"""stage_center.live_collectors: hk_minute (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _collect_hk_minute_body(_v4_scope, /, plan, *, codes, python_path, shared_root, process_runner, replay_provider):
    """Use ExHQ bars and the original Futu predicate on the fixed D-1 codes.

    ExHQ is the exact minute source, but it does not prove the V3
    ``LIVE_HKCONNECT_GAINER`` trigger.  The trigger came from a separate Futu
    full-market snapshot in the old V3 implementation. The V4 runner binds
    both probes to the same exact D-1 Top100; it never enumerates a plate.  The Futu result is copied only into the
    selection-only row fields; the immutable raw acquisition rows remain the
    ExHQ rows.
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

    # This is intentionally a second, read-only module load.  The shared
    # auction module owns the already-reviewed Futu snapshot bridge and keeps
    # its child cwd/PYTHONPATH scoped by the same runner wrapper as ExHQ.
    return _v4_global(_v4_scope, 'refresh_hk_active_lanes')(
        source,
        codes=codes,
        python_path=python_path,
        shared_root=root,
        process_runner=process_runner,
        trade_date=plan.trade_date,
        stage_id=plan.stage_id,
        cutoff_at=_v4_global(_v4_scope, 'STAGE_BY_ID')[plan.stage_id].cutoff,
    )


def _refresh_hk_active_lanes_body(_v4_scope, /, source, *, codes, python_path, shared_root, process_runner, trade_date, stage_id, cutoff_at):
    """Re-probe only the V3 active trigger for an existing raw HK source.

    This is the recovery path after raw publication has succeeded but a
    selection publication failed.  It never calls ExHQ and never changes the
    immutable raw rows; it only rebuilds the selection-only lane metadata from
    the same explicit code-bounded Futu snapshot and carries its evidence.
    """
    root = _v4_global(_v4_scope, '_shared_scripts_root')(shared_root)
    scoped_runner = _v4_global(_v4_scope, '_scoped_process_runner')(root, process_runner)
    active, evidence, probe_errors = _v4_global(_v4_scope, '_futu_hkconnect_active_snapshot')(
        root,
        codes=codes,
        python_path=python_path,
        process_runner=scoped_runner,
        trade_date=trade_date,
        cutoff_at=cutoff_at,
    )
    if "HK_ACTIVE_SNAPSHOT_TEMPORAL_CUTOFF_UNSAFE" in probe_errors and trade_date and cutoff_at:
        return _v4_global(_v4_scope, 'replace')(
            source,
            status="CANNOT_CONFIRM",
            rows=(),
            cannot_confirm=_v4_global(_v4_scope, 'tuple')(_v4_global(_v4_scope, 'dict').fromkeys((*source.cannot_confirm, *probe_errors))),
            source_evidence=_v4_global(_v4_scope, 'tuple')(_v4_global(_v4_scope, 'dict').fromkeys((*source.source_evidence, *evidence))),
        )
    enriched: list[dict[str, Any]] = []
    for row in source.rows:
        code = _v4_global(_v4_scope, '_canonical_hk_code')(row.get("code"))
        merged = _v4_global(_v4_scope, 'dict')(row)
        # A lane is valid only when this exact full-scan probe matched the
        # code.  Never carry a D-1/static lane into the live minute copy.
        merged["candidate_lanes"] = []
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
    return _v4_global(_v4_scope, 'replace')(source, rows=_v4_global(_v4_scope, 'tuple')(enriched), cannot_confirm=cannot, source_evidence=_v4_global(_v4_scope, 'tuple')(_v4_global(_v4_scope, 'dict').fromkeys((*source.source_evidence, *evidence))))
