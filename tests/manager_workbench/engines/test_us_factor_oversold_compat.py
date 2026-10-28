from copy import deepcopy

from test_oversold_inputs import batch, ctx, rec
from v4.manager_workbench.engines.common import US_FACTOR_RULES_VERSION
from v4.manager_workbench.engines.oversold import PRICE40_RULES_VERSION, run_oversold


def run_with_version(record, rules_version):
    context = ctx()
    context["rules_version"] = rules_version
    source = batch([deepcopy(record)])
    source["context"] = context
    return run_oversold(context, source)["rows"][0]


def test_new_factor_rules_keep_frozen_forty_percent_and_and_behavior():
    cases = []
    for close, volume, expected_price_pass, expected_volume_pass in (
        ("60", "150", True, True),
        ("60.000001", "150", False, True),
        ("60", "149.999999", True, False),
        ("60.000001", "149.999999", False, False),
    ):
        record = rec()
        record["previous_bar"].update(close=close, volume=volume)
        cases.append((record, expected_price_pass, expected_volume_pass))
    missing = rec()
    missing["high_history60"].pop()
    cases.append((missing, None, None))

    for record, expected_price_pass, expected_volume_pass in cases:
        old = run_with_version(record, PRICE40_RULES_VERSION)
        new = run_with_version(record, US_FACTOR_RULES_VERSION)
        assert new["decision"] == old["decision"]
        assert {k: v for k, v in new["metrics"].items() if k != "oversold_rules_version"} == {
            k: v for k, v in old["metrics"].items() if k != "oversold_rules_version"}
        if expected_price_pass is None:
            assert new["metrics"]["price_pass"] is None
            assert new["metrics"]["volume_pass"] is None
        else:
            assert new["metrics"]["price_pass"] is expected_price_pass
            assert new["metrics"]["volume_pass"] is expected_volume_pass
