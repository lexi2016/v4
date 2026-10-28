"""stage_center.live_collectors: a_minute (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _collect_a_share_minute_body(_v4_scope, /, plan, *, codes, python_path, shared_root, process_runner):
    """Use shared_data's Futu/PyTDX route for an explicit A code list."""
    root = _v4_global(_v4_scope, '_shared_scripts_root')(shared_root)
    module = _v4_global(_v4_scope, '_load_shared_module')(root, "scripts.live_acquisition.futu_bridge")
    scoped_runner = _v4_global(_v4_scope, '_scoped_process_runner')(root, process_runner)
    result = module.collect_futu_minute(
        python_path,
        plan.trade_date,
        plan.stage_id,
        _v4_global(_v4_scope, 'list')(codes),
        market="A_SHARE",
        process_runner=scoped_runner,
    )
    return _v4_global(_v4_scope, '_to_source')(result, source_id="futu", route="shared_futu_a_share_minute", requested=_v4_global(_v4_scope, 'len')(codes))


def _collect_a_share_hq_minute_body(_v4_scope, /, plan, *, codes, python_path, shared_root, process_runner):
    """Use the verified PyTDX HQ path for the full A-share universe.

    The shared bridge's HQ probe is the V3 route for large universes and
    preserves the exact cutoff/amount aggregation.  Futu's 100-code
    subscription ceiling is therefore never used for this production path.
    """
    root = _v4_global(_v4_scope, '_shared_scripts_root')(shared_root)
    module = _v4_global(_v4_scope, '_load_shared_module')(root, "scripts.live_acquisition.pytdx_hq")
    scoped_runner = _v4_global(_v4_scope, '_scoped_process_runner')(root, process_runner)
    tdx_codes = [_v4_global(_v4_scope, '_tdx_code')(code) for code in codes]
    result = module.collect_pytdx_hq_minute(
        python_path,
        plan.trade_date,
        plan.stage_id,
        tdx_codes,
        market="A_SHARE",
        process_runner=scoped_runner,
    )
    return _v4_global(_v4_scope, '_to_source')(result, source_id="pytdx_hq", route="shared_pytdx_hq_a_share_exact_cutoff", requested=_v4_global(_v4_scope, 'len')(codes))
