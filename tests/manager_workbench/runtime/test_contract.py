import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from v4.manager_workbench.contracts import (
    SCHEMA_VERSION, JobRecord, PlanSnapshot, RunContext, schema, seal_snapshot,
    validate_date, product_digest,
)

SAMPLES = Path(__file__).resolve().parents[1] / "contract_samples"


def test_public_schema_and_samples():
    assert json.loads((SAMPLES / "mwb_v1.schema.json").read_text()) == schema()
    for name in ("normal", "empty", "partial", "unknown_counts"):
        data = json.loads((SAMPLES / f"{name}.json").read_text())
        snap = PlanSnapshot.model_validate(data)
        assert snap.schema_version == SCHEMA_VERSION
        assert snap.product_sha256 == product_digest(data)
    job = json.loads((SAMPLES / "failed_job.json").read_text())
    assert JobRecord.model_validate(job).state.value == "FAILED"
    old = json.loads((SAMPLES / "legacy.json").read_text())
    assert old["data"]["verification"] == "CANNOT_CONFIRM"


def test_forged_safety_and_hash_and_run_rejected():
    obj = json.loads((SAMPLES / "normal.json").read_text())
    for key, val in (("production_allowed", True), ("orders_sent", True)):
        bad = copy.deepcopy(obj)
        bad[key] = val
        with pytest.raises(ValidationError):
            seal_snapshot(bad)
    bad = copy.deepcopy(obj)
    bad["product_sha256"] = "0" * 64
    with pytest.raises(ValidationError, match="PRODUCT_SHA_MISMATCH"):
        PlanSnapshot.model_validate(bad)
    bad = copy.deepcopy(obj)
    bad["lanes"][0]["run_id"] = "different"
    with pytest.raises(ValidationError, match="LANE_RUN_MISMATCH"):
        seal_snapshot(bad)


def test_dates_and_cutoffs_are_strict():
    for v in ("20260230", "2026-01-01", "2026011", "２０２６０１０１", "20261301"):
        with pytest.raises(ValueError):
            validate_date(v)
    obj = json.loads((SAMPLES / "normal.json").read_text())["context"]
    obj["cutoff"] = "2026-10-13T09:25:00"
    with pytest.raises(ValidationError, match="TIME_TZ_REQUIRED"):
        RunContext.model_validate(obj)


def test_seal_normalizes_optional_defaults_before_hash():
    obj = json.loads((SAMPLES / "normal.json").read_text())
    obj.pop("changes")
    obj["stocks"][0].pop("risks")
    sealed = seal_snapshot(obj)
    assert sealed.changes == {} and sealed.stocks[0].risks == []
    assert PlanSnapshot.model_validate(sealed.model_dump(mode="json")) == sealed


def test_symbol_rejects_unicode_digits_and_schema_matches():
    from v4.manager_workbench.contracts import StockDecision
    with pytest.raises(ValidationError):
        StockDecision(symbol="HK.００００１", decision="UNASSESSED")
    assert StockDecision.model_json_schema()["properties"]["symbol"]["pattern"] == r"^HK\.[0-9]{5}$"
