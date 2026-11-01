import hashlib,json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from infrastructure import research_workbench_host as wb


def _ref(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,sort_keys=True))
    return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}


@pytest.fixture
def fixture(tmp_path,monkeypatch):
    generation='a'*64;input_sha='b'*64;numeric={'path':'/frozen/manifest.json','sha256':'c'*64}
    relocation=_ref(tmp_path/'relocation.json',{'mode':'ISOLATED_READ_ONLY'})
    gate=_ref(tmp_path/'gate.json',{'status':'PASS_RELOCATED_SOURCE_GATE','canonical_input_sha256':input_sha,'relocation_ref':relocation})
    identity={'relocation_sha256':relocation['sha256'],'source_gate_sha256':gate['sha256'],'source_generation':generation}
    candidate=hashlib.sha256(json.dumps(identity,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()
    assets={}
    for kind in ('kb','projection','html'):
        path=tmp_path/(kind+'.bin');path.write_bytes((kind+' test').encode());assets[kind]={'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'bytes':path.stat().st_size}
    value={'schema':'v4.workbench.single_kb_binding.v1','symbol':'002865.SZ','name':'钧达股份','source_date':'2026-10-30','observation_date':'2026-11-02','source_generation':generation,'source_input_sha256':input_sha,'numeric_manifest':numeric,'candidate_pool_member':False,'historical_PIT':False,'candidate_identity':identity,'candidate_generation':candidate,'source_gate_receipt':gate,'source_relocation':relocation,'assets':assets,'fields_count':57,'rows':2311,**wb.FLAGS}
    binding=_ref(tmp_path/'single.json',value);host=wb.ResearchWorkbenchHost.__new__(wb.ResearchWorkbenchHost)
    host.binding={'single_stock_research':binding};host._view=lambda date,revision=None: {'source_generation':generation,'source_identity':{'input_sha256':input_sha},'manifest':numeric,'rows':[{'symbol':str(i)} for i in range(172)]} if revision in (None,generation) else (_ for _ in ()).throw(ValueError('REVISION_CONFLICT'))
    host._observation_date=lambda date:'2026-11-02';host.classifications=SimpleNamespace(close=lambda:None)
    return host,value,binding


def test_single_stock_binds_11_2_to_10_30_without_modifying_pool(fixture):
    host,value,_=fixture;before=host._view('2026-10-30')['rows'];answer=host.single_stock_research('2026-10-30','002865.SZ',value['source_generation'])
    assert answer['observation_date']=='2026-11-02' and answer['source_date']=='2026-10-30'
    assert answer['candidate_pool_member'] is False and len(before)==172
    assert host._view('2026-10-30')['rows']==before and answer['fields_count']==57
    assert answer['assets']['kb']['sha256']==value['assets']['kb']['sha256']


def test_wrong_date_symbol_generation_or_changed_asset_fails(fixture):
    host,value,_=fixture
    with pytest.raises(KeyError):host.single_stock_research('2026-11-02','002865.SZ')
    with pytest.raises(KeyError):host.single_stock_research('2026-10-30','000001.SZ')
    with pytest.raises(ValueError):host.single_stock_research('2026-10-30','002865.SZ','d'*64)
    with pytest.raises(ValueError,match='ASSET_SHA_CONFLICT'):host.single_stock_asset('2026-10-30','002865.SZ','kb','f'*64,value['source_generation'])
    Path(value['assets']['kb']['path']).write_text('changed')
    with pytest.raises(ValueError,match='SOURCE_SHA_DRIFT'):host.single_stock_asset('2026-10-30','002865.SZ','kb',value['assets']['kb']['sha256'],value['source_generation'])


def test_single_stock_http_endpoints_and_asset_headers(fixture,tmp_path,monkeypatch):
    host,value,_=fixture;outer=_ref(tmp_path/'outer.json',{'ok':True})
    monkeypatch.setenv('V4_WORKBENCH_HOST_BINDING',outer['path']);monkeypatch.setenv('V4_WORKBENCH_HOST_BINDING_SHA256',outer['sha256'])
    monkeypatch.setattr(wb,'ResearchWorkbenchHost',lambda source,binding:host)
    app=FastAPI();app.include_router(wb.create_workbench_router(object()))
    with TestClient(app) as client:
        root='/workbench/days/2026-10-30/single-research/002865.SZ';result=client.get(root,params={'revision':value['source_generation']});assert result.status_code==200
        url=root+'/assets/html';response=client.get(url,params={'revision':value['source_generation'],'sha256':value['assets']['html']['sha256']})
        assert response.status_code==200 and response.content==b'html test'
        assert "frame-ancestors 'self'" in response.headers['content-security-policy']
        assert client.get(root,params={'revision':'f'*64}).status_code==409


def test_single_stock_score_contract_is_sha_bound(fixture,tmp_path):
    host,value,binding=fixture
    contract=_ref(tmp_path/'score.json',{'schema':'a_share_kb_hold_score_v1',**wb.FLAGS})
    value['hold_score_contract']=contract;value['hold_score_engine_sha256']='e'*64
    value['candidate_identity']['score_contract_sha256']=contract['sha256']
    value['candidate_identity']['score_engine_sha256']='e'*64
    value['candidate_generation']=hashlib.sha256(json.dumps(value['candidate_identity'],sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()
    new_binding=_ref(Path(binding['path']),value);host.binding['single_stock_research']=new_binding
    result=host.single_stock_research('2026-10-30','002865.SZ',value['source_generation'])
    assert result['hold_score_contract_sha256']==contract['sha256']
    assert result['hold_score_engine_sha256']=='e'*64
    Path(contract['path']).write_text('{}')
    with pytest.raises(ValueError,match='SOURCE_SHA_DRIFT'):
        host.single_stock_research('2026-10-30','002865.SZ',value['source_generation'])


def test_single_stock_supplemental_contract_is_sha_bound(fixture,tmp_path):
    host,value,binding=fixture
    contract=_ref(tmp_path/'supplemental.json',{'schema':'a_share_kb_supplemental_signals_v1',**wb.FLAGS})
    value['supplemental_contract']=contract
    value['candidate_identity']['supplemental_contract_sha256']=contract['sha256']
    value['candidate_generation']=hashlib.sha256(json.dumps(value['candidate_identity'],sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()
    host.binding['single_stock_research']=_ref(Path(binding['path']),value)
    assert host.single_stock_research('2026-10-30','002865.SZ',value['source_generation'])['supplemental_contract_sha256']==contract['sha256']
    Path(contract['path']).write_text('{}')
    with pytest.raises(ValueError,match='SOURCE_SHA_DRIFT'):
        host.single_stock_research('2026-10-30','002865.SZ',value['source_generation'])


def test_single_stock_action_contract_is_sha_bound(fixture,tmp_path):
    host,value,binding=fixture
    contract=_ref(tmp_path/'action.json',{'schema':'a_share_kb_action_v1',**wb.FLAGS})
    value['action_contract']=contract
    value['candidate_identity']['action_contract_sha256']=contract['sha256']
    value['candidate_generation']=hashlib.sha256(json.dumps(value['candidate_identity'],sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()
    host.binding['single_stock_research']=_ref(Path(binding['path']),value)
    assert host.single_stock_research('2026-10-30','002865.SZ')['action_contract_sha256']==contract['sha256']
    Path(contract['path']).write_text('{}')
    with pytest.raises(ValueError,match='SOURCE_SHA_DRIFT'):
        host.single_stock_research('2026-10-30','002865.SZ',value['source_generation'])


def test_single_stock_yidong_contract_is_sha_bound(fixture,tmp_path):
    host,value,binding=fixture
    contract=_ref(tmp_path/'yidong.json',{'schema':'a_share_kb_yidong_v1',**wb.FLAGS})
    value['yidong_contract']=contract
    value['candidate_identity']['yidong_contract_sha256']=contract['sha256']
    value['candidate_generation']=hashlib.sha256(json.dumps(value['candidate_identity'],sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()
    host.binding['single_stock_research']=_ref(Path(binding['path']),value)
    assert host.single_stock_research('2026-10-30','002865.SZ')['yidong_contract_sha256']==contract['sha256']
    Path(contract['path']).write_text('{}')
    with pytest.raises(ValueError,match='SOURCE_SHA_DRIFT'):
        host.single_stock_research('2026-10-30','002865.SZ',value['source_generation'])


def test_display_projection_binds_f10_and_does_not_fill_history(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq
    exclusions=['B1']+['excluded_'+str(i) for i in range(24)]
    policy=_ref(tmp_path/'policy.json',{'schema':'a_share_single_display_projection_v1',
        'authorized_symbols':['002865.SZ'],'excluded_from_display_projection':exclusions,**wb.FLAGS})
    f10=_ref(tmp_path/'f10.json',{'symbol':'002865.SZ','status':'OBSERVED','concept_status':'OBSERVED',
        'captured_at':'2026-11-01T14:27:02+00:00','concepts':[{'name':'光伏'}]})
    generation='a'*64;roles={}
    def file_ref(path):return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    for role in ('selector','backtest'):
        full=pa.table({'trade_date':[20261029,20261030],'B1':[0,1],
                       'kb_hold_volume_ok_reason':['RULE_NOT_QUANTIFIED',None]})
        full=full.replace_schema_metadata({b'kb_single_candidate_v1':json.dumps({'candidate_generation':generation}).encode()})
        full_path=tmp_path/(role+'_full.parquet');pq.write_table(full,full_path);source_ref=file_ref(full_path)
        metadata={'candidate_generation':generation,'symbol':'002865.SZ','role':role,'source_full_sha256':source_ref['sha256'],
            'policy_sha256':policy['sha256'],'f10_sha256':f10['sha256'],'captured_at':'2026-11-01T14:27:02+00:00',
            'historical_PIT':False,**wb.FLAGS}
        projected=pa.table({'trade_date':[20261029,20261030],'kb_hold_volume_ok_reason':['RULE_NOT_QUANTIFIED',None],
                            'kb_concepts':pa.array([None,'光伏'],type=pa.string()),'kb_concept_count':pa.array([None,1],type=pa.int8())})
        projected=projected.replace_schema_metadata({b'a_share_single_display_projection_v1':json.dumps(metadata).encode()})
        path=tmp_path/(role+'_display.parquet');pq.write_table(projected,path)
        roles[role]={'artifact':file_ref(path),'source_full':source_ref,'rows':2,'columns':4}
    display={'policy':policy,'f10_source':f10,'captured_at':'2026-11-01T14:27:02+00:00',
             'kb_concepts':'光伏','kb_concept_count':1,'historical_PIT':False,'roles':roles}
    binding={'symbol':'002865.SZ','candidate_generation':generation,'display_projection':display}
    identity={'display_policy_sha256':policy['sha256'],'display_f10_sha256':f10['sha256']}
    assert wb.checked_single_display_projection(binding,identity)['selector_columns']==4
    path=Path(roles['selector']['artifact']['path']);changed=pq.read_table(path)
    changed=changed.set_column(2,changed.schema.field(2),pa.array(['光伏','光伏']))
    pq.write_table(changed,path);roles['selector']['artifact']=file_ref(path)
    with pytest.raises(ValueError,match='SINGLE_DISPLAY_CONCEPT_HISTORY_CONFLICT'):
        wb.checked_single_display_projection(binding,identity)


def test_field_inventory_is_bound_to_contracts_and_candidate(fixture,tmp_path):
    host,value,binding=fixture
    score=_ref(tmp_path/'score.json',{'schema':'a_share_kb_hold_score_v1','materialized_fields':{'score':['kb_hold_score']},**wb.FLAGS})
    extra=_ref(tmp_path/'supplemental.json',{'schema':'a_share_kb_supplemental_signals_v1','fields':[{'name':'kb_s1'}],**wb.FLAGS})
    inventory={'base_kb_fields':57,'hold_score_fields':['kb_hold_score'],'supplemental_fields':['kb_s1'],
               'total_new_fields':2,'total_derived_fields':59,'display_only_metadata':[]}
    value.update(hold_score_contract=score,hold_score_engine_sha256='e'*64,supplemental_contract=extra,field_inventory=inventory)
    value['candidate_identity'].update(score_contract_sha256=score['sha256'],score_engine_sha256='e'*64,
                                       supplemental_contract_sha256=extra['sha256'],field_inventory=inventory.copy())
    value['candidate_generation']=hashlib.sha256(json.dumps(value['candidate_identity'],sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()
    host.binding['single_stock_research']=_ref(Path(binding['path']),value)
    assert host.single_stock_research('2026-10-30','002865.SZ')['field_inventory']==inventory
    value['field_inventory']={**inventory,'total_derived_fields':57}
    host.binding['single_stock_research']=_ref(Path(binding['path']),value)
    with pytest.raises(ValueError,match='SINGLE_STOCK_FIELD_INVENTORY_CONFLICT'):
        host.single_stock_research('2026-10-30','002865.SZ')


def test_history_relocation_only_reads_declared_sha_and_footer(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq
    backup=tmp_path/'frozen.parquet.bak';table=pa.table({'trade_date':['20261030']})
    table=table.replace_schema_metadata({b'kb_single_candidate_v1':json.dumps({'candidate_generation':'a'*64,'source_generation':'b'*64}).encode()})
    pq.write_table(table,backup)
    digest=hashlib.sha256(backup.read_bytes()).hexdigest();original={'path':str(tmp_path/'original.parquet'),'sha256':digest}
    mapping={'original_path':original['path'],'expected_sha256':digest,'physical_path':str(backup),'physical_sha256':digest,
             'candidate_generation':'a'*64,'source_generation':'b'*64,'parquet_columns':1}
    manifest=_ref(tmp_path/'relocation.json',{'schema':'v4.single_stock_history_source_relocation.v1',
        'mode':'EXPLICIT_SHA_BOUND_READ_ONLY','SEARCH_FALLBACK':False,'mappings':[mapping],**wb.FLAGS})
    assert wb.checked_relocated_parquet(original,manifest)==backup.read_bytes()
    with pytest.raises(ValueError,match='RELOCATION_SOURCE_MISMATCH'):
        wb.checked_relocated_parquet({**original,'path':str(tmp_path/'other.parquet')},manifest)
    backup.write_bytes(b'changed')
    with pytest.raises(ValueError,match='SOURCE_SHA_DRIFT'):
        wb.checked_relocated_parquet(original,manifest)


def test_two_bound_stocks_keep_actual_pool_membership(fixture,tmp_path):
    host,junda,_=fixture
    gold={**junda,'symbol':'301048.SZ','name':'金鹰重工','candidate_pool_member':True}
    gold['candidate_identity']={**junda['candidate_identity'],'symbol':'301048.SZ'}
    gold['candidate_generation']=hashlib.sha256(json.dumps(gold['candidate_identity'],sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()
    host.binding['single_stock_research_by_symbol']={'301048.SZ':_ref(tmp_path/'gold.json',gold)}
    old_view=host._view
    host._view=lambda date,revision=None:{**old_view(date,revision),'rows':[{'symbol':'301048.SZ'}]+[{'symbol':str(i)} for i in range(171)]}
    assert host.single_stock_research('2026-10-30','301048.SZ')['candidate_pool_member'] is True
    assert host.single_stock_research('2026-10-30','002865.SZ')['candidate_pool_member'] is False
    gold['candidate_pool_member']=False
    host.binding['single_stock_research_by_symbol']['301048.SZ']=_ref(tmp_path/'gold.json',gold)
    with pytest.raises(ValueError,match='SINGLE_STOCK_SOURCE_IDENTITY_CONFLICT'):
        host.single_stock_research('2026-10-30','301048.SZ')
