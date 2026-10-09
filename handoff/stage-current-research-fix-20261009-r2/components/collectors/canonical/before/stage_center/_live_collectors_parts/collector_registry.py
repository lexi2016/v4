"""stage_center.live_collectors: collector_registry (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _production_collectors_body(_v4_scope, /, plan, *, python_path, shared_root, a_auction_root, hk_auction_root, hk_stage_replay_root):
    """Return the packaged read-only collector bridge for one stage.

    09:25 remains intentionally fail-closed until an exact auction provider
    yields rows; no minute collector is substituted for the auction contract.
    """
    if plan.stage_id == "STAGE_0925":
        return {
            "A_SHARE": lambda stage_plan, _market: _v4_global(_v4_scope, 'collect_a_share_auction')(
                stage_plan,
                codes=stage_plan.codes_for("A_SHARE"),
                python_path=python_path,
                shared_root=shared_root,
                auction_root=a_auction_root,
            ),
            "HK_CONNECT": lambda stage_plan, _market: _v4_global(_v4_scope, 'collect_hk_auction')(
                stage_plan,
                codes=stage_plan.codes_for("HK_CONNECT"),
                python_path=python_path,
                shared_root=shared_root,
                auction_root=hk_auction_root,
            ),
        }
    if plan.stage_id == "STAGE_1545_1555":
        # The final HK window has no A-share lane in the frozen contract.
        # Returning an A collector here makes the runner reject the stage
        # before it can publish the HK observation.
        replay_provider = None
        if hk_stage_replay_root is not None:
            from infrastructure.hkconnect_stage_replay_provider import HkConnectStageReplayProvider

            # The root is explicit and date/stage resolution remains inside
            # the provider.  No environment variable or cwd-based fallback is
            # allowed for the production Stage8 route.
            replay_provider = HkConnectStageReplayProvider(
                data_root=_v4_global(_v4_scope, 'Path')(hk_stage_replay_root).expanduser().resolve()
            )
        return {
            "HK_CONNECT": lambda stage_plan, _market: _v4_global(_v4_scope, 'collect_hk_minute')(
                stage_plan,
                codes=stage_plan.codes_for("HK_CONNECT"),
                python_path=python_path,
                shared_root=shared_root,
                replay_provider=replay_provider,
            ),
        }
    return {
        "A_SHARE": lambda stage_plan, _market: _v4_global(_v4_scope, 'collect_a_share_hq_minute')(
            stage_plan,
            codes=stage_plan.codes_for("A_SHARE"),
            python_path=python_path,
            shared_root=shared_root,
        ),
        "HK_CONNECT": lambda stage_plan, _market: _v4_global(_v4_scope, 'collect_hk_minute')(
            stage_plan,
            codes=stage_plan.codes_for("HK_CONNECT"),
            python_path=python_path,
            shared_root=shared_root,
        ),
    }
