"""Read the frozen D29 product through an isolated loopback API; never publish."""
from pathlib import Path
import hashlib
import json
import socket
import sys
import tempfile
import threading
import time
from urllib.request import urlopen

HANDOFF = Path(__file__).resolve().parents[1]
PROJECT = HANDOFF.parents[2]
sys.path.insert(0, str(HANDOFF))
sys.path.insert(0, str(PROJECT))
from serve_daily_dashboard_demo import create_demo_app
import uvicorn

SOURCE = Path('/Users/lexi/Desktop/学习/因子工厂/research/a_daily_update_path_20261029_r1/dashboard_completion_r1/today_full_r1')
RESULT_SHA = '58c8016a0dd814c434bd66b344153a5ed99abe69f557884a7b07f66a413131ac'
FROZEN = ('domains/research_daily_product.py', 'domains/research_daily_statistics.py', 'ops/research_panel_daily_product.py')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    assert digest(SOURCE / 'RESULT.json') == RESULT_SHA
    frozen_before = {name: digest(PROJECT / name) for name in FROZEN}
    with tempfile.TemporaryDirectory(prefix='v4-3p2-check-') as temporary, socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(create_demo_app(SOURCE, Path(temporary)), log_level='warning', access_log=False))
        thread = threading.Thread(target=server.run, kwargs={'sockets': [listener]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started and thread.is_alive() and time.monotonic() < deadline:
                time.sleep(0.02)
            assert server.started
            base = f'http://127.0.0.1:{port}'

            def read(path):
                with urlopen(base + path, timeout=10) as response:
                    assert response.status == 200
                    return json.load(response)

            product = read('/api/v4/research/a-share/daily-product?date=20261029')
            assert product['status'] == 'PARTIAL_WITH_ROWS'
            assert len(product['rows']) == product['unique_count'] == 247
            assert product['processed_count'] == 5808
            detail = read('/api/v4/research/a-share/daily-product?date=20261029&symbol=600025.SH')
            assert detail['status'] == 'READY', detail
            assert detail['source_generation'] == product['source_generation']
            price = detail['row']['statistics']['price_distribution']
            assert price['near_250']['percentile_le'] == 1.0
            assert price['all_history']['percentile_le'] == 0.9790697674418605
            event = None
            with urlopen(base + '/api/v4/research/events', timeout=10) as response:
                assert response.status == 200
                for _ in range(20):
                    line = response.readline().decode('utf-8')
                    if line.startswith('data: '):
                        candidate = json.loads(line[6:])
                        if candidate.get('schema_version') == 'v4.a_share.daily_completion.v1':
                            event = candidate
                            break
            assert event is not None
            assert event['manifest'] == product['manifest'] and event['artifact'] == product['artifact']
            reports = read('/api/v4/research/pdf-relations?identity_date=20261029&symbols=600025.SH&max_dates=1&max_documents=5')
            assert reports['status'] == 'NOT_MATERIALIZED'
            assert reports['coverage']['detail_attempts'] == 0
            assert reports['coverage']['dates_scanned'] == []
            evidence = {'status': 'PASS', 'scope': 'ISOLATED_LOOPBACK_API_AND_SSE', 'port': port,
                        'result_sha256': RESULT_SHA, 'data_date': product['data_date'],
                        'unique_count': product['unique_count'], 'processed_count': product['processed_count'],
                        'group_counts': product['group_counts'], 'artifact': product['artifact'],
                        'symbol': detail['row']['symbol'], 'symbol_status': detail['status'],
                        'price_distribution': price, 'historical_coverage': detail['row']['historical_coverage'],
                        'sse_event_id': event['event_id'], 'sse_exact_refs_match': True,
                        'report_status': reports['status'], 'report_detail_attempts': 0,
                        'frozen_sha256': frozen_before, 'UI': 'NOT_RUN', 'DEPLOYED': False,
                        'RESEARCH_ONLY': True, 'production_allowed': False, 'buy_gate_updated': False, 'orders_sent': False}
        finally:
            server.should_exit = True
            thread.join(timeout=10)
            assert not thread.is_alive(), 'isolated server did not exit'
    assert frozen_before == {name: digest(PROJECT / name) for name in FROZEN}
    assert digest(SOURCE / 'RESULT.json') == RESULT_SHA
    evidence['isolated_server_stopped'] = True
    evidence['temporary_root_removed'] = not Path(temporary).exists()
    (Path(__file__).parent / 'REAL_D29_RESULT.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: evidence[k] for k in ('status', 'data_date', 'unique_count', 'processed_count', 'symbol_status', 'sse_exact_refs_match', 'isolated_server_stopped')}))


if __name__ == '__main__':
    main()
