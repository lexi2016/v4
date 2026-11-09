from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import json
import pytest
from ops import complete_workbench_v192_assets as completion
from ops import research_panel_daily_product as owner


def test_empty_missing_scope_never_calls_original_score_default_scope(tmp_path,monkeypatch):
    monkeypatch.setenv('V4_SHARED_PACKAGE_ROOT','unused');monkeypatch.setenv('V4_SHARED_DATA_ROOT','unused')
    monkeypatch.setattr(completion.assets,'original_model_reader',lambda *args:SimpleNamespace(rows=[{'ts_code':'301199.SZ'}]))
    monkeypatch.setattr(completion.assets,'prepare',lambda *args,**kw:pytest.fail('empty extension would rescore canonical rows'))
    result=completion.prepare_completed(SimpleNamespace(),{'data_date':'20261109','rows':[{'symbol':'301199.SZ'}]}, {},'20261110')
    assert result['status']=='NO_MISSING_MODEL_VIEWS'


def prepared(tmp_path):
    root=tmp_path/'native';stage=tmp_path/'isolated';lock=tmp_path/'A_LONG.lock';lock.write_text('')
    numeric={'path':'/immutable/numeric','sha256':'a'*64}
    original=dict(dates={'20261109':numeric},latest_date='20261109',score_action={'20261109':{'index':'original371'}},company_materials={'keep':'all'},original_charts={'keep':'371'})
    event=dict(data_date='20261109',event_id='old',manifest=numeric,score_action='original371')
    owner.save(root/'index.json',original);owner.save(root/'events/latest.json',event)
    module=owner.save(tmp_path/'module.json',{'status':'READY','marker':'new17'})
    descriptor=dict(data_date='20261109',numeric_manifest=numeric,module=module,status='READY')
    return root,stage,lock,original,event,descriptor


def test_publication_isolated_cas_keeps371_and_completion_and_noop(tmp_path):
    root,stage,lock,before,event,d=prepared(tmp_path)
    plan=completion.publication_plan(d,root,stage,lock)
    assert json.loads((root/'index.json').read_bytes())==before
    assert json.loads((root/'events/latest.json').read_bytes())==event
    result=completion.publish(plan)
    assert result['status']=='PUBLISHED_V192_ASSETS'
    after=json.loads((root/'index.json').read_bytes());new_event=json.loads((root/'events/latest.json').read_bytes())
    assert {k:v for k,v in after.items() if k!='v192_assets'}==before
    assert {k:v for k,v in new_event.items() if k not in ['v192_assets','event_id']}=={k:v for k,v in event.items() if k!='event_id'}
    assert new_event['event_id']!=event['event_id']
    again=completion.publication_plan(d,root,stage/'again',lock)
    assert completion.publish(again)['status']=='NOOP'


def test_moved_index_rejected_without_overwriting_other_module(tmp_path):
    root,stage,lock,before,event,d=prepared(tmp_path);plan=completion.publication_plan(d,root,stage,lock)
    updated=deepcopy(before);updated['company_materials']={'new':'received'};owner.save(root/'index.json',updated)
    with pytest.raises(ValueError,match='PIN_DRIFT'):completion.publish(plan)
    assert json.loads((root/'index.json').read_bytes())==updated
    assert json.loads((root/'events/latest.json').read_bytes())==event


def test_daily_owner_uses_existing_completion_hook_without_nested_lock():
    import ast
    tree=ast.parse(Path(owner.__file__).read_text())
    calls=[node for node in ast.walk(tree) if isinstance(node,ast.Call) and isinstance(node.func,ast.Name)]
    assert sum(node.func.id=='at_numeric_completion' for node in calls)==1
    assert sum(node.func.id=='attach' for node in calls)==1


def test_preselection_reuse_completes_after_pool_publication_and_failure_is_scoped(tmp_path,monkeypatch,capsys):
    from ops import materialize_scheduled_preselection as scheduled
    order=[]
    monkeypatch.setattr(scheduled,'build_scheduled_artifacts',lambda **kw:order.append('build_or_reuse') or [])
    monkeypatch.setattr(scheduled,'publish_scheduled_artifacts',lambda *args:order.append('formal_publish') or [])
    monkeypatch.setattr(scheduled,'_formal_pool_gate',lambda a:{'status':'READY'})
    def complete(d,o):
        order.append((d,o));raise ValueError('VIEW_UNKNOWN')
    monkeypatch.setattr(completion,'after_preselection',complete)
    args=['--trade-date','20261110','--signal-date','20261109','--input-root',str(tmp_path),'--data-root',str(tmp_path/'data'),'--shared-data-root',str(tmp_path/'shared'),'--shared-package-root',str(tmp_path/'package')]
    assert scheduled.main(args)==0
    result=json.loads(capsys.readouterr().out)
    assert order==['build_or_reuse','formal_publish',('20261109','20261110')]
    assert result['status']=='READY' and result['v192_assets']['status']=='CANNOT_CONFIRM'


def test_next_day_seeds_only_past_missing_symbol_recurrence(tmp_path,monkeypatch):
    monkeypatch.setenv('V4_SHARED_PACKAGE_ROOT','unused');monkeypatch.setenv('V4_SHARED_DATA_ROOT','unused')
    verified=SimpleNamespace(rows=[{'ts_code':'301199.SZ'},{'ts_code':'603286.SH'}],run=SimpleNamespace(verification={'artifact_sha256':'a'*64,'manifest_sha256':'b'*64}))
    monkeypatch.setattr(completion.assets,'original_model_reader',lambda *args:verified)
    record={'symbol':'603286.SH','trade_date':'20261109','cache_identity':{'symbol':'603286.SH','prefix_sha256':'past'},'recurrence':{'unchanged':'authority-state'}}
    rr=owner.save(tmp_path/'past_record.json',record);si=owner.save(tmp_path/'past_index.json',{'items':{'603286.SH':rr}})
    mr=owner.save(tmp_path/'past_module.json',{'score_action':{'index':si}})
    root=tmp_path/'native';owner.save(root/'index.json',{'v192_assets':{'20261109':{'module':mr}}})
    context=SimpleNamespace(target=20261110,root=root,identity={'selector_artifact_sha256':'c'*64})
    product={'data_date':'20261110','rows':[{'symbol':'301199.SZ'}]};calls=[]
    monkeypatch.setattr(completion.assets,'prepare',lambda c,p,m,v,base,**kw:calls.append(kw['symbols']) or {'status':'prepared'})
    assert completion.prepare_completed(context,product,{},'20261111',output_root=tmp_path/'derived')['status']=='prepared'
    cached=list((tmp_path/'derived').glob('**/stock_cache/603286.SH/*.json'))
    assert len(cached)==1 and json.loads(cached[0].read_bytes())==record and calls==[['603286.SH']]
