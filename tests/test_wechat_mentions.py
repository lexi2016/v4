"""Bounded Stage A projection tests for archived WeChat mention rows."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from infrastructure.wechat_research_archive import ArchiveError, WechatResearchArchive
from ops.index_wechat_research import register_return


HEADERS = 'market,code,name,source_index,mapping_status,source_named_or_derived,claim_context,entity_id,source_name,listing_origin\n'
ROWS = [
    'A,600000.SH,浦发银行,IMAGE001,IDENTITY_REFERENCE_RESOLVED,SOURCE_NAMED,原文提及，不是推荐,ISSUER_600000_SH,浦发,NAME_RESOLVED',
    'A,600000.SH,浦发银行,IMAGE002,IDENTITY_REFERENCE_RESOLVED,SOURCE_NAMED,同一公司再次提及,ISSUER_600000_SH,浦发,NAME_RESOLVED',
    'BJ,920001.BJ,示例北交所,IMAGE003,IDENTITY_REFERENCE_RESOLVED,SOURCE_NAMED,原文提及,ISSUER_920001_BJ,示例,NAME_RESOLVED',
    'HK,00700.HK,腾讯控股,IMAGE004,IDENTITY_REFERENCE_RESOLVED,SOURCE_NAMED,原文提及,ISSUER_00700_HK,腾讯,SUPPLEMENTAL_LISTING',
]


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_return(root: Path, folder: str, *, received_at: str, report_only: bool = False,
                 mentions_text: str | None = None, package_suffix: str = 'one',
                 bound: bool = True) -> Path:
    target = root / folder
    target.mkdir(parents=True)
    package_id = f'wechat-test-{package_suffix}'
    source_run_id = f'run-test-{package_suffix}'
    input_digest = 'd' * 64
    package_sha = (('a' if package_suffix == 'one' else 'b') * 64)
    article_url = 'https://mp.weixin.qq.com/s/test-article'
    report = '# 原报告\n'.encode()
    (target / 'report.md').write_bytes(report)
    archived = {'report': {'archived_filename': 'report.md', 'sha256': sha(report), 'bytes': len(report)}}
    missing = ['coverage.csv', 'mentions.csv', 'unmapped.csv', 'summary.json']
    if report_only:
        status = 'REPORT_ONLY_ARCHIVED'
    else:
        coverage = b'source_index,coverage_status\n'
        unmapped = b'entity_id,reason\n'
        (target / 'coverage.csv').write_bytes(coverage)
        (target / 'unmapped.csv').write_bytes(unmapped)
        archived['coverage'] = {'archived_filename': 'coverage.csv', 'sha256': sha(coverage), 'bytes': len(coverage)}
        archived['unmapped'] = {'archived_filename': 'unmapped.csv', 'sha256': sha(unmapped), 'bytes': len(unmapped)}
        mentions = (mentions_text or (HEADERS + '\n'.join(ROWS) + '\n')).encode()
        (target / 'mentions.csv').write_bytes(mentions)
        counts = {
            'total': len(mentions.decode().splitlines()) - 1,
            'A': 2, 'BJ': 1, 'HK': 1, 'entities': 3,
            'source_named_entities': 3, 'supplemental_listing_rows': 1,
        }
        summary = {
            'url': article_url, 'package_id': package_id, 'input_digest': input_digest,
            'return_id': f'return-{package_suffix}', 'article_date': '20260920',
            'mentions_counts': counts, 'status': 'PARTIAL_WITH_UNREADABLE',
        }
        summary_bytes = (json.dumps(summary, ensure_ascii=False, sort_keys=True) + '\n').encode()
        (target / 'summary.json').write_bytes(summary_bytes)
        archived['mentions'] = {'archived_filename': 'mentions.csv', 'sha256': sha(mentions), 'bytes': len(mentions)}
        archived['summary'] = {'archived_filename': 'summary.json', 'sha256': sha(summary_bytes), 'bytes': len(summary_bytes)}
        missing = []
        status = 'REPORT_AND_STRUCTURED_ARCHIVED'
    receipt = {
        'receipt_version': 'wechat-chat-return-v2', 'status': status,
        'binding': {
            'source_run_id': source_run_id, 'package_id': package_id,
            'package_sha256_declared': package_sha, 'package_sha256_observed': package_sha,
            'package_sha256_status': 'VERIFIED' if bound else 'UNVERIFIED', 'article_url': article_url,
            'article_id': 'test-article', 'article_title': '测试文章 9.20',
            'article_date': '20260920', 'content_hash': 'c' * 40,
            'input_digest': input_digest, 'package_identity_status': 'VERIFIED',
        },
        'report_origin': 'USER_PROVIDED_CHAT_RETURN', 'received_at': received_at,
        'archived_files': archived, 'missing_artifacts': missing,
        'structured_validation_status': 'COMPLETE' if not report_only else 'MISSING',
        'local_acceptance': {
            'input_binding_valid': not report_only and bound, 'structured_files_complete': not report_only,
            'independent_review_scope': [], 'semantic_research_accepted': False,
        },
        'production_allowed': False, 'buy_gate_updated': False, 'orders_sent': False,
    }
    receipt_path = target / 'IMPORT_RECEIPT.json'
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return receipt_path


@pytest.fixture
def reader(tmp_path: Path):
    archive = tmp_path / 'archive'
    index = tmp_path / 'index'
    archive.mkdir()
    r = WechatResearchArchive(archive, index)
    return archive, r


def register(archive: Path, reader: WechatResearchArchive, receipt: Path):
    return register_return(reader, receipt=str(receipt.relative_to(archive)), receipt_sha256=sha(receipt.read_bytes()))


def test_deduplicates_by_market_listing_and_preserves_provenance(reader):
    archive, r = reader
    receipt = write_return(archive, 'v1', received_at='2026-09-21T01:00:00+08:00')
    registered = register(archive, r, receipt)
    result = r.list_mentions(date='20260920', limit=100)
    assert registered['record_id'] == result['record_id']
    assert r._record(registered['record_id'])['snapshot']['states']['input_binding'] == 'RECEIPT_BOUND'
    assert result['status'] == 'READY'
    assert result['total'] == 3
    assert result['counts'] == {
        'rows': 4, 'listings': 3, 'issuers': 3,
        'market_rows': {'A': 2, 'BJ': 1, 'HK': 1},
        'market_listings': {'A': 1, 'BJ': 1, 'HK': 1},
        'source_named_rows': 4, 'source_named_listings': 3,
        'source_named_entities': 3, 'supplemental_listing_rows': 1,
    }
    a = result['items'][0]
    assert a['market'] == 'A' and a['source_count'] == 2
    assert a['source_indexes'] == ['IMAGE001', 'IMAGE002']
    assert 'rank' not in a and 'score' not in a
    assert result['summary_status'] == 'PARTIAL_WITH_UNREADABLE'
    assert 'ISSUER_MAPPING_NOT_INDEPENDENTLY_VERIFIED' in result['cannot_confirm']


def test_report_only_is_explicitly_missing_and_date_does_not_fallback(reader):
    archive, r = reader
    receipt = write_return(archive, 'report-only', received_at='2026-09-21T01:00:00+08:00', report_only=True)
    register(archive, r, receipt)
    result = r.list_mentions(date='20260920')
    assert result['status'] == 'MISSING'
    assert result['missing_artifacts'] == ['mentions']
    assert result['items'] == []
    assert r.list_mentions(date='20260919')['status'] == 'NOT_INDEXED'


def test_latest_same_article_is_selected_but_tamper_does_not_fallback(reader):
    archive, r = reader
    first = write_return(archive, 'v1', received_at='2026-09-21T01:00:00+08:00', package_suffix='one')
    register(archive, r, first)
    second = write_return(archive, 'v2', received_at='2026-09-21T02:00:00+08:00', package_suffix='two')
    latest = register(archive, r, second)
    assert r.list_mentions(date='20260920')['record_id'] == latest['record_id']
    mentions = archive / 'v2' / 'mentions.csv'
    mentions.write_text(mentions.read_text(encoding='utf-8') + 'A,600001.SH,篡改,IMAGE005,x,SOURCE_NAMED,x,ISSUER_600001_SH,x,NAME_RESOLVED\n', encoding='utf-8')
    with pytest.raises(ArchiveError, match='HASH_MISMATCH'):
        r.list_mentions(date='20260920')


def test_unbound_structured_return_is_rejected_for_date_and_record_lookup(reader):
    archive, r = reader
    receipt = write_return(archive, 'unbound', received_at='2026-09-21T01:00:00+08:00', bound=False)
    registered = register(archive, r, receipt)
    record = r._record(registered['record_id'])
    assert record['snapshot']['states']['input_binding'] == 'RETURN_UNBOUND'
    with pytest.raises(ArchiveError, match='RETURN_UNBOUND'):
        r.list_mentions(date='20260920')
    with pytest.raises(ArchiveError, match='RETURN_UNBOUND'):
        r.list_mentions(record_id=registered['record_id'])


def test_malformed_mentions_fail_closed(reader):
    archive, r = reader
    receipt = write_return(archive, 'bad', received_at='2026-09-21T01:00:00+08:00',
                           mentions_text=HEADERS + 'A,not-a-code,bad,IMAGE001,x,SOURCE_NAMED,x,ISSUER_BAD,x,NAME_RESOLVED\n',
                           package_suffix='bad')
    register(archive, r, receipt)
    with pytest.raises(ArchiveError, match='MENTIONS_INVALID_SECURITY'):
        r.list_mentions(date='20260920')


def test_embedded_blank_csv_row_fails_closed(reader):
    archive, r = reader
    mentions = HEADERS + ROWS[0] + '\n\n' + ROWS[1] + '\n'
    receipt = write_return(archive, 'blank-row', received_at='2026-09-21T01:00:00+08:00',
                           mentions_text=mentions, package_suffix='blank')
    register(archive, r, receipt)
    with pytest.raises(ArchiveError, match='MENTIONS_MALFORMED_ROW_3'):
        r.list_mentions(date='20260920')


def test_malformed_csv_quoting_fails_closed(reader):
    archive, r = reader
    mentions = HEADERS + 'A,"600000.SH,浦发银行,IMAGE001,IDENTITY_REFERENCE_RESOLVED,SOURCE_NAMED,原文提及,ISSUER_600000_SH,浦发,NAME_RESOLVED\n'
    receipt = write_return(archive, 'bad-quote', received_at='2026-09-21T01:00:00+08:00',
                           mentions_text=mentions, package_suffix='quote')
    register(archive, r, receipt)
    with pytest.raises(ArchiveError, match='MENTIONS_MALFORMED'):
        r.list_mentions(date='20260920')
