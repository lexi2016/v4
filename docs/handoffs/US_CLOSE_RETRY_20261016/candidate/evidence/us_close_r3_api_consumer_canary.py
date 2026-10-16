from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

LIVE_DATA = Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/state/data')
LIVE_PAYLOAD_REL = Path('research/peripherals/20261016/external_finance.json')
LIVE_RECEIPT_REL = Path('receipts/research/peripherals/20261016/external_finance.json')
LIVE_MANIFEST_REL = Path('research/peripherals/manifest.json')
EXPECTED_PREIMAGE_SHA256 = '3c395a48f7d5d52f49e52cbbe77859bde661719b9bc01dfc1664e53a1f01c8c3'
EXPECTED_PREIMAGE_RECEIPT_SHA256 = '22611d26644a4259f4c22331ea46f911d51bcfe4891679acdc3c46dff3fbd6fc'
API_APP_ROOT = Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/zsxq-pdf-ocr-api-20261016-r4/app')
CONFIG_PATH = Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/config/manager-workbench-v7.json')
PYTHON = Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python')
FROZEN_RECOVERY_NOW = datetime.fromisoformat('2026-10-16T00:35:00-04:00')


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def run_actual_api_consumer(data_root: Path) -> dict:
    code = r'''
import hashlib, json, sys
from pathlib import Path
from apps.api.v35_api import research_lane_router
from infrastructure.research_peripheral_store import ResearchPeripheralStore
store = ResearchPeripheralStore(Path(sys.argv[1]))
row = research_lane_router._project_global_industries(store=store, research_date="20261016")
module_path = Path(research_lane_router.__file__).resolve()
print(json.dumps({"api_module_path": str(module_path), "api_module_sha256": hashlib.sha256(module_path.read_bytes()).hexdigest(), **{key: row.get(key) for key in (
    "status", "cannot_confirm", "capture_id", "run_id", "captured_at",
    "bound_capture_captured_at", "source_date", "artifact_trade_date",
    "requested_symbol_count", "available_symbol_count", "production_allowed",
    "buy_gate_updated", "orders_sent",
) }}, sort_keys=True))
'''
    env = dict(os.environ)
    env['PYTHONPATH'] = str(API_APP_ROOT)
    completed = subprocess.run(
        [str(PYTHON), '-B', '-c', code, str(data_root)],
        cwd=API_APP_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise SystemExit(
            f'actual API consumer failed rc={completed.returncode}: '
            f'{completed.stderr[-4000:]}'
        )
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if len(lines) != 1:
        raise SystemExit(f'actual API consumer output was not one JSON record: {completed.stdout[-2000:]}')
    return json.loads(lines[0])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--app-root', type=Path, required=True)
    parser.add_argument('--expect', choices=('ambiguous', 'bound'), required=True)
    args = parser.parse_args()
    app_root = args.app_root.resolve()
    release_root = app_root.parent
    manifest_path = release_root / 'release-manifest.json'
    manifest_raw = manifest_path.read_bytes()
    manifest_sha = sha256_bytes(manifest_raw)
    manifest = json.loads(manifest_raw)
    release_id = manifest['candidate']['release_id']

    payload_path = LIVE_DATA / LIVE_PAYLOAD_REL
    receipt_path = LIVE_DATA / LIVE_RECEIPT_REL
    live_manifest_path = LIVE_DATA / LIVE_MANIFEST_REL
    preimage_bytes = payload_path.read_bytes()
    receipt_bytes = receipt_path.read_bytes()
    preimage_sha = sha256_bytes(preimage_bytes)
    receipt_sha = sha256_bytes(receipt_bytes)
    if preimage_sha != EXPECTED_PREIMAGE_SHA256 or receipt_sha != EXPECTED_PREIMAGE_RECEIPT_SHA256:
        raise SystemExit('real 48-symbol preimage or receipt changed; no canary was run')
    preimage = json.loads(preimage_bytes)
    pre_snapshot = preimage.get('market_snapshot') or {}
    prior_capture_ids = {
        row.get('capture_id') for row in preimage.get('us_session_captures') or []
        if isinstance(row, dict) and isinstance(row.get('capture_id'), str)
    }
    if (
        len(pre_snapshot.get('quotes') or []) != 48
        or pre_snapshot.get('requested_symbol_count') != 48
        or pre_snapshot.get('available_symbol_count') != 48
        or len(prior_capture_ids) != 2
        or pre_snapshot.get('capture_id') is not None
    ):
        raise SystemExit('current pinned input is not the expected 48/48 two-capture ambiguous preimage')
    live_manifest = json.loads(live_manifest_path.read_text(encoding='utf-8'))
    if live_manifest.get(LIVE_PAYLOAD_REL.as_posix()) != preimage_sha:
        raise SystemExit('live data manifest does not pin the exact 48/48 input')
    if not CONFIG_PATH.is_file() or not API_APP_ROOT.is_dir() or not PYTHON.is_file():
        raise SystemExit('required owner config, API app, or runtime is unavailable')

    for key, value in {
        'V35_APP_ROOT': str(app_root),
        'V35_RELEASE_ID': release_id,
        'V35_RELEASE_MANIFEST_PATH': str(manifest_path),
        'V35_RELEASE_MANIFEST_SHA256': manifest_sha,
        'V4_MANAGER_WORKBENCH_CONFIG_PATH': str(CONFIG_PATH),
        'HTTP_PROXY': 'http://127.0.0.1:7897',
        'HTTPS_PROXY': 'http://127.0.0.1:7897',
        'ALL_PROXY': 'http://127.0.0.1:7897',
        'http_proxy': 'http://127.0.0.1:7897',
        'https_proxy': 'http://127.0.0.1:7897',
        'all_proxy': 'http://127.0.0.1:7897',
        'NO_PROXY': '127.0.0.1,localhost,::1',
        'no_proxy': '127.0.0.1,localhost,::1',
    }.items():
        os.environ[key] = value

    os.chdir(app_root)
    sys.path.insert(0, str(app_root))
    from infrastructure.http_transport import FetchResult, ProxyAwareHTTPTransport
    from infrastructure.research_peripheral_store import ResearchPeripheralStore
    import ops.us_market_digest as digest

    contract = digest._configured_us_universe_contract()
    symbols = list(contract['symbols'])
    if contract.get('version') != 'US_MAPPING_UNIVERSE_CONTRACT_V3' or len(symbols) != 48:
        raise SystemExit('candidate did not load owner-configured V3/48 contract')

    quote_response_sha = None
    request_urls: list[str] = []

    def synthetic_fetch(self, url, *, timeout=None, **kwargs):
        nonlocal quote_response_sha
        request_urls.append(url)
        if 'qt.gtimg.cn' in url:
            records = []
            for index, symbol in enumerate(symbols):
                fields = [''] * 31
                fields[1:5] = [symbol, symbol, '111', '100']
                fields[30] = '20261015160001' if index % 2 == 0 else '20261015160531'
                records.append(f'v_us{symbol}="' + '~'.join(fields) + '";')
            body = ''.join(records).encode()
            quote_response_sha = sha256_bytes(body)
        else:
            key = hashlib.sha256(url.encode()).hexdigest()[:12]
            body = (
                f'<rss><channel><item><title>R3 API identity canary {key}</title>'
                f'<link>https://example.test/us-close-r3-canary/{key}</link>'
                '<pubDate>Thu, 15 Oct 2026 20:00:00 GMT</pubDate>'
                '<source>synthetic local canary</source></item></channel></rss>'
            ).encode()
        return FetchResult(body, {
            'status': 'READY', 'source': 'SYNTHETIC_LOCAL_CANARY',
            'source_url': url, 'response_sha256': sha256_bytes(body),
            'production_allowed': False, 'buy_gate_updated': False, 'orders_sent': False,
        })

    with tempfile.TemporaryDirectory(prefix='us-close-r3-api-canary-', dir=Path(__file__).resolve().parent) as temporary:
        temp_root = Path(temporary) / 'data'
        (temp_root / LIVE_PAYLOAD_REL).parent.mkdir(parents=True)
        (temp_root / LIVE_RECEIPT_REL).parent.mkdir(parents=True)
        (temp_root / LIVE_PAYLOAD_REL).write_bytes(preimage_bytes)
        (temp_root / LIVE_RECEIPT_REL).write_bytes(receipt_bytes)
        (temp_root / LIVE_MANIFEST_REL).parent.mkdir(parents=True, exist_ok=True)
        (temp_root / LIVE_MANIFEST_REL).write_text(
            json.dumps({LIVE_PAYLOAD_REL.as_posix(): preimage_sha}, sort_keys=True) + '\n',
            encoding='utf-8',
        )
        producer_store = ResearchPeripheralStore(temp_root)
        if producer_store.read_exact('20261016', 'external_finance') is None:
            raise SystemExit('candidate store rejected copied exact 48/48 preimage')

        original_now = digest._capture_now
        original_fetch = ProxyAwareHTTPTransport.fetch
        digest._capture_now = lambda value=None: original_now(value) if value is not None else FROZEN_RECOVERY_NOW
        ProxyAwareHTTPTransport.fetch = synthetic_fetch
        stdout, stderr = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                exit_code = digest.main([
                    '--data-root', str(temp_root),
                    '--trade-date', '20261016',
                    '--us-session-date', '20261015',
                    '--capture-phase', 'POST_CLOSE',
                    '--allow-late-post-close',
                    '--manual-late-recovery',
                ])
        finally:
            digest._capture_now = original_now
            ProxyAwareHTTPTransport.fetch = original_fetch

        cli_text = stdout.getvalue().strip()
        cli_result = json.loads(cli_text) if cli_text else None
        if exit_code != 0 or not cli_result or cli_result.get('status') != 'READY':
            raise SystemExit(f'candidate full producer did not complete: rc={exit_code} result={cli_result} stderr={stderr.getvalue()[-2000:]}')
        merged = producer_store.read_exact('20261016', 'external_finance')
        if merged is None or sha256_bytes((temp_root / LIVE_PAYLOAD_REL).read_bytes()) == preimage_sha:
            raise SystemExit('candidate full producer did not replace only the temp target')
        snapshot = merged.get('market_snapshot') or {}
        captures = merged.get('us_session_captures') or []
        if (
            snapshot.get('status') != 'READY'
            or len(snapshot.get('quotes') or []) != 48
            or snapshot.get('requested_symbol_count') != 48
            or snapshot.get('available_symbol_count') != 48
            or len(snapshot.get('rows') or []) != 24
            or not prior_capture_ids.issubset({row.get('capture_id') for row in captures if isinstance(row, dict)})
        ):
            raise SystemExit('candidate full producer lost 48/48 coverage, rows, or prior capture metadata')
        archive = temp_root / 'research/peripherals/history/20261016/external_finance' / f'{preimage_sha}.json'
        if not archive.is_file() or archive.read_bytes() != preimage_bytes:
            raise SystemExit('exact 48/48 preimage was not preserved in hash-addressed history')

        api_result = run_actual_api_consumer(temp_root)
        api_manifest_path = API_APP_ROOT.parent / 'release-manifest.json'
        api_manifest = json.loads(api_manifest_path.read_text(encoding='utf-8'))
        if not str(Path(api_result.get('api_module_path') or '')).startswith(str(API_APP_ROOT) + os.sep):
            raise SystemExit('actual API consumer module did not resolve inside the pinned API app root')
        if args.expect == 'ambiguous':
            if api_result.get('status') != 'CANNOT_CONFIRM' or 'MARKET_SNAPSHOT_CAPTURE_IDENTITY_AMBIGUOUS_OR_UNBOUND' not in (api_result.get('cannot_confirm') or []):
                raise SystemExit(f'pre-identity baseline expected ambiguity, got actual API result: {api_result}')
            if snapshot.get('capture_id') is not None or snapshot.get('run_id') is not None:
                raise SystemExit('R1 baseline unexpectedly bound snapshot capture identity')
        else:
            if api_result.get('status') not in {'READY', 'PARTIAL'}:
                raise SystemExit(f'R3 expected API projection to bind, got: {api_result}')
            if (
                not isinstance(snapshot.get('capture_id'), str)
                or api_result.get('capture_id') != snapshot.get('capture_id')
                or api_result.get('run_id') != snapshot.get('run_id')
                or api_result.get('captured_at') != snapshot.get('captured_at')
                or api_result.get('bound_capture_captured_at') != snapshot.get('captured_at')
            ):
                raise SystemExit(f'actual API consumer did not bind to the snapshot-owned capture: {api_result}')
            if len(captures) != len(prior_capture_ids) + 1:
                raise SystemExit('R3 did not preserve both prior captures and add one synthetic late capture')

        result = {
            'schema_version': 'us_close_r3_api_consumer_canary.v1',
            'expect': args.expect,
            'candidate_app_root': str(app_root),
            'candidate_release_id': release_id,
            'candidate_manifest_sha256': manifest_sha,
            'candidate_phase_merge_sha256': sha256_bytes((app_root / 'ops/_us_market_digest_parts/phase_merge.py').read_bytes()),
            'api_app_root': str(API_APP_ROOT),
            'api_release_id': (api_manifest.get('candidate') or {}).get('release_id'),
            'api_release_manifest_sha256': sha256_bytes(api_manifest_path.read_bytes()),
            'api_consumer_module_path': api_result.get('api_module_path'),
            'api_consumer_module_sha256': api_result.get('api_module_sha256'),
            'real_preimage_payload_sha256': preimage_sha,
            'real_preimage_receipt_sha256': receipt_sha,
            'real_preimage_snapshot_captured_at': pre_snapshot.get('captured_at'),
            'real_preimage_capture_ids': sorted(prior_capture_ids),
            'owner_universe_contract_version': contract.get('version'),
            'owner_universe_symbol_count': len(symbols),
            'synthetic_recovery_timestamp': FROZEN_RECOVERY_NOW.isoformat(),
            'synthetic_quote_response_sha256': quote_response_sha,
            'synthetic_request_count': len(request_urls),
            'full_producer_exit_code': exit_code,
            'full_producer_result': cli_result,
            'actual_api_consumer': api_result,
            'temp_only': True,
            'network_requests': 'All producer HTTP responses were synthetic in-process transport; API read was local temp-store access.',
            'preserved_preimage_history_path': f'research/peripherals/history/20261016/external_finance/{preimage_sha}.json',
            'preserved_preimage_history_sha256': sha256_bytes(archive.read_bytes()),
            'merged_snapshot_capture_identity': {key: snapshot.get(key) for key in ('capture_id', 'run_id', 'captured_at')},
            'merged_capture_count': len(captures),
            'research_safety': {'production_allowed': False, 'buy_gate_updated': False, 'orders_sent': False},
        }
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
