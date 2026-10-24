"""Bounded original-producer archive additions; all inputs are synthetic."""
import copy
import hashlib
import json
from pathlib import Path
import struct
import zipfile

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ops import research_panel_qfq as q
from ops import research_panel_adjustment_inputs as inputs

W = Path(__file__).resolve().parents[1]
DRIVER = W / "ops/vendor/data_layer_daily_formula_increment_update_v1.py"
FORMULA = W / "ops/vendor/build_canonical_formula_research_panel.py"
BEFORE = Path("/Users/lexi/Desktop/学习/因子工厂/research/a_share_local_panel_completion_20261024/residual_recovery_r1/original_archive_addition_r1/research_panel_qfq_before.py")


def ref(path):
    return dict(path=str(path), sha256=q.sha(path))


def js(path, value):
    q._json(path, value)
    return ref(path)


def raw(path, dates):
    path.write_bytes(b"".join(struct.pack("<IIIIIfII", d, 1000+i, 1010+i, 990+i, 1000+i,
                                        float(100000+i), 10000+i, 0) for i, d in enumerate(dates)))
    return ref(path)


@pytest.fixture(scope="module")
def addition(tmp_path_factory):
    root = tmp_path_factory.mktemp("archive_additions")
    driver = q.authorities(DRIVER, FORMULA)[0]
    dates = pd.bdate_range(end="2026-10-23", periods=90).strftime("%Y%m%d").astype(int).tolist()
    target = dates[-1]; active = "002612.SZ"; inactive = "603007.SH"
    additions = ["601091.SH", "688837.SH"]
    member_refs = {}; all_dates = {}; archive = root / "original_archive.zip"
    with zipfile.ZipFile(archive, "w") as z:
        for code, count in zip(additions, (17, 39)):
            ds = dates[-4-count:-4]; path = root / (code + ".day"); raw(path, ds)
            member = "sh/lday/sh" + code[:6] + ".day"; z.writestr(member, path.read_bytes())
            member_refs[code] = dict(name="archive", kind="archive_member", path=str(archive), member=member,
                                     member_sha256=q.sha(path), inventory_first_date=str(ds[0]))
            all_dates[code] = ds
    archive_ref = ref(archive)
    policy = js(root / "policy.json", dict(name=q.HISTORY_RESOLUTION, selection_unit="COMPLETE_SOURCE_BAR", price_or_volume_conversion="NONE"))
    stock_rows = []; old_items = {}; frames = []
    for code, ds in ((active, dates), (inactive, dates[:-5])):
        source = raw(root / (code + ".day"), ds)
        stock_rows.append(dict(code=code, sources=[dict(**source, name="archive", kind="day_bytes")]))
        item = dict(raw_files=[dict(**source, source_role="archive")], history_start_date=ds[0], history_end_date=ds[-1],
                    events=[], event_coverage_complete=True, publish_roles=["selector", "backtest"],
                    history_extension=True, raw_resolution=q.HISTORY_RESOLUTION)
        old_items[code] = item
        f = q.rebuild_symbol(code, item, target, driver); f["name"] = "synthetic " + code
        f["field_contract_version"] = driver.CONTRACT_PROVENANCE_FIELD_DEFAULTS["field_contract_version"]
        frames.append(f)
    cfg_old = js(root / "source_old.json", dict(source_resolution=q.HISTORY_RESOLUTION, stocks=stock_rows))
    retention = dict(source_config=cfg_old, source_policy=policy, archive_refs=[archive_ref], accepted_evidence=[])
    for item in old_items.values():
        item.update(source_config=cfg_old, accepted_evidence=[])
    old = dict(schema="a_share_qfq_adjustment_input_v1", asof_date=target, coverage_end_date=target, price_basis="QFQ_ASOF",
               volume_basis="QFQ_EVENT_VOLUME", amount_basis="RAW_TURNOVER", convention="SYNTHETIC_ARCHIVE_ONLY", revision="before",
               observed_at="2026-10-24T00:00:00+00:00", source_files=[policy, cfg_old, archive_ref], symbols=old_items,
               history_extension=None, history_retention_binding=retention, retained_history_codes=[], accepted_target_date_floor=1)
    old_ref = js(root / "baseline_snapshot.json", old)
    cfg_new = js(root / "source_new.json", dict(source_resolution=q.HISTORY_RESOLUTION,
                    stocks=stock_rows + [dict(code=c, sources=[member_refs[c]]) for c in additions]))
    adjustment_source = js(root / "synthetic_adjustment_capture.json", dict(synthetic=True, original_rows="BOUND_SYNTHETIC_NO_PRICE_ACTIONS"))
    raw_reviews = {}; adjustment_reviews = {}; items = copy.deepcopy(old_items)
    for code in additions:
        ds = all_dates[code]
        items[code] = dict(raw_files=[dict(**ref(root / (code + ".day")), source_role="archive", original_ref=member_refs[code])],
            history_start_date=ds[0], history_end_date=ds[-1], compute_start_date=ds[0], required_output_start_date=ds[0],
            events=[], event_coverage_complete=True, publish_roles=["selector", "backtest"], history_extension=True,
            raw_resolution=q.HISTORY_RESOLUTION, source_method="SYNTHETIC_INDEPENDENT_IDENTITY_ONLY")
        raw_reviews[code] = dict(original_ref=member_refs[code], raw32_sha256=q.sha(root / (code + ".day")),
            dates_sha256=q.canonical_sha(ds), rows=len(ds), first_date=ds[0], last_date=ds[-1])
        adjustment_reviews[code] = dict(events_sha256=q.canonical_sha([]), source_method=items[code]["source_method"],
            history_coverage_start_date=ds[0], history_coverage_end_date=target, source_files=[adjustment_source])
    raw_review = js(root / "independent_raw_review.json", dict(verdict="REVIEWED/PASS_ARCHIVE_ONLY_SOURCE_KEYS_AND_BYTES",
        reviewer_id="/root/synthetic_independent_raw_reviewer", asof_date=target, codes=raw_reviews))
    adjustment_review = js(root / "independent_adjustment_review.json", dict(verdict="REVIEWED/PASS_ARCHIVE_ADDITION_ADJUSTMENT_INPUTS",
        reviewer_id="/root/synthetic_independent_adjustment_reviewer", asof_date=target, codes=adjustment_reviews))
    evidence = [raw_review, adjustment_review]
    new_retention = {**retention, "source_config": cfg_new, "accepted_evidence": evidence}
    for item in items.values():
        item.update(source_config=cfg_new, accepted_evidence=evidence)
    new = {**copy.deepcopy(old), "symbols": items, "revision": "archive_addition", "history_retention_binding": new_retention,
           "source_files": old["source_files"] + [cfg_new, *evidence, adjustment_source, *[ref(root/(c+".day")) for c in additions]]}
    field = root / "field.csv"; field.write_text("synthetic contract\n")
    identity = q.generation_identity(new, DRIVER, FORMULA, field)
    f = pd.concat(frames, ignore_index=True)
    columns = ["ts_code", "trade_date", "open", "high", "low", "close", "vol", "volume", "amount", "pre_close", "pct_chg",
               "BBI", "J", "ma60", "zge_white_line", "zge_yellow_line", "name", "bars_since_list", "field_contract_version",
               "raw_source_role", "raw_source_ref_sha256", "raw_source_record_index", *q.USER_FORMULA_SIGNAL_FIELDS]
    columns = list(dict.fromkeys(columns + [c for c in (*driver.CONTRACT_REQUIRED_V192_SELECTOR_COLUMNS,
        *driver.V192_ENTRY_FIELDS, *driver.V192_INTERMEDIATE_FIELDS, *driver.CRITICAL_SELECTOR_FORMULA_COLUMNS) if c in f]))
    baseline = f[columns].copy(); foreign = baseline.loc[baseline.ts_code.eq(active)].iloc[-2:].copy(); foreign.ts_code = "00700.HK"
    for name in q.USER_FORMULA_SIGNAL_FIELDS:
        foreign[name] = None
    baseline = pd.concat([baseline, foreign], ignore_index=True)
    sidecar = root / "original_excluded.parquet"; pq.write_table(pa.table(dict(ts_code=["301139.SZ"], trade_date=[20260831], close=[None])), sidecar)
    old_quarantine = js(root / "old_quarantine.json", dict(artifacts={r: ref(sidecar) for r in ("selector", "backtest")}, excluded_from_accepted=True))
    old_receipt = js(root / "old_receipt.json", dict(quarantine_manifest=old_quarantine))
    data = root / "data"; pointers = {}; roles = {}
    for role in ("selector", "backtest"):
        table = pa.Table.from_pandas(baseline, preserve_index=False)
        schema = pa.schema([pa.field(x.name, pa.int64(), nullable=True) if x.name == "bars_since_list" else x for x in q.user_formula_schema(table.schema)])
        meta = dict(**{**identity, "adapter_sha256": q.sha(BEFORE), "input_sha256": q.canonical_sha(old)},
                    asof_date=target, generation_id="synthetic-archive-baseline", history_retention_binding=retention,
                    quarantine_manifest_path=old_quarantine["path"], generation_manifest_path=old_receipt["path"])
        table = table.cast(schema).replace_schema_metadata({q.META_KEY: json.dumps(meta).encode()})
        path = root / (role + ".parquet"); pq.write_table(table, path); roles[role] = ref(path)
        pointer = data / role / "CURRENT.txt"; pointer.parent.mkdir(parents=True); pointer.write_text(str(path)); pointers[role] = pointer
    contract = dict(schema="qfq_archive_only_history_additions_v1", asof_date=target,
        baseline_generation_id="synthetic-archive-baseline", baseline_snapshot=old_ref, baseline_core=ref(BEFORE), baseline_roles=roles,
        codes={c: dict(dates=all_dates[c], raw_review=raw_review, adjustment_review=adjustment_review,
                       adjustment_source_files=[adjustment_source]) for c in additions})
    return dict(root=root, data=data, pointers=pointers, roles=roles, field=field, target=target, dates=all_dates,
                new=new, old=old, retention=retention, identity=identity, contract=contract,
                contract_ref=js(root / "addition_contract.json", contract), additions=additions,
                active=active, inactive=inactive, sidecar=sidecar, old_quarantine=old_quarantine, driver=driver)


def test_only_new_short_archive_prefixes_compute_all_old_arrow_rows_and_sidecars_survive(addition, monkeypatch):
    e = addition; before = {r: p.read_bytes() for r, p in e["pointers"].items()}; side = e["sidecar"].read_bytes()
    original = q.rebuild_symbol; called = []
    def rebuild(code, *args, **kwargs):
        assert code in e["additions"], "Recomputed unchanged accepted code"
        called.append(code); return original(code, *args, **kwargs)
    monkeypatch.setattr(q, "rebuild_symbol", rebuild); monkeypatch.setattr(inputs, "existing_day_files", lambda _: [])
    q._json(q.input_path(e["data"]), e["new"])
    result = q.run_daily_rebuild(driver_path=DRIVER, formula_path=FORMULA, tdx_root=e["root"]/"tdx", data_root=e["data"],
        pointers=e["pointers"], contract_csv=e["field"], return_root=e["root"]/"runs", target=e["target"],
        workers=2, archive_additions=e["contract_ref"])
    assert result["status"] == "CANDIDATE_READY" and sorted(called) == e["additions"]
    for role, path in result["candidates"].items():
        old = pq.read_table(e["roles"][role]["path"]); new = pq.read_table(path)
        assert len(new) == len(old) + 56
        for code in (e["active"], e["inactive"], "00700.HK"):
            a = old.filter(pa.compute.equal(old["ts_code"], code)); b = new.filter(pa.compute.equal(new["ts_code"], code))
            assert a.schema.equals(b.schema, check_metadata=False)
            for name in a.column_names:
                assert a[name].is_null().equals(b[name].is_null()) and a[name].equals(b[name])
        for code in e["additions"]:
            rows = new.filter(pa.compute.equal(new["ts_code"], code))
            assert rows["trade_date"].to_pylist() == e["dates"][code] and max(e["dates"][code]) < e["target"]
            # Original short-prefix initialization; no warmup/source fabrication.
            expected = original(code, e["new"]["symbols"][code], e["target"], e["driver"])
            for name in q.USER_FORMULA_SIGNAL_FIELDS:
                assert rows[name].to_pylist() == expected[name].tolist()
        assert result["counts"][role]["target_date_symbols"] == 1
        assert result["counts"][role]["old_key_conservation"]
        assert result["counts"][role]["archive_added_rows"] == 56
        assert e["pointers"][role].read_bytes() == before[role]
    assert e["sidecar"].read_bytes() == side
    manifest = json.loads(Path(result["quarantine_manifest"]["path"]).read_text())
    assert manifest["inherited_quarantine_manifests"] == [e["old_quarantine"]]
    assert result["history_retention_binding"] == e["new"]["history_retention_binding"]
    # Same original adapter dereferences real bound ZIP/member/source refs later.
    bound = inputs.history_raw_bindings(result["history_retention_binding"], e["root"]/"future"/"binding.json", e["driver"], e["target"])
    for code in e["additions"]:
        assert bound[code]["history_start_date"] == e["dates"][code][0]
        assert bound[code]["history_end_date"] == e["dates"][code][-1]
        assert len(bound[code]["raw_files"]) == 1 and bound[code]["raw_files"][0]["source_role"] == "archive"


@pytest.mark.parametrize("mutation,match", [
    ("old_value", "OLD_SYMBOL"), ("floor", "OLD_POLICY"), ("drop_old", "MEMBERSHIP"),
    ("no_adjustment_review", "INDEPENDENT_ADJUSTMENT_REVIEW"), ("wrong_raw_keys", "INDEPENDENT_RAW_REVIEW"),
    ("old_code", "MEMBERSHIP"), ("alter_old_stock", "OLD_SOURCE_CONFIG"), ("missing_adjustment_source", "PROVENANCE"),
])
def test_archive_addition_rejects_unbound_or_old_mutations(addition, mutation, match):
    e = addition; s = copy.deepcopy(e["new"]); contract = copy.deepcopy(e["contract"]); root = e["root"]; code = e["additions"][0]
    if mutation == "old_value": s["symbols"][e["active"]]["events"] = [dict(ex_date=e["target"], a=1., b=-1., volume_a=1.)]
    if mutation == "floor": s["accepted_target_date_floor"] = 0
    if mutation == "drop_old": s["symbols"].pop(e["inactive"])
    if mutation == "old_code": contract["codes"][e["active"]] = contract["codes"].pop(code)
    if mutation == "alter_old_stock":
        cfg = json.loads(Path(s["history_retention_binding"]["source_config"]["path"]).read_text()); cfg["stocks"][0]["extra"] = True
        s["history_retention_binding"]["source_config"] = js(root/"bad_old_stock.json", cfg)
    if mutation in ("no_adjustment_review", "wrong_raw_keys"):
        kind = "adjustment_review" if mutation == "no_adjustment_review" else "raw_review"
        report = json.loads(Path(contract["codes"][code][kind]["path"]).read_text()); report["codes"].pop(code)
        bad = js(root/(mutation+".json"), report); contract["codes"][code][kind] = bad
        s["history_retention_binding"]["accepted_evidence"].append(bad); s["symbols"][code]["accepted_evidence"].append(bad); s["source_files"].append(bad)
    if mutation == "missing_adjustment_source": contract["codes"][code]["adjustment_source_files"] = []
    with pytest.raises(q.QfqGateError, match=match):
        q.archive_addition_binding(js(root/(mutation+"_contract.json"), contract), snapshot=s, pointers=e["pointers"],
                                  identity=e["identity"], target=e["target"], retained_history=e["retention"])


def test_archive_addition_never_reuses_tail_or_soft_quarantines_new_failure(addition, monkeypatch):
    e = addition
    kwargs = dict(driver_path=DRIVER, formula_path=FORMULA, tdx_root=e["root"]/"tdx", data_root=e["data"],
        pointers=e["pointers"], contract_csv=e["field"], return_root=e["root"]/"failed_runs", target=e["target"], workers=1)
    with pytest.raises(q.QfqGateError, match="MUTUALLY_EXCLUSIVE"):
        q.run_daily_rebuild(**kwargs, archive_additions=e["contract_ref"], tail_delta={})
    with pytest.raises(q.QfqGateError, match="TAIL_DELTA_CONTRACT_INVALID"):
        q.tail_delta_binding(e["contract_ref"], snapshot=e["new"], pointers=e["pointers"], identity=e["identity"], target=e["target"], retained_history=e["retention"])
    monkeypatch.setattr(inputs, "existing_day_files", lambda _: [])
    def fail(*_, **__): raise q.QfqGateError("ORIGINAL_NEW_ARCHIVE_RAW_QUALITY_FAILURE")
    monkeypatch.setattr(q, "rebuild_symbol", fail); q._json(q.input_path(e["data"]), e["new"])
    before = {r: p.read_bytes() for r, p in e["pointers"].items()}
    with pytest.raises(q.QfqGateError, match="ORIGINAL_NEW_ARCHIVE_RAW_QUALITY_FAILURE"):
        q.run_daily_rebuild(**kwargs, archive_additions=e["contract_ref"])
    assert before == {r: p.read_bytes() for r, p in e["pointers"].items()}


def test_original_daily_retains_new_archive_only_members_without_target_bar(addition, monkeypatch):
    e = addition; next_target = 20261026
    summary = js(e["root"]/"future_sync.json", dict(target_keys=[dict(symbol=e["active"][:6], market=0)]))
    monkeypatch.setattr(inputs, "original_sync_contract", lambda *_: (summary, {}, 1))
    monkeypatch.setattr(inputs, "existing_day_files", lambda _: [])
    response = js(e["root"]/"future_empty_response.json", dict(code="SZ."+e["active"][:6], return_code=0, rows=[]))
    asked = []
    def cached_metadata(codes, **kwargs):
        asked.extend(codes)
        symbols = {}
        for code in codes:
            r = response if code == e["active"] else js(e["root"]/(code+".future_empty.json"), dict(code=code[-2:]+"."+code[:6], return_code=0, rows=[]))
            symbols[code] = dict(status="EMPTY", asof_date=next_target, capture_date=next_target, response=r, row_count=0)
        return dict(asof_date=next_target, symbols=symbols, finished_at="2026-10-26T16:00:00+08:00")
    monkeypatch.setattr(inputs, "collect_metadata", cached_metadata)
    data = e["root"]/"future_daily_data"
    snapshot = inputs.prepare_snapshot(tdx_root=e["root"]/"tdx", data_root=data, target=next_target, driver=e["driver"],
        required_start={c:e["dates"][c][0] for c in e["additions"]}, retained_history=e["new"]["history_retention_binding"])
    assert set(snapshot["retained_history_codes"]) == set(e["additions"])
    assert not set(e["additions"]) & set(asked)
    assert not set(e["additions"]) & set(snapshot["symbols"])
    assert snapshot["history_retention_binding"] == e["new"]["history_retention_binding"]
