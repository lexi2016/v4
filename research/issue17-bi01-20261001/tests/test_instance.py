"""BI-01: synthetic HTTP/master, original parser + stores + history + projection."""
from test_b1_history import wired, capture, context, selection, snapshot
from copy import deepcopy
from datetime import timedelta
import json, os, subprocess
from pathlib import Path
import pytest
from v4.manager_research import workspace_announcements as ann
from v4.manager_research.eastmoney_run_history import read_history
from v4.manager_research.announcement_observation import event_lane
from v4.manager_research.ports import SourceResponse

@pytest.fixture
def scenario(wired, monkeypatch):
    svc,p,clock=wired
    from v4.manager_research import announcement_source as src
    original_capture=src.capture_eastmoney
    def fresh(*a,**kw):
        kw['force']=True  # Synthetic refreshed responses; keep original Store fetch/retention.
        return original_capture(*a,**kw)
    monkeypatch.setattr(src,'capture_eastmoney',fresh)
    original=p._request_eastmoney_hk
    state={'version':'A'}
    def response(url,**kw):
        r=original(url,**kw)
        if 'stock_list=' in url or 'art_code=' in url:
            data=json.loads(r.body)
            if 'stock_list=' in url:
                data['data']['list'][0]['art_code']='AN202609290000100001'
                data['data']['list'][0]['title']='合成共同公告'
            else:
                data['data']['notice_title']='合成共同公告'
                data['data']['security']=[dict(market_uni='116',stock=x) for x in ['00001','00002']]
                data['data']['notice_content']+=' 合成正文版本 '+state['version']
            return SourceResponse(url=url,final_url=url,status_code=200,headers={},body=json.dumps(data,ensure_ascii=False).encode(),retrieved_at=clock[0].isoformat())
        return r
    monkeypatch.setattr(p,'_request_eastmoney_hk',response)
    capture(wired,'HK.00001'); first=context(wired)
    clock[0]+=timedelta(minutes=1);state['version']='B';capture(wired,'HK.00001')
    clock[0]+=timedelta(minutes=1);capture(wired,'HK.00002')
    clock[0]+=timedelta(minutes=1);capture(wired,'HK.00001')
    return wired,first


def test_original_store_to_ts_validator_and_dom(scenario,tmp_path):
    wired,first=scenario;svc,p,clock=wired
    before=snapshot(svc.store.root);calls=len(p.calls)
    history=read_history(svc,'20260930',context(wired))
    assert len(history['captures'])==4,history['gaps']
    assert len(history['documents'])==3
    review=ann.read(svc,'20260930',context(wired))
    lane=event_lane(review,{},context(wired))
    assert len(lane['eastmoney_hk_documents'])==3
    payload=tmp_path/'lane.json';payload.write_text(json.dumps(lane,ensure_ascii=False))
    result=subprocess.run(['node',str(Path(__file__).with_name('validate.mjs')),os.environ['BI01_APP'],str(payload)],capture_output=True,text=True)
    print(result.stdout,result.stderr)
    assert result.returncode==0,result.stdout+result.stderr
    ids=[r['document']['event_id'] for r in history['documents']]
    assert len(set(ids))==3
    from v4.manager_research.eastmoney_run_history import committed_products
    products,_,_=committed_products(svc,'20260930')
    projected=[ann._project_eastmoney_hk(p,context(wired))[0][0] for p in products]
    assert projected[1]['event_id']==projected[3]['event_id']
    assert projected[0]['body_sha256']!=projected[1]['body_sha256']
    assert projected[1]['body_sha256']==projected[2]['body_sha256']
    assert projected[1]['symbol']!=projected[2]['symbol']
    repeated=next(r for r in history['documents'] if len(r['occurrences'])==2)
    assert repeated['document']['symbol']=='HK.00001'
    assert len({r['run_id'] for r in repeated['occurrences']})==2
    earlier=read_history(svc,'20260930',first)
    assert len(earlier['documents'])==1
    assert earlier['documents'][0]['document']['event_id']==ids[0]
    materials=selection(wired)['materials']
    assert len(materials)==3
    assert len({m['material_id'] for m in materials})==3
    assert {m['original_article_id'] for m in materials}==set(ids)
    assert all(m['original_article_id']==m['owner_document']['event_id'] for m in materials)
    assert sorted(len(m['capture_occurrences']) for m in materials)==[1,1,2]
    assert snapshot(svc.store.root)==before and len(p.calls)==calls
    print('PASS: 4 committed captures, 3 readable instances, occurrences 1/1/2, historical cutoff, read-only, unique materials')

@pytest.mark.parametrize('mutation',['body','refs','raw','snapshot'])
def test_original_source_and_body_guards(wired,mutation):
    from test_b1_history import test_tampered_body_or_reference_rejects_only_bad_run
    test_tampered_body_or_reference_rejects_only_bad_run(wired,mutation)
