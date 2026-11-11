"""R1's real false-readiness defect, bounded metadata-only fixture."""
import json
from pathlib import Path
import pytest
from ops import research_panel_qfq as q


@pytest.fixture
def ready(tmp_path,monkeypatch):
    src=tmp_path/'ops';src.mkdir()
    names=['research_panel_qfq.py','research_panel_adjustment_inputs.py','research_panel_factor_cache.py','research_panel_tdx_adjustment_inputs.py','research_panel_logical.py','research_panel_delta.py','driver.py','formula.py','contract.csv']
    for name in names:(src/name).write_text('bound fixture '+name)
    monkeypatch.setattr(q,'__file__',str(src/'research_panel_qfq.py'))
    monkeypatch.setattr(q,'DRIVER_SHA',q.sha(src/'driver.py'));monkeypatch.setattr(q,'FORMULA_SHA',q.sha(src/'formula.py'))
    monkeypatch.setattr(q,'_release_tuple_bound',lambda:True) # Metadata mechanics only; no release acceptance claim.
    refs=[dict(path=str(src/name),sha256=q.sha(src/name))for name in ['driver.py','formula.py','contract.csv','research_panel_logical.py','research_panel_delta.py']]
    root=tmp_path/'data';pointers={r:root/d/n for r,d,n in [('selector','data_layer_interface_current','CURRENT_SELECTOR_READY_PANEL.txt'),('backtest','backtest_panel_interface_current','CURRENT_BACKTEST_BASE_PANEL.txt')]}
    for role,p in pointers.items():p.parent.mkdir(parents=True);p.write_text(str(tmp_path/(role+'.logical'))+'\n')
    input_file=root/'input.json';input_file.write_text(json.dumps(dict(asof_date=20261111)))
    contract=dict(generation_id='fixture',asof_date=20261111,snapshot_file_sha256=q.sha(input_file),driver_sha256=q.DRIVER_SHA,formula_sha256=q.FORMULA_SHA,
        adapter_sha256=q.sha(src/'research_panel_qfq.py'),input_adapter_sha256=q.sha(src/'research_panel_adjustment_inputs.py'),factor_cache_sha256=q.sha(src/'research_panel_factor_cache.py'),tdx_adapter_sha256=q.sha(src/'research_panel_tdx_adjustment_inputs.py'),
        user_formula_sha256=q.USER_FORMULA_SHA,field_contract_sha256=refs[2]['sha256'],logical_reader_sha256=refs[3]['sha256'],delta_owner_sha256=refs[4]['sha256'])
    readiness=dict(generation_id='fixture',code_refs=refs,turnover_watch=['frozen'],factor_cache_identity='factor',source_stats=[])
    watch=input_file.with_name('qfq_readiness.json');watch.write_text(json.dumps(readiness))
    monkeypatch.setattr(q,'refresh_due',lambda *a:False);monkeypatch.setattr(q,'panel_contract',lambda *a:contract)
    monkeypatch.setattr(q,'turnover_watch_unchanged',lambda *a:True);monkeypatch.setattr(q,'factor_cache_identity',lambda *a:'factor')
    return contract,input_file,readiness,watch,pointers,src


def test_precise_five_refs_are_ready_and_legacy_three_refs_still_work(ready):
    contract,path,value,watch,pointers,_=ready
    assert q._generation_tuple_compatible(contract,path)
    assert q.pointer_ready(pointers['selector'],20261111,path)
    value['code_refs']=value['code_refs'][:3];watch.write_text(json.dumps(value))
    old={k:v for k,v in contract.items()if k not in ['logical_reader_sha256','delta_owner_sha256']}
    assert q._generation_tuple_compatible(old,path)
    assert not q._generation_tuple_compatible(contract,path)


@pytest.mark.parametrize('drift',['helper_path','helper_sha','helper_contract','unknown_count'])
def test_new_helper_refs_reject_drift(ready,drift):
    contract,path,value,watch,pointers,src=ready
    if drift=='helper_path':
        copy=src/'different.py';copy.write_bytes(Path(value['code_refs'][3]['path']).read_bytes());value['code_refs'][3]['path']=str(copy)
    if drift=='helper_sha':Path(value['code_refs'][3]['path']).write_bytes(b'changed')
    if drift=='helper_contract':contract['logical_reader_sha256']='f'*64
    if drift=='unknown_count':value['code_refs'].append(value['code_refs'][4])
    watch.write_text(json.dumps(value))
    assert not q.pointer_ready(pointers['selector'],20261111,path)
