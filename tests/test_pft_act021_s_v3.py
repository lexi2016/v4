from __future__ import annotations

import inspect
import json
from pathlib import Path
import zipfile

import numpy as np
import pandas as pd
import pytest

from ops import pft_act021_s_v3 as s
from ops import pft_act021_transform as t


def bars(n=90, code="000001.SZ"):
    dates = pd.bdate_range("2026-07-01",periods=n)
    rows = []
    for i,d in enumerate(dates):
        p = 10+i*.01
        rows.append(dict(ts_code=code,trade_date=d.strftime("%Y%m%d"),market_type="SZ",
                         open=p*.999,high=p*1.01,low=p*.99,close=p,vol=1000.,
                         zge_white_line=p*.98,zge_yellow_line=p*.96,bbi=p*.99))
    return pd.DataFrame(rows)


def group(d="20261103"):
    return dict(source_date=d,observation_date=d,decision_date=d,top200_revision="verified-r1",source_generation="g1",
                panel_generation="g1",ranking_sha256="a"*64,source_ref="verified-original",price_basis="QFQ_ASOF",
                rows=[dict(source_rank=i,ts_code=f"{i:06d}.SZ") for i in range(1,201)])


def binding():
    return dict(status="BOUND",panel_generation="g1",volume_basis="QFQ_EVENT_VOLUME")


def review(frame, **updates):
    d=frame.iloc[-1].trade_date
    g=group(d)
    raw=s.previous.causal_shapes(frame,start=d,end=d)
    shape=raw.iloc[-1].to_dict() if len(raw) else None
    if shape:
        shape.update(updates)
    return s.review_row(g,g["rows"][0],frame,shape,binding(),{})


def test_rank_package_iso_and_unique_200_preserves_missing_group(tmp_path):
    g=group()
    g.update(source_date="2026-11-03",observation_date="2026-11-04",decision_date="2026-11-03")
    p=tmp_path/"ranks.json"
    p.write_text(json.dumps({"groups":[g,dict(source_date="2026-11-04",observation_date="2026-11-05",decision_date="2026-11-04",status="CANNOT_CONFIRM",reason="not published")]}))
    groups,identity=s.load_groups(p)
    assert len(groups[0]["rows"])==200 and groups[0]["decision_date"]=="20261103"
    assert groups[1]["status"]=="CANNOT_CONFIRM" and identity["group_count"]==2
    g["rows"][199]["source_rank"]=1
    p.write_text(json.dumps({"groups":[g]}))
    with pytest.raises(s.ContractError,match="DUPLICATE_OR_GAP"):
        s.load_groups(p)


def test_source_sha_is_checked_and_group_date_never_substituted(tmp_path):
    g=group()
    manifest=tmp_path/"source.json"
    manifest.write_text("immutable")
    g["source_manifests"]=[dict(path=str(manifest),sha256="0"*64)]
    p=tmp_path/"ranks.json"
    p.write_text(json.dumps({"groups":[g]}))
    with pytest.raises(s.ContractError,match="SOURCE_SHA_MISMATCH"):
        s.load_groups(p)
    g.pop("source_manifests")
    g["decision_date"]="20261102"
    p.write_text(json.dumps({"groups":[g]}))
    with pytest.raises(s.ContractError,match="RANK_DATE_BINDING"):
        s.load_groups(p)


def test_causality_future_poison_does_not_change_d_row():
    f=bars()
    d=f.iloc[79].trade_date
    prefix=f.iloc[:80]
    before=review(prefix)
    after=f.copy()
    after.loc[80:,list(s.NUMERIC)]=1e10
    shaped=s.previous.causal_shapes(after,start=d,end=d).iloc[0].to_dict()
    actual=s.review_row(group(d),group(d)["rows"][0],after.loc[after.trade_date.le(d)],shaped,binding(),{})
    assert before==actual
    assert before["strict_le_d_verified"] and before["context_observed_bars"]==80
    assert all(max(e["window"])<=d for e in before["positive_evidence"]+before["contra_evidence"] if e["window"])


def event_frame():
    f=bars(20)
    # First root impulse after sufficient prior-volume history.
    f.loc[6,["open","high","low","close","vol"]]=[10.,10.65,9.9,10.5,1500.]
    return f


def test_anchor_same_day_pierce_and_close_failure_and_recovery_distinct():
    f=event_frame().iloc[:10].copy()
    f.loc[7,["open","high","low","close"]]=[10.1,10.3,9.7,10.2]
    h=s.anchor_history(f.iloc[:8])
    root=h["root"]
    assert root["low_pierced_recovered_flag"] is True
    assert root["close_broken_flag"] is False
    assert root["same_day_low_pierce_reclaim_current"] is True
    # A close-break followed by a later above-anchor close is not same-day reclaim.
    f.loc[7,["open","high","low","close"]]=[10.,10.1,9.6,9.7]
    f.loc[8,["open","high","low","close"]]=[10.,10.3,9.95,10.2]
    h=s.anchor_history(f.iloc[:9])
    root=h["root"]
    assert root["low_pierced_recovered_flag"] is False
    assert root["close_broken_flag"] is True and root["multi_day_close_recovery_current"] is True
    assert root["min_low_since_anchor"]==9.6 and root["min_close_since_anchor"]==9.7


def test_old_close_failure_survives_new_management_anchor():
    f=event_frame().iloc[:12].copy()
    f.loc[7,["open","high","low","close"]]=[10.,10.1,9.5,9.6]
    f.loc[10,["open","high","low","close","vol"]]=[10.,11.0,10.,10.9,2500.]
    h=s.anchor_history(f)
    assert h["root"]["role"]=="root" and h["root"]["close_broken_flag"]
    assert h["active"]["role"]=="management" and h["active"]["parent_anchor_id"]==h["root"]["anchor_id"]
    assert h["old_close_failure_survives_new_anchor"]
    assert len(h["active"]["quality_dimensions"])==3


def test_repair_without_observed_root_does_not_invent_root():
    f=bars(12)
    f.loc[6:7,["open","high","low","close"]]=[9.6,9.8,9.4,9.5]
    f.loc[8,["open","high","low","close","vol"]]=[10.,10.45,9.95,10.3,1200.]
    h=s.anchor_history(f.iloc[:9])
    assert h["events"] and h["active"]["role"]=="repair"
    assert h["root"] is None and h["window_left_censored"] is True


def test_stage_and_breakout_trigger_are_independent_of_tactic():
    f=bars()
    shape=s.previous.causal_shapes(f,start=f.iloc[-1].trade_date,end=f.iloc[-1].trade_date).iloc[0].to_dict()
    shape.update(tactic="UNKNOWN",repair_age=0.,volume_ratio=1.5,resistance_distance=.01)
    stage,flags=s.observable_stage(f,shape,s.anchor_history(f),True)
    assert stage=="EARLY_REPAIR" and flags["VOL_BREAKOUT"]
    shape["tactic"]="invalid_fake"
    assert s.observable_stage(f,shape,s.anchor_history(f),True)==(stage,flags)


def test_missing_context_is_retained_unknown_and_no_synthetic_bbi():
    f=bars(10)
    r=review(f)
    assert r["s_decision_state"]=="UNKNOWN_BORDERLINE" and r["s_overall_prob"] is None
    assert r["s_overall_score_100"] is None and r["ce_deduction_pts"] is None
    assert r["conformal_set_size"] is None and r["refusal_reasons"]==["DATA_UNAVAILABLE"]
    f=bars()
    f.loc[f.index[-3],"bbi"]=np.nan
    assert not s.blind_eligible(f,f.iloc[-1].trade_date)


def test_recent_and_prior_contraction_denominators_explicit_and_separate():
    f=bars(30)
    f["vol"]=np.arange(1,31,dtype=float)
    recent=s.contraction(f,"vol",recent=True)
    prior=s.contraction(f,"vol",recent=False)
    assert recent["numerator_mean"]==28 and recent["denominator_mean"]==18
    assert prior["numerator_mean"]==27 and prior["denominator_mean"]==17
    assert recent["numerator_dates"][-1]==f.iloc[-1].trade_date
    assert prior["numerator_dates"][-1]==f.iloc[-2].trade_date


def test_hierarchy_projection_retains_raw_model_and_no_half_gate():
    f=bars()
    d=f.iloc[-1].trade_date
    shape=s.previous.causal_shapes(f,start=d,end=d).iloc[0].to_dict()
    p={"pullback":.7,"readvance":.1,"rebuild":.1,"invalid_fake":.1}
    model={"binary_hgb":{"raw_positive_probability":.3},"tactic_hgb":{"raw_tactic_probabilities":p,"argmax_tactic":"pullback"}}
    r=s.review_row(group(d),group(d)["rows"][0],f,shape,binding(),model)
    assert r["s_overall_prob"]==.7 and r["frozen_model_diagnostic"]["binary_hgb"]["raw_positive_probability"]==.3
    assert "GREY_PROB_BAND" in r["refusal_reasons"] and r["s_decision_state"]=="UNKNOWN_BORDERLINE"
    assert r["tactic_probs_json"]==p and r["conformal_set_size"] is None


def test_compatibility_requires_generation_price_volume_indicator_identity():
    g=group()
    g["series_formula_sha256"]="formula"
    c=dict(allowed_panel_generations=["g1"],price_basis="QFQ_ASOF",volume_basis="QFQ_EVENT_VOLUME",series_formula_sha256="formula")
    assert s.compatible(g,binding(),c)
    for field in ("allowed_panel_generations","price_basis","volume_basis","series_formula_sha256"):
        assert not s.compatible(g,binding(),{**c,field:"wrong"})


def synthetic_candidates():
    # Disjoint true synthetic strata used only to verify mechanical selection.
    result=[]
    specs=[("conflict",8),("pullback",2),("readvance",2),("rebuild",2),("invalid_fake",2),("unknown",16)]
    specs += [(f"random{i}",2) for i in range(4)]
    index=1
    for kind,n in specs:
        for j in range(n):
            f=bars(code=f"{index:06d}.SZ")
            r=review(f)
            tactic=kind if kind in s.previous.CLASSES else "pullback"
            r.update(ts_code=f"{index:06d}.SZ",classification_id=str(index),primary_tactic=tactic,
                     model_argmax_tactic="invalid_fake" if kind=="conflict" else tactic,
                     tactic_probs_json={c:(.9 if c==tactic else .1/3) for c in s.previous.CLASSES} if kind in s.previous.CLASSES else None,
                     model_rule_conflict=kind=="conflict",s_decision_state="UNKNOWN_BORDERLINE" if kind=="unknown" else "CONFIRMED_S",
                     source_rank=int(kind[-1])*50+j+1 if kind.startswith("random") else 1)
            result.append(dict(review=r,frame=f.tail(60)))
            index+=1
    return result


def test_blind_quotas_truthful_unique_deterministic_and_shortfall():
    candidates=synthetic_candidates()
    a,receipt=s.select_blind(candidates)
    b,_=s.select_blind(list(reversed(candidates)))
    assert len(a)==40 and receipt["status"]=="COMPLETE_40"
    assert [r["review"]["classification_id"] for r in a]==[r["review"]["classification_id"] for r in b]
    assert len({r["review"]["ts_code"] for r in a})==40
    no_conflict=[c for c in candidates if not c["review"]["model_rule_conflict"]]
    selected,receipt=s.select_blind(no_conflict)
    assert receipt["shortfall"]["ACTUAL_MODEL_RULE_CONFLICT"]==8 and len(selected)==32
    assert receipt["status"]=="PARTIAL_QUOTA_SHORTFALL" and not receipt["quota_substitution"]


def test_public_whitelist_normalization_zip_membership_and_private_separation(tmp_path):
    result=s.write_blind(synthetic_candidates(),tmp_path)
    assert result["status"]=="COMPLETE_40"
    reveal=json.loads((tmp_path/"private_reveal.json").read_text())
    assert len(reveal["cases"])==40
    with zipfile.ZipFile(tmp_path/"public_blind.zip") as z:
        names=z.namelist()
        assert len(names)==42 and "private_reveal.json" not in names
        for name in names:
            raw=z.read(name).decode()
            assert not any(x in raw for x in ("ts_code","source_rank","primary_tactic","decision_date","private_bucket","classification_id","ACTUAL_MODEL_RULE","/Users/"))
            if name.endswith(".json") and name!="manifest.json":
                c=json.loads(raw)
                s.validate_public_case(c)
                assert c["bars"][0]["close"]==1
                c["answer"]="hint"
                with pytest.raises(s.ContractError,match="TOP_LEVEL_LEAK"):
                    s.validate_public_case(c)
    assert (tmp_path/"private_reveal.json").stat().st_mode & 0o777==0o600


def test_numpy_transform_exact_kernel_pooling_shape_no_fit_and_determinism():
    k=t.kernels()
    assert k.shape==(84,9) and np.all((k==2).sum(axis=1)==3) and np.all(k.sum(axis=1)==0)
    x=t.channels(bars().tail(65))
    assert x.shape==(7,60) and np.isfinite(x).all()
    first=t.transform(x[None])
    second=t.transform(x[None])
    assert first.shape==(1,84672) and np.array_equal(first,second)
    pooled=t._pool(np.array([[1.,-2.,3.,4.,-1.]]),0)
    np.testing.assert_allclose(pooled,[[.6,8/3,(0+2+3)/3/4,.4]])
    none=t._pool(np.array([[-1.,0.]]),0)
    np.testing.assert_array_equal(none,[[0,0,-1,0]])
    assert not hasattr(t,"fit") and not hasattr(s,"fit")
    src=inspect.getsource(s)
    assert ".fit(" not in src and "fit_four(" not in src and "forward_returns(" not in src
    assert "previous.predict(" not in src


def test_transform_benchmark_reports_actual_shape_scope_checksum():
    x=t.channels(bars().tail(65))[None]
    result=t.benchmark(x)
    assert result["input_shape"]==[1,7,60] and result["output_shape"]==[1,84672]
    assert result["deterministic"] and result["fit_count"]==0 and result["peak_rss_bytes"]>0
    assert len(result["output_sha256"])==64 and "whole process" in result["peak_rss_scope"]
    with pytest.raises(ValueError,match="65_VALID"):
        t.channels(bars(60))


def test_pipeline_retains_200_rows_per_group_and_missing_exact_d(tmp_path,monkeypatch):
    f=bars()
    d=f.iloc[-1].trade_date
    g=group(d)
    next_g=group((pd.Timestamp(d)+pd.offsets.BDay(1)).strftime("%Y%m%d"))
    next_g["panel_missing_reason"]="authoritative context missing"
    inp=tmp_path/"input.json"
    inp.write_text(json.dumps({"groups":[g,next_g]}))
    def binder(g):
        return (Path("bound") if g["decision_date"]==d else None),binding()
    def reader(*a):
        return f
    monkeypatch.setattr(s.previous,"model_factory",lambda *a:pytest.fail("must not fit"))
    result=s.run(inp,tmp_path/"out",reader=reader,binder=binder)
    lines=[json.loads(x) for x in (tmp_path/"out"/"review_rows.jsonl").read_text().splitlines()]
    assert lines[0]["record_type"]=="schema" and len(lines)==401
    actual=lines[1:]
    assert len({r["classification_id"] for r in actual})==400
    assert [r["source_rank"] for r in actual[:200]]==list(range(1,201))
    assert sum(r["context_status"]=="READY" for r in actual)==1
    assert sum(r["context_status"]=="EXACT_D_MISSING" for r in actual)==399
    for r in actual:
        assert all(set(fields)<=set(r) for fields in s.FIELD_GROUPS.values())
        assert r["conformal_set_size"] is None and r["reviewed_asof_d"] is None
    assert result["actual_fit"]==dict(S=0,B=0,tuning=0,conformal=0) and result["backtest_count"]==0
    assert result["source_recheck"]=="PASS_NO_EXCEPTION"
    assert result["blind"]["status"]=="PARTIAL_QUOTA_SHORTFALL"


def test_cross_class_internal_fallback_never_fabricates_absent_class():
    candidates=synthetic_candidates()
    candidates=[c for c in candidates if c["review"]["primary_tactic"]!="rebuild"]
    # Add two genuinely eligible positive proxies to replace the absent class.
    for j in range(2):
        c=dict(candidates[8+j])
        c["review"]={**c["review"],"ts_code":f"{900+j:06d}.SZ","classification_id":f"extra{j}"}
        candidates.append(c)
    _,receipt=s.select_blind(candidates)
    assert receipt["actual"]["CROSS_CLASS_HIGH_CONF_PROXY"]==8
    assert receipt["cross_class_actual_tactic_allocation"]["rebuild"]==0
    assert "rebuild" in receipt["cross_class_absent_eligible_tactics"]
    assert receipt["cross_class_actual_tactic_allocation"]["invalid_fake"]>=1
    only_positive=[c for c in candidates if c["review"]["primary_tactic"]!="invalid_fake"]
    _,receipt=s.select_blind(only_positive)
    assert receipt["shortfall"]["CROSS_CLASS_HIGH_CONF_PROXY"]==8
    assert not receipt["cross_class_positive_negative_available"]


def test_per_group_panel_binding_rejects_latest_or_wrong_generation(tmp_path,monkeypatch):
    from ops import pft_s_first_baseline as b
    from ops import research_panel_qfq as q
    panel=tmp_path/"panel.parquet"
    panel.write_bytes(b"synthetic-only-contract-mock")
    g=group()
    g.update(panel_path=str(panel),panel_sha256=s.file_sha(panel))
    monkeypatch.setattr(q,"panel_contract",lambda p:{"synthetic":True})
    identity=dict(generation_id="g1",price_basis="QFQ_ASOF",volume_basis="QFQ_EVENT_VOLUME")
    source=dict(asof_date=g["decision_date"])
    monkeypatch.setattr(b,"_contract_identity",lambda *args:(identity,source))
    bound,receipt=s.bind_panel(g)
    assert bound==panel and receipt["panel_generation"]=="g1"
    source["asof_date"]="20261120"
    with pytest.raises(s.ContractError,match="EXACT_PANEL_GENERATION_OR_DATE"):
        s.bind_panel(g)
    source["asof_date"]=g["decision_date"]
    identity["generation_id"]="latest-unrelated"
    with pytest.raises(s.ContractError,match="EXACT_PANEL_GENERATION_OR_DATE"):
        s.bind_panel(g)


def test_model_loader_pins_weight_ledger_sha_features_and_zero_new_fit(tmp_path,monkeypatch):
    class ReadOnlyFake:
        def __init__(self,name):
            self.classes_=np.array([0,1] if name.startswith("binary") else [0,1,2,3])
        def predict_proba(self,x):
            return np.full((len(x),len(self.classes_)),1/len(self.classes_))
        def fit(self,*args):
            pytest.fail("infrastructure may not call fit")
    models={}
    weight_sha={}
    for name in s.previous.MODEL_NAMES:
        weight=tmp_path/f"{name}.joblib"
        weight.write_text("synthetic trusted local bytes "+name)
        weight_sha[name]=s.file_sha(weight)
        models[name]=dict(state="COMPLETE",weight_sha256=weight_sha[name])
    ledger=tmp_path/"fit_ledger.json"
    ledger.write_text(json.dumps(dict(S=4,B=0,tuning=0,models=models)))
    contract=dict(scope="RETROSPECTIVE_FROZEN_DIAGNOSTIC_ONLY",training_panel_generation=s.previous.GENERATION,
                  features=s.previous.FEATURE_UNITS,weights_sha256=weight_sha,fit_ledger_sha256=s.file_sha(ledger))
    p=tmp_path/"contract.json"
    p.write_text(json.dumps(contract))
    monkeypatch.setattr(s.previous,"load_weight",lambda path:ReadOnlyFake(path.stem))
    loaded,identity=s.load_models(tmp_path,p)
    assert len(loaded)==4 and identity["status"]=="LOADED_TRUSTED_LOCAL"
    f=bars()
    d=f.iloc[-1].trade_date
    shapes=s.previous.causal_shapes(f,start=d,end=d)
    result=s.infer_batch(shapes,loaded)
    assert result[("000001.SZ",d)]["binary_hgb"]["raw_positive_probability"]==.5
    (tmp_path/"binary_hgb.joblib").write_text("changed weights")
    with pytest.raises(s.ContractError,match="SOURCE_SHA_MISMATCH"):
        s.load_models(tmp_path,p)


def test_public_validator_rejects_free_text_in_anchor_values():
    c=synthetic_candidates()[0]
    payload=s.public_case(c,"a"*24)
    payload["anchor_facts"]=[dict(role="root",bar_index=0,outside_visible_window=False,low="private identity",body_mid=1.)]
    with pytest.raises(s.ContractError,match="ANCHOR_VALUE_LEAK"):
        s.validate_public_case(payload)


def test_unknown_refusal_repairs_439_unflagged_rows_without_changing_frozen_fields():
    # Reproduces the observed materialized failure shape: UNKNOWN, false flag,
    # no reasons and NORMAL priority. This is a row-only repair, not a rerun.
    original_rows=[dict(record_type="review",classification_id=f"frozen-{i}",classification_revision=1,
                        source_rank=i%200+1,ts_code=f"{i+1:06d}.SZ",source_date="20261120",
                        observation_date="20261123",decision_date="20261120",top200_revision="frozen",
                        s_decision_state="UNKNOWN_BORDERLINE",primary_tactic="UNKNOWN",s_overall_prob=.91,
                        s_overall_score_100=42.,tactic_probs_json={"pullback":.1,"invalid_fake":.9},
                        refusal_flag=False,refusal_reasons=[],human_review_priority="NORMAL") for i in range(439)]
    changed_fields={"refusal_flag","refusal_reasons","human_review_priority"}
    for original in original_rows:
        snapshot=json.loads(json.dumps(original))
        repaired=s.repair_unknown_refusal(original)
        assert original==snapshot
        assert repaired["refusal_flag"] is True and repaired["refusal_reasons"]==["OUT_OF_DOMAIN"]
        assert repaired["human_review_priority"]=="HIGH"
        assert {k:v for k,v in repaired.items() if k not in changed_fields}=={k:v for k,v in original.items() if k not in changed_fields}
        assert s.repair_unknown_refusal(repaired)==repaired
    assert len(original_rows)==439


def test_unknown_refusal_preserves_specific_reasons_and_non_unknown_rows():
    original=dict(s_decision_state="UNKNOWN_BORDERLINE",refusal_flag=True,
                  refusal_reasons=["EVIDENCE_CONFLICT","GREY_PROB_BAND"],human_review_priority="HIGH")
    result=s.repair_unknown_refusal(original)
    assert result==original and result["refusal_reasons"] is not original["refusal_reasons"]
    for state in ("CONFIRMED_S","REJECTED_FAKE"):
        row=dict(s_decision_state=state,refusal_flag=False,refusal_reasons=[],human_review_priority="NORMAL",s_overall_prob=.91)
        assert s.repair_unknown_refusal(row)==row
    schema=dict(record_type="schema",schema_version=s.SCHEMA)
    assert s.repair_unknown_refusal(schema)==schema


def test_review_row_applies_unknown_refusal_when_no_specific_flag_exists():
    f=bars()
    f.loc[6,["open","high","low","close","vol"]]=[10.,10.65,9.9,10.5,1500.]
    d=f.iloc[-1].trade_date
    shape=s.previous.causal_shapes(f,start=d,end=d).iloc[0].to_dict()
    shape.update(feature_ready=True,tactic="UNKNOWN",positive_evidence="",counterevidence="",repair_age=-1.)
    p={"pullback":.8,"readvance":.1,"rebuild":.05,"invalid_fake":.05}
    model={"binary_hgb":{"raw_positive_probability":.9},"tactic_hgb":{"raw_tactic_probabilities":p,"argmax_tactic":"pullback"}}
    row=s.review_row(group(d),group(d)["rows"][0],f,shape,binding(),model)
    assert row["s_decision_state"]=="UNKNOWN_BORDERLINE" and row["refusal_flag"]
    assert row["refusal_reasons"]==["OUT_OF_DOMAIN"] and row["human_review_priority"]=="HIGH"
