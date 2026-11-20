"""Disabled candidate source contract; synthetic injected quotes, no live calls."""
from datetime import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

import pytest

ROOT=Path(__file__).resolve().parents[1]
OWNER=Path(os.environ.get('V4_OBSERVATION_OWNER_APP',ROOT))
if not (OWNER/'infrastructure/research_workbench_host.py').is_file():
    pytest.skip('Pin the existing observation owner dependency root',allow_module_level=True)
sys.path.insert(0,str(OWNER))
spec=importlib.util.spec_from_file_location('opend_observation_candidate',ROOT/'ops/collect_workbench_observations.py')
c=importlib.util.module_from_spec(spec);spec.loader.exec_module(c)
NOW=datetime.fromisoformat('2026-11-20T10:00:30+08:00')
DAY='2026-11-20'
IDENTITY=dict(source_date='2026-11-19',generation='a'*64,input_sha256='b'*64)
PROVIDER=dict(source='FUTU_OPEND_READ_ONLY_SNAPSHOT',api='get_market_snapshot',market='A_SHARE_SH_SZ',
              provider_timezone='Asia/Shanghai',units=dict(price='CNY',amount='CNY',volume='SHARES'))


class Frame:
    def __init__(self,records):self.records=records
    def to_json(self,**kwargs):return json.dumps(self.records)


class Quote:
    def __init__(self,change=None):self.calls=[];self.closed=False;self.change=change or (lambda rows:rows)
    def get_market_snapshot(self,codes):
        self.calls.append(codes)
        rows=[dict(code=code,update_time='2026-11-20 10:00:00',last_price=11,prev_close_price=10,turnover=11000,volume=1000) for code in codes]
        return 0,Frame(self.change(rows))
    def close(self):self.closed=True


def acceptance(tmp_path,mutate=None,freshness_change=None):
    freshness=dict(status='PASS',capture_kind='NATURAL_SESSION',samples=[dict(code='SH.600011',
        source_asof='2026-11-19T10:00:00+08:00',received_at='2026-11-19T10:00:30+08:00')],**PROVIDER)
    if freshness_change:freshness_change(freshness)
    proof=dict(schema='V4_WORKBENCH_OPEND_ACCEPTANCE_V1',status='PASS',max_age_seconds=120,
               collector_sha256=hashlib.sha256((ROOT/'ops/collect_workbench_observations.py').read_bytes()).hexdigest(),
               checks=dict(source_identity='PASS',units='PASS',intraday_freshness='PASS'),
               evidence=dict(unit_crosscheck=c.put(tmp_path/'units.json',{'test_only':'synthetic'}),
                             intraday_freshness=c.put(tmp_path/'freshness.json',freshness)),**PROVIDER,**c.FLAGS)
    if mutate:mutate(proof)
    return c.put(tmp_path/'acceptance.json',proof)


def test_exact_roster_intersection_cumulative_units_and_provider_time(tmp_path):
    ref=acceptance(tmp_path);quote=Quote()
    rows,raw=c.a_share_snapshot(DAY,['600011.SH','000039.SZ','920001.BJ'],ref,lambda:NOW,lambda:quote)
    assert quote.calls==[['SH.600011','SZ.000039']] and quote.closed
    assert [r['symbol'] for r in rows]==['600011.SH','000039.SZ','920001.BJ']
    assert rows[0]['price']==11 and rows[0]['change_percent_source']==10
    assert rows[0]['amount_source']==11000 and rows[0]['comparable_volume_shares']==1000
    assert rows[0]['source_asof']=='2026-11-20T10:00:00+08:00' and rows[0]['source_ref']==ref
    assert rows[0]['units']==PROVIDER['units'] and rows[0]['volume_rank_eligible']
    assert rows[2]['price'] is None and not rows[2]['volume_rank_eligible']
    assert raw['acceptance']==ref and len(raw['batches'])==1


@pytest.mark.parametrize('mutate',[
    lambda p:p.update(status='CANNOT_CONFIRM'),lambda p:p.update(market='HK'),
    lambda p:p.update(api='get_cur_kline'),lambda p:p.update(provider_timezone='UTC'),
    lambda p:p.update(units=dict(price='CNY',amount='CNY',volume='LOTS')),
    lambda p:p.update(collector_sha256='0'*64),lambda p:p.update(max_age_seconds=121),
    lambda p:p['checks'].update(intraday_freshness='CANNOT_CONFIRM')])
def test_unaccepted_source_never_opens_context(tmp_path,mutate):
    ref=acceptance(tmp_path,mutate)
    rows,_=c.a_share_snapshot(DAY,['600011.SH'],ref,lambda:NOW,lambda:pytest.fail('must remain disabled'))
    assert rows[0]['price'] is None and not rows[0]['volume_rank_eligible']


@pytest.mark.parametrize('change',[
    lambda f:f.update(capture_kind='MOCK'),lambda f:f.update(status='CANNOT_CONFIRM'),
    lambda f:f.update(samples=[]),lambda f:f['samples'][0].update(source_asof='2026-11-19T09:00:00+08:00'),
    lambda f:f['samples'][0].update(received_at='2026-11-21T10:00:30+08:00')])
def test_close_or_mock_or_invalid_freshness_evidence_never_enables_source(tmp_path,change):
    ref=acceptance(tmp_path,freshness_change=change)
    rows,_=c.a_share_snapshot(DAY,['600011.SH'],ref,lambda:NOW,lambda:pytest.fail('must remain disabled'))
    assert rows[0]['price'] is None


@pytest.mark.parametrize('field,value',[
    ('update_time','2026-11-19 10:00:00'),('update_time','2026-11-20 10:00:31'),
    ('update_time','2026-11-20 09:58:29'),('update_time','2026-11-20 09:25:00'),
    ('last_price',0),('prev_close_price',None),('turnover',-1),('volume',float('nan')),
    ('volume',-1),('volume',1.5),('last_price',True)])
def test_bad_provider_rows_preserve_unknown_and_close_context(tmp_path,field,value):
    ref=acceptance(tmp_path)
    quote=Quote(lambda rows:[dict(rows[0],**{field:value})])
    rows,_=c.a_share_snapshot(DAY,['600011.SH'],ref,lambda:NOW,lambda:quote)
    assert quote.closed and rows[0]['price'] is None and not rows[0]['percent_change_rank_eligible']


@pytest.mark.parametrize('change',[
    lambda rows:rows+rows,lambda rows:[dict(rows[0],code='HK.00001')],lambda rows:[]])
def test_duplicate_foreign_or_missing_return_does_not_leak_into_admitted_rows(tmp_path,change):
    quote=Quote(change)
    rows,_=c.a_share_snapshot(DAY,['600011.SH'],acceptance(tmp_path),lambda:NOW,lambda:quote)
    assert quote.closed and len(rows)==1 and rows[0]['price'] is None


def test_invalid_row_isolated_and_proof_sha_drift_blocks_before_context(tmp_path):
    ref=acceptance(tmp_path);quote=Quote(lambda rows:[dict(rows[0],volume=-1),rows[1]])
    rows,_=c.a_share_snapshot(DAY,['600011.SH','000039.SZ'],ref,lambda:NOW,lambda:quote)
    assert rows[0]['price'] is None and rows[1]['price']==11
    Path(ref['path']).write_text('{}')
    rows,_=c.a_share_snapshot(DAY,['600011.SH'],ref,lambda:NOW,lambda:pytest.fail('SHA drift'))
    assert rows[0]['price'] is None


def test_small_batches_keep_complete_roster_without_200_truncation(tmp_path):
    symbols=[f'{n:06d}.SZ' for n in range(1,222)];quote=Quote()
    rows,_=c.a_share_snapshot(DAY,symbols,acceptance(tmp_path),lambda:NOW,lambda:quote)
    assert len(rows)==221 and len(quote.calls)==5 and max(map(len,quote.calls))==50
    assert all(r['error'] is None for r in rows)


def foreign_stubs(monkeypatch):
    monkeypatch.setattr(c,'korea',lambda *a,**k:dict(indices=[dict(symbol=s,value=None) for s in ('^KS11','^KQ11')]))
    monkeypatch.setattr(c,'japan',lambda *a,**k:({'status':'TEST_ONLY'},{}))
    monkeypatch.setattr(c,'us_benchmarks',lambda *a,**k:({'status':'TEST_ONLY'},{}))


def test_default_stays_gap_and_official_close_precedes_candidate(tmp_path,monkeypatch):
    foreign_stubs(monkeypatch)
    snapshot,_,_=c.collect(DAY,'1000',IDENTITY,['600011.SH'],now=NOW,clock=lambda:NOW,
                           quote_factory=lambda:pytest.fail('default must not open quote'))
    assert 'original owner has no date-certified' in snapshot['rows'][0]['error']
    official=[dict(symbol='600011.SH',capture_kind='OFFICIAL_DAILY_ARCHIVE',error=None)]
    monkeypatch.setattr(c,'official_close',lambda *a:(official,{'official':True}))
    later=NOW.replace(hour=16)
    snapshot,_,raw=c.collect(DAY,'1640',IDENTITY,['600011.SH'],now=later,clock=lambda:later,
                            official_input={'test':True},intraday_quote_acceptance=acceptance(tmp_path),
                            quote_factory=lambda:pytest.fail('official close must take precedence'))
    assert snapshot['rows']==official and snapshot['capture_kind']=='OFFICIAL_DAILY_ARCHIVE' and raw['official']


def test_optin_snapshot_binds_daily_identity_and_old_candidate_cannot_bypass_receipt(tmp_path,monkeypatch):
    foreign_stubs(monkeypatch);quote=Quote();symbols=['600011.SH']
    snapshot,_,_=c.collect(DAY,'1000',IDENTITY,symbols,now=NOW,clock=lambda:NOW,
        quote_factory=lambda:quote,intraday_quote_acceptance=acceptance(tmp_path))
    assert snapshot['rows'][0]['error'] is None
    assert snapshot['source_generation']==IDENTITY['generation'] and snapshot['input_sha256']==IDENTITY['input_sha256']
    assert snapshot['daily_contract_sha256']==c.digest(symbols) and snapshot['analysis_admission']=='NOT_GRANTED'
    assert snapshot['capture_kind']=='FUTU_OPEND_SNAPSHOT' and snapshot['source_asof_min']=='2026-11-20T10:00:00+08:00'
    again,_,_=c.collect(DAY,'1000',IDENTITY,symbols,now=NOW,clock=lambda:NOW,prior_snapshot=snapshot,
                       quote_factory=lambda:pytest.fail('disabled source'))
    assert again['rows'][0]['price'] is None
