"""Summary counts must preserve the existing rebound screen's known/unknown state."""
from __future__ import annotations

from typing import Any

from v4.manager_research.workspace_plan import read_rebound_screen
from v4.manager_research.workspace_projection import build_workspace


TARGET_DATE = '20260924'
_MISSING = object()


def screen_result(*, strict_count: int, near_count: int, status: str = 'READY', ready: bool = True,
                  input_candidate_count: int | None = None, history_complete_count: int | None = None,
                  history_pending_count: int = 0) -> dict[str, Any]:
    strict = [{'code': f'HK.{1000 + i:05d}', 'classification': 'STRICT_REBOUND'}
              for i in range(strict_count)]
    near = [{'code': f'HK.{2000 + i:05d}', 'classification': 'NEAR_REBOUND'}
            for i in range(near_count)]
    cards = [*strict, *near]
    pending = [{'code': f'HK.{3000 + i:05d}', 'history_status': 'PARTIAL_UNKNOWN'}
               for i in range(history_pending_count)]
    input_candidate_count = input_candidate_count if input_candidate_count is not None else len(cards) + history_pending_count
    history_complete_count = history_complete_count if history_complete_count is not None else len(cards)
    return {
        'status': status,
        'main_screen_ready': ready,
        'strict': strict,
        'near': near,
        'cards': cards,
        'pending': pending,
        'gaps': [f"SCREEN_HISTORY_OR_VOLUME_INCOMPLETE:{row['code']}" for row in pending],
        'coverage': {
            'input_candidate_count': input_candidate_count,
            'history_complete_count': history_complete_count,
            'history_pending_count': history_pending_count,
            'strict_count': len(strict),
            'near_candidate_count': len(near),
            'near_count': len(near),
            'selected_count': len(cards),
        },
    }


def project(screen: Any = _MISSING) -> dict[str, Any]:
    inputs: dict[str, Any] = {}
    if screen is not _MISSING:
        inputs['market_screen'] = screen
    return build_workspace(
        TARGET_DATE,
        catalyst={'status': 'NOT_MATERIALIZED', 'target_trade_date': TARGET_DATE, 'cards': []},
        **inputs,
    )


def test_ready_nonempty_screen_summary_matches_existing_screen_counts() -> None:
    screen = screen_result(strict_count=21, near_count=260, status='READY_WITH_GAPS',
                           input_candidate_count=687, history_complete_count=664,
                           history_pending_count=23)

    result = project(screen)

    assert result['summary']['market_screen_strict_count'] == screen['coverage']['strict_count'] == len(screen['strict'])
    assert result['summary']['market_screen_near_count'] == screen['coverage']['near_count'] == len(screen['near']) == 260
    assert result['summary']['market_screen_card_count'] == len(screen['cards']) == 281


def test_ready_empty_screen_is_known_zero() -> None:
    screen = screen_result(strict_count=0, near_count=0, status='READY')

    result = project(screen)

    assert result['summary']['market_screen_strict_count'] == 0
    assert result['summary']['market_screen_near_count'] == 0
    assert result['summary']['market_screen_card_count'] == 0


def test_missing_screen_is_unknown_in_summary() -> None:
    result = project()

    assert result['summary']['market_screen_strict_count'] is None
    assert result['summary']['market_screen_near_count'] is None
    assert result['summary']['market_screen_card_count'] is None
    assert 'market_screen' not in result


def test_source_unverified_screen_preserves_status_and_unknown_counts() -> None:
    # Exercise the real reader's fail-closed output for an unbound source root.
    screen = read_rebound_screen(None, {
        'market_session': '20260923',
        'plan_trade_date': TARGET_DATE,
    })
    assert screen['status'] == 'CANNOT_CONFIRM'
    assert screen['main_screen_ready'] is False
    assert screen['coverage']['counts_known'] is False
    assert screen['coverage']['strict_count'] is None
    assert screen['coverage']['near_count'] is None
    assert screen['cards'] == []

    result = project(screen)

    assert result['market_screen']['status'] == 'CANNOT_CONFIRM'
    assert result['summary']['market_screen_strict_count'] is None
    assert result['summary']['market_screen_near_count'] is None
    assert result['summary']['market_screen_card_count'] is None


def test_missing_coverage_count_is_unknown_not_zero() -> None:
    screen = screen_result(strict_count=1, near_count=1)
    del screen['coverage']['near_count']

    result = project(screen)

    assert result['summary']['market_screen_strict_count'] == 1
    assert result['summary']['market_screen_near_count'] is None
    assert result['summary']['market_screen_card_count'] == 2
