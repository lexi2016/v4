from contextlib import nullcontext
import json
import plistlib

import pytest
from ops import f10_main_release as op


@pytest.fixture
def environment(tmp_path, monkeypatch):
    target=tmp_path/'candidate';config=target/'config';config.mkdir(parents=True)
    old=plistlib.dumps({'EnvironmentVariables':{'V4_APP_ROOT':'/before'}})
    new=plistlib.dumps({'EnvironmentVariables':{'V4_APP_ROOT':'/after'}})
    (config/'before.plist').write_bytes(old);(config/'candidate.plist').write_bytes(new)
    live=tmp_path/'live.plist';live.write_bytes(old)
    old_process={'pid':1,'root':'/before'};new_process={'pid':2,'root':'/after'};state={'process':old_process,'unloads':0,'bootstraps':[]}
    receipt={'base_process':old_process,'candidate_plist_sha256':op.sha(new),'manifest':{'sha256':'a'*64}}
    monkeypatch.setattr(op,'target',lambda:target);monkeypatch.setattr(op,'PLIST',live);monkeypatch.setattr(op,'BASE_PLIST_SHA',op.sha(old))
    monkeypatch.setattr(op,'locks',lambda:nullcontext());monkeypatch.setattr(op,'verify',lambda _:receipt)
    monkeypatch.setattr(op,'service_state',lambda:state['process']);monkeypatch.setattr(op,'require_idle',lambda *_:None)
    monkeypatch.setattr(op,'atomic_plist',lambda raw:live.write_bytes(raw))
    def bootstrap(root,tracking=None):
        process=old_process if str(root)=='/before' else new_process;state['process']=process;state['bootstraps'].append(str(root))
        if tracking:tracking(process)
        return process
    monkeypatch.setattr(op,'bootstrap',bootstrap)
    return target,live,old,new,old_process,new_process,state,receipt


def test_unload_timeout_after_stop_restores_previous_service(environment,monkeypatch):
    _,live,old,_,old_process,_,state,_=environment
    def unload():
        state['unloads']+=1;state['process']=None
        raise RuntimeError('MAIN_UNLOAD_TIMEOUT')
    monkeypatch.setattr(op,'unload',unload)
    with pytest.raises(RuntimeError,match='RECOVERY_VERIFIED'):
        op.switch('receipt','unused','unused')
    assert live.read_bytes()==old and state['process']==old_process and state['bootstraps']==['/before']


def test_process_drift_before_bootout_is_rejected_without_unload(environment,monkeypatch):
    _,_,_,_,_,new_process,state,_=environment
    monkeypatch.setattr(op,'require_idle',lambda *_:state.update(process=new_process))
    monkeypatch.setattr(op,'unload',lambda:state.update(unloads=state['unloads']+1))
    with pytest.raises(ValueError,match='MAIN_PROCESS_CAS_DRIFT'):
        op.switch('receipt','unused','unused')
    assert state['unloads']==0


def test_interrupted_recovery_uses_journal_and_rejects_external_process(environment,monkeypatch):
    target,live,old,new,old_process,new_process,state,receipt=environment
    attempt={'preparation_sha256':'receipt','before_plist_sha256':op.sha(old),'candidate_plist_sha256':op.sha(new),
             'candidate_manifest_sha256':receipt['manifest']['sha256'],'before_process':old_process,'candidate_process':new_process}
    ref=op.write_json(target/'attempt.json',attempt);live.write_bytes(new);state['process']={'pid':3,'root':'/other'}
    monkeypatch.setattr(op,'unload',lambda:state.update(unloads=state['unloads']+1,process=None))
    with pytest.raises(ValueError,match='MAIN_RECOVERY_DESIRED_PROCESS_CHANGED'):
        op.recover('receipt',ref['sha256'],'unused','unused')
    assert state['unloads']==0 and live.read_bytes()==new
    state['process']=new_process;op.recover('receipt',ref['sha256'],'unused','unused')
    assert live.read_bytes()==old and state['process']==old_process and state['unloads']==1
