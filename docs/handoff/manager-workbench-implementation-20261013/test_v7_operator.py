"""Operator-only paths tested with temp roots and fake service control."""
import hashlib,json
from pathlib import Path
import pytest
import operate_v7_cutover as op
from ops.api_release_integration import inventory_tree
sha=lambda raw:hashlib.sha256(raw).hexdigest()


def setup(tmp_path,monkeypatch):
 formal=tmp_path/'formal';canonical=tmp_path/'canonical';launch=tmp_path/'LaunchAgents';launch.mkdir()
 monkeypatch.setattr(op,'FORMAL',formal);monkeypatch.setattr(op,'CANONICAL',canonical)
 monkeypatch.setattr(op,'API',launch/'com.lexi.v35.api-only.plist');monkeypatch.setattr(op,'SCHED',launch/'com.lexi.v35.scheduler.plist')
 monkeypatch.setattr(op,'verify_api_release_candidate',lambda **kw:None)
 entries=[]
 def add(kind,target,before,after):
  i=len(entries);source=tmp_path/f'source-{i}';source.write_bytes(after);backup=tmp_path/f'backup-{i}'
  if before is not None:target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(before);backup.write_bytes(before)
  e=dict(kind=kind,target=str(target),source=str(source),backup=str(backup) if before is not None else None,before_sha256=sha(before) if before is not None else None,after_sha256=sha(after));entries.append(e)
 add('config',formal/'config/manager-workbench-v7.json',None,b'{"capture_enabled":false}')
 add('canonical',canonical/'apps/api/v35_api/app.py',b'old app',b'new app')
 add('saved_state',formal/'state/manager_workbench/manager_workbench/plans/saved.json',None,b'{"phase":"RETROSPECTIVE"}')
 pairs=[dict(label='com.lexi.v35.api-only',formal_path=str(op.API)),dict(label='com.lexi.v35.scheduler',formal_path=str(op.SCHED))]
 for pair in pairs:add('plist',Path(pair['formal_path']),b'old plist',b'new plist')
 plan=dict(entries=entries,plists=pairs)
 for role in ('api','scheduler'):
  app=tmp_path/role/'app';app.mkdir(parents=True);mp=app.parent/'release-manifest.json';mp.write_text(json.dumps({'application_inventory':{'entries':inventory_tree(app)}}));plan['candidate_'+role]=str(app);plan[role+'_manifest_sha256']=sha(mp.read_bytes())
 return plan


def test_apply_and_whole_rollback_preserve_saved_evidence(tmp_path,monkeypatch):
 plan=setup(tmp_path,monkeypatch);events=[];monkeypatch.setattr(op,'launch',lambda action,pair:events.append((action,pair['label'])))
 op.validate(plan,'apply');op.execute(plan,'apply',tmp_path/'apply.json')
 assert [a for a,_ in events]==['bootout','bootout','bootstrap','bootstrap']
 assert all(op.current_sha(Path(e['target']))==e['after_sha256'] for e in plan['entries'])
 op.execute(plan,'rollback',tmp_path/'rollback.json')
 for e in plan['entries']:
  assert op.current_sha(Path(e['target']))==(e['after_sha256'] if e['kind']=='saved_state' else e['before_sha256'])


def test_parallel_drift_and_unlisted_path_fail_before_writes(tmp_path,monkeypatch):
 plan=setup(tmp_path,monkeypatch);e=plan['entries'][1];Path(e['target']).write_bytes(b'parallel edit')
 with pytest.raises(ValueError,match='PARALLEL_DRIFT'):op.validate(plan,'apply')
 with pytest.raises(ValueError,match='CHANGED_BEFORE_WRITE'):op.write(e)
 assert Path(e['target']).read_bytes()==b'parallel edit'
 e={**e,'target':str(op.CANONICAL/'unrelated.py')}
 with pytest.raises(ValueError,match='SOURCE_PATH_FORBIDDEN'):op.target_root(e)


def test_start_failure_restores_both_prior_plists_and_sources(tmp_path,monkeypatch):
 plan=setup(tmp_path,monkeypatch);failed=False
 def launch(action,pair):
  nonlocal failed
  if action=='bootstrap' and not failed:failed=True;raise RuntimeError('synthetic start failed')
 monkeypatch.setattr(op,'launch',launch)
 with pytest.raises(RuntimeError,match='synthetic'):op.execute(plan,'apply',tmp_path/'journal.json')
 for e in plan['entries']:
  assert op.current_sha(Path(e['target']))==(e['after_sha256'] if e['kind']=='saved_state' else e['before_sha256'])
 assert json.loads((tmp_path/'journal.json').read_text())['status']=='FAILED_PRESERVED_JOURNAL'


def test_capture_lease_is_not_a_transferable_material(tmp_path,monkeypatch):
 setup(tmp_path,monkeypatch)
 root=op.FORMAL/'state/manager_workbench_capture'
 with pytest.raises(ValueError,match='CAPTURE_LEASE_TRANSFER_FORBIDDEN'):
  op.target_root(dict(kind='capture_material',target=str(root/'leases/EASTMONEY_HK.json')))
 assert op.target_root(dict(kind='capture_material',target=str(root/'objects/raw.bin')))==root
