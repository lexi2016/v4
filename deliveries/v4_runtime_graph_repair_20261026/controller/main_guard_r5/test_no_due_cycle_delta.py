"""Only current-minute completed NO_DUE cycle proof; no business/service work."""
from datetime import datetime as RealDateTime
from pathlib import Path
import copy
import json

import pytest
import guard_recipe as g

class FrozenDateTime(RealDateTime):
    @classmethod
    def now(cls,tz=None):return cls(2026,10,27,0,32,5,tzinfo=tz)

@pytest.fixture
def proof(tmp_path,monkeypatch):
    monkeypatch.setattr(g,'datetime',FrozenDateTime)
    app=tmp_path/'old-release'/'app';source=app/'ops/run_v35_macos_scheduler_daemon.py'
    source.parent.mkdir(parents=True);source.write_bytes(b'frozen old daemon fixture\n')
    log=tmp_path/'stdout.log'
    p={'service':'gui/501/com.lexi.v35.scheduler','guard_program':'/bin/sleep','guard_seconds':618518,
       'old_root':str(app),'old_daemon_sha256':g.sha(source.read_bytes()),'log_path':str(log)}
    reader=g.LiveOps(p)
    owner={'pid':12345,'start':'Tue Oct 27 00:12:53 2026','command':'/fixture/python -S -m ops.run_v35_macos_scheduler_daemon','identity_sha256':'owned-fixture-start'}
    reader.identity=lambda pid:copy.deepcopy(owner)
    reader.cwd=lambda pid:str(app)
    reader.service=lambda:{'pid':12345,'text':f'V35_APP_ROOT => {app}\nV35_RELEASE_ID => old-release\n'}
    flags={'production_allowed':False,'orders_sent':False,'buy_gate_updated':False}
    result={**flags,'schema_version':'v3_5.macos_scheduler_result.v1','status':'NO_DUE_SLOT','business_date':'20261027','observed_slot':'0032','release_id':'old-release'}
    cycle={**flags,'schema_version':'v3_5.macos_scheduler_daemon.v1','status':'DAEMON_CYCLE','pid':12345,'minute':'2026-10-27T00:32','result_status':'NO_DUE_SLOT','return_code':0,'release_id':'old-release'}
    def write(rows=None,ending=b'\n'):
        rows=rows or [result,cycle]
        records=[json.dumps(x,sort_keys=True).encode() if isinstance(x,dict) else x for x in rows]
        log.write_bytes(b'\n'.join(records)+ending);return records
    return reader,result,cycle,write,source,owner

def test_current_no_due_pair_has_null_run_and_two_original_record_hashes(proof):
    reader,result,cycle,write,source,owner=proof;records=write()
    def no_receipt(_):raise AssertionError('NO_DUE must not invent/read a dispatch receipt')
    reader.receipt=no_receipt
    value=reader.cycle(12345)
    assert value['ready'] and value['proof_kind']=='COMPLETED_NO_DUE_CYCLE' and value['run_id'] is None
    assert value['result_record_sha256']==g.sha(records[0]) and value['cycle_record_sha256']==g.sha(records[1])
    assert value['owner_identity']==owner and value['source_sha256']==g.sha(source.read_bytes())

@pytest.mark.parametrize('fault',['wrong_pid','stale_minute','wrong_day','wrong_slot','unpaired','nonzero','true_flag','wrong_release','incomplete'])
def test_wrong_or_unpaired_current_completion_is_not_ready(proof,fault):
    reader,result,cycle,write,source,owner=proof
    if fault=='wrong_pid':cycle['pid']=999
    if fault=='stale_minute':cycle['minute']='2026-10-27T00:31'
    if fault=='wrong_day':result['business_date']='20261026'
    if fault=='wrong_slot':result['observed_slot']='0031'
    if fault=='nonzero':cycle['return_code']=1
    if fault=='true_flag':result['production_allowed']=True
    if fault=='wrong_release':cycle['release_id']='another-release'
    if fault=='unpaired':write([result,b'not the matching output',cycle])
    elif fault=='incomplete':write(ending=b'')
    else:write()
    assert reader.cycle(12345)['ready'] is False

def test_owner_start_source_changes_refuse_no_due_proof(proof):
    reader,result,cycle,write,source,owner=proof;write()
    reader.identity=lambda pid:{**owner,'start':'Tue Oct 27 00:33:00 2026'}
    assert reader.cycle(12345)['ready'] is False
    identities=iter([copy.deepcopy(owner),{**owner,'start':'Tue Oct 27 00:13:00 2026'}])
    reader.identity=lambda pid:next(identities)
    with pytest.raises(g.StopOwned,match='OWNER_CHANGED_DURING_PROOF'):reader.cycle(12345)
    reader.identity=lambda pid:copy.deepcopy(owner)
    source.write_bytes(b'changed old daemon')
    with pytest.raises(g.StopOwned,match='OLD_DAEMON_SOURCE_CHANGED'):reader.cycle(12345)
