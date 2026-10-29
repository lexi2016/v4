"""One existing indexed candidate, real public owner detail, no cache writes."""
from pathlib import Path
import hashlib
import json
import runpy

HERE = Path(__file__).resolve().parent
runpy.run_path(str(HERE.parent / 'run_targeted_checks.py'), run_name='candidate_read_only_imports')
from infrastructure import zsxq_pdf_ingestion as owner
from infrastructure import zsxq_pdf_search_index as search
from infrastructure.data_store import NativeDataStore
from domains.related_pdf_reports import read_related_pdf_reports

ROOT = Path('/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data')
DOC = 'ffd9fdfa04632c4d8ee530d00cbc5870190b31f8ab6d8f8bab8753ae06025073'
DAY = '20261027'


def main():
    store = NativeDataStore(ROOT)
    ledger, ledger_sha = search._read_day(store, DAY)
    entry = ledger['entries'][DOC]
    candidate = {key: entry[key] for key in ('verified_pdf_sha256', 'verified_pdf_size', 'verified_pages_size')}
    candidate.update(document_id=DOC, research_date=DAY)
    detail = owner.read_pdf_document_detail(ROOT, DOC, DAY)
    assert detail['status'] == 'READY'
    assert detail['receipt']['verified_pdf_sha256'] == candidate['verified_pdf_sha256']
    assert detail['processing']['verified_pdf_size'] == candidate['verified_pdf_size']
    assert detail['processing']['verified_pages_size'] == candidate['verified_pages_size']

    class Reader:
        def query_pdf_search_index(self, _root, _terms):
            return {'status': 'PARTIAL', 'candidates': [candidate], 'checkpoint_sha256': ledger_sha,
                    'coverage': {'indexed_documents': 1, 'gaps': []}}

        def read_pdf_document_detail(self, _root, doc_id, day):
            assert doc_id == DOC and day == DAY
            return detail

    result = read_related_pdf_reports(ROOT, None, identity_date='20261029',
        symbols=['600025.SH', '000410.SZ', '920454.BJ'],
        hints=['600025.SH:华能水电', '000410.SZ:沈阳机床', '920454.BJ:同心传动'], max_documents=1, reader=Reader())
    assert result['coverage']['verified_documents'] == 1
    assert not any(g.get('reason') == 'DOCUMENT_DETAIL_CONTRACT_INVALID' for g in result['coverage']['gaps'])
    evidence = {'status': 'PASS', 'scope': 'ONE_SELECTED_EXISTING_CANDIDATE_REAL_PUBLIC_OWNER_DETAIL',
        'document_id': DOC, 'research_date': DAY, 'derived_day_sha256': ledger_sha,
        'owner_status': detail['status'], 'owner_receipt': detail['receipt'],
        'verified_pdf_size': detail['processing']['verified_pdf_size'],
        'verified_pages_size': detail['processing']['verified_pages_size'],
        'relation_result': result, 'source_index_sha256': hashlib.sha256((ROOT / owner.STATE_RELATIVE).read_bytes()).hexdigest(),
        'cache_writes': 0, 'services_started': 0, 'full_three_stock_api_verdict': 'ROOT_PENDING'}
    (HERE / 'ONE_REAL_DETAIL_RESULT.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'status': evidence['status'], 'verified_documents': 1,
        'stocks': [{'symbol': s['symbol'], 'reports': len(s['reports']), 'result_status': s['result_status']}
                   for s in result['stocks']]}, ensure_ascii=False))


if __name__ == '__main__':
    main()
