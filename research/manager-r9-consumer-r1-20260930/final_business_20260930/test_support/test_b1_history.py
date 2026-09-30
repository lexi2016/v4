"""Synthetic issuer/HTTP inputs; real owner, response parser and disk stores."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit, parse_qs
import pytest
from v4.manager_research import workspace_announcements as ann, announcement_source as src
from v4.manager_research.materials import MaterialStore
from v4.manager_research.store import ManagerResearchStore
from v4.manager_research.ports import SourceResponse
from v4.manager_research.workspace_projection import digest, FLAGS


def pdf():
    """One tiny valid PDF; content is an explicit synthetic test document."""
    stream=b'BT /F1 12 Tf 50 700 Td (Synthetic business contract) Tj ET'
    objects=[b'<< /Type /Catalog /Pages 2 0 R >>',
      b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
      b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
      b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
      b'<< /Length '+str(len(stream)).encode()+b' >>\nstream\n'+stream+b'\nendstream']
    raw=b'%PDF-1.4\n';offsets=[0]
    for i,obj in enumerate(objects,1):
        offsets.append(len(raw));raw+=f'{i} 0 obj\n'.encode()+obj+b'\nendobj\n'
    x=len(raw);raw+=b'xref\n0 6\n0000000000 65535 f \n'
    raw+=b''.join(f'{n:010d} 00000 n \n'.encode() for n in offsets[1:])
    return raw+b'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n'+str(x).encode()+b'\n%%EOF\n'


def snapshot(root):
    return {str(p.relative_to(root)):sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}


class Provider:
    def __init__(self,store,clock):
        self._material_store=store; self._material_transport=object();self._timeout=5
        self.clock=clock; self.calls=[];self.fail=False;self.versions={}; self.listing_revision=0
    def collect_eastmoney_hk_batch(self,**kw):
        if self.fail:raise RuntimeError('SYNTHETIC_OWNER_FAILURE')
        return src.collect_eastmoney_hk_batch(self,**kw)
    def _request_eastmoney_hk(self,url,**kw):
        self.calls.append(url);q=parse_qs(urlsplit(url).query)
        if 'stock_list' in q:
            code=q['stock_list'][0];art='AN20260929'+code+'00001'
            row=dict(art_code=art,title='样本'+code+'业务公告',notice_date='2026-09-29 00:00:00',
                display_time='2026-09-29 18:00:00:000',codes=[dict(market_code='116',stock_code=code,ann_type='H',short_name='样本'+code)])
            data=dict(success=1,data=dict(list=[row],page_index=1,page_size=5,total_hits=1),synthetic_revision=self.listing_revision)
            body=json.dumps(data,ensure_ascii=False).encode()
        elif 'art_code' in q:
            art=q['art_code'][0];code=art[10:15]
            body_text='本公司已簽署機器人產品合作協議，取得新增訂單。'
            body=json.dumps(dict(success=1,data=dict(art_code=art,notice_title='样本'+code+'业务公告',
                notice_date='2026-09-29 00:00:00',eitime='2026-09-29 18:00:00',page_size=1,
                security=[dict(market_uni='116',stock=code)],notice_content=body_text,
                attach_url_web='https://pdf.dfcfw.com/pdf/H2_'+art+'_1.pdf')),ensure_ascii=False).encode()
        else:body=pdf()
        return SourceResponse(url=url,status_code=200,body=body,headers={},
            retrieved_at=self.clock[0].isoformat(),final_url=url)


@pytest.fixture
def wired(monkeypatch,tmp_path):
    clock=[datetime.fromisoformat('2026-09-30T08:00:00+08:00')]
    names={'HK.'+f'{i:05d}':{'name':'样本'+f'{i:05d}'} for i in range(1,7)}
    witness={'owner':'SYNTHETIC_MASTER_BOUNDARY','artifact_sha256':'a'*64}
    monkeypatch.setattr(ann,'_master',lambda *a:(deepcopy(names),deepcopy(witness)))
    monkeypatch.setattr(ann,'_now',lambda:clock[0].isoformat())
    # R9's provider/allowlist is not in the frozen business slice. On a native
    # app use that original implementation. Author reference dependency lacks
    # the method, so explicitly restrict the fixture boundary to three hosts.
    import v4.manager_research.hkex_provider as hp
    if not hasattr(hp,'_safe_eastmoney_hk_url'):
        monkeypatch.setattr(hp,'_safe_eastmoney_hk_url',lambda u:
            urlsplit(u).scheme=='https' and urlsplit(u).hostname in {
                'np-anotice-stock.eastmoney.com','np-cnotice-stock.eastmoney.com','pdf.dfcfw.com'},raising=False)
    store=ManagerResearchStore(tmp_path/'manager');material=MaterialStore(tmp_path/'manager/materials')
    provider=Provider(material,clock)
    svc=SimpleNamespace(store=store,_material_store=material,source_provider=provider)
    return svc,provider,clock


def capture(wired,issuer=None):
    svc,p,clock=wired
    return ann.refresh(svc,clock[0].strftime('%Y%m%d'),source_scope='EASTMONEY_HK',issuer_code=issuer)


def context(wired,*,target='20260930'):
    clock=wired[2][0]
    return dict(plan_trade_date=target,market_session='20260929',
        focus_window_start='2026-09-28T16:10:00+08:00',research_cutoff=clock.isoformat(),
        source_dates=['20260928','20260929','20260930'] if target=='20260930' else ['20260928','20260929'])


def selection(wired):
    svc,_,_=wired
    return ann.read_selection_inputs(svc,context(wired))


def test_default_two_batches_advance_scope_and_both_enter_original_input(wired):
    a=capture(wired);wired[2][0]+=timedelta(minutes=1);b=capture(wired)
    assert a['eastmoney_hk_capture']['queried_issuers']==['HK.00001','HK.00002','HK.00003']
    assert b['eastmoney_hk_capture']['queried_issuers']==['HK.00004','HK.00005','HK.00006']
    result=selection(wired)
    assert {m['document_issuer_symbol'] for m in result['materials']}=={'HK.'+f'{i:05d}' for i in range(1,7)}
    assert len(result['captures'])==2
    progress=b['eastmoney_hk_coverage']
    assert progress['sweep']['visited_issuer_count']==6
    assert progress['sweep']['all_issuers_visited'] is True
    assert progress['directory_exhaustion']=='UNVERIFIED'


def test_repeated_document_deduplicates_and_old_refs_survive_listing_index_update(wired):
    capture(wired,'HK.00001');svc,p,clock=wired
    paths=list((svc.store.root/'workspace_announcements/20260930/eastmoney_hk').glob('*.json'))
    prior={str(f):f.read_bytes() for f in paths if f.name!='latest.json'}
    p.listing_revision=1;clock[0]+=timedelta(minutes=6)
    capture(wired,'HK.00001')
    before=snapshot(svc.store.root);calls=len(p.calls)
    result=selection(wired)
    assert len(result['materials'])==1 and len(result['captures'])==2
    assert result['materials'][0]['available_at']=='2026-09-30T08:00:00+08:00'
    assert all(Path(f).read_bytes()==v for f,v in prior.items())
    assert snapshot(svc.store.root)==before and len(p.calls)==calls
    assert not any('RAW_INDEX_MISMATCH' in g for g in result['gaps'])


def test_later_failed_batch_retains_previous_committed_body(wired):
    capture(wired,'HK.00001');svc,p,clock=wired
    p.fail=True;clock[0]+=timedelta(minutes=1)
    with pytest.raises(RuntimeError,match='SYNTHETIC_OWNER_FAILURE'):capture(wired,'HK.00002')
    p.fail=False
    result=selection(wired)
    assert [m['document_issuer_symbol'] for m in result['materials']]==['HK.00001']
    assert len(result['captures'])==1
    assert any('SYNTHETIC_OWNER_FAILURE' in g for g in result['gaps'])


def test_cross_day_original_runs_and_after_cutoff_exclusion(wired):
    wired[2][0]=datetime.fromisoformat('2026-09-29T19:00:00+08:00');capture(wired,'HK.00001')
    wired[2][0]=datetime.fromisoformat('2026-09-30T08:00:00+08:00');capture(wired,'HK.00002')
    wired[2][0]+=timedelta(minutes=1);capture(wired,'HK.00003')
    svc,_,_=wired;cut=context(wired);cut['research_cutoff']='2026-09-30T08:00:30+08:00'
    result=ann.read_selection_inputs(svc,cut)
    assert {m['document_issuer_symbol'] for m in result['materials']}=={'HK.00001','HK.00002'}
    assert result['materials'][0]['capture_trade_date']=='20260929'
    assert all(m['published_at'] is None for m in result['materials'])
    assert any('AFTER_CONSUMER_CUTOFF' in g for g in result['gaps'])


@pytest.mark.parametrize('mutation',['body','refs','raw','snapshot'])
def test_tampered_body_or_reference_rejects_only_bad_run(wired,mutation):
    capture(wired,'HK.00001');wired[2][0]+=timedelta(minutes=1);capture(wired,'HK.00002')
    svc,_,_=wired;root=svc.store.root/'workspace_announcements/20260930/eastmoney_hk'
    paths=[f for f in root.glob('*.json') if f.name!='latest.json']
    path=next(p for p in paths if json.loads(p.read_bytes())['scope']==['HK.00002'])
    product=json.loads(path.read_bytes());ref=product['documents'][0]['content_refs'][0]
    if mutation=='body':product['documents'][0]['body_text']+=' tampered';product=ann._seal(product);svc.store._write_atomic(path,product)
    elif mutation=='refs':
        product['documents'][0]['content_refs'][0]['body_sha256']='f'*64;product=ann._seal(product);svc.store._write_atomic(path,product)
    elif mutation=='raw':(svc._material_store.root/'blobs'/ref['blob_sha256']).write_bytes(b'corrupt')
    else:
        files=list((svc._material_store.root/'observations/eastmoney_hk').glob('*.json'))
        assert files,'per-response original index observations missing'
        item=next(p for p in files if json.loads(p.read_bytes())['index']['source_key']==ref['source_key'])
        item.write_text('{}')
    if mutation in {'body','refs'} and product.get('attempt_run_id'):
        from v4.manager_research.workspace import seal_attempt
        a=svc.store.root/'workspace_announcement_runs/20260930/eastmoney_hk'/(product['attempt_run_id']+'.json')
        proof=json.loads(a.read_bytes());proof['product_sha256']=product['sha256']
        svc.store._write_atomic(a,seal_attempt(proof))
    result=selection(wired)
    assert 'HK.00002' not in {m['document_issuer_symbol'] for m in result['materials']}
    assert 'HK.00001' in {m['document_issuer_symbol'] for m in result['materials']}
    assert result['rejections']


def test_get_is_read_only_and_current_review_cannot_hide_older_runs(wired):
    capture(wired,'HK.00001');wired[2][0]+=timedelta(minutes=1);latest=capture(wired,'HK.00002')
    svc,p,_=wired;before=snapshot(svc.store.root);calls=len(p.calls)
    result=ann.read_selection_inputs(svc,context(wired),current_review=latest)
    assert len(result['materials'])==2
    assert snapshot(svc.store.root)==before and len(p.calls)==calls
    assert all(result[k] is v for k,v in FLAGS.items())


def test_default_sweep_wraps_and_singleton_does_not_reset_default_cursor(wired):
    capture(wired);wired[2][0]+=timedelta(minutes=1)
    capture(wired,'HK.00006');wired[2][0]+=timedelta(minutes=1)
    second=capture(wired)
    assert second['eastmoney_hk_capture']['queried_issuers']==['HK.00004','HK.00005','HK.00006']
    wired[2][0]+=timedelta(minutes=1);third=capture(wired)
    assert third['eastmoney_hk_capture']['queried_issuers']==['HK.00001','HK.00002','HK.00003']
    assert third['eastmoney_hk_coverage']['sweep']['cycle']==2
    assert len(selection(wired)['materials'])==6


def test_failed_named_commit_keeps_prior_success_and_does_not_advance_cursor(wired,monkeypatch):
    capture(wired);svc,p,clock=wired;clock[0]+=timedelta(minutes=1)
    before=list((svc.store.root/'workspace_announcements/20260930/eastmoney_hk').glob('*.json'))
    original=svc.store._io.write_bytes
    def fail_final(relative,raw,**kw):
        if relative.startswith('workspace_announcements/') and kw.get('require_absent'):
            raise OSError('SYNTHETIC_COMMIT_FAIL')
        return original(relative,raw,**kw)
    with monkeypatch.context() as m:
        m.setattr(svc.store._io,'write_bytes',fail_final)
        with pytest.raises(OSError):capture(wired)
    result=selection(wired)
    assert {m['document_issuer_symbol'] for m in result['materials']}=={'HK.00001','HK.00002','HK.00003'}
    assert any('NOT_COMMITTED' in g for g in result['gaps'])
    clock[0]+=timedelta(minutes=1)
    assert capture(wired)['eastmoney_hk_capture']['queried_issuers']==['HK.00004','HK.00005','HK.00006']


def test_provider_failure_after_forced_index_change_preserves_success(wired,monkeypatch):
    capture(wired,'HK.00001');svc,p,clock=wired;clock[0]+=timedelta(minutes=1)
    original=p._request_eastmoney_hk
    def failing_list(url,**kw):
        if 'stock_list=' in url:return SourceResponse(url=url,status_code=503,body=b'failure',headers={},
            retrieved_at=clock[0].isoformat(),final_url=url)
        return original(url,**kw)
    with monkeypatch.context() as m:
        m.setattr(p,'_request_eastmoney_hk',failing_list)
        with pytest.raises(ValueError):capture(wired,'HK.00001')
    result=selection(wired)
    assert len(result['materials'])==1 and len(result['captures'])==1
    assert result['materials'][0]['available_at']=='2026-09-30T08:00:00+08:00'


def test_invalid_scope_or_date_never_widens_or_backdates(wired):
    with pytest.raises(ValueError):capture(wired,'SH.600000')
    capture(wired,'HK.00001')
    c=context(wired);c['source_dates']=['20260930','20260929']
    with pytest.raises(ValueError,match='SOURCE_DATES_INVALID'):ann.read_selection_inputs(wired[0],c)
    c=context(wired);c['focus_window_start']='2026-09-29T18:00:00+08:00';c['source_dates']=['20260929','20260930']
    r=ann.read_selection_inputs(wired[0],c)
    assert r['materials']==[] and r['rejections']


def test_legacy_committed_run_kept_without_rewriting_it(wired):
    capture(wired,'HK.00001');svc,p,clock=wired
    root=svc.store.root/'workspace_announcements/20260930/eastmoney_hk'
    path=next(f for f in root.glob('*.json') if f.name!='latest.json')
    product=json.loads(path.read_bytes());product.pop('commit_protocol');product.pop('attempt_run_id');product.pop('sweep')
    product=ann._seal(product);svc.store._write_atomic(path,product);svc.store._write_atomic(root/'latest.json',product)
    # Emulate original old writer, which has terminal scope/time journal but no link.
    for a in (svc.store.root/'workspace_announcement_runs/20260930/eastmoney_hk').glob('*.json'):
        v=json.loads(a.read_bytes());v.pop('product_run_id',None);v.pop('product_sha256',None)
        from v4.manager_research.workspace import seal_attempt
        svc.store._write_atomic(a,seal_attempt(v))
    raw=path.read_bytes();clock[0]+=timedelta(minutes=1);capture(wired,'HK.00002')
    r=selection(wired)
    assert {m['document_issuer_symbol'] for m in r['materials']}=={'HK.00001','HK.00002'}
    assert path.read_bytes()==raw


def test_query_budget_partial_scope_is_visible_not_claimed_success(wired,monkeypatch):
    svc,p,clock=wired;original=p.collect_eastmoney_hk_batch
    def one_query(**kw):
        kw['issuers']=kw['issuers'][:1]
        return original(**kw)
    monkeypatch.setattr(p,'collect_eastmoney_hk_batch',one_query)
    result=capture(wired)
    progress=result['eastmoney_hk_coverage']['sweep']
    assert progress['successful_query_count']==1 and progress['failed_query_count']==2
    assert progress['all_issuers_visited'] is False
    assert result['eastmoney_hk_coverage']['all_announcements_captured'] is False
    assert len(selection(wired)['materials'])==1


def test_duplicate_retains_both_capture_provenance(wired):
    capture(wired,'HK.00001');wired[2][0]+=timedelta(minutes=1);capture(wired,'HK.00001')
    r=selection(wired)
    assert len(r['materials'])==1
    assert len(r['materials'][0]['capture_occurrences'])==2
    assert len({x['run_id'] for x in r['materials'][0]['capture_occurrences']})==2


def test_cross_day_legacy_index_is_preserved_before_first_new_day_same_url(wired):
    svc,p,clock=wired
    clock[0]=datetime.fromisoformat('2026-09-29T19:00:00+08:00');capture(wired,'HK.00001')
    root=svc.store.root/'workspace_announcements/20260929/eastmoney_hk'
    path=next(f for f in root.glob('*.json') if f.name!='latest.json')
    product=json.loads(path.read_bytes());product.pop('commit_protocol');product.pop('attempt_run_id');product.pop('sweep')
    product=ann._seal(product);svc.store._write_atomic(path,product);svc.store._write_atomic(root/'latest.json',product)
    # Original legacy storage had no immutable index observations.
    for f in (svc._material_store.root/'observations/eastmoney_hk').glob('*.json'):f.unlink()
    old=path.read_bytes()
    clock[0]=datetime.fromisoformat('2026-09-30T08:00:00+08:00');p.listing_revision=8
    capture(wired,'HK.00001');r=selection(wired)
    assert len(r['materials'])==1 and len(r['captures'])==2
    assert r['materials'][0]['available_at']=='2026-09-29T19:00:00+08:00'
    assert path.read_bytes()==old


def test_incomplete_new_run_cannot_be_admitted_from_latest_pointer(wired):
    capture(wired,'HK.00001');svc,p,clock=wired
    root=svc.store.root/'workspace_announcements/20260930/eastmoney_hk'
    named=next(f for f in root.glob('*.json') if f.name!='latest.json');named.unlink()
    r=selection(wired)
    assert r['materials']==[] and r['captures']==[]
    assert 'EASTMONEY_HK_LATEST_RUN_NOT_COMMITTED' in r['gaps']


def test_history_limit_refuses_without_unbounded_read_or_fetch(wired,monkeypatch):
    capture(wired,'HK.00001');wired[2][0]+=timedelta(minutes=1);capture(wired,'HK.00002')
    from v4.manager_research import eastmoney_run_history as history
    monkeypatch.setattr(history,'MAX_RUNS',1)
    before=snapshot(wired[0].store.root);calls=len(wired[1].calls)
    r=selection(wired)
    assert not r['materials'] and 'EASTMONEY_HK_HISTORY_RUN_BUDGET' in r['gaps']
    assert before==snapshot(wired[0].store.root) and len(wired[1].calls)==calls


def test_retention_write_failure_prevents_overwrite_of_legacy_latest_index(wired,monkeypatch):
    capture(wired,'HK.00001');svc,p,clock=wired
    for f in (svc._material_store.root/'observations/eastmoney_hk').glob('*.json'):f.unlink()
    before=snapshot(svc.store.root);calls=len(p.calls)
    original=svc._material_store._io.write_bytes
    def fail_observation(relative,raw,**kw):
        if relative.startswith('observations/'):raise OSError('SYNTHETIC_DISK_FULL')
        return original(relative,raw,**kw)
    monkeypatch.setattr(svc._material_store._io,'write_bytes',fail_observation)
    clock[0]+=timedelta(minutes=1)
    with pytest.raises(ValueError,match='RETENTION_WRITE_FAILED'):capture(wired,'HK.00001')
    assert len(p.calls)==calls and snapshot(svc.store.root)==before
    assert len(selection(wired)['materials'])==1
