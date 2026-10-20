from pathlib import Path
import hashlib
import json
import pytest
from ops import run_pdf_research_package_once as package
from ops import run_pdf_research_batch as batch
from ops import run_pdf_research_remaining_once as dispatcher


def test_package_lossless_groups_label_document_and_page():
    p={'package_id':package.PACKAGE_IDS[0],'kind':'company','question':'compare forecasts and facts'}
    pages=[{'document_id':'a'*64,'page_number':1,'text':'中文123\n'*2300,'page_text_sha256':'x'},
           {'document_id':'b'*64,'page_number':1,'text':'English 4Q26E costs 100\n'*900,'page_text_sha256':'y'}]
    groups=package.source_groups(p,pages)
    assert len(groups)>2
    for original in pages:
        units=[u for g in groups for u in g if u['document_id']==original['document_id']]
        assert ''.join(u['text'] for u in units)==original['text']
        assert all(u['page_number']==1 for u in units)
    assert all(sum(len(u['text']) for u in g)<=batch.MAX_SOURCE_CHARACTERS for g in groups)
    assert all(len(batch._request_envelope(package.package_messages(p,g,synthesis=False)))<=batch.MAX_REQUEST_ENVELOPE_BYTES for g in groups)
    assert '不可信数据' in package.PACKAGE_SYSTEM


def test_package_foreign_id_has_no_model_path():
    with pytest.raises(batch.BatchError,match='ID_NOT_ADMITTED'):
        package.selected_package('foreign')


def test_package_selected_pages_preserve_exact_offsets_and_fail_tampered_hash(tmp_path,monkeypatch):
    source=tmp_path/'page-input.json';text='首付款不是潜在里程碑。'
    source.write_text(json.dumps({'document_id':'a'*64,'pdf_sha256':'a'*64,'pages':[{'page_number':1,'status':'NATIVE_TEXT','text':text,'text_sha256':hashlib.sha256(text.encode()).hexdigest()}]}))
    source2=tmp_path/'second.json';v=json.loads(source.read_text());v.update(document_id='b'*64,pdf_sha256='b'*64);source2.write_text(json.dumps(v))
    def source_ref(path,did):return {'document_id':did,'pdf_sha256':did,'source_pages':[1],'page_input':package.ref(path)}
    selected={'packages':[{'package_id':pid,'kind':kind,'question':'compare','documents':[source_ref(source,'a'*64),source_ref(source2,'b'*64)]} for pid,kind in zip(package.PACKAGE_IDS,['company','industry','event'])]}
    monkeypatch.setattr(batch,'_pilot_fixed',lambda *a:selected)
    p,pages,digest=package.selected_package(package.PACKAGE_IDS[0])
    assert len(pages)==2 and all(x['text']==text for x in pages) and len(digest)==64
    v=json.loads(source.read_text());v['pages'][0]['text']+='篡改';source.write_text(json.dumps(v));selected['packages'][0]['documents'][0]['page_input']=package.ref(source)
    with pytest.raises(batch.BatchError,match='PAGE_SHA_MISMATCH'):
        package.selected_package(package.PACKAGE_IDS[0])


def test_package_no_selected_page_review_is_fail_closed(tmp_path,monkeypatch):
    monkeypatch.setattr(dispatcher,'CONTINUATION_ROOT',tmp_path)
    with pytest.raises(batch.BatchError,match='ADMISSION_REQUIRED'):
        package.verify_package_input_review(package.PACKAGE_IDS[0],'a'*64)


def test_package_review_binds_exact_source_digest(tmp_path,monkeypatch):
    monkeypatch.setattr(dispatcher,'CONTINUATION_ROOT',tmp_path)
    monkeypatch.setattr(batch,'RESEARCH_PILOT_ROOT',tmp_path)
    folder=tmp_path/'independent-review';folder.mkdir();review_path=folder/'package-input-review.json'
    review={'status':'PACKAGE_INPUT_PASS','reviewer':'/root/pdf_model_analysis_reviewer','package_input_plan_sha256':batch.PILOT_PACKAGE_PLAN_SHA256,
            'packages':{pid:{'status':'SELECTED_PAGES_ACCEPTED','source_digest':'a'*64} for pid in reversed(package.PACKAGE_IDS)}}
    review_path.write_text(json.dumps(review,sort_keys=True));root=tmp_path/'ROOT_PDF_PILOT3_PACKAGE_ADMISSION_20261020_R1.json'
    root.write_text(json.dumps({'status':'ROOT_ADOPTED','independent_review':package.ref(review_path)}))
    package.verify_package_input_review(package.PACKAGE_IDS[0],'a'*64)
    with pytest.raises(batch.BatchError,match='REVIEW_MISMATCH'):
        package.verify_package_input_review(package.PACKAGE_IDS[0],'b'*64)
