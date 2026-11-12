"""Synthetic closed-run recovery mechanics; no live checkpoint writes."""
import copy
import importlib.util
import json
from pathlib import Path
import pytest
from test_delta_owner import fixture,write
from ops import research_panel_qfq as owner
from ops import research_panel_delta as delta
from ops import research_panel_logical as logical

OLD_APP=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/v4-daily-delta-20261111-r1/main/app')


def load_old():
    path=OLD_APP/'ops/research_panel_delta.py'
    spec=importlib.util.spec_from_file_location('r3_real_original_delta_wrapper',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


@pytest.fixture
def recovery(fixture,monkeypatch):
    f=fixture;data=f.tmp/'state/workspace/data';data.mkdir(parents=True)
    snapshot=f.c['snapshot'];mutable=owner.input_path(data);owner._json(mutable,snapshot)
    immutable=mutable.parent/'adjustment_snapshots'/(owner.sha(mutable)+'.json');owner._write(immutable,mutable.read_bytes());snapshot_ref=dict(path=str(immutable),sha256=owner.sha(immutable))
    identity={**f.c['identity'],'adapter_sha256':owner.sha(OLD_APP/'ops/research_panel_qfq.py'), 'delta_owner_sha256':owner.sha(OLD_APP/'ops/research_panel_delta.py'), 'logical_reader_sha256':owner.sha(OLD_APP/'ops/research_panel_logical.py'),
        'input_adapter_sha256':'input-adapter-fixture','factor_cache_sha256':'factor-helper-fixture','tdx_adapter_sha256':'tdx-fixture'}
    generation=owner.canonical_sha(dict(target=3,baseline_panel_sha256=f.c['baseline_hashes'],**identity))
    run=data.parents[1]/'research_panel_daily/a_formula_runs'/('qfq_'+generation[:20]);run.mkdir(parents=True)
    f.c.update(data_root=data,run_dir=run,run_id=generation,snapshot_file=mutable,identity=identity)
    f.c['meta'].update(identity);f.c['meta'].update(generation_id=generation,generation_manifest_path=str(run/'candidate_receipt.json'),adjustment_snapshot=snapshot_ref)
    f.q['__file__']=str(OLD_APP/'ops/research_panel_qfq.py')
    f.q['generation_identity']=lambda s,*a:{**{k:v for k,v in identity.items()if k!='turnover_input_sha256'},'input_sha256':owner.canonical_sha(s)}
    load_old().run_delta(f.q,f.c)
    status=json.loads((run/'stage_status.json').read_text());status['status']='FAILED';status['error']='ISOLATED_FIXTURE_AFTER_COMPUTATION_BEFORE_PUBLISH';owner._json(run/'stage_status.json',status)
    entries=[]
    for name in ['research_panel_qfq.py','research_panel_delta.py','research_panel_logical.py']:
        entries.append(dict(owner='main',target_relative='ops/'+name,target=str(OLD_APP/'ops'/name),before_sha256=owner.sha(OLD_APP/'ops'/name),after_sha256=owner.sha(Path(owner.__file__).with_name(name))))
    binding=write(f.tmp/'isolated-source-binding.json',dict(items=entries,fixture_only=True))
    review=write(f.tmp/'isolated-review.json',dict(verdict='REVIEWED/PASS',reviewer='independent-fixture',writer='writer-fixture',source_binding=binding,not_a_live_acceptance=True))
    monkeypatch.setattr(owner,'factor_cache_identity',lambda *a:'fixture factor')
    monkeypatch.setattr(owner,'load_snapshot',lambda *a:copy.deepcopy(snapshot))
    body=delta.prepare_delta_resume(source_run=run,target_core=Path(owner.__file__),target_delta=Path(delta.__file__),independent_review=review,data_root=data)
    ref=write(f.tmp/'resume.json',body)
    new_identity={**identity,'adapter_sha256':owner.sha(Path(owner.__file__)),'delta_owner_sha256':owner.sha(Path(delta.__file__)),'logical_reader_sha256':owner.sha(Path(logical.__file__))}
    return f,body,ref,new_identity


def test_sealed_original_delta_records_reused_without_recompute_or_copy(recovery):
    f,body,ref,identity=recovery
    restored=delta.load_delta_recovery(vars(owner),body,f.c['snapshot'],identity,f.c['baseline_hashes'],f.c['data_root'])
    assert len(restored)==4
    original={p:p.read_bytes()for p in f.c['run_dir'].rglob('*.json')}
    old_blocks={Path(v['artifact']['path']):Path(v['artifact']['path']).read_bytes()for p in (f.c['run_dir']/'delta_checkpoints').glob('*.json')for v in json.loads(p.read_text())['roles'].values()}
    c=dict(f.c);c['run_dir']=f.tmp/'newrun';c['run_dir'].mkdir();c['run_id']='new-generation';c['identity']=identity
    c['candidates']={role:f.tmp/('new_'+role)/'current.logical'for role in f.c['currents']}
    c['meta']={**f.c['meta'],**identity,'generation_id':c['run_id'],'generation_manifest_path':str(c['run_dir']/'candidate_receipt.json')}
    c['checkpoint_resume']=ref;c['delta_resume_control']=body;c['recovered']=restored
    q=dict(f.q);q['__file__']=owner.__file__;q['generation_identity']=lambda s,*a:{**{k:v for k,v in identity.items()if k!='turnover_input_sha256'},'input_sha256':owner.canonical_sha(s)}
    calls=list(f.calls);result=delta.run_delta(q,c)
    assert f.calls==calls and result['reused_delta_checkpoints']==4 and result['new_delta_file_bytes']==0
    assert not (c['run_dir']/'delta_checkpoints').exists()
    assert all(p.read_bytes()==raw for p,raw in original.items())and all(p.read_bytes()==raw for p,raw in old_blocks.items())
    for role,path in c['candidates'].items():
        assert len(logical.parquet.read_table(path))==12
        assert all(b['path']in {str(p)for p in old_blocks}for b in logical.closure(path)[1:])
        assert body['source_status']in logical.closure(path)[0]['metadata_refs']


@pytest.mark.parametrize('change',['baseline','date','review','artifact','abandoned','snapshot'])
def test_recovery_rejects_wrong_scope_or_changed_source(recovery,change):
    f,body,ref,identity=recovery;value=copy.deepcopy(body)
    if change=='baseline':value['baseline_panel_sha256']['selector']='wrong'
    if change=='date':value['asof_date']=4
    if change=='review':value['target_delta']['sha256']='0'*64
    if change=='artifact':
        cp=json.loads(Path(next(iter(value['chunks'].values()))['path']).read_text());artifact=Path(next(iter(cp['roles'].values()))['artifact']['path']);artifact.write_bytes(artifact.read_bytes()+b'drift')
    if change=='abandoned':
        p=Path(value['source_status']['path']);status=json.loads(p.read_text());status['status']='ABANDONED';owner._json(p,status);value['source_status']['sha256']=owner.sha(p)
    if change=='snapshot':Path(value['original_snapshot']['path']).write_text('changed')
    with pytest.raises((ValueError,owner.QfqGateError)):
        delta.load_delta_recovery(vars(owner),value,f.c['snapshot'],identity,f.c['baseline_hashes'],f.c['data_root'])


def test_fixed_input_preserves_current_descriptor_and_rejects_drift(recovery):
    f,body,ref,identity=recovery
    before=f.c['snapshot_file'].read_bytes()
    fixed=delta.fixed_delta_resume_input(vars(owner),ref,3,f.c['snapshot_file'])
    assert fixed['_validated_snapshot']==f.c['snapshot']and f.c['snapshot_file'].read_bytes()==before
    f.c['snapshot_file'].write_bytes(before+b'x')
    with pytest.raises(owner.QfqGateError):delta.fixed_delta_resume_input(vars(owner),ref,3,f.c['snapshot_file'])
