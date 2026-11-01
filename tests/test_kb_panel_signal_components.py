from ops.kb_panel_signal_components import (
    bowl_components, double_gun_components, violence_k_components, yidong_above_60d_at,
)


def test_yidong_position_preconditions_and_history():
    closes = [100.0] * 66
    assert yidong_above_60d_at(closes, index=63, vol_ratio_5=2, pct_chg=1)["kb_yidong_above_60d_status"] == "INSUFFICIENT_HISTORY"
    assert yidong_above_60d_at(closes, index=64, vol_ratio_5=1.99, pct_chg=1)["kb_yidong_above_60d"] is None
    assert yidong_above_60d_at(closes, index=64, vol_ratio_5=2, pct_chg=0)["kb_yidong_above_60d_status"] == "NOT_APPLICABLE_SOURCE_PRECONDITION"
    assert yidong_above_60d_at(closes, index=64, vol_ratio_5=2, pct_chg=1)["kb_yidong_above_60d"] is True
    closes[64] = 94
    result = yidong_above_60d_at(closes, index=64, vol_ratio_5=2, pct_chg=1)
    assert result["kb_yidong_above_60d"] is False
    closes[65] = None
    assert yidong_above_60d_at(closes, index=64, vol_ratio_5=2, pct_chg=1) == result


def test_double_gun_uses_same_source_return_only_on_hit():
    assert double_gun_components(None, signal=None, available_bars=23, input_valid=False)["kb_double_gun_components_status"] == "INSUFFICIENT_HISTORY"
    absent = double_gun_components(None, signal=False, available_bars=24, input_valid=True)
    assert absent["kb_double_gun_vol1"] is None and absent["kb_double_gun_components_status"] == "NOT_APPLICABLE_NO_SIGNAL"
    source = {"is_double_gun": True, "double_gun_vol1": 2.3, "double_gun_vol2": 1.8, "double_gun_gap_days": 7}
    value = double_gun_components(source, signal=True, available_bars=100, input_valid=True)
    assert (value["kb_double_gun_vol1"], value["kb_double_gun_vol2"], value["kb_double_gun_gap_days"]) == (2.3, 1.8, 7)
    assert double_gun_components(None, signal=True, available_bars=100, input_valid=True)["kb_double_gun_components_status"] == "SOURCE_RESULT_UNBOUND_OR_CONFLICT"


def test_bowl_lines_keep_source_order_and_preheat_guard():
    assert bowl_components(11, 10, available_bars=119, close_prefix_valid=True)["kb_bowl_upper"] is None
    value = bowl_components(9, 10, available_bars=120, close_prefix_valid=True)
    assert (value["kb_bowl_upper"], value["kb_bowl_lower"]) == (9.0, 10.0)
    assert bowl_components(11, 10, available_bars=120, close_prefix_valid=False)["kb_bowl_components_status"] == "INVALID_LINE_OR_PREFIX"


def test_violence_fields_require_latest_source_event_and_never_default_to_zero():
    assert violence_k_components(None, signal=False, available_bars=20, input_valid=True)["kb_violence_k_components_status"] == "INSUFFICIENT_HISTORY"
    absent = violence_k_components([], signal=False, available_bars=21, input_valid=True)
    assert absent["kb_violence_k_body"] is None and absent["kb_violence_k_components_status"] == "NOT_APPLICABLE_NO_SIGNAL"
    event = [{"is_latest": False, "type": "大暴力", "body_pct": 9.4},
             {"is_latest": True, "type": "小暴力", "body_pct": 6.1}]
    value = violence_k_components(event, signal=True, available_bars=80, input_valid=True)
    assert (value["kb_violence_k_type"], value["kb_violence_k_body"]) == ("小暴力", 6.1)
    assert violence_k_components(event[:-1], signal=True, available_bars=80, input_valid=True)["kb_violence_k_components_status"] == "SOURCE_RESULT_UNBOUND_OR_CONFLICT"
