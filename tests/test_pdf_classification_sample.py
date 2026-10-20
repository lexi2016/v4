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


@pytest.mark.parametrize('text,label',[
 ('J.P. Morgan专栏_导读\n关键词\n全文摘要\n章节速览\n思维导图',tool.PRIMARY[5]),
 ('HUAAN SECURITIES\n中国石油（601857）\n公司覆盖\n投资评级：买入',tool.PRIMARY[0]),
 ('J.P.Morgan\n摩根大通\n证券研究\n评级：增持',tool.PRIMARY[0]),
 ('CMB INTERNATIONAL\nA Wholly Owned Subsidlary\n行业研究\n目标价',tool.PRIMARY[0]),
 ('爱建证券\n证券研究报告\n相关研究：ESG白皮书',tool.PRIMARY[0]),
 ('Bloomberg\nNews Story\n记者报道Bianco Research和UBS看法',tool.PRIMARY[3]),
 ('极兔速递业务展望\n摘要\nQ&A\n问：增速？\n答：业务发展。',tool.PRIMARY[2]),
])
def test_full_generalized_structure_repairs(text,label):
    assert tool.primary_candidate(pages(text))[0]==label


def test_full_publisher_cover_not_cited_bank_or_derivative_title():
    assert tool.publisher_candidate(pages('记者指出，UBS认为需求增长。'),tool.PRIMARY[3])==(None,None)
    assert tool.publisher_candidate(pages('J.P. Morgan专栏\n全文摘要\n章节速览'),tool.PRIMARY[5])==(None,None)
    name,ref=tool.publisher_candidate(pages('CMB INTERNATIONAL\n行业研究\nUBS分析师认为需求增加。'),tool.PRIMARY[0])
    assert name=='招银国际' and ref['page_text_sha256']==tool.sha(pages('CMB INTERNATIONAL\n行业研究\nUBS分析师认为需求增加。')[0]['text'].encode())


def test_full_incremental_cache_binds_body_status_rules_and_reuses(tmp_path,monkeypatch):
    doc={'document_id':'a'*64,'pdf_sha256':'a'*64,'pdf_bytes':10,'local_pdf_path':'/safe/file.pdf','collection_directories':[]}
    refs={'receipt':{'sha256':'r'},'page_input':{'sha256':'p'}};taxonomy={'labels':[],'version':'test'};metrics={}
    first=tool.cached_metadata(doc,{'status':'READY'},pages('HUAAN SECURITIES\n公司覆盖\n中国石油（601857）'),taxonomy,refs,tmp_path,metrics)
    def forbidden(*a,**k):raise AssertionError('classification repeated')
    original=tool.candidate_metadata;monkeypatch.setattr(tool,'candidate_metadata',forbidden)
    second=tool.cached_metadata(doc,{'status':'READY'},pages('HUAAN SECURITIES\n公司覆盖\n中国石油（601857）'),taxonomy,refs,tmp_path,metrics)
    assert first==second and metrics['classified']==metrics['reused']==1
    monkeypatch.setattr(tool,'candidate_metadata',original)
    changed=tool.cached_metadata(doc,{'status':'READY'},pages('HUAAN SECURITIES\n公司覆盖\n中国石油（601857） +5%'),taxonomy,refs,tmp_path,metrics)
    assert changed['classification_cache_key']!=first['classification_cache_key']
    monkeypatch.setattr(tool,'RULES_VERSION','new-rules')
    revised=tool.cached_metadata(doc,{'status':'READY'},pages('HUAAN SECURITIES\n公司覆盖\n中国石油（601857）'),taxonomy,refs,tmp_path,metrics)
    assert revised['classification_cache_key']!=first['classification_cache_key']
    assert len(list(tmp_path.rglob('*.json')))==3


def test_full_cache_tampering_fails_closed(tmp_path):
    doc={'document_id':'a'*64,'pdf_sha256':'a'*64,'pdf_bytes':10,'local_pdf_path':'/safe/file.pdf','collection_directories':[]};refs={'receipt':None,'page_input':None};taxonomy={'labels':[],'version':'test'}
    tool.cached_metadata(doc,None,[],taxonomy,refs,tmp_path,{})
    path=next(tmp_path.rglob('*.json'));value=json.loads(path.read_text());value['metadata']['primary_type_candidate']='fabricated';tool.write_json(path,value)
    with pytest.raises(ValueError,match='CACHE_BINDING_OR_CONTENT'):tool.cached_metadata(doc,None,[],taxonomy,refs,tmp_path,{})


def test_full_terminal_gate_rejects_missing_pending_duplicate_or_status():
    ids=[f'{i:064x}' for i in range(2209)]
    value={'status':'FROZEN_COMPLETE','parent_manifest_sha256':tool.MANIFEST_SHA,'full_cohort':True,'parent_document_count':2209,'counts':{'total':2209,'ready':2209,'quarantined':0,'failed':0,'pending':0},'documents':[{'document_id':k,'status':'READY'} for k in ids]}
    assert len(tool.verify_terminal_manifest(value,ids))==2209
    for key,changed in [('counts',{**value['counts'],'pending':1}),('documents',value['documents'][:-1]),('documents',[value['documents'][0]]*2209),('status','RUNNING')]:
        bad=copy.deepcopy(value);bad[key]=changed
        with pytest.raises(ValueError,match='TERMINAL_MANIFEST'):tool.verify_terminal_manifest(bad,ids)


def test_full_no_ocr_retry_when_final_manifest_missing(tmp_path):
    root=tmp_path/'root';(root/'input').mkdir(parents=True);prepared=tmp_path/'prepared';prepared.mkdir()
    raw=b'{"documents":[]}';(root/'input/batch-manifest.json').write_bytes(raw)
    original=tool.MANIFEST_SHA
    try:
        tool.MANIFEST_SHA=tool.sha(raw)
        with pytest.raises(ValueError,match='WAITING_OCR_FINAL_MANIFEST_ABSENT'):tool.freeze_full_snapshot(root,prepared,require_final=True)
    finally:tool.MANIFEST_SHA=original


def test_full_dedup_preserves_quarantine_and_numeric_sign_variants():
    rows=[];texts={}
    for i,(text,status) in enumerate([('盈利 +5%','READY'),('盈利 +5%','READY'),('盈利 -5%','READY'),('盈利 +5%','QUARANTINED')]):
        doc={'document_id':str(i),'pdf_sha256':str(i),'pdf_bytes':10,'local_pdf_path':'/safe/同题20261013.pdf','collection_directories':[]}
        row=tool.candidate_metadata(doc,{'status':status},pages(text),{'labels':[],'version':'test'});row['source_references']={'page_input':None};rows.append(row);texts[str(i)]=pages(text)
    result=tool.full_relations(rows,texts)
    assert len(result['exact_normalized_text_groups'])==1
    assert result['exact_normalized_text_groups'][0]['document_ids']==['0','1','3']
    assert rows[1]['route_candidate']=='REUSE_CANDIDATE' and rows[3]['route_candidate']=='REVIEW'
    assert rows[2]['duplicate_group'] is None
    assert all(p['action']=='PRESERVE_BOTH_NO_MERGE' for p in result['repost_or_version_candidates'])
    assert result['merged']==result['deleted']==0


def test_full_company_literal_does_not_validate_ticker_or_infer_issuer_industry():
    result=tool.company_entities(pages('中国石油（601857）\n投资评级：买入'),tool.PRIMARY[0])
    assert result[0]['name']=='中国石油' and 'stock_code' not in result[0]
    assert tool.company_entities(pages('资料来源：某证券（123456）'),tool.PRIMARY[0])==[]


def test_full_header_dates_keep_event_export_and_download_dates_separate():
    assert tool.report_date_candidate(pages('Equity Research\n13 October 2026\nIndustry outlook'))['value']=='2026-10-13'
    assert tool.report_date_candidate(pages('Bloomberg\nNews Story\n09/29/2026\n记者报道'))['value']=='2026-09-29'
    assert tool.report_date_candidate(pages('正文讨论September 29, 2026公司发生的事件。'))['value'] is None
    doc={'document_id':'a'*64,'pdf_sha256':'a'*64,'pdf_bytes':10,'local_pdf_path':'/safe/20261018.pdf','collection_directories':['2026年10月18日']}
    row=tool.candidate_metadata(doc,{'status':'READY'},pages('某公司_导读\n2026年10月15日\n全文摘要\n章节速览'),{'labels':[],'version':'test'})
    assert row['report_date']['value'] is None and row['original_institution_candidate'] is None


def test_full_new_completion_classifies_only_changed_binding(tmp_path):
    taxonomy={'labels':[],'version':'test'};refs={'receipt':None,'page_input':None};a={'document_id':'a'*64,'pdf_sha256':'a'*64,'pdf_bytes':10,'local_pdf_path':'/safe/a.pdf','collection_directories':[]};b={**a,'document_id':'b'*64,'pdf_sha256':'b'*64};metrics={}
    tool.cached_metadata(a,{'status':'READY'},pages('已完成正文'),taxonomy,refs,tmp_path,metrics)
    tool.cached_metadata(b,None,[],taxonomy,refs,tmp_path,metrics)
    metrics={}
    tool.cached_metadata(a,{'status':'READY'},pages('已完成正文'),taxonomy,refs,tmp_path,metrics)
    tool.cached_metadata(b,{'status':'READY'},pages('新完成正文'),taxonomy,refs,tmp_path,metrics)
    assert metrics['reused_document_ids']==[a['document_id']]
    assert metrics['classified_document_ids']==[b['document_id']]


def test_full_dashboard_payload_escape_pagination_and_local_source_index(tmp_path):
    doc={'document_id':'a'*64,'pdf_sha256':'a'*64,'pdf_bytes':10,'local_pdf_path':'/safe/a#b?.pdf','collection_directories':[]}
    row=tool.candidate_metadata(doc,{'status':'READY'},pages('</script><img src=x onerror=alert(1)>'),{'labels':[],'version':'test'});row.update({'source_references':{'page_input':None,'pages':[{'page_number':1,'text_sha256':'f'*64}]},'sample_verification':'historical','classification_binding':{},'asof_utc':'frozen-before'})
    stats=tool.build_stats([row],[row['document_id']],{'same_normalized_page_sequence_groups':0,'ready_body_identity_denominator':1},{'asof_utc':'frozen-full'},{});stats.update({'sample_unknown_by_class':{},'sample_main_company_counts_nonexclusive':{},'field_coverage':tool.coverage_stats([row])})
    path=tmp_path/'report.html';tool.render_full_report(path,stats,[row],[row],[],[]);body=path.read_text()
    assert all('id="'+key+'"' in body for key in ('full-q','full-type','full-route','full-status','full-language','full-fold','full-prev','full-next','full-list'))
    assert 'const fullPageSize=25' in body and 'function fullSelect' in body
    assert '</script><img src=x' not in body and '\\u003c/script>' in body
    assert 'replace(/#/g' in body and 'replace(/\\?/g' in body


@pytest.mark.parametrize('text,publisher',[
 ('平安证券\nPING AN SECURITIES\n海外策略周报\n证券分析师\n投资咨询编号\n平安观点：9月FOMC会议纪要偏鹰。','平安证券'),
 ('财信证券\nCHASING SECURITIES\n策略点评\n证券研究报告\n从市场情绪看，据港交所及财联社，沽空比例下降。','财信证券'),
])
def test_repair_f1_cover_publication_outranks_prose_citations(text,publisher):
    assert tool.primary_candidate(pages(text))[0]==tool.PRIMARY[0]
    assert tool.publisher_candidate(pages(text),tool.PRIMARY[0])[0]==publisher
    assert tool.publisher_candidate(pages('据港交所及财联社，市场情绪回暖。'),tool.PRIMARY[3])==(None,None)


@pytest.mark.parametrize('text',[
 '【风口研报】财联社\n中信证券分析师认为景气改善。\n证券研究报告被引用。',
 '财联社10月13日电\n据某证券研究报告，市场活跃。',
])
def test_repair_f1_genuine_news_material_stays_news(text):
    assert tool.primary_candidate(pages(text))[0]==tool.PRIMARY[3]


@pytest.mark.parametrize('later_page',[
 '问答整理\n（本次电话会议为策略观点播报，未设问答环节）\n原文\n发言人 00:00 欢迎参加会议。',
 '问答整理\nQ1：经营情况如何？\n答：业务增长。',
])
def test_repair_f2_record_form_on_later_prepared_page(later_page):
    source=[{'page_number':i+1,'text':text} for i,text in enumerate(['公司业务概览\n'+'要点总结。'*1600,'摘要续页。',later_page])]
    candidate=tool.primary_candidate(source)
    assert candidate[0]==tool.PRIMARY[2]
    assert tool.evidence(source,candidate[2])['page_number']==3
    broker=[{'page_number':1,'text':'财信证券\n策略点评\n证券研究报告'},source[-1]]
    assert tool.primary_candidate(broker)[0]==tool.PRIMARY[0]
    assert tool.primary_candidate(pages('正文引用了某次会议纪要与问答整理，但无记录结构。'))[0]==tool.PRIMARY[6]


def test_repair_f3_masthead_and_explicit_date_precede_market_asof_date():
    source=[{'page_number':1,'text':'证券研究报告\n市场数据：\n收盘价（元）\n数据来源：Wind\n2026年8月19日\n基础数据：\n2026年03月31日\n相关研究\nAIJIAN SECURITIES\n2026年08月20日\n长鑫科技公司深度报告'}, {'page_number':2,'text':'长鑫科技\n2026年08月20日\n投资案件'}]
    got=tool.report_date_candidate(source)
    assert got['value']=='2026-08-20' and got['status']=='COVER_MASTHEAD_DATE_CANDIDATE'
    assert '2026年08月20日' in got['evidence']['excerpt']
    assert tool.report_date_candidate(pages('市场数据：\n收盘价\n数据来源：Wind\n2026年8月19日'))['value'] is None
    assert tool.report_date_candidate(pages('2026年8月19日\n报告日期：2026-08-20'))['value']=='2026-08-20'
    assert tool.report_date_candidate(pages('报告日期：2026-08-20\n发布日期：2026-08-21'))['value'] is None


def test_repair_f4_html_available_text_denominator_is_not_ready(tmp_path):
    doc={'document_id':'a'*64,'pdf_sha256':'a'*64,'pdf_bytes':10,'local_pdf_path':'/safe/a.pdf','collection_directories':[]};row=tool.candidate_metadata(doc,{'status':'READY'},pages('材料正文'),{'labels':[],'version':'test'});row.update({'source_references':{'page_input':None},'sample_verification':'test'})
    stats=tool.build_stats([row],[row['document_id']],{'same_normalized_page_sequence_groups':9,'ready_body_identity_denominator':1709,'available_text_identity_denominator':1751},{'asof_utc':'fixed'},{});stats.update({'sample_unknown_by_class':{},'sample_main_company_counts_nonexclusive':{}})
    target=tmp_path/'report.html';tool.render_report(target,stats,[row],[]);body=target.read_text()
    assert '9 / 1751 份可用准备正文（含隔离，质量状态单列）' in body
    assert '1751 份READY正文' not in body


def test_repair_f1_localized_research_masthead_still_precedes_consulting_reference():
    text='J.P.Morgan\n摩根大通\n中国 证券研究\n2026年9月23日\n行业观点提及白皮书。'
    assert tool.primary_candidate(pages(text))[0]==tool.PRIMARY[0]


@pytest.mark.parametrize('column', ['盘中宝','电报解读','财联社早知道','研选•研报数据','九点特供','机构调研','点金互动易'])
def test_third_owned_news_column_over_quoted_broker_and_consultant(column):
    text='关于我们\nC财联社\n首页 电报 投研\n【'+column+'】产业事件\n电报内容\n财联社资讯获悉，国信证券研究报告认为需求增长，中国信通院白皮书引用德勤数据。'
    assert tool.primary_candidate(pages(text))[0]==tool.PRIMARY[3]


def test_third_prose_wire_citation_and_broker_record_heading_do_not_fake_publication():
    assert tool.primary_candidate(pages('财信证券\n策略点评\n证券研究报告\n据港交所及财联社，市场情绪回暖。'))[0]==tool.PRIMARY[0]
    assert tool.primary_candidate(pages('某证券\n公司交流纪要\n证券分析师\n问：经营情况？\n答：变化。'))[0]==tool.PRIMARY[2]
    assert tool.owned_news_marker(pages('正文引用了盘中宝报道和财联社的数据。')) is None


@pytest.mark.parametrize('text,label',[
 ('• 证券研究报告•\n证券分析师：张某 A0230525040004\n行业研究',tool.PRIMARY[0]),
 ('MISSING BRAND SECURITIES\n行业周报\nAnalyst\nRating: Buy',tool.PRIMARY[0]),
 ('KPMG\n毕马威\n中国IPO市场\n2026年第三季回顾',tool.PRIMARY[4]),
 ('行业研究摘要\nQ1：需求如何？\n回答：增长。\nQ2：供给如何？\n回答：稳定。',tool.PRIMARY[2]),
 ('调研总结\n核心观点\n·需求\n·供给',tool.PRIMARY[2]),
 ('原视频：Liquid-Cooled Power Shelf\n演讲嘉宾：某工程师\n内容整理',tool.PRIMARY[2]),
 ('行业近况\n估值与建议\n风险\n盈利预测',tool.PRIMARY[0]),
 ('股票市场复盘\n市场走势和事件点评。',tool.PRIMARY[3]),
 ('xuanguTong.com.cn\n本文来自持牌证券机构，不代表平台观点\n两家公司评级日报与摘要',tool.PRIMARY[3]),
])
def test_third_missing_form_patterns_use_existing_body(text,label):
    assert tool.primary_candidate(pages(text))[0]==label


def test_third_state_dispositions_separate_unavailable_failed_and_actual_form_unknown():
    base={'ocr_status_asof':'READY','primary_type_candidate':tool.PRIMARY[6],'text_characters':1000,'classification_reason':'body inspected'}
    assert tool.disposition({**base,'ocr_status_asof':'PENDING'})[:2]==('WAITING_OCR','待OCR')
    assert tool.disposition({**base,'ocr_status_asof':'FAILED'})[:2]==('EXTRACTION_FAILED','提取失败')
    assert tool.disposition({**base,'text_characters':11})[:2]==('READY_QUALITY_REVIEW','正文质量待核')
    assert tool.disposition(base)[:2]==('READY_FORM_REVIEW','待核分类')
    assert tool.disposition({**base,'primary_type_candidate':tool.PRIMARY[3],'quality_flags':['body unreadable']})[:2]==('READY_QUALITY_REVIEW',tool.PRIMARY[3])


def test_third_manual_form_data_requires_exact_source_and_literal_evidence(tmp_path):
    doc={'document_id':'a'*64,'pdf_sha256':'a'*64,'pdf_bytes':10,'local_pdf_path':'/safe/a.pdf','collection_directories':[]};ps=pages('独立研究文章\n作者\n实际正文。');row=tool.candidate_metadata(doc,{'status':'READY'},ps,{'labels':[],'version':'test'});row['frozen_page_input_sha256']='b'*64
    item={'document_id':doc['document_id'],'pdf_sha256':doc['pdf_sha256'],'page_input_sha256':'b'*64,'exact_body_sha256':row['exact_body_sha256'],'primary_type':tool.PRIMARY[0],'reason':'字面研究形式','evidence':[tool.evidence(ps)]};path=tmp_path/'review.json';tool.write_json(path,{'manifest_sha256':tool.MANIFEST_SHA,'documents':[item]})
    tool.apply_full_form_reviews([row],{doc['document_id']:ps},path)
    assert row['primary_type_candidate']==tool.PRIMARY[0] and row['verified_stock_codes']==[]
    assert row['original_institution_candidate'] is None
    bad=copy.deepcopy(item);bad['page_input_sha256']='c'*64;tool.write_json(path,{'manifest_sha256':tool.MANIFEST_SHA,'documents':[bad]})
    with pytest.raises(ValueError,match='SOURCE_BINDING'):tool.apply_full_form_reviews([row],{doc['document_id']:ps},path)
    bad=copy.deepcopy(item);bad['evidence'][0]['excerpt']='伪造正文';tool.write_json(path,{'manifest_sha256':tool.MANIFEST_SHA,'documents':[bad]})
    with pytest.raises(ValueError,match='EVIDENCE_MISMATCH'):tool.apply_full_form_reviews([row],{doc['document_id']:ps},path)


def test_third_ipo_intermediary_not_research_publisher_and_earnings_brief_unknown_issuer():
    assert tool.primary_candidate(pages('科创板投资风险提示\n某公司\n首次公开发行股票\n招股说明书（申报稿）\n中信证券是保荐人'))[0]==tool.PRIMARY[1]
    assert tool.primary_candidate(pages('某公司（123456）业绩点评\n盈利预测与估值\n风险：行业变化'))[0]==tool.PRIMARY[0]
    assert tool.primary_candidate(pages('某公司（123456）发布新闻，业绩符合预期。'))[0]==tool.PRIMARY[6]


def test_third_explicit_snapshot_cannot_mix_final_or_escape_evidence(tmp_path):
    root=tmp_path/'V4_PDF_CLASSIFICATION_FULL_20261020_R1';root.mkdir();prepared=tmp_path/'prepared';prepared.mkdir()
    base=['--full','--evidence-root',str(root),'--prepared-root',str(prepared),'--sample-root',str(tmp_path/'sample')]
    with pytest.raises(ValueError,match='EXPLICIT_SNAPSHOT_SCOPE'):
        tool.full_main(base+['--snapshot-root',str(tmp_path/'outside')])
    with pytest.raises(ValueError,match='EXPLICIT_SNAPSHOT_SCOPE'):
        tool.full_main(base+['--snapshot-root',str(root/'snapshot'),'--require-final'])


def test_third_research_cover_cannot_be_masked_by_wrapped_fed_citation():
    text='国泰海通证券\nGUOTAI HAITONG SECURITIES\n资产概览\n本报告导读：\n投资要点：\n美债配置需求回暖，\n但偏鹰的 FED 会议纪要和欧元疲软仍支撑美元上涨。'
    assert tool.primary_candidate(pages(text))[0]==tool.PRIMARY[0]
