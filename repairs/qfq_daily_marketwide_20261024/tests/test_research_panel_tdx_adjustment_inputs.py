import io
import json
from pathlib import Path
import struct
import zipfile

import pandas as pd
import pytest

from ops import research_panel_tdx_adjustment_inputs as tdx


def setup_source(tmp_path, monkeypatch, categories):
    parser = tmp_path / "parser.py"
    parser.write_text("# synthetic parser fixture\n")
    monkeypatch.setattr(tdx, "PARSER_SHA", tdx.sha(parser))
    policy = tmp_path / "policy.json"
    policy.write_text(json.dumps(dict(controller="fixture controller", policy_id="TDX_GBBQ_CATEGORY1_AFFINE_BJ_V1", category_policy=categories)))
    (tmp_path / "qfq_tdx_official_source.json").write_text(json.dumps(dict(source_url=tdx.OFFICIAL_URL,
        parser=dict(path=str(parser), sha256=tdx.sha(parser)), category_policy_receipt=dict(path=str(policy), sha256=tdx.sha(policy)))))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("gbbq", struct.pack("<I", 1) + bytes(29))
    return buffer.getvalue()


def parser_for(category):
    class Parser:
        def get_df(self, _path):
            return pd.DataFrame([dict(market=2, code="830779", datetime=20260526, category=category,
                                      hongli_panqianliutong=3.8, peigujia_qianzongguben=0.,
                                      songgu_qianzongguben=3., peigu_houzongguben=0.)])
    return Parser


def test_official_category1_has_explicit_tdx_convention_not_futu_fitted(tmp_path, monkeypatch):
    payload = setup_source(tmp_path, monkeypatch, {"1": "PRICE_ACTION_PER10_CASH_RIGHTS_BONUS_AFFINE"})
    result = tdx.build_fallback(tmp_path, {"830779.BJ": dict(history_start_date=20200101)}, 20261023,
                                fetch=lambda: payload, parser_factory=parser_for(1))
    item = result["symbols"]["830779.BJ"]
    assert item["event_coverage_complete"] is True
    assert item["events"] == [dict(ex_date=20260526, a=1 / 1.3, b=-.38 / 1.3, volume_a=1.3)]
    assert "NOT_FUTU_EQUIVALENT" in item["price_convention"]


def test_unknown_category_preserves_original_rows_and_blocks_that_symbol(tmp_path, monkeypatch):
    payload = setup_source(tmp_path, monkeypatch, {"1": "PRICE_ACTION_PER10_CASH_RIGHTS_BONUS_AFFINE"})
    result = tdx.build_fallback(tmp_path, {"830779.BJ": dict(history_start_date=20200101)}, 20261023,
                                fetch=lambda: payload, parser_factory=parser_for(14))
    item = result["symbols"]["830779.BJ"]
    assert item["event_coverage_complete"] is False
    assert item["unsupported_categories"] == [14]
    original = json.loads(Path(item["source_files"][-1]["path"]).read_text())
    assert original["rows"][0]["category"] == 14
    assert result["gaps"][0]["ts_code"] == "830779.BJ"


def test_official_archive_trailing_bytes_fail_before_parser(tmp_path, monkeypatch):
    setup_source(tmp_path, monkeypatch, {"1": "PRICE_ACTION_PER10_CASH_RIGHTS_BONUS_AFFINE"})
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("gbbq", struct.pack("<I", 1) + bytes(28))
    with pytest.raises(tdx.QfqGateError, match="RECORD_COUNT_OR_TRAILING_BYTES"):
        tdx.build_fallback(tmp_path, {"830779.BJ": dict(history_start_date=20200101)}, 20261023,
                           fetch=lambda: buffer.getvalue(), parser_factory=parser_for(1))
