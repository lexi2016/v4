"""Read-only projection of the existing shared morning-news authority.

No network, producer calls, imports of runtime services, or source writes.
Only supplied evidence directory is written; input hashes bind every read.
"""
import csv
import hashlib
import json
from pathlib import Path
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

ROOT = Path('/Users/lexi/Desktop/学习/因子工厂')
OUT = ROOT / 'research/week_miss387_diagnosis_20261023/catalyst'
SOURCE = Path('/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/v3_shared_data/.runtime/data')
TZ = ZoneInfo('Asia/Shanghai')

def canon(v):
    return json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()

def digest(v):
    return hashlib.sha256(canon(v)).hexdigest()

def file_sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def save(name, v):
    (OUT / name).write_text(json.dumps(v, ensure_ascii=False, indent=2) + '\n')

def under(rel):
    p = (SOURCE / rel).resolve()
    if SOURCE.resolve() not in p.parents:
        raise ValueError('PATH_ESCAPES_SOURCE')
    return p

def stamp(day, time='15:00:00'):
    return datetime.strptime(day + ' ' + time, '%Y%m%d %H:%M:%S').replace(tzinfo=TZ)

def main():
    assert (OUT/'CATALYST_START_REGISTRY_RECEIPT.json').is_file(), 'REGISTRATION_REQUIRED'
    now = datetime.now(timezone.utc).isoformat()
    path = ROOT/'research/week_two_model_comparison_20261023/comparison/COMMON_MISS_CONFIRMED.csv'
    rows = list(csv.DictReader(path.open(encoding='utf-8-sig')))
    assert len(rows)==387 and len({(r['selection_date'],r['code']) for r in rows})==387
    pointer = SOURCE/'morning_news/latest.json'
    index = json.loads(pointer.read_text())
    assert index['schema_version']=='v3_shared_data.morning_news_latest.v1'
    sessions=['20261012','20261013','20261014','20261015','20261016','20261019','20261020','20261021','20261022']
    coverage=[]; articles=[]
    for day in sessions:
        entry=index['entries'].get(day)
        record={'trade_date':day,'retrieved_at':now,'source':'JIUYANGONGSHE_MORNING_NEWS','pointer_path':str(pointer),'pointer_file_sha256':file_sha(pointer)}
        if not entry:
            coverage.append({**record,'query_status':'SOURCE_DATE_NOT_COVERED','article_count':None});continue
        files={k:under(entry[k+'_relative']) for k in ['payload','manifest','receipt']}
        values={k:json.loads(p.read_text()) for k,p in files.items()}
        p,m,r=values['payload'],values['manifest'],values['receipt']
        issues=[]
        if not (entry['payload_sha256']==digest(p)==m['payload_sha256']):issues.append('PAYLOAD_SHA_MISMATCH')
        if r.get('manifest_sha256')!=digest(m):issues.append('RECEIPT_MANIFEST_SHA_MISMATCH')
        if p.get('trade_date')!=day or m.get('trade_date')!=day:issues.append('DATE_MISMATCH')
        if p.get('source_role')!='JIUYANGONGSHE_MORNING_NEWS':issues.append('SOURCE_ROLE_MISMATCH')
        if p.get('article_count')!=len(p.get('articles',[])):issues.append('ARTICLE_COUNT_MISMATCH')
        if any(p.get(k) is not False or r.get(k) is not False for k in ['production_allowed','buy_gate_updated','orders_sent']):issues.append('SAFETY_FLAGS_MISMATCH')
        coverage.append({**record,'query_status':'VERIFIED_CACHE_READ' if not issues else 'CACHE_BINDING_FAILED','issues':issues,'article_count':len(p.get('articles',[])),'source_cannot_confirm':p.get('cannot_confirm',[]),'source_status':p.get('status'),'source_mode':p.get('source_mode'),'bindings':{k:{'path':str(files[k]),'file_sha256':file_sha(files[k]),'canonical_sha256':digest(values[k])} for k in files}})
        if issues:continue
        for i,a in enumerate(p.get('articles',[])):
            articles.append({'article_id':f'CACHE_{day}_{i:02d}','cache_trade_date':day,'payload_path':str(files['payload']),'payload_file_sha256':file_sha(files['payload']),'retrieved_at':now,**a})
    candidates=[]; plans=[]
    for row in rows:
        code=row['code'];name=row['name'].strip(); signal=stamp(row['signal_asof']); selection=stamp(row['selection_date'])
        low=sessions[max(0,sessions.index(row['signal_asof'])-2)]
        known_low=stamp(low,'00:00:00')
        matches=[]
        for a in articles:
            body=str(a.get('body_text') or a.get('body_excerpt_preview') or '')
            tokens=[code.split('.')[0]]+([name] if len(name)>=2 else [])
            hits=[x for x in tokens if x in body]
            if not hits:continue
            published_raw=a.get('published_at');pub=None;time_status='TIMING_UNKNOWN'
            try:
                pub=datetime.fromisoformat(str(published_raw))
                if pub.tzinfo is not None:time_status='SOURCE_EXPLICIT_OFFSET'
                else:pub=None;time_status='TIMEZONE_NOT_EXPLICIT'
            except (TypeError,ValueError):pass
            bucket='TIMING_UNKNOWN'
            if pub:
                if known_low<=pub<=signal:bucket='KNOWN_BEFORE_SIGNAL'
                elif signal<pub<=selection:bucket='MAIN_WINDOW'
                elif selection<pub:bucket='RETROSPECTIVE_ONLY'
                else:continue
            pos=min(body.index(x) for x in hits)
            # Minimal local excerpt for manual relevance review; never assert catalyst from matching name.
            item={'selection_date':row['selection_date'],'signal_asof':row['signal_asof'],'code':code,'input_name':name,'article_id':a['article_id'],'title':a.get('title'),'url':a.get('url'),'publication_timestamp':published_raw,'publication_timezone_status':time_status,'temporal_bucket':bucket,'matched_tokens':hits,'name_binding':'INPUT_ALIAS_NOT_HISTORICAL_CERTIFIED','context_excerpt':body[max(0,pos-70):pos+160],'source':'韭研公社早报','verification_status':'CACHE_MANIFEST_RECEIPT_VERIFIED_CONTENT_RELEVANCE_PENDING','payload_path':a['payload_path'],'payload_file_sha256':a['payload_file_sha256'],'retrieved_at':now}
            candidates.append(item);matches.append(a['article_id'])
        d=row['selection_date'];datestr=f'{d[:4]}年{int(d[4:6])}月{int(d[6:])}日'
        query=f'{code.split(".")[0]} {name} {datestr} 公告 新闻 政策 题材 涨停原因'
        plans.append({'query_id':f'WEB_{d}_{code.replace(".","_")}','selection_date':d,'signal_asof':row['signal_asof'],'code':code,'name':name,'query':query,'main_window_start':signal.isoformat(),'main_window_end':selection.isoformat(),'known_before_signal_start':known_low.isoformat(),'cache_matches':matches})
    save('CACHE_COVERAGE.json',{'retrieved_at':now,'source_root':str(SOURCE),'scope':'EXISTING_EARLY_NEWS_ONLY_NOT_EXHAUSTIVE_ANNOUNCEMENTS','coverage':coverage,'articles_read':len(articles),'input_file_sha256':file_sha(path),'code_sha256':file_sha(Path(__file__))})
    save('CACHE_MENTION_CANDIDATES.json',candidates)
    save('QUERY_PLAN.json',plans)
    save('CACHE_EXTRACTION_RECEIPT.json',{'status':'IMPLEMENTED_WRITER_CHECKED_NOT_INDEPENDENT_ACCEPTANCE','rows':len(rows),'unique_codes':len({x['code'] for x in rows}),'article_count':len(articles),'mention_candidate_rows':len(candidates),'matched_code_dates':len({(x['selection_date'],x['code']) for x in candidates}),'missing_cache_dates':[x['trade_date'] for x in coverage if x['query_status']=='SOURCE_DATE_NOT_COVERED'],'failed_cache_dates':[x['trade_date'] for x in coverage if x['query_status']=='CACHE_BINDING_FAILED'],'research_only':True,'production_allowed':False,'buy_gate_updated':False,'orders_sent':False})
    print(json.dumps(json.loads((OUT/'CACHE_EXTRACTION_RECEIPT.json').read_text()),ensure_ascii=False))

if __name__=='__main__':main()
