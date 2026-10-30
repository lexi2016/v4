"""Completion publication, row parity, sidecar preservation and real UI source."""
import copy
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest
from infrastructure.research_lane_source import ResearchLaneSource
from ops.bootstrap_stock_event_history import load, ref, save
from ops.sync_stock_history_completion import prepare, publish, Staging


def fixture(tmp_path):
    root, batch, stage = (tmp_path/name for name in ('root','batch','stage'))
    root.mkdir();batch.mkdir()
    owner_lock=tmp_path/'A_LONG.lock';owner_lock.touch()
    symbols=['000554.SZ','001328.SZ']
    identity=dict(generation='g',input_sha256='i',basis={'price_basis':'QFQ_ASOF'},asof=20261029)
    code=[]
    for name in ['runner.py','ops/research_panel_daily_product.py','rule.py','stats.py']:
        path=tmp_path/name
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text('from ops.research_panel_daily_product import save\n' if name.endswith('research_panel_daily_product.py') else '# fixture\n')
        code.append(ref(path))
    config=save(tmp_path/'config.json',dict(formula={'sha256':'f'},**__import__('ops.sync_stock_history_completion',fromlist=['FLAGS']).FLAGS))
    flags=dict(RESEARCH_ONLY=True,production_allowed=False,buy_gate_updated=False,orders_sent=False)
    stats={'asof':'2026-10-29','groups':[dict(group_id='original',horizons={key:dict(total=1) for key in ['d2','d5']})]}
    rows={s:dict(symbol=s,data_date='20261029',groups='original',statistics=copy.deepcopy(stats),historical_coverage=dict(known_full_history=False,missing=['bootstrap']),**flags) for s in symbols}
    row_refs={s:save(root/'old'/f'{s}.json',row) for s,row in rows.items()}
    product=dict(schema_version='v4.a_share.daily_product.v1',data_date='20261029',source_generation='g',source_identity=identity,source_config=config,row_refs=row_refs,rows=[{'symbol':s,'groups':'original'} for s in symbols],**flags)
    artifact=save(root/'old/product.json',product)
    manifest=save(root/'old/manifest.json',dict(schema_version='v4.a_share.daily_product_manifest.v1',artifact=artifact,data_date='20261029',source_generation='g',input_sha256='i',**flags))
    materials={s:save(root/'materials'/f'{s}.json',dict(symbol=s,numeric_manifest=manifest,**flags)) for s in symbols}
    material_index=save(root/'materials/index.json',dict(items=materials,numeric_manifest=manifest,**flags))
    events_index=save(root/'cases/index.json',dict(items={},numeric_manifest=manifest,**flags))
    names=save(root/'names.json',dict(items={},numeric_manifest=manifest,**flags))
    chart=save(root/'chart.json',dict(samples={},**flags));receipt=save(root/'receipt.json',flags)
    index=dict(dates={'20261029':manifest},latest_date='20261029',latest=manifest,original_charts={'20261029':dict(chart_origin_manifest=manifest,history_updated_symbols=[],numeric_manifest=manifest,manifest=chart,receipt=receipt)},display_names={'20261029':names},company_materials={'20261029':material_index},event_cases={'20261029':events_index},**flags)
    save(root/'index.json',index);save(root/'events/latest.json',dict(manifest=manifest,artifact=artifact,data_date='20261029',source_generation='g',input_sha256='i',**flags))
    calendar=save(tmp_path/'calendar.json',dict(dates={'SZ':[20261027,20261028,20261029,20261030]},**flags))
    projection=save(tmp_path/'projection.json',flags)
    contract=dict(config={'target':20261029,'symbols':symbols},code=code,source_generation='g',source_identity=identity,input_sha256='i',refs=dict(numeric_product=artifact,source_config=config,calendar=calendar),entries={s:dict(rows=2,projection=projection) for s in symbols},**flags)
    contract_ref=save(batch/'CONTRACT.json',contract);save(batch/'RUN_AUTHORIZATION_R2.json',dict(status='ROOT_RUN_STARTED_REGISTERED',contract=contract_ref,contract_sha256=contract_ref['sha256']))
    symbol='001328.SZ';row=copy.deepcopy(rows[symbol]);row['historical_coverage']=dict(known_full_history=True,missing=[])
    new_row=save(batch/'row.json',row)
    history=save(batch/'history.json',dict(source_identity=identity,rule_sha256=code[2]['sha256'],evaluations={'20261027':{'groups':{'original':'TRUE'}},'20261029':{'groups':{'original':'FALSE'}}},**flags))
    from ops.bootstrap_stock_event_history import canonical
    import hashlib
    cases=save(batch/'case.json',dict(symbol=symbol,data_date='20261029',contract=contract_ref,accepted_cache=history,projection=projection,calendar=calendar,numeric_manifest=manifest,source_generation='g',input_sha256='i',statistics_sha256=hashlib.sha256(canonical(row['statistics'])).hexdigest(),groups={'original':{key:dict(total=1,cases=[{'event_date':'2026-10-27'}]) for key in ['d2','d5']}},**flags))
    result=save(batch/'stocks'/symbol/'RESULT.json',dict(symbol=symbol,status='COMPLETE_DESCRIPTIVE_NONPIT',contract=contract_ref,row=new_row,history_cache=history,event_cases=cases,remaining_dates=[],**flags))
    return SimpleNamespace(root=root,batch=batch,stage=stage,rows=rows,original=index,result=result,owner_lock=owner_lock)


def test_completion_changes_only_statistics_and_rebinds_sidecars_without_material_copy(tmp_path):
    f=fixture(tmp_path)
    before=(f.root/'index.json').read_bytes()
    plan=prepare(f.batch,f.root,f.stage,owner_lock=f.owner_lock)
    assert (f.root/'index.json').read_bytes()==before
    assert plan['completed']==['001328.SZ']
    writer=Staging(f.root,f.stage);writer.files=plan['immutable_files']
    product=writer.read(plan['artifact'])
    original=load(load(f.original['latest'])['artifact'])
    assert product['rows']==original['rows']
    assert product['row_refs']['000554.SZ']==original['row_refs']['000554.SZ']
    index=load(plan['staged_index'])
    material=writer.read(index['company_materials']['20261029'])
    assert material['items']==load(f.original['company_materials']['20261029'])['items']
    assert material['source_numeric_manifest']==f.original['latest']
    assert index['history_sync']['20261029']['candidate_symbols']==['000554.SZ','001328.SZ']
    published=publish(plan)
    assert published['status']=='PUBLISHED_HISTORY_SYNC'
    completion=load(published['event'])
    for key in ['company_materials','event_cases','display_names']:
        assert completion[key]==index[key]['20261029']
    assert prepare(f.batch,f.root,f.stage/'repeat',owner_lock=f.owner_lock)['status']=='NO_NEW_COMPLETION'


def test_publication_fails_closed_on_index_cas_drift(tmp_path):
    f=fixture(tmp_path);plan=prepare(f.batch,f.root,f.stage,owner_lock=f.owner_lock)
    index=json.loads((f.root/'index.json').read_text());index['other_task']='preserve';save(f.root/'index.json',index)
    with pytest.raises(ValueError,match='FROZEN_REFERENCE_DRIFT'):
        publish(plan)
    assert json.loads((f.root/'index.json').read_text())['other_task']=='preserve'


def test_nonstatistical_change_is_rejected_before_publication(tmp_path):
    f=fixture(tmp_path);result=load(f.result);row=load(result['row']);row['groups']='nav_pullback';result['row']=save(f.batch/'altered_row.json',row);save(Path(f.result['path']),result)
    with pytest.raises(ValueError,match='NONSTAT_PARITY'):
        prepare(f.batch,f.root,f.stage,owner_lock=f.owner_lock)


def test_multi_stock_chart_bridge_reads_only_requested_changed_rows_and_rejects_declared_delta():
    origin=dict(row_refs={'000554.SZ':{'path':'oldA'},'001328.SZ':{'path':'oldB'}},rows=[{'symbol':'000554.SZ'},{'symbol':'001328.SZ'}],source_generation='g',source_identity={'input_sha256':'i'})
    product={**origin,'row_refs':{'000554.SZ':{'path':'newA'},'001328.SZ':{'path':'newB'}}}
    descriptor=dict(chart_origin_manifest={'path':'mf'},history_updated_symbols=['000554.SZ','001328.SZ'])
    values={'mf':dict(artifact={'path':'origin'},schema_version='v4.a_share.daily_product_manifest.v1',data_date='20261029',source_generation='g',input_sha256='i'),'origin':origin,'oldA':{'groups':'original','statistics':1},'newA':{'groups':'original','statistics':2}}
    reads=[];reader=ResearchLaneSource.__new__(ResearchLaneSource)
    reader._a_product_reference=lambda r:(reads.append(r['path']) or values[r['path']])
    reader._a_daily_checkpoint_binding=lambda *args:None
    answer=reader._a_chart_history_origin(product,descriptor,'20261029','000554.SZ')
    assert answer['row_refs']==origin['row_refs']
    assert reads==['mf','origin','oldA','newA']
    descriptor['history_updated_symbols']=['000554.SZ']
    with pytest.raises(ValueError,match='DELTA_INVALID'):
        reader._a_chart_history_origin(product,descriptor,'20261029','000554.SZ')


def test_same_date_completion_keeps_selected_stock_and_sidebar_filter_and_pending_rate_is_hidden():
    node='/Users/lexi/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node'
    script=r'''
const assert=require('assert'),fs=require('fs'),source=fs.readFileSync('research-panel/numeric283-panel.js','utf8');
const body=source.slice(source.indexOf('function commitPayload('),source.indexOf('\n    async function loadDated'));
const calls=[],els=new Map(),document={getElementById(id){if(!els.has(id))els.set(id,{textContent:'',hidden:false});return els.get(id)}};
const api=new Function('document','calls',`let selectedSymbol='000554.SZ',payloadMetadata={data_date:'20261029',source_generation:'g',artifact:{sha256:'old'}},chartRequest=1,chartController={abort(){}},currentRows=[];const EXPECTED={schema_version:'legacy'},validateDatedData=p=>p.rows,validateData=p=>p.rows,keepCurrentProductBinding=(a,b)=>b,clearOriginalChart=()=>{},windowObject={},setChartControlsDisabled=()=>{},download={},setupReaderLayout=()=>{},GROUP_LABELS={},groupSelect={value:'nav_pullback',options:[]},chartStatus={},refresh=()=>{},status={},loadChart=(s)=>{calls.push(s);selectedSymbol=s;};${body};return {commit:commitPayload,state:()=>({selectedSymbol,group:groupSelect.value})};`)(document,calls);
api.commit({schema_version:'new',data_date:'20261029',source_generation:'g',artifact:{sha256:'new'},rows:[{symbol:'002003.SZ'},{symbol:'000554.SZ'}],group_counts:{}});
assert.deepStrictEqual(calls,['000554.SZ']);assert.deepStrictEqual(api.state(),{selectedSymbol:'000554.SZ',group:'nav_pullback'});
const statsBody=source.slice(source.indexOf('function showStatistics('),source.indexOf('\n    function commitPayload'));
const pending=new Function('document',`let chartRequest=1,currentStatistics;const chartController={signal:null},sameRef=()=>true,payloadMetadata={data_date:'20261029',source_generation:'g'},windowObject={fetch:async()=>({json:async()=>({status:'READY',source_generation:'g',data_date:'20261029',history_sync:{status:'IN_PROGRESS'},row:{symbol:'000554.SZ',historical_coverage:{evaluated_count:1,available_prefix_dates:7887}}})})},renderStatistics=()=>{throw Error('pending must not display rate')};${statsBody};showStatistics('000554.SZ',1);`)(document);
setTimeout(()=>{assert(document.getElementById('dailyEventStatistics').textContent.includes('历史统计补齐中 · 已发布历史覆盖 1/7887'));assert(!document.getElementById('dailyEventStatistics').textContent.includes('已保留断点'));},0);
'''
    result = subprocess.run([node,'-e',script],cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True)
    assert result.returncode == 0, result.stderr


def test_later_main_product_or_event_cannot_be_replaced_by_older_batch(tmp_path):
    f=fixture(tmp_path)
    index=load(ref(f.root/'index.json'));index['latest_date']='20261030';save(f.root/'index.json',index)
    with pytest.raises(ValueError,match='LATEST_PRODUCT_OR_COMPLETION_EVENT_MOVED'):
        prepare(f.batch,f.root,f.stage,owner_lock=f.owner_lock)
    save(f.root/'index.json',f.original)
    event=load(ref(f.root/'events/latest.json'));event['data_date']='20261030';save(f.root/'events/latest.json',event)
    with pytest.raises(ValueError,match='LATEST_PRODUCT_OR_COMPLETION_EVENT_MOVED'):
        prepare(f.batch,f.root,f.stage,owner_lock=f.owner_lock)


def test_shared_owner_lock_is_same_stable_inode_and_reconciles_after_wait(tmp_path):
    f=fixture(tmp_path);plan=prepare(f.batch,f.root,f.stage,owner_lock=f.owner_lock)
    assert plan['shared_owner_lock']['inode']==f.owner_lock.stat().st_ino
    called=[]
    def refresh():
        import fcntl,os
        fd=os.open(f.owner_lock,os.O_RDONLY)
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        finally:
            os.close(fd)
        called.append(True)
        return prepare(f.batch,f.root,f.stage/'reconciled',owner_lock=f.owner_lock)
    assert publish(plan,refresh=refresh)['status']=='PUBLISHED_HISTORY_SYNC'
    assert called==[True]
