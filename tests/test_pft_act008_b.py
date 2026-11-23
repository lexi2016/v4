from __future__ import annotations

import json
import numpy as np
import pandas as pd
import pytest

from ops.pft_act008_b_features import BASE_FEATURES, FULL_FEATURES, b_frame, frozen_s_gate
from ops.pft_act008_b import _scan_one, _selected_one, select, rank


def history(count=90):
    h=pd.DataFrame({'trade_date':pd.bdate_range('2025-01-01',periods=count).strftime('%Y%m%d'),
        'ts_code':'000001.SZ','open':10.,'high':10.2,'low':9.8,'close':10.,'vol':100.,
        'bbi':10.1,'zge_white_line':9.9,'zge_yellow_line':9.5,
        'kdj_k':20.,'kdj_d':23.,'kdj_j':14.,'tradeable_basic':1,
        'user_v1_B1':0,'user_v1_B2':0,'user_v1_B3':0})
    return h


def test_feature_allowlist_has_no_label_bool_identity_or_S_in_baseline():
    assert not any('label' in n or 'original' in n or n.startswith('S_') for n in BASE_FEATURES)
    assert FULL_FEATURES[:len(BASE_FEATURES)]==BASE_FEATURES
    assert len(set(FULL_FEATURES))==len(FULL_FEATURES)


def test_prefix_invariance_and_future_changes():
    h=history(); a=b_frame(h.iloc[:75])
    h.loc[75:,'close']=99.;h.loc[75:,'kdj_j']=-999.
    b=b_frame(h)
    pd.testing.assert_frame_equal(a,b.iloc[:75].reset_index(drop=True))


def test_nan_original_and_indicator_stay_unknown_and_are_not_accepted():
    h=history();h.loc[89,'kdj_j']=np.nan;h.loc[88,'user_v1_B1']=np.nan
    f=b_frame(h)
    assert pd.isna(f.loc[89,'B1_recomputed']) and pd.isna(f.loc[89,'B1_label'])
    assert pd.isna(f.loc[88,'B1_label'])
    assert not f.loc[89,'eligible']


def test_b1_weak_positive_can_exist_without_original_trigger():
    h=history();h.loc[89,'vol']=80.
    f=b_frame(h).iloc[-1]
    assert f.B1_recomputed==0 and f.B1_label==1
    h.loc[89,'close']=9.3;h.loc[89,'low']=9.2
    assert b_frame(h).iloc[-1].B1_label==0


def test_original_formula_boundaries_use_strict_user_F03():
    h=history();h.loc[87,'kdj_j']=12.;h.loc[89,['close','high','vol']]=[10.4,10.5,125.]
    f=b_frame(h).iloc[-1]
    assert f.B2_recomputed==0  # volume must exceed 1.25, not equal
    h.loc[89,['close','high','vol']]=[10.5,10.6,126.]
    assert b_frame(h).iloc[-1].B2_recomputed==1
    assert b_frame(h).iloc[-1].B2_formula_mismatch


def test_1006_and_151_full_classification_stay_unknown():
    f=b_frame(history()).iloc[-1]
    assert f.B2_1006_full=='UNKNOWN' and f.B2_151_full=='UNKNOWN'
    assert 'B2_1006_r_ge4' not in BASE_FEATURES


def test_frozen_gate_drops_only_unconditional_35():
    row=dict(wy_spread_pct=2,c_vs_yellow_pct=40,d_upper_shadow_pct=1,d_vr5=1,dd_from_pk30_pct=-5,d_amp_pct=4)
    assert frozen_s_gate(row)==(1.,'PASS')
    row.update(d_upper_shadow_pct=4,d_vr5=1.5)
    assert frozen_s_gate(row)==(0.,'G2_DISTRIBUTION_GE_25')
    row.update(c_vs_yellow_pct=0,dd_from_pk30_pct=-22,d_amp_pct=8)
    assert frozen_s_gate(row)==(0.,'G2_DRAWDOWN_RANGE')
    row['wy_spread_pct']=np.nan
    assert np.isnan(frozen_s_gate(row)[0])


def test_sampling_is_deterministic_one_stock_per_lane_and_reports_shortages():
    rows=[]
    for code,label,stratum in [('000001.SZ',1,'POSITIVE'),('000001.SZ',0,'HARD_ORIGINAL_ADVERSE'),('000002.SZ',0,'NEAR_MISS_ADVERSE')]:
        rows.append(dict(canonical_security_id=code,lane='B1',split='TRAIN',label=label,stratum=stratum,D='20250101',rank_hash=rank('B1','TRAIN',stratum,code,'20250101')))
    a,counts=select(rows,'B1','TRAIN',2,2)
    b,_=select(list(reversed(rows)),'B1','TRAIN',2,2)
    assert a==b and len({r['canonical_security_id'] for r in a})==len(a)
    assert counts['shortage_positive']==1 and counts['shortage_negative']==1


def test_selected_matrices_are_numeric_and_json_serializable_without_future():
    h=history();rows=h.to_dict('records');d=rows[74]['trade_date']
    out=_selected_one(('000001.SZ',{'000001.SZ':rows},[{'D':d}],[]))[0]
    assert out['D']==d
    json.dumps(out,allow_nan=False)
    assert list(out['base'])==list(BASE_FEATURES)
    for value in out['base'].values(): assert value=='' or np.isfinite(value)
    assert not out['gate']['prior_anchor_date'] or out['gate']['prior_anchor_date']<d


def test_missing_previous_open_does_not_erase_B3_conflict_into_negative():
    h=history();h.loc[87,'kdj_j']=10.
    h.loc[88,['open','high','low','close','vol']]=[10.0,10.7,10.0,10.5,140.]
    h.loc[89,['open','high','low','close','vol']]=[10.5,10.6,9.7,10.4,100.]
    # Current low proves adverse; all positive operands must still be known.
    h.loc[88,'open']=np.nan
    assert pd.isna(b_frame(h).iloc[-1].B3_label)


def test_missing_B2_five_bar_J_or_peak_high_stays_unknown():
    h=history();h.loc[87,'kdj_j']=12.
    h.loc[89,['close','high','vol','user_v1_B2']]=[10.5,11.1,140.,1]
    h.loc[85,'kdj_j']=np.nan
    assert pd.isna(b_frame(h).iloc[-1].B2_label)
    h.loc[85,'kdj_j']=14.;h.loc[70,'high']=np.nan
    assert pd.isna(b_frame(h).iloc[-1].B2_label)


def test_s_fold_alias_canonical_group_and_gated_unknown():
    from ops.pft_act008_b_fit import fold_for,gated
    assert fold_for('000001.SZ')==fold_for('000001.SZ')
    values=gated([.9,.8,.7],[{'gate':1},{'gate':0},{'gate':''}])
    assert values[:2]==[.9,0.] and np.isnan(values[2])


def test_matrix_rejects_schema_inf_but_accepts_numeric_nan(tmp_path):
    from ops.pft_act008_b_fit import matrix
    path=tmp_path/'x.csv'
    pd.DataFrame({'a':[np.nan,1.]}).to_csv(path,index=False)
    assert pd.isna(matrix(path,['a']).iloc[0,0])
    with pytest.raises(Exception,match='SCHEMA'):matrix(path,['label'])
    pd.DataFrame({'a':[np.inf]}).to_csv(path,index=False)
    with pytest.raises(Exception,match='INFINITY'):matrix(path,['a'])


def test_calendar_outcomes_do_not_compress_missing_or_halted_and_drawdown_uses_running_peak():
    from ops.pft_act008_b_score import outcome
    sessions=['20260105','20260106','20260107','20260108','20260109','20260112']
    case={'D':sessions[0],'episode_id':'x'}
    bars={d:{'open':10.,'close':c,'vol':100.,'tradeable_basic':1} for d,c in zip(sessions[1:],[12.,11.,13.,12.,11.])}
    row=outcome(case,bars,sessions,5,'20260112')
    assert row['return_pct']==pytest.approx(10.)
    assert row['running_close_drawdown_pct']==pytest.approx((11/13-1)*100)
    missing=dict(bars);del missing[sessions[1]]
    assert outcome(case,missing,sessions,5,'20260112')['status']=='MISSING_SCHEDULED_BAR'
    bars[sessions[2]]['vol']=0
    assert outcome(case,bars,sessions,5,'20260112')['status']=='HALTED_OR_UNTRADEABLE'
    assert outcome(case,bars,sessions,5,'20260109')['status']=='RIGHT_CENSORED'


class SyntheticEstimator:
    """Serialization/lock oracle only: no statistical estimator is fitted."""
    classes_=np.array([0,1])
    def __init__(self,features=None):self.feature_names_in_=list(features or [])
    def fit(self,x,y):self.feature_names_in_=list(x.columns);return self
    def predict_proba(self,x):
        p=np.array([.25 if i%2==0 else .75 for i in range(len(x))])
        return np.column_stack([1-p,p])


def test_synthetic_fit_seal_score_serialization_and_no_prelock_truth_reads(tmp_path,monkeypatch):
    import joblib
    from ops import pft_act008_b_fit as fit
    from ops import pft_act008_b_score as score
    from ops import pft_s_full_ashare as old
    from ops import pft_s_full_ashare_fit as oldfit
    from ops.pft_act008_b import _write_rows,write_json,FLAGS
    from ops.pft_act008_b_features import BRANCH_FEATURES,LANES
    from ops.pft_s_full_ashare_features import FEATURES as SF
    artifact=tmp_path/'artifact';artifact.mkdir();prepared=artifact/'prepared';prepared.mkdir()
    sroot=tmp_path/'act005';(sroot/'prepared').mkdir(parents=True);(sroot/'fit_v1').mkdir()
    scodes=[f'{200000+i:06d}.SZ' for i in range(450)]
    sr=[{'canonical_security_id':c,'D':'20250101','split':'TRAIN','label':'TRUE' if i<180 else 'FALSE'} for i,c in enumerate(scodes)]
    _write_rows(sroot/'prepared/train_manifest.csv',sr)
    _write_rows(sroot/'prepared/train_features.csv',[{n:1. for n in SF} for _ in sr],SF)
    write_json(sroot/'fit_v1/prediction_lock.json',{'fixture':'synthetic'})
    saved=sroot/'fit_v1/model_lr.joblib';joblib.dump(SyntheticEstimator(SF),saved)
    config={'primary_for_B':'GEMINI_R2_FIXED_LR','feature_columns':list(SF),'model_configs':oldfit.MODEL_CONFIGS,
        'threshold':.5,'G2_remove':'G2_CLOSE_YELLOW_GE_35','weights':{'GEMINI_R2_FIXED_LR':{'file':str(saved),'sha256':old._sha_file(saved)}},
        'train_manifest_sha256':old._sha_file(sroot/'prepared/train_manifest.csv'),'train_features_sha256':old._sha_file(sroot/'prepared/train_features.csv'),
        'source_prediction_lock_sha256':old._sha_file(sroot/'fit_v1/prediction_lock.json')}
    write_json(artifact/'S_FROZEN_V1_inference.json',config);write_json(artifact/'scope_frozen.json',{})
    (artifact/'WRITER_SCOPE.md').write_text('synthetic test only')
    aliases={c:c for c in scodes};partitions={c:'TRAIN' for c in scodes}
    for lane in LANES:
        for split,codes in [('train',['001001.SZ','001002.SZ']),('oos',['600001.SH','600002.SH'])]:
            key=f'{lane}_{split}'
            ids=[{'episode_id':f'{key}_{i}','canonical_security_id':c,'D':'20250106' if split=='train' else '20260105','lane':lane,'split':split.upper()} for i,c in enumerate(codes)]
            _write_rows(prepared/f'{key}_identity.csv',ids)
            _write_rows(prepared/f'{key}_labels.csv',[{**r,'label':i,'original':1,'reason':'INDEPENDENT','stratum':'POSITIVE' if i else 'HARD_ORIGINAL_ADVERSE'} for i,r in enumerate(ids)])
            _write_rows(prepared/f'{key}_diagnostics.csv',[{'forbidden_truth':1} for r in ids])
            for c in codes:aliases[c]=c;partitions[c]=split.upper()
    kb_ids=[{'case_id':f'CASE_{i:02d}','canonical_security_id':f'{300000+i:06d}.SZ','security_id':f'{300000+i:06d}.SZ','D':'20250106','split':'EXPOSED_KB','B_human_gold':'UNKNOWN'} for i in range(25)]
    _write_rows(prepared/'kb_identity.csv',kb_ids)
    _write_rows(prepared/'kb_diagnostics.csv',[{f'{lane}_{suffix}':value for lane in LANES for suffix,value in [('label',''),('reason','UNKNOWN'),('original',0)]} for _ in kb_ids])
    for key in [f'{l}_{s}' for l in LANES for s in ('train','oos')]+['kb']:
        count=25 if key=='kb' else 2
        _write_rows(prepared/f'{key}_base.csv',[{n:1. for n in BASE_FEATURES} for _ in range(count)],BASE_FEATURES)
        _write_rows(prepared/f'{key}_branches.csv',[{f'S_{n}':1. for n in BRANCH_FEATURES} for _ in range(count)],[f'S_{n}' for n in BRANCH_FEATURES])
        _write_rows(prepared/f'{key}_s.csv',[{n:1. for n in SF} for _ in range(count)],SF)
        _write_rows(prepared/f'{key}_gates.csv',[{'gate':1,'gate_reason':'PASS','prior_anchor_date':''} for _ in range(count)])
    manifest={'batch':'ACT-008','flags':FLAGS,'base_features':list(BASE_FEATURES),'branch_features':[f'S_{n}' for n in BRANCH_FEATURES],'s_features':list(SF),
        'input_sha256':{n:old._sha_file(artifact/n) for n in ['S_FROZEN_V1_inference.json','scope_frozen.json','WRITER_SCOPE.md']},
        'outputs_sha256':{p.name:old._sha_file(p) for p in prepared.iterdir()}}
    write_json(prepared/'manifest.json',manifest)
    monkeypatch.setattr(old,'_validate_inputs',lambda _:dict(input_sha256={},aliases=aliases,canonical_partition=partitions,excluded_canonical=set()))
    monkeypatch.setattr(oldfit,'_fixed_models',lambda :{n:SyntheticEstimator() for n in oldfit.MODEL_CONFIGS})
    original_read=oldfit._read_csv;blocked=[]
    def guarded(path):
        if '_oos_labels' in path.name or '_oos_diagnostics' in path.name:
            blocked.append(path.name);raise AssertionError('prelock OOS truth opened')
        return original_read(path)
    monkeypatch.setattr(oldfit,'_read_csv',guarded)
    fitted=artifact/'fit'
    result=fit.fit_and_lock(prepared_dir=prepared,artifact_root=artifact,act005_root=sroot,output_dir=fitted)
    assert result['B_fits']==12 and result['S_helper_fits']==5 and not blocked
    audit=json.loads((fitted/'S_crossfit_audit.json').read_text())
    for f in audit['folds']:
        assert not set(f['S_train_canonical'])&set(f['B_query_canonical'])
        assert all(fit.fold_for(c)!=f['fold'] for c in f['S_train_canonical'])
    monkeypatch.setattr(oldfit,'_read_csv',original_read)
    # All post-D access is mocked, and score must verify the lock first.
    reads=[]
    def outcome_bars(*args):
        reads.append('post-lock')
        return {},{'fixture':'synthetic no panel read'}
    monkeypatch.setattr(score,'_read_outcome_bars',outcome_bars)
    scored=score.score(prepared_dir=prepared,fit_dir=fitted,data_root=artifact,act005_root=sroot,output_dir=artifact/'score')
    assert reads==['post-lock'] and scored['KB_prediction_rows']==300 and scored['OOS_prediction_rows']==24
    (fitted/'predictions.csv').write_text('tampered')
    with pytest.raises(Exception,match='SHA_MISMATCH'):
        score.score(prepared_dir=prepared,fit_dir=fitted,data_root=artifact,act005_root=sroot,output_dir=artifact/'score_tamper')
    assert reads==['post-lock']
