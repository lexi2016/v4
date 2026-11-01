import pytest

from ops.kb_panel_rebuild_brick import BRICK_SERIES_ID, brick_fields_at, rebuild_at


def test_rebuild_warmup_boundary_maturity_and_no_future():
    closes = [100 + i * 0.001 for i in range(125)]
    vols = [100] * 125
    pct = [0] * 125
    vols[115], pct[115] = 1000, 6
    before = rebuild_at(closes, vols, pct, index=122)
    assert before["kb_rebuild"] is None
    assert (before["kb_rebuild_reason"], before["kb_rebuild_required_bars"], before["kb_rebuild_available_bars"]) == ("INSUFFICIENT_HISTORY", 124, 123)
    mature = rebuild_at(closes, vols, pct, index=123)
    assert mature["kb_rebuild"] is True and mature["kb_rebuild_reason"] is None
    assert mature["components"]["up_volume_day_index"] == 115
    closes[-1], vols[-1], pct[-1] = 9999, 0, None
    assert rebuild_at(closes, vols, pct, index=123) == mature
    assert rebuild_at(closes, vols, pct, index=124)["kb_rebuild_reason"] == "INVALID_VOLUME_IN_REQUIRED_WINDOW"


def test_rebuild_missing_input_is_not_history_shortage():
    closes, vols, pct = [100.0] * 124, [10.0] * 124, [0.0] * 124
    closes[20] = None
    value = rebuild_at(closes, vols, pct, index=123)
    assert value["kb_rebuild"] is None
    assert value["kb_rebuild_reason"] == "INVALID_CLOSE_IN_REQUIRED_WINDOW"
    closes[20] = 100.0
    assert rebuild_at(closes, vols, pct, index=123)["kb_rebuild"] is False
    with pytest.raises(ValueError, match="INPUT_LENGTH_MISMATCH"):
        rebuild_at(closes, vols[:-1], pct, index=123)


def brick(values, index, **overrides):
    options = {"prefix_valid": True, "prefix_seed_bound": True, "series_id": BRICK_SERIES_ID}
    options.update(overrides)
    return brick_fields_at(values, index=index, **options)


def test_brick_color_count_becomes_known_only_after_real_reversal():
    values = [None] * 11 + [5, 6, 6, 5, 5]
    assert brick(values, 11)["kb_brick_trend_reason"] == "INSUFFICIENT_HISTORY"
    warm = brick(values, 13)
    assert warm["kb_brick_trend"] == "RED"
    assert warm["kb_brick_count"] is None
    assert warm["kb_brick_observed_run_lower_bound"] == 2
    assert warm["kb_brick_count_reason"] == "BRICK_RUN_ORIGIN_IN_WARMUP"
    turned = brick(values, 14)
    assert (turned["kb_brick_trend"], turned["kb_brick_count"]) == ("GREEN", 1)
    assert turned["kb_brick_action_desc"] is None
    assert turned["kb_brick_action_desc_reason"] == "PREVIOUS_RED_RUN_ORIGIN_IN_WARMUP"
    next_day = brick(values, 15)
    assert (next_day["kb_brick_trend"], next_day["kb_brick_count"]) == ("RED", 1)
    assert next_day["kb_brick_action_desc"] == "红砖上涨中（1块），继续持有"


def test_flip_description_uses_prior_red_run_not_new_green_count():
    values = [None] * 11 + [5, 6, 6, 5, 5, 5, 6, 7, 8, 9, 8]
    result = brick(values, len(values) - 1)
    assert (result["kb_brick_trend"], result["kb_brick_count"]) == ("GREEN", 1)
    assert result["kb_brick_action_desc"] == "红砖翻绿！立刻止损（连续红砖6块后翻绿）"
    assert result["kb_brick_action_desc_reason"] is None


def test_brick_source_prefix_and_invalid_inputs_fail_closed():
    values = [None] * 11 + [5, 6, 5]
    assert brick(values, 13, prefix_seed_bound=False)["kb_brick_trend_reason"] == "SOURCE_PREFIX_OR_BRICK_KERNEL_UNBOUND"
    assert brick(values, 13, series_id="other")["kb_brick_trend"] is None
    assert brick(values, 13, prefix_valid=False)["kb_brick_count_reason"] == "INVALID_HLC_INPUT_IN_REQUIRED_PREFIX"
    values[12] = float("nan")
    assert brick(values, 13)["kb_brick_trend_reason"] == "INVALID_BRICK_VALUE_IN_REQUIRED_PREFIX"
