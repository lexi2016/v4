from __future__ import annotations

import inspect
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ops import pft_act020_s_v2 as s


def shape(**changes):
    row = dict(ts_code="000001.SZ", trade_date="20261119", market_type="SZ", context_valid=True,
               body_frac=.002, wick_frac=.002, range_frac=.02, volume_ratio=.7,
               volume_compression=.7, range_compression=.7, prior_volume_compression=.8,
               prior_range_compression=.8, white_slope=.001, yellow_slope=.0005,
               line_spread=.02, white_distance=.01, yellow_distance=.03,
               resistance_distance=-.03, trailing_peak_distance=-.04, prior_impulse_body=.04,
               prior_impulse_volume=2., anchor_distance=.04, anchor_age=8., repair_age=-1.,
               repair_distance=-1., anchor_date="20261109", anchor_low=10., anchor_failed=False,
               low=10.3, close=10.5, zge_white_line=10.3, zge_yellow_line=10.1,
               repair_date="", damage_date="", damage_age=-1, repair_failed=False,
               repair_high=None, prior_expansion_count=0, prior_expansion_nonbull=0,
               recent_positive=True, white_below_observations=0)
    row.update(changes)
    return row


def raw_panel(n=90, code="000001.SZ"):
    days = pd.bdate_range("2026-07-01", periods=n)
    rows=[]
    for i, day in enumerate(days):
        p=10+i*.01
        rows.append(dict(ts_code=code, trade_date=day.strftime("%Y%m%d"), market_type="SZ", open=p*.999,
                         high=p*1.01, low=p*.99, close=p, vol=1000., zge_white_line=p*.98, zge_yellow_line=p*.96))
    return pd.DataFrame(rows)


def sample_frame():
    rows=[]
    train=next(f"{i:06d}.SZ" for i in range(1,50) if s.security_group(f"{i:06d}.SZ")=="train")
    val=next(f"{i:06d}.SZ" for i in range(1,50) if s.security_group(f"{i:06d}.SZ")=="validation")
    for split,code,day in [("train",train,"20260820"),("validation",val,"20260910")]:
        for j,c in enumerate(s.CLASSES):
            r=shape(ts_code=code, trade_date=day)
            r.update({f:float(j+1)/10 for f in s.FEATURES})
            r.update(tactic=c,s_label="FALSE" if c=="invalid_fake" else "TRUE",episode_id=f"{code}:event:{j}",feature_ready=True,split=split)
            rows.append(r)
    return pd.DataFrame(rows)


class FakeModel:
    fits=0
    def fit(self,x,y):
        type(self).fits+=1
        self.classes_=np.unique(y)
        return self
    def predict_proba(self,x):
        return np.full((len(x),len(self.classes_)),1/len(self.classes_))


def test_exact_taxonomy_pullback_readvance_rebuild_fake_and_unknown():
    assert s.label_shape(shape())["tactic"]=="pullback"
    assert s.label_shape(shape(body_frac=.025,resistance_distance=.01,volume_ratio=1.4))["tactic"]=="readvance"
    rebuilt=shape(anchor_date="",anchor_age=-1.,damage_date="20261105",damage_age=10,repair_date="20261112",repair_age=3.,repair_distance=.02,repair_high=10.6)
    result=s.label_shape(rebuilt)
    assert result["tactic"]=="rebuild" and result["post_repair_consolidation"]
    fake=s.label_shape(shape(anchor_failed=True))
    assert fake["tactic"]=="invalid_fake" and "K_BREAK" in fake["counterevidence"]
    assert s.label_shape(shape(context_valid=False))["tactic"]=="UNKNOWN"


def test_conflicting_positive_and_prior_volume_fake_never_forced_into_a_class():
    r=s.label_shape(shape(prior_expansion_count=4,prior_expansion_nonbull=3))
    assert r["tactic"]=="UNKNOWN" and r["s_label"]=="UNKNOWN"
    assert r["positive_evidence"]=="pullback"
    assert r["counterevidence"]=="PRIOR_VOLUME_NONBULL_3_OF_4"


def test_fake_requires_recent_positive_and_is_not_bulk_negatives():
    for update in [dict(anchor_failed=True),dict(line_spread=.001,white_slope=.0001,yellow_slope=.0001,anchor_date="",anchor_age=-1),
                   dict(anchor_age=45),dict(volume_ratio=3,wick_frac=.04,resistance_distance=.01,body_frac=-.01)]:
        assert s.label_shape(shape(**update))["tactic"]=="invalid_fake"
        assert s.label_shape(shape(**update,recent_positive=False))["tactic"]=="UNKNOWN"
    assert s.label_shape(shape(anchor_date="",anchor_age=-1,recent_positive=False))["tactic"]=="UNKNOWN"


def test_reclaim_is_not_rebuild_and_old_repaired_damage_allows_new_pullback():
    r=shape(damage_date="20261101",damage_age=12,repair_date="20261118",repair_age=1,repair_high=10.6)
    assert s.label_shape(r)["tactic"]=="UNKNOWN"
    r.update(repair_age=3)
    assert s.label_shape(r)["tactic"]=="rebuild"
    r.update(repair_failed=True)
    assert s.label_shape(r)["tactic"]=="invalid_fake"
    r.update(repair_failed=False,repair_age=18,damage_age=30)
    assert s.label_shape(r)["tactic"]=="pullback"


def test_causal_prefix_and_future_price_mutation_and_unused_flags_are_identical():
    raw=raw_panel()
    day=raw.trade_date.iloc[75]
    a=s.causal_shapes(raw,start=day,end=raw.trade_date.iloc[-1])
    prefix=s.causal_shapes(raw.iloc[:76],start=day,end=day)
    changed=raw.copy()
    changed.loc[76:,["open","high","low","close","vol","zge_white_line","zge_yellow_line"]]=99999.
    changed["future_return"]=np.arange(len(raw))
    changed["buy"]=True
    changed["tactic"]="invalid_fake"
    b=s.causal_shapes(changed,start=day,end=day)
    pd.testing.assert_frame_equal(prefix,b)
    pd.testing.assert_series_equal(a.iloc[0],prefix.iloc[0])
    assert not any(c in b for c in ("future_return","buy"))


def test_yellow_pair_requires_consecutive_valid_bars_and_volume_nonbull_uses_previous_close():
    raw=raw_panel(75)
    # Red body but higher than prior close does not count as 阴量.
    for i in [65,67,69,71]:
        raw.loc[i,"vol"]=3000.
        raw.loc[i,"open"]=raw.loc[i,"close"]*1.002
    raw.loc[72:73,"zge_yellow_line"]=20.
    raw.loc[72,"vol"]=0.  # an invalid prior observation cannot establish a yellow pair
    out=s.causal_shapes(raw,start=raw.trade_date.iloc[71],end=raw.trade_date.iloc[74])
    assert out.iloc[0].prior_expansion_nonbull==0
    assert out.iloc[2].damage_date==""
    assert out.iloc[3].tactic=="UNKNOWN"  # invalid historical context remains unknown
    raw.loc[72,"vol"]=1000.
    out=s.causal_shapes(raw,start=raw.trade_date.iloc[73],end=raw.trade_date.iloc[73])
    assert out.iloc[0].damage_date==raw.trade_date.iloc[73]


def test_episode_dedup_security_time_and_external_exclusion():
    frame=sample_frame()
    dup=frame.copy()
    dup["trade_date"]=dup.trade_date.map({"20260820":"20260821","20260910":"20260911"})
    out=s.select_samples(pd.concat([frame,dup]),set(),validation_cap=1)
    assert len(out)==8 and not out.duplicated(["split","tactic","episode_id"]).any()
    assert not set(out.loc[out.split.eq("train"),"ts_code"]) & set(out.loc[out.split.eq("validation"),"ts_code"])
    excluded={frame.ts_code.iloc[0]}
    assert not set(s.select_samples(frame,excluded).ts_code)&excluded
    future=frame.loc[frame.split.eq("train")].copy()
    future["trade_date"]="20260901"
    assert s.select_samples(future,set()).empty


def test_four_mock_fits_fixed_order_reload_and_repeat_protection(tmp_path):
    FakeModel.fits=0
    frame=sample_frame()
    models,ledger=s.fit_four(frame,tmp_path,{"source":"synthetic"},factory=lambda _:FakeModel())
    assert FakeModel.fits==4 and ledger["S"]==4 and ledger["B"]==0
    assert list(models)==list(s.MODEL_NAMES)
    s.fit_four(frame,tmp_path,{"source":"synthetic"},factory=lambda _:FakeModel())
    assert FakeModel.fits==4
    with pytest.raises(s.ContractError,match="FIT_IDENTITY_CHANGED"):
        s.fit_four(frame,tmp_path,{"source":"changed"},factory=lambda _:FakeModel())
    saved=json.loads((tmp_path/"fit_ledger.json").read_text())
    saved["models"]["binary_lr"]["state"]="RESERVED"
    s.write_json(tmp_path/"fit_ledger.json",saved)
    with pytest.raises(s.ContractError,match="UNCERTAIN_FIT"):
        s.fit_four(frame,tmp_path,{"source":"synthetic"},factory=lambda _:FakeModel())
    assert FakeModel.fits==4


def test_predictions_threshold_argmax_fixed_classes_and_confusion(tmp_path):
    models,_=s.fit_four(sample_frame(),tmp_path,{},factory=lambda _:FakeModel())
    p=s.predict(sample_frame(),models)
    assert p.pred_binary_hgb.eq(1).all() # inclusive 0.5
    assert p.pred_tactic_hgb.eq(s.CLASSES[0]).all() # fixed argmax tie ordering
    m=s.metrics(p)
    assert np.asarray(m["binary_hgb"]["confusion_matrix"]).shape==(2,2)
    assert np.asarray(m["tactic_hgb"]["confusion_matrix"]).shape==(4,4)


def test_external_missing_dates_exact_absence_unknown_and_labels_preserved(tmp_path):
    cases=pd.DataFrame([dict(source="X",case_id=str(i),ts_code="000001.SZ",trade_date=day,s_label=lab,tactic="S14",split="validation",episode_id="old")
                        for i,day,lab in [(1,"","UNKNOWN"),(2,"20230103","TRUE"),(3,"20230104","FALSE"),(4,"20230105","EXCLUDED")]])
    path=tmp_path/"cases.csv"
    cases.to_csv(path,index=False)
    cases=s.read_external_cases(path)
    calls=[]
    def reader(panel,code,dates):
        calls.append((code,dates))
        return pd.DataFrame()
    p=s.external_inference(cases,Path("unused"),{},reader=reader)
    assert p.prediction_status.tolist()==["UNKNOWN_DATE_NO_SUBSTITUTE","EXACT_D_NOT_IN_BOUND_PANEL","EXACT_D_NOT_IN_BOUND_PANEL","EXCLUDED_BY_ADJUDICATED_REFERENCE"]
    assert p.s_label.tolist()==cases.s_label.tolist() and p.tactic.tolist()==cases.tactic.tolist()
    assert calls==[("000001.SZ",["20230103","20230104","20230105"])]


def test_static_no_full_vectorizer_no_future_b_or_flags_as_features():
    source=inspect.getsource(s)
    assert "v12._vectorize_rows(" not in source
    assert "base.build_candidates(" not in source
    forbidden=("target","label","g1","g2","flag","buy","bbi","recent_below","held","candidate","future","return")
    assert not any(any(word in f for word in forbidden) for f in s.FEATURES)
    assert set(s.INPUTS).isdisjoint({"bbi","j","b1","b2","b3","buy"})
    assert s.PRIMARY=="hgb" and len(s.MODEL_NAMES)==4


def test_factory_is_fixed_and_no_early_stopping_or_b_models():
    for name in s.MODEL_NAMES:
        model=s.model_factory(name)
        if name.endswith("hgb"):
            assert {k:model.get_params()[k] for k in s.HGB_CONFIG}==s.HGB_CONFIG
            assert model.early_stopping is False
        else:
            assert {k:model[-1].get_params()[k] for k in s.LR_CONFIG}==s.LR_CONFIG
    with pytest.raises(s.ContractError,match="UNAUTHORIZED_MODEL"):
        s.model_factory("B")


def test_failed_fit_reservation_stops_repeat_instead_of_refitting(tmp_path):
    def failure(name):
        raise RuntimeError("synthetic estimator construction failed")
    with pytest.raises(RuntimeError,match="synthetic"):
        s.fit_four(sample_frame(),tmp_path,{},factory=failure)
    receipt=json.loads((tmp_path/"fit_ledger.json").read_text())
    assert receipt["S"]==1 and receipt["models"]["binary_lr"]["state"]=="RESERVED"
    with pytest.raises(s.ContractError,match="UNCERTAIN_FIT"):
        s.fit_four(sample_frame(),tmp_path,{},factory=lambda _:FakeModel())


def test_coverage_reuses_projection_and_keeps_unknown_no_score_denominators(tmp_path,monkeypatch):
    models,_=s.fit_four(sample_frame(),tmp_path,{},factory=lambda _:FakeModel())
    projection=sample_frame().loc[lambda x:x.split.eq("validation")].copy()
    projection.loc[projection.index[0],"tactic"]="UNKNOWN"
    daily=pd.DataFrame([dict(trade_date="20260910",market_type="SZ",rows=10,unknown=4,known=6)])
    def prohibited(*a,**k):
        raise AssertionError("causal projection must not be repeated")
    monkeypatch.setattr(s,"causal_shapes",prohibited)
    result=s.oos_coverage(projection,models,{projection.ts_code.iloc[0]},daily)
    assert result.iloc[0].rows==10 and result.iloc[0].scored_rows==4 and result.iloc[0].no_score_rows==6
    assert result.iloc[0].unknown_structure_rows==1 and result.iloc[0].external_reference_rows==4


def test_synthetic_cli_pipeline_serializes_summary_and_rechecks_source(tmp_path,monkeypatch):
    from contextlib import contextmanager
    raw=raw_panel()
    called=[]
    @contextmanager
    def bind(root):
        yield Path("synthetic_panel"),{"generation_id":s.GENERATION,"asof_date":s.END},lambda:called.append("recheck")
    monkeypatch.setattr(s.v12,"bind_current_panels",bind)
    monkeypatch.setattr(s.base,"read_projected",lambda p:(raw,{"synthetic":True}))
    samples=sample_frame()
    daily=pd.DataFrame([dict(trade_date="20260910",market_type="SZ",rows=20,unknown=16,known=4)])
    monkeypatch.setattr(s,"prepare",lambda *a:(samples,daily,samples.loc[samples.split.eq("validation")]))
    real_fit=s.fit_four
    monkeypatch.setattr(s,"fit_four",lambda frame,out,ident:real_fit(frame,out,ident,factory=lambda _:FakeModel()))
    monkeypatch.setattr(s,"read_external_symbol",lambda *a:pd.DataFrame())
    monkeypatch.setattr(s,"resource_snapshot",lambda:{"threads":1})
    cases=tmp_path/"input.csv"
    pd.DataFrame([dict(source="SYNTHETIC",case_id="1",ts_code="000001.SZ",trade_date="",s_label="UNKNOWN",tactic="S14",split="validation",episode_id="external")]).to_csv(cases,index=False)
    out=tmp_path/"results"
    summary=s.run(tmp_path/"authority",out,cases)
    assert summary["actual_fit"]=={"S":4,"B":0,"tuning":0}
    assert summary["source_recheck"]=="PASS_NO_EXCEPTION" and called==["recheck"]
    assert not (out/"run.lock").exists()
    saved=json.loads((out/"summary.json").read_text())
    assert saved["external_status_counts"]=={"UNKNOWN_DATE_NO_SUBSTITUTE":1}
