from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ops import pft_act017_execution as study


def book_fixture(n=12,codes=("000001.SZ",)):
    dates=pd.bdate_range("2024-11-01",periods=n).strftime("%Y%m%d").tolist()
    rows=[]
    for code in codes:
        for day in dates:
            rows.append(dict(ts_code=code,trade_date=day,open=10.,high=12.,low=8.,
                             close=10.,vol=100.,pct_chg=0.,pre_close=10.,tradeable_basic=1.))
    return study.base.PriceBook.from_frame(pd.DataFrame(rows))


def test_generic_ideal_and_constrained_match_accepted_simulator():
    book=book_fixture(18,codes=("000001.SZ","920001.BJ"))
    book.values["close"][:,0]=np.linspace(10.,11.,18)
    book.values["open"][1,0]=10.6
    book.valid[8,1]=False
    signals={day:[0,1] for day in range(14)}
    for horizon in (3,5):
        for policy,prior_mode in (("I0","ideal"),("OCOST","constrained")):
            current,stats,_=study.simulate(book,signals,horizon,policy,{})
            prior,accepted=study.base.simulate(book,signals,horizon,prior_mode)
            np.testing.assert_allclose(current.nav,prior.nav,rtol=0,atol=1e-13)
            np.testing.assert_allclose(current.cash,prior.cash,rtol=0,atol=1e-13)
            assert stats["attempts"]==accepted["attempts"]
            assert stats["fills"]==accepted["fills"]
            assert stats["delayed_positions"]==accepted["delayed_positions"]


def test_matched_gap_availability_fee_bridge_closed_form():
    book=book_fixture(8,codes=("000001.SZ","000002.SZ"))
    book.values["open"][1]=[10.2,10.6]
    book.values["close"][1:]=11.
    endpoints={}
    for name in study.POLICIES:
        daily,_,_=study.simulate(book,{0:[0,1]},3,name,{})
        endpoints[name]=daily.nav.iloc[-1]-1
    expected_i0=1/3*.1
    expected_raw=(1/6)*(11/10.2-1)+(1/6)*(11/10.6-1)
    expected_filtered=(1/6)*(11/10.2-1)
    expected_cost=(1/6)*(11/10.2*(1-.0015)/(1+.0015)-1)
    assert endpoints["I0"]==pytest.approx(expected_i0)
    assert endpoints["MATCHED_D0"]==pytest.approx(expected_i0)
    assert endpoints["O0_RAW"]==pytest.approx(expected_raw)
    assert endpoints["O0_FILTERED"]==pytest.approx(expected_filtered)
    assert endpoints["OCOST"]==pytest.approx(expected_cost)
    values=study.attribution_values(endpoints)
    assert values["pure_gap_contribution"]==pytest.approx(expected_i0-expected_raw)
    assert values["fill_availability_contribution"]==pytest.approx(expected_raw-expected_filtered)
    assert values["sequential_fee_contribution"]==pytest.approx(expected_filtered-expected_cost)
    assert values["additive_residual"]==pytest.approx(0.)


def test_matched_bridge_restricts_both_to_same_missing_t1_quote_cash():
    book=book_fixture(8,codes=("000001.SZ","000002.SZ"))
    book.values["open"][1,1]=np.nan
    book.values["close"][1:]=11.
    endpoints={}
    for name in ("I0","MATCHED_D0","O0_RAW","O0_FILTERED","OCOST"):
        daily,stats,_=study.simulate(book,{0:[0,1]},3,name,{})
        endpoints[name]=daily.nav.iloc[-1]-1
        assert stats["fills"]==(2 if name=="I0" else 1)
    values=study.attribution_values(endpoints)
    assert values["fill_availability_contribution"]==pytest.approx(1/6*.1)


def test_tail_gate_uses_d_close_and_d_prior_only():
    book=book_fixture()
    book.values["close"][0,0]=10.6
    book.values["open"][0,0]=10.
    assert study.base.entry_status(book,0,0)[0]
    assert not study.tail_close_allowed(book,0,0)[0]
    book.values["close"][0,0]=10.2
    before=study.tail_close_allowed(book,0,0)
    book.values["open"][1,0]=99.
    book.values["close"][1:,0]=1.
    assert study.tail_close_allowed(book,0,0)==before
    assert before[0]


def test_targets_use_exact_execution_excess_and_negative_path_mdd():
    book=book_fixture(10,codes=("000001.SZ","000002.SZ"))
    book.values["close"][1:6,0]=[10.1,10.2,10.6,9.,9.5]
    candidates=pd.DataFrame(dict(session=[0,0],code_index=[0,1]))
    result,ledger=study.attach_targets(candidates,book)
    # A's T3 +6%, the all-A endpoint benchmark +3%, excess +3% => success.
    assert result.exec_t3_target.tolist()==[1.,0.]
    assert result.q15_target.iloc[0]==pytest.approx(9/10.6-1)
    assert result.q15_target.iloc[1]==0.
    assert ledger["exec_t3_known"]==2
    assert ledger["exec_t3_positive"]==1
    assert result.exec_t3_target_date.iloc[0]==book.dates[3]


def test_executable_label_unknown_on_entry_exit_or_missing_exact_path():
    book=book_fixture(10)
    candidates=pd.DataFrame(dict(session=[0],code_index=[0]))
    book.values["open"][1,0]=10.6
    result,_=study.attach_targets(candidates,book)
    assert result.exec_t3_target.isna().all()
    book.values["open"][1,0]=10.
    for name in ("open","high","low","close"):
        book.values[name][3,0]=9.5
    result,ledger=study.attach_targets(candidates,book)
    assert result.exec_t3_target.isna().all()
    assert any(k.startswith("exit_") for k in ledger["exec_t3_eligibility"])
    book.values["high"][3,0]=10.
    book.valid[2,0]=False
    result,_=study.attach_targets(candidates,book)
    assert result.exec_t3_target.isna().all()
    assert result.q15_target.isna().all()


def test_q15_ranks_less_negative_first_and_applies_f5_before_topk():
    candidates=pd.DataFrame(dict(trade_date=["20241101"]*3,session=[0]*3,
        ts_code=["000002.SZ","000001.SZ","000003.SZ"],code_index=[2,1,3],
        q15_score=[-.20,-.02,-.01],f5_s1_pass=[True,True,False],b_any=[False]*3))
    assert study.ranked_signals(candidates,"q15_score",1)=={0:[3]}
    assert study.ranked_signals(candidates,"q15_score",1,f5=True)=={0:[1]}


def test_quarter_maturity_boundary_and_train_group_purge():
    candidates=pd.DataFrame(dict(trade_date=["20240701","20240926","20240925","20241101"],
        ts_code=["000001.SZ"]*4,_anchor_date=["shared","","","shared"],
        rebuild_episode_id=[""]*4,q15_target=[-.1]*4,
        q15_target_date=["20240708","20241001","20240930","20241108"]))
    train,predict,report=study.quarter_masks(candidates,"2024Q4","q15_target")
    assert train.tolist()==[False,False,True,False]
    assert predict.tolist()==[False,False,False,True]
    assert report["purged_rows"]==1
    assert report["latest_train_target"]=="20240930"


def test_lot_meltdown_denominator_excludes_delayed_and_residual():
    book=book_fixture(8,codes=("000001.SZ","000002.SZ","000003.SZ"))
    book.values["close"][3:,0]=8.
    book.valid[3,1]=False  # delayed but eventually closes, excluded from exact denom
    book.valid[3:,2]=False  # residual, also excluded
    _,stats,lots=study.simulate(book,{0:[0,1,2]},3,"OCOST",{book.dates[0]:"bull"})
    all_lots=next(x for x in lots if x["signal_regime"]=="ALL")
    bull=next(x for x in lots if x["signal_regime"]=="bull")
    assert all_lots["scheduled_exit_denominator"]==1
    assert all_lots["net_loss_below_minus10"]==1
    assert all_lots["net_loss_below_minus10_rate"]==1.
    assert all_lots["delayed_positions"]==2
    assert all_lots["unclosed_positions"]==1
    assert stats["residual_positions"]==1
    assert bull["scheduled_exit_denominator"]==1


class FixedRegressor:
    calls=0
    def fit(self,x,y):
        type(self).calls+=1
        assert (y<=0).all()
        return self
    def predict(self,x):
        return np.full(len(x),-.05)


class FixedClassifier:
    calls=0
    def fit(self,x,y,sample_weight):
        type(self).calls+=1
        assert sample_weight[y==0].sum()==pytest.approx(sample_weight[y==1].sum())
        return self
    def predict_proba(self,x):
        return np.column_stack([np.full(len(x),.4),np.full(len(x),.6)])


def model_fixture():
    rows=[]
    quarters=[f"{year}Q{q}" for year in (2023,2024,2025,2026) for q in (1,2,3,4)
              if f"{year}Q{q}">="2023Q4"]
    for q in quarters:
        day="20241101" if q=="2024Q4" else study.base.quarter_start(q)
        target=pd.bdate_range(day,periods=6)[-1].strftime("%Y%m%d")
        for i in (0,1):
            rows.append({**{name:float(i) for name in study.FEATURES},"trade_date":day,
                "ts_code":f"00000{i+1}.SZ","_anchor_date":"","rebuild_episode_id":"",
                "q15_target":-.1-i*.1,"q15_target_date":target,
                "exec_t3_target":float(i),"exec_t3_target_date":target,"b_any":False})
    return pd.DataFrame(rows)


def test_exact_18_fits_hard_pool_without_b_and_checkpoint_resume(tmp_path):
    FixedRegressor.calls=FixedClassifier.calls=0
    factory=lambda kind:FixedRegressor() if kind=="q15" else FixedClassifier()
    candidates=model_fixture()
    first,report=study.fit_models(candidates,{"synthetic":"binding"},tmp_path,estimator_factory=factory)
    assert report["actual_fits"]==18 and report["reused"]==0
    assert FixedRegressor.calls==9 and FixedClassifier.calls==9
    assert first.q15_score.notna().sum()==18
    files={p.name:p.read_bytes() for p in tmp_path.glob("*.joblib")}
    second,replayed=study.fit_models(candidates,{"synthetic":"binding"},tmp_path,resume=True,estimator_factory=factory)
    assert replayed["actual_fits"]==0 and replayed["reused"]==18
    assert FixedRegressor.calls==9 and FixedClassifier.calls==9
    pd.testing.assert_series_equal(first.q15_score,second.q15_score)
    assert files=={p.name:p.read_bytes() for p in tmp_path.glob("*.joblib")}
    with pytest.raises(study.Act017Error,match="CHECKPOINT_CONTRACT_MISMATCH"):
        study.fit_models(candidates,{"synthetic":"different"},tmp_path,resume=True,estimator_factory=factory)


def test_f5_reuses_signed_weak_endpoint_rank():
    counts=pd.Series([1]*39+[1])
    assert study.base.f5_s1(counts).iloc[-1]==1.
