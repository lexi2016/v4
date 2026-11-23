"""Isolated ordinary daily input tests; no live data/pointers or network."""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import struct
from types import SimpleNamespace
import zipfile

import numpy as np
import pandas as pd
import pyarrow as pa
import pytest

from ops import research_panel_adjustment_inputs as inputs
from ops import research_panel_qfq as q
from ops import research_panel_delta as delta


ROOT = Path(__file__).resolve().parents[1]
DAY = struct.Struct('<IIIIIfII')
TARGET, PREVIOUS = 20261123, 20261120
SPECS = [('sh', 1, '600035'), ('sz', 0, '000001'), ('bj', 2, '920002')]


def ref(path):
    return dict(path=str(path), sha256=q.sha(path))


def save(path, value):
    q._json(path, value)
    return ref(path)


def bar(date, close=10.5, reserved=0):
    return DAY.pack(date, int((close-.1)*100), int((close+.2)*100), int((close-.2)*100),
                    int(close*100), 129622.515625, 12345, reserved)


def package(root, *, target=TARGET, previous=PREVIOUS, missing_codes=()):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as z:
        for prefix, market, code in SPECS:
            cod, md = bytearray(150), bytearray(512)
            cod[:6] = ('999999' if code in missing_codes else code).encode(); cod[40:44] = '样本'.encode('gbk')
            struct.pack_into('<d', md, 4, 10.)
            struct.pack_into('<4d', md, 12, 10.4, 10.7, 10.3, 10.5)
            struct.pack_into('<Q', md, 56, 12345)
            struct.pack_into('<d', md, 72, 129622.515625)
            z.writestr(f'{prefix}{str(target)[2:]}.cod', cod)
            z.writestr(f'{prefix}{str(target)[2:]}.md1', md)
    path = root/'official.zip'; path.write_bytes(buffer.getvalue())
    from ops._a_share_daily_sync_parts.official_daily_package import SOURCE_URL
    return save(root/'official.json', dict(schema_version='a_sync_official_daily_input.v1',
        source_kind='TDX_OFFICIAL_G4DAY', target_date=target, source_url=SOURCE_URL.format(date=target),
        previous_session=str(previous), package=ref(path), calendar=ref(ROOT/'contracts/market_calendar_2026.json'),
        calendar_adapter=ref(ROOT/'contracts/trading_calendar.py')))


def decoder(code, path, tail_records):
    with path.open('rb') as handle:
        handle.seek(max(0, path.stat().st_size//32-tail_records)*32)
        payload = handle.read()
    records = []
    for offset in range(0, len(payload), 32):
        date, op, high, low, close, amount, volume, _ = DAY.unpack_from(payload, offset)
        records.append(dict(ts_code=code, trade_date=date, open=op/100, high=high/100, low=low/100,
                            close=close/100, amount=amount, vol=volume, volume=volume))
    return pd.DataFrame(records)


@pytest.fixture
def case(tmp_path):
    driver = SimpleNamespace(DAY_STRUCT=DAY, read_day_tail=decoder)
    dates = [int(d.strftime('%Y%m%d')) for d in pd.bdate_range(end='2026-11-20', periods=90)]
    stocks, symbols, rows = [], {}, []
    for prefix, market, number in SPECS:
        code = number+'.'+prefix.upper()
        native = tmp_path/(code+'.native.day')
        native.write_bytes(b''.join(bar(d, 11+(i%11)/10, reserved=0x7065656b) for i,d in enumerate(dates)))
        archive = tmp_path/(code+'.archive.day')
        archive.write_bytes(b''.join(bar(d, 10+(i%13)/10) for i,d in enumerate(dates[:60])))
        sources = [dict(name=role, kind='day_bytes', **ref(path)) for role,path in [('archive',archive),('native',native)]]
        stocks.append(dict(code=code, sources=sources))
        live = tmp_path/'tdx/vipdoc'/prefix/'lday'/(prefix+number+'.day')
        live.parent.mkdir(parents=True, exist_ok=True)
        live.write_bytes(native.read_bytes()+bar(TARGET))
        rows.append(dict(symbol=number, market=market, classification='ACCEPTED', target_date_ready=True,
                         path=str(live), source_sha256_after=q.sha(live)))
    source = save(tmp_path/'source.json', dict(source_resolution=inputs.HISTORY_RESOLUTION, stocks=stocks))
    policy = save(tmp_path/'policy.json', dict(name=inputs.HISTORY_RESOLUTION, selection_unit='COMPLETE_SOURCE_BAR', price_or_volume_conversion='NONE'))
    evidence = save(tmp_path/'evidence.json', dict(accepted=True))
    config = dict(source_config=source, source_policy=policy, accepted_evidence=[evidence], archive_refs=[])
    bindings = inputs.history_raw_bindings(config, tmp_path/'binding.json', driver, PREVIOUS)
    symbols = {c:dict(item, events=[], event_coverage_complete=True) for c,item in bindings.items()}
    previous = dict(asof_date=PREVIOUS, history_retention_binding=config, symbols=symbols)
    previous_ref = save(tmp_path/'previous.json', previous)
    official_ref = package(tmp_path)
    descriptor = json.loads(Path(official_ref['path']).read_text())
    sync = dict(target_date=str(TARGET), symbol_reconciliation=rows, official_daily_source=dict(
        source_kind='TDX_OFFICIAL_G4DAY', input_ref=official_ref, package=descriptor['package'], previous_session=PREVIOUS))
    sync_ref = save(tmp_path/'sync.json', sync)
    return SimpleNamespace(root=tmp_path, driver=driver, config=config, previous=previous, previous_ref=previous_ref,
        sync=sync, sync_ref=sync_ref, dates=dates, tdx=tmp_path/'tdx')


def candidate(c):
    return inputs.history_raw_bindings(c.config, c.root/'unused/binding.json', c.driver, TARGET,
        current_tdx_root=c.tdx, previous_snapshot=c.previous_ref, sync_ref=c.sync_ref,
        retained_native_recovery=getattr(c,'recovery_ref',None))


def test_exact_legacy_whole_rows_without_input_files_or_decoder(case, monkeypatch):
    c = case
    legacy = inputs.history_raw_bindings(c.config, c.root/'oracle/binding.json', c.driver, TARGET, current_tdx_root=c.tdx)
    expected = {code:q.resolved_raw_history(code,item,TARGET,c.driver) for code,item in legacy.items()}
    before = {p:q.sha(p) for p in c.root.rglob('*') if p.is_file()}
    monkeypatch.setattr(inputs, '_write', lambda *a:pytest.fail('input wrote a merged .day'))
    monkeypatch.setattr(inputs, '_json', lambda *a:pytest.fail('input wrote a per-stock receipt'))
    c.driver.read_day_tail = lambda *a,**kw:pytest.fail('input decoded old history')
    actual = candidate(c)
    assert before == {p:q.sha(p) for p in c.root.rglob('*') if p.is_file()}
    c.driver.read_day_tail = decoder
    for code,item in actual.items():
        pd.testing.assert_frame_equal(q.resolved_raw_history(code,item,TARGET,c.driver), expected[code], check_exact=True)
        native = next(r for r in item['raw_files'] if r['source_role']=='native')
        assert native['sha256'] != native['raw32_sha256']
        assert q.raw32_source_sha(native) == next(r for r in legacy[code]['raw_files'] if r['source_role']=='native')['sha256']
    assert candidate(c) == actual


@pytest.mark.parametrize('failure', ['suffix', 'native', 'source', 'gap', 'first_census'])
def test_corrupt_or_unproved_input_fails_closed(case, failure):
    c = case; code = '000001.SZ'
    live = c.tdx/'vipdoc/sz/lday/sz000001.day'
    if failure in {'suffix', 'gap'}:
        payload = live.read_bytes()
        if failure == 'suffix':payload = payload[:-32]+bar(TARGET,11.)
        else:payload = payload[:-32]+bar(20261121)+payload[-32:]
        live.write_bytes(payload)
        next(r for r in c.sync['symbol_reconciliation'] if r['symbol']=='000001')['source_sha256_after']=q.sha(live)
        c.sync_ref=save(c.root/'sync.json',c.sync)
    if failure == 'native':
        p=Path(c.previous['symbols'][code]['raw_files'][1]['path']); p.write_bytes(p.read_bytes()+b'bad')
    if failure == 'source':c.sync['official_daily_source']['package']['sha256']='0'*64; c.sync_ref=save(c.root/'sync.json',c.sync)
    if failure == 'first_census':
        del c.previous['symbols'][code]; c.previous['retained_history_codes']=[code]; c.previous_ref=save(c.root/'previous.json',c.previous)
    with pytest.raises(q.QfqGateError):candidate(c)


def test_resealed_inline_tamper_cannot_replace_official_bar(case):
    c=case; value=candidate(c); code='000001.SZ'; item=value[code]
    native=next(r for r in item['raw_files'] if r['source_role']=='native')
    payload=bar(TARGET,11.)
    native['raw32_segments'][-1]=dict(raw32_hex=payload.hex(),sha256=hashlib.sha256(payload).hexdigest())
    native['raw32_sha256']=hashlib.sha256(b''.join(q.raw32_payloads(native,owner=code))).hexdigest()
    with pytest.raises(q.QfqGateError,match='NATIVE_TAIL_AUTHORITY_CONFLICT'):
        q.resolved_raw_history(code,item,TARGET,c.driver)


def test_same_date_baseline_reuses_same_component_identity(case):
    c=case; value=candidate(c)
    c.previous.update(asof_date=TARGET,symbols=value)
    c.previous_ref=save(c.root/'same_date.json',c.previous)
    assert candidate(c)==value


def generation(c, name, snapshot_ref, baseline, candidates):
    snapshot=json.loads(Path(snapshot_ref['path']).read_text())
    keys=set(q._GENERATION_TUPLE_KEYS)|{'input_sha256','logical_reader_sha256','delta_owner_sha256','turnover_input_sha256'}
    identity={k:hashlib.sha256(k.encode()).hexdigest() for k in keys}
    identity['input_sha256']=q.canonical_sha(snapshot)
    value=dict(status='READY',asof_date=snapshot['asof_date'],adjustment_snapshot=snapshot_ref,
        baseline_panel_sha256=baseline,candidate_sha256=candidates,**identity)
    value['generation_id']=q.canonical_sha(dict(target=snapshot['asof_date'],baseline_panel_sha256=baseline,**identity))
    return save(c.root/(name+'.json'),value)


@pytest.fixture
def retained_case(case):
    c=case; code='000001.SZ'; source_date=20261119
    old=copy.deepcopy(c.previous['symbols'][code]); old['history_end_date']=source_date
    native=next(r for r in old['raw_files'] if r['source_role']=='native')
    raw=Path(native['path']).read_bytes()[:-32]
    source_native=c.root/'source_native.day';source_native.write_bytes(raw)
    native.update(ref(source_native))
    source=copy.deepcopy(c.previous);source.update(asof_date=source_date,symbols={code:old})
    source_ref=save(c.root/'source_snapshot.json',source)
    source_candidates=dict(selector='1'*64,backtest='2'*64)
    source_gen=generation(c,'source_generation',source_ref,dict(selector='3'*64,backtest='4'*64),source_candidates)
    skipped_root=c.root/'skipped';skipped_root.mkdir()
    skipped_input=package(skipped_root,target=PREVIOUS,previous=source_date,missing_codes=[code[:6]])
    skipped_descriptor=json.loads(Path(skipped_input['path']).read_text())
    live=c.tdx/'vipdoc/sz/lday/sz000001.day';live.write_bytes(raw+bar(TARGET))
    skipped_row=dict(symbol=code[:6],market=0,classification='QUARANTINED',quarantine=True,
        reason_code='TARGET_DATE_MISSING',target_date_ready=False,last_date_before=source_date,last_date_after=source_date,
        source_sha256_before=native['sha256'],source_sha256_after=native['sha256'],path=str(live))
    skipped_ref=save(c.root/'skipped_sync.json',dict(target_date=str(PREVIOUS),symbol_reconciliation=[skipped_row],
        official_daily_source=dict(source_kind='TDX_OFFICIAL_G4DAY',input_ref=skipped_input,
                                  package=skipped_descriptor['package'],previous_session=source_date)))
    del c.previous['symbols'][code]
    c.previous.update(retained_history_codes=[code],source_files=[skipped_ref])
    c.previous_ref=save(c.root/'retained_snapshot.json',c.previous)
    parent_gen=generation(c,'retained_generation',c.previous_ref,source_candidates,dict(selector='5'*64,backtest='6'*64))
    c.recovery=dict(schema='qfq_retained_native_recovery_v1',target_date=TARGET,previous_snapshot=c.previous_ref,
        previous_generation=parent_gen,symbols={code:dict(source_generation=source_gen,source_snapshot=source_ref,retained_sync_ref=skipped_ref)})
    c.recovery_ref=save(c.root/'recovery.json',c.recovery)
    next(r for r in c.sync['symbol_reconciliation']if r['symbol']==code[:6])['source_sha256_after']=q.sha(live)
    c.sync_ref=save(c.root/'sync.json',c.sync)
    c.reactivated=code;c.source_item=old;c.source_ref=source_ref;c.source_bytes=raw
    return c


def test_retained_reactivation_exact_bytes_and_full_prefix(retained_case):
    c=retained_case;values=candidate(c);item=values[c.reactivated]
    native=next(r for r in item['raw_files']if r['source_role']=='native')
    assert item['native_tail_proof']['retained_native_recovery']==c.recovery_ref
    assert q.raw32_source_sha(native)==hashlib.sha256(c.source_bytes+bar(TARGET)).hexdigest()
    expected_native=c.root/'legacy_merged.day';expected_native.write_bytes(c.source_bytes+bar(TARGET))
    expected=copy.deepcopy(c.source_item);expected['raw_files']=[dict(ref(expected_native),source_role='native')if r['source_role']=='native'else r for r in expected['raw_files']]
    pd.testing.assert_frame_equal(q.resolved_raw_history(c.reactivated,item,TARGET,c.driver),
                                  q.resolved_raw_history(c.reactivated,expected,TARGET,c.driver),check_exact=True)
    driver_path=os.environ.get('QFQ_TEST_DRIVER');formula_path=os.environ.get('QFQ_TEST_FORMULA')
    if driver_path and formula_path:
        import importlib.util
        path=ROOT/'docs/handoffs/daily_incremental_io_20261111/research_panel_qfq.before.py'
        spec=importlib.util.spec_from_file_location('retained_original_oracle',path)
        original=importlib.util.module_from_spec(spec);spec.loader.exec_module(original)
        driver,_=original.authorities(Path(driver_path),Path(formula_path))
        pd.testing.assert_frame_equal(q.rebuild_symbol(c.reactivated,item,TARGET,driver),
                                      original.rebuild_symbol(c.reactivated,expected,TARGET,driver),check_exact=True)


@pytest.mark.parametrize('failure',['generation','parent','target','membership','coverage','traded_skip','native','unlisted','current_gap'])
def test_retained_reactivation_rejects_unbound_evidence(retained_case,failure):
    c=retained_case;entry=c.recovery['symbols'][c.reactivated]
    if failure in {'generation','parent'}:
        path=Path(entry['source_generation']['path']);value=json.loads(path.read_text())
        if failure=='generation':value['generation_id']='f'*64
        else:value['candidate_sha256']['selector']='a'*64
        entry['source_generation']=save(path,value)
    if failure=='target':c.recovery['target_date']=20261124
    if failure=='membership':
        c.previous['retained_history_codes']=[];c.previous_ref=save(c.root/'retained_snapshot.json',c.previous)
    if failure=='coverage':
        path=Path(entry['retained_sync_ref']['path']);value=json.loads(path.read_text());value['symbol_reconciliation'][0]['last_date_after']=PREVIOUS
        entry['retained_sync_ref']=save(path,value)
    if failure=='traded_skip':
        skipped_root=c.root/'skipped'
        changed=package(skipped_root,target=PREVIOUS,previous=20261119)
        descriptor=json.loads(Path(changed['path']).read_text())
        path=Path(entry['retained_sync_ref']['path']);value=json.loads(path.read_text())
        value['official_daily_source'].update(input_ref=changed,package=descriptor['package'])
        entry['retained_sync_ref']=save(path,value)
    if failure in {'coverage','traded_skip'}:
        # Reseal all outer witnesses so refusal tests the business proof,
        # rather than merely rejecting an outdated outer SHA.
        c.previous['source_files']=[entry['retained_sync_ref']]
        c.previous_ref=save(c.root/'retained_snapshot.json',c.previous)
        source=json.loads(Path(entry['source_generation']['path']).read_text())
        parent=json.loads(Path(c.recovery['previous_generation']['path']).read_text())
        c.recovery.update(previous_snapshot=c.previous_ref,previous_generation=generation(c,'retained_generation',
            c.previous_ref,source['candidate_sha256'],parent['candidate_sha256']))
    if failure=='native':Path(c.source_item['raw_files'][1]['path']).write_bytes(c.source_bytes+b'bad')
    if failure=='unlisted':c.recovery['symbols']={}
    if failure=='current_gap':
        live=c.tdx/'vipdoc/sz/lday/sz000001.day';live.write_bytes(c.source_bytes+bar(PREVIOUS)+bar(TARGET))
        next(r for r in c.sync['symbol_reconciliation']if r['symbol']==c.reactivated[:6])['source_sha256_after']=q.sha(live)
        c.sync_ref=save(c.root/'sync.json',c.sync)
    c.recovery_ref=save(c.root/'recovery.json',c.recovery)
    with pytest.raises(q.QfqGateError,match='RETAINED_NATIVE_SKIPPED_SESSION_UNPROVED' if failure in {'coverage','traded_skip'} else None):candidate(c)


def test_retained_input_continues_next_daily_without_exception(retained_case):
    c=retained_case;values=candidate(c);today=dict(c.previous,asof_date=TARGET,symbols=values,retained_history_codes=[])
    today_ref=save(c.root/'today.json',today)
    next_root=c.root/'next';next_root.mkdir()
    next_input=package(next_root,target=20261124,previous=TARGET)
    descriptor=json.loads(Path(next_input['path']).read_text())
    sync=copy.deepcopy(c.sync);sync['target_date']='20261124';sync['official_daily_source']=dict(
        source_kind='TDX_OFFICIAL_G4DAY',input_ref=next_input,package=descriptor['package'],previous_session=TARGET)
    for row in sync['symbol_reconciliation']:
        live=Path(row['path']);live.write_bytes(live.read_bytes()+bar(20261124));row['source_sha256_after']=q.sha(live)
    sync_ref=save(c.root/'next_sync.json',sync)
    next_values=inputs._daily_native_bindings(c.config,today_ref,sync_ref,20261124,c.tdx,c.driver)
    item=next_values[c.reactivated]
    assert 'retained_native_recovery' not in item['native_tail_proof']
    actual=q.resolved_raw_history(c.reactivated,item,20261124,c.driver)
    assert actual.trade_date.tolist()[-3:]==[20261119,TARGET,20261124]
    assert q.raw32_source_sha(next(r for r in item['raw_files']if r['source_role']=='native'))==hashlib.sha256(c.source_bytes+bar(TARGET)+bar(20261124)).hexdigest()


def test_unchanged_reuses_decoded_sources_without_old_decode(case):
    c=case; values=candidate(c); code='000001.SZ'; item=values[code]
    raw=q.resolved_raw_history(code,item,TARGET,c.driver)
    table=pa.Table.from_pandas(raw,preserve_index=False)
    calls=[]
    def observed(*a,**kw):calls.append(a[1]);return decoder(*a,**kw)
    c.driver.read_day_tail=observed
    rules={k:k for k in ('driver_sha256','formula_sha256','user_formula_sha256','field_contract_sha256')}
    context=dict(target=TARGET,snapshot=dict(symbols=values),driver=c.driver,run_dir=c.root/'candidate',
        currents=dict(selector=c.root/'selector'),contracts=dict(selector=rules),baseline_hashes={},identity={})
    namespace={**vars(q),'rebuild_symbol':lambda *a:pytest.fail('unchanged source recomputed')}
    prepared=delta._prepare(namespace,context,code,dict(selector={code:table}),
        dict(asof_date=TARGET,symbols=values),dict(selector=table.schema),rules)
    assert prepared['kind']=='UNCHANGED' and prepared['computed'] is None and len(calls)==2


def test_shared_official_package_is_parsed_once_and_sync_duplicates_refuse(case,monkeypatch):
    c=case; values=candidate(c)
    from ops._a_share_daily_sync_parts import official_daily_package as official
    calls=[]; parse=official.parse_package
    def observed(*a,**kw):calls.append(a[1]);return parse(*a,**kw)
    monkeypatch.setattr(official,'parse_package',observed)
    q._native_official_package.cache_clear()
    for code,item in values.items():q.resolved_raw_history(code,item,TARGET,c.driver)
    assert calls==[TARGET]
    c.sync['symbol_reconciliation'].append(c.sync['symbol_reconciliation'][0])
    duplicate=save(c.root/'duplicate_sync.json',c.sync)
    with pytest.raises(q.QfqGateError,match='NATIVE_SYNC_DUPLICATE_IDENTITY'):
        q._native_sync_rows(duplicate['path'],duplicate['sha256'],q._native_proof_stamp(duplicate['path']))


@pytest.mark.parametrize('revision',[False,True])
def test_full_prefix_oracle_and_no_baseline_decode(case,monkeypatch,revision):
    driver_path=os.environ.get('QFQ_TEST_DRIVER'); formula_path=os.environ.get('QFQ_TEST_FORMULA')
    if not driver_path or not formula_path:pytest.skip('set pinned authority paths for full numerical oracle')
    import importlib.util
    source=ROOT/'docs/handoffs/daily_incremental_io_20261111/research_panel_qfq.before.py'
    spec=importlib.util.spec_from_file_location('native_original_oracle',source)
    original=importlib.util.module_from_spec(spec);spec.loader.exec_module(original)
    driver,_=original.authorities(Path(driver_path),Path(formula_path))
    c=case; c.driver=driver; values=candidate(c); code='000001.SZ'
    item=values[code]
    if revision:item['events']=[dict(ex_date=TARGET,a=1.,b=-.15,volume_a=1.2)]
    legacy=inputs.history_raw_bindings(c.config,c.root/'oracle/binding.json',driver,TARGET,current_tdx_root=c.tdx)
    legacy[code]['events']=item['events']
    expected=original.rebuild_symbol(code,legacy[code],TARGET,driver)
    before=original.rebuild_symbol(code,c.previous['symbols'][code],PREVIOUS,driver)
    inferred=pa.Table.from_pandas(expected,preserve_index=False).schema
    # Production role contracts type nullable fields explicitly; pandas alone
    # infers Arrow null for the deliberately unknown listing-date context.
    schema=pa.schema([pa.field(f.name,pa.int64() if pa.types.is_null(f.type) else f.type) for f in inferred])
    table=pa.Table.from_pandas(before,schema=schema,preserve_index=False)
    calls=[];read=driver.read_day_tail
    def observed(*args,**kwargs):calls.append(str(args[1]));return read(*args,**kwargs)
    monkeypatch.setattr(driver,'read_day_tail',observed)
    rules={k:k for k in ('driver_sha256','formula_sha256','user_formula_sha256','field_contract_sha256')}
    context=dict(target=TARGET,snapshot=dict(symbols=values),driver=driver,run_dir=c.root/'candidate',
        currents=dict(selector=c.root/'selector'),contracts=dict(selector=rules),baseline_hashes=dict(selector='baseline'),identity={})
    prepared=delta._prepare(vars(q),context,code,dict(selector={code:table}),c.previous,dict(selector=schema),rules)
    assert prepared['kind']==('FACTOR_REVISION' if revision else 'APPEND')
    assert prepared['baseline_proof'][0]['kind']=='IMMUTABLE_COMPONENT_PREFIX'
    pd.testing.assert_frame_equal(prepared['computed'],expected,check_exact=True)
    assert len(calls)==2  # archive + concatenated native; no old-baseline decoder.
    fresh=pa.Table.from_pandas(prepared['computed'],schema=schema,preserve_index=False)
    patch=delta.changed_rows(table,fresh)
    assert len(patch)>1 if revision else len(patch)==1


@pytest.mark.parametrize('retained',[False,True])
def test_normal_entry_passes_paired_committed_input(request,monkeypatch,retained):
    """Observe ordinary owner path through real raw-input binding, stop pre-build."""
    c=request.getfixturevalue('retained_case' if retained else 'case'); pointers={}
    for role in ('selector','backtest'):
        pointers[role]=c.root/(role+'.txt'); pointers[role].write_text(str(c.root/(role+'.parquet')))
        q.pq.write_table(pa.table(dict(ts_code=['000001.SZ'],trade_date=[PREVIOUS])),c.root/(role+'.parquet'))
    monkeypatch.setattr(q,'authorities',lambda *a:(c.driver,None))
    monkeypatch.setattr(q,'accepted_history_retention',lambda *a:c.config)
    monkeypatch.setattr(q,'selected_history_retention',lambda *a,**kw:c.config)
    monkeypatch.setattr(q,'required_a_history',lambda *a:{'000001.SZ':c.dates[0]})
    contract=dict(adjustment_snapshot=c.previous_ref)
    if retained:contract['generation_id']=json.loads(Path(c.recovery['previous_generation']['path']).read_text())['generation_id']
    monkeypatch.setattr(q,'panel_contract',lambda *a:contract)
    from ops import research_panel_daily_source
    monkeypatch.setattr(research_panel_daily_source,'build_cache_configuration',lambda **kw:{'fixture':True})
    class ObservedEntry(Exception):pass
    def prepare(**kw):
        assert kw['previous_snapshot']==c.previous_ref and kw['retained_history']==c.config
        assert kw['retained_native_recovery']==getattr(c,'recovery_ref',None)
        assert candidate(c)['000001.SZ']['native_tail_proof']['added_dates']==[TARGET]
        raise ObservedEntry
    monkeypatch.setattr(inputs,'prepare_snapshot',prepare)
    with pytest.raises(ObservedEntry):
        q.run_daily_rebuild(driver_path=c.root/'driver',formula_path=c.root/'formula',tdx_root=c.tdx,
            data_root=c.root/'data',pointers=pointers,contract_csv=c.root/'contract',return_root=c.root/'runs',
            target=TARGET,refresh_inputs=True,compute_backend='thread',workers=1,publish=False,
            retained_native_recovery=getattr(c,'recovery_ref',None))


def test_authority_only_forwards_explicit_retained_input(retained_case,monkeypatch):
    import ast
    from ops import research_storage_retention as retention
    c=retained_case;path=ROOT/'ops/macos_research_panel_daily_authority.py'
    node=next(n for n in ast.parse(path.read_text()).body if isinstance(n,ast.FunctionDef)and n.name=='run_windows_a_formula_authority')
    namespace=dict(Path=Path,Any=object,__file__=str(path),_date=lambda x:x,_ensure_pointer_seed=lambda *a:None)
    exec(compile(ast.Module(body=[node],type_ignores=[]),str(path),'exec'),namespace)
    class Observed(Exception):pass
    def guarded(call,**kwargs):
        assert call is q.run_daily_rebuild and kwargs['retained_native_recovery']==c.recovery_ref
        assert kwargs['storage_layout']=='arrow_blocks_v1' and kwargs['refresh_inputs'] is True
        raise Observed
    monkeypatch.setattr(retention,'run_with_retention',guarded)
    with pytest.raises(Observed):
        namespace['run_windows_a_formula_authority'](c.root/'script',tdx_root=c.tdx,data_root=c.root/'data',
            selector_pointer=c.root/'selector.txt',backtest_pointer=c.root/'backtest.txt',selector_seed=None,backtest_seed=None,
            contract_csv=c.root/'contract',canonical_formula_path=c.root/'formula',return_root=c.root/'runs',
            target_date=str(TARGET),retained_native_recovery=c.recovery_ref)
