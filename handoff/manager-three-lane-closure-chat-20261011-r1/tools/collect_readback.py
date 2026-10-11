#!/usr/bin/env python3
"""Capture one existing 8873 GET and its raw-byte SHA; never runs an owner."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def day(value: str) -> str:
    parsed = datetime.strptime(value, '%Y%m%d').strftime('%Y%m%d')
    if parsed != value:
        raise argparse.ArgumentTypeError('Use a valid YYYYMMDD date')
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:8873')
    parser.add_argument('--date', type=day, required=True)
    parser.add_argument('--selection-date', type=day)
    parser.add_argument('--announcement-date', type=day)
    parser.add_argument('--view', choices=('auto', 'historical', 'dynamic'), required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    base = urlsplit(args.base_url)
    if (base.scheme != 'http' or base.hostname not in {'127.0.0.1', 'localhost', '::1'}
            or base.port != 8873 or base.username or base.password
            or base.path not in ('', '/') or base.query or base.fragment):
        parser.error('Only the explicitly selected local HTTP 8873 origin is allowed')
    query = {'date': args.date, 'view': args.view}
    for key in ('selection_date', 'announcement_date'):
        if getattr(args, key) is not None:
            query[key] = getattr(args, key)
    url = args.base_url.rstrip('/') + '/api/v4/manager/research/workspace?' + urlencode(query)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    captured = datetime.now(timezone.utc).isoformat()
    error = None
    try:
        response = build_opener(NoRedirect).open(Request(url, headers={'Accept': 'application/json'}), timeout=185)
    except HTTPError as exc:
        response = exc
    except OSError as exc:
        response = None
        error = type(exc).__name__ + ': ' + str(exc)
    status = None
    raw = b''
    if response is not None:
        with response:
            status = response.status
            raw = response.read(64 * 1024 * 1024 + 1)
        if len(raw) > 64 * 1024 * 1024:
            error = 'API_CAPTURE_RESPONSE_EXCEEDS_64_MIB; raw body is incomplete'
    (args.output_dir / 'workspace-response.bin').write_bytes(raw)
    try:
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError('Response must be an object')
    except (ValueError, UnicodeDecodeError):
        value = {}
        error = error or 'API_RESPONSE_JSON_INVALID'
    raw_channels = value.get('daily_channels')
    channels = raw_channels.get('channels', []) if isinstance(raw_channels, dict) else []
    projected = []
    for channel in channels if isinstance(channels, list) else []:
        if isinstance(channel, dict):
            projected.append({key: channel.get(key) for key in
                ('channel', 'owner', 'status', 'candidate_count', 'pending_count',
                 'target_trade_date', 'selection_date', 'announcement_date', 'data_date',
                 'run_id', 'product_sha256', 'input_identity', 'generated_at',
                 'execution_kind', 'gaps', 'natural_run_verified')})
    bindings = value.get('date_bindings')
    binding_match = isinstance(bindings, dict) and bindings.get('plan_date') == args.date
    for key in ('selection_date', 'announcement_date'):
        if getattr(args, key) is not None:
            binding_match = binding_match and bindings.get(key) == getattr(args, key)
    summary = {'schema': 'v4.three_lane_handoff.api_capture.v1', 'captured_at': captured,
        'url': url, 'http_status': status, 'error': error, 'raw_bytes': len(raw),
        'raw_response_sha256': hashlib.sha256(raw).hexdigest(),
        'raw_capture_complete': response is not None and error != 'API_CAPTURE_RESPONSE_EXCEEDS_64_MIB; raw body is incomplete',
        'requested_binding_matches': bool(binding_match), 'date_bindings': bindings,
        'plan_product': value.get('plan_product'), 'read_context': value.get('read_context'),
        'channels': projected, 'owner_executed_by_this_script': False,
        'owner_receipts_independently_rehashed': False,
        'browser_reload_verified': False, 'natural_run_verified_by_this_script': False}
    (args.output_dir / 'api-capture-summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if status == 200 and error is None and binding_match else 2


if __name__ == '__main__':
    raise SystemExit(main())
