from datetime import datetime,timedelta
from io import BytesIO
import hashlib
import json
from types import SimpleNamespace
from urllib.parse import parse_qs,urlsplit
import pytest
from v4.manager_workbench.contracts import RunContext
from v4.manager_workbench.inputs.capture import (capture_window,capture_announcements,resolve_publication_window,
    date_scoped_url,content_url,hkex_directory_url,_hkex_page)
from v4.manager_workbench.inputs.capture_store import CaptureStore,OWNER
from v4.manager_workbench.inputs.pdf_pages import extract_pdf_pages,pinned_pypdf

NOW=datetime.fromisoformat('2026-10-13T09:20:00+08:00')


def context(target='20261013',phase='PREOPEN',cutoff='2026-10-13T09:25:00+08:00'):
    return RunContext(target_date=target,phase=phase,cutoff=cutoff,trigger='SCHEDULED',rules_version='POSITIVE_OPERATING_RESEARCH_V1')


def store(tmp_path,source='EASTMONEY_HK'):
    result=CaptureStore(tmp_path/'cache',source=source,clock=lambda:NOW)
    result.grant(expires_at=NOW+timedelta(hours=1));return result


def listing(i=1,day='2026-10-13',code='00001'):
    return dict(art_code=f'AN202610130000{i:04d}',title=f'Article {i}',notice_date=day+' 00:00:00',
        display_time=day+' 09:00:00',codes=[dict(market_code='116',ann_type='H',stock_code=code,short_name='Issuer')])


def body(row,page=1,total=1):
    return dict(art_code=row['art_code'],notice_title=row['title'],notice_date=row['notice_date'],page_size=total,
        security=[dict(market_uni='116',stock=row['codes'][0]['stock_code'])],notice_content=f'Original page {page}\n  verbatim whitespace')


class Transport:
    def __init__(self,rows=None,body_pages=1):self.rows=rows if rows is not None else [listing()];self.calls=[];self.body_pages=body_pages;self.fail=set();self.rewrite={};self.after=None
    def get(self,url,**kwargs):
        assert kwargs==dict(timeout=(5,20),allow_redirects=False)
        self.calls.append(url);query=parse_qs(urlsplit(url).query);page=int(query['page_index'][0])
        if url in self.fail:raise OSError('injected failure')
        if 'begin_time' in query:
            day=query['begin_time'][0];rows=[r for r in self.rows if r['notice_date'][:10]==day]
            value=dict(list=rows[(page-1)*20:page*20],total_hits=len(rows),page_index=page,page_size=20)
        else:
            row=next(r for r in self.rows if r['art_code']==query['art_code'][0]);value=body(row,page,self.body_pages)
        if url in self.rewrite:value.update(self.rewrite[url])
        if self.after:self.after(url)
        return SimpleNamespace(status_code=200,url=url,content=json.dumps(dict(success=1,data=value)).encode())


def capture(ctx,cache,transport):return capture_window(ctx,dict(publication_date='20261013',transport=transport),cache)


def files(root):return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}


def test_date_protocol_and_nextday_calendar_window():
    assert parse_qs(urlsplit(date_scoped_url('20261013',1)).query)==dict(ann_type=['H'],client_source=['web'],f_node=['0'],begin_time=['2026-10-13'],end_time=['2026-10-13'],page_size=['20'],page_index=['1'])
    w=resolve_publication_window(context())
    assert w['publication_window_start']=='2026-10-09T16:10:00+08:00'
    assert w['publication_dates']==['2026-10-09','2026-10-10','2026-10-11','2026-10-12','2026-10-13']
    assert w['left_inclusive'] is False and w['research_cutoff'].endswith('09:25:00+08:00')
    nextday=resolve_publication_window(context('20261014','NEXT_DAY','2026-10-13T16:30:00+08:00'))
    assert nextday['publication_dates']==['2026-10-12','2026-10-13'] and nextday['target_trade_date']=='20261014'
    with pytest.raises(ValueError,match='FUTURE_PUBLICATION'):resolve_publication_window(context('20261014','NEXT_DAY','2026-10-13T16:30:00+08:00'),publication_date='20261014')
    with pytest.raises(ValueError,match='NEXT_DAY_TARGET'):resolve_publication_window(context('20261015','NEXT_DAY','2026-10-13T16:30:00+08:00'))


def test_weekend_target_and_halfday_close_boundaries():
    with pytest.raises(ValueError,match='TARGET_NOT_HK'):resolve_publication_window(context('20261010'))
    # Christmas Eve is a native half-day; full/half closes remain distinct.
    w=resolve_publication_window(context('20261230','PREOPEN','2026-12-30T09:25:00+08:00'))
    assert w['publication_window_start']=='2026-12-24T12:10:00+08:00'
    day=resolve_publication_window(context(),publication_date='20261012')
    assert day['publication_dates']==['2026-10-12'] and day['publication_window_end']=='2026-10-13T00:00:00+08:00'


def test_complete_251_directory_no_truncation_and_cache_restart(tmp_path):
    cache=store(tmp_path);transport=Transport([listing(i) for i in range(1,252)])
    product=capture(context(),cache,transport)
    assert product['observed_count']==251 and product['scope_count']==251 and not product['gaps']
    day=product['catalogues'][0];assert len(day['page_receipts'])==14 and day['terminal_empty_seen']
    assert len(transport.calls)==14+251
    restarted=CaptureStore(cache.io.root,token=cache.token,clock=lambda:NOW)
    second=capture(context(),restarted,transport)
    assert len(transport.calls)==265 and second['rows'][250]['body_text']==product['rows'][250]['body_text']
    ref=product['saved_ref'];raw=cache.io.read_bytes(ref['artifact_ref']);assert hashlib.sha256(raw).hexdigest()==ref['sha256']
    assert json.loads(raw)['window']['research_cutoff']==context().cutoff


def test_empty_requires_terminal_evidence(tmp_path):
    cache=store(tmp_path);t=Transport([]);result=capture(context(),cache,t)
    assert result['scope_count']==0 and result['catalogues'][0]['terminal_empty_seen'] and len(t.calls)==1
    assert result['coverage_status']=='COMPLETE_OBSERVED_EASTMONEY_DATE_CATALOG'


def test_only_missing_body_page_repaired_and_fail_attempt_retained(tmp_path):
    cache=store(tmp_path);t=Transport(body_pages=3);missing=content_url(listing()['art_code'],2);t.fail.add(missing)
    first=capture(context(),cache,t)
    assert first['rows'][0]['body_complete'] is False and first['rows'][0]['content_page_count']==3
    assert [p['page_number'] for p in first['rows'][0]['pages']]==[1,3]
    firstfiles=files(cache.io.root);before=len(t.calls);t.fail.clear();second=capture(context(),cache,t)
    assert t.calls[before:]==[missing] and second['rows'][0]['body_complete']
    assert second['rows'][0]['body_text']=='\n\n'.join(body(listing(),i,3)['notice_content'] for i in range(1,4))
    assert all(files(cache.io.root)[p]==digest for p,digest in firstfiles.items() if p.startswith('attempts/') or p.startswith('products/'))


def test_only_missing_directory_page_repaired(tmp_path):
    cache=store(tmp_path);t=Transport([listing(i) for i in range(1,42)]);missing=date_scoped_url('20261013',2);t.fail.add(missing)
    first=capture(context(),cache,t);assert first['observed_count']==21 and first['catalogues'][0]['total_hits']==41 and first['gaps']
    before=len(t.calls);t.fail.clear();second=capture(context(),cache,t)
    assert second['observed_count']==41 and not second['gaps']
    assert t.calls[before:][0]==missing and date_scoped_url('20261013',1) not in t.calls[before:]
    assert len(t.calls[before:])==21 # missing directory + 20 missing article bodies


@pytest.mark.parametrize('patch,error',[
    ({'total_hits':2},'ROW_COUNT'),({'total_hits':True},'TOTAL_HITS'),({'page_index':2},'PAGE_IDENTITY'),
    ({'page_size':21},'PAGE_IDENTITY'),({'list':None},'ROW_COUNT'),({'total_hits':20001},'PAGE_LIMIT')])
def test_invalid_catalog_never_gets_success_pointer(tmp_path,patch,error):
    cache=store(tmp_path);t=Transport();url=date_scoped_url('20261013',1);t.rewrite[url]=patch
    result=capture(context(),cache,t);assert any(error in g for g in result['gaps']) and result['scope_count']==0
    assert not cache.io.files('requests') and cache.io.files('attempts/'+next((cache.io.root/'attempts').iterdir()).name)


def test_catalog_total_drift_terminal_and_duplicate_failclosed(tmp_path):
    cache=store(tmp_path);t=Transport([listing(i) for i in range(1,22)])
    t.rewrite[date_scoped_url('20261013',2)]={'total_hits':22,'list':[listing(21),listing(22)]}
    result=capture(context(),cache,t);assert 'CATALOG_TOTAL_HITS_DRIFT' in result['gaps']
    assert result['observed_count']==20 and result['coverage_status']=='PARTIAL'
    other=store(tmp_path/'other');duplicate=Transport([listing(),listing()]);result=capture(context(),other,duplicate)
    assert 'CATALOG_DUPLICATE_ARTICLE' in result['gaps'] and result['observed_count']==1


@pytest.mark.parametrize('patch,error',[
    ({'page_size':151},'TOTAL_INVALID'),({'page_size':True},'TOTAL_INVALID'),({'notice_title':'other'},'TITLE_OR_DATE'),
    ({'notice_date':'2026-10-12 00:00:00'},'TITLE_OR_DATE'),({'security':[{'market_uni':'105','stock':'00001'}]},'ISSUER_IDENTITY'),
    ({'notice_content':'  \n'},'TEXT_MISSING')])
def test_body_protocol_rejects_wrong_identity_or_incomplete(tmp_path,patch,error):
    cache=store(tmp_path);t=Transport();t.rewrite[content_url(listing()['art_code'],1)]=patch
    result=capture(context(),cache,t);assert any(error in g for g in result['rows'][0]['gaps'])
    assert result['rows'][0]['body_text'] is None


def test_body_page_total_drift_is_not_partial_text_success(tmp_path):
    cache=store(tmp_path);t=Transport(body_pages=3);t.rewrite[content_url(listing()['art_code'],2)]={'page_size':4}
    result=capture(context(),cache,t);assert 'BODY_PAGE_TOTAL_DRIFT' in result['rows'][0]['gaps'] and not result['rows'][0]['body_complete']


def test_body_full_150_pages_and_source_applicant_identity(tmp_path):
    cache=store(tmp_path);t=Transport([listing(code='H5354')],body_pages=150)
    result=capture(context(),cache,t);assert result['rows'][0]['content_page_count']==150 and result['rows'][0]['body_complete']
    assert result['rows'][0]['source_issuer_codes'][0]['code']=='H5354'
    assert result['connect_eligibility_status']=='NOT_ASSESSED' and result['semantic_status']=='NOT_REVIEWED'


def test_new_cutoff_refreshes_catalog_and_reuses_identical_body(tmp_path):
    cache=store(tmp_path);t=Transport();capture(context(),cache,t);before=len(t.calls)
    later=context(cutoff='2026-10-13T09:30:00+08:00');result=capture(later,cache,t)
    assert len(t.calls[before:])==2 and all('begin_time=' in url for url in t.calls[before:])
    assert result['rows'][0]['available_at']==NOW.isoformat()
    assert result['window']['research_cutoff']==later.cutoff


def test_missing_revoked_expired_lease_zero_request_zero_write(tmp_path):
    root=tmp_path/'absent';cache=CaptureStore(root,clock=lambda:NOW);t=Transport()
    with pytest.raises(ValueError,match='EXCLUSIVE_OWNER'):capture(context(),cache,t)
    assert not root.exists() and not t.calls
    cache=store(tmp_path);cache.revoke();before=files(cache.io.root)
    with pytest.raises(ValueError,match='REVOKED'):capture(context(),cache,t)
    assert files(cache.io.root)==before and not t.calls
    expired=CaptureStore(cache.io.root,token=cache.token,clock=lambda:NOW+timedelta(days=1))
    with pytest.raises(ValueError,match='REVOKED'):capture(context(),expired,t)
    assert files(cache.io.root)==before


def test_revoke_during_transport_discards_result_and_stale_generation(tmp_path):
    cache=store(tmp_path);t=Transport();t.after=lambda url:cache.revoke()
    with pytest.raises(ValueError,match='REVOKED'):capture(context(),cache,t)
    assert len(t.calls)==1 and not cache.io.files('requests') and not cache.io.files('products')
    stale=CaptureStore(cache.io.root,token=cache.token,clock=lambda:NOW)
    cache.grant(expires_at=NOW+timedelta(hours=1))
    with pytest.raises(ValueError,match='REVOKED'):stale.assert_exclusive_owner()
    with pytest.raises(ValueError,match='ALREADY_HELD'):CaptureStore(cache.io.root,clock=lambda:NOW).grant(expires_at=NOW+timedelta(hours=1))


def test_same_source_lease_conflict_across_different_caches(tmp_path):
    first=CaptureStore(tmp_path/'a',lease_root=tmp_path/'owner');first.grant(expires_at=datetime.now().astimezone()+timedelta(hours=1))
    second=CaptureStore(tmp_path/'b',lease_root=tmp_path/'owner')
    with pytest.raises(ValueError,match='ALREADY_HELD'):second.grant(expires_at=datetime.now().astimezone()+timedelta(hours=1))
    assert not (tmp_path/'b').exists()


def test_cached_raw_tampering_fails_no_refetch(tmp_path):
    cache=store(tmp_path);t=Transport();result=capture(context(),cache,t);ref=result['catalogues'][0]['page_receipts'][0]
    (cache.io.root/ref['artifact_ref']).write_bytes(b'bad');before=len(t.calls)
    changed=capture(context(),cache,t);assert 'CAPTURE_CACHED_SHA_MISMATCH' in changed['gaps'] and len(t.calls)==before


def test_batch_preserves_mirror_refs_and_missing_membership(tmp_path):
    cache=store(tmp_path);t=Transport(body_pages=2)
    result=capture_announcements(context(),dict(publication_date='20261013',transport=t),cache)
    record=result.records[0];assert record['owner']=='EASTMONEY_MIRROR' and record['membership'] is None and record['body_complete']
    assert record['source_page_count']==2 and record['publication_time_status']=='CANNOT_CONFIRM'
    assert any(r.sha256==record['source_sha256'] and r.role=='ANNOUNCEMENT_BODY' for r in result.evidence_refs)
    assert result.input_sha256 and 'MONTHLY_CONNECT' in result.gaps[-1]


def test_pdf_true_positions_blank_failure_and_exact_whitespace():
    class Page:
        def __init__(self,text):self.text=text
        def extract_text(self):
            if isinstance(self.text,Exception):raise self.text
            return self.text
    reader=lambda *args,**kwargs:SimpleNamespace(pages=[Page('x\n  y'),Page(' \n'),Page(ValueError('bad page')),Page('last')])
    value=extract_pdf_pages(b'%PDF-test',reader_factory=reader)
    assert value['page_count']==4 and value['nonempty_page_count']==2 and value['page_coverage_complete']
    assert [p['page_number'] for p in value['pages']]==[1,2,3,4]
    assert [p['status'] for p in value['pages']]==['COMPLETE','BLANK','FAILED','COMPLETE']
    assert value['pages'][0]['text']=='x\n  y' and value['complete'] is False


def test_pdf_real_pinned_dependency_preserves_blank_pages():
    pdf=pinned_pypdf();writer=pdf.PdfWriter();writer.add_blank_page(width=72,height=72);writer.add_blank_page(width=72,height=72)
    raw=BytesIO();writer.write(raw);value=extract_pdf_pages(raw.getvalue())
    assert value['page_count']==2 and [p['page_number'] for p in value['pages']]==[1,2]
    assert value['nonempty_page_count']==0 and value['complete'] is False
    assert pdf.__version__=='6.10.0'


def test_hkex_cumulative_protocol_br_codes_and_drift(tmp_path):
    cache=store(tmp_path,'HKEX_OFFICIAL');calls=[]
    class T:
        def get(self,url,**kwargs):
            calls.append(url);n=int(parse_qs(urlsplit(url).query)['rowRange'][0]);rows=[dict(NEWS_ID=str(i),STOCK_CODE='00001<br/>00002\n00003',FILE_LINK='/a.pdf') for i in range(1,min(n,230)+1)]
            return SimpleNamespace(status_code=200,url=url,content=json.dumps(dict(recordCnt=230,rowRange=n,loadedRecord=len(rows),hasNextRow=len(rows)<230,result=json.dumps(rows))).encode())
    result=capture_announcements(context(),dict(source='HKEX_OFFICIAL',from_date='20261013',to_date='20261013',max_bodies=0,transport=T()),cache)
    assert [int(parse_qs(urlsplit(u).query)['rowRange'][0]) for u in calls]==[100,200,300]
    assert result.coverage.observed_count==230 and len(result.records)==690
    assert {r['symbol'] for r in result.records}=={'HK.00001','HK.00002','HK.00003'}
    with pytest.raises(ValueError,match='ROW_RANGE'):hkex_directory_url('20261013','20261013',0)
    with pytest.raises(ValueError,match='COUNT_DRIFT'):_hkex_page(json.dumps(dict(recordCnt=0,loadedRecord=0,rowRange=100,hasNextRow=False,result=[])).encode(),100,1)


def test_after_cutoff_capture_retains_honest_availability_gap(tmp_path):
    cache=store(tmp_path);cache.clock=lambda:NOW+timedelta(minutes=10);t=Transport()
    result=capture(context(),cache,t)
    assert result['rows'][0]['body_complete'] and result['rows'][0]['available_at']=='2026-10-13T09:30:00+08:00'
    assert 'CAPTURE_AVAILABLE_AFTER_RESEARCH_CUTOFF' in result['gaps']
    assert result['window']['research_cutoff']=='2026-10-13T09:25:00+08:00'


def test_new_observation_total_changes_without_overwriting_old_cache(tmp_path):
    cache=store(tmp_path);t=Transport();old=capture(context(),cache,t);old_raw=cache.io.read_bytes(old['saved_ref']['artifact_ref'])
    t.rows.append(listing(2));new=capture(context(cutoff='2026-10-13T09:30:00+08:00'),cache,t)
    assert new['observed_count']==2 and old['observed_count']==1
    assert cache.io.read_bytes(old['saved_ref']['artifact_ref'])==old_raw
    assert new['rows'][0]['body_text_sha256']==old['rows'][0]['body_text_sha256']


def test_terminal_page_failure_repair_only_empty_probe(tmp_path):
    cache=store(tmp_path);t=Transport();terminal=date_scoped_url('20261013',2);t.fail.add(terminal)
    old=capture(context(),cache,t);assert old['observed_count']==1 and 'CATALOG_TERMINAL_EMPTY_PAGE_MISSING' in old['gaps']
    before=len(t.calls);t.fail.clear();new=capture(context(),cache,t)
    assert not new['gaps'] and t.calls[before:]==[terminal]


@pytest.mark.parametrize('value',['００００１','H５３５４','HK.00001','000001','A0001'])
def test_catalog_rejects_unapproved_source_identifier(tmp_path,value):
    cache=store(tmp_path);t=Transport([listing(code=value)]);result=capture(context(),cache,t)
    assert 'CATALOG_HK_116_H_IDENTITY_INVALID' in result['gaps'] and result['observed_count']==0


def test_wrong_notice_date_row_is_not_silently_consumed(tmp_path):
    cache=store(tmp_path);t=Transport();t.rewrite[date_scoped_url('20261013',1)]={'list':[listing(day='2026-10-12')]}
    result=capture(context(),cache,t);assert 'CATALOG_NOTICE_DATE_MISMATCH' in result['gaps'] and result['observed_count']==0


def test_protocol_preserves_non_midnight_notice_date_and_normal_body_prefix(tmp_path):
    cache=store(tmp_path);row=listing();row['notice_date']='2026-10-13 08:00:00';t=Transport([row])
    t.rewrite[content_url(row['art_code'],1)]={'notice_date':' 2026-10-13 08:00:00'}
    result=capture(context(),cache,t);assert result['rows'][0]['body_complete']


def test_store_serializes_same_request_parallel_callers(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    cache=store(tmp_path);t=Transport();url=date_scoped_url('20261013',1)
    args=dict(scope={'frozen':'identity'},transport=t,validate=lambda raw:json.loads(raw))
    with ThreadPoolExecutor(max_workers=2) as pool:
        one=pool.submit(cache.fetch,url,**args);two=pool.submit(cache.fetch,url,**args)
        a=one.result();b=two.result()
    assert len(t.calls)==1 and a[0]==b[0] and a[1]['sha256']==b[1]['sha256']


def test_pdf_invalid_limits_and_cooperative_timeout_preserve_positions():
    with pytest.raises(ValueError,match='BUDGET'):extract_pdf_pages(b'%PDF-test',seconds=float('nan'),reader_factory=lambda *a,**k:None)
    class Slow:
        def extract_text(self):
            import time;time.sleep(.01);return 'first'
    value=extract_pdf_pages(b'%PDF-test',seconds=.001,reader_factory=lambda *a,**k:SimpleNamespace(pages=[Slow(),Slow()]))
    assert value['page_count']==2 and value['pages'][0]['status']=='COMPLETE' and value['pages'][1]['status']=='FAILED'
    assert value['pages'][1]['page_number']==2 and 'COOPERATIVE' in value['pages'][1]['error']


def test_success_receipt_crash_pointer_recovery_without_request(tmp_path):
    cache=store(tmp_path);t=Transport();result=capture(context(),cache,t)
    receipt=result['catalogues'][0]['page_receipts'][0]
    (cache.io.root/f'requests/{receipt["request_sha256"]}.json').unlink()
    before=len(t.calls);again=capture(context(),cache,t)
    assert len(t.calls)==before and not again['gaps']
    assert again['catalogues'][0]['page_receipts'][0]['sha256']==receipt['sha256']


def test_receipt_metadata_tamper_does_not_reclassify_cutoff(tmp_path):
    cache=store(tmp_path);t=Transport();result=capture(context(),cache,t)
    receipt=result['catalogues'][0]['page_receipts'][0];path=cache.io.root/f'requests/{receipt["request_sha256"]}.json'
    altered=json.loads(path.read_bytes());altered['available_at']='2026-10-12T01:00:00+08:00';path.write_text(json.dumps(altered))
    before=len(t.calls);again=capture(context(),cache,t)
    assert 'CAPTURE_REQUEST_OR_RECEIPT_IDENTITY_CONFLICT' in again['gaps'] and len(t.calls)==before


@pytest.mark.parametrize('url',['https://example.com/api/security/ann','https://np-anotice-stock.eastmoney.com/other','https://user@np-anotice-stock.eastmoney.com/api/security/ann','http://np-anotice-stock.eastmoney.com/api/security/ann'])
def test_unapproved_transport_destination_zero_requests(tmp_path,url):
    cache=store(tmp_path);t=Transport();before=files(cache.io.root)
    with pytest.raises(ValueError,match='APPROVED_SOURCE'):cache.fetch(url,scope={},transport=t,validate=lambda raw:None)
    assert not t.calls and files(cache.io.root)==before


def test_full_plan_window_empty_calendar_dates_have_distinct_evidence_identity(tmp_path):
    cache=store(tmp_path);t=Transport([listing(day='2026-10-12')])
    result=capture_window(context(),dict(transport=t),cache)
    assert result['window']['publication_dates']==['2026-10-09','2026-10-10','2026-10-11','2026-10-12','2026-10-13']
    assert len(result['catalogues'])==5 and result['observed_count']==1 and not result['gaps']
    refs=result['evidence_refs'];assert len({r['evidence_id'] for r in refs})==len(refs)
    assert result['rows'][0]['publication_date']=='2026-10-12' and result['target_trade_date']=='20261013'


def test_open_plan_window_boundaries_preserve_catalogue_isolate_consumption(tmp_path):
    rows=[]
    for i,stamp in enumerate(['2026-10-09 16:09:59','2026-10-09 16:10:00','2026-10-09 16:10:01','2026-10-13 09:25:00','2026-10-13 09:25:01'],1):
        row=listing(i,day=stamp[:10]);row['display_time']=stamp;rows.append(row)
    cache=store(tmp_path);t=Transport(rows);product=capture_window(context(),dict(transport=t),cache)
    assert product['scope_count']==5 and product['observed_count']==5 and len(product['rows'])==5
    assert [a['publication_window_status'] for a in product['rows']]==['OUTSIDE_LEFT_BOUNDARY','OUTSIDE_LEFT_BOUNDARY','INSIDE_SOURCE_DISPLAY_WINDOW','INSIDE_SOURCE_DISPLAY_WINDOW','OUTSIDE_RIGHT_BOUNDARY']
    assert len([u for u in t.calls if '/api/content/' in u])==2
    assert all(a['body_text'] is None and a['body_status']=='NOT_REQUESTED_OUTSIDE_RESEARCH_WINDOW' for a in product['rows'] if a['window_consumption_status']=='EXCLUDED_OUTSIDE_WINDOW')
    result=capture_announcements(context(),dict(transport=t),cache)
    assert len(result.records)==2 and {r['title'] for r in result.records}=={'Article 3','Article 4'}
    assert all(a['publication_time_basis']=='EASTMONEY_MIRROR_DISPLAY_TIME_NOT_OFFICIAL_HKEX_PIT' for a in product['rows'])


def test_daily_window_inclusive_midnight_and_exclusive_next_midnight(tmp_path):
    rows=[]
    for i,stamp in enumerate(['2026-10-11 23:59:59','2026-10-12 00:00:00','2026-10-12 23:59:59','2026-10-13 00:00:00'],1):
        row=listing(i,day='2026-10-12');row['display_time']=stamp;rows.append(row)
    cache=store(tmp_path);t=Transport(rows);request=dict(publication_date='20261012',transport=t)
    result=capture_window(context(),request,cache)
    assert [a['window_consumption_status'] for a in result['rows']]==['EXCLUDED_OUTSIDE_WINDOW','ELIGIBLE_SOURCE_TIME','ELIGIBLE_SOURCE_TIME','EXCLUDED_OUTSIDE_WINDOW']
    assert len(capture_announcements(context(),request,cache).records)==2
    today=store(tmp_path/'today');t=Transport()
    t.rows[0]['display_time']='2026-10-13 09:25:00'
    assert capture(context(),today,t)['rows'][0]['window_consumption_status']=='ELIGIBLE_SOURCE_TIME'


@pytest.mark.parametrize('characters,complete',[(500000,True),(500001,False)])
def test_cumulative_body_character_limit_exact_and_cache_replay(tmp_path,characters,complete):
    cache=store(tmp_path);t=Transport(body_pages=2)
    for page in (1,2):t.rewrite[content_url(listing()['art_code'],page)]={'notice_content':'x'*characters}
    result=capture(context(),cache,t);article=result['rows'][0]
    assert article['body_complete'] is complete and article['text_characters']==characters*2
    assert len(article['pages'])==2 and all(len(p['text'])==characters for p in article['pages'])
    if complete:assert len(article['body_text'])==1_000_002
    else:assert article['body_text'] is None and 'BODY_CONTENT_TEXT_LIMIT_EXCEEDED' in article['gaps']
    before=len(t.calls);again=capture(context(),cache,t)
    assert len(t.calls)==before and again['rows'][0]['body_complete'] is complete
    assert again['rows'][0]['pages']==article['pages']


def test_observed_eastmoney_millisecond_format_preserved_and_cutoff_exact(tmp_path):
    rows=[]
    for i,stamp in enumerate(['2026-10-13 13:27:48:470','2026-10-13 12:12:21:499','2026-10-13 12:05:57:440','2026-10-13 09:25:00:000','2026-10-13 09:25:00:001'],1):
        row=listing(i);row['display_time']=stamp;rows.append(row)
    cache=store(tmp_path);result=capture(context(),cache,Transport(rows))
    assert [a['source_display_time_raw'] for a in result['rows']]==[r['display_time'] for r in rows]
    assert result['rows'][0]['display_time']=='2026-10-13T13:27:48.470000+08:00'
    assert result['rows'][1]['display_time']=='2026-10-13T12:12:21.499000+08:00'
    assert result['rows'][3]['window_consumption_status']=='ELIGIBLE_SOURCE_TIME'
    assert result['rows'][4]['window_consumption_status']=='EXCLUDED_OUTSIDE_WINDOW'


@pytest.mark.parametrize('suffix',[':47',':4700','.470',':abc','Z',':470more'])
def test_millisecond_format_does_not_accept_unobserved_suffix(tmp_path,suffix):
    row=listing();row['display_time']='2026-10-13 09:00:00'+suffix
    result=capture(context(),store(tmp_path),Transport([row]))
    assert 'CATALOG_DISPLAY_TIME_INVALID' in result['gaps'] and result['observed_count']==0
