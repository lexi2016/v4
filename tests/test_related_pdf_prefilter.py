import hashlib

from domains import related_pdf_reports as reports


class FakeOwner:
    ZsxqPdfError = ValueError

    def __init__(self, index):
        self.index = index
        self.reads = 0

    def _read_index(self, store):
        return self.index

    def _latest_engine_run(self, row):
        return 'engine', row['artifact']

    def _safe_document_paths(self, source, artifact, engine):
        return artifact['paths']

    def _safe_artifact_path(self, root, relative):
        return root / relative

    def _verified_document_detail(self, store, index, doc_id, *, verify_pdf):
        assert verify_pdf is False
        self.reads += 1
        row = index['documents'][doc_id]
        artifact = row['artifact']
        raw = (store.root / artifact['paths'][1]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != artifact['pages_file_sha256']:
            raise ValueError('PAGE_SHA_MISMATCH')
        return {'status':'READY', 'document_id':doc_id, 'research_date':'20261027',
                'source':row['source'], 'pages':[{'text':raw.decode()}],
                'processing':{'verified_pages_size':len(raw)},
                'receipt':{'integrity':'SOURCE_AND_PAGE_HASHES_VERIFIED'}, **reports.SAFETY}


def test_exact_prefilter_keeps_verified_hits_and_rechecks_changed_pages(tmp_path):
    docs, candidates = {}, []
    for n, text in enumerate(('沪市 600000.SH 报告', '无关公司和数据'), 1):
        doc_id = str(n) * 64
        pdf, pages, receipt = (f'{n}.pdf', f'{n}.pages', f'{n}.receipt')
        (tmp_path / pdf).write_bytes(b'pdf')
        raw = text.encode()
        (tmp_path / pages).write_bytes(raw)
        (tmp_path / receipt).write_bytes(b'receipt')
        artifact = {'status':'READY', 'pdf_sha256':str(n + 2) * 64, 'pdf_size':3,
                    'pages_file_sha256':hashlib.sha256(raw).hexdigest(), 'paths':(pdf, pages, receipt)}
        docs[doc_id] = {'source':{'topic_title':'', 'original_filename':''}, 'artifact':artifact}
        candidates.append({'document_id':doc_id, 'research_date':'20261027',
                           'verified_pdf_sha256':artifact['pdf_sha256'], 'verified_pdf_size':3,
                           'verified_pages_size':len(raw)})
    reader = FakeOwner({'documents':docs})
    search = {'checkpoint_sha256':'a' * 64, 'candidates':candidates, 'coverage':{'gaps':[]}}
    parsed = {'A.600000':reports._symbol('600000.SH')}
    profiles = {'A.600000':{'exchange':'SH'}}
    terms = {'A.600000':['600000']}
    first = reports._exact_index_candidates(tmp_path, search, parsed, profiles, terms, reader)
    assert [c['document_id'] for c in first['candidates']] == ['1' * 64]
    assert first['coverage']['ocr_prefilter_checked'] == 2
    assert first['coverage']['ocr_prefilter_unknown'] == 0
    assert reader.reads == 2
    second = reports._exact_index_candidates(tmp_path, search, parsed, profiles, terms, reader)
    assert second['candidates'] == first['candidates']
    assert reader.reads == 2
    (tmp_path / '2.pages').write_bytes(b'changed')
    third = reports._exact_index_candidates(tmp_path, search, parsed, profiles, terms, reader)
    assert {c['document_id'] for c in third['candidates']} == {'1' * 64, '2' * 64}
    assert third['coverage']['ocr_prefilter_unknown'] == 1
    assert {'reason':'SEARCH_EXACT_PREFILTER_INCOMPLETE', 'count':1} in third['coverage']['gaps']
    assert reader.reads == 3


def test_prefilter_budget_retains_unchecked_candidate(tmp_path, monkeypatch):
    monkeypatch.setattr(reports, '_PREFILTER_BYTES', 1)
    candidate = {'document_id':'a' * 64, 'research_date':'20261027', 'verified_pdf_sha256':'b' * 64,
                 'verified_pdf_size':3, 'verified_pages_size':100}
    reader = FakeOwner({'documents':{}})
    search = {'checkpoint_sha256':'c' * 64, 'candidates':[candidate], 'coverage':{'gaps':[]}}
    result = reports._exact_index_candidates(tmp_path, search, {}, {}, {}, reader)
    assert result['candidates'] == [candidate]
    assert result['coverage']['ocr_prefilter_unknown'] == 1
    assert reader.reads == 0
