from datetime import date,timedelta
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
import pandas as pd
from ops.materialize_workbench_score_action import target_kb,project_symbol,authority_identity,digest,save
from ops.kb_signal_authority import append_kb_signals
from ops.kb_action_authority import project_action
from infrastructure.research_workbench_score_action import read_score_action


def bars(n=180):
    rows=[]
    for i in range(n):
        close=20+i*.01+(i%17)*.07
        rows.append(dict(ts_code='002047.SZ',trade_date=(date(2025,1,1)+timedelta(days=i)).strftime('%Y%m%d'),open=close-.1,high=close+.3,low=close-.3,close=close,volume=10000+i*30,pre_close=close-.05,pct_chg=.2,user_v1_sell_signal_daily=1.0 if i==n-1 else 0.0))
    return rows


@pytest.mark.parametrize('missing',['none','negative_qfq','missing_hlc','zero_volume'])
def test_target_matches_untrimmed_authority(missing):
    rows=bars()
    if missing=='negative_qfq':
        for r in rows:
            for k in ('open','high','low','close','pre_close'):r[k]-=40
    elif missing=='missing_hlc':rows[30]['high']=float('nan')
    elif missing=='zero_volume':rows[-1]['volume']=0
    f=pd.DataFrame(rows).rename(columns={'volume':'vol'})
    # Oracle is the preserved full original function, never the target adapter.
    expected=append_kb_signals(f)
    chosen=[int(rows[8]['trade_date']),int(rows[115]['trade_date']),int(rows[-1]['trade_date'])]
    actual=target_kb(f,chosen)
    fields=[c for c in expected.columns if c.startswith('kb_')]
    for day in chosen:
        i=next(i for i,r in enumerate(rows) if int(r['trade_date'])==day)
        for k in fields:
            a,b=actual.iloc[i][k],expected.iloc[i][k]
            assert (pd.isna(a) and pd.isna(b)) or a==b,(missing,day,k,a,b)


def test_corrected_float_sell_and_unknown_are_preserved():
    base=dict(kb_hold_score=4,kb_hold_score_min=4,kb_hold_score_max=4,
        kb_bull_rope_status='牵牛',kb_brick_action='持有',kb_macd_veto=False,kb_white_cross_down=False,
        kb_b1=False,kb_b2=False,kb_b3=False)
    for sell in [True,1,1.0]:
        out=project_action(base|{'user_v1_sell_signal_daily':sell})
        assert out['kb_action_with_position_status']=='CONFLICTING_OBSERVATIONS'
    unknown=project_action({})
    assert unknown['kb_action_with_position'] is None
    assert unknown['kb_action_no_position'] is None


def test_stock_cache_and_earlier_asof_do_not_read_future(tmp_path):
    rows=bars();rules=authority_identity();target=rows[-1]['trade_date'];basis={'price_basis':'QFQ_ASOF'}
    args=('002047.SZ',rows,target,basis,str(tmp_path),rules,{'status':'CURRENT_PRODUCER_ACCEPTED_FOR_REQUESTED_RESEARCH'})
    first=project_symbol(args);second=project_symbol(args)
    assert second['reused'] and first['record']==second['record']
    earlier=project_symbol((args[0],rows[:-1],rows[-2]['trade_date'],*args[3:]))
    assert not earlier['reused'] and earlier['record']['trade_date']!=target
    assert earlier['record']['cache_identity']['prefix_sha256']==digest(rows[:-1])
    assert first['record']['n_structure']['rule_sha256']==rules['a_share_kb_n_structure_v1.json']


def test_reader_rejects_other_day_generation_and_digest(tmp_path):
    rules=authority_identity();basis={'price_basis':'QFQ_ASOF'};row=project_symbol(('002047.SZ',bars(),'20250629',basis,str(tmp_path),rules,{'status':'CURRENT_PRODUCER_ACCEPTED_FOR_REQUESTED_RESEARCH'}))['record']
    rr=save(tmp_path/'records',row);manifest={'path':'/numeric','sha256':'a'*64}
    flags=dict(RESEARCH_ONLY=True,production_allowed=False,buy_gate_updated=False,orders_sent=False)
    ident=dict(data_date='20250629',source_generation='b'*64,input_sha256='c'*64,numeric_manifest=manifest)
    ix=dict(schema='v4.workbench.daily_score_action.v1',historical_PIT=False,source_selector_sha256='d'*64,items={'002047.SZ':rr},rules=rules,price_basis=basis,**ident,**flags)
    descriptor=dict(index=save(tmp_path/'indexes',ix),**ident)
    product=dict(source_generation='b'*64,source_identity={'input_sha256':'c'*64,'selector_artifact_sha256':'d'*64},manifest=manifest)
    assert read_score_action(tmp_path,descriptor,product,'2025-06-29','002047.SZ')['status']=='MATERIALIZED'
    assert read_score_action(tmp_path,descriptor,product,'2025-06-29','300856.SZ')['status']=='UNKNOWN'
    with pytest.raises(ValueError,match='IDENTITY'):
        read_score_action(tmp_path,descriptor,product,'2025-06-30','002047.SZ')
    Path(rr['path']).write_text('{}')
    with pytest.raises(ValueError,match='SHA'):
        read_score_action(tmp_path,descriptor,product,'2025-06-29','002047.SZ')


def test_next_day_resumes_only_new_score_and_n_observation(tmp_path):
    rules=authority_identity();rows=bars();basis={'price_basis':'QFQ_ASOF'}
    old=project_symbol(('002047.SZ',rows[:-1],rows[-2]['trade_date'],basis,str(tmp_path),rules,{'status':'CURRENT_PRODUCER_ACCEPTED_FOR_REQUESTED_RESEARCH'}))
    new=project_symbol(('002047.SZ',rows,rows[-1]['trade_date'],basis,str(tmp_path),rules,{'status':'CURRENT_PRODUCER_ACCEPTED_FOR_REQUESTED_RESEARCH'}))
    fresh=project_symbol(('002047.SZ',rows,rows[-1]['trade_date'],basis,str(tmp_path/'fresh'),rules,{'status':'CURRENT_PRODUCER_ACCEPTED_FOR_REQUESTED_RESEARCH'}))
    assert new['record']['incremental_prefix_rows']==179
    assert new['record']['new_observation_rows']==1
    for field in ['hold_score','action','kb']:
        assert new['record'][field]==fresh['record'][field],field
    for field in ['state','structure_known_at','L1','H1','L2','H2']:
        assert new['record']['n_structure'].get(field)==fresh['record']['n_structure'].get(field)


def qualification_args(root,qualification):
    rows=bars()
    return ('002047.SZ',rows,rows[-1]['trade_date'],{'price_basis':'QFQ_ASOF'},str(root),authority_identity(),qualification)


def test_qualification_accepted_to_unknown_never_reuses_score(tmp_path):
    accepted={'status':'CURRENT_PRODUCER_ACCEPTED_FOR_REQUESTED_RESEARCH','accepted_evidence':[{'path':'/receipt','sha256':'a'*64}]}
    first=project_symbol(qualification_args(tmp_path,accepted))
    assert first['record']['status']=='MATERIALIZED'
    rejected=project_symbol(qualification_args(tmp_path,{'status':'CANNOT_CONFIRM','reason':'ADMISSION_REVOKED'}))
    assert not rejected['reused']
    assert rejected['record']['status']=='UNKNOWN'
    assert rejected['record']['reason']=='ADMISSION_REVOKED'
    assert rejected['record']['hold_score'] is None and rejected['record']['action'] is None


def test_qualification_unknown_to_accepted_recovers_same_prices(tmp_path):
    unknown=project_symbol(qualification_args(tmp_path,{'status':'UNKNOWN','reason':'RECEIPT_NOT_BOUND'}))
    assert unknown['record']['status']=='UNKNOWN'
    accepted={'status':'CURRENT_PRODUCER_ACCEPTED_FOR_REQUESTED_RESEARCH','accepted_evidence':[{'path':'/receipt','sha256':'a'*64}]}
    recovered=project_symbol(qualification_args(tmp_path,accepted))
    assert not recovered['reused'] and recovered['record']['status']=='MATERIALIZED'
    assert recovered['record']['hold_score'] is not None and recovered['record']['action'] is not None
    same=project_symbol(qualification_args(tmp_path,dict(reversed(list(accepted.items())))))
    assert same['reused'] and same['record']==recovered['record']


def test_qualification_reason_or_evidence_changes_invalidate_same_prices(tmp_path):
    base={'status':'CURRENT_PRODUCER_ACCEPTED_FOR_REQUESTED_RESEARCH','reason':None,
          'accepted_evidence':[{'path':'/receipt','sha256':'a'*64}]}
    initial=project_symbol(qualification_args(tmp_path,base))
    for changed in [dict(base,reason='REVIEW_RECONFIRMED'),
                    dict(base,accepted_evidence=[{'path':'/receipt','sha256':'b'*64}])]:
        result=project_symbol(qualification_args(tmp_path,changed))
        assert not result['reused']
        assert result['record']['cache_identity']['qualification']!=initial['record']['cache_identity']['qualification']
        assert result['record']['cache_identity']['prefix_sha256']==initial['record']['cache_identity']['prefix_sha256']
        stable=project_symbol(qualification_args(tmp_path,changed))
        assert stable['reused'] and stable['record']==result['record']
