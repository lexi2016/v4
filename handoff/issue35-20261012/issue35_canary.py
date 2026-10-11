#!/usr/bin/env python3
"""Issue #35: invoke existing local 8873 owners and verify dated readbacks.

No substitute data producer, BUY path, schedule claim, or trade operation.
The default invocation performs GET only; all owner POSTs are opt-in.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from zoneinfo import ZoneInfo

HK = ZoneInfo('Asia/Hong_Kong')
PREFIX = '/api/v4/manager/research'
MAX_BYTES = 64 * 1024 * 1024
SHA64 = re.compile(r'[a-f0-9]{64}\Z')
RUN32 = re.compile(r'[a-f0-9]{32}\Z')
FLAGS = {'RESEARCH_ONLY': True, 'production_allowed': False,
         'buy_gate_updated': False, 'orders_sent': False}


def day(s: str) -> str:
    try:
        if datetime.strptime(s, '%Y%m%d').strftime('%Y%m%d') != s:
            raise ValueError(s)
    except ValueError as exc:
        raise argparse.ArgumentTypeError('Expected real YYYYMMDD') from exc
    return s


def local_origin(url: str) -> str:
    u = urlsplit(url)
    if (u.scheme != 'http' or u.hostname not in {'localhost', '127.0.0.1', '::1'}
            or u.port != 8873 or u.username or u.password or u.query or u.fragment
            or u.path not in ('', '/')):
        raise ValueError('ORIGIN_INVALID: only loopback HTTP 8873 permitted')
    return url.rstrip('/')


def ensure_us_due(target: str, now: datetime) -> None:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('US_MAPPING_CLOCK_MUST_BE_AWARE')
    if datetime.strptime(day(target), '%Y%m%d').date() > now.astimezone(HK).date():
        raise ValueError('US_MAPPING_FUTURE_TARGET_NOT_ELIGIBLE')


def validate_import_ref(obj: object) -> dict:
    if not isinstance(obj, dict) or set(obj) != {
            'schema_version', 'evidence_run_id', 'handoff_manifest_sha256', 'product_sha256'}:
        raise ValueError('IMPORT_REF_INVALID')
    if (obj['schema_version'] != 'v4.manager_research.announcement_analysis_import_ref.v1'
            or not isinstance(obj['evidence_run_id'], str)
            or RUN32.fullmatch(obj['evidence_run_id']) is None
            or any(not isinstance(obj[k], str) or SHA64.fullmatch(obj[k]) is None
                for k in ('handoff_manifest_sha256', 'product_sha256'))):
        raise ValueError('IMPORT_REF_INVALID')
    return obj


def _dict(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _list(value: object) -> list:
    return value if isinstance(value, list) else []


def _sha(value: object) -> bool:
    return isinstance(value, str) and SHA64.fullmatch(value) is not None


def extract_workspace(value: dict, target: str, publication: str) -> dict:
    """Project raw owner statuses, preserving unknown counts and provenance gaps."""
    value = _dict(value)
    bindings = _dict(value.get('date_bindings'))
    if bindings != {'plan_date': target, 'selection_date': target, 'announcement_date': publication}:
        raise ValueError('BINDINGS_MISMATCH')
    if any(value.get(key) is not flag for key, flag in FLAGS.items()):
        raise ValueError('RESEARCH_ONLY_FLAGS_INVALID')
    channels = _list(_dict(value.get('daily_channels')).get('channels'))
    lanes = {}
    for lane in channels:
        lane = _dict(lane)
        name = lane.get('channel')
        if name not in {'ANNOUNCEMENT', 'OVERSOLD', 'HK_CONNECT'}:
            continue
        if name in lanes:
            raise ValueError('DUPLICATE_DAILY_CHANNEL')
        rows = _list(lane.get('rows'))
        run_id, product_sha = lane.get('run_id'), lane.get('product_sha256')
        lanes[name] = dict(status=lane.get('status'), candidate_count=lane.get('candidate_count'),
            pending_count=lane.get('pending_count'), visible_rows=len(rows),
            run_id=run_id, product_sha256=product_sha,
            owner_identity_present=isinstance(run_id, str) and bool(run_id) and _sha(product_sha),
            input_identity=lane.get('input_identity'), data_date=lane.get('data_date'),
            gaps=lane.get('gaps'),
            rows=[{k:r.get(k) for k in ('symbol', 'name', 'reason', 'selection_status',
                'run_id', 'product_sha256', 'source_refs') if k in r}
                for r in rows if isinstance(r, dict)])
        if name == 'ANNOUNCEMENT':
            research = _dict(lane.get('research_result'))
            lanes[name]['research_result'] = {key:research.get(key) for key in
                ('status', 'validation_status', 'stock_count', 'run_id',
                 'product_sha256', 'gaps')}
    for name in ('ANNOUNCEMENT', 'OVERSOLD', 'HK_CONNECT'):
        lanes.setdefault(name, dict(status='MISSING', candidate_count=None, visible_rows=0,
            run_id=None, product_sha256=None, owner_identity_present=False,
            gaps=['DAILY_CHANNEL_NOT_PRESENT'], rows=[]))

    attention = _dict(value.get('us_market_attention'))
    daily = _dict(_dict(value.get('us_mapping_research')).get('daily_run'))
    daily_ok = (daily.get('status') in {'COMPLETED', 'VALID_EMPTY'}
        and isinstance(daily.get('run_id'), str) and bool(daily['run_id'])
        and _sha(daily.get('artifact_sha256'))
        and _dict(daily.get('run_readback')).get('status') == 'VERIFIED')
    us = dict(raw_status=attention.get('status'),
        expected_us_session=attention.get('expected_us_session'),
        raw_industry_up_count=len(_list(attention.get('raw_industry_up'))),
        raw_individual_up_count=len(_list(attention.get('raw_individual_up'))),
        daily_run_status=daily.get('status'), daily_run_id=daily.get('run_id'),
        daily_artifact_sha256=daily.get('artifact_sha256'),
        daily_us_session=daily.get('us_session_date'),
        daily_gaps=daily.get('gaps'), verified_daily=daily_ok,
        matching_rows=[{k:r.get(k) for k in ('us_symbol', 'hk_symbol', 'change_pct',
            'relation_type', 'reason', 'relation_identity') if k in r}
            for r in _list(daily.get('matches')) if isinstance(r, dict)])
    plan = _dict(value.get('plan_product'))
    plan_view = {k:plan.get(k) for k in ('status', 'consumed', 'run_id', 'sha256',
        'execution_kind', 'input_identity_diagnostics')}
    blockers = []
    if not (plan.get('status') == 'CURRENT' and plan.get('consumed') is True
            and isinstance(plan.get('run_id'), str) and _sha(plan.get('sha256'))):
        blockers.append('SAVED_PLAN_NOT_CURRENT')
    if lanes['ANNOUNCEMENT']['status'] not in {'READY', 'READY_EMPTY'}:
        blockers.append('ANNOUNCEMENT_OWNER_NOT_VERIFIED')
    if not lanes['OVERSOLD'].get('owner_identity_present'):
        blockers.append('OVERSOLD_OWNER_IDENTITY_MISSING')
    if (lanes['OVERSOLD']['status'] not in {'READY', 'READY_EMPTY'}
            or _dict(_dict(value.get('market_screen')).get('authority')).get('status') != 'VERIFIED'):
        blockers.append('OVERSOLD_SOURCE_NOT_COMPLETE')
    if not daily_ok:
        blockers.append('US_DAILY_NOT_VERIFIED')
    # Real source receipt rehash, natural schedule and browser DOM verification
    # require separate Mac owner/reviewer evidence, NOT this HTTP client.
    return dict(target_trade_date=target, announcement_date=publication,
        plan=plan_view, lanes=lanes, us=us,
        input_identity=value.get('input_identity'),
        blocking_codes=sorted(set(blockers)), business_complete=False,
        owner_receipts_independently_rehashed=False,
        browser_reload_verified=False, natural_run_verified=False)


def verify_two_auto(first: dict, second: dict, target: str, publication: str) -> dict:
    a = extract_workspace(first, target, publication)
    b = extract_workspace(second, target, publication)
    def identity(projection: dict) -> tuple:
        p = projection['plan']
        return (p.get('status'), p.get('consumed'), p.get('run_id'),
            p.get('sha256'), projection.get('input_identity'),
            tuple((key, projection['lanes'][key]['status'],
                projection['lanes'][key].get('candidate_count'))
                for key in ('ANNOUNCEMENT', 'OVERSOLD', 'HK_CONNECT')),
            projection['us']['daily_run_status'], projection['us']['daily_artifact_sha256'])
    return {'stable': a['plan'].get('status') == 'CURRENT'
        and a['plan'].get('consumed') is True and identity(a) == identity(b),
        'first_run_id': a['plan'].get('run_id'),
        'second_run_id': b['plan'].get('run_id'),
        'first_sha256': a['plan'].get('sha256'),
        'second_sha256': b['plan'].get('sha256')}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request_local(origin: str, route: str, *, params: dict | None = None,
                  method: str = 'GET', body: dict | None = None) -> tuple[dict, dict]:
    url = origin + PREFIX + route + ('?' + urlencode(params) if params else '')
    payload = json.dumps(body, separators=(',', ':')).encode() if body is not None else None
    headers = {'Accept': 'application/json', 'Origin': origin}
    if payload is not None:
        headers['Content-Type'] = 'application/json'
    req = Request(url, data=payload, headers=headers, method=method)
    opener = build_opener(ProxyHandler({}), NoRedirect())
    try:
        response = opener.open(req, timeout=185)
    except HTTPError as exc:
        response = exc
    with response:
        code = response.status
        raw = response.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('HTTP_BODY_EXCEEDS_64_MIB')
    try:
        parsed = json.loads(raw)
    except (UnicodeDecodeError, ValueError):
        parsed = None
    receipt = dict(method=method, route=route, params=params, http_status=code,
        raw_bytes=len(raw), http_raw_sha256=hashlib.sha256(raw).hexdigest(),
        json_object=isinstance(parsed, dict))
    if code != 200 or not isinstance(parsed, dict):
        raise ValueError('HTTP_READBACK_FAILED:' + json.dumps(receipt, sort_keys=True))
    return parsed, receipt


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base-url', default='http://127.0.0.1:8873')
    p.add_argument('--target', type=day, default='20261012')
    p.add_argument('--announcement-date', type=day, default='20261009')
    p.add_argument('--output-dir', type=Path, required=True)
    p.add_argument('--refresh-catalog', action='store_true',
                   help='Invoke existing Eastmoney date catalog owner (no judgment)')
    p.add_argument('--import-refs', type=Path,
                   help='Existing registered owner references only; no stock list')
    p.add_argument('--refresh-us', action='store_true',
                   help='Run original US mapping owner only when target day has arrived')
    p.add_argument('--refresh-plan', action='store_true',
                   help='Run original research plan owner, not a trade or scheduled run')
    args = p.parse_args(argv)
    origin = local_origin(args.base_url)
    if args.refresh_us:
        ensure_us_due(args.target, datetime.now(HK))
    envelope = None
    if args.import_refs is not None:
        envelope = validate_import_ref(json.loads(args.import_refs.read_text(encoding='utf-8')))
    params = {'date': args.target, 'selection_date': args.target,
              'announcement_date': args.announcement_date}
    # Exclusive output: never alter user store, existing evidence or release.
    args.output_dir.mkdir(mode=0o700, parents=False, exist_ok=False)
    records = []
    def call(route: str, *, method: str = 'GET', params: dict | None = None,
             body: dict | None = None) -> dict:
        value, receipt = request_local(origin, route, params=params, method=method, body=body)
        records.append(receipt)
        return value
    try:
        baseline = call('/workspace', params={**params, 'view': 'auto'})
        extract_workspace(baseline, args.target, args.announcement_date)
        if args.refresh_catalog:
            call('/announcements/refresh', method='POST', params={
                'date': args.target, 'source_scope': 'EASTMONEY_HK_DATE_CATALOG',
                'publication_date': args.announcement_date})
        if envelope is not None:
            call('/announcements/analysis/import', method='POST', body=envelope)
        if args.refresh_us:
            call('/workspace/us-mapping/refresh', method='POST', params={'date': args.target})
        if args.refresh_plan:
            call('/workspace/refresh', method='POST', params=params)
        first = call('/workspace', params={**params, 'view': 'auto'})
        second = call('/workspace', params={**params, 'view': 'auto'})
        dynamic = call('/workspace', params={**params, 'view': 'dynamic'})
        analysis = call('/announcements/analysis', params={
            'date': args.target, 'publication_date': args.announcement_date})
        receipt = dict(issue='lexi2016/v4#35', target_trade_date=args.target,
            publication_date=args.announcement_date,
            captured_at=datetime.now(HK).isoformat(), http_receipts=records,
            saved_plan_repeated_readback=verify_two_auto(first, second, args.target, args.announcement_date),
            auto=extract_workspace(second, args.target, args.announcement_date),
            dynamic=extract_workspace(dynamic, args.target, args.announcement_date),
            announcement_owner_api=dict(status=analysis.get('status'),
                publication_date=analysis.get('publication_date'),
                owner_receipt_readback_status=analysis.get('owner_receipt_readback_status'),
                consumption_validation=_dict(analysis.get('consumption_validation')).get('status')),
            owner_posts_executed_by_this_script=any(r['method'] == 'POST' for r in records),
            natural_run_verified=False, browser_reload_verified=False,
            owner_receipts_independently_rehashed=False)
        (args.output_dir/'issue35-receipt.json').write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(dict(output=str(args.output_dir/'issue35-receipt.json'),
            auto_plan=receipt['auto']['plan'],
            stability=receipt['saved_plan_repeated_readback'],
            auto_blockers=receipt['auto']['blocking_codes'],
            dynamic_blockers=receipt['dynamic']['blocking_codes'],
            raw_us_status=receipt['dynamic']['us']['raw_status'],
            daily_us_status=receipt['dynamic']['us']['daily_run_status']),
            ensure_ascii=False, indent=2))
        return 0 if receipt['saved_plan_repeated_readback']['stable'] else 3
    except (OSError, ValueError, TimeoutError) as exc:
        (args.output_dir/'issue35-error.json').write_text(json.dumps(dict(
            issue='lexi2016/v4#35', error_type=type(exc).__name__, error=str(exc),
            http_receipts=records), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(type(exc).__name__ + ': ' + str(exc))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
