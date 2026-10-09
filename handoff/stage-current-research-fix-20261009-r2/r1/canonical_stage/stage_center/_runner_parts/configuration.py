"""stage_center.runner: configuration (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _build_production_config_body(_v4_scope, /, *, candidate_acquisition_root, raw_root, selection_root, receipt_root, v3_formal_root, v3_research_root, v4_research_data_root, v4_morning_news_root, hk_d1_root, preselection_source_root, hk_second_filter_root, hk_full_universe_root, a_auction_root, hk_auction_root, hk_stage_replay_root, a_research_panel_receipt_root, shared_data_root, python_path):
    """Construct a production-shaped config without starting any collector.

    ``v4_research_data_root`` is the explicit V4-owned hourly archive root for
    the six research stages.  ``v3_research_root`` is accepted for older
    serialized configs but is not read by the stage context adapter.
    ``v4_morning_news_root`` is the separate exact-date shared producer store.
    ``shared_data_root`` and ``python_path`` are explicit bridge inputs; the
    runner uses them to construct the packaged read-only collectors at tick
    time.
    """
    return _v4_global(_v4_scope, 'RunnerConfig')(
        candidate_acquisition_root=_v4_global(_v4_scope, 'Path')(candidate_acquisition_root),
        raw_root=_v4_global(_v4_scope, 'Path')(raw_root),
        selection_root=_v4_global(_v4_scope, 'Path')(selection_root),
        receipt_root=_v4_global(_v4_scope, 'Path')(receipt_root),
        v3_formal_root=_v4_global(_v4_scope, 'Path')(v3_formal_root) if v3_formal_root is not None else None,
        v3_research_root=_v4_global(_v4_scope, 'Path')(v3_research_root) if v3_research_root is not None else None,
        v4_research_data_root=(_v4_global(_v4_scope, 'Path')(v4_research_data_root) if v4_research_data_root is not None else None),
        v4_morning_news_root=(_v4_global(_v4_scope, 'Path')(v4_morning_news_root) if v4_morning_news_root is not None else None),
        hk_d1_root=_v4_global(_v4_scope, 'Path')(hk_d1_root) if hk_d1_root is not None else None,
        preselection_source_root=(_v4_global(_v4_scope, 'Path')(preselection_source_root) if preselection_source_root is not None else None),
        hk_second_filter_root=_v4_global(_v4_scope, 'Path')(hk_second_filter_root) if hk_second_filter_root is not None else None,
        hk_full_universe_root=_v4_global(_v4_scope, 'Path')(hk_full_universe_root) if hk_full_universe_root is not None else None,
        a_auction_root=_v4_global(_v4_scope, 'Path')(a_auction_root) if a_auction_root is not None else None,
        hk_auction_root=_v4_global(_v4_scope, 'Path')(hk_auction_root) if hk_auction_root is not None else None,
        hk_stage_replay_root=_v4_global(_v4_scope, 'Path')(hk_stage_replay_root) if hk_stage_replay_root is not None else None,
        a_research_panel_receipt_root=_v4_global(_v4_scope, 'Path')(a_research_panel_receipt_root) if a_research_panel_receipt_root is not None else None,
        shared_data_root=_v4_global(_v4_scope, 'Path')(shared_data_root) if shared_data_root is not None else None,
        python_path=_v4_global(_v4_scope, 'Path')(python_path) if python_path is not None else None,
    )
