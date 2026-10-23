"""Read-only incremental checker for catalyst evidence and exact two-axis merge.
Never invokes producer main(), network tools, or already accepted model probes.
"""
import argparse,html,json,re
from datetime import datetime
from collections import Counter
from pathlib import Path
from html.parser import HTMLParser
from zoneinfo import ZoneInfo
from registry_bridge import w,ROOT
from diagnose import OUT,readcsv
from merge_report import verify as verify_merge
class Body(HTMLParser):
 def __init__(self):super().__init__(convert_charrefs=True);self.parts=[]
 def handle_data(self,text):self.parts.append(text)
def norm(s):return re.sub(r'\s+','',s).replace('Ａ','A')
def load(p):return json.loads(Path(p).read_text())
def key(r):return r['selection_date'],r['code']
def path(p):
 p=Path(p);return p if p.is_absolute() else ROOT/p

def publisher(e):
 p=path(e['raw_response_path']);assert w.sha(p)==e['raw_response_sha256'];text=p.read_text()
 # Decode captured publisher JSON directly, separate from catalyst producer helper.
 match=re.search(r'<script\b[^>]*\bid=[\"\']__NEXT_DATA__[\"\'][^>]*>(.*?)</script>',text,re.S)
 if match:obj=json.loads(match.group(1));article=obj['props']['pageProps']['articleDetail']
 else:
  marker=re.search(r'__NEXT_DATA__\s*=\s*',text);assert marker,'PUBLISHER_EMBEDDED_JSON_MISSING';obj,_=json.JSONDecoder().raw_decode(text[marker.end():]);article=obj['props']['initialState']['deep_details']
 assert 'CLS_'+str(article.get('id',article.get('article_id')))==e['evidence_id']
 assert article['ctime']==e['ctime_epoch_seconds']
 assert datetime.fromtimestamp(article['ctime'],ZoneInfo('Asia/Shanghai')).isoformat()==e['publication_timestamp']
 parser=Body();parser.feed(article.get('content') or '');return ' '.join(parser.parts)

def main(output):
 output=Path(output);output.mkdir(parents=True,exist_ok=True);c=load(OUT/'CATALYST_MERGE_REVIEW_CONTRACT.json')
 for p,h in c['frozen_source_bindings'].items():assert w.sha(p)==h,'FROZEN_INCREMENT_INPUT_DRIFT:'+p
 base=OUT/'catalyst';rows=[json.loads(x) for x in (base/'CATALYST_ROWS_387.jsonl').read_text().splitlines()];plan=load(base/'QUERY_PLAN.json');qs=load(base/'SOURCE_QUERY_LEDGER.json');evidence=load(base/'VERIFIED_EVIDENCE.json');ev={x['evidence_id']:x for x in evidence};queries={x['query_id']:x for x in qs}
 original=readcsv(OUT.parent/'week_two_model_comparison_20261023/comparison/COMMON_MISS_CONFIRMED.csv');assert len(rows)==len({key(x) for x in rows})==387
 assert {key(r) for r in rows}=={key(r) for r in original}=={key(r) for r in plan}
 assert len({r['code'] for r in rows})==342;assert len(qs)==len(queries)==729
 partition=dict(Counter(r['catalyst_label'] for r in rows));assert partition=={'TIMING_UNKNOWN':172,'SOURCE_NOT_COVERED':136,'PUBLIC_REPORTED_ATTRIBUTION':79}
 counts=dict(main=sum(bool(r['main_window_report_evidence_ids']) for r in rows),known=sum(bool(r['known_before_signal_evidence_ids']) for r in rows),overlap=sum(bool(r['main_window_report_evidence_ids']) and bool(r['known_before_signal_evidence_ids']) for r in rows));assert counts=={'main':63,'known':22,'overlap':6};assert counts['main']+counts['known']-counts['overlap']==79
 bodies={eid:publisher(e) for eid,e in ev.items() if e['verification_status']=='ORIGINAL_PUBLISHER_BODY_AND_EPOCH_VERIFIED'};assert len(bodies)==6;entitybindings=[]
 for r in rows:
  assert r['research_only'] and not any(r[x] for x in ['production_allowed','buy_gate_updated','orders_sent']);assert r['formula_miss_causality'] and '不能证明' in r['formula_miss_causality']
  lo,sig,end=[datetime.fromisoformat(r[k]) for k in ['known_before_signal_start','main_window_start','main_window_end']];assert all(t.utcoffset().total_seconds()==28800 for t in [lo,sig,end]);assert lo<=sig<end
  ids=r['main_window_report_evidence_ids']+r['known_before_signal_evidence_ids'];assert bool(ids)==(r['catalyst_label']=='PUBLIC_REPORTED_ATTRIBUTION')==r['verified_report_context_present']
  prs={x['evidence_id']:x for x in r['publication_records']}
  for label,ids in [('main',r['main_window_report_evidence_ids']),('known',r['known_before_signal_evidence_ids'])]:
   for eid in ids:
    e=ev[eid];assert e['verification_status']=='ORIGINAL_PUBLISHER_BODY_AND_EPOCH_VERIFIED';assert e['publication_timezone']=='Asia/Shanghai';assert e['price_causality']=='NOT_ESTABLISHED'
    t=datetime.fromisoformat(e['publication_timestamp']);assert t.utcoffset().total_seconds()==28800 and t.timestamp()==e['ctime_epoch_seconds']
    assert sig<t<=end if label=='main' else lo<=t<=sig
    assert prs[eid]['publication_timestamp']==e['publication_timestamp'] and prs[eid]['publication_timezone']=='Asia/Shanghai' and prs[eid]['url']==e['url']
    name=norm(r['input_name']);assert name and name in norm(bodies[eid]),'POSITIVE_ENTITY_NOT_IN_ORIGINAL_BODY:'+str(key(r))+':'+eid
    assert e['url'] in r['evidence_urls'];entitybindings.append(dict(selection_date=r['selection_date'],code=r['code'],frozen_input_name=r['input_name'],evidence_id=eid,source_url=e['url'],window=label,publication_timestamp=e['publication_timestamp'],epoch=e['ctime_epoch_seconds'],entity_present_in_original_body=True,historical_alias_passport='CANNOT_CONFIRM'))
  for eid in r['retrospective_later_report_evidence_ids']:assert datetime.fromisoformat(ev[eid]['publication_timestamp'])>end
  for eid in r['company_announcement_evidence_ids']:
   e=ev[eid];assert e['code']==r['code'];assert e['publication_timestamp'] is None and lo.date().isoformat()<=e['document_date']<=end.date().isoformat()
  assert len(r['query_ids'])==2
  for qid in r['query_ids']:assert qid in queries and queries[qid]['code']==r['code']
  assert r['query_ids'][0]=='WEB_'+r['selection_date']+'_'+r['code'].replace('.','_') and r['query_ids'][1]=='OFFICIAL_'+r['code'].replace('.','_')
 for q in qs:
  assert w.sha(path(q['response_path']))==q['response_sha256'];assert q['parsed_source_count']==len(q['parsed_candidate_sources']);assert q['search_hit_count'] is None and q['search_hit_count_null_reason'];assert q['tool_response_block_count'] is None and q['tool_response_block_count_null_reason'];assert q['actual_query'] and q['retrieved_at']
 for e in evidence:assert w.sha(path(e['raw_response_path']))==e['raw_response_sha256'] and e['price_causality']=='NOT_ESTABLISHED'
 for manifest in ['OUTPUT_MANIFEST.json','presentation_r2/PRESENTATION_MANIFEST.json']:
  for p,h in load(OUT/manifest).items():assert w.sha(p)==h,'ACCEPTED_TECHNICAL_ARTIFACT_DRIFT:'+p
 for entry in load(OUT/'SOURCE_SYNC_ALLOWLIST.json')['files']:
  if entry['path'] in c['technical12_source_sha256']:assert w.sha(ROOT/'worktrees/week_miss387_diagnosis_20261023'/entry['path'])==c['technical12_source_sha256'][entry['path']]
 verify_merge(output/'MERGE_VERIFIER_RECEIPT.json')
 w.save(output/'ENTITY_EVIDENCE_BINDINGS.json',entitybindings)
 result=dict(status='INCREMENTAL_CHECK_PASS_INDEPENDENT_REVIEWER_VERDICT_SEPARATE',rows=387,unique_codes=342,queries=729,evidence_records=len(evidence),publisher_epoch_sources=len(bodies),partition=partition,time_window_counts=counts,positive_entity_evidence_bindings=len(entitybindings),known_before_uses_same_verified_timezone_epoch_gate_as_main=True,technical_source_and_artifacts_unchanged=True,model_probes_replayed=0,news_queries_replayed=0,source_sha256=w.sha(__file__),limitations=['Public reported context only, no proven price/formula-miss cause','Historical name/eligibility/PIT and exhaustive announcement coverage unconfirmed','Company PDF document date is not first-publication available_at'],**w.FLAGS);w.save(output/'INCREMENTAL_CHECK_RECEIPT.json',result);print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args();main(a.output)
