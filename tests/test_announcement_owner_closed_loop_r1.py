"""Isolated owner-contract tests against the delivered source-only handoff.

Synthetic inputs exercise code paths; they are NOT historical Mac data or proof
of a natural schedule. The complete live repo must run its original suites.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
from hashlib import sha256
import importlib
import json
from pathlib import Path
import re
import sys
import types

import pytest


@pytest.fixture
def owner_modules(monkeypatch):
    """Supply only the unavailable shared dependencies, never the owner modules."""
    project = Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(project))
    # Always load the exact local owner bytes, not an unrelated v4 installation.
    for name in list(sys.modules):
        if name.startswith('v4.manager_research.') and (name.endswith('_analysis') or
            name.endswith('_selection') or name.endswith('_announcements')):
            monkeypatch.delitem(sys.modules, name, raising=False)
    projection = types.ModuleType('v4.manager_research.workspace_projection')
    projection.FLAGS = dict(RESEARCH_ONLY=True, production_allowed=False,
                            buy_gate_updated=False, orders_sent=False)
    projection.HK = __import__('zoneinfo').ZoneInfo('Asia/Shanghai')
    def digest(value):
        return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                 separators=(',', ':')).encode('utf-8')).hexdigest()
    def date_token(value):
        if not isinstance(value, str) or not re.fullmatch(r'\d{8}', value):
            raise ValueError('BAD_DATE')
        if datetime.strptime(value, '%Y%m%d').strftime('%Y%m%d') != value:
            raise ValueError('BAD_DATE')
        return value
    def timestamp(value):
        try:
            d = datetime.fromisoformat(value.replace('Z', '+00:00'))
            return d if d.tzinfo else None
        except (TypeError, AttributeError, ValueError):
            return None
    projection.digest, projection.date_token, projection.timestamp = digest, date_token, timestamp
    projection.canonical_symbol = lambda value: value if isinstance(value, str) and re.fullmatch(r'HK\.\d{5}', value) else None
    monkeypatch.setitem(sys.modules, projection.__name__, projection)
    source = types.ModuleType('v4.manager_research.announcement_source')
    for attr in ('read_response','query_request','directory_entries','classify_pages',
                 'extract_pdf_pages','_cached_extract_pdf_pages','safe_reason','window',
                 'publication_window','publication_in_window','request_context'):
        setattr(source, attr, lambda *a, **kw: None)
    source.MAX_BYTES, source.MAX_DOCUMENTS, source.PARSER_VERSION = 1, 1, 'test'
    monkeypatch.setitem(sys.modules, source.__name__, source)
    plan = types.ModuleType('v4.manager_research.workspace_plan')
    plan.plan_context = lambda *a, **kw: {}
    monkeypatch.setitem(sys.modules, plan.__name__, plan)
    selection = importlib.import_module('v4.manager_research.announcement_selection')
    analysis = importlib.import_module('v4.manager_research.announcement_analysis')
    announcements = importlib.import_module('v4.manager_research.workspace_announcements')
    return projection, selection, analysis, announcements


def selected_product(modules):
    projection, selection, _analysis, _owner = modules
    binding = dict(target_trade_date='20261009',publication_date='2026-10-08',
        source_scope='EASTMONEY_HK_DATE_CATALOG',catalog_run_id='c'*32,
        catalog_product_sha256='a'*64,semantic_catalog_sha256='b'*64,
        body_corpus_sha256='d'*64)
    statuses = ['SELECTED_EVENT','CONDITIONAL_WATCH','NOT_SELECTED','NOT_ASSESSED']
    records = []
    decisions = []
    for index, disposition in enumerate(statuses, 1):
        code = f'AN20261008{index:010d}'
        record = dict(art_code=code, title=f'公告{index}',
            issuer_codes=[dict(code=f'HK.{index:05d}', name=f'发行人{index}')],
            security_scope='HK_LISTED',semantic_record_sha256=str(index)*64,
            body_record_sha256=str(index+4)*64, analysis_kind='COMPLETE_API_BODY')
        records.append(record)
        decisions.append(dict(art_code=code,issuer_codes=[f'HK.{index:05d}'],
            security_scope='HK_LISTED', semantic_record_sha256=record['semantic_record_sha256'],
            body_record_sha256=record['body_record_sha256'], disposition=disposition,
            reason=f'已核事实及研究判断{index}', risk_notes=['仅供研究'],
            selection_basis={
                'SELECTED_EVENT':'OPERATING_EVENT',
                'CONDITIONAL_WATCH':'CONDITIONAL_WATCH',
                'NOT_SELECTED':'NOT_SELECTED',
                'NOT_ASSESSED':'NOT_ASSESSED'}[disposition]))
        decisions[-1]['issuer_codes'] = [f'HK.{index:05d}']
    base = dict(target_trade_date=binding['target_trade_date'],
        publication_date=binding['publication_date'],source_manifest=binding,
        source_manifest_sha256=projection.digest(binding),records=records,
        agent_judgment_receipt=dict(evidence_run_id='e'*32,
            parent_task_id='task',parent_run_id='run',
            reviewed_at='2026-10-11T10:00:00+00:00',sha256='1'*64),
        **projection.FLAGS)
    base['sha256'] = projection.digest(base)
    ext = selection.make_extension(base, decisions)
    product = selection.attach_extension(base, ext)
    # Agent receipt is present before the sealed selection extension is bound.
    return product


class MemoryStore:
    def __init__(self, path):
        self.root = path
        self.rows = {}
        self.transactions = 0
    def _read(self, path):
        return deepcopy(self.rows.get(str(path)))
    def _write_atomic(self, path, value):
        self.rows[str(path)] = deepcopy(value)
    @contextmanager
    def _transaction(self, date, name):
        self.transactions += 1
        yield


class Service:
    def __init__(self, root, product):
        self.store = MemoryStore(root)
        self.product = product
    def get_announcement_date_catalog(self, target, publication):
        return dict(catalog=dict(target_trade_date=target, publication_date=publication))
    def get_announcement_analysis(self, target, publication):
        path = self.store.root / 'workspace_announcements' / target / 'eastmoney_date_catalog' / publication.replace('-','') / 'analysis.v1.json'
        row = self.store._read(path)
        return dict(target_trade_date=target,publication_date=publication,
            source_catalog=dict(readback_status='VERIFIED'),
            analysis=dict(status='VERIFIED',product_sha256=row['sha256'],
                source_manifest_sha256=row['source_manifest_sha256']))


def test_registered_owner_import_writes_product_and_receipt_and_is_idempotent(monkeypatch, tmp_path, owner_modules):
    projection, _selection, analysis, announcements = owner_modules
    product = selected_product(owner_modules)
    service = Service(tmp_path, product)
    evidence = 'e'*32
    handoff = 'f'*64
    monkeypatch.setattr(announcements, 'validate_registered_handoff',
        lambda store, rid, h, sha: {'product': deepcopy(product)} if
            (rid,h,sha)==(evidence,handoff,product['sha256']) else (_ for _ in ()).throw(ValueError('WRONG_HANDOFF')))
    monkeypatch.setattr(announcements,'validate_agent_judgment_receipt',
        lambda receipt,p: deepcopy(dict(receipt,sha256='1'*64)))
    monkeypatch.setattr(analysis,'_assert_catalog_readback', lambda read, target, pub: read['catalog'])
    monkeypatch.setattr(analysis,'validate_product', lambda row, **kwargs: deepcopy(row))
    monkeypatch.setattr(announcements,'read_analysis_consumption',
        lambda service, target, pub, **kwargs: dict(validation_status='VERIFIED',
            product_sha256=product['sha256'],owner_import_receipt_sha256=service.store._read(
              analysis.product_path(service.store, target, pub).with_name('owner_import_receipt.v1.json'))['sha256']))
    first = analysis.import_registered_product(service, evidence, handoff, product['sha256'])
    assert first['import_status'] == 'IMPORTED'
    assert first['owner_import_receipt']['product_sha256'] == product['sha256']
    assert first['owner_import_receipt']['evidence_run_id'] == evidence
    assert first['consumption_validation']['validation_status'] == 'VERIFIED'
    assert first['owner_import_receipt']['sha256'] == projection.digest({k:v for k,v in first['owner_import_receipt'].items() if k!='sha256'})
    assert len(service.store.rows) == 2 and service.store.transactions == 1
    second = analysis.import_registered_product(service, evidence, handoff, product['sha256'])
    assert second['import_status'] == 'ALREADY_IMPORTED'
    assert second['owner_import_receipt'] == first['owner_import_receipt']
    assert len(service.store.rows) == 2


def test_bad_handoff_does_not_write(monkeypatch, tmp_path, owner_modules):
    _, _, analysis, announcements = owner_modules
    product = selected_product(owner_modules)
    service = Service(tmp_path, product)
    monkeypatch.setattr(announcements, 'validate_registered_handoff',
        lambda *a, **kw: (_ for _ in ()).throw(ValueError('WRONG_HANDOFF')))
    with pytest.raises(ValueError, match='WRONG_HANDOFF'):
        analysis.import_registered_product(service, 'e'*32, '0'*64, product['sha256'])
    assert not service.store.rows and service.store.transactions == 0


@pytest.mark.parametrize('valid,status,cutoff,expected', [
    (True, 'VERIFIED', None, 'RETROSPECTIVE_RESEARCH_ONLY'),
    (True, 'NOT_CONSUMED_AFTER_CUTOFF', '2026-10-09T09:30:00+08:00', 'RETROSPECTIVE_RESEARCH_ONLY'),
    (True, 'CONSUMED', '2026-10-09T09:30:00+08:00', 'CONSUMED_AT_CUTOFF'),
    (False, 'NOT_CONSUMED_INVALID', '2026-10-09T09:30:00+08:00', 'CANNOT_CONFIRM'),
])
def test_research_audit_never_promotes_after_cutoff_into_pit(
        monkeypatch,tmp_path,owner_modules,valid,status,cutoff,expected):
    _projection, selection, analysis, owner = owner_modules
    product = selected_product(owner_modules)
    service = Service(tmp_path, product)
    path = analysis.product_path(service.store, '20261009', '2026-10-08')
    service.store._write_atomic(path, product)
    assessment = dict(status=status,validation_status='VERIFIED' if valid else 'CANNOT_CONFIRM',
        target_trade_date='20261009',publication_date='2026-10-08',
        consumed=status=='CONSUMED',cutoff_status='SATISFIED' if status=='CONSUMED' else 'AFTER_CUTOFF',
        decision_status='EXPLICIT_DISPOSITIONS', selection_status='VERIFIED',
        product_sha256=product['sha256'],source_manifest_sha256=product['source_manifest_sha256'],
        evidence_run_id='e'*32,owner_import_receipt_sha256='0'*64,
        handoff_manifest_sha256='1'*64,source_run_id='c'*32,
        catalog_product_sha256='a'*64,latest_source_or_review_at='2026-10-11T10:00:00+00:00',
        owner_available_at='2026-10-11T10:00:00+00:00',
        stock_count=4,selected_stock_count=1,conditional_watch_count=1,
        not_selected_stock_count=1,not_assessed_stock_count=1,gaps=[] if valid else ['BAD_RECEIPT'])
    monkeypatch.setattr(owner,'read_analysis_consumption',lambda *a, **kw: deepcopy(assessment))
    result = owner.read_announcement_research_result(service,'20261009','2026-10-08',cutoff=cutoff)
    assert result['status'] == expected
    assert result['historical_pit_verified'] is False
    if valid:
        assert result['stock_count'] == 4
        assert {x['status'] for x in result['stocks']} == {'SELECTED','CONDITIONAL_WATCH','NOT_SELECTED','NOT_ASSESSED'}
        assert result['selected_stock_count'] == 1 and result['not_assessed_stock_count'] == 1
        assert result['product_sha256'] == product['sha256']
        assert result['selection_sha256'] == product['stock_selection']['sha256']
        if status!='CONSUMED':
            assert result['consumed_at_cutoff'] is False
    else:
        assert result['stocks']==[] and result['stock_count'] is None
        assert result['selected_stock_count'] is None


def test_research_audit_rejects_mutated_saved_product(monkeypatch,tmp_path,owner_modules):
    _,_,analysis,owner=owner_modules
    product=selected_product(owner_modules)
    service=Service(tmp_path,product)
    product['sha256']='0'*64
    service.store._write_atomic(analysis.product_path(service.store,'20261009','2026-10-08'),product)
    monkeypatch.setattr(owner,'read_analysis_consumption', lambda *a,**kw: dict(
        status='VERIFIED', validation_status='VERIFIED', decision_status='EXPLICIT_DISPOSITIONS',
        product_sha256='1'*64, selection_status='VERIFIED', gaps=[]))
    result=owner.read_announcement_research_result(service,'20261009','2026-10-08')
    assert result['status']=='CANNOT_CONFIRM'
    assert result['stocks']==[]
    assert 'ANNOUNCEMENT_RESEARCH_OWNER_PRODUCT_CHANGED' in result['gaps']


def test_existing_receipt_identity_conflict_rejected_without_rewrite(monkeypatch,tmp_path,owner_modules):
    _proj, _, analysis, owner = owner_modules
    product=selected_product(owner_modules)
    service=Service(tmp_path,product)
    import hashlib
    from copy import deepcopy
    monkeypatch.setattr(owner,'validate_registered_handoff',
        lambda *a,**kw:{'product':deepcopy(product)})
    monkeypatch.setattr(owner,'validate_agent_judgment_receipt',
        lambda receipt,p:dict(receipt,sha256='1'*64))
    monkeypatch.setattr(analysis,'_assert_catalog_readback',lambda read,target,pub:read['catalog'])
    monkeypatch.setattr(analysis,'validate_product',lambda value,**kw:deepcopy(value))
    monkeypatch.setattr(owner,'read_analysis_consumption',lambda *a,**kw:dict(
        validation_status='VERIFIED',product_sha256=product['sha256'],
        owner_import_receipt_sha256='0'*64))
    with pytest.raises(ValueError,match='ANNOUNCEMENT_ANALYSIS_REGISTERED_CONSUMPTION_READBACK_FAILED'):
        analysis.import_registered_product(service,'e'*32,'f'*64,product['sha256'])
    path=analysis.product_path(service.store,'20261009','2026-10-08')
    first=deepcopy(service.store.rows)
    assert first[str(path)]['sha256']==product['sha256']
    assert first[str(path.with_name('owner_import_receipt.v1.json'))]['sha256']!= '0'*64
    with pytest.raises(ValueError,match='ANNOUNCEMENT_ANALYSIS_OWNER_RECEIPT_CONFLICT'):
        analysis.import_registered_product(service,'e'*32,'8'*64,product['sha256'])
    assert service.store.rows==first


def test_missing_or_unverified_chain_never_returns_fake_zero(monkeypatch,tmp_path,owner_modules):
    _proj,_,analysis,owner=owner_modules
    product=selected_product(owner_modules)
    service=Service(tmp_path,product)
    monkeypatch.setattr(owner,'read_analysis_consumption',lambda *a,**kw:dict(
        status='NOT_IMPORTED',validation_status='NOT_IMPORTED',gaps=['ANNOUNCEMENT_ANALYSIS_NOT_IMPORTED']))
    result=owner.read_announcement_research_result(service,'20261009','2026-10-08')
    assert result['status']=='CANNOT_CONFIRM'
    assert result['stock_count'] is None and result['selected_stock_count'] is None
    assert result['stocks']==[]


def test_verified_chain_with_conflicting_count_is_rejected(monkeypatch,tmp_path,owner_modules):
    _proj,_,analysis,owner=owner_modules
    product=selected_product(owner_modules);service=Service(tmp_path,product)
    service.store._write_atomic(analysis.product_path(service.store,'20261009','2026-10-08'),product)
    monkeypatch.setattr(owner,'read_analysis_consumption',lambda *a,**kw:dict(
        status='VERIFIED',validation_status='VERIFIED',decision_status='EXPLICIT_DISPOSITIONS',
        selection_status='VERIFIED',product_sha256=product['sha256'],
        source_manifest_sha256=product['source_manifest_sha256'],owner_import_receipt_sha256='0'*64,
        evidence_run_id='e'*32,stock_count=4,selected_stock_count=2,
        conditional_watch_count=1,not_selected_stock_count=1,not_assessed_stock_count=1,gaps=[]))
    result=owner.read_announcement_research_result(service,'20261009','2026-10-08')
    assert result['status']=='CANNOT_CONFIRM' and result['selected_stock_count'] is None
    assert 'ANNOUNCEMENT_RESEARCH_COUNT_IDENTITY_MISMATCH' in result['gaps']
