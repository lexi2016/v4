import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ops.research_panel_f10 import FLAGS, _concept_section, bound_universe, complete_f10, fetch_one, publish_f10_completion


def test_f10_uses_exchange_mapping_and_missing_source_is_not_empty_success():
    calls=[]
    class API:
        def connect(self,*host):return True
        def get_company_info_category(self,market,code):calls.append((market,code));return []
        def disconnect(self):pass
    vendor=(SimpleNamespace(TdxHq_API=API),None)
    value=fetch_one('301048.SZ','SZ',api_factory=API,vendor=vendor)
    assert value['status']=='FAILED' and 'F10_CATEGORY_MISSING' in value['reason']
    assert calls==[(0,'301048')]
    bj=fetch_one('920123.BJ','BJ',api_factory=API,vendor=vendor)
    assert bj['status']=='FAILED' and bj['reason']=='F10_COMPONENTS_INCOMPLETE'
    assert calls[-1]==(0,'920123')
    absent=fetch_one('920123.BJ',None,api_factory=API,vendor=vendor)
    assert absent['status']=='SOURCE_IDENTITY_UNAVAILABLE' and absent['reason']=='BOUND_PANEL_EXCHANGE_MISSING'
    text='【3.概念板块】\n｜高端装备｜内容｜\n【4.风险提示】\n｜旧风险｜不能算概念｜'
    assert '旧风险' not in _concept_section(text)


def test_f10_content_ranges_reassemble_before_strict_gbk_decode():
    import base64
    from ops.research_panel_f10 import _read_company_text,F10_CONTENT_CHUNK_BYTES
    raw=b'a'*(F10_CONTENT_CHUNK_BYTES-1)+'汉'.encode('gbk')+b'z'
    calls=[]
    class Command:
        def __init__(self,client,lock=None):pass
        def setParams(self,market,code,filename,start,length):self.start=start;self.length=length;calls.append((start,length))
        def call_api(self):return raw[self.start:self.start+self.length]
    api=SimpleNamespace(client=object(),lock=None)
    text,proof=_read_company_text(api,0,'000408',{'start':0,'length':len(raw),'filename':'000408.txt'},command_factory=Command)
    assert text.endswith('汉z') and calls==[(0,F10_CONTENT_CHUNK_BYTES),(F10_CONTENT_CHUNK_BYTES,2)]
    assert proof['declared_bytes']==proof['received_bytes']==len(raw) and base64.b64decode(proof['raw_base64'])==raw
    class Short(Command):
        def call_api(self):return super().call_api()[:-1]
    with pytest.raises(ValueError,match='F10_CONTENT_SHORT_READ'):
        _read_company_text(api,0,'000408',{'start':0,'length':len(raw),'filename':'000408.txt'},command_factory=Short)
    raw=b'\x81'
    with pytest.raises(ValueError,match='F10_CONTENT_GBK_INVALID'):
        _read_company_text(api,0,'000408',{'start':0,'length':1,'filename':'000408.txt'},command_factory=Command)


def test_f10_completion_is_receipt_bound_and_resume_reuses_success(tmp_path):
    panel=tmp_path/'panel.parquet';pq.write_table(pa.table({'ts_code':['002865.SZ','301048.SZ'],'exchange':['SZ','SZ']}),panel)
    context=SimpleNamespace(scope=['002865.SZ','301048.SZ'],panel=panel,target=20261030,generation='a'*64,
                            identity={'selector_artifact_sha256':'b'*64,'input_sha256':'c'*64},unchanged=lambda:None)
    receipt=tmp_path/'receipt.json';receipt.write_text(json.dumps({'schema':'V4_A_DAILY_DERIVATIVES_V1',
        'status':'COMPLETE_DESCRIPTIVE_NONPIT','data_date':'20261030','source_generation':'a'*64,**FLAGS}))
    ref={'path':str(receipt),'sha256':hashlib.sha256(receipt.read_bytes()).hexdigest()};seen=[]
    def fetch(code,exchange):
        seen.append((code,exchange));return {'symbol':code,'exchange':exchange,'status':'OBSERVED','historical_PIT':False,**FLAGS}
    first=complete_f10(context,ref,tmp_path/'out',workers=2,fetch=fetch)
    second=complete_f10(context,ref,tmp_path/'out',workers=2,fetch=lambda *_:pytest.fail('already observed symbol fetched again'))
    assert first['status']==second['status']=='COMPLETE' and first['requested']==first['observed']==2
    assert json.loads(Path(first['receipt']['path']).read_text())['scope']['kind']=='ADMITTED_DAILY_UNIVERSE'
    assert sorted(seen)==[('002865.SZ','SZ'),('301048.SZ','SZ')]
    with pytest.raises(ValueError,match='OUTSIDE_DAILY_SCOPE'):
        complete_f10(context,ref,tmp_path/'out',requested=['000001.SZ'],fetch=fetch)
    with pytest.raises(ValueError,match='WORKER_LIMIT'):
        complete_f10(context,ref,tmp_path/'out',workers=5,fetch=fetch)
    receipt.write_text('{}')
    with pytest.raises(ValueError,match='REFERENCE_SHA_DRIFT'):
        complete_f10(context,ref,tmp_path/'out',fetch=fetch)


def test_partial_receipt_checkpoint_survives_successful_resume(tmp_path):
    panel=tmp_path/'panel.parquet';pq.write_table(pa.table({'ts_code':['002865.SZ','301048.SZ'],'exchange':['SZ','SZ']}),panel)
    context=SimpleNamespace(scope=['002865.SZ','301048.SZ'],panel=panel,target=20261030,generation='a'*64,
                            identity={'selector_artifact_sha256':'b'*64,'input_sha256':'c'*64},unchanged=lambda:None)
    receipt=tmp_path/'receipt.json';receipt.write_text(json.dumps({'schema':'V4_A_DAILY_DERIVATIVES_V1',
        'status':'COMPLETE_DESCRIPTIVE_NONPIT','data_date':'20261030','source_generation':'a'*64,**FLAGS}))
    ref={'path':str(receipt),'sha256':hashlib.sha256(receipt.read_bytes()).hexdigest()}
    def partial(code,exchange):
        return {'symbol':code,'exchange':exchange,'status':'FAILED' if code=='301048.SZ' else 'OBSERVED',**FLAGS}
    first=complete_f10(context,ref,tmp_path/'out',workers=1,fetch=partial)
    prior=json.loads(Path(first['receipt']['path']).read_text());checkpoint=Path(prior['checkpoint']['path']);before=checkpoint.read_bytes()
    assert first['status']=='PARTIAL' and len(json.loads(before)['items'])==1
    second=complete_f10(context,ref,tmp_path/'out',workers=1,fetch=lambda code,exchange:{'symbol':code,'exchange':exchange,'status':'OBSERVED',**FLAGS})
    assert second['status']=='COMPLETE' and checkpoint.read_bytes()==before
    assert hashlib.sha256(before).hexdigest()==prior['checkpoint']['sha256']
    assert len(json.loads(Path(json.loads(Path(second['receipt']['path']).read_text())['checkpoint']['path']).read_text())['items'])==2


def test_f10_completion_publishes_bound_reference_without_mutating_upstream(tmp_path, monkeypatch):
    import ops.sync_stock_history_completion as owner
    from infrastructure.research_workbench_host import ResearchWorkbenchHost
    root=tmp_path/'product';(root/'events').mkdir(parents=True)
    panel=tmp_path/'panel.parquet';pq.write_table(pa.table({'ts_code':['301048.SZ'],'exchange':['SZ']}),panel)
    context=SimpleNamespace(scope=['301048.SZ'],panel=panel,target=20261030,generation='a'*64,
        identity={'selector_artifact_sha256':'b'*64,'input_sha256':'c'*64},unchanged=lambda:None)
    def save(path, payload):
        path.write_text(json.dumps(payload,sort_keys=True));return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    upstream=save(tmp_path/'upstream.json',{'schema':'V4_A_DAILY_DERIVATIVES_V1','status':'COMPLETE_DESCRIPTIVE_NONPIT',
        'data_date':'20261030','source_generation':context.generation,**FLAGS})
    manifest=save(root/'manifest.json',{'source_generation':context.generation,'input_sha256':context.identity['input_sha256']})
    save(root/'index.json',{'dates':{'20261030':manifest},'existing':'preserved'})
    save(root/'events/latest.json',{'data_date':'20261030','source_generation':context.generation,
        'input_sha256':context.identity['input_sha256'],'manifest':manifest,'event_id':'old','existing':'preserved'})
    lock=tmp_path/'owner.lock';lock.touch()
    monkeypatch.setattr(owner,'DEFAULT_OWNER_LOCK',lock)
    monkeypatch.setattr(owner,'_inherited_owner_duplicate',lambda *_:None,raising=False)
    result=complete_f10(context,upstream,root,workers=1,fetch=lambda code,exchange:{
        'symbol':code,'exchange':exchange,'status':'OBSERVED','historical_PIT':False,'concepts':[],**FLAGS})
    published=publish_f10_completion(context,root,result['receipt'])
    index=json.loads((root/'index.json').read_text());event=json.loads((root/'events/latest.json').read_text())
    assert published['status']=='PUBLISHED_F10_COMPLETION' and index['f10']['20261030']==event['f10']==result['receipt']
    assert index['existing']==event['existing']=='preserved' and event['event_id']!='old'
    assert hashlib.sha256(Path(upstream['path']).read_bytes()).hexdigest()==upstream['sha256']
    host=ResearchWorkbenchHost.__new__(ResearchWorkbenchHost)
    host.binding={}
    host._view=lambda *_:{'rows':[{'symbol':'301048.SZ'}],'source_generation':context.generation,'source_identity':context.identity}
    def read_ref(ref):
        raw=Path(ref['path']).read_bytes()
        assert hashlib.sha256(raw).hexdigest()==ref['sha256']
        return json.loads(raw)
    host.source=SimpleNamespace(_a_product_root=lambda:root,_a_product_reference=read_ref)
    assert host.f10('2026-10-30','301048.SZ')['status']=='OBSERVED'
    assert host.f10('2026-10-30','301048.SZ')['stock_ref']==json.loads(Path(read_ref(result['receipt'])['checkpoint']['path']).read_text())['items']['301048.SZ']
    before_index=(root/'index.json').read_bytes();before_event=(root/'events/latest.json').read_bytes()
    with pytest.raises(ValueError,match='F10_EXPECTED_INDEX_EVENT_CAS_MOVED'):
        publish_f10_completion(context,root,result['receipt'],expected_index_sha256='0'*64,expected_event_sha256='1'*64)
    old_receipt=read_ref(result['receipt']);existing_checkpoint=read_ref(old_receipt['checkpoint'])
    empty_checkpoint=save(root/'empty.json',{**existing_checkpoint,'items':{}})
    narrower=save(root/'narrower.json',{**old_receipt,'requested':0,'observed':0,'checkpoint':empty_checkpoint,
                                      'scope':{'kind':'EXPLICIT_SYMBOLS','count':0,'symbols':[]}})
    with pytest.raises(ValueError,match='F10_COVERAGE_REGRESSION'):
        publish_f10_completion(context,root,narrower)
    assert (root/'index.json').read_bytes()==before_index and (root/'events/latest.json').read_bytes()==before_event
    context.identity['input_sha256']='d'*64
    with pytest.raises(ValueError,match='F10_PUBLICATION_RECEIPT_CONFLICT'):
        publish_f10_completion(context,root,result['receipt'])


def test_existing_f10_source_reuse_requires_symbol_market_sha_and_origin(tmp_path):
    from ops.research_panel_f10 import verified_reuse_sources
    def save(name,value):
        path=tmp_path/name;path.write_text(json.dumps(value,ensure_ascii=False));return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    text='◇000001 平安银行 更新日期：2026-10-30◇'
    stock={'symbol':'000001.SZ','exchange':'SZ','status':'OBSERVED','captured_at':'2026-11-02T00:00:00Z',
           'source_text':text,'source_text_sha256':hashlib.sha256(text.encode()).hexdigest(),
           'finance_native_raw':{'code':'000001','market':0},'historical_PIT':False,**FLAGS}
    stock_ref=save('stock.json',stock);origin=save('origin.json',{'stock':stock_ref})
    item={'symbol':'000001.SZ','ref':stock_ref,'origin':origin}
    seed=save('seed.json',{'schema':'v4.a_share.f10_reuse_inputs.v1','items':[item],'historical_PIT':False,**FLAGS})
    selected,lineage=verified_reuse_sources({'000001.SZ':'SZ'},seed)
    assert selected=={'000001.SZ':stock_ref} and lineage=={'000001.SZ':[origin]}
    with pytest.raises(ValueError,match='SCOPE_CONFLICT'):
        verified_reuse_sources({'000002.SZ':'SZ'},seed)
    wrong_origin=save('other-origin.json',{'stock':{'path':'/not-this-source','sha256':'a'*64}})
    bad_seed=save('bad-origin-seed.json',{'schema':'v4.a_share.f10_reuse_inputs.v1',
        'items':[{**item,'origin':wrong_origin}],'historical_PIT':False,**FLAGS})
    with pytest.raises(ValueError,match='ORIGIN_UNBOUND'):
        verified_reuse_sources({'000001.SZ':'SZ'},bad_seed)
    bad_ref=save('wrong-market.json',{**stock,'finance_native_raw':{'code':'000001','market':1}})
    bad_origin=save('bad-stock-origin.json',{'stock':bad_ref})
    bad_seed=save('bad-stock-seed.json',{'schema':'v4.a_share.f10_reuse_inputs.v1',
        'items':[{'symbol':'000001.SZ','ref':bad_ref,'origin':bad_origin}],'historical_PIT':False,**FLAGS})
    with pytest.raises(ValueError,match='SOURCE_IDENTITY_CONFLICT'):
        verified_reuse_sources({'000001.SZ':'SZ'},bad_seed)
    second=save('different-snapshot.json',{**stock,'captured_at':'2026-11-02T01:00:00Z'})
    second_origin=save('different-origin.json',{'stock':second})
    conflicting=save('conflicting-seed.json',{'schema':'v4.a_share.f10_reuse_inputs.v1',
        'items':[item,{'symbol':'000001.SZ','ref':second,'origin':second_origin}],
        'historical_PIT':False,**FLAGS})
    with pytest.raises(ValueError,match='F10_REUSE_SOURCE_CONFLICT'):
        verified_reuse_sources({'000001.SZ':'SZ'},conflicting)
