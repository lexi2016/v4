#!/usr/bin/env python3
"""Temporary, read-only test harness; requires externally supplied SHA-verified samples.

Never an online source. No producer, scheduler or persistence. Only loopback serving.
Missing frozen endpoints/assets return an explicit error, not synthetic market data.
"""
from __future__ import annotations
import argparse
import copy
import csv
import hashlib
import json
import re
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.request import urlopen


def load_samples(root: Path):
    manifest = json.loads((root / 'MATERIALS_MANIFEST.json').read_text())
    for item in manifest['files']:
        raw = (root / item['path']).read_bytes()
        if len(raw) != item['bytes'] or hashlib.sha256(raw).hexdigest() != item['sha256']:
            raise ValueError('sample SHA mismatch: ' + item['path'])
    samples = {p.stem: json.loads(p.read_text())['payload'] for p in (root / 'api_samples').glob('*.json')}
    days = {}
    for date in ('20261112', '20261113'):
        base = copy.deepcopy(samples['pools_' + date + '_limit1'])
        with (root / ('POOL_MEMBERSHIPS_' + date + '.csv')).open(encoding='utf-8-sig', newline='') as f:
            records = list(csv.DictReader(f))
        for pool in base['pools']:
            originals = {r.get('symbol'): r for r in pool['rows']}
            rows = []
            for r in records:
                if r['pool_id'] != pool['pool_id']:
                    continue
                row = dict(originals.get(r['symbol'], {}))
                row.update({k: v for k, v in r.items() if v != ''})
                row.update(symbol=r['symbol'], market=r['market'], stock_name=r['name'],
                           signal_date=r['source_date'], trade_date=r['observation_date'])
                # CSV score/rank strings are preserved; absent fields stay absent.
                if r['stage_selection_eligible']:
                    row['stage_selection_eligible'] = r['stage_selection_eligible'].lower() == 'true'
                else:
                    row['stage_selection_eligible'] = None
                rows.append(row)
            if len(rows) != pool['pool_size']:
                raise ValueError('pool membership denominator mismatch')
            pool['rows'] = rows
        days[date] = base
    return samples, days


def pool_page(base, offset, limit):
    value = copy.deepcopy(base)
    # The owner's contract applies a common offset/limit to each pool and market array.
    max_rows = max([*value['market_totals'].values(), *(p['pool_size'] for p in value['pools'])])
    more = offset + limit < max_rows
    value['pagination'] = dict(offset=offset, limit=limit, next_offset=offset+limit if more else None,
                               has_more=more, complete=offset == 0 and not more)
    for pool in value['pools']:
        pool['rows'] = pool['rows'][offset:offset+limit]
        pool.update(returned_rows=len(pool['rows']), page_offset=offset, page_limit=limit,
                    has_more=offset+limit < pool['pool_size'], complete=offset == 0 and pool['pool_size'] <= limit)
    # Do not retain the original limit-1 projection arrays as if they were complete.
    for key in ('unified_rows', 'a_source_only_rows', 'a_all_pool_rows', 'rows'):
        value.pop(key, None)
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--samples', type=Path, required=True)
    parser.add_argument('--export', type=Path)
    parser.add_argument('--dist', type=Path)
    parser.add_argument('--port', type=int, default=8874)
    parser.add_argument('--check-http', action='store_true', help='Check built entry URLs in-process, then close the temporary server')
    args = parser.parse_args()
    samples, days = load_samples(args.samples)
    if args.export:
        args.export.mkdir(parents=True, exist_ok=True)
        for date, base in days.items():
            pages = [pool_page(base, i, 300) for i in range(0, max(base['market_totals'].values()), 300)]
            (args.export / (date + '.json')).write_text(json.dumps(pages, ensure_ascii=False))
        for name, payload in samples.items():
            (args.export / (name + '.json')).write_text(json.dumps(payload, ensure_ascii=False))
        print('PASS: 23 member hashes; complete two-day pool projections exported', flush=True)
    if not args.dist:
        return
    dist = args.dist.resolve()
    if not (dist / 'v45/selection/index.html').is_file():
        raise ValueError('build the candidate first')

    class Handler(SimpleHTTPRequestHandler):
        def send_json(self, value, code=200):
            raw = json.dumps(value, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-V45-Test-Mode', 'FROZEN_SAMPLE_REPLAY_NOT_PRODUCTION')
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            url = urlparse(self.path)
            query = parse_qs(url.query)
            get = lambda key, default='': query.get(key, [default])[0]
            date = get('date')
            if url.path == '/api/v4/preselection-pools' and date in days:
                return self.send_json(pool_page(days[date], int(get('offset', '0')), int(get('limit', '200'))))
            if url.path in ('/api/v3/review', '/api/v4/review') and date == '20261112':
                return self.send_json(samples['review_D12'])
            endpoints = {'daily-product':'individual_product', 'original-chart':'original_chart_descriptor',
                         'company-materials':'company_materials'}
            endpoint = url.path.rsplit('/', 1)[-1]
            if url.path.startswith('/api/v4/research/a-share/') and date == '20261111' and get('symbol') == '000159.SZ':
                if endpoint in endpoints:
                    return self.send_json(samples[endpoints[endpoint] + '_000159_D11'])
                if endpoint == 'event-cases' and get('group') == 'original' and get('horizon') == 'd2':
                    return self.send_json(samples['event_cases_000159_D11_d2'])
            if url.path.startswith('/api/'):
                return self.send_json({'status':'CANNOT_CONFIRM', 'test_mode':'FROZEN_SAMPLE_REPLAY',
                                       'cannot_confirm':['ENDPOINT_OR_ASSET_NOT_INCLUDED_IN_SUPPLIED_SAMPLE']}, 503)
            return super().do_GET()

        def do_POST(self):
            return self.send_json({'error':'TEST_HARNESS_READ_ONLY'}, 405)
        do_PUT = do_POST
        do_PATCH = do_POST
        do_DELETE = do_POST

    server = ThreadingHTTPServer(('127.0.0.1', args.port), partial(Handler, directory=str(dist)))
    if args.check_http:
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            origin = f'http://127.0.0.1:{server.server_port}'
            paths = ['/?date=20261112', '/daily-research-command/', '/manager-selection/',
                     '/v45/selection/?date=20261113',
                     '/v45/research/?date=20261111&observationDate=20261112&market=A&symbol=000159.SZ',
                     '/v45/review/?date=20261112&sourceDate=20261111&market=A&symbol=000159.SZ&group=nav_pullback']
            assets = set()
            for path in paths:
                with urlopen(origin + path, timeout=5) as response:
                    assert response.status == 200
                    html = response.read().decode()
                    assert '<!doctype html>' in html.lower()
                    assets.update(re.findall(r'(?:src|href)="(/assets/[^\"]+)"', html))
            for asset in assets:
                with urlopen(origin + asset, timeout=5) as response:
                    assert response.status == 200 and response.read()
            for date in days:
                with urlopen(origin + f'/api/v4/preselection-pools?date={date}&limit=300&offset=0', timeout=5) as response:
                    assert response.headers['X-V45-Test-Mode'] == 'FROZEN_SAMPLE_REPLAY_NOT_PRODUCTION'
                    assert json.load(response)['trade_date'] == date
            print(json.dumps({'status': 'FROZEN_REPLAY_HTTP_PASS', 'html_entries': len(paths),
                              'built_assets': len(assets), 'pool_dates': list(days),
                              'browser_rendering': 'NOT_RUN', 'production': 'NOT_RUN'}), flush=True)
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=2)
        return
    print(f'Frozen sample replay only: http://127.0.0.1:{args.port}; Ctrl-C closes it.', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

if __name__ == '__main__':
    main()
