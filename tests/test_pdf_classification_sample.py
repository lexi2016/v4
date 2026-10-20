from pathlib import Path
import copy
import hashlib
import json
import socket
import subprocess
import pytest
from ops import build_pdf_classification_sample as tool


def pages(text):
    return [{'page_number':1,'text':text,'text_sha256':tool.sha(text.encode())}]


def test_exact_normalization_preserves_signs_numbers_dates_and_units():
    assert tool.normalize_exact('收入 +5.0%\n2026-10-13 亿元') == '收入 +5.0% 2026-10-13 亿元'
    variants=['盈利+5%','盈利-5%','盈利−5%','盈利5%','盈利50%','盈利5亿元','盈利5万元','2026-10-13','2026-10-14']
    assert len({tool.body_sha(pages(t)) for t in variants}) == len(variants)
    assert tool.body_sha(pages('2026-10-13\n+5.0%')) == tool.body_sha(pages('2026-10-13 +5.0%'))
    assert tool.body_sha(pages('1 2')) != tool.body_sha(pages('12'))
    assert tool.body_sha([{'text':'12'},{'text':'34'}]) != tool.body_sha([{'text':'1234'}])


@pytest.mark.parametrize('text,label',[
 ('【风口研报】财联社 2026.10.13 中信证券分析师认为行业景气；证券研究报告。',tool.PRIMARY[3]),
 ('浙商证券\n证券研究报告\n银行业前瞻\n美联储会议纪要偏鹰。',tool.PRIMARY[0]),
 ('申万宏源\nSWS RESEARCH\n汽车评价体系\n相关研究：《ESG白皮书》。',tool.PRIMARY[0]),
 ('南亚科技 Nanya Technology\n2026年第3季財務報告摘要\n2026年10月12日',tool.PRIMARY[1]),
 ('Deloitte.\n德勤\n中国银行业发展回顾与展望',tool.PRIMARY[4]),
 ('行业访谈\n发言人 04:09\n关于需求与供给。',tool.PRIMARY[2]),
 ('投资教程\n课程讲义\n投资方法和交易纪律。',tool.PRIMARY[5]),
 ('无明确作者和材料结构的正文',tool.PRIMARY[6]),
])
def test_content_type_uses_body_structure(text,label):
    assert tool.primary_candidate(pages(text))[0]==label


def test_filename_never_establishes_broker_or_publication_date():
    doc={'document_id':'a'*64,'pdf_sha256':'a'*64,'pdf_bytes':10,'local_pdf_path':'/tmp/高盛-证券研究报告-20261013.pdf','collection_directories':['2026年10月15日']}
    row=tool.candidate_metadata(doc,{'status':'READY','revision':None},pages('材料正文没有出版者，也没有发布日期。'),{'labels':[],'version':'existing'})
    assert row['primary_type_candidate']==tool.PRIMARY[6]
    assert row['report_date']['value'] is None
    assert row['collection_dates']==['2026-10-15']
    assert row['original_institution_candidate'] is None
    assert row['verified_stock_codes']==[]
    assert row['route_candidate']=='REVIEW'


def test_date_does_not_take_incidental_event_date():
    assert tool.report_date_candidate(pages('银行业研究\n公司2026年10月8日签署协议。'))['value'] is None
    assert tool.report_date_candidate(pages('2026年10月13日\n研究报告'))['value']=='2026-10-13'


def test_csv_rendering_protects_formula_without_changing_identity():
    assert tool.csv_value('-5%')=="'-5%"
    assert tool.normalize_exact('-5%')=='-5%'
    assert tool.csv_value('=HYPERLINK("x")').startswith("'=")


def test_bound_reference_and_hash_drift_fail_closed(tmp_path):
    p=tmp_path/'source.json';p.write_text('{"ready":true}')
    with pytest.raises(ValueError,match='SHA_MISMATCH'):tool.read_json(p,'0'*64)
    with pytest.raises(ValueError,match='UNSAFE_DERIVED_REFERENCE'):tool.bound_path(tmp_path,'../escape.json')
    link=tmp_path/'symlink';link.symlink_to(p)
    with pytest.raises(ValueError,match='INPUT_NOT_REGULAR'):tool.read_json(link)


def test_stratified_sample_repeatable_and_class_shortfalls_visible():
    rows=[]
    for i in range(100):
        rows.append({'document_id':f'{i:064x}','primary_type_candidate':tool.PRIMARY[i%5],'source_references':{'page_input':{'path':'frozen'}},'language_candidate':['ZH','EN','ZH_EN_MIXED'][i%3],'page_count':i+1,'institution_status':'UNKNOWN','ocr_status_asof':'READY','report_date':{'value':None},'collection_dates':['2026-10-13']})
    ids,supply=tool.select_sample(rows)
    assert ids==tool.select_sample(list(reversed(rows)))[0]
    assert len(ids)==len(set(ids))==60
    assert supply[tool.PRIMARY[5]]==0
    assert all(sum(row['document_id'] in ids for row in rows if row['primary_type_candidate']==label)>=5 for label in tool.PRIMARY[:5])


def test_no_network_or_execution_capability_in_source():
    # This one-purpose derivative tool must not acquire OCR/model/network clients.
    import ast
    tree=ast.parse(Path(tool.__file__).read_text())
    imported=[]
    for n in ast.walk(tree):
        if isinstance(n,ast.Import): imported.extend(a.name for a in n.names)
        elif isinstance(n,ast.ImportFrom):imported.append(n.module or '')
    assert not set(imported)&{'requests','httpx','urllib.request','socket','subprocess','infrastructure.pdf_research','infrastructure.local_document_model'}


def test_institution_abbreviation_cannot_match_subsidlary():
    assert not __import__('re').search(tool.institution_pattern('UBS'), 'A Wholly Owned Subsidlary', __import__('re').I)
    assert __import__('re').search(tool.institution_pattern('UBS'), 'UBS RESEARCH', __import__('re').I)


def test_review_excerpt_must_actually_exist_in_page(tmp_path):
    document_id='a'*64
    text='真实正文：行业研究与数据。'
    row={'source_references':{'pages':[{'page_number':1,'text_sha256':tool.sha(text.encode())}]}}
    item={'primary_type':tool.PRIMARY[0],'route':'SAVE','evidence':[{'page_number':1,'page_text_sha256':tool.sha(text.encode()),'excerpt':'伪造的原文'}]}
    path=tmp_path/'review.json';tool.write_json(path,{'manifest_sha256':tool.MANIFEST_SHA,'sample_document_ids':[document_id],'documents':{document_id:item}})
    with pytest.raises(ValueError,match='EXCERPT_NOT_IN_SOURCE'):
        tool.apply_sample_reviews({document_id:row},[document_id],path,{document_id:pages(text)})


def test_deep_route_requires_explicit_research_question(tmp_path):
    document_id='a'*64
    item={'primary_type':tool.PRIMARY[0],'route':'DEEP_RESEARCH_CANDIDATE','evidence':[]}
    path=tmp_path/'review.json';tool.write_json(path,{'manifest_sha256':tool.MANIFEST_SHA,'sample_document_ids':[document_id],'documents':{document_id:item}})
    with pytest.raises(ValueError,match='NO_RESEARCH_QUESTION'):
        tool.apply_sample_reviews({document_id:{}},[document_id],path)


def test_relation_score_cannot_promote_different_text_to_confirmed_same(tmp_path):
    pair={'pair_id':1,'left_document_id':'a','right_document_id':'b','confirmed_same_normalized_page_sequence':False}
    path=tmp_path/'pairs.json';tool.write_json(path,{'manifest_sha256':tool.MANIFEST_SHA,'pairs':[{'pair_id':1,'left_document_id':'a','right_document_id':'b','reviewed_relation':'SAME_NORMALIZED_TEXT'}]})
    with pytest.raises(ValueError,match='FALSE_EXACT_DUPLICATE'):
        tool.apply_relation_reviews([pair],path)


def test_dashboard_escapes_source_and_contains_native_filters(tmp_path):
    doc={'document_id':'a'*64,'pdf_sha256':'a'*64,'pdf_bytes':10,'local_pdf_path':'/safe/report.pdf','collection_directories':[]}
    row=tool.candidate_metadata(doc,{'status':'READY','revision':None},pages('<script>alert(1)</script> 未核资料'),{'labels':[],'version':'existing'})
    row['source_references']={'page_input':{'path':'/safe/page.json','sha256':'b'*64}}
    row['sample_verification']='WRITER_REVIEWED_PENDING_INDEPENDENT_REVIEW'
    stats=tool.build_stats([row],['a'*64],{'same_normalized_page_sequence_groups':0,'ready_body_identity_denominator':1},{'asof_utc':'2026-10-20T04:09:53Z'},{})
    stats.update({'sample_unknown_by_class':{tool.PRIMARY[6]:{'sample_count':1,'source_or_content_uncertain':1}},'sample_main_company_counts_nonexclusive':{}})
    path=tmp_path/'report.html';tool.render_report(path,stats,[row],[])
    body=path.read_text()
    assert '<script>alert(1)</script>' not in body
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in body
    assert all(f'id="{key}"' in body for key in ('q','kind','route','ocr'))
    assert 'src="http' not in body
    assert '独立分类准确率：尚未评分' in body
