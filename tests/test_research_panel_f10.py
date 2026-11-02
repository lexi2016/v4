import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ops.research_panel_f10 import FLAGS, _concept_section, _isolated_sample_upstream, bound_universe, complete_f10, fetch_one, publish_f10_completion


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
    unsupported=fetch_one('920123.BJ','BJ',api_factory=API,vendor=vendor)
    assert unsupported['status']=='FAILED' and unsupported['reason']=='F10_COMPONENTS_INCOMPLETE'
    conflict=fetch_one('920123.BJ','SZ',api_factory=API,vendor=vendor)
    assert conflict['status']=='SOURCE_IDENTITY_CONFLICT' and conflict['reason']=='BOUND_EXCHANGE_SYMBOL_MISMATCH'
    absent=fetch_one('920123.BJ',None,api_factory=API,vendor=vendor)
    assert absent['status']=='SOURCE_IDENTITY_UNAVAILABLE' and absent['reason']=='BOUND_PANEL_EXCHANGE_MISSING'
    text='【3.概念板块】\n｜高端装备｜内容｜\n【4.风险提示】\n｜旧风险｜不能算概念｜'
    assert '旧风险' not in _concept_section(text)


def test_bj_f10_uses_independent_markets_and_checks_both_identities():
    calls=[]
    class API:
        def connect(self,*host):return True
        def get_company_info_category(self,market,code):
            calls.append(('category',market,code));return [{'filename':'f10.txt','name':'提示','start':0,'length':100}]
        def get_company_info_content(self,market,code,*args):
            calls.append(('content',market,code));return '◇920000 安徽凤凰 更新日期：2026-11-02◇\n【3.概念板块】\n｜高端装备｜描述｜'
        def get_finance_info(self,market,code):
            calls.append(('finance',market,code));return {'market':market,'code':code,'updated_date':20261029,'gudongrenshu':12}
        def disconnect(self):pass
    vendor=(SimpleNamespace(TdxHq_API=API,concepts_from=lambda _:[],grab=lambda *_:None),None)
    result=fetch_one('920000.BJ','BJ',api_factory=API,vendor=vendor)
    assert result['status']=='OBSERVED' and result['name']=='安徽凤凰'
    assert result['endpoint_markets']=={'text':0,'finance':2}
    assert result['source_updated_date']=='2026-11-02' and result['finance_updated_date']=='20261029'
    assert result['historical_PIT'] is False and result['financials']['holder_count'] is None
    assert result['financials']['holder_count_status']=='SOURCE_PERIOD_UNBOUND' and result['finance_native_raw']['gudongrenshu']==12
    assert calls==[('category',0,'920000'),('content',0,'920000'),('finance',2,'920000')]


def test_bj_missing_numeric_indicator_stays_unknown_without_losing_other_data():
    class API:
        def connect(self,*host):return True
        def get_company_info_category(self,market,code):return [{'filename':'f10.txt','start':0,'length':100}]
        def get_company_info_content(self,market,code,*args):return ('◇920201 百瑞吉 更新日期：2026-10-30◇\n'
            '｜★最新主要指标★｜2026-11-04｜2026-09-30｜\n'
            '｜每股收益(元)｜-｜1.0400｜\n｜每股净资产(元)｜-｜7.1820｜\n｜净资产收益率(%)｜-｜17.7300｜\n'
            '｜2026-09-30 营业总收入(元):2.4543亿｜\n｜2026-09-30 净利润(元):6237.3014万｜\n'
            '｜2026-06-30 营业总收入(元):旧值｜')
        def get_finance_info(self,market,code):return {'market':2,'code':'920201','gudongrenshu':123}
        def disconnect(self):pass
    def unavailable(*_):return float('-')
    vendor=(SimpleNamespace(TdxHq_API=API,concepts_from=lambda _:[],grab=unavailable),None)
    result=fetch_one('920201.BJ','BJ',api_factory=API,vendor=vendor)
    assert result['status']=='OBSERVED' and result['financials']['holder_count'] is None
    assert result['finance_native_raw']['gudongrenshu']==123
    assert result['financials']['report_period']=='2026-09-30' and result['financials']['eps']==1.04
    assert result['financials']['bps']==7.182 and result['financials']['roe_pct']==17.73
    assert result['financials']['revenue_text']=='2.4543亿' and result['financials']['net_profit_text']=='6237.3014万'
    assert result['financials']['net_profit_scope']=='SOURCE_LABEL_NET_PROFIT_PARENT_SCOPE_UNCONFIRMED'


def test_sh_placeholder_numeric_cell_does_not_discard_company_material():
    class API:
        def connect(self,*host):return True
        def get_company_info_category(self,market,code):return [{'filename':'f10.txt','start':0,'length':100}]
        def get_company_info_content(self,market,code,*args):
            return '◇688981 中芯国际 更新日期：2026-10-30◇\n★最新主要指标★｜2026-09-30｜'
        def get_finance_info(self,market,code):return {'market':1,'code':'688981'}
        def disconnect(self):pass
    def grab(text,label):
        if label=='每股收益(元)':raise ValueError("could not convert string to float: '-'")
        return 2.5 if label=='每股净资产(元)' else float('nan')
    vendor=(SimpleNamespace(TdxHq_API=API,concepts_from=lambda _:[],grab=grab),None)
    result=fetch_one('688981.SH','SH',api_factory=API,vendor=vendor)
    assert result['status']=='OBSERVED' and result['name']=='中芯国际'
    assert result['financials']['eps'] is None and result['financials']['bps']==2.5
    assert result['financials']['roe_pct'] is None and result['historical_PIT'] is False


def test_sh_placeholder_header_uses_a_single_bound_actual_period():
    class API:
        def connect(self,*host):return True
        def get_company_info_category(self,market,code):return [{'filename':'f10.txt','start':0,'length':100}]
        def get_company_info_content(self,market,code,*args):return ('◇688981 中芯国际 更新日期：2026-10-30◇\n'
            '｜★最新主要指标★｜2026-10-13｜2026-06-30｜\n'
            '｜每股收益(元)｜-｜0.5600｜\n｜每股净资产(元)｜-｜20.0281｜\n｜净资产收益率(%)｜-｜2.9000｜\n'
            '｜2026-06-30 营业总收入(元):386.3512亿｜\n｜2026-06-30 净利润(元):44.6743亿｜')
        def get_finance_info(self,market,code):return {'market':1,'code':'688981','gudongrenshu':123}
        def disconnect(self):pass
    def grab(*_):raise ValueError("could not convert string to float: '-'")
    vendor=(SimpleNamespace(TdxHq_API=API,concepts_from=lambda _:[],grab=grab),None)
    result=fetch_one('688981.SH','SH',api_factory=API,vendor=vendor)
    values=result['financials']
    assert result['status']=='OBSERVED' and values['report_period']=='2026-06-30'
    assert values['eps']==.56 and values['bps']==20.0281 and values['roe_pct']==2.9
    assert values['revenue_text']=='386.3512亿' and values['net_profit_text']=='44.6743亿'
    assert values['holder_count'] is None and values['holder_count_status']=='SOURCE_PERIOD_UNBOUND'
    assert result['finance_native_raw']['gudongrenshu']==123


@pytest.mark.parametrize('bad_part',['text','finance'])
def test_bj_partial_preserves_verified_component_without_admitting_mismatch(bad_part):
    class API:
        def connect(self,*host):return True
        def get_company_info_category(self,market,code):return [{'filename':'f10.txt','start':0,'length':100}]
        def get_company_info_content(self,market,code,*args):
            return '◇'+('920001' if bad_part=='text' else code)+' 安徽凤凰 更新日期：2026-10-30◇'
        def get_finance_info(self,market,code):return {'market':market,'code':'920001' if bad_part=='finance' else code}
        def disconnect(self):pass
    vendor=(SimpleNamespace(TdxHq_API=API,concepts_from=lambda _:[],grab=lambda *_:None),None)
    result=fetch_one('920000.BJ','BJ',api_factory=API,vendor=vendor)
    assert result['status']=='PARTIAL' and result['reason']=='F10_COMPONENTS_INCOMPLETE'
    assert result['source_components'][bad_part]['status']=='UNKNOWN'
    assert result['source_components']['finance' if bad_part=='text' else 'text']['status']=='OBSERVED'
    assert result['historical_PIT'] is False


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


def test_partial_bj_component_is_preserved_and_retried(tmp_path):
    panel=tmp_path/'panel.parquet';pq.write_table(pa.table({'ts_code':['920000.BJ'],'exchange':['BJ']}),panel)
    context=SimpleNamespace(scope=['920000.BJ'],panel=panel,target=20261030,generation='a'*64,
        identity={'selector_artifact_sha256':'b'*64,'input_sha256':'c'*64},unchanged=lambda:None)
    upstream=tmp_path/'upstream.json';upstream.write_text(json.dumps({'schema':'V4_A_DAILY_DERIVATIVES_V1',
        'status':'COMPLETE_DESCRIPTIVE_NONPIT','data_date':'20261030','source_generation':context.generation,**FLAGS}))
    ref={'path':str(upstream),'sha256':hashlib.sha256(upstream.read_bytes()).hexdigest()}
    partial={'symbol':'920000.BJ','exchange':'BJ','status':'PARTIAL','reason':'F10_COMPONENTS_INCOMPLETE',
        'source_components':{'text':{'status':'UNKNOWN'},'finance':{'status':'OBSERVED','market':2,
        'finance_native_raw':{'market':2,'code':'920000'}}},'historical_PIT':False,**FLAGS}
    first=complete_f10(context,ref,tmp_path/'out',workers=1,fetch=lambda *_:partial)
    receipt=json.loads(Path(first['receipt']['path']).read_text())
    failure=receipt['failures']['920000.BJ'];raw=Path(failure['artifact']['path']).read_bytes()
    assert first['status']=='PARTIAL' and failure['status']=='PARTIAL'
    assert hashlib.sha256(raw).hexdigest()==failure['artifact']['sha256']
    assert json.loads(raw)['source_components']['finance']['finance_native_raw']['code']=='920000'
    checkpoint=json.loads(Path(receipt['checkpoint']['path']).read_text())
    assert '920000.BJ' not in checkpoint['items']
    second=complete_f10(context,ref,tmp_path/'out',workers=1,fetch=lambda code,exchange:{
        'symbol':code,'exchange':exchange,'status':'OBSERVED','historical_PIT':False,**FLAGS})
    assert second['status']=='COMPLETE' and second['observed']==1


def test_isolated_f10_completion_requires_bound_sample_and_admission(tmp_path):
    isolated=tmp_path/'isolated'; isolated.mkdir()
    data=isolated/'data'; data.mkdir()
    root=isolated/'product'; root.mkdir()
    context=SimpleNamespace(data_root=data,pointer=data/'selector',backpointer=data/'backtest',
        target=20261030,generation='a'*64,scope=['920201.BJ','920000.BJ','920001.BJ'],
        identity={'input_sha256':'b'*64},
        qualify=lambda symbol:{'status':'CURRENT_PRODUCER_ACCEPTED_FOR_REQUESTED_RESEARCH'
            if symbol!='920001.BJ' else 'UNKNOWN'})
    def save(path,value):
        raw=json.dumps(value,sort_keys=True).encode();path.write_bytes(raw)
        return {'path':str(path),'sha256':hashlib.sha256(raw).hexdigest()}
    requested=['920201.BJ','920000.BJ']
    product={'sample_only':True,'source_generation':context.generation,'source_identity':context.identity,
             'processed_universe':requested,'processed_count':2,**FLAGS}
    artifact=save(root/'product.json',product)
    manifest={'schema_version':'v4.a_share.daily_product_manifest.v1','sample_only':True,
        'data_date':'20261030','source_generation':context.generation,'input_sha256':context.identity['input_sha256'],
        'processed_count':2,'source_universe_count':3,'artifact':artifact,**FLAGS}
    manifest_ref=save(root/'manifest.json',manifest)
    assert _isolated_sample_upstream(context,manifest_ref,manifest,root,isolated,requested)==isolated
    with pytest.raises(ValueError,match='MANIFEST_CONFLICT'):
        _isolated_sample_upstream(context,manifest_ref,{**manifest,'input_sha256':'c'*64},root,isolated,requested)
    with pytest.raises(ValueError,match='PRODUCT_CONFLICT'):
        _isolated_sample_upstream(context,manifest_ref,manifest,root,isolated,['920201.BJ','920001.BJ'])
    outside=save(tmp_path/'outside.json',product)
    with pytest.raises(ValueError,match='ARTIFACT_ESCAPE'):
        _isolated_sample_upstream(context,manifest_ref,{**manifest,'artifact':outside},root,isolated,requested)
    bad_product={**product,'processed_universe':['920201.BJ','920001.BJ']}
    bad_artifact=save(root/'bad-product.json',bad_product)
    with pytest.raises(ValueError,match='ADMISSION_FAILED'):
        _isolated_sample_upstream(context,manifest_ref,{**manifest,'artifact':bad_artifact},root,isolated,bad_product['processed_universe'])


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
