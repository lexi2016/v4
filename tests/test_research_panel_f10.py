import hashlib
import json
from pathlib import Path
import re

import pytest

from ops import research_panel_f10 as owner
from ops.research_panel_f10 import fetch_one

FLAGS = dict(RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw=(json.dumps(value,sort_keys=True,separators=(',',':'))+'\n').encode()
    path.write_bytes(raw)
    return {'path':str(path.resolve()),'sha256':hashlib.sha256(raw).hexdigest()}


def exact_source_fixture(tmp_path, day='20261119'):
    identity={'input_sha256':'a'*64,'selector_artifact_sha256':'b'*64}
    context=type('Context',(),{'target':int(day),'generation':'c'*64,'identity':identity,'unchanged':lambda self:None})()
    product_ref=write_json(tmp_path/'product.json',dict(schema_version='v4.a_share.daily_product.v1',
        status='PARTIAL_WITH_ROWS',sample_only=False,data_date=day,source_generation=context.generation,
        source_identity=identity,**FLAGS))
    manifest_ref=write_json(tmp_path/'manifest.json',dict(schema_version='v4.a_share.daily_product_manifest.v1',
        status='PARTIAL_WITH_ROWS',sample_only=False,data_date=day,source_generation=context.generation,
        input_sha256=identity['input_sha256'],artifact=product_ref,**FLAGS))
    write_json(tmp_path/'index.json',dict(dates={day:manifest_ref}))
    write_json(tmp_path/'events'/'latest.json',dict(schema_version='v4.a_share.daily_completion.v1',
        status='PARTIAL_WITH_ROWS',data_date=day,source_generation=context.generation,
        input_sha256=identity['input_sha256'],artifact=product_ref,manifest=manifest_ref,**FLAGS))
    return context,manifest_ref


class FakeApi:
    def __init__(self, text, finance):
        self.text = text
        self.finance = finance

    def connect(self, host, port):
        return True

    def get_company_info_category(self, market, code):
        assert (market, code) == (1, '688728')
        return [{'name': '最新提示', 'filename': 'company.dat', 'start': 0, 'length': len(self.text)}]

    def get_company_info_content(self, market, code, filename, start, length):
        return self.text

    def get_finance_info(self, market, code):
        return self.finance

    def disconnect(self):
        return None


class FakeFetch:
    @staticmethod
    def grab(text, label):
        match = re.search(re.escape(label) + r'[^｜]*｜\s*([-0-9.]+)', text)
        return float(match.group(1)) if match else None

    @staticmethod
    def concepts_from(section):
        return [{'name': '图像传感器', 'desc': '测试来源概念'}] if section else []


def source_text(eps='-', bps='1.25', roe='8.5'):
    return '\n'.join([
        '◇688728 格科微 更新日期：2026-11-19',
        '★最新主要指标★｜2026-06-30',
        f'每股收益(元)｜{eps}',
        f'每股净资产(元)｜{bps}',
        f'净资产收益率(%)｜{roe}',
        '【3.概念板块】',
        '｜图像传感器｜测试来源概念',
        '【4.风险提示】',
    ])


def api_factory(text):
    finance = {'code': '688728', 'market': 1, 'updated_date': '2026-11-19',
               'gudongrenshu': 12345, 'industry': 9}
    return lambda: FakeApi(text, finance)


def test_literal_dash_keeps_f10_snapshot_and_other_fields():
    value = fetch_one('688728.SH', 'SH', api_factory=api_factory(source_text()),
                      vendor=(FakeFetch, FakeFetch))

    assert value['status'] == 'OBSERVED'
    assert value['financials']['eps'] is None
    assert value['financials']['bps'] == 1.25
    assert value['financials']['roe_pct'] == 8.5
    assert value['financials']['holder_count'] == 12345
    assert value['concepts'] == [{'name': '图像传感器', 'desc': '测试来源概念'}]
    assert value['source_text'] == source_text()


def test_malformed_number_is_still_a_collector_failure():
    value = fetch_one('688728.SH', 'SH', api_factory=api_factory(source_text(bps='1..25')),
                      vendor=(FakeFetch, FakeFetch))

    assert value['status'] == 'FAILED'
    assert 'could not convert string to float' in value['reason']


def test_f10_requires_an_exact_current_day_numeric_product_and_event(tmp_path):
    context,manifest_ref=exact_source_fixture(tmp_path)
    ready=owner.exact_daily_source_receipt(context,tmp_path,tmp_path)
    receipt=json.loads(Path(ready['path']).read_bytes())
    owner._validate_f10_upstream(context,receipt,tmp_path)
    assert receipt['numeric_manifest']==manifest_ref
    assert receipt['data_date']=='20261119'

    wrong_date={**receipt,'data_date':'20261118'}
    with pytest.raises(ValueError,match='SOURCE_RECEIPT_CONFLICT'):
        owner._validate_f10_upstream(context,wrong_date,tmp_path)

    event=Path(tmp_path/'events'/'latest.json')
    value=json.loads(event.read_bytes());value['input_sha256']='d'*64
    event.write_text(json.dumps(value))
    with pytest.raises(ValueError,match='EVENT_IDENTITY_CONFLICT|EVENT_MOVED'):
        owner.exact_daily_source_receipt(context,tmp_path,tmp_path/'output')


def test_f10_source_is_not_ready_when_the_exact_date_has_no_numeric_manifest(tmp_path):
    context,manifest_ref=exact_source_fixture(tmp_path)
    write_json(tmp_path/'index.json',dict(dates={'20261118':manifest_ref}))
    with pytest.raises(ValueError,match='F10_EXACT_DAILY_PRODUCT_NOT_READY'):
        owner.exact_daily_source_receipt(context,tmp_path,tmp_path/'output')


def test_f10_publish_rejects_same_identity_numeric_manifest_ref_drift(tmp_path,monkeypatch):
    import sys
    from types import SimpleNamespace

    context,original_manifest=exact_source_fixture(tmp_path)
    ready=owner.exact_daily_source_receipt(context,tmp_path,tmp_path)
    monkeypatch.setattr(owner,'bound_universe',lambda ctx,requested=None:{symbol:'SH' for symbol in requested})
    result=owner.complete_f10(context,ready,tmp_path,requested=['600000.SH'],
        fetch=lambda symbol,exchange:{'symbol':symbol,'status':'OBSERVED'})

    product_ref=write_json(tmp_path/'replacement-product.json',dict(schema_version='v4.a_share.daily_product.v1',
        status='PARTIAL_WITH_ROWS',sample_only=False,data_date='20261119',source_generation=context.generation,
        source_identity=context.identity,**FLAGS))
    replacement=write_json(tmp_path/'replacement-manifest.json',dict(schema_version='v4.a_share.daily_product_manifest.v1',
        status='PARTIAL_WITH_ROWS',sample_only=False,data_date='20261119',source_generation=context.generation,
        input_sha256=context.identity['input_sha256'],artifact=product_ref,**FLAGS))
    assert replacement!=original_manifest
    write_json(tmp_path/'index.json',dict(dates={'20261119':replacement}))
    write_json(tmp_path/'events'/'latest.json',dict(schema_version='v4.a_share.daily_completion.v1',
        status='PARTIAL_WITH_ROWS',data_date='20261119',source_generation=context.generation,
        input_sha256=context.identity['input_sha256'],artifact=product_ref,manifest=replacement,**FLAGS))

    lock=tmp_path/'owner.lock';lock.touch()
    monkeypatch.setitem(sys.modules,'ops.sync_stock_history_completion',SimpleNamespace(
        DEFAULT_OWNER_LOCK=lock,_inherited_owner_duplicate=lambda *args:None))
    with pytest.raises(ValueError,match='F10_EXACT_DAILY_INDEX_MOVED'):
        owner.publish_f10_completion(context,tmp_path,result['receipt'])


def test_f10_same_day_retry_reuses_observed_checkpoint_without_refetch(tmp_path,monkeypatch):
    context,_=exact_source_fixture(tmp_path)
    ready=owner.exact_daily_source_receipt(context,tmp_path,tmp_path/'output')
    monkeypatch.setattr(owner,'bound_universe',lambda ctx,requested=None:{symbol:'SH' for symbol in requested})
    calls=[]
    def fetch(symbol,exchange):
        calls.append((symbol,exchange))
        return {'symbol':symbol,'status':'OBSERVED'}
    first=owner.complete_f10(context,ready,tmp_path,requested=['600000.SH'],fetch=fetch)
    second=owner.complete_f10(context,ready,tmp_path,requested=['600000.SH'],fetch=fetch)
    assert first['status']==second['status']=='COMPLETE'
    assert calls==[('600000.SH','SH')]


def test_f10_rejects_previous_owner_adapter_checkpoint_without_mutating_it(tmp_path,monkeypatch):
    context,_=exact_source_fixture(tmp_path)
    ready=owner.exact_daily_source_receipt(context,tmp_path,tmp_path/'continuations')
    symbol='600000.SH';universe={symbol:'SH'}
    monkeypatch.setattr(owner,'bound_universe',lambda ctx,requested=None:universe)
    identity={'data_date':'20261119','source_generation':context.generation,
        'selector_sha256':context.identity['selector_artifact_sha256'],'input_sha256':context.identity['input_sha256'],
        'scope_sha256':owner._sha(json.dumps(universe,sort_keys=True).encode()),
        'adapter_sha256':'8c181223093b7f3fba859290cd3f5ffde8500cdd6b992098001ad1c66e5b8780',
        'collector_sha256':owner.VENDOR}
    row_ref=write_json(tmp_path/'f10'/'20261119'/context.generation[:16]/'stocks'/symbol/'observed.json',
        {'symbol':symbol,'status':'OBSERVED'})
    checkpoint=tmp_path/'f10'/'20261119'/context.generation[:16]/'checkpoint.json'
    write_json(checkpoint,{'schema':'v4.a_share.f10_checkpoint.v1','identity':identity,
        'items':{symbol:row_ref},'upstream_success_receipt':ready,**FLAGS})
    before=checkpoint.read_bytes()
    with pytest.raises(ValueError,match='F10_CHECKPOINT_IDENTITY_CONFLICT'):
        owner.complete_f10(context,ready,tmp_path,requested=[symbol],
            fetch=lambda *args:pytest.fail('incompatible checkpoint must fail before fetch'))
    assert checkpoint.read_bytes()==before
