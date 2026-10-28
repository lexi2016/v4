"""One fake startup/exit sequence regression; no subprocess, HTTP or lifecycle."""
from pathlib import Path
from types import SimpleNamespace
import importlib.util

import pytest

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('identity_sampling_control',HERE/'api_profile_control.py')
ctrl=importlib.util.module_from_spec(spec);spec.loader.exec_module(ctrl)


def test_known_startup_and_exit_sampling_stays_bounded_and_identity_strict(monkeypatch):
    strict_sampler=ctrl.process
    class Clock:
        now=0.0
        def monotonic(self):return self.now
        def sleep(self,seconds):self.now+=seconds
    clock=Clock();monkeypatch.setattr(ctrl,'time',clock)
    monkeypatch.setattr(ctrl,'pin',lambda *args:None)
    monkeypatch.setattr(ctrl,'listeners',lambda **kwargs:{77})
    plan=dict(candidate_root='/synthetic/candidate',base_app='/synthetic/base/app',candidate_manifest_sha256='f'*64,base_manifest_sha256='e'*64,operation=dict(before_sha256='a'*64,after_sha256='b'*64))
    op=SimpleNamespace(label_state=lambda label:77,metadata_pin=lambda row:None)
    integ=SimpleNamespace(read_active_release=lambda path:dict(release_manifest_sha256='f'*64))
    ps='77 Thu Oct 29 02:15:00 2026 synthetic-api'
    identity=dict(pid=77,ps_identity=ps,cwd='/synthetic/candidate/app')
    requests=[]
    def runtime(**kwargs):
        requests.append(kwargs['timeout_seconds'])
        return dict(release_id='candidate',manifest_sha256='f'*64,status='MANIFEST_EXECUTION_FILES_VERIFIED')
    monkeypatch.setattr(ctrl,'runtime',runtime)

    # New known label/PID: temporarily no ps row, then known ps/no cwd,
    # then exact identity; manifest acceptance requires an exact final sample.
    observations=iter([None,ctrl.ProcessSamplePending('CWD_SAMPLE_PENDING',ps),identity,identity])
    def sample(pid,**kwargs):
        assert pid==77 and 0<kwargs['sample_timeout_seconds']<=2
        result=next(observations)
        if isinstance(result,Exception):raise result
        return result
    monkeypatch.setattr(ctrl,'process',sample)
    result=ctrl.verify_running(plan,integ,op,True)
    assert result['process']==identity and result['identity_sample_attempts']==3
    assert requests==[20]

    # An explicit wrong cwd is rejected immediately, never accepted as pending.
    monkeypatch.setattr(ctrl,'process',lambda *args,**kwargs:{**identity,'cwd':'/synthetic/wrong/app'})
    with pytest.raises(RuntimeError,match='STARTUP_CWD_MISMATCH'):
        ctrl.verify_running(plan,integ,op,True)
    assert requests==[20]

    # Same PID with a different start identity is reuse, even if cwd matches.
    observations=iter([ctrl.ProcessSamplePending('CWD_SAMPLE_PENDING',ps),{**identity,'ps_identity':ps+'-different-start'}])
    monkeypatch.setattr(ctrl,'process',sample)
    with pytest.raises(RuntimeError,match='STARTUP_PID_REUSED'):
        ctrl.verify_running(plan,integ,op,True)

    # A missing cwd never becomes successful natural/runtime evidence at deadline.
    def unavailable(*args,**kwargs):raise ctrl.ProcessSamplePending('CWD_SAMPLE_PENDING',ps)
    monkeypatch.setattr(ctrl,'process',unavailable);start=clock.now
    with pytest.raises(RuntimeError,match='RUNTIME_READBACK_UNCONFIRMED:CWD_SAMPLE_PENDING'):
        ctrl.verify_running(plan,integ,op,True,wait_seconds=.25)
    assert .25<=clock.now-start<.251 and requests==[20]

    # The actual incident's old-PID exit gap is retryable only while its
    # already-frozen ps/start identity remains unchanged, until ps is absent.
    old=dict(pid=77,ps_identity=ps,cwd='/synthetic/base/app')
    observations=iter([ctrl.ProcessSamplePending('CWD_SAMPLE_PENDING',ps),None])
    monkeypatch.setattr(ctrl,'process',sample)
    assert ctrl.exit_wait(old,wait_seconds=.25) is None
    monkeypatch.setattr(ctrl,'process',unavailable);start=clock.now
    with pytest.raises(RuntimeError,match='EXIT_UNCONFIRMED_NO_KILL'):
        ctrl.exit_wait(old,wait_seconds=.25)
    assert .25<=clock.now-start<.251
    monkeypatch.setattr(ctrl,'process',lambda *args,**kwargs:{**old,'ps_identity':ps+'-reused'})
    with pytest.raises(RuntimeError,match='PID_REUSED'):ctrl.exit_wait(old)

    # Outside the two wait contexts, the same sampler still raises on missing
    # cwd; it neither retries globally nor treats an unknown cwd as identity.
    commands=[]
    def os_sample(args,**kwargs):
        commands.append(args);assert kwargs['timeout'] is None
        return SimpleNamespace(returncode=0 if args[0]=='/bin/ps' else 1,
            stdout=ps+'\n' if args[0]=='/bin/ps' else 'p77\n',stderr='')
    monkeypatch.setattr(ctrl.subprocess,'run',os_sample)
    with pytest.raises(ctrl.ProcessSamplePending,match='CWD_SAMPLE_PENDING'):
        strict_sampler(77)
    assert len(commands)==2
