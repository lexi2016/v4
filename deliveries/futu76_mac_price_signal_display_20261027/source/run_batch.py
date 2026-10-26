"""This exact-76 batch only: original producer kernel and consumer readback.

No network, default-pointer mutation, training, return evaluation, or publisher.
"""
from pathlib import Path
import csv
import hashlib
import importlib.util
import json
import sys
import time

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq

B = Path(__file__).resolve().parent
W = Path('/Users/lexi/.codex/worktrees/futu76-mac-integration-20261026/v4_app')
S = B.parent / 'futu_qfq76_export_20261026_r1'
FULL = S / 'outputs/full/FUTU_QFQ76_EXPORT_20261026_01'
STATE = Path('/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/数据')
VENDOR = Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/local-panel-history-source-20261024-r1/app/ops/vendor')
sys.path.insert(0, str(W))
from ops import research_panel_qfq as q


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def ref(p):
    return dict(path=str(p), sha256=sha(p))


def save(p, value):
    q._json(Path(p), value)


def api_module():
    p = W / 'apps/api/v35_api/a_share_panel_history.py'
    spec = importlib.util.spec_from_file_location('batch_exact76_api', p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def run(phase):
    assert phase in {'canary', 'full'}
    c = json.loads((B / 'EXECUTION_CONTRACT.json').read_text())
    for r in c['bound_identity_refs']:
        assert sha(r['path']) == r['sha256'], r
    out = B / phase
    if (out / 'RESULT.json').exists():
        raise RuntimeError('COMPLETED_PHASE_MUST_NOT_RERUN')
    out.mkdir(exist_ok=(phase == 'full'))
    rows = list(csv.DictReader((S / 'universe_request_76.csv').open(encoding='utf-8-sig')))
    chosen = [r for r in rows if r['ts_code'] == '000523.SZ'] if phase == 'canary' else rows
    if phase == 'full':
        canary = json.loads((B / 'canary/RESULT.json').read_text())
        assert canary['status'] == 'PASS_SINGLE_STOCK_ORIGINAL_CONSUMER_CORE'
    driver, _ = q.authorities(VENDOR / 'data_layer_daily_formula_increment_update_v1.py',
                              VENDOR / 'build_canonical_formula_research_panel.py')
    api = api_module()
    features, statuses, entries = [], [], {}
    t0 = time.monotonic()
    for index, record in enumerate(chosen):
        code, futu = record['ts_code'], record['futu_code']
        previous = B / 'canary' if phase == 'full' and code == '000523.SZ' else None
        if previous:
            result = json.loads((previous / 'RESULT.json').read_text())
            status = result['stocks'][0]
            frame = pd.read_parquet(previous / (code + '.parquet'))
            item = result['candidate']['symbols'][code]
            status = {**status, 'reused_canary': True}
        else:
            summary = json.loads((FULL / 'stocks' / futu / 'QFQ_summary.json').read_text())
            source = S / summary['combined_path']
            item = dict(source=ref(source), source_kind=q.DIRECT_QFQ_KIND,
                adjustment_anchor='UNKNOWN_NONPIT', volume_basis='FUTU_SDK_NATIVE_UNSCALED',
                amount_basis='FUTU_SDK_TURNOVER_UNSCALED',
                history_start_date=summary['first_date'].replace('-', ''))
            assert item['source']['sha256'] == summary['combined_sha256']
            try:
                assert summary['status'] in ('SUCCESS', 'SUCCESS_HISTORY_START_AFTER_REQUESTED_START')
                assert summary['page_ended'] is True
                stock_path = out / (code + '.parquet')
                resumed = stock_path.exists()
                if resumed:
                    frame = pd.read_parquet(stock_path)
                    assert frame.source_sha256.eq(item['source']['sha256']).all()
                    assert frame.source.eq(q.DIRECT_QFQ_KIND).all()
                else:
                    frame = q.rebuild_direct_qfq_symbol(code, item, 20261026, driver)
                assert len(frame) == summary['row_count']
                assert frame[list(api.SIGNALS)].notna().all().all()
                assert frame[list(api.SIGNALS)].isin([0, 1]).all().all()
                assert frame.trade_date.astype(int).max() == 20261026
                frame['trade_date'] = frame.trade_date.astype(int)
                if not resumed:
                    frame.to_parquet(stock_path, index=False)
                capture = [json.loads((S / p).read_text()) for p in summary['page_receipt_paths']]
                item['capture_started_at'] = capture[0]['request_started_at_utc']
                item['capture_returned_at'] = capture[-1]['request_returned_at_utc']
                item['row_count'] = len(frame)
                item['source_summary'] = ref(FULL / 'stocks' / futu / 'QFQ_summary.json')
                item['page_count'] = summary['page_count']
                status = dict(ts_code=code, status='CANDIDATE_GENERATED', source=item['source'],
                    rows=len(frame), first_date=str(frame.trade_date.min()), last_date=str(frame.trade_date.max()),
                    nonnull_binary_signal_cells=int(frame[list(api.SIGNALS)].size),
                    short_observed_history=summary['history_start_after_requested_start'],
                    source_mapping='OHLC/volume identity; turnover→amount identity; volume→vol identity',
                    resumed_saved_checkpoint=resumed)
            except Exception as error:
                status = dict(ts_code=code, status='CANNOT_CONFIRM', first_error_type=type(error).__name__,
                              first_error=str(error), source=item['source'])
                statuses.append(status)
                save(out / 'progress.json', dict(processed=len(statuses), total=len(chosen), last=status))
                if phase == 'canary':
                    raise
                continue
        features.append(frame)
        entries[code] = item
        statuses.append(status)
        save(out / 'progress.json', dict(processed=len(statuses), total=len(chosen), last=status,
             elapsed_seconds=time.monotonic()-t0))
    assert features
    combined = pd.concat(features, ignore_index=True)
    assert not combined[['ts_code', 'trade_date']].duplicated().any()
    metadata = dict(source_kind=q.DIRECT_QFQ_KIND, asof_date='20261026',
        source_hashes={k: v['source']['sha256'] for k,v in entries.items()},
        adjustment_anchor='UNKNOWN_NONPIT', volume_basis='FUTU_SDK_NATIVE_UNSCALED',
        amount_basis='FUTU_SDK_TURNOVER_UNSCALED', producer_sha256=sha(q.__file__),
        formula_sha256=q.FORMULA_SHA, user_formula_sha256=q.USER_FORMULA_SHA)
    table = pa.Table.from_pandas(combined, preserve_index=False)
    table = table.replace_schema_metadata({**(table.schema.metadata or {}),
        b'futu_direct_qfq76_v1': json.dumps(metadata, sort_keys=True).encode()})
    artifact = out / 'futu_direct_qfq76_candidate.parquet'
    pq.write_table(table, artifact)
    candidate = dict(schema='futu_direct_qfq76_consumer_candidate_v1', **metadata,
        signal_fields=list(api.SIGNALS), universe=ref(S / 'universe_request_76.csv'), symbols=entries,
        artifact=ref(artifact), artifact_metadata=metadata,
        reader_sha256=sha(STATE/'data_layer_interface_current/DATA_LAYER_INTERFACE.py'),
        research_only=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)
    save(out / 'candidate_manifest.json', candidate)
    # Content sample fixed before execution: 000523, 600030, 601868. Canary is
    # reused in full. No all-stock semantic re-audit, full payload recalc or API.
    samples = ['000523.SZ'] if phase == 'canary' else ['600030.SH', '601868.SH']
    checks = []
    for code in samples:
        if code not in entries:
            checks.append(dict(ts_code=code, status='CANNOT_CONFIRM_GENERATION_FAILED'))
            continue
        api._request(code, '20261019', '20261026', api.VERSION)
        got = api._direct_qfq_rows(STATE, candidate, code, '20261019', '20261026')
        source = pd.read_parquet(entries[code]['source']['path'])
        recent = source.loc[source.time_key.str[:10].ge('2026-10-19')]
        assert len(got['rows']) == len(recent) == 6
        expected = combined.loc[combined.ts_code.eq(code)&combined.trade_date.ge(20261019)]
        for column in ('open','high','low','close','volume'):
            assert np.array_equal([row[column] for row in got['rows']], recent[column].to_numpy())
        assert np.array_equal([row['amount'] for row in got['rows']], recent.turnover.to_numpy())
        for column in api.SIGNALS:
            assert np.array_equal([row[column] for row in got['rows']], expected[column].to_numpy())
        for column in ('BBI','zge_white_line','zge_yellow_line','ma60','J','macd_dif','macd_dea','macd_hist'):
            assert np.isfinite([row[column] for row in got['rows']]).all()
            np.testing.assert_allclose([row[column] for row in got['rows']],expected[column].to_numpy(),rtol=1e-13,atol=1e-13)
        save(out / (code + '_api_core.json'), got)
        checks.append(dict(ts_code=code,status='PASS_ORIGINAL_READER_API_CORE',rows=6,
            signals=23,price_volume_amount='IDENTICAL_TO_SDK_SOURCE',identity=got['identity']))
    # Only 3 representative current windows; predicate/columns reach Arrow
    # before materialization. This is evidence of coordinate differences, never
    # permission to replace the preserved default data.
    comparisons=[]
    baseline=json.loads((B/'BASELINE_FRESH.json').read_text())
    panel=Path(baseline['expected_current']['value']['roles']['selector']['target_path'])
    for code in (['000523.SZ'] if phase=='canary' else ['600030.SH','601868.SH']):
        if code not in entries: continue
        dataset=ds.dataset(panel,format='parquet')
        date_type=dataset.schema.field('trade_date').type
        cast=str if pa.types.is_string(date_type) or pa.types.is_large_string(date_type) else int
        filt=(ds.field('ts_code')==code)&(ds.field('trade_date')>=cast('20261019'))&(ds.field('trade_date')<=cast('20261026'))
        cols=['ts_code','trade_date','open','high','low','close','volume',*api.SIGNALS]
        old=dataset.scanner(columns=cols,filter=filt).to_table().to_pandas()
        old['trade_date']=old.trade_date.astype(int)
        new=combined.loc[combined.ts_code.eq(code)&combined.trade_date.ge(20261019)]
        joined=old.merge(new,on=['ts_code','trade_date'],suffixes=('_old','_new'))
        comparisons.append(dict(ts_code=code,current_rows=len(old),candidate_rows=len(new),overlap=len(joined),
            differing_cells={col:int(joined[col+'_old'].ne(joined[col+'_new']).sum()) for col in ['open','high','low','close','volume',*api.SIGNALS]}))
    save(out/'CURRENT_COMPARISON_SAMPLE.json', comparisons)
    accepted=len(entries)
    result=dict(status=('PASS_SINGLE_STOCK_ORIGINAL_CONSUMER_CORE' if phase=='canary' else 'PREPARED_ORIGINAL_CONSUMER_CANDIDATE')
        if all(x['status'].startswith('PASS') for x in checks) else 'CANNOT_CONFIRM',
        phase=phase,accepted_candidates=accepted,total=len(chosen),rows=len(combined),
        page_total=sum(v['page_count'] for v in entries.values()),stocks=statuses,
        candidate=candidate,candidate_manifest=ref(out/'candidate_manifest.json'),content_samples=checks,
        elapsed_seconds=time.monotonic()-t0,canonical_mutations=0,publish=False,
        api_core_only=True,api_activation='PENDING_INDEPENDENT_REVIEW_AND_ROOT_CAS',
        ui='NOT_RUN',historical_PIT=False,research_only=True,production_allowed=False,buy_gate_updated=False,orders_sent=False)
    save(out/'RESULT.json', result)
    print(json.dumps({k:result[k] for k in ['status','phase','accepted_candidates','total','rows','page_total','elapsed_seconds']}))


if __name__ == '__main__':
    run(sys.argv[1])
