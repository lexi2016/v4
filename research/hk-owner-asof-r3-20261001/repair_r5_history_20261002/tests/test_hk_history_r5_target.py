"""Focused R5 HK history/as-of tests. No live provider or production writes.

Mac runs this only in an isolated composition after SHA-gating the R5 after images.
The 27/27 R4 suite is intentionally not repeated.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from stage_center import hk_universe_preflight as publisher
from ops.macos_research_panel_daily_collectors import collect_hk_futu_history_rows
from infrastructure.preselection_pool_store import _validate_hk_source_extension
from domains import preselection_materializer as projector
from infrastructure.isolated_package_loader import load_isolated_package_module

FLAGS=dict(production_allowed=False,buy_gate_updated=False,orders_sent=False)
HEX='b'*64

def qualification(source_date='20260930', *, natural=False, validity='EXACT_CAPTURE_DATE_ONLY'):
    captured=f'{source_date[:4]}-{source_date[4:6]}-{source_date[6:]}T17:20:00+08:00'
    value=dict(schema_version='v4.hk_eligibility_asof.v1',source_date=source_date,
        captured_at=captured,security_master_captured_at=captured,validity=validity,
        source_role='FUTU_HKCONNECT_PLATE_MEMBERSHIP',authority_run_id='synthetic-authority',
        security_master_run_id='synthetic-master',code_count=696,natural_verified=natural,
        **FLAGS,**{key:HEX for key in ('source_sha256','codes_sha256',
          'authority_artifact_sha256','authority_manifest_sha256','authority_receipt_sha256',
          'authority_current_sha256','security_master_artifact_sha256')})
    return value

def envelope(price='20261002',target='20261005',eligibility='20260930'):
    q=qualification(eligibility)
    return dict(schema_version='v3_5.preselection_pool.v1',trade_date=target,
        pool_id='hkconnect_d1_top100',display_name='SYNTHETIC',market='HK',
        status='STRICT_0_2_READY',producer_id='v3_shared_hk_0_2_consumer_v1',
        source_role='SHARED_VERIFIED_HK_0_2',source_path='runs/synthetic/artifact.csv',
        source_sha256='c'*64,source_manifest_sha256='d'*64,source_receipt_sha256='e'*64,
        source_run_id='synthetic-run',signal_date=price,target_date=target,
        rows=[dict(code=f'HK.{i:05d}',symbol=f'HK.{i:05d}',market='HK',
                   signal_date=price,target_date=target,selected_strategy='prob_active')
              for i in range(1,101)],
        cannot_confirm=[],stage_selection_eligible=True,
        historical_provenance=dict(schema_version='v4.hk_d1_eligibility_asof.v2',
            price_signal_date=price,eligibility_source_date=eligibility,eligibility_asof=q,
            d1_source_run_id='synthetic-run',d1_source_artifact_sha256='c'*64,
            d1_source_manifest_sha256='d'*64,d1_source_receipt_sha256='e'*64),
        **FLAGS)

def test_official_two_delta_codes_are_allowed_but_duplicates_are_not():
    assert publisher._validate_delta_codes(['HK.03228','HK.09607']) == ['HK.03228','HK.09607']
    with pytest.raises(ValueError):
        publisher._validate_delta_codes(['HK.03228','HK.03228'])



def test_manual_membership_recovery_two_deltas_self_verifies_and_stays_non_natural(tmp_path):
    parent=[f'HK.{i:05d}' for i in range(1,652)]
    delta=['HK.03228','HK.09607']
    class Frame:
        def __init__(self,codes): self.codes=codes
        def to_dict(self,*,orient):
            assert orient=='records'
            return [{'code':code} for code in self.codes]
    class Quote:
        def __init__(self,plates): self.plates=plates
        def get_plate_stock(self,plate): return 0,Frame(self.plates[plate])
        def close(self): pass
    parent_plates={plate:list(parent) for plate in publisher.HKCONNECT_PLATE_CODES}
    publisher.ensure_hk_connect_universe(
        tmp_path,'20260928',
        now=datetime(2026,9,28,17,20,tzinfo=ZoneInfo('Asia/Shanghai')),
        quote_context_factory=lambda:Quote(parent_plates),
    )
    reader=publisher._load_shared_universe_reader()
    verified_parent=reader(tmp_path,'20260928','HK_CONNECT')
    parent_sha=hashlib.sha256(verified_parent.path.read_bytes()).hexdigest()
    evidence=tmp_path/'sse-20260928.json'
    evidence.write_text(json.dumps({
      'official_url':'https://www.sse.com.cn/services/hkexsc/disclo/eligiblead/',
      'notice_date':'20260928','effective_date':'20260929','added_codes':delta,
    },sort_keys=True),encoding='utf-8')
    expected=set(parent)|set(delta)
    first=sorted(list(expected))[:350]
    second=sorted(list(expected))[350:]
    recovery_plates={
      publisher.HKCONNECT_PLATE_CODES[0]:first,
      publisher.HKCONNECT_PLATE_CODES[1]:second,
    }
    result=publisher.recover_hk_connect_universe(
      tmp_path,'20260929',parent_trade_date='20260928',
      parent_artifact_sha256=parent_sha,parent_codes_sha256=verified_parent.codes_sha256,
      official_evidence_path=evidence,
      official_evidence_sha256=hashlib.sha256(evidence.read_bytes()).hexdigest(),
      official_evidence_url='https://www.sse.com.cn/services/hkexsc/disclo/eligiblead/',
      notice_date='20260928',effective_date='20260929',delta_codes=delta,
      now=datetime(2026,10,2,9,30,tzinfo=ZoneInfo('Asia/Shanghai')),
      quote_context_factory=lambda:Quote(recovery_plates),
    )
    recovered=reader(tmp_path,'20260929','HK_CONNECT')
    payload=json.loads(recovered.path.read_text())
    assert result['natural_verified'] is False
    assert set(recovered.codes)==expected
    assert payload['captured_at'].startswith('2026-10-02')
    assert payload['recovery_lineage']['delta_codes']==delta
    package=Path(os.environ['HK_R5_SHARED_PACKAGE_ROOT'])
    sec=load_isolated_package_module(package,package_directory='shared_data',
      module_leaf='hk_security_master',namespace_prefix='hk_r5_master')
    sec.publish_hk_security_master(
      tmp_path,trade_date='20260929',
      rows=[{'code':c,'name':'SYNTHETIC '+c} for c in recovered.codes],
      universe_codes_sha256=recovered.codes_sha256,
      captured_at='2026-10-02T09:31:00+08:00',
    )
    q=sec.read_verified_hk_eligibility_asof(
      tmp_path,'20260929',universe_root=tmp_path
    )
    assert q['validity']=='OFFICIAL_EFFECTIVE_RECOVERY'
    assert q['natural_verified'] is False
    assert q['captured_at'].startswith('2026-10-02')

def test_history_reader_keeps_real_retrieval_time_and_no_historical_capture():
    codes=[f'HK.{i:05d}' for i in range(1,601)]
    names={code:f'SYNTHETIC {code}' for code in codes}
    times=iter([
        datetime(2026,10,2,1,35,47,tzinfo=timezone.utc),
        datetime(2026,10,2,1,36,10,tzinfo=timezone.utc),
    ])
    class Context:
        def close(self): pass
    class Frame:
        def __init__(self,row): self.row=row
        def to_dict(self,*,orient):
            assert orient=='records'
            return [self.row]
    def request(context,code,start,end,page):
        assert start==end=='2026-09-29' and page is None
        return 0, Frame(dict(time_key='2026-09-29 16:00:00',open=10,high=11,low=9,
                            close=10.5,volume=1000,turnover=100000)), None
    result=collect_hk_futu_history_rows('20260929',codes,names=names,
        context_factory=Context,history_request=request,now_factory=lambda:next(times))
    p=result['history_provenance']
    assert result['row_count']==600 and p['source_date']=='20260929'
    assert p['requested_at'].startswith('2026-10-02') and p['received_at'].startswith('2026-10-02')
    assert 'captured_at' not in p and p['natural_verified'] is False
    assert all(row['source']=='FUTU_HISTORY_KLINE_NONE' for row in result['rows'])

def test_r9_store_accepts_prior_connect_asof_false():
    _validate_hk_source_extension(envelope())

def test_r9_store_rejects_false_natural_claim_escalation():
    value=envelope()
    value['historical_provenance']['eligibility_asof']['natural_verified']=True
    with pytest.raises(ValueError,match='eligibility'):
        _validate_hk_source_extension(value)

def test_r9_store_accepts_manual_recovery_with_real_late_timestamp():
    value=envelope(price='20260929',target='20260930',eligibility='20260929')
    q=value['historical_provenance']['eligibility_asof']
    q.update(validity='OFFICIAL_EFFECTIVE_RECOVERY',
      captured_at='2026-10-02T09:30:00+08:00',
      security_master_captured_at='2026-10-02T09:31:00+08:00',
      recovery_lineage=dict(schema_version='v35.hk_connect.manual_recovery.lineage.v1',
        kind='MANUAL_RECOVERY',target_trade_date='20260929',natural_verified=False,
        official_evidence=dict(effective_date='20260929'),delta_codes=['HK.03228','HK.09607']))
    value['historical_provenance']['price_recovery']=dict(
      schema_version='v4.hk_history_price_recovery.v1',source_date='20260929',
      provider='FUTU_OPEND_HISTORY_KLINE',adjustment='NONE',
      requested_at='2026-10-02T01:35:47+00:00',received_at='2026-10-02T01:36:10+00:00',
      source_sha256='f'*64,natural_verified=False)
    _validate_hk_source_extension(value)

def test_projector_keeps_price_and_eligibility_dates_separate():
    price,target,eligibility='20261002','20261005','20260930'
    q=qualification(eligibility)
    rows=[dict(code_norm=f'HK.{i:05d}',name=f'SYNTHETIC {i}',rank=i,
               score_prob_active=(101-i)/101,signal_date=price,target_date=target,
               d1_freshness_status='PASS',selected_strategy='prob_active')
          for i in range(1,101)]
    verification=dict(run_id='synthetic-run',row_count=100,artifact_sha256='c'*64,
      artifact_relative=f'runs/{target}/HK_CONNECT_D1_TOP100_0_2/synthetic-run/artifact.csv',
      manifest_sha256='d'*64,receipt_sha256='e'*64)
    pool=SimpleNamespace(rows=rows,run=SimpleNamespace(verification=verification,receipt=FLAGS,
      manifest={'provenance':{'eligibility_asof_hex':
        json.dumps(q,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode().hex()}}))
    def reader(root,**kwargs):
        assert kwargs['expected_signal_date']==price
        assert kwargs['expected_eligibility_source_date']==eligibility
        return pool
    out=projector.build_shared_hk_0_2_pool(Path('/SYNTHETIC_NOT_READ'),
      trade_date=target,signal_date=price,eligibility_source_date=eligibility,reader=reader)
    p=out['historical_provenance']
    assert p['price_signal_date']==price and p['eligibility_source_date']==eligibility
    assert p['eligibility_asof']['natural_verified'] is False
