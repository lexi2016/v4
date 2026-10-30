"""Persistent received fields, exact identity joins and view-only theme filters."""
import copy,hashlib,json,subprocess
from pathlib import Path
from unittest.mock import patch
import pytest
from infrastructure.research_classification_view import ReceivedClassificationStore,import_received
from infrastructure.research_workbench_host import FLAGS

def ref(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,ensure_ascii=False));return dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest())
def source_row(symbol,name,instrument='A_SHARE',**fields):
    return dict(symbol=symbol,name=name,instrument_type=instrument,reference_date='2026-10-28',classification_status='VERIFIED_PARTIAL',missing_reason='细分仍缺失',main_industry='UNKNOWN',shortline_themes=[],shortline_subthemes=[],normalized_themes=[],external_themes=[],daily_catalyst={'text':'UNKNOWN','event_date':None,'evidence_ids':[]},**fields)
@pytest.fixture
def received(tmp_path):
    a=[source_row('600025.SH','华能水电'),source_row('002694.SZ','*ST顾地')]
    a[0]['shortline_themes']=[dict(label='机器人',evidence_ids=['e1'])];a[0]['normalized_themes']=[dict(label='芯片',evidence_ids=['e1'])];a[0]['official_industry']=dict(major_name='电力生产',published_at='2026-09-30',retrieved_at='2026-10-28T23:30:00+08:00')
    hk=[source_row('00001.HK','长和','HK_SHARE',eligibility_asof='2026-10-28',eligibility_status='BUY_AND_SELL'),source_row('06006.HK','历史仅卖','HK_SHARE',eligibility_asof='2026-10-28',eligibility_status='SELL_ONLY_RULE_DERIVED')]
    catalogs={'A_SHARE':a,'HK_CONNECT':hk,'CDR':[source_row('689009.SH','九号公司','CDR')]}
    refs={}
    for kind,rows in catalogs.items():
        value=dict(schema_version='market-baseline-v1',asof='2026-10-28',classification_complete=False,classifications=rows,sources=[dict(source_id='s1',url='https://example.test/source')],evidence=[dict(id='e1',symbol='600025.SH',source_id='s1',published_at='UNKNOWN',temporal_scope='SUPPLEMENTAL_LOOKUP')],gaps=[])
        if kind=='HK_CONNECT':value.update(explicit_buy_stock_count=1,rule_derived_sell_only_distinct_count=1,complete_sell_only_universe_certified=False,qualification_unresolved_records=[dict(code='12345',reason='UNKNOWN')])
        refs[kind]=ref(tmp_path/'inputs'/(kind+'.json'),value)
    root=tmp_path/'persistent';pointer=import_received(refs,root)
    return root,refs,pointer

def test_import_is_idempotent_and_reads_survive_original_input_removal(received):
    root,refs,pointer=received;store=ReceivedClassificationStore(root)
    assert import_received(refs,root)==pointer
    for source in refs.values():Path(source['path']).unlink()
    rows=[dict(symbol='600025.SH',display_name='华能水电'),dict(symbol='002694.SZ',display_name='顾地科技'),dict(symbol='689009.SH',display_name='九号公司')]
    original=copy.deepcopy(rows);first=store.join(rows);second=store.join(rows)
    assert first is second and rows==original
    assert first['identity_counts']=={'BOUND_EXACT_CODE_NAME':2,'IDENTITY_CONFLICT_NAME':1}
    assert first['rows']['002694.SZ']['classification'] is None
    assert first['rows']['689009.SH']['market_scope']=='CDR'
    assert len(first['rows']['600025.SH']['evidence'])==1 and first['catalogs']['A_SHARE']['metadata']['classification_complete'] is False
    hk=store.catalog('HK_CONNECT');assert hk['count']==2 and hk['metadata']['explicit_buy_stock_count']==1
    assert hk['extras']['qualification_unresolved_records'][0]['code']=='12345'
    assert all(r['eligibility_asof']=='2026-10-28' for r in hk['rows']) and hk['production_allowed'] is False

def test_new_source_version_changes_only_received_fields_and_rejects_bad_pointer(received):
    root,refs,old=received;store=ReceivedClassificationStore(root);before=store.version();rows=[dict(symbol='600025.SH',display_name='华能水电')]
    first=store.join(rows);raw=json.loads(Path(refs['A_SHARE']['path']).read_text());raw['classifications'][0]['normalized_themes']=[dict(label='商业航天',evidence_ids=['e1'])]
    refs['A_SHARE']=ref(Path(refs['A_SHARE']['path']),raw)
    Path(refs['HK_CONNECT']['path']).unlink();Path(refs['CDR']['path']).unlink()
    new=import_received(refs,root)
    manifest=json.loads((root/new['manifest']['path']).read_text());assert manifest['reused_markets']==['HK_CONNECT','CDR'] and manifest['imported_markets']==['A_SHARE']
    assert new['version']!=old['version'] and store.version()!=before
    assert store.join(rows)['rows']['600025.SH']['classification']['normalized_themes'][0]['label']=='商业航天'
    assert first['rows']['600025.SH']['classification']['normalized_themes'][0]['label']=='芯片'
    current=json.loads((root/'current.json').read_text());current['manifest']['path']='../escape.json';(root/'current.json').write_text(json.dumps(current))
    assert store.version().startswith('CANNOT_CONFIRM:')
    with pytest.raises(ValueError):store.catalog('A_SHARE')

def test_multilabel_union_unknown_and_name_conflict_do_not_change_pool():
    node='/Users/lexi/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node'
    script="""import assert from 'node:assert/strict';import {matchesClassification as match} from './research/stock_panel_collab_20261030/mac-host/classification-local.mjs';const row={symbol:'600025.SH',classification:{identity_status:'BOUND_EXACT_CODE_NAME',classification:{main_industry:'半导体',main_business:'UNKNOWN',shortline_themes:[{label:'机器人'},{label:'芯片'}],normalized_themes:[],daily_catalyst:{text:'UNKNOWN'}}}},unknown={symbol:'u',classification:{identity_status:'IDENTITY_CONFLICT_NAME',classification:null}},pool=[row,unknown],before=JSON.stringify(pool);assert.equal(pool.filter(r=>match(r,{labels:['机器人','芯片']})).length,1);assert(match(row,{query:'半导体 芯片'}));assert(!match(row,{labels:['商业航天']}));assert(!match(unknown,{labels:['芯片']}));assert(match(unknown,{}));assert.equal(JSON.stringify(pool),before);"""
    subprocess.run([node,'--input-type=module','-e',script],cwd=Path(__file__).resolve().parents[1],check=True,capture_output=True)

def test_readonly_hk_catalog_api_uses_saved_index_only(received,tmp_path,monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from infrastructure.research_workbench_host import create_workbench_router
    root,refs,pointer=received
    binding=ref(tmp_path/'binding.json',dict(schema='V4_MAC_WORKBENCH_BINDING_V1',classification_store_root=str(root),**FLAGS))
    monkeypatch.setenv('V4_WORKBENCH_HOST_BINDING',binding['path']);monkeypatch.setenv('V4_WORKBENCH_HOST_BINDING_SHA256',binding['sha256'])
    app=FastAPI();app.include_router(create_workbench_router(object()),prefix='/api/v4/research');client=TestClient(app)
    answer=client.get('/api/v4/research/workbench/classifications/HK_CONNECT')
    assert answer.status_code==200 and answer.json()['count']==2 and answer.json()['status'].startswith('PARTIAL')
    assert client.post('/api/v4/research/workbench/classifications/HK_CONNECT').status_code==405
