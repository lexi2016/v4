import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import struct
import pandas as pd
import pytest
from ops import research_panel_qfq as owner
from ops import research_panel_delta as delta


@pytest.mark.parametrize('bad',['none','old_revision','new_sha','slicing','future'])
def test_baseline_prefix_requires_exact_both_sources(tmp_path,bad):
    dates=[20261109,20261110,20261111]
    record=struct.Struct('<I28s');original=b''.join(record.pack(d,b'x'*28)for d in dates[:2])
    raw=original+record.pack(dates[-1],b'x'*28)
    if bad=='old_revision':raw=record.pack(dates[0],b'changed'.ljust(28,b'x'))+raw[32:]
    if bad=='future':raw+=record.pack(20261112,b'x'*28)
    path=tmp_path/'source.day';path.write_bytes(raw)
    old=dict(path=str(path),sha256=hashlib.sha256(original).hexdigest(),from_date_exclusive=20261101)
    new={**old,'sha256':hashlib.sha256(raw).hexdigest()}
    if bad=='new_sha':new['sha256']='f'*64
    if bad=='slicing':new['from_date_exclusive']=20261102
    def read(code,path,tail_records):
        days=[record.unpack_from(path.read_bytes(),i)[0]for i in range(0,path.stat().st_size,32)]
        return pd.DataFrame(dict(trade_date=days,open=10.,high=11.,low=9.,close=10.,vol=100.,amount=1000.))
    driver=SimpleNamespace(DAY_STRUCT=record,read_day_tail=read)
    before=dict(raw_files=[old]);after=dict(raw_files=[new]);current=read('000001.SZ',path,0)
    if bad=='none':
        frame,proof=delta.baseline_raw_history(vars(owner),'000001.SZ',before,after,20261110,20261111,driver,current)
        assert frame.trade_date.tolist()==dates[:2]and proof[0]['prefix_sha256']==old['sha256']and proof[0]['added_dates']==[20261111]
    else:
        with pytest.raises(owner.QfqGateError):delta.baseline_raw_history(vars(owner),'000001.SZ',before,after,20261110,20261111,driver,current)


def test_resource_selection_maximum_and_pressure_clamp():
    gib=1024**3
    observed=dict(cpu_cores=18,physical_memory_bytes=128*gib,available_bytes=110*gib,parent_rss_bytes=6*gib,cumulative_rss_bytes=6*gib,maximum_worker_rss_bytes=0)
    plan=delta.resource_plan(observed)
    assert plan['workers']==16 and plan['max_pending']==32 and plan['job_budget_bytes']==64*gib and plan['reserve_available_bytes']==24*gib
    assert delta.resource_plan(observed,3)['workers']==3
    assert delta.resource_plan({**observed,'available_bytes':25*gib})['workers']==1
    assert delta.resource_plan({**observed,'available_bytes':23*gib})['drained']
    assert delta.resource_plan({**observed,'maximum_worker_rss_bytes':8*gib})['workers']==7


def test_real_spawn_workers_preserve_original_full_prefix_and_turnover(tmp_path):
    import multiprocessing,os
    import pyarrow as pa
    from concurrent.futures import ProcessPoolExecutor
    from ops.research_panel_turnover import DailyTurnover
    from ops import research_panel_logical as logical
    app=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/v4-daily-delta-20261111-r1/main/app')
    driver_path=app/'ops/vendor/data_layer_daily_formula_increment_update_v1.py'
    formula=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/workbench-daily-chain-20261031-r6-main/app/components/a_formula/build_canonical_formula_research_panel.py')
    driver,_=owner.authorities(driver_path,formula)
    dates=pd.bdate_range(end='2026-11-11',periods=90).strftime('%Y%m%d').astype(int).tolist()
    items={};old_items={};frames={};expected={};schemas=None
    for code in ['000001.SZ','002152.SZ','002717.SZ']:
        raw=b''.join(driver.DAY_STRUCT.pack(day,1000+i,1020+i,980+i,1005+i,1000000.,100000,0)for i,day in enumerate(dates))
        old_path=tmp_path/(code+'.old.day');old_path.write_bytes(raw[:-32])
        new_path=tmp_path/(code+'.new.day');new_path.write_bytes(raw[:-32]if code=='002717.SZ'else raw)
        old_items[code]=dict(raw_files=[dict(path=str(old_path),sha256=owner.sha(old_path))],events=[],history_start_date=dates[0],publish_roles=['backtest'])
        items[code]={**old_items[code],'raw_files':[dict(path=str(new_path),sha256=owner.sha(new_path))], 'events':([dict(ex_date=20261111,a=1.,b=-.1,volume_a=1.)]if code=='002152.SZ'else[])}
        old_frame=owner.rebuild_symbol(code,old_items[code],20261110,driver)
        fresh=owner.rebuild_symbol(code,items[code],20261111,driver)
        if schemas is None:
            schema=pa.Table.from_pandas(fresh,preserve_index=False).schema.remove_metadata()
            schema=pa.schema(list(schema)+[pa.field('turnover_rate_pct',pa.float64()),pa.field('float_share_10k',pa.float64()),pa.field('turnover_rate_status',pa.string()),pa.field('turnover_rate_volume_source',pa.string()),pa.field('turnover_rate_denominator_10k',pa.float64())])
            schemas={'backtest':schema}
        old_table=owner._table(old_frame,schemas['backtest'],driver,'backtest')
        frames[code]={'backtest':old_table}
        out=owner.merge_rebuilt(old_table.to_pandas(),fresh,role='backtest',driver=driver)
        out=DailyTurnover(20261111,None,{}, {},'FIXTURE_INPUT_UNKNOWN').apply_target(code,out)
        expected[code]=delta.changed_rows(old_table,owner._table(out,schemas['backtest'],driver,'backtest'))
    identity=dict(input_sha256='fixture',adapter_sha256=owner.sha(Path(owner.__file__)),delta_owner_sha256=owner.sha(Path(delta.__file__)),driver_sha256=owner.DRIVER_SHA,formula_sha256=owner.FORMULA_SHA,user_formula_sha256=owner.USER_FORMULA_SHA,field_contract_sha256='contract',turnover_input_sha256='turnover')
    semantics={k:identity[k]for k in ['driver_sha256','formula_sha256','user_formula_sha256','field_contract_sha256']};semantics['kernel_sha256']=owner.computation_kernel_sha(Path(owner.__file__))
    state=dict(target=20261111,run_dir=tmp_path/'newrun',currents={'backtest':tmp_path/'base'},schemas=schemas,contracts={'backtest':semantics},baseline_hashes={'backtest':'base'},identity=identity,
        turnover=DailyTurnover(20261111,None,{}, {},'FIXTURE_INPUT_UNKNOWN'),role_start={'backtest':dates[0]},driver_path=driver_path,formula_path=formula,retained_history=None,source_semantics=semantics)
    multiprocessing.set_executable(__import__('sys').executable)
    results={}
    with ProcessPoolExecutor(max_workers=2,mp_context=multiprocessing.get_context('spawn'),initializer=delta._initialize_delta_process,initargs=(state,))as pool:
        futures={code:pool.submit(delta._delta_process_task,(code,items[code],old_items[code],20261110,frames[code],None))for code in items}
        for code,future in futures.items():results[code]=future.result()
    pids={r['worker_pid']for r in results.values()}
    assert len(pids)==2 and os.getpid()not in pids
    assert sum(r['cpu_seconds']for r in results.values())>0
    for code,result in results.items():
        actual=result.get('patches',{}).get('backtest',pa.Table.from_batches([],schema=schemas['backtest']))
        assert actual.schema.equals(expected[code].schema,check_metadata=True)
        for field in actual.column_names:assert actual[field].is_null().equals(expected[code][field].is_null())
        pd.testing.assert_frame_equal(actual.to_pandas(),expected[code].to_pandas(),check_exact=True)
        assert result['record']['logical_rows']['backtest']==(89 if code=='002717.SZ' else 90)
        if code!='002717.SZ':assert actual.filter(__import__('pyarrow.compute').compute.equal(actual['trade_date'],20261111))['turnover_rate_status'].to_pylist()==['FIXTURE_INPUT_UNKNOWN']


@pytest.mark.parametrize('cap',[None,16])
def test_authority_forwards_auto_without_old_fixed_env_cap(tmp_path,monkeypatch,cap):
    import ast
    from ops import research_storage_retention as retention
    path=Path(owner.__file__).with_name('macos_research_panel_daily_authority.py')
    node=next(n for n in ast.parse(path.read_text()).body if isinstance(n,ast.FunctionDef)and n.name=='run_windows_a_formula_authority')
    captured={}
    def run(rebuild,**kwargs):
        captured.update(kwargs);return dict(selector=str(tmp_path/'s'),backtest=str(tmp_path/'b'),authority={},counts={})
    monkeypatch.setattr(retention,'run_with_retention',run);monkeypatch.setenv('RESEARCH_PANEL_QFQ_WORKERS','4')
    scope=dict(Path=Path,Any=object,__file__=str(path),_date=lambda x:x,_ensure_pointer_seed=lambda *a:None,_formula_artifact_binding=lambda *a:{})
    exec(compile(ast.Module(body=[node],type_ignores=[]),str(path),'exec'),scope)
    scope['run_windows_a_formula_authority'](tmp_path/'legacy',tdx_root=tmp_path,data_root=tmp_path,selector_pointer=tmp_path/'s.txt',backtest_pointer=tmp_path/'b.txt',selector_seed=None,backtest_seed=None,contract_csv=tmp_path/'fields',canonical_formula_path=tmp_path/'formula',return_root=tmp_path,target_date='20261111',formula_max_workers=cap)
    assert captured['workers']is cap and captured['refresh_inputs']is True and captured['storage_layout']=='arrow_blocks_v1'
