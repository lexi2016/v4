"""Synthetic data only: targeted carry, preserved provenance, bounded restart."""
import copy
import json
from pathlib import Path
import struct
import zipfile

import pandas as pd
import pytest

from ops import research_panel_factor_cache as fc
from ops import research_panel_tdx_adjustment_inputs as td

CODES = ["600001.SH", "000001.SZ", "000002.SZ"]


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    return dict(path=str(path), sha256=fc.sha(path))


def ref(path):
    return dict(path=str(path), sha256=fc.sha(path))


def row(code="600001.SH", date=20260101, category=1, value=1):
    return dict(market={"SH": 1, "SZ": 0, "BJ": 2}[code[-2:]], code=code[:6], datetime=date,
                category=category, hongli_panqianliutong=float(value), peigujia_qianzongguben=0.,
                songgu_qianzongguben=0., peigu_houzongguben=0.)


def detector(root, day, rows, monkeypatch):
    root.mkdir(parents=True, exist_ok=True)
    parser = root / "reader.py"
    parser.write_text("# synthetic parser identity only\n")
    monkeypatch.setattr(td, "PARSER_SHA", fc.sha(parser))
    policy = put(root / "policy.json", {"synthetic": True})
    raw = root / "raw.gbbq"
    raw.write_bytes(struct.pack("<I", len(rows)) + bytes(29 * len(rows)))
    archive = root / "raw.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("gbbq", raw.read_bytes())
    captured = dict(observed_at=f"{str(day)[:4]}-{str(day)[4:6]}-{str(day)[6:]}T10:00:00+00:00",
                    coverage_end_date=day, source_url=td.OFFICIAL_URL,
                    parser=ref(parser), raw=ref(raw), archive=ref(archive))
    capture = put(root / "capture.json", captured)
    frame = pd.DataFrame(rows, columns=list(row()))
    pq = root / "rows.parquet"
    frame.to_parquet(pq, index=False)
    derived = put(root / "derived.json", dict(sha256=fc.sha(pq), cache_id=fc.canonical_sha(
        dict(raw=ref(raw), parser=ref(parser), policy=policy))))
    return dict(capture=capture, raw=ref(raw), archive=ref(archive), parser=ref(parser),
                category_policy=policy, derived_parquet=ref(pq), derived_receipt=derived)


def original(root, code, rows=None):
    rows = rows or []
    response = put(root / (code + ".json"), dict(source="Futu OpenD get_rehab", code=code[-2:] + "." + code[:6], return_code=0, rows=rows))
    return dict(status="OK" if rows else "EMPTY", asof_date=20261028, capture_date=20261028,
                queried_at="2026-10-28T10:00:00+00:00", response=response, row_count=len(rows))


@pytest.fixture
def case(tmp_path, monkeypatch):
    old = detector(tmp_path / "d28", 20261028, [row()], monkeypatch)
    new = detector(tmp_path / "d29", 20261029, [row()], monkeypatch)
    previous = put(tmp_path / "previous.json", dict(asof_date=20261028, symbols={c: original(tmp_path / "responses", c) for c in CODES}))
    identities = {c: {"code": c, "market": c[-2:], "lifecycle": "LISTED"} for c in CODES}
    cfg = dict(schema="research_factor_cache_plan.v1", target_date=20261029, previous_metadata=previous,
        previous_identities=put(tmp_path / "ids28.json", dict(asof_date=20261028, symbols=identities)),
        current_identities=put(tmp_path / "ids29.json", dict(asof_date=20261029, symbols=identities)),
        prior_detector=old, current_detector=new, observed_provider_only_exceptions=[],
        provider_only_exception_scope="Observed D28/D29 only; unknown future vendor-only revisions CANNOT_CONFIRM", source_comparison_refs=[])
    return tmp_path, cfg


def plan(case):
    root, cfg = case
    return fc.research_cache_plan(CODES, target=cfg["target_date"], config_ref=put(root / "cfg.json", cfg))


def no_client():
    raise AssertionError("unexpected provider client")


def test_carry_all_no_provider_preserves_original_and_restart(case):
    root, cfg = case
    cfgref = put(root / "cfg.json", cfg)
    out = fc.collect_research_metadata(CODES, cache_root=root / "cache", target=20261029, config_ref=cfgref, client_factory=no_client)
    assert out["counts"] == {fc.RESEARCH_CARRY_LABEL: 3}
    assert out["provider_call_count"] == 0
    receipt = out["symbols"][CODES[0]]
    assert receipt["original_capture_date"] == receipt["original_asof_date"] == 20261028
    assert receipt["provider_revision_coverage"] == "CANNOT_CONFIRM"
    assert receipt["historical_PIT"] is False
    restarted = fc.collect_research_metadata(CODES, cache_root=root / "cache", target=20261029, config_ref=cfgref, client_factory=no_client)
    assert restarted["reused_completed_proof"] is True
    assert restarted["symbols"] == out["symbols"]


def test_d28_d29_d30_carry_of_carry_and_parent(case, monkeypatch):
    root, cfg = case
    out = fc.collect_research_metadata(CODES, cache_root=root / "cache", target=20261029,
                                      config_ref=put(root / "cfg29.json", cfg), client_factory=no_client)
    parent = put(root / "parent29.json", out)
    cfg.update(target_date=20261030, previous_metadata=parent, previous_identities=cfg["current_identities"],
        current_identities=put(root / "ids30.json", dict(asof_date=20261030, symbols=json.loads(Path(cfg["current_identities"]["path"]).read_text())["symbols"])),
        prior_detector=cfg["current_detector"], current_detector=detector(root / "d30", 20261030, [row()], monkeypatch))
    second = fc.collect_research_metadata(CODES, cache_root=root / "cache", target=20261030,
            config_ref=put(root / "cfg30.json", cfg), client_factory=no_client)
    for c in CODES:
        item = second["symbols"][c]
        assert item["original_provider_receipt"] == out["symbols"][c]["original_provider_receipt"]
        assert item["original_capture_date"] == 20261028
        assert item["prior_valid_through"] == 20261029
        assert item["parent_metadata"] == parent
        assert item["verification"]["target_date"] == 20261030
    assert second["provider_call_count"] == 0


@pytest.mark.parametrize("new_rows,reason", [
    ([row(value=2)], "OFFICIAL_FULL_ROW_CHANGE"),
    ([row(), row(date=20261029)], "OFFICIAL_EVENT_EFFECTIVE_WINDOW"),
    ([row(), row(category=99)], "OFFICIAL_FULL_ROW_CHANGE"),
    ([], "OFFICIAL_FULL_ROW_CHANGE"),
    ([row(), row()], "OFFICIAL_FULL_ROW_CHANGE"),
])
def test_full_rows_invalidate_only_affected(case, monkeypatch, new_rows, reason):
    root, cfg = case
    cfg["current_detector"] = detector(root / "new", 20261029, new_rows, monkeypatch)
    out = plan(case)["symbols"]
    assert out[CODES[0]]["route"] == "REFRESH_REQUIRED"
    assert reason in out[CODES[0]]["reasons"]
    assert all(out[c]["route"] == fc.RESEARCH_CARRY_LABEL for c in CODES[1:])


def test_reordering_ignored_but_full_fields_preserved():
    rows = [row(), row(date=20260102, category=99)]
    assert td.full_row_event_index(rows) == td.full_row_event_index(rows[::-1])
    assert td.full_row_event_index(rows) != td.full_row_event_index(rows + [rows[0]])


@pytest.mark.parametrize("issue", ["identity", "missing", "exception", "response_sha", "future_event"])
def test_targeted_identity_cache_exception_and_future(case, issue):
    root, cfg = case
    if issue == "identity":
        ids = json.loads(Path(cfg["current_identities"]["path"]).read_text())
        ids["symbols"][CODES[0]]["lifecycle"] = "CHANGED"
        cfg["current_identities"] = put(root / "changed_ids.json", ids)
    elif issue == "exception":
        cfg["observed_provider_only_exceptions"] = [dict(ts_code=CODES[0], evidence=put(root / "exception.json", dict(observed=True)))]
    else:
        previous = json.loads(Path(cfg["previous_metadata"]["path"]).read_text())
        if issue == "missing":
            del previous["symbols"][CODES[0]]
        elif issue == "response_sha":
            previous["symbols"][CODES[0]]["response"]["sha256"] = "wrong"
        else:
            previous["symbols"][CODES[0]] = original(root / "future", CODES[0], [dict(ex_div_date="2026-10-29", forward_adj_factorA=1., forward_adj_factorB=-.4, backward_adj_factorA=1.)])
        cfg["previous_metadata"] = put(root / "previous_changed.json", previous)
    out = plan(case)["symbols"]
    assert out[CODES[0]]["route"] == "REFRESH_REQUIRED"
    assert all(out[c]["route"] == fc.RESEARCH_CARRY_LABEL for c in CODES[1:])


@pytest.mark.parametrize("issue", ["missing_source", "coverage", "parser", "schema", "identity_date"])
def test_global_unbound_stops_before_any_provider(case, issue):
    root, cfg = case
    if issue == "missing_source":
        cfg["current_detector"]["raw"]["sha256"] = "bad"
    elif issue == "coverage":
        cfg["current_detector"] = cfg["prior_detector"]
    elif issue == "parser":
        cfg["current_detector"]["parser"]["sha256"] = "bad"
    elif issue == "schema":
        p = Path(cfg["current_detector"]["derived_parquet"]["path"])
        pd.DataFrame([dict(bad=1)]).to_parquet(p)
        cfg["current_detector"]["derived_parquet"] = ref(p)
    else:
        cfg["current_identities"] = cfg["previous_identities"]
    with pytest.raises((fc.QfqGateError, ValueError)):
        fc.collect_research_metadata(CODES, cache_root=root / "cache", target=20261029,
            config_ref=put(root / "cfg.json", cfg), client_factory=no_client)
    assert not (root / "cache" / "20261029" / "checkpoint.json").exists()


def test_actual_original_collector_only_refreshes_changed_identity(case, monkeypatch):
    root, cfg = case
    cfg["current_detector"] = detector(root / "changed", 20261029, [row(value=4)], monkeypatch)
    calls = []
    class Client:
        def get_rehab(self, code):
            calls.append(code)
            return 0, []
        def close(self):
            pass
    monkeypatch.setattr(fc, "_capture_date", lambda: 20261029)
    monkeypatch.setattr(fc, "_now", lambda: "2026-10-29T10:00:00+00:00")
    cfgref = put(root / "cfg.json", cfg)
    out = fc.collect_research_metadata(CODES, cache_root=root / "cache", target=20261029,
        config_ref=cfgref, client_factory=Client, retries=0, min_interval=0)
    assert calls == ["SH.600001"]
    assert out["provider_identity_count"] == out["provider_call_count"] == 1
    assert sum(out["counts"].values()) == 3
    again = fc.collect_research_metadata(CODES, cache_root=root / "cache", target=20261029,
        config_ref=cfgref, client_factory=no_client)
    assert again["invocation_provider_call_count"] == 0


def test_builder_preserves_original_affine_volume_and_rejects_relabel(case):
    root, cfg = case
    previous = json.loads(Path(cfg["previous_metadata"]["path"]).read_text())
    previous["symbols"][CODES[0]] = original(root / "affine", CODES[0], [dict(ex_div_date="2026-01-01", forward_adj_factorA=.83, forward_adj_factorB=-.19112, backward_adj_factorA=1.21)])
    cfg["previous_metadata"] = put(root / "previous_affine.json", previous)
    p = plan(case)
    receipt = copy.deepcopy(p["symbols"][CODES[0]]["receipt"])
    events, scope = fc.research_carry_events(receipt, CODES[0], 20261029, 20250101, plan=p)
    assert events == [dict(ex_date=20260101, a=.83, b=-.19112, volume_a=1.21)]
    assert "CANNOT_CONFIRM" in scope
    receipt["original_capture_date"] = 20261029
    with pytest.raises(fc.QfqGateError):
        fc.research_carry_events(receipt, CODES[0], 20261029, 20250101, plan=p)


def test_carry_parent_identity_or_coverage_drift_stops(case, monkeypatch):
    root, cfg = case
    out = fc.collect_research_metadata(CODES, cache_root=root / "cache", target=20261029,
            config_ref=put(root / "cfg29.json", cfg), client_factory=no_client)
    out["detector_binding"] = "drift"
    cfg.update(target_date=20261030, previous_metadata=put(root / "parent.json", out),
        previous_identities=cfg["current_identities"],
        current_identities=put(root / "ids30.json", dict(asof_date=20261030, symbols=json.loads(Path(cfg["current_identities"]["path"]).read_text())["symbols"])),
        prior_detector=cfg["current_detector"], current_detector=detector(root / "d30", 20261030, [row()], monkeypatch))
    with pytest.raises(fc.QfqGateError, match="PARENT_DETECTOR"):
        plan(case)


def test_existing_same_day_gate_remains_strict_and_builder_explicit(case, monkeypatch):
    # Only the absent canonical qfq module is supplied as an import fixture;
    # execute the actual adjustment builder and original same-day validator.
    import importlib.util
    import re
    import sys
    import types
    root, cfg = case
    stub = types.ModuleType("ops.research_panel_qfq")
    for name in ("_json", "_source", "canonical_sha", "sha"):
        setattr(stub, name, getattr(fc, name))
    stub._write = lambda *args: None
    stub.CODE = re.compile(r"\d{6}\.(SH|SZ|BJ)")
    stub.legacy_preservation = lambda _: {}
    stub.input_path = lambda data: data / "inputs" / "snapshot.json"
    monkeypatch.setitem(sys.modules, "ops.research_panel_qfq", stub)
    spec = importlib.util.spec_from_file_location("carry_builder_under_test", Path(__file__).parents[1] / "ops/research_panel_adjustment_inputs.py")
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    previous = json.loads(Path(cfg["previous_metadata"]["path"]).read_text())
    with pytest.raises(fc.QfqGateError, match="ASOF_CONFLICT"):
        builder._full_provider_response_events(previous["symbols"][CODES[0]], CODES[0], 20261029, 20250101, previous)
    sync = put(root / "sync.json", dict(symbol_reconciliation=[], target_keys=[]))
    monkeypatch.setattr(builder, "original_sync_contract", lambda *args: (sync, {}, 20261029))
    monkeypatch.setattr(builder, "raw_bindings", lambda *args, **kwargs: {c: dict(history_start_date=20250101, compute_start_date=20250101) for c in CODES})
    out = builder.prepare_snapshot(tdx_root=root / "isolated" / "tdx", data_root=root / "output", target=20261029, driver=None,
                                  research_cache_config_ref=put(root / "config.json", cfg), client_factory=no_client)
    assert out["schema"] == "a_share_qfq_adjustment_input_research_cache_v1"
    assert out["provider_revision_coverage"] == "CANNOT_CONFIRM"
    assert all(r["source_method"] == fc.RESEARCH_CARRY_LABEL for r in out["symbols"].values())
    assert out["research_factor_receipts"]["provider_call_count"] == 0


@pytest.mark.parametrize("issue", ["identity", "coverage", "original_proof"])
def test_second_carry_day_rechecks_identity_coverage_and_original(case, monkeypatch, issue):
    root, cfg = case
    first = fc.collect_research_metadata(CODES, cache_root=root / "cache", target=20261029,
        config_ref=put(root / "cfg29.json", cfg), client_factory=no_client)
    ids = json.loads(Path(cfg["current_identities"]["path"]).read_text())
    ids["asof_date"] = 20261030
    if issue == "identity":
        ids["symbols"][CODES[0]]["market"] = "changed"
    if issue == "original_proof":
        first["symbols"][CODES[0]]["original_capture_date"] = 20261029
    cfg.update(target_date=20261030, previous_metadata=put(root / "parent29.json", first),
        previous_identities=cfg["current_identities"], current_identities=put(root / "ids30.json", ids),
        prior_detector=cfg["current_detector"], current_detector=detector(root / "d30", 20261030, [row()], monkeypatch))
    if issue == "coverage":
        cfg["current_detector"] = cfg["prior_detector"]
        with pytest.raises(fc.QfqGateError, match="COVERAGE"):
            plan(case)
    else:
        p = plan(case)["symbols"]
        assert p[CODES[0]]["route"] == "REFRESH_REQUIRED"
        assert all(p[c]["route"] == fc.RESEARCH_CARRY_LABEL for c in CODES[1:])
