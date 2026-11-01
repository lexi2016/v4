"""stage_center.runner: configuration (review candidate, not deployment)."""
from __future__ import annotations
from pathlib import Path
from stage_center.runner import RunnerConfig


def _build_production_config_body(*, candidate_acquisition_root, raw_root, selection_root, receipt_root, v3_formal_root, v3_research_root, v4_research_data_root, v4_morning_news_root, hk_d1_root, preselection_source_root, hk_second_filter_root, hk_full_universe_root, a_auction_root, hk_auction_root, hk_stage_replay_root, a_research_panel_receipt_root, shared_data_root, python_path):
    """Construct a production-shaped config without starting any collector.

    ``v4_research_data_root`` is the explicit V4-owned hourly archive root for
    the six research stages.  ``v3_research_root`` is accepted for older
    serialized configs but is not read by the stage context adapter.
    ``v4_morning_news_root`` is the separate exact-date shared producer store.
    ``shared_data_root`` and ``python_path`` are explicit bridge inputs; the
    runner uses them to construct the packaged read-only collectors at tick
    time.
    """
    return RunnerConfig(
        candidate_acquisition_root=Path(candidate_acquisition_root),
        raw_root=Path(raw_root),
        selection_root=Path(selection_root),
        receipt_root=Path(receipt_root),
        v3_formal_root=Path(v3_formal_root) if v3_formal_root is not None else None,
        v3_research_root=Path(v3_research_root) if v3_research_root is not None else None,
        v4_research_data_root=(Path(v4_research_data_root) if v4_research_data_root is not None else None),
        v4_morning_news_root=(Path(v4_morning_news_root) if v4_morning_news_root is not None else None),
        hk_d1_root=Path(hk_d1_root) if hk_d1_root is not None else None,
        preselection_source_root=(Path(preselection_source_root) if preselection_source_root is not None else None),
        hk_second_filter_root=Path(hk_second_filter_root) if hk_second_filter_root is not None else None,
        hk_full_universe_root=Path(hk_full_universe_root) if hk_full_universe_root is not None else None,
        a_auction_root=Path(a_auction_root) if a_auction_root is not None else None,
        hk_auction_root=Path(hk_auction_root) if hk_auction_root is not None else None,
        hk_stage_replay_root=Path(hk_stage_replay_root) if hk_stage_replay_root is not None else None,
        a_research_panel_receipt_root=Path(a_research_panel_receipt_root) if a_research_panel_receipt_root is not None else None,
        shared_data_root=Path(shared_data_root) if shared_data_root is not None else None,
        python_path=Path(python_path) if python_path is not None else None,
    )
