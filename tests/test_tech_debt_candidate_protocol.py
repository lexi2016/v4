"""Exercise the retained runtime scope protocol with the reviewed fixtures.

Run with PYTHONPATH pointing at the isolated candidate app. These two cases
replace only the source tests' newer pool_store_class calling convention;
the candidate's actual assembler and its response are not patched.
"""
import importlib.util
import inspect
from pathlib import Path

import pytest

from domains import preselection
from domains._preselection_parts.pool_assembly import _preselection_body


def _fixtures():
    spec = importlib.util.spec_from_file_location(
        "reviewed_entity_fixtures", Path(__file__).with_name("test_a_share_entity_filter.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("all_invalid", [False, True])
def test_retained_runtime_pool_protocol(all_invalid):
    if "_v4_scope" not in inspect.signature(_preselection_body).parameters:
        pytest.skip("only applies to the isolated inherited runtime calling convention")
    fixture = _fixtures()
    rows = [fixture._row("261029", 1, "申昊科技")]
    if not all_invalid:
        rows += [
            fixture._row("600519", 2, "贵州茅台"),
            fixture._row("00700", 1, "腾讯控股", pool_id="hkconnect_d1_top100", market="HK"),
        ]
    pools = [fixture._pool(rows)]

    class Store:
        root = Path("/nonexistent-v4-test-root")

    class PoolStore:
        def __init__(self, root):
            self.root = root

        def read_all(self, date):
            return pools

    scope = {**vars(preselection), "PreselectionPoolStore": PoolStore}
    response = _preselection_body(scope, Store(), "20261030", 300, offset=0, allow_legacy_flat=False)
    assert response["ok"] is True
    assert response["quarantined_row_count"] == 1
    assert response["filter_rule_version"] == fixture.FILTER_RULE_VERSION
    assert response["original_row_count"] == len(rows)
    if all_invalid:
        assert response["data_status"] == "ALL_ROWS_QUARANTINED"
        assert response["rows"] == []
        assert response["effective_row_count"] == 0
        assert "ALL_ROWS_QUARANTINED_AS_INVALID_A_SHARE" in response["blocking_reasons"]
    else:
        assert response["data_status"] == "PARTIAL_WITH_ROWS"
        assert [row["code"] for row in response["rows"]] == ["600519", "00700"]
        assert response["effective_row_count"] == 2
        assert response["quarantined"][0]["code"] == "261029"
