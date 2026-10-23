"""Offline Writer checks. Independent Reviewer acceptance is still required."""
import hashlib
import json
from datetime import datetime
from pathlib import Path

ROOT=Path('/Users/lexi/Desktop/学习/因子工厂')
OUT=ROOT/'research/week_miss387_diagnosis_20261023/catalyst'
def load(p): return json.loads(Path(p).read_text())
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def main():
    contract=load(OUT/'CONTRACT.json')
    for p,h in contract['input_bindings'].items():assert sha(p)==h, p
    plans=load(OUT/'QUERY_PLAN.json')
    rows=[json.loads(s) for s in (OUT/'CATALYST_ROWS_387.jsonl').read_text().splitlines()]
    queries=load(OUT/'SOURCE_QUERY_LEDGER.json')
    evidence={x['evidence_id']:x for x in load(OUT/'VERIFIED_EVIDENCE.json')}
    assert len(rows)==len(plans)==387
    expected={(x['selection_date'],x['code']) for x in plans}
    assert {(x['selection_date'],x['code']) for x in rows}==expected
    assert len(queries)==729 and len({q['query_id'] for q in queries})==729
    qmap={q['query_id']:q for q in queries}
    positive=0
    for r in rows:
        assert r['query_ids'][0] in qmap and r['query_ids'][1] in qmap
        assert r['query_retrieved_at'] and isinstance(r['query_candidate_source_urls'],list)
        assert r['research_only'] and not any(r[k] for k in ['production_allowed','buy_gate_updated','orders_sent'])
        assert r['rise_explanation_zh'] and r['formula_miss_causality']
        lo=datetime.fromisoformat(r['known_before_signal_start']);sig=datetime.fromisoformat(r['main_window_start']);end=datetime.fromisoformat(r['main_window_end'])
        for eid in r['main_window_report_evidence_ids']:
            e=evidence[eid];t=datetime.fromisoformat(e['publication_timestamp'])
            assert sig<t<=end and e['publication_timezone']=='Asia/Shanghai'
            assert e['verification_status']=='ORIGINAL_PUBLISHER_BODY_AND_EPOCH_VERIFIED'
        for eid in r['known_before_signal_evidence_ids']:
            e=evidence[eid];t=datetime.fromisoformat(e['publication_timestamp'])
            assert lo<=t<=sig
        for eid in r['retrospective_later_report_evidence_ids']:
            assert datetime.fromisoformat(evidence[eid]['publication_timestamp'])>end
        for eid in r['company_announcement_evidence_ids']:
            assert lo.date().isoformat()<=evidence[eid]['document_date']<=end.date().isoformat()
            assert evidence[eid]['publication_timestamp'] is None
        if r['catalyst_label']=='PUBLIC_REPORTED_ATTRIBUTION':
            positive+=1
            assert r['main_window_report_evidence_ids'] or r['known_before_signal_evidence_ids']
            assert r['evidence_urls']
    for q in queries:
        assert sha(q['response_path'])==q['response_sha256']
        assert q['parsed_source_count']==len(q['parsed_candidate_sources'])
        assert q['search_hit_count'] is None and q['search_hit_count_null_reason']
        assert q['tool_response_block_count'] is None and q['tool_response_block_count_null_reason']
        assert q['actual_query'] and q['retrieved_at']
        raw=load(q['response_path'])['response']
        assert not any(x in raw for x in ['You have reached the limit','Too Many Requests','USER_NOT_LOGGED_IN']), q['query_id']
    for e in evidence.values():
        assert sha(e['raw_response_path'])==e['raw_response_sha256']
        assert e['url'].startswith('https://') and e['retrieved_at']
        assert e['price_causality']=='NOT_ESTABLISHED'
    receipt=load(OUT/'CATALYST_HANDOFF_RECEIPT.json')
    assert positive==receipt['label_counts']['PUBLIC_REPORTED_ATTRIBUTION']
    result={'status':'WRITER_OFFLINE_CHECKS_PASS_NOT_INDEPENDENT_ACCEPTANCE','rows_checked':387,'query_bindings_checked':729,'evidence_records_checked':len(evidence),'positive_report_context_rows':positive,'failed_assertions':0,'network_calls':0,'input_sha_binding':'UNCHANGED','checks':['ROW_CARDINALITY_AND_IDENTITY','QUERY_RESPONSE_AND_COUNT_BINDINGS','POSITIVE_SOURCE_EPOCH_AND_TIME_WINDOWS','NO_FUTURE_REPORT_IN_MAIN_WINDOW','DOCUMENT_DATE_NOT_FIRST_PUBLICATION','SAFETY_FLAGS_AND_PRICE_CAUSE_BOUNDARY'],'code_sha256':sha(__file__)}
    (OUT/'WRITER_OFFLINE_CHECKS.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':main()
