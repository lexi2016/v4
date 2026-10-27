"""R4 keeps the three unchanged services bound during forward and recovery."""
import copy
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

CONTROL=Path(__file__).parents[1]/'deliveries/v4_business_gaps_20261027/control'
sys.path.insert(0,str(CONTROL))
import prepare as prep
import controller as ctl


def plan():
    p={'scope':prep.SCOPE,'control_mode':prep.R4_MODE,'operations':[], 'base':{},'components':{},
       'production_allowed':False,'buy_gate_updated':False,'orders_sent':False}
    for k,label in prep.LABELS.items():
        root='/old/'+k; plist=str(Path.home()/'Library/LaunchAgents'/(label+'.plist'))
        p['base'][k]=dict(app_root=root+'/app',manifest=root+'/release-manifest.json',manifest_sha256='m'+k,application_inventory_sha256='i'+k,plist_sha256='p'+k)
        p['components'][k]=dict(candidate_app=root+'/app',path=root+'/release-manifest.json',release_root=root,sha256='m'+k,application_inventory_sha256='i'+k)
        p['operations'].append(dict(component=k,label=label,plist=plist,before_sha256='p'+k,after_sha256='p'+k))
    old={'components':copy.deepcopy(p['components']),'operations':copy.deepcopy(p['operations'])}
    for k in ('api','collector'):
        p['components'][k].update(candidate_app='/candidate/'+k,path='/candidate/'+k+'/manifest',release_root='/new/'+k,sha256='new'+k,application_inventory_sha256='newi'+k)
        next(r for r in p['operations'] if r['component']==k)['after_sha256']='newp'+k
    return p,old


def test_r4_and_default_full_scope_and_drift():
    p,old=plan();ctl.require_scope(p);ctl.validate_unchanged_prior(p,old)
    full=copy.deepcopy(p);full.pop('control_mode');ctl.require_scope(full)
    for key,field,value in [('main','release_root','/unexpected'),('stage','sha256','other'),('a_precapture','application_inventory_sha256','other')]:
        bad=copy.deepcopy(p);bad['components'][key][field]=value
        with pytest.raises(ValueError,match='UNCHANGED_IDENTITY_DRIFT'):ctl.require_scope(bad)
    bad=copy.deepcopy(p);next(r for r in bad['operations'] if r['component']=='main')['after_sha256']='other'
    with pytest.raises(ValueError,match='UNCHANGED_IDENTITY_DRIFT'):ctl.require_scope(bad)
    wrong=copy.deepcopy(old);wrong['components']['stage']['sha256']='other'
    with pytest.raises(ValueError,match='UNCHANGED_PRIOR_IDENTITY_DRIFT'):ctl.validate_unchanged_prior(p,wrong)
    wrong=copy.deepcopy(p);wrong['components']['api']['release_root']=str(Path(wrong['base']['api']['app_root']).parent)
    with pytest.raises(ValueError,match='R4_CHANGED_IDENTITY_AMBIGUOUS'):ctl.require_scope(wrong)


def test_identical_binding_and_missing_service(monkeypatch):
    p,old=plan();c=object.__new__(ctl.Controller);c.p=p
    c.op=SimpleNamespace(op=lambda p,k:next(r for r in p['operations'] if r['component']==k),label_state=lambda label:42)
    c.g=SimpleNamespace(cwd=lambda pid:'/old/main/app')
    c.read_command=lambda args:SimpleNamespace(stdout=b'/old/main/app/ops/launch_v35_macos_scheduler.sh')
    monkeypatch.setattr(prep,'sha',lambda path:'pmain')
    assert c.binding('main',old)['version']=='UNCHANGED'
    c.g.cwd=lambda pid:'/wrong'
    with pytest.raises(RuntimeError,match='UNKNOWN_LOADED_DEFINITION'):c.binding('main',old)
    c.op.label_state=lambda label:None
    assert c.binding('main',old)=={'loaded':False,'disk':'UNCHANGED'}


def test_recovery_never_touches_unchanged(monkeypatch):
    p,old=plan();c=object.__new__(ctl.Controller);c.p=p
    states={k:({'loaded':True,'version':'UNCHANGED','disk':'UNCHANGED'} if k in prep.R4_UNCHANGED else {'loaded':True,'version':'NEW','disk':'NEW'}) for k in prep.LABELS}
    actions=[];c.binding=lambda k,old:states[k];c.row=lambda k:next(r for r in p['operations'] if r['component']==k)
    c.unload=lambda k:actions.append(('unload',k));c.bootstrap=lambda k:actions.append(('bootstrap',k));c.record=lambda *a,**kw:None
    c.op=SimpleNamespace(install_plist=lambda row,rollback:actions.append(('install',row['component'])),label_state=lambda label:42)
    c.wait_verify=lambda old:None;c.cas=lambda **kw:None;c.verify_graph=lambda old:None;c.verify=lambda old:'ok'
    assert c.rollback(old)=='ok'
    assert actions==[('unload','collector'),('install','collector'),('unload','api'),('install','api')]
    states['stage']={'loaded':False,'disk':'UNCHANGED'};actions.clear()
    with pytest.raises(RuntimeError,match='UNCHANGED_SERVICE_NOT_BOUND'):c.rollback(old)
    assert actions==[]


def test_command_rejects_unmodified_services():
    p,_=plan();c=object.__new__(ctl.Controller);c.p=p;c.phase='FORWARD';c.uncertain=False;c.attempted=set()
    for key in prep.R4_UNCHANGED:
        with pytest.raises(RuntimeError,match='SERVICE_ACTION_OUTSIDE_FIXED_SCOPE'):
            c.command(['bootout',f'gui/{__import__("os").getuid()}/'+prep.LABELS[key]])
        with pytest.raises(RuntimeError,match='SERVICE_ACTION_OUTSIDE_FIXED_SCOPE'):
            c.command(['bootstrap',f'gui/{__import__("os").getuid()}',next(r['plist'] for r in p['operations'] if r['component']==key)])
