"""Deterministic, offline catalyst evidence projection. Raw material stays local.

An index hit, a same-day title, or a routine announcement is never a cause.
Only manually frozen named-riser groups from ctime-bound publisher bodies can
become PUBLIC_REPORTED_ATTRIBUTION, and that label never asserts price cause.
"""
import csv
import hashlib
import html
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path('/Users/lexi/Desktop/学习/因子工厂')
OUT = ROOT/'research/week_miss387_diagnosis_20261023/catalyst'
RAW = OUT/'raw'

def load(path): return json.loads(Path(path).read_text())
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def persisted_at(path): return datetime.fromtimestamp(Path(path).stat().st_mtime,timezone.utc).isoformat()
def save(name, value):
    (OUT/name).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')
def norm(name): return re.sub(r'\s+', '', name).replace('Ａ','A')
def csvout(name, rows):
    with (OUT/name).open('w', encoding='utf-8-sig', newline='') as f:
        w=csv.DictWriter(f, fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)

# Frozen attribution scope: each name is explicitly in a rising-stock clause,
# not inferred from present-day theme membership or nearby unrelated text.
GROUPS = {
 'CLS_2506563': {
  '军工':'航发科技 长城军工 金奥博 晨曦航空 广东宏大 航天晨光',
  '低空经济':'万丰奥威 中信海直 保隆科技',
  '福建区域上涨观察':'厦门信达 福建水泥',
  '房地产':'深物业A 新城控股'},
 'CLS_2508091': {
  '低空经济':'保隆科技 京城股份 万丰奥威 文灿股份 金盾股份 中信海直 富临精工 上工申贝',
  'PCB':'肯特股份 协和电子 沃特股份 四会富仕 澳弘电子',
  '数据要素':'太极股份 久远银海',
  '电力':'江苏新能 浙江新能 晶科科技',
  '军工':'甘化科工 北方导航 长城军工 国科军工 新兴装备',
  '连板观察':'东方嘉盛 吉大正元 海洋王 长春一东 东安动力'},
 'CLS_2510719': {
  '鱼粉':'百洋股份','军工':'海洋王','低空经济':'东安动力','机器人':'大业股份'},
 'CLS_2511964': {
  '人形机器人':'大业股份 兆威机电 大洋电机 襄阳轴承 鸣志电器 赛象科技 奕帆传动 华阳智能 赛福天 福莱新材 三协电机 浙江荣泰 方正电机',
  '工程机械':'山河智能 南方路机 铁拓机械 恒立钻具 万通液压 万达轴承 长龄液压',
  '军工':'湖南天雁 江龙船艇 长城军工 内蒙一机 北方长龙 航天信息',
  '连板观察':'海洋王 星光股份 三峡新材 华瓷股份 哈空调 上海九百 出版传媒 海量数据'},
 'CLS_2509405': {
  '人形机器人':'大业股份 福莱新材 宁波东力 浙江荣泰 凡拓数创 长盈精密 模塑科技 宇树科技 华依科技 汉威科技 安培龙',
  '端侧AI':'恒玄科技 美格智能 移远通信 日海智能 博通集成 龙旗科技 泰晶科技 瑞芯微 乐鑫科技 泰凌微 全志科技',
  'PCB':'骏亚科技 协和电子 博敏电子 则成电子 世运电路 广合科技',
  'AI漫剧':'粤传媒 城市传媒',
  '创新药':'昭衍新药 海正药业 八亿时空 欧林生物 三力制药 昂利康',
  '连板观察':'吉大正元 海洋王 东安动力 京城股份 慕思股份 科森科技'},
 'CLS_2510745': {
  '数据要素':'南威软件 星光股份 海量数据 天威视讯 三维天地 出版传媒 久远银海 太极股份 铜牛信息 零点有数 国新健康 国源科技 新致软件',
  'AI漫剧':'粤传媒 文投控股 天威视讯 慈星股份 广电网络 百纳千成 天地在线',
  '养殖':'东瑞股份 天康生物 巨星农牧 国联水产 晓鸣股份',
  '福建区域上涨观察':'安记食品 平潭发展 福建水泥',
  '算力硬件':'致尚科技 光库科技 亚康股份 顺络电子 剑桥科技 长芯博创',
  '连板观察':'海洋王 东安动力 大业股份 润建股份 永达股份 日海智能 泰尔股份 百洋股份 同为股份 昂利康 三峡新材'}
}

ANNOUNCEMENTS = [
 ('000573.SZ','https://static.cninfo.com.cn/finalpage/2026-10-16/1225607597.PDF','2026-10-16','董事会通过股权收购意向议案','CORPORATE_EVENT_CONTENT_CONFIRMED_TIMING_UNKNOWN','OFFICIAL_PDF_VERIFY_01.json'),
 ('300492.SZ','https://static.cninfo.com.cn/finalpage/2026-10-16/1225606083.PDF','2026-10-16','拟更名并调整经营范围，代码保持300492','CORPORATE_EVENT_CONTENT_CONFIRMED_TIMING_UNKNOWN','VERIFIED_OPEN_02.json'),
 ('688279.SH','https://static.cninfo.com.cn/finalpage/2026-10-17/1225609844.PDF','2026-10-17','前三季度业绩预增','CORPORATE_EVENT_CONTENT_CONFIRMED_TIMING_UNKNOWN','OFFICIAL_PDF_VERIFY_01.json'),
 ('001288.SZ','https://static.cninfo.com.cn/finalpage/2026-10-13/1225601246.PDF','2026-10-13','获回购专项贷款承诺函','CORPORATE_EVENT_CONTENT_CONFIRMED_TIMING_UNKNOWN','OFFICIAL_PDF_VERIFY_01.json'),
 ('600032.SH','https://static.cninfo.com.cn/finalpage/2026-10-15/1225604288.PDF','2026-10-15','季度发电量披露，不能据此直接认定利好','OPERATING_DISCLOSURE_NOT_AUTOMATIC_CATALYST','OFFICIAL_PDF_VERIFY_01.json'),
 ('300458.SZ','https://static.cninfo.com.cn/finalpage/2026-10-12/1225601760.PDF','2026-10-12','前三季度业绩预增','CORPORATE_EVENT_CONTENT_CONFIRMED_TIMING_UNKNOWN','OFFICIAL_PDF_VERIFY_01.json'),
 ('300620.SZ','https://static.cninfo.com.cn/finalpage/2026-10-15/1225606072.PDF','2026-10-15','前三季度业绩预增','CORPORATE_EVENT_CONTENT_CONFIRMED_TIMING_UNKNOWN','OFFICIAL_PDF_VERIFY_01.json'),
 ('603350.SH','https://static.cninfo.com.cn/finalpage/2026-10-16/1225606862.PDF','2026-10-16','闲置募集资金现金管理赎回，例行事项','ROUTINE_NOT_POSITIVE_CATALYST','OFFICIAL_PDF_VERIFY_02.json'),
 ('600178.SH','https://static.cninfo.com.cn/finalpage/2026-10-21/1225612222.PDF','2026-10-21','交易风险及基本面未显著变化提示','RISK_DISCLOSURE_NOT_POSITIVE_CATALYST','OFFICIAL_PDF_VERIFY_02.json'),
 ('301313.SZ','https://static.cninfo.com.cn/finalpage/2026-10-20/1225612937.PDF','2026-10-20','股价异动及交易风险提示','RISK_DISCLOSURE_NOT_POSITIVE_CATALYST','OFFICIAL_PDF_VERIFY_02.json')
]

def blocks(raw):
    return raw.split('--------------------------------------------------------------------------------')

def source_docs():
    """Parse each already captured publisher response; never contact a source."""
    result={}
    direct=load(OUT/'DIRECT_VERIFICATION.json')+load(OUT/'DIRECT_VERIFICATION_ADDITIONAL.json')
    wanted={'DIRECT_VERIFY_00.html','DIRECT_VERIFY_01.html','DIRECT_VERIFY_02.html',
            'DIRECT_VERIFY_05.html','DIRECT_VERIFY_07.html','DIRECT_VERIFY_08.html'}
    for record in direct:
        path=Path(record.get('raw_response_path',''))
        if path.name not in wanted:continue
        assert record['query_status']=='FETCHED' and sha(path)==record['sha256']
        text=path.read_text()
        script=re.search(r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>',text,re.S)
        if script:
            obj=json.loads(script.group(1));article=obj['props']['pageProps']['articleDetail']
        else:
            marker=re.search(r'__NEXT_DATA__\s*=\s*',text)
            assert marker
            obj,_=json.JSONDecoder().raw_decode(text[marker.end():]);article=obj['props']['initialState']['deep_details']
        eid='CLS_'+str(article.get('id',article.get('article_id')))
        result[eid]={'evidence_id':eid,'source':'财联社','title':article['title'],
            'url':record['url'],'ctime_epoch_seconds':article['ctime'],
            'publication_timestamp':datetime.fromtimestamp(article['ctime'],ZoneInfo('Asia/Shanghai')).isoformat(),
            'publication_timezone':'Asia/Shanghai',
            'publication_time_basis':'SOURCE_EMBEDDED_CTIME_UNIX_EPOCH_AND_PUBLISHER_DISPLAY_PARITY',
            'body_text':html.unescape(re.sub('<[^>]+>',' ',article.get('content') or '')),
            'raw_response_path':str(path),
            'positive_scope':'PUBLIC_REPORTED_SECTOR_ASSOCIATION_ONLY_NOT_PROVEN_PRICE_CAUSE'}
    assert set(result)==set(GROUPS)
    return result

def profile_clue(web, day, code, name):
    iso=f'{day[:4]}-{day[4:6]}-{day[6:]}'
    for b in blocks(web['response']):
        if code.split('.')[0] not in b:continue
        u=re.search(r'^.+? \((https?[^\n]+)\)\n',b.strip())
        if not u:continue
        for line in b.splitlines():
            if line.startswith(iso) and '|' in line and ('涨停' in line):
                parts=[t.strip() for t in line.split('|')]
                if len(parts)>=4:
                    reason=parts[3].split('1、')[0].split('1.')[0][:48]
                    return {'url':u.group(1),'event_date':iso,'clue':reason,'status':'RETROSPECTIVE_PROFILE_LABEL_FIRST_PUBLICATION_TIME_UNVERIFIED'}
    return None

def main():
    assert (OUT/'CATALYST_START_REGISTRY_RECEIPT.json').is_file()
    plans=load(OUT/'QUERY_PLAN.json'); docs=source_docs()
    verification=load(OUT/'DIRECT_VERIFICATION.json')+load(OUT/'DIRECT_VERIFICATION_ADDITIONAL.json')
    direct_by_url={x['url']:x for x in verification}
    evidence=[]
    for eid,groups in GROUPS.items():
        d=docs[eid]; rawpath=Path(d['raw_response_path'])
        assert rawpath.is_file()
        assert '"ctime":'+str(d['ctime_epoch_seconds']) in rawpath.read_text()
        for theme,names in groups.items():
            for name in names.split():assert norm(name) in norm(d['body_text']), (eid,name)
        r=direct_by_url[d['url']]
        assert r['query_status']=='FETCHED' and r['sha256']==sha(rawpath)
        evidence.append({k:d[k] for k in ['evidence_id','source','title','url','ctime_epoch_seconds','publication_timestamp','publication_timezone','publication_time_basis','raw_response_path','positive_scope']} | {'retrieved_at':r['retrieved_at'],'raw_response_sha256':sha(rawpath),'verification_status':'ORIGINAL_PUBLISHER_BODY_AND_EPOCH_VERIFIED','price_causality':'NOT_ESTABLISHED','historical_name_scope':'ARTICLE_NAMES_MATCH_FROZEN_INPUT_NAMES_ONLY_NOT_FULL_ALIAS_PASSPORT'})
    ann_evidence=[]
    for i,(code,url,date,text,relevance,rawfile) in enumerate(ANNOUNCEMENTS):
        rawpath=RAW/rawfile;v=load(rawpath)
        matched=[b for b in blocks(v['response']) if url in b and code.split('.')[0] in b and 'Failed to fetch' not in b]
        assert matched, (code,url)
        ann_evidence.append({'evidence_id':f'ANN_{i:02d}','code':code,'source':'巨潮资讯原始公司公告PDF','url':url,'document_date':date,'publication_timestamp':None,'publication_timezone':None,'publication_time_precision':'DOCUMENT_DATE_ONLY_NOT_FIRST_PUBLICATION','publication_time_null_reason':'PDF_DOCUMENT_OR_URL_DATE_DOES_NOT_PROVE_FIRST_AVAILABLE_AT','short_paraphrase_zh':text,'relevance':relevance,'verification_status':'ORIGINAL_PDF_CODE_AND_CONTENT_VERIFIED_FIRST_PUBLICATION_UNKNOWN','retrieved_at':v['retrieved_at'],'raw_response_path':str(rawpath),'raw_response_sha256':sha(rawpath),'price_causality':'NOT_ESTABLISHED'})
    evidence.extend(ann_evidence); evby={x['evidence_id']:x for x in evidence}
    cache=load(OUT/'CACHE_MENTION_CANDIDATES.json'); cacheby=defaultdict(list)
    for c in cache:cacheby[(c['selection_date'],c['code'])].append(c)
    allrows=[]; queryledger=[]
    for p in plans:
        webpath=RAW/(p['query_id']+'.json'); officialpath=RAW/('OFFICIAL_'+p['code'].replace('.','_')+'.json')
        web=load(webpath);official=load(officialpath)
        assert web['code']==official['code']==p['code'] and web['selection_date']==p['selection_date']
        main=[];known=[];retro=[];priceonly=[];themes={};name=norm(p['name'])
        for eid,g in GROUPS.items():
            these=[theme for theme,names in g.items() if name and name in {norm(n) for n in names.split()}]
            if not these:continue
            d=docs[eid];t=datetime.fromisoformat(d['publication_timestamp'])
            lo=datetime.fromisoformat(p['known_before_signal_start']);sig=datetime.fromisoformat(p['main_window_start']);end=datetime.fromisoformat(p['main_window_end'])
            if these==['连板观察']:
                if lo<=t<=end:priceonly.append(eid)
                continue
            if sig<t<=end:main.append(eid)
            elif lo<=t<=sig:known.append(eid)
            elif t>end:retro.append(eid)
            else:continue
            themes[eid]=these
        all_ann=[e for e in ann_evidence if e['code']==p['code']]
        lowdate=p['known_before_signal_start'][:10]
        seldate=p['main_window_end'][:10]
        ann=[e for e in all_ann if lowdate<=e['document_date']<=seldate]
        retroann=[e for e in all_ann if e['document_date']>seldate]
        olderann=[e for e in all_ann if e['document_date']<lowdate]
        clue=profile_clue(web,p['selection_date'],p['code'],p['name'])
        cm=cacheby[(p['selection_date'],p['code'])]
        if main:
            label='PUBLIC_REPORTED_ATTRIBUTION';phrase='盘中报道关联：'+'、'.join(sorted({t for eid in main for t in themes[eid]}))+'。'
        elif known:
            label='PUBLIC_REPORTED_ATTRIBUTION';phrase='信号前已有报道：'+'、'.join(sorted({t for eid in known for t in themes[eid]}))+'；本次上涨新增事件仍未证实。'
        elif clue:
            label='TIMING_UNKNOWN';phrase='回溯题材线索：'+clue['clue']+'；首发时点未核实。'
        elif ann:
            label='TIMING_UNKNOWN';phrase='原文事项：'+ann[0]['short_paraphrase_zh']+'；首次公开时间未闭环。'
        elif cm:
            label='TIMING_UNKNOWN';phrase='早报正文存在该股名称或代码线索；发布时间缺时区，未据此认定催化。'
        elif priceonly:
            label='SOURCE_NOT_COVERED';phrase='盘中报道仅记录连板或价格表现，未提供可证实事件归因；其他来源未穷尽。'
        else:
            label='SOURCE_NOT_COVERED';phrase='两类公开索引已查，未取得可核实主窗口催化；来源未穷尽，不能判定没有公告或题材。'
        if ann and main:phrase+='另有公司公告事项，须按证据表区分例行、风险和候选利好。'
        strict_positive=bool(main or known)
        ids=main+known+[e['evidence_id'] for e in ann]
        r={'selection_date':p['selection_date'],'signal_asof':p['signal_asof'],'code':p['code'],'input_name':p['name'],'historical_name_status':'CANNOT_CONFIRM_FULL_HISTORICAL_ALIAS_EXACT_FROZEN_NAME_MATCH_ONLY','benchmark_scope':'EXISTING5533_RESEARCH_POOL_NOT_CERTIFIED_HISTORICAL_ALL_A','query_status':web['query_status'],'official_query_status':official['query_status'],'query_ids':[p['query_id'],official['query_id']],'query_retrieved_at':[web['retrieved_at'],official['retrieved_at']],'query_candidate_source_urls':sorted({x['url'] for x in web.get('sources',[])+official.get('sources',[])}),'main_window_start':p['main_window_start'],'main_window_end':p['main_window_end'],'known_before_signal_start':p['known_before_signal_start'],'catalyst_label':label,'verified_report_context_present':strict_positive,'main_window_report_evidence_ids':main,'known_before_signal_evidence_ids':known,'retrospective_later_report_evidence_ids':retro,'price_observation_only_evidence_ids':priceonly,'company_announcement_evidence_ids':[e['evidence_id'] for e in ann],'retrospective_company_announcement_ids':[e['evidence_id'] for e in retroann],'before_lookback_company_announcement_ids':[e['evidence_id'] for e in olderann],'profile_clue':clue,'cache_candidate_ids':sorted({x['article_id'] for x in cm}),'evidence_ids':ids,'rise_explanation_zh':phrase,'formula_miss_causality':'上涨报道背景不能证明公式漏选原因；原始公式门与形态差异由技术诊断另报。','coverage_limitations':['NONEXHAUSTIVE_PUBLIC_INDEX_NO_ZERO_ANNOUNCEMENT_CLAIM','FACTIVA_USER_NOT_LOGGED_IN','AIERA_REQUIRED_CORE_INSTRUCTIONS_TOOL_NOT_EXPOSED','V4_ANNOUNCEMENT_CATALOG_HK_ONLY','MORNING_NEWS_20261021_MISSING','MORNING_NEWS_PUBLICATION_TIMEZONE_UNCONFIRMED','RETRIEVED_20261023_NO_ARCHIVED_VINTAGE_PROOF'],'evidence_urls':sorted({evby[e]['url'] for e in ids}),'query_artifacts':[str(webpath),str(officialpath)],'research_only':True,'production_allowed':False,'buy_gate_updated':False,'orders_sent':False}
        r['query_started_at']=[web['retrieved_at'],official['retrieved_at']]
        r['query_retrieved_at']=[persisted_at(webpath),persisted_at(officialpath)]
        r['query_retrieved_at_basis']='LOCAL_RESPONSE_FILE_PERSISTED_AT_UPPER_BOUND_NOT_PROVIDER_INTERNAL_FETCH_TIME'
        r['query_response_counts']=[{'query_id':v['query_id'],'parsed_source_count':v.get('parsed_source_count',v.get('response_count')),'search_hit_count':None,'search_hit_count_null_reason':'PROVIDER_TOTAL_HITS_NOT_EXPOSED'} for v in [web,official]]
        r['publication_records']=[{'evidence_id':eid,'url':evby[eid]['url'],'publication_timestamp':evby[eid]['publication_timestamp'],'publication_timezone':evby[eid]['publication_timezone'],'time_status':evby[eid]['verification_status']} for eid in ids]
        r['publication_null_reason']=None if ids else 'NO_PUBLISHER_TIMESTAMP_VERIFIED_FOR_THIS_ROW_CANDIDATE_CLUES_NOT_PROMOTED'
        allrows.append(r)
        for v,path in [(web,webpath),(official,officialpath)]:
            if any(x['query_id']==v['query_id'] for x in queryledger):continue
            queryledger.append({'query_id':v['query_id'],'code':v['code'],'source':'PUBLIC_WEB_INDEX_OFFICIAL_DOMAINS' if v['query_id'].startswith('OFFICIAL') else 'PUBLIC_WEB_INDEX_NEWS','actual_query':v.get('actual_query'),'query_status':v['query_status'],'retrieved_at':v['retrieved_at'],'tool_response_block_count':None,'tool_response_block_count_null_reason':'WEB_TOOL_RETURNS_COMBINED_TEXT_NOT_STRUCTURED_BLOCKS','parsed_source_count':v.get('parsed_source_count',v.get('response_count')),'parsed_source_count_scope':v.get('parsed_source_count_scope','PARSED_TITLE_URL_HEADERS_IN_SINGLE_QUERY_RESPONSE_NOT_ARTICLES_OR_CATALYSTS'),'parsed_candidate_sources':v.get('sources',[]),'search_hit_count':None,'search_hit_count_null_reason':'PROVIDER_TOTAL_HIT_COUNT_NOT_EXPOSED','response_path':str(path),'response_sha256':sha(path),'batch_query_ids':v.get('batch_query_ids',[v['query_id']]),'response_is_raw_local_only':True})
            queryledger[-1].update(query_started_at=v['retrieved_at'],retrieved_at=persisted_at(path),retrieved_at_basis='LOCAL_RESPONSE_FILE_PERSISTED_AT_UPPER_BOUND_NOT_PROVIDER_INTERNAL_FETCH_TIME')
    assert len(allrows)==387 and len({(r['selection_date'],r['code']) for r in allrows})==387
    assert len(queryledger)==729
    (OUT/'CATALYST_ROWS_387.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False,sort_keys=True)+'\n' for r in allrows))
    csvrows=[]
    for r in allrows:
        csvrows.append({'selection_date':r['selection_date'],'signal_asof':r['signal_asof'],'code':r['code'],'name':r['input_name'],'catalyst_label':r['catalyst_label'],'query_status':r['query_status'],'official_query_status':r['official_query_status'],'main_window_reports':';'.join(r['main_window_report_evidence_ids']),'known_before_signal_reports':';'.join(r['known_before_signal_evidence_ids']),'announcement_contents_only':';'.join(r['company_announcement_evidence_ids']),'rise_explanation_zh':r['rise_explanation_zh'],'formula_miss_causality':r['formula_miss_causality'],'evidence_urls':';'.join(r['evidence_urls']),'profile_clue_url':(r['profile_clue'] or {}).get('url',''),'query_ids':';'.join(r['query_ids']),'coverage':'公开索引非穷尽；缺少证据不等于无公告/题材'})
    csvout('CATALYST_ROWS_387.csv',csvrows)
    save('SOURCE_QUERY_LEDGER.json',queryledger);save('VERIFIED_EVIDENCE.json',evidence)
    daily=[]
    for day in sorted({r['selection_date'] for r in allrows}):
        rs=[r for r in allrows if r['selection_date']==day]
        daily.append({'selection_date':day,'rows':len(rs),'queried':len(rs),'official_index_queried':len(rs),'main_window_report_context':sum(bool(r['main_window_report_evidence_ids']) for r in rs),'known_before_signal_report_context':sum(bool(r['known_before_signal_evidence_ids']) for r in rs),'company_content_confirmed_timing_unknown':sum(bool(r['company_announcement_evidence_ids']) for r in rs),'retrospective_profile_clue':sum(bool(r['profile_clue']) for r in rs),'timing_unknown':sum(r['catalyst_label']=='TIMING_UNKNOWN' for r in rs),'source_not_covered':sum(r['catalyst_label']=='SOURCE_NOT_COVERED' for r in rs)})
    csvout('DAILY_SUMMARY.csv',daily)
    failed=[x['query_id'] for x in queryledger if x['query_status']=='QUERY_FAILED']
    receipt={'status':'WRITER_HANDOFF_REQUIRES_INDEPENDENT_REVIEW','decision':'OPENBOOK_CATALYST_EVIDENCE_WITH_EXPLICIT_CANNOT_CONFIRM','rows':387,'unique_codes':len({r['code'] for r in allrows}),'news_row_queries':387,'official_unique_code_queries':342,'query_ledger_count':729,'failed_query_ids':failed,'label_counts':dict(Counter(r['catalyst_label'] for r in allrows)),'main_window_report_context_rows':sum(bool(r['main_window_report_evidence_ids']) for r in allrows),'known_before_signal_report_context_rows':sum(bool(r['known_before_signal_evidence_ids']) for r in allrows),'company_announcement_content_rows':sum(bool(r['company_announcement_evidence_ids']) for r in allrows),'evidence_records':len(evidence),'verified_epoch_report_sources':len(GROUPS),'all_729_total_search_hits':None,'total_search_hits_null_reason':'INDEX_PROVIDER_DOES_NOT_EXPOSE_TOTAL_HIT_COUNTS','query_failures_separate_from_connector_failure':True,'factiva_canary_status':'USER_NOT_LOGGED_IN','aiera_status':'NOT_CALLED_REQUIRED_CORE_INSTRUCTIONS_TOOL_UNAVAILABLE','price_cause_claims':0,'zero_announcement_claims':0,'historical_universe_certified':False,'pit_certified':False,'code_sha256':sha(__file__),'daily_summary':daily,'research_only':True,'production_allowed':False,'buy_gate_updated':False,'orders_sent':False}
    save('CATALYST_HANDOFF_RECEIPT.json',receipt)
    lines=['# 387条共同漏选：催化证据逐条说明','', '范围是既有5533研究池中的共同漏选，并非认证历史全A。387次逐条公开新闻索引、342次唯一代码官方域名索引均已执行；索引不穷尽全公告，因此没有“无公告”结论。','', '标签“公开报道归因”仅表示存在经原文和Unix时间戳核验的报道背景，不证明该事件造成涨幅，更不证明公式为何漏选。信号前已知背景、盘中报道、之后的回溯报道分别列出。公司PDF只确认代码和内容；文档/URL日期不替代首次公开时点。','', 'Factiva未登录；Aiera缺少其要求的前置工具；V4公告目录仅港股；10/21早报缺档；其余早报无显式时区。以上均保留为覆盖缺口。','', '原始来源及精确时间见VERIFIED_EVIDENCE.json；检索条件、返回候选计数和响应SHA见SOURCE_QUERY_LEDGER.json。','']
    for day in sorted({r['selection_date'] for r in allrows}):
        lines += ['## '+day,'','|代码|冻结名称|证据结论|中文解释|证据ID|','|---|---|---|---|---|']
        for r in allrows:
            if r['selection_date']!=day:continue
            labels={'PUBLIC_REPORTED_ATTRIBUTION':'公开报道背景','TIMING_UNKNOWN':'时点待核','SOURCE_NOT_COVERED':'来源覆盖不足'}
            ids=','.join(r['main_window_report_evidence_ids']+r['known_before_signal_evidence_ids']+r['company_announcement_evidence_ids']) or r['query_ids'][0]
            lines.append('|'+ '|'.join([r['code'],r['input_name'] or '名称未认证',labels[r['catalyst_label']],r['rise_explanation_zh'].replace('|','/'),ids])+'|')
        lines.append('')
    (OUT/'CATALYST_REPORT_ZH.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps(receipt,ensure_ascii=False))

if __name__=='__main__':main()
