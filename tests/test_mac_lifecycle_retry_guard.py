"""Accepted lifecycle facts: no current-bar requests, no denominator change."""
import importlib.util
import json
import struct
from pathlib import Path

import pytest
from ops import a_share_daily_sync as sync
from ops.macos_research_panel_daily_authority import _audit_sync_scope, _row_classification

B=Path('/Users/lexi/Desktop/学习/因子工厂/research/mac_lifecycle_retry_guard_20261027_r1')


def bar(day):return struct.pack('<IIIIIfII',day,1000,1100,900,1000,100000.,10000,0)


def target(root,code,dates):
    number,exchange=code.split('.');market={'SH':1,'SZ':0,'BJ':2}[exchange]
    path=root/'vipdoc'/exchange.lower()/'lday'/(exchange.lower()+number+'.day')
    path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b''.join(bar(day) for day in dates))
    return sync.DailyTarget(number,market,path)


def run(targets,tmp_path,day=20261026):
    calls=[]
    def sentinel(*args):calls.append(args);raise AssertionError('REAL_PROVIDER_FORBIDDEN')
    result=sync.run_sync(targets,target_date=str(day),api_factory=sentinel,
        host_candidates=[('sentinel.invalid',7709)],progress_path=tmp_path/'progress.json')
    return result,calls


def test_same_mechanism_all21_plus_one_normal_local_current(tmp_path):
    assert json.loads((B/'canary_601198/RESULT.json').read_text())['provider_calls']==0
    facts=sync._load_verified_lifecycle_facts();assert len(facts)==21 and '600193.SH' not in facts
    root=tmp_path/'tdx';targets=[target(root,code,[20261016]) for code in facts]
    targets.append(target(root,'300001.SZ',[20261023,20261026]))
    before={t.path:t.path.read_bytes() for t in targets};result,calls=run(targets,tmp_path)
    assert calls==[] and result['target_count']==22 and result['accepted_count']==1
    assert result['quarantine_count']==result['lifecycle_skipped_count']==21
    assert result['technical_failure_count']==0 and result['authority_status']=='REBUILD_REQUIRED'
    assert result['coverage_rate']==1/22 and result['status']=='FAILED'
    assert all(t.path.read_bytes()==before[t.path] for t in targets)
    assert all(_row_classification(r)=='QUARANTINED' for r in result['symbol_reconciliation'] if r.get('lifecycle_skip'))
    scope=_audit_sync_scope(root,20261026,[t.path for t in targets],result)
    assert scope['authority_status']=='REBUILD_REQUIRED' and scope['target_count']==22 and scope['accepted_count']==1
    # Keep all counts/results as batch evidence; no real provider/network used.
    (B/'SAME21_RESULT.json').write_text(json.dumps(dict(status='PASS_SAME21_ORIGINAL_RECONCILIATION',
        target_count=22,lifecycle_skipped_count=21,accepted_count=1,real_provider_calls=0,
        original_authority_scope=scope,coverage=result['coverage_rate']),sort_keys=True,indent=2)+'\n')


@pytest.mark.parametrize('code,day',[('601198.SH',20261016),('601059.SH',20261016),
    ('600193.SH',20261026),('300001.SZ',20261026),('601198.SZ',20261026)])
def test_effective_before_unknown_nonmember_and_market_mismatch_keep_original_route(tmp_path,code,day):
    from datetime import datetime,timedelta
    previous=int((datetime.strptime(str(day),'%Y%m%d')-timedelta(days=1)).strftime('%Y%m%d'))
    result,calls=run([target(tmp_path/'tdx',code,[previous,day])],tmp_path,day)
    assert calls==[] and result['accepted_count']==1 and result['lifecycle_skipped_count']==0
    assert result['authority_status']=='PASS'


@pytest.mark.parametrize('missing',['verified','requires_recent_listed_A_share_bars','delisting_effective_date'])
def test_local_unknown_fact_cannot_skip(missing):
    facts=sync._load_verified_lifecycle_facts();row=dict(facts['601198.SH']);row.pop(missing)
    assert sync._lifecycle_fact_for_target({'601198.SH':row},'601198',1,20261026) is None


@pytest.mark.parametrize('day',[20261019,20261026,20261027])
def test_effective_day_and_later_are_guarded(day):
    assert sync._lifecycle_fact_for_target(sync._load_verified_lifecycle_facts(),'601198',1,day) is not None


def api():
    path=Path(sync.__file__).parents[1]/'apps/api/v35_api/a_share_panel_history.py'
    spec=importlib.util.spec_from_file_location('lifecycle21_api',path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


@pytest.mark.parametrize('code',['601198.SH','601059.SH'])
def test_two_new_api_notes_preserve_error_and_no_bar(code):
    m=api();response=dict(status='CANNOT_CONFIRM',rows=[],cannot_confirm=['ORIGINAL_QUARANTINE:old-timeout'],
        ts_code=code,start_date='20261019',end_date='20261026')
    result=m._with_lifecycle_note(response)
    assert result['status']=='CANNOT_CONFIRM' and result['rows']==[]
    assert result['cannot_confirm'][0]==response['cannot_confirm'][0]
    assert '2026-10-19' in result['cannot_confirm'][1]


def test_one_existing_futu000523_envelope_unchanged():
    m=api();root=Path('/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/数据')
    expected=json.loads((B.parent/'futu_qfq76_mac_integration_20261026_r1/FINAL_API_CORE_000523.SZ.json').read_text())
    actual=m.read_history(root,'000523.SZ','20261019','20261026',m.VERSION)
    assert actual==expected
    (B/'FUTU000523_REUSE_CHECK.json').write_text(json.dumps(dict(status='PASS_UNCHANGED_FUTU000523_SAVED_ENVELOPE',
        rows=len(actual['rows']),formula_calls=0,provider_calls=0,source_kind=actual['identity']['source_kind'],
        candidate_manifest_sha256=actual['identity']['manifest_sha256']),sort_keys=True,indent=2)+'\n')
