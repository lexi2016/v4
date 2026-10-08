"""Regression fixtures for PR3's pinned boundary defects; no real prices or OCR.

Filesystem/ZIP/import/archive/API checks exercise actual implementations. Only
performance panel-probe and loaded scheduler discovery IO are replaced with
explicit synthetic dictionaries, since they require the owner's local runtime.
Those tests are numerical/control-flow tests, NOT Parquet/market-data acceptance.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[1] / 'scripts'))
# The export uses sibling source/wechat and source/v4_app. Local integration
# can point at the real V4 root without relocating or stubbing its modules.
V4_ROOT = Path(os.environ.get('WECHAT_REVIEW_V4_ROOT', str(HERE.parents[2] / 'v4_app'))).expanduser()
if not (V4_ROOT / 'infrastructure/wechat_research_archive.py').is_file():
    raise RuntimeError('V4 source missing: set WECHAT_REVIEW_V4_ROOT to the actual V4 root')
sys.path.insert(0, str(V4_ROOT))
import wechat_chat_handoff as handoff
import wechat_yesterday_performance as perf
from test_wechat_chat_handoff import _make_run
from infrastructure.wechat_research_archive import (
    ArchiveError, MENTION_COLUMNS, WechatResearchArchive, _parse_mentions,
)
from ops.index_wechat_research import register_return

FLAGS = {'production_allowed': False, 'buy_gate_updated': False, 'orders_sent': False}


def sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def write_json(path: Path, obj: object) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def csv_bytes(columns, rows) -> bytes:
    out = io.StringIO(newline='')
    writer = csv.DictWriter(out, fieldnames=columns)
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue().encode('utf-8')


def make_package(root: Path, package_id: str, date='20260927', count=0):
    root.mkdir(parents=True)
    run = _make_run(root, count=count)
    intake_path = run / 'wechat_article_intake_summary.json'
    intake = json.loads(intake_path.read_text())
    stamp = datetime.fromisoformat(f'{date[:4]}-{date[4:6]}-{date[6:]}T22:20:20+08:00')
    intake.update(article_date=date, raw_publish_time=str(int(stamp.timestamp())))
    write_json(intake_path, intake)
    out = root / 'frozen'
    receipt = handoff.package_run(run, out, package_id)
    return run, out, receipt


def make_archive(root: Path, *, rows=None, date='20260927'):
    run, frozen, package = make_package(root, 'review_prior', date=date)
    returned = root / 'returned'
    returned.mkdir()
    if rows is None:
        rows = [dict(market='A', code='000001.SZ', name='Fixture A', source_index='BODY',
                     mapping_status='NAME_RESOLVED', source_named_or_derived='SOURCE_NAMED',
                     claim_context='synthetic unit fixture', entity_id='issuer-a',
                     source_name='Fixture A', listing_origin='NAME_RESOLVED')]
    coverage = csv_bytes(
        'source_index,event,subject,claim,date,number,unit,source_grade,uncertainty,original_checked,original_scope,text_read'.split(','),
        [dict(source_index='BODY', event='EVENT', subject='fixture', claim='read fixture BODY',
              date=date, number='', unit='', source_grade='UNKNOWN', uncertainty='synthetic fixture',
              original_checked='false', original_scope='NOT_APPLICABLE', text_read='true')])
    report_header = {k: package[k] for k in ('package_id', 'input_digest')}
    report_header['return_id'] = 'review_return_01'
    payloads = {
        'report.md': ('<!-- wechat-return: ' + json.dumps(report_header) + ' -->\n# fixture report\n').encode(),
        'coverage.csv': coverage,
        'mentions.csv': csv_bytes(MENTION_COLUMNS, rows),
        'unmapped.csv': b'name,reason,source_index\n',
    }
    summary = {
        'schema_version': 2, 'review_contract_version': package['review_contract_version'],
        'event_dispositions': {'BODY': 'HOLD'}, 'url': package['original_url'],
        'package_id': package['package_id'], 'input_digest': package['input_digest'],
        'manifest_sha256': package['manifest_sha256'], 'return_id': report_header['return_id'],
        'reading_mode': 'OCR_RISK_REVIEW', 'article_date': date, 'image_count': 0,
        'coverage_counts': {'total': 1, 'EVENT': 1, 'NO_EVENT': 0, 'UNREADABLE': 0},
        'mentions_counts': {
            'total': len(rows), **{m: sum(r['market'] == m for r in rows) for m in ('A', 'BJ', 'HK')},
            'entities': len({r['entity_id'] for r in rows}),
            'source_named_entities': len({r['entity_id'] for r in rows if r['source_named_or_derived'] == 'SOURCE_NAMED'}),
            'supplemental_listing_rows': sum(r['listing_origin'] == 'SUPPLEMENTAL_LISTING' for r in rows),
        },
        'status': 'PARTIAL', 'missing_inputs': [],
        'artifact_sha256': {name: sha(data) for name, data in payloads.items()}, **FLAGS,
    }
    for name, data in payloads.items():
        (returned / name).write_bytes(data)
    write_json(returned / 'summary.json', summary)
    kwargs = dict(source_run_value=run, package_id_value=package['package_id'],
                  package_zip_value=frozen / package['zip']['path'], package_sha_value=package['zip']['sha256'],
                  report_value=returned / 'report.md', coverage_value=returned / 'coverage.csv',
                  mentions_value=returned / 'mentions.csv', unmapped_value=returned / 'unmapped.csv',
                  summary_value=returned / 'summary.json', out_dir_value=root / 'archive')
    receipt = handoff.import_chat_return(**kwargs)
    assert receipt['status'] == 'REPORT_AND_STRUCTURED_ARCHIVED'
    return root / 'archive', kwargs, receipt


def make_performance_inputs(root: Path):
    rows = []
    for n in (1, 2):
        rows.append(dict(market='HK', code=f'{n:05d}.HK', name=f'Fixture HK {n}', source_index='BODY',
                         mapping_status='NAME_RESOLVED', source_named_or_derived='SOURCE_NAMED',
                         claim_context='synthetic unit fixture', entity_id=f'issuer-hk-{n}',
                         source_name=f'Fixture HK {n}', listing_origin='NAME_RESOLVED'))
    article, _, _ = make_archive(root / 'prior', rows=rows)
    _, frozen, _ = make_package(root / 'current', 'review_current', date='20260928')
    calendar = root / 'calendar.json'
    write_json(calendar, {'schema_version': 'v3_5.market_calendar_2026.v1', 'year': 2026,
                         'timezone': 'Asia/Shanghai', 'official_sources': [
                             {'market': 'a_share'}, {'market': 'hk_securities'}],
                         'markets': {m: {'holiday_periods': [], 'half_days': []}
                                     for m in ('a_share', 'hk_securities')}})
    return dict(prior_article_dir=article, current_package_receipt=frozen / 'PACKAGE_RECEIPT.json',
                observation_date='20260928', runtime_config_evidence=root / 'synthetic-runtime.json',
                calendar_json=calendar)


@pytest.mark.parametrize('extra_url', ['https://mmbiz.qpic.cn/fixture/unlisted', 'https://mmbiz.qpic.cn/fixture/1'])
def test_freeze_rejects_unmanifested_body_image(tmp_path, extra_url):
    root = tmp_path / 'inputs'
    root.mkdir()
    run = _make_run(root, count=1)
    html = run / 'wechat_article_raw.html'
    html.write_text(html.read_text().replace('</div>', f'<img data-src="{extra_url}" /></div>'))
    with pytest.raises(handoff.HandoffError):
        handoff.package_run(run, tmp_path / 'out', 'no_lost_image')
    assert not list((tmp_path / 'out').glob('*.zip'))


@pytest.mark.parametrize('role', ['report', 'coverage', 'mentions', 'unmapped', 'summary'])
def test_repeat_import_rebinds_corrupt_archive_without_overwrite(tmp_path, role):
    archive, kwargs, first = make_archive(tmp_path / 'case')
    prior_receipt_bytes = (archive / 'IMPORT_RECEIPT.json').read_bytes()
    old = archive / first['archived_files'][role]['archived_filename']
    old.write_bytes(b'corrupted historical bytes')
    second = handoff.import_chat_return(**kwargs)
    ref = second['archived_files'][role]
    assert sha((archive / ref['archived_filename']).read_bytes()) == ref['sha256']
    assert old.read_bytes() == b'corrupted historical bytes'
    assert (archive / 'IMPORT_RECEIPT.json').read_bytes() == prior_receipt_bytes
    assert second['archived_files'][role]['archived_filename'] != first['archived_files'][role]['archived_filename']
    third = handoff.import_chat_return(**kwargs)
    assert third == second


@pytest.mark.parametrize('status', ['RESEARCH_ONLY', 'WATCH_ONLY', 'NO_BUY_GATE'])
def test_boundary_labels_are_not_research_completion_status(tmp_path, status):
    _, kwargs, _ = make_archive(tmp_path / 'case')
    path = kwargs['summary_value']
    data = json.loads(path.read_text())
    data['status'] = status
    write_json(path, data)
    receipt = handoff.import_chat_return(**kwargs)
    assert receipt['status'] == 'REPORT_AND_STRUCTURED_INVALID'
    assert 'summary.json' in receipt['invalid_artifacts']


def test_prior_summary_bytes_must_match_archive_receipt(tmp_path):
    archive, _, _ = make_archive(tmp_path / 'case')
    assert perf._load_prior_article_mentions(archive)['chat_report_status'] == 'PARTIAL'
    path = archive / 'summary.json'
    obj = json.loads(path.read_text())
    obj['status'] = 'COMPLETE_WITH_ALL_SOURCES'
    write_json(path, obj)
    with pytest.raises(perf.PerformanceAppendixError):
        perf._load_prior_article_mentions(archive)


@pytest.mark.parametrize('field,value', [('package_id', 'other_package'), ('input_digest', 'a' * 64),
                                        ('manifest_sha256', 'b' * 64), ('original_url', 'https://mp.weixin.qq.com/s/other')])
def test_current_receipt_must_match_real_frozen_zip(tmp_path, field, value):
    _, out, _ = make_package(tmp_path / 'case', 'current')
    path = out / 'PACKAGE_RECEIPT.json'
    data = json.loads(path.read_text())
    data[field] = value
    write_json(path, data)
    with pytest.raises(perf.PerformanceAppendixError):
        perf._load_current_package_binding(path)


def test_present_non_zip_bytes_do_not_establish_frozen_identity(tmp_path):
    _, out, receipt = make_package(tmp_path / 'case', 'current')
    package = out / receipt['zip']['path']
    package.write_bytes(b'not a ZIP but matching a declared digest')
    receipt['zip'].update(sha256=sha(package.read_bytes()), bytes=package.stat().st_size)
    write_json(out / 'PACKAGE_RECEIPT.json', receipt)
    with pytest.raises(perf.PerformanceAppendixError):
        perf._load_current_package_binding(out / 'PACKAGE_RECEIPT.json')


@pytest.mark.parametrize('bad', [0.0, None, float('nan'), float('inf'), True])
def test_invalid_hk_denominator_preserves_all_listings(tmp_path, bad):
    args = make_performance_inputs(tmp_path)
    probe = dict(current_receipt_path='synthetic', current_receipt_sha256='a' * 64,
                 current_manifest_sha256='b' * 64, current_panel_sha256='c' * 64,
                 current_receipt_status='READY', previous_receipt_status='READY',
                 native_price_transform='NONE', status='SYNTHETIC_UNIT_PROBE')
    current = {'HK.00001': {'close': 11, 'pre_close': bad, 'pct_chg': 0},
               'HK.00002': {'close': 12, 'pre_close': 10, 'pct_chg': 20}}
    prior = {'HK.00001': {'close': bad}, 'HK.00002': {'close': 10}}
    with patch.object(perf, '_load_runtime_config_evidence', return_value={}), \
         patch.object(perf, '_build_hk_panel_probe', return_value=(probe, current, prior, prior)):
        result = perf.build_prior_mentions_performance_appendix(**args)
    assert len(result['rows']) == 2
    first, second = result['rows']
    assert first['status'] == 'CANNOT_CONFIRM'
    assert first['pct_chg_close'] is None
    assert second['status'] == 'OBSERVED_RAW_CLOSE_TO_PRIOR_SESSION_CLOSE'
    assert second['pct_chg_close'] == 20
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize('variant', [False, True])
def test_immutable_appendix_rejects_dangling_symlinks(tmp_path, variant):
    out = tmp_path / 'out'
    out.mkdir()
    name, data = 'performance_appendix.md', b'research appendix'
    target = tmp_path / 'outside.txt'
    if variant:
        (out / name).write_bytes(b'old version')
        path = out / f'performance_appendix.{sha(data)[:12]}.md'
    else:
        path = out / name
    path.symlink_to(target)
    with pytest.raises(perf.PerformanceAppendixError):
        perf._write_immutable_version(out, name, data)
    assert not target.exists()
    assert path.is_symlink()


def test_immutable_appendix_preserves_real_versions(tmp_path):
    first = perf._write_immutable_version(tmp_path, 'performance_appendix.md', b'first')
    assert perf._write_immutable_version(tmp_path, 'performance_appendix.md', b'first') == first
    second = perf._write_immutable_version(tmp_path, 'performance_appendix.md', b'second')
    assert first[0] != second[0]
    assert (tmp_path / first[0]).read_bytes() == b'first'
    assert (tmp_path / second[0]).read_bytes() == b'second'


def test_closed_market_is_not_all_observed():
    result = perf._count_market_rows([dict(market='A', status='NO_TRADING_SESSION')], 'A', {})
    assert result['status'] == 'NO_TRADING_SESSION'
    assert result['observed_listings'] == 0


def test_same_day_article_is_not_a_prior_article(tmp_path):
    args = make_performance_inputs(tmp_path)
    args['observation_date'] = '20260927'
    with pytest.raises(perf.PerformanceAppendixError):
        perf.build_prior_mentions_performance_appendix(**args)


@pytest.mark.parametrize('empty', [False, True])
def test_v4_accepts_valid_body_or_empty_mentions_and_serves_raw_bytes(tmp_path, empty):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from apps.api.v35_api.wechat_research_router import create_wechat_research_router
    archive, _, receipt = make_archive(tmp_path / 'case', rows=[] if empty else None)
    reader = WechatResearchArchive(archive, tmp_path / 'index')
    registered = register_return(reader, receipt='IMPORT_RECEIPT.json',
                                 receipt_sha256=sha((archive / 'IMPORT_RECEIPT.json').read_bytes()))
    before = {p.name: sha(p.read_bytes()) for p in archive.iterdir() if p.is_file()}
    app = FastAPI()
    app.include_router(create_wechat_research_router(reader))
    with TestClient(app) as client:
        response = client.get('/wechat/materials/mentions?date=20260927')
        assert response.status_code == 200, response.text
        doc = response.json()
        assert doc['total'] == (0 if empty else 1)
        if not empty:
            assert doc['items'][0]['source_indexes'] == ['BODY']
        raw = client.get(f"/wechat/materials/{registered['record_id']}/artifacts/mentions")
        assert raw.content == (archive / receipt['archived_files']['mentions']['archived_filename']).read_bytes()
        assert raw.headers['x-content-type-options'] == 'nosniff'
    assert before == {p.name: sha(p.read_bytes()) for p in archive.iterdir() if p.is_file()}


def test_repaired_import_does_not_report_broken_v4_index_as_idempotent(tmp_path):
    archive, kwargs, first = make_archive(tmp_path / 'case')
    reader = WechatResearchArchive(archive, tmp_path / 'index')
    first_registration = register_return(
        reader, receipt='IMPORT_RECEIPT.json',
        receipt_sha256=sha((archive / 'IMPORT_RECEIPT.json').read_bytes()))
    old_report = archive / first['archived_files']['report']['archived_filename']
    old_report.write_bytes(b'corrupted historical bytes')
    repaired = handoff.import_chat_return(**kwargs)
    # Select the actual newly written receipt, not the stale canonical filename.
    candidates = [path for path in archive.glob('IMPORT_RECEIPT*.json')
                  if json.loads(path.read_text()) == repaired]
    assert len(candidates) == 1
    repair_receipt = candidates[0]
    assert repair_receipt.name != 'IMPORT_RECEIPT.json'
    with pytest.raises(ArchiveError, match='IDEMPOTENT_SOURCE_UNAVAILABLE'):
        register_return(reader, receipt=repair_receipt.name,
                        receipt_sha256=sha(repair_receipt.read_bytes()))
    assert reader.detail(first_registration['record_id'])['report']['status'] == 'HASH_MISMATCH'
    assert len(list((tmp_path / 'index' / 'records').glob('*.json'))) == 1
    assert old_report.read_bytes() == b'corrupted historical bytes'
