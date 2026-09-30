"""Synthetic owner-boundary tests of the real r9 consumer pipeline; NOT live/Mac."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import pytest
from test_r9_selection import (C,S,NAME,MASTER,IDENTITY,mirror_doc,capture,connect_scope,us_market,material,cards)
from v4.manager_research.workspace_projection import FLAGS,digest


def wire(monkeypatch,tmp_path,*,membership=True,body=None):
    from v4.manager_research import workspace as ws,workspace_announcements as ann,connect_selection as cs,us_market_bridge as bridge
    from v4.manager_research.announcement_materials import mirror_material
    from v4.manager_research.workspace_discovery import project_material_discovery
    doc=mirror_doc(body);m=mirror_material(doc,capture());cap=capture()
    announcements=dict(materials=[m],rejections=[],gaps=[],captures=[cap],status='READY',input_identity=digest([m,cap]),**FLAGS)
    service=SimpleNamespace(store=SimpleNamespace(root=tmp_path,_read=lambda p:None),
       observation_reader=None,_close_observation_reader=None,_catalyst_data_root=tmp_path,
       get_catalyst_observations=lambda date:dict(status='READY_EMPTY',target_trade_date=date,cards=[],**FLAGS))
    monkeypatch.setattr(ws,'_reader_value',lambda reader,date,lane:dict(status='READY_EMPTY',target_trade_date=date,rows=[],candidates=[]))
    monkeypatch.setattr(ws,'_materials',lambda *a:dict(materials=[],coverage={},input_bindings=[],gaps=[]))
    monkeypatch.setattr(ws,'_discovery',lambda *a:dict(cards=[],gaps=[],status='READY_EMPTY',coverage={}))
    def discovery(materials,context,*a,**kw):
        rejections=[];result=project_material_discovery(materials,MASTER,IDENTITY,context,rejection_audit=rejections)
        return dict(cards=result,gaps=[],status='READY',coverage={'material_count':len(materials)},rejected_relations=rejections)
    monkeypatch.setattr(ws,'read_material_discovery',discovery)
    monkeypatch.setattr(ws,'read_plan_quotes',lambda *a,**kw:dict(quotes={},verified=False,gaps=[]))
    screen=dict(status='READY',strict=[],near=[],cards=[],gaps=[],coverage={})
    monkeypatch.setattr(ws,'read_rebound_screen',lambda *a:deepcopy(screen))
    monkeypatch.setattr(ws,'_previous_observation',lambda *a:(None,None))
    monkeypatch.setattr(ws,'_stage_attempt',lambda *a:(None,['STAGE_TARGET_EXECUTION_RECEIPT_NOT_FOUND']))
    monkeypatch.setattr(ann,'read',lambda *a:dict(status='NOT_RUN',official_documents=[],positive_observations=[],risk_alerts=[],clarifications=[],pending_review=[],coverage={},gaps=[],eastmoney_hk_documents=[],eastmoney_hk_capture={}))
    calls=[]
    def read_inputs(*a,**kw):calls.append('ORIGINAL_OWNER_READ_BOUNDARY');return deepcopy(announcements)
    monkeypatch.setattr(ann,'read_selection_inputs',read_inputs)
    scope=connect_scope() if membership else dict(status='CANNOT_CONFIRM',codes=[],target_trade_date=C['plan_trade_date'],identity=None,gaps=['MISSING_REAL_AUTHORITY'])
    monkeypatch.setattr(cs,'read_scope',lambda *a:deepcopy(scope))
    us=us_market();monkeypatch.setattr(bridge,'project_us_market',lambda *a:deepcopy(us))
    return ws,service,announcements,screen,us,calls


def test_body_enters_original_stock_focus_and_attention(monkeypatch,tmp_path):
    ws,svc,ann,screen,us,calls=wire(monkeypatch,tmp_path)
    original=deepcopy(ann)
    result=ws._compute_workspace(svc,C['plan_trade_date'],include_saved=False,context=C)
    assert [r['symbol'] for r in result['stocks']]==[S]
    assert result['focus_symbols']==[S]
    assert result['selection_diagnostics']['candidate_count']==1
    row=result['selection_diagnostics']['candidates'][0]
    assert row['symbol']==S and row['name']==NAME and row['reason']
    evidence=row['evidence'][0]
    assert evidence['body_sha256']==ann['materials'][0]['body_sha256']
    assert evidence['published_at'] is None
    assert evidence['time_basis']=='MIRROR_DISPLAY_TIME_NOT_HKEX_FIRST_PUBLICATION'
    assert result['research_attention']['cards'][0]['symbol']==S
    assert result['market_screen']==screen and result['us_market_attention']['raw_individual_up']==us['raw_individual_up']
    assert ann==original and calls==['ORIGINAL_OWNER_READ_BOUNDARY']
    assert all(result[k] is v for k,v in FLAGS.items())


def test_missing_target_authority_rejects_selection_not_raw_movers(monkeypatch,tmp_path):
    ws,svc,ann,screen,us,calls=wire(monkeypatch,tmp_path,membership=False)
    result=ws._compute_workspace(svc,C['plan_trade_date'],include_saved=False,context=C)
    assert result['stocks']==[] and result['focus_symbols']==[] and result['research_attention']['cards']==[]
    diag=result['selection_diagnostics'];assert diag['candidate_count']==0
    assert any('MEMBERSHIP' in r['reason'] for r in diag['rejections'])
    assert result['us_market_attention']['raw_industry_up']==us['raw_industry_up']


def test_real_pipeline_is_stable_and_body_change_invalidates_identity(monkeypatch,tmp_path):
    ws,svc,ann,screen,us,calls=wire(monkeypatch,tmp_path)
    a=ws._compute_workspace(svc,C['plan_trade_date'],include_saved=False,context=C)
    b=ws._compute_workspace(svc,C['plan_trade_date'],include_saved=False,context=C)
    assert a['input_identity']==b['input_identity']
    from v4.manager_research.announcement_materials import mirror_material
    ann['materials']=[mirror_material(mirror_doc(NAME+'已签署新的机器人合作合同，订单增长30%。'),capture())]
    ann['input_identity']=digest(ann['materials'])
    c=ws._compute_workspace(svc,C['plan_trade_date'],include_saved=False,context=C)
    assert a['input_identity']!=c['input_identity']


def test_no_second_collector_or_store_writer_added():
    import ast
    from v4.manager_research import announcement_materials as am,connect_selection as cs
    for mod in (am,cs):
        tree=ast.parse(Path(mod.__file__).read_text())
        attrs={n.func.attr for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)}
        assert not attrs.intersection({'write_bytes','write_text','urlopen','refresh_announcements','put_blob','submit','post'})


def test_cross_date_reads_original_store_then_validator_once(monkeypatch,tmp_path):
    import json
    from v4.manager_research import workspace_announcements as ann
    original=json.loads(Path(__file__).with_name('actual_eastmoney_product_20260929.json').read_text())
    paths=[];validated=[]
    def read(path):
        paths.append(str(path.relative_to(tmp_path)))
        return deepcopy(original) if '/20260929/' in str(path) else None
    # Raw MaterialStore response blobs are NOT supplied. This is explicitly
    # an injected original-owner validation boundary, not its live acceptance.
    monkeypatch.setattr(ann,'_check_eastmoney_sources',lambda svc,p:validated.append(p['sha256']))
    svc=SimpleNamespace(store=SimpleNamespace(root=tmp_path,_read=read))
    result=ann.read_selection_inputs(svc,C,current_review={'eastmoney_hk_capture':None})
    assert len(result['materials'])==1
    assert result['materials'][0]['capture_trade_date']=='20260929'
    assert result['materials'][0]['published_at'] is None
    assert validated==[original['sha256']]
    assert len(paths)==2 and len(result['rejections'])>=1
    monkeypatch.setattr(ann,'_check_eastmoney_sources',lambda *a:(_ for _ in ()).throw(ValueError('ORIGINAL_STORE_SHA_MISMATCH')))
    failed=ann.read_selection_inputs(svc,C,current_review={'eastmoney_hk_capture':None})
    assert failed['materials']==[] and failed['status']=='PARTIAL'
    assert any('SHA_MISMATCH' in x for x in failed['gaps'])
