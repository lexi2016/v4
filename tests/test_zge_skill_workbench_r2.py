import hashlib
import json
from pathlib import Path
import sys
import types
from unittest.mock import patch

import pytest

from infrastructure.research_workbench_skill_r2 import GROUPS, SkillR2Workbench


FLAGS = dict(RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)
GEN = "a" * 64
INPUT = "b" * 64
SELECTOR = "c" * 64
RULE = "d" * 64
CODE = "002959.SZ"


def ref(path):
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def put(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False) + "\n", encoding="utf-8")
    return ref(path)


@pytest.fixture
def fixture(tmp_path):
    source = put(tmp_path / "source.json", {
        "target_date": "20261028", "selector_sha256": SELECTOR,
        "formula": {"authority": {"generation_id": GEN, "source_sha256": INPUT}},
    })
    branches = {g: {"seed_state": "FALSE"} for g in GROUPS}
    branches["skill_r2_b1"]["seed_state"] = "TRUE"
    branches["skill_r2_sb1"]["seed_state"] = "UNKNOWN"
    row = dict(ts_code=CODE, name="样本", name_source_date="20261027", asof="20261028",
               ruleset_id="ZGE_SKILL_DAILY_CANDIDATES_R2", ruleset_sha256=RULE, source_generation=GEN,
               branches=branches, raw_hit_group_ids=["skill_r2_b1"], pending_group_ids=["skill_r2_b1"],
               risk_review_group_ids=["skill_r2_b1"], record_status="RISK_REVIEW")
    candidate = tmp_path / "d28_candidate_union_R2.jsonl"
    candidate.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
    candidate_ref = {**ref(candidate), "rows": 1}
    receipt = put(tmp_path / "D28_RUN_RECEIPT_R2.json", {
        "schema": "zge_skill_d28_screen_run/1", "asof": "20261028",
        "ruleset_id": "ZGE_SKILL_DAILY_CANDIDATES_R2", "enabled_groups": list(GROUPS),
        "counts": {"accepted_target_rows": 5538, "quarantine_retained_separately": 270, "candidate_union": 1},
        "source": {"receipt_path": source["path"], "receipt_sha256_actual": source["sha256"],
                   "generation_id": GEN, "selector_sha256_declared": SELECTOR},
        "ruleset": {"sha256": RULE}, "artifacts": {candidate.name: candidate_ref}, **FLAGS,
    })
    chart_root = tmp_path / "charts"
    chart_root.mkdir()
    for name, data in [("one.png", b"png bytes"), ("one.html", b"<html>original</html>"),
                       ("one.projection.json.gz", b"gzip bytes")]:
        (chart_root / name).write_bytes(data)
    sample = {"status": "READY", "symbol": CODE, "data_date": "20261028", "last_date": "20261028",
              "rows": 120, "values_per_row": 51, "drawings_per_row": 22,
              "PNG": ref(chart_root / "one.png"), "html": ref(chart_root / "one.html"),
              "projection": ref(chart_root / "one.projection.json.gz"), **FLAGS}
    chart_ref = put(chart_root / "CHART_MANIFEST.json", {
        "schema": "ZGE_SKILL_D28_ORIGINAL_CHARTS_V1", "source_date": "20261028", "source_generation": GEN,
        "source_input_sha256": INPUT, "source_selector_sha256": SELECTOR,
        "ruleset_id": "ZGE_SKILL_DAILY_CANDIDATES_R2", "rule_config_sha256": RULE,
        "lineage": {"screen_receipt": receipt, "candidate_artifact": candidate_ref},
        "samples": {CODE: sample}, "errors": {}, **FLAGS,
    })
    review_path = tmp_path / "review.json"
    config = {"schema": "ZGE_SKILL_D28_WORKBENCH_BINDING_V1", "receipt": receipt,
              "chart_manifest": chart_ref, "review_path": str(review_path)}
    return config, candidate_ref, chart_ref, sample, review_path


def review(candidate, chart, sample, **changes):
    row = dict(symbol=CODE, asof="20261028", ruleset_id="ZGE_SKILL_DAILY_CANDIDATES_R2", source_generation=GEN,
               decision="KEEP", actual_image_viewed=True, image_sha256=sample["PNG"]["sha256"],
               visible_evidence=["形态证据"], counter_evidence=["反证"], reason="研究判断",
               reviewer_id="luna", reviewed_at="2026-10-31T10:00:00+08:00")
    row.update(changes)
    return dict(schema="ZGE_SKILL_D28_CHART_REVIEW_V1", asof="20261028",
                ruleset_id="ZGE_SKILL_DAILY_CANDIDATES_R2", source_generation=GEN,
                candidate_artifact=candidate, chart_manifest=chart, rows={CODE: row}, **FLAGS)


def test_day_exposes_r2_status_chart_and_missing_same_rule_statistics(fixture):
    config, candidate, chart, sample, review_path = fixture
    put(review_path, review(candidate, chart, sample))
    api = SkillR2Workbench(config)
    day = api.day("2026-10-29", {"time_contract": {"nodes": []}}, GEN)
    row = day["rows"][0]
    assert day["scope_count"] == 1 and day["original_processed_count"] == 5538
    assert day["statistics_status"] == "CANNOT_CONFIRM_NO_SAME_RULESET_D2_D5"
    assert row["group_states"]["skill_r2_b1"] == "TRUE" and row["group_states"]["skill_r2_sb1"] == "UNKNOWN"
    assert row["r2_pending"] and row["r2_risk"] and row["r2_record_status"] == "RISK_REVIEW"
    assert row["r2_review"]["decision"] == "KEEP" and row["r2_review"]["actual_image_viewed"] is True
    assert row["r2_chart"]["png_sha256"] == sample["PNG"]["sha256"]
    assert "skill-r2/assets" in row["r2_chart"]["html_url"]
    png, media = api.asset(CODE, "png", sample["PNG"]["sha256"], GEN)
    assert png == b"png bytes" and media == "image/png"
    with pytest.raises(ValueError, match="SHA_CONFLICT"):
        api.asset(CODE, "png", "0" * 64, GEN)
    with pytest.raises(ValueError, match="REVISION_CONFLICT"):
        api.day("2026-10-29", {"time_contract": {"nodes": []}}, "f" * 64)


def test_unviewed_or_wrong_image_cannot_be_promoted_to_reviewed(fixture):
    config, candidate, chart, sample, review_path = fixture
    api = SkillR2Workbench(config)
    def item(): return api.day("2026-10-29", {"time_contract": {"nodes": []}})["rows"][0]["r2_review"]
    assert item()["status"] == "NOT_REVIEWED"
    put(review_path, review(candidate, chart, sample, actual_image_viewed=False))
    assert item()["status"] == "ERROR_REVIEW_RECORD"
    put(review_path, review(candidate, chart, sample, image_sha256="0" * 64))
    assert item()["status"] == "ERROR_REVIEW_RECORD"
    put(review_path, review(candidate, chart, sample, symbol="000001.SZ"))
    assert item()["status"] == "ERROR_REVIEW_RECORD"
    put(review_path, review(candidate, chart, sample, asof="20261029"))
    assert item()["status"] == "ERROR_REVIEW_RECORD"
    put(review_path, review(candidate, chart, sample, source_generation="f" * 64))
    assert item()["status"] == "ERROR_REVIEW_RECORD"
    put(review_path, review(candidate, chart, sample, visible_evidence=[None, " "]))
    assert item()["status"] == "ERROR_REVIEW_RECORD"
    bad = review(candidate, chart, sample)
    bad["asof"] = "20261029"
    put(review_path, bad)
    assert item()["status"] == "ERROR_REVIEW_BINDING"


def test_later_review_changes_version_and_becomes_visible_without_reselection(fixture):
    config, candidate, chart, sample, review_path = fixture
    api = SkillR2Workbench(config)
    before = api.versions("2026-10-29")
    put(review_path, review(candidate, chart, sample, decision="WATCH"))
    after = api.versions("2026-10-29")
    assert after["event_id"] != before["event_id"]
    assert api.day("2026-10-29", {"time_contract": {"nodes": []}})["rows"][0]["r2_review"]["decision"] == "WATCH"


def test_asset_drift_and_escape_do_not_serve_bytes(fixture, tmp_path):
    config, _, _, sample, _ = fixture
    api = SkillR2Workbench(config)
    Path(sample["PNG"]["path"]).write_bytes(b"different")
    with pytest.raises(ValueError, match="SHA_DRIFT"):
        api.asset(CODE, "png", sample["PNG"]["sha256"], GEN)
    chart_path = Path(config["chart_manifest"]["path"])
    manifest = json.loads(chart_path.read_text())
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"outside")
    manifest["samples"][CODE]["PNG"] = ref(outside)
    config["chart_manifest"] = put(chart_path, manifest)
    with pytest.raises(ValueError, match="PATH_ESCAPE"):
        SkillR2Workbench(config).asset(CODE, "png", ref(outside)["sha256"], GEN)


def test_changed_candidate_artifact_fails_closed(fixture):
    config, candidate, _, _, _ = fixture
    Path(candidate["path"]).write_text("{}\n")
    with pytest.raises(ValueError, match="SHA_DRIFT"):
        SkillR2Workbench(config).day("2026-10-29", {"time_contract": {"nodes": []}})


def test_host_keeps_legacy_four_groups_for_other_dates(fixture):
    from infrastructure.research_workbench_host import ResearchWorkbenchHost
    config, _, _, _, _ = fixture
    classification = types.ModuleType("infrastructure.research_classification_view")
    classification.ReceivedClassificationStore = lambda root: types.SimpleNamespace(root=None)
    binding = {"schema": "V4_MAC_WORKBENCH_BINDING_V1", "skill_r2_d28": config, **FLAGS}
    source = types.SimpleNamespace()
    with patch.dict(sys.modules, {"infrastructure.research_classification_view": classification}):
        host = ResearchWorkbenchHost(source, binding)
    host._index = lambda: {"dates": {"20261029": {"sha256": "old"}}, "display_names": {}}
    host._observation_date = lambda day: "2026-10-30" if day == "2026-10-29" else "2026-10-29"
    host.workflow = lambda source_date: {"time_contract": {"nodes": []}}
    host._module_reference = lambda *args: None
    host._view = lambda source_date, revision=None: {
        "data_date": "20261029", "source_generation": "e" * 64,
        "source_identity": {"input_sha256": "f" * 64}, "manifest": {"path": "old", "sha256": "1" * 64},
        "artifact": {}, "processed_count": 247,
        "rows": [{"symbol": CODE, "display_name": "旧组样本", "groups": "original|nav_smallk",
                  "pending_groups": "nav_pullback"}],
    }
    legacy = host.day("2026-10-29")
    states = legacy["rows"][0]["group_states"]
    assert states == {"nav_smallk": "TRUE", "original": "TRUE", "nav_pullback": "UNKNOWN", "nav_breakout": "FALSE"}
    assert "ruleset_id" not in legacy and legacy["statistics_status"] == "CANNOT_CONFIRM_PROJECTION_MISSING"
    history = host.history()
    assert [d["source_date"] for d in history["days"]] == ["2026-10-29", "2026-10-28"]
    assert history["days"][0]["revision"] == "e" * 64 and history["days"][1]["revision"] == GEN
