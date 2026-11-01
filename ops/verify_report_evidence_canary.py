"""Frozen 12-question comparison against real local native vectors, never fixtures."""
import argparse
import asyncio
import json
from pathlib import Path
import time
from domains.report_evidence import ReportEvidenceService
from infrastructure.report_evidence_index import PdfOwner,ReportIndex,digest
from infrastructure.report_evidence_native import LocalNative

def percentile95(values):
    return sorted(values)[max(0,__import__('math').ceil(len(values)*.95)-1)]

async def main(args):
    frozen=json.loads(Path(args.frozen).read_text());owner=PdfOwner(args.data_root)
    index=ReportIndex(args.index_root,owner);native=LocalNative(args.bridge);native.guard()
    service=ReportEvidenceService(index,native,document_allowlist=[d['document_id'] for d in frozen['documents']])
    verified={}
    for row in frozen['documents']:
        d=owner.verified(row['document_id'],row['date']);assert d['receipt']['verified_pdf_sha256']==row['pdf_sha']
        assert d['receipt']['sha256']==row['receipt_sha'];verified[d['document_id']]=d
    frozen_db_sha=digest(index.path.read_bytes())
    frozen_generation=index.coverage()['generation']
    with index.connect() as db:
        frozen_uri_sha=digest(json.dumps(sorted({r[0] for r in db.execute('SELECT uri FROM chunks') if r[0]}),sort_keys=True))
    results=[];times={'keyword':[],'hybrid':[],'vector':[]}
    # A real warm-up is excluded from full-query timings. No response cache exists.
    await service.search(frozen['cases'][0]['query'])
    for case in frozen['cases']:
        params=dict(case['params']);empty=params.pop('expect_empty',False);strategy=params.pop('strategy',None)
        if case['gold_document_ids'] and not empty:
            gold_text='\n'.join(p['text'] for doc in case['gold_document_ids'] for p in verified[doc]['pages'] if p['page_number'] in case['gold_pages'])
            assert all(needle in gold_text for needle in case['gold_literal_needles']), 'GOLD_NOT_IN_ORIGINAL_PAGE:'+case['id']
        row={'id':case['id'],'query':case['query'],'results':{}}
        for mode in ('keyword','vector','hybrid'):
            start=time.perf_counter();r=await service.search(case['query'],strategy=strategy or mode,**params);elapsed=time.perf_counter()-start
            times[mode].append(elapsed)
            relevant=[h for h in r['hits'] if h['document_id'] in case['gold_document_ids'] and h['page'] in case['gold_pages'] and all(n in h['text'] for n in case['gold_literal_needles'])]
            valid_empty=not r['hits'] if empty else None
            row['results'][mode]={'seconds':elapsed,'relevant':bool(relevant),'valid_empty':valid_empty,'response':r}
        results.append(row)
    kw=sum(r['results']['keyword']['relevant'] for r in results)
    hybrid=sum(r['results']['hybrid']['relevant'] for r in results)
    improvement=sum(not r['results']['keyword']['relevant'] and r['results']['hybrid']['relevant'] for r in results if r['id'] in {'C02','C03'})
    errors=[]
    for row,case in zip(results,frozen['cases']):
        r=row['results']['hybrid']['response']
        if case['params'].get('expect_empty') and r['hits']:errors.append(case['id']+':EXPECTED_EMPTY')
        if r['index_generation']!=frozen_generation:errors.append(case['id']+':GENERATION_CHANGED')
        if case['gold_document_ids'] and not case['params'].get('expect_empty') and not r['vector_succeeded']:errors.append(case['id']+':NO_REAL_VECTOR_CALL')
        if r['vector_attempted'] and r['vector_scope_sha256']!=frozen_uri_sha and not case['params'].get('security'):errors.append(case['id']+':SCOPE_CHANGED')
        if r['input_tokens_upper_bound']>6000:errors.append(case['id']+':TOKEN_LIMIT')
        if any('KEYWORD_ONLY' in gap for gap in r['gaps']) and row['id'] not in {'C09','C10','C11','C12'}:errors.append(case['id']+':VECTOR_NOT_PROVEN')
        for hit in r['hits']:
            original=verified[hit['document_id']]
            p=next(p for p in original['pages'] if p['page_number']==hit['page'])
            if p['text_sha256']!=hit['page_sha256']:errors.append(case['id']+':PAGE_SHA')
            if case['params'].get('security') and not hit['subjects']:errors.append(case['id']+':ENTITY_ROLE')
    try:service.read('../outside.pdf');errors.append('ACL_PATH_ACCEPTED')
    except ValueError:pass
    p95={k:percentile95(v) for k,v in times.items()}
    if frozen_db_sha!=digest(index.path.read_bytes()):errors.append('SQLITE_BYTES_CHANGED')
    passed=not errors and hybrid>=kw and improvement>=1 and p95['hybrid']<=max(2,1.2*p95['keyword'])
    receipt=dict(status='PASS_FROZEN_12_REAL_LOCAL_VECTOR' if passed else 'FAIL_FROZEN_12',frozen_sha256=digest(Path(args.frozen).read_bytes()),
        sqlite_sha256=frozen_db_sha,native_uri_set_sha256=frozen_uri_sha,index_generation=frozen_generation,
        owner_module_path=owner.owner.__file__,owner_module_sha256=digest(Path(owner.owner.__file__).read_bytes()),
        coverage=index.coverage(),keyword_relevant=kw,hybrid_relevant=hybrid,synonym_improvement=improvement,p95_seconds=p95,errors=errors,
        scope='3 original PDFs/12 frozen questions only; all result page SHA verified; ACL path refusal checked',results=results)
    Path(args.output).write_text(json.dumps(receipt,ensure_ascii=False,indent=2))
    print(json.dumps({k:v for k,v in receipt.items() if k!='results'},ensure_ascii=False,indent=2))
    return passed

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('data-root','index-root','bridge','frozen','output'):p.add_argument('--'+name,required=True)
    args=p.parse_args();raise SystemExit(0 if asyncio.run(main(args)) else 1)
