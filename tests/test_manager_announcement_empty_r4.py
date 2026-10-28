"""Regression for verified HKEX title-search empty results."""
from datetime import timedelta
from hashlib import sha256
from urllib.parse import parse_qs

import pytest

from announcement_autorun_fixtures import OwnerFixture, DAY
from v4.manager_research.announcement_source import directory_entries
from v4.manager_research.ports import SourceResponse


def _native_empty_page(start: str, end: str, stock_id: str, stock_code: str) -> bytes:
    """Sanitized native structure retained by the real HKEX 00001 response."""
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


CONTEXT = {
    'focus_window_start': '2026-09-29T16:10:00+08:00',
    'research_cutoff': '2026-10-01T08:46:37.748536+08:00',
}


def _install_native_empty_transport(fixture):
    original_transport = fixture.transport

    def transport(url, *, timeout, method='GET', body=None, headers=None):
        if method != 'POST':
            return original_transport(url, timeout=timeout, method=method, body=body, headers=headers)
        form = parse_qs((body or b'').decode())
        stock_id = form['stockId'][0]
        raw = _native_empty_page(
            f"{form['from'][0][:4]}-{form['from'][0][4:6]}-{form['from'][0][6:]}",
            f"{form['to'][0][:4]}-{form['to'][0][4:6]}-{form['to'][0][6:]}",
            stock_id, f'{stock_id.zfill(5)} Fixture Issuer',
        )
        return SourceResponse(url=url, final_url=url, status_code=200, headers={},
                              body=raw, retrieved_at=fixture.now.isoformat())

    fixture.provider._material_transport._transport = transport


def _save_legacy_failed_query(fixture, *, reason='ANNOUNCEMENT_DIRECTORY_LAYOUT_OR_EMPTY_UNVERIFIED'):
    import v4.manager_research.workspace_announcements as owner

    product_path = fixture.service.store.root / 'workspace_announcements' / DAY / 'latest.json'
    product = fixture.service.store._read(product_path)
    query = next(q for q in product['queries'] if q['code'] == 'HK.00001')
    query.update(status='FAILED', entries=[], rejected=[], reason=reason)
    sealed = owner._seal(product)
    fixture.service.store._write_atomic(product_path, sealed)
    return product_path, sealed


def test_sanitized_hkex_empty_body_requires_exact_query_and_page_identity():
    raw = _native_empty_page('2026-09-29', '2026-10-01', '1', '00001 CKH HOLDINGS')
    entries, rejected, reason = directory_entries(
        raw, 'HK.00001', CONTEXT, expected_stock_id='1'
    )
    assert entries == [] and rejected == []
    assert reason == 'NO_ROWS_IN_OBSERVED_RESPONSE'


@pytest.mark.parametrize('raw,expected_stock_id', [
    (b'<html><body>No matches found</body></html>', '1'),
    (_native_empty_page('2026-09-29', '2026-10-01', '2', '00001 CKH HOLDINGS'), '1'),
    (_native_empty_page('2026-09-29', '2026-10-01', '1', '00002 CKH HOLDINGS'), '1'),
    (_native_empty_page('2026-09-28', '2026-10-01', '1', '00001 CKH HOLDINGS'), '1'),
    (_native_empty_page('2026-09-29', '2026-10-01', '1', '00001 CKH HOLDINGS'), None),
])
def test_generic_or_mismatched_empty_pages_stay_unverified(raw, expected_stock_id):
    with pytest.raises(ValueError, match='ANNOUNCEMENT_DIRECTORY_LAYOUT_OR_EMPTY_UNVERIFIED'):
        directory_entries(raw, 'HK.00001', CONTEXT, expected_stock_id=expected_stock_id)


def test_nonempty_hkex_rows_keep_existing_cutoff_and_issuer_filtering():
    row = b'''<tr>
<td class="release-time">30/09/2026 12:00</td>
<td class="stock-short-code">00001</td>
<td class="stock-short-name">CKH HOLDINGS</td>
<td><div class="doc-link"><a href="/listedco/listconews/sehk/2026/0930/example.pdf">Official notice</a></div></td>
</tr>'''
    raw = _native_empty_page('2026-09-29', '2026-10-01', '1', '00001 CKH HOLDINGS')
    raw = raw.replace(b'Total records found: 0', b'Total records found: 1')
    raw = raw.replace(b'<div id="titleSearchResultPanel"><div class="result_norecords">No matches found</div></div>',
                      b'<div id="titleSearchResultPanel"><table>' + row + b'</table></div>')
    entries, rejected, reason = directory_entries(
        raw, 'HK.00001', CONTEXT, expected_stock_id='1'
    )
    assert len(entries) == 1 and not rejected
    assert entries[0]['stock_code'] == '00001'
    assert reason == 'OBSERVED_DIRECTORY_ROWS'


def test_original_capture_and_readback_bind_verified_empty_to_official_stock_id(tmp_path, monkeypatch):
    fixture = OwnerFixture(tmp_path, monkeypatch, codes=('HK.00001',))
    _install_native_empty_transport(fixture)
    try:
        first = fixture.service.refresh_announcements(DAY)
        product_path = fixture.service.store.root / 'workspace_announcements' / DAY / 'latest.json'
        product = fixture.service.store._read(product_path)
        captured_query = next(q for q in product['queries'] if q['code'] == 'HK.00001')
        assert captured_query['status'] == 'OBSERVED'
        assert captured_query['entries'] == []
        assert captured_query['reason'] == 'NO_ROWS_IN_OBSERVED_RESPONSE'

        readback = fixture.service.get_announcements(DAY)
        assert readback['status'] != 'READBACK_FAILED'
        product = fixture.service.store._read(product_path)
        query = next(q for q in product['queries'] if q['code'] == 'HK.00001')
        assert query['status'] == 'OBSERVED'
        assert query['official_issuer']['stock_id'] == '00001'
        assert query['reason'] == 'NO_ROWS_IN_OBSERVED_RESPONSE'
    finally:
        fixture.service.close()


def test_legacy_failed_exact_empty_is_read_only_and_remains_failed(tmp_path, monkeypatch):
    fixture = OwnerFixture(tmp_path, monkeypatch, codes=('HK.00001',))
    _install_native_empty_transport(fixture)
    try:
        fixture.service.refresh_announcements(DAY)
        product_path, legacy = _save_legacy_failed_query(fixture)
        original_bytes = product_path.read_bytes()

        readback = fixture.service.get_announcements(DAY)

        assert readback['status'] == 'PARTIAL'
        assert readback['coverage']['failed_issuers'] == [dict(
            symbol='HK.00001', reason='ANNOUNCEMENT_DIRECTORY_LAYOUT_OR_EMPTY_UNVERIFIED')]
        assert readback['product_identity']['run_id'] == legacy['run_id']
        assert product_path.read_bytes() == original_bytes
        stored = fixture.service.store._read(product_path)
        query = next(q for q in stored['queries'] if q['code'] == 'HK.00001')
        assert query['status'] == 'FAILED'
        assert query['reason'] == 'ANNOUNCEMENT_DIRECTORY_LAYOUT_OR_EMPTY_UNVERIFIED'
        assert stored['run_id'] == legacy['run_id']
        assert stored['revision'] == legacy['revision']
    finally:
        fixture.service.close()


@pytest.mark.parametrize('case', ['different_reason', 'unverified_body', 'derivable_rows'])
def test_legacy_failed_empty_allowance_rejects_other_evidence(tmp_path, monkeypatch, case):
    fixture = OwnerFixture(tmp_path, monkeypatch, codes=('HK.00001',))
    try:
        if case == 'derivable_rows':
            fixture.add('HK.00001')
        else:
            _install_native_empty_transport(fixture)
        fixture.service.refresh_announcements(DAY)

        reason = ('ANNOUNCEMENT_OTHER_LEGACY_FAILURE' if case == 'different_reason'
                  else 'ANNOUNCEMENT_DIRECTORY_LAYOUT_OR_EMPTY_UNVERIFIED')
        product_path, legacy = _save_legacy_failed_query(fixture, reason=reason)

        if case == 'unverified_body':
            from v4.manager_research.material_transport import _encode_envelope

            product = fixture.service.store._read(product_path)
            query = next(q for q in product['queries'] if q['code'] == 'HK.00001')
            ref = query['directory_ref']
            raw = b'<html><body>No matches found</body></html>'
            envelope = _encode_envelope(SourceResponse(
                url=ref['request']['url'], final_url=ref['final_url'], status_code=200,
                headers={}, body=raw, retrieved_at=ref['retrieved_at']))
            material = fixture.materials.fetch(
                ref['source_key'], url=ref['request']['url'], ttl_seconds=None,
                transport=lambda _url: dict(body=envelope, retrieved_at=ref['retrieved_at'],
                    content_type='application/vnd.v4.source-envelope+json'), force=True)
            ref['blob_sha256'] = material.sha256
            ref['body_sha256'] = sha256(raw).hexdigest()
            import v4.manager_research.workspace_announcements as owner
            legacy = owner._seal(product)
            fixture.service.store._write_atomic(product_path, legacy)

        original_bytes = product_path.read_bytes()
        readback = fixture.service.get_announcements(DAY)

        if case == 'unverified_body':
            # A raw layout failure remains a faithful FAILED query; it does not
            # receive the new empty-result interpretation.
            assert readback['status'] == 'PARTIAL'
            assert readback['coverage']['failed_issuers'] == [dict(
                symbol='HK.00001', reason='ANNOUNCEMENT_DIRECTORY_LAYOUT_OR_EMPTY_UNVERIFIED')]
        else:
            assert readback['status'] == 'READBACK_FAILED'
            assert readback['gaps'] == ['ANNOUNCEMENT_FAILED_QUERY_HAS_DERIVABLE_DIRECTORY']
        assert product_path.read_bytes() == original_bytes
        stored = fixture.service.store._read(product_path)
        query = next(q for q in stored['queries'] if q['code'] == 'HK.00001')
        assert query['status'] == 'FAILED'
        assert query['reason'] == reason
        assert stored['run_id'] == legacy['run_id']
    finally:
        fixture.service.close()
