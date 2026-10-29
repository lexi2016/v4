"""Only locale-consistent identity capture; no real ps/launchctl/lock/action."""
import json,sys
from pathlib import Path
from types import SimpleNamespace
import pytest
HERE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(HERE))
import observe_main_identity as O
C=O.C
PLAN=json.loads((HERE/'PLAN.json').read_bytes())

def test_capture_uses_live_c_locale_and_strict_guard_still_rejects_drift(monkeypatch):
    p=PLAN;expected=p['main_readonly']['identity'];evidence=json.loads((HERE/'LOCALE_MISMATCH_ACTUAL.json').read_bytes());wrong=evidence['before_identity'];calls=[];state={'drift':False}
    def run(args,**kwargs):
        calls.append({'args':args,'env':kwargs['env']['LC_ALL']})
        assert kwargs['env']['LC_ALL']=='C'
        if args[0]=='/bin/ps':
            text=expected['ps_text'] if not state['drift'] else expected['ps_text']+'REAL_OWNER_DRIFT'
            return SimpleNamespace(returncode=0,stdout=text,stderr='')
        assert args==['/bin/launchctl','print','gui/501/com.lexi.v4.scheduler']
        return SimpleNamespace(returncode=0,stdout='\tpid = 73799\n',stderr='')
    monkeypatch.setattr(C.r7.subprocess,'run',run)
    assert O.capture_main_identity(p)==expected and expected!=wrong
    C.Live(p).main_unchanged()
    assert all(c['env']=='C' for c in calls)
    assert not any(c['args'][1] in ['debug','bootout','bootstrap','kickstart'] for c in calls)
    state['drift']=True;prior=len(calls)
    with pytest.raises(C.Stop,match='READONLY_MAIN_IDENTITY_CHANGED'):C.Live(p).main_unchanged()
    assert len(calls)==prior+1 and calls[-1]['args'][0]=='/bin/ps'
