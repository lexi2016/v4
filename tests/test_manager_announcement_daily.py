from datetime import datetime, timedelta
from uuid import uuid4
from urllib.parse import parse_qs

from announcement_autorun_fixtures import OwnerFixture, pdf_bytes
from v4.manager_research import announcement_source as source
from v4.manager_research.ports import SourceResponse
from v4.manager_research import workspace_announcements as owner
from v4.manager_research.workspace_plan import plan_context


DAY = '20260924'


def _native_empty_page(start: str, end: str, stock_id: str, stock_code: str) -> bytes:
    return f'''<!doctype html><html><body>
<form id="j_idt10" name="j_idt10" method="post" action="/search/titlesearch.xhtml">
<input type="hidden" id="startDate" value="{start}" />
<input type="hidden" id="endDate" value="{end}" />
<input type="hidden" id="stockId" value="{stock_id}" />
<input type="hidden" id="stockCode" value="{stock_code}" />
<input type="hidden" id="searchTypeInt" value="0" />
<input type="hidden" id="selectedDocType" value="-1" />
<input type="hidden" id="selectedSecurities" value="0" />
<div id="recordCountPanel"><div class="total-records">Total records found: 0 </div></div>
<div id="titleSearchResultPanel"><div class="result_norecords">No matches found</div></div>
</form></body></html>'''.encode()


def _install_native_empty_transport(fixture):
    original_transport = fixture.transport

    def transport(url, *, timeout, method='GET', body=None, headers=None):
        if method != 'POST':
            return original_transport(url, timeout=timeout, method=method, body=body, headers=headers)
        form = parse_qs((body or b'').decode())
        stock_id = form['stockId'][0]
        code = stock_id.zfill(5)
        symbol = f'HK.{code}'
        if fixture.rows.get(symbol) or symbol in fixture.fail:
            return original_transport(url, timeout=timeout, method=method, body=body, headers=headers)
        raw = _native_empty_page(
            f"{form['from'][0][:4]}-{form['from'][0][4:6]}-{form['from'][0][6:]}",
            f"{form['to'][0][:4]}-{form['to'][0][4:6]}-{form['to'][0][6:]}",
            stock_id, f'{code} Fixture Issuer',
        )
        return SourceResponse(url=url, final_url=url, status_code=200, headers={},
                              body=raw, retrieved_at=fixture.now.isoformat())

    fixture.provider._material_transport._transport = transport


def test_hk_calendar_day_window_keeps_midnight_and_actual_cutoff_separate():
    hk_now = datetime.fromisoformat('2026-09-24T08:00:00+08:00')
    current = owner._daily_context(DAY, now=hk_now)
    assert source.publication_in_window(datetime.fromisoformat('2026-09-24T00:00:00+08:00'), current)
    assert source.publication_in_window(hk_now, current)
    assert not source.publication_in_window(datetime.fromisoformat('2026-09-24T08:00:00.000001+08:00'), current)
    assert current['research_cutoff'] == hk_now.isoformat()
    assert source.request_context(current)['as_of'].startswith(DAY[:4] + '-' + DAY[4:6] + '-' + DAY[6:])

    historical_now = datetime.fromisoformat('2026-09-25T10:00:00+08:00')
    historical = owner._daily_context(DAY, now=historical_now)
    assert source.publication_in_window(datetime.fromisoformat('2026-09-24T23:59:59.999999+08:00'), historical)
    assert not source.publication_in_window(datetime.fromisoformat('2026-09-25T00:00:00+08:00'), historical)
    assert historical['research_cutoff'] == historical_now.isoformat()
    assert source.request_context(historical)['as_of'].startswith('2026-09-24')

    try:
        owner._daily_context('20260925', now=hk_now)
    except ValueError as exc:
        assert str(exc) == 'ANNOUNCEMENT_FUTURE_PUBLICATION_DATE_NOT_ALLOWED'
    else:
        raise AssertionError('future publication dates must be rejected')


def test_daily_updates_rotate_three_issuers_keep_union_and_reuse_parsed_pdf(tmp_path, monkeypatch):
    codes=[f'HK.{number:05d}' for number in range(1,7)]
    fixture=OwnerFixture(tmp_path,monkeypatch,codes)
    _install_native_empty_transport(fixture)
    existing_url=fixture.add(code='HK.00001',slug='same-event',text='Unique cached body for daily reuse 20261003.')
    original_parser=source.extract_pdf_pages
    parser_calls=[]
    def counted_parser(raw,**kwargs):
        parser_calls.append(raw)
        return original_parser(raw,**kwargs)
    monkeypatch.setattr(source,'extract_pdf_pages',counted_parser)

    first=fixture.service.refresh_announcements(DAY)
    assert first['status']=='PARTIAL'
    assert first['coverage']['observed_document_count']==1
    assert len(parser_calls)==1
    first_run=first['capture_runs'][0]
    assert first_run['query_cutoff']=='2026-09-24T08:00:00+08:00'
    assert len(first['coverage']['queried_issuers'])==3

    fixture.now+=timedelta(minutes=1)
    second=fixture.service.refresh_announcements(DAY)
    assert second['coverage']['observed_document_count']==1
    assert second['capture_runs'][-1]['run_id']!=first_run['run_id']
    assert len(second['coverage']['queried_issuers'])==6
    assert len(parser_calls)==1

    fixture.now+=timedelta(minutes=1)
    third=fixture.service.refresh_announcements(DAY)
    assert third['coverage']['observed_document_count']==1
    assert third['official_documents'][0]['event_id']==first['official_documents'][0]['event_id']
    pdf_requests=[call['url'] for call in fixture.calls if call['url'].endswith('.pdf')]
    assert pdf_requests.count(existing_url)==1
    assert any(run['run_id']==first_run['run_id'] for run in third['capture_runs'])
    assert len(parser_calls)==1
    latest=fixture.service.store._read(fixture.service.store.root/'workspace_announcements'/DAY/'latest.json')
    assert len(latest['daily_parent_refs'])==2
    again=fixture.service.get_announcements(DAY)
    assert again['coverage']['observed_document_count']==1
    assert len(parser_calls)==1
    fixture.service.close()


def test_deterministic_pdf_budget_failure_cache_binds_body_parser_version_and_limits(monkeypatch):
    raw = pdf_bytes('Budget failure cache identity 20261003.', pages=41)
    changed = pdf_bytes('Changed budget failure cache identity 20261003.', pages=42)
    byte_limited = pdf_bytes('Byte limit invalidation identity 20261003.')
    text_limited = pdf_bytes('Text limit invalidation identity 20261003.')
    transient = pdf_bytes('Transient timeout retry identity 20261003.')
    original_parser = source.extract_pdf_pages
    parser_calls = []
    transient_attempts = []

    def counted_parser(body, **kwargs):
        parser_calls.append(body)
        if body == transient:
            transient_attempts.append(body)
            if len(transient_attempts) == 1:
                raise RuntimeError('PDF_TIME_BUDGET_EXCEEDED')
        return original_parser(body, **kwargs)

    monkeypatch.setattr(source, 'extract_pdf_pages', counted_parser)

    def parse_result(body, cache_stats, **kwargs):
        try:
            return source._cached_extract_pdf_pages(body, cache_stats=cache_stats, **kwargs)
        except RuntimeError as exc:
            return str(exc)

    stats = {}
    assert parse_result(raw, stats) == 'PDF_PAGE_BUDGET_EXCEEDED'
    assert stats['pdf_reparses'] == 1
    assert parse_result(raw, stats) == 'PDF_PAGE_BUDGET_EXCEEDED'
    assert stats['pdf_reparses'] == 1
    assert stats['pdf_parse_cache_hits'] == 1
    assert parse_result(changed, stats) == 'PDF_PAGE_BUDGET_EXCEEDED'
    assert stats['pdf_reparses'] == 2

    monkeypatch.setattr(source, 'PARSER_VERSION', source.PARSER_VERSION + '.cache-key-check')
    assert parse_result(raw, stats) == 'PDF_PAGE_BUDGET_EXCEEDED'
    assert stats['pdf_reparses'] == 3

    assert parse_result(raw, stats, max_pages=39) == 'PDF_PAGE_BUDGET_EXCEEDED'
    assert stats['pdf_reparses'] == 4
    assert parse_result(raw, stats, max_pages=39) == 'PDF_PAGE_BUDGET_EXCEEDED'
    assert stats['pdf_reparses'] == 4
    page_limited_result = parse_result(raw, stats, max_pages=41)
    assert isinstance(page_limited_result, list) and len(page_limited_result) == 41
    assert stats['pdf_reparses'] == 5

    assert parse_result(byte_limited, stats, max_bytes=len(byte_limited) - 1) == 'PDF_BYTE_BUDGET_EXCEEDED'
    assert stats['pdf_reparses'] == 6
    assert parse_result(byte_limited, stats, max_bytes=len(byte_limited) - 1) == 'PDF_BYTE_BUDGET_EXCEEDED'
    assert stats['pdf_reparses'] == 6
    byte_limit_revalidated = parse_result(byte_limited, stats, max_bytes=len(byte_limited))
    assert isinstance(byte_limit_revalidated, list)
    assert stats['pdf_reparses'] == 7

    assert parse_result(text_limited, stats, max_text_characters=1) == 'PDF_TEXT_BUDGET_EXCEEDED'
    assert stats['pdf_reparses'] == 8
    assert parse_result(text_limited, stats, max_text_characters=1) == 'PDF_TEXT_BUDGET_EXCEEDED'
    assert stats['pdf_reparses'] == 8
    text_limit_revalidated = parse_result(text_limited, stats, max_text_characters=1000)
    assert isinstance(text_limit_revalidated, list)
    assert stats['pdf_reparses'] == 9

    assert parse_result(transient, stats, timeout_seconds=0.01) == 'PDF_TIME_BUDGET_EXCEEDED'
    assert stats['pdf_reparses'] == 10
    timeout_retry = parse_result(transient, stats, timeout_seconds=0.01)
    assert isinstance(timeout_retry, list)
    assert stats['pdf_reparses'] == 11
    assert len(transient_attempts) == 2
    assert len(parser_calls) == 11

def test_refresh_reuses_budget_failure_but_still_revalidates_original_body(tmp_path, monkeypatch):
    fixture = OwnerFixture(tmp_path, monkeypatch, ['HK.00001', 'HK.00002', 'HK.00003'])
    _install_native_empty_transport(fixture)
    url = fixture.add(code='HK.00001', slug='cached-page-budget',
                      text='Refresh budget cache identity 20261003.', pages=41)
    original_parser = source.extract_pdf_pages
    parser_calls = []

    def counted_parser(body, **kwargs):
        parser_calls.append(body)
        return original_parser(body, **kwargs)

    monkeypatch.setattr(source, 'extract_pdf_pages', counted_parser)
    first = fixture.service.refresh_announcements(DAY)
    assert first['status'] == 'PARTIAL'
    assert len(parser_calls) == 1
    latest = fixture.service.store._read(
        fixture.service.store.root / 'workspace_announcements' / DAY / 'latest.json')
    doc = next(item for item in latest['documents'] if item['row']['url'] == url)
    assert doc['parse_status'] == 'FAILED'
    assert doc['reason'] == 'PDF_PAGE_BUDGET_EXCEEDED'

    repeated = fixture.service.get_announcements(DAY)
    assert repeated['coverage']['source_revalidation']['pdf_reparses'] == 0
    assert len(parser_calls) == 1
    blob = fixture.materials.root / fixture.materials._blob_relative(doc['body_ref']['blob_sha256'])
    blob.write_bytes(b'corrupted after deterministic negative parse cache')
    assert fixture.service.get_announcements(DAY)['status'] == 'READBACK_FAILED'
    assert len(parser_calls) == 1
    fixture.service.close()


def test_legacy_cross_day_capture_projects_selected_date_without_relabeling_source(tmp_path, monkeypatch):
    fixture=OwnerFixture(tmp_path,monkeypatch,['HK.00001','HK.09690'])
    today_url=fixture.add(code='HK.00001',slug='today')
    yesterday_url='https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0923/00001-yesterday.pdf'
    fixture.rows['HK.00001'].append((yesterday_url,datetime.fromisoformat('2026-09-23T20:00:00+08:00')))
    fixture.pdfs[yesterday_url]=fixture.pdfs[today_url]

    context=plan_context(DAY,now=fixture.now)
    names,witness=owner._master(fixture.service,context)
    batch=fixture.provider.collect_announcement_batch(context=context,
        issuers=[dict(code='HK.00001',name=names['HK.00001']['name'])])
    product=owner._seal(dict(schema_version=owner.SCHEMA,owner=owner.OWNER,target_trade_date=DAY,
        run_id=uuid4().hex,revision=1,context=context,identity_witness=witness,scope=sorted(names),
        scan_order=sorted(names),scope_identity=owner.digest([witness,sorted(names)]),next_index=1,
        queries=batch['queries'],documents=batch['documents'],pending_documents=batch['pending_documents'],
        generated_at=fixture.now.isoformat(),parser_revision=source.PARSER_VERSION,
        execution_kind='MANUAL_REFRESH',natural_run_verified=False,**owner.FLAGS))
    owner.validate_product(product,DAY);owner._check_sources(fixture.service,product)
    root=fixture.service.store.root/'workspace_announcements'/DAY
    fixture.service.store._write_atomic(root/product['run_id']/'1.json',product)
    fixture.service.store._write_atomic(root/'latest.json',product)

    review=fixture.service.get_announcements(DAY)
    assert review['target_trade_date']==DAY
    assert len(review['official_documents'])==1
    assert review['official_documents'][0]['source_url']==today_url
    assert review['official_documents'][0]['capture_trade_date']==DAY
    assert review['retained_cross_day']['counts_by_publication_date']=={'20260923':1}
    assert review['coverage']['source_coverage_cutoff']==fixture.now.isoformat()
    fixture.service.close()


def test_warm_pdf_parse_cache_does_not_skip_raw_source_validation(tmp_path, monkeypatch):
    fixture=OwnerFixture(tmp_path,monkeypatch,['HK.00001','HK.00002','HK.00003'])
    _install_native_empty_transport(fixture)
    fixture.add(code='HK.00001',slug='corrupt-after-cache',text='Unique raw validation body 20261003.')
    fixture.service.refresh_announcements(DAY)
    reads=[]
    original_read=owner.read_response
    def counted_read(store,ref):
        reads.append(ref['blob_sha256'])
        return original_read(store,ref)
    monkeypatch.setattr(owner,'read_response',counted_read)
    calls_before=sum(call['url'].endswith('.pdf') for call in fixture.calls)
    good=fixture.service.get_announcements(DAY)
    assert good['coverage']['source_revalidation']['pdf_reparses']==0
    assert reads and sum(call['url'].endswith('.pdf') for call in fixture.calls)==calls_before
    ref=good['official_documents'][0]['source_refs'][-1]
    blob=fixture.materials.root/fixture.materials._blob_relative(ref['blob_sha256'])
    blob.write_bytes(b'corrupted after cached parse')
    assert fixture.service.get_announcements(DAY)['status']=='READBACK_FAILED'
    fixture.service.close()
