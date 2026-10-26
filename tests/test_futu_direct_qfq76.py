"""Frozen direct-source boundaries and unchanged original formula kernel."""
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ops import research_panel_qfq as q

B = Path('/Users/lexi/Desktop/学习/因子工厂/research/futu_qfq76_mac_integration_20261026_r1')
V = Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/local-panel-history-source-20261024-r1/app/ops/vendor')


def load(p, name):
    s = importlib.util.spec_from_file_location(name, p)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


@pytest.fixture(scope='module')
def driver():
    return q.authorities(V/'data_layer_daily_formula_increment_update_v1.py', V/'build_canonical_formula_research_panel.py')[0]


@pytest.fixture
def sample(tmp_path):
    dates = pd.bdate_range('2025-01-02', periods=475)
    dates = dates[dates <= '2026-10-26']
    dates = dates.union(pd.DatetimeIndex(['2026-10-26']))
    close = 10 + np.sin(np.arange(len(dates)) / 9) + np.arange(len(dates))/300
    frame = pd.DataFrame(dict(code='SZ.000523', name='synthetic', time_key=dates.strftime('%Y-%m-%d %H:%M:%S'),
        open=close-.03, high=close+.1, low=close-.1, close=close,
        volume=100000.+np.arange(len(dates))*17, turnover=1000000.+np.arange(len(dates))*171))
    p=tmp_path/'source.parquet';frame.to_parquet(p,index=False)
    item=dict(source=dict(path=str(p),sha256=q.sha(p)), source_kind=q.DIRECT_QFQ_KIND,
        adjustment_anchor='UNKNOWN_NONPIT',volume_basis='FUTU_SDK_NATIVE_UNSCALED',
        amount_basis='FUTU_SDK_TURNOVER_UNSCALED',history_start_date=int(dates[0].strftime('%Y%m%d')))
    return p,frame,item


def test_original_rebuild_formula_parity(sample, driver, monkeypatch):
    p,frame,item=sample
    raw=frame.rename(columns={'turnover':'amount'}).copy()
    raw['ts_code']='000523.SZ';raw['trade_date']=pd.to_datetime(raw.time_key).dt.strftime('%Y%m%d').astype(int)
    raw['vol']=raw.volume
    old=load(B/'preimages/ops/research_panel_qfq.py','old_qfq_parity')
    monkeypatch.setattr(old,'resolved_raw_history',lambda *args:raw.copy())
    monkeypatch.setattr(q,'resolved_raw_history',lambda *args:raw.copy())
    params={'history_start_date':int(raw.trade_date.min()),'events':[]}
    before=old.rebuild_symbol('000523.SZ',params,20261026,driver)
    after=q.rebuild_symbol('000523.SZ',params,20261026,driver)
    pd.testing.assert_frame_equal(before,after,check_exact=True)


def test_direct_preserves_source_and_never_adjusts(sample, driver, monkeypatch):
    p,frame,item=sample
    def forbidden(*args):raise AssertionError('SECOND_ADJUSTMENT_FORBIDDEN')
    monkeypatch.setattr(q,'apply_adjustments',forbidden)
    out=q.rebuild_direct_qfq_symbol('000523.SZ',item,20261026,driver)
    for c in ['open','high','low','close','volume']:
        np.testing.assert_array_equal(out[c],frame[c])
    np.testing.assert_array_equal(out.amount,frame.turnover)
    np.testing.assert_allclose(out.pre_close,frame.close.shift(1),equal_nan=True)
    assert out.bars_since_list.isna().all()
    assert out.source.eq(q.DIRECT_QFQ_KIND).all()
    assert out[list(q.USER_FORMULA_SIGNAL_FIELDS)].isin([0,1]).all().all()


@pytest.mark.parametrize('field,value',[('source_kind','FUTU_GET_REHAB'),('adjustment_anchor','20261026'),
    ('volume_basis','QFQ_EVENT_VOLUME'),('amount_basis','RAW_TURNOVER')])
def test_coordinate_conflicts_rejected(sample,driver,field,value):
    p,frame,item=sample;item[field]=value
    with pytest.raises(q.QfqGateError,match='COORDINATE_CONFLICT'):
        q.rebuild_direct_qfq_symbol('000523.SZ',item,20261026,driver)


@pytest.mark.parametrize('failure',['wrong_code','duplicate','future','negative_volume','bad_ohlc','source_sha'])
def test_source_conflicts_fail_closed(sample,driver,failure):
    p,frame,item=sample
    if failure=='wrong_code':frame.loc[0,'code']='SH.600030'
    if failure=='duplicate':frame.loc[1,'time_key']=frame.loc[0,'time_key']
    if failure=='future':frame.loc[len(frame)-1,'time_key']='2026-10-27 00:00:00'
    if failure=='negative_volume':frame.loc[0,'volume']=-1
    if failure=='bad_ohlc':frame.loc[0,'high']=0
    frame.to_parquet(p,index=False)
    if failure!='source_sha':item['source']['sha256']=q.sha(p)
    else:item['source']['sha256']='0'*64
    with pytest.raises((q.QfqGateError,ValueError)):
        q.rebuild_direct_qfq_symbol('000523.SZ',item,20261026,driver)


def test_api_unadmitted_symbols_keep_original_path(tmp_path):
    api=load(Path(q.__file__).parents[1]/'apps/api/v35_api/a_share_panel_history.py','api_scope')
    assert api._admitted_direct_qfq(tmp_path,tmp_path,'600000.SH','20261019','20261026') is None
    candidate=tmp_path/'candidate.json';candidate.write_text(json.dumps({'symbols':{'000523.SZ':{}}}))
    admission=dict(schema='futu_direct_qfq76_admission_v1',candidate=dict(path=str(candidate),sha256=q.sha(candidate)))
    (tmp_path/api.DIRECT_ADMISSION).write_text(json.dumps(admission))
    assert api._admitted_direct_qfq(tmp_path,tmp_path,'600000.SH','20261019','20261026') is None
    with pytest.raises(KeyError):
        api._admitted_direct_qfq(tmp_path,tmp_path,'000523.SZ','20261019','20261026')


def test_api_rejects_wrong_formula_request():
    api=load(Path(q.__file__).parents[1]/'apps/api/v35_api/a_share_panel_history.py','api_request')
    with pytest.raises(ValueError,match='formula_version'):
        api._request('000523.SZ','20261019','20261026','OTHER')


@pytest.mark.parametrize('code',['000523.SZ','600030.SH','601868.SH'])
def test_actual_candidate_matches_unchanged_web_response_contract(code):
    api=load(Path(q.__file__).parents[1]/'apps/api/v35_api/a_share_panel_history.py','api_web_contract')
    candidate=json.loads((B/'full/candidate_manifest.json').read_text())
    state=Path('/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/数据')
    result=api._direct_qfq_rows(state,candidate,code,'20261019','20261026')
    assert result['profile_id']==api.VERSION
    assert result['status']=='READY' and len(result['rows'])==6
    assert result['identity']['manifest_sha256']==q.sha(B/'full/candidate_manifest.json')
    import re
    for key in ['generation_id','input_sha256','manifest_sha256','artifact_sha256','formula_source_sha256']:
        assert re.fullmatch('[a-f0-9]{64}',result['identity'][key])
    assert result['identity']['source_kind']==q.DIRECT_QFQ_KIND
    assert result['identity']['adjustment_anchor']=='UNKNOWN_NONPIT'
    assert all(row['ts_code']==code and '20261019'<=row['trade_date']<='20261026' for row in result['rows'])


@pytest.mark.parametrize('start,end',[('20210505','20261026'),('20261019','20261027')])
def test_actual_candidate_rejects_coordinate_splice_or_future_vintage(start,end):
    api=load(Path(q.__file__).parents[1]/'apps/api/v35_api/a_share_panel_history.py','api_vintage_contract')
    candidate=json.loads((B/'full/candidate_manifest.json').read_text())
    with pytest.raises(api.Unconfirmed,match='OUTSIDE_CAPTURED_PREFIX_OR_VINTAGE'):
        api._direct_qfq_rows(B,candidate,'000523.SZ',start,end)


def test_actual_candidate_empty_weekend_keeps_original_empty_response():
    api=load(Path(q.__file__).parents[1]/'apps/api/v35_api/a_share_panel_history.py','api_empty_range')
    candidate=json.loads((B/'full/candidate_manifest.json').read_text())
    state=Path('/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/数据')
    result=api._direct_qfq_rows(state,candidate,'000523.SZ','20261024','20261025')
    assert result['status']=='EMPTY_EXACT_RANGE' and result['rows']==[]
    assert result['identity']['formula_source_sha256']==api.FORMULA_SHA
