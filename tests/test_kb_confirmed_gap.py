import json
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ops import research_panel_qfq as q
from ops.kb_confirmed_gap import (DIAGNOSTICS, FIELDS, helper_sha256s, prefix_hashes,
                                  project_selected, project_with_reuse, rule_sha256)


def bars(count=130):
    result=[]
    previous=20.0
    for i in range(count):
        close=round(20+i*0.01, 2)
        result.append({'ts_code':'002865.SZ', 'trade_date':int((date(2025,1,1)+timedelta(days=i)).strftime('%Y%m%d')),
            'open':close-0.1, 'high':close+0.2, 'low':close-0.2, 'close':close, 'vol':1000.0,
            'pre_close':previous, 'pct_chg':round((close/previous-1)*100,2),
            'kb_double_gun':False if i>=23 else None, 'kb_violence_k':False if i>=20 else None,
            'kb_yidong_vol_ratio_5':1.0 if i>=5 else None})
        previous=close
    return pd.DataFrame(result)


def test_selected_full_prefix_respects_124_boundary_and_no_future_input():
    frame=bars()
    result=project_selected(frame,[12,13,122,123,129])
    assert result[122][0]['kb_rebuild'] is None
    assert result[122][1]['kb_rebuild_reason']=='INSUFFICIENT_HISTORY'
    assert result[123][0]['kb_rebuild'] is not None
    assert set(result[129][0])==FIELDS|{'kb_rebuild'}
    assert set(result[129][1])==set(DIAGNOSTICS)
    changed=frame.copy();changed.loc[129,'close']+=0.01
    assert project_selected(changed,[123])[123]==result[123]


def test_verified_prefix_cache_reuses_only_unchanged_rows_and_rejects_calendar_drift():
    frame=bars();saved=project_selected(frame,list(range(len(frame))))
    old=frame.copy()
    for name in FIELDS|{'kb_rebuild'}:
        old[name]=[saved[i][0][name] for i in range(len(frame))]
    hashes=prefix_hashes(frame)
    sidecar=[{'ts_code':'002865.SZ','trade_date':str(row.trade_date),
              'diagnostics_json':json.dumps(saved[i][1],sort_keys=True),
              'prefix_input_sha256':hashes[i]} for i,row in enumerate(frame.itertuples())]
    calendar='a'*64
    prior={'frame':old,'sidecar':sidecar,'metadata':{'symbol':'002865.SZ','calendar_sha256':calendar,
        'confirmed_gap_contract_sha256':rule_sha256(),'helper_sha256':helper_sha256s(),
        'price_basis':'QFQ_ASOF','volume_basis':'QFQ_EVENT_VOLUME'}}
    extended=bars(131)
    values,_,stats=project_with_reuse(extended,prior=prior,calendar_sha256=calendar)
    assert stats['reused_rows']==130 and stats['computed_rows']==1
    assert values[129]==saved[129]
    revised=extended.copy();revised.loc[125,'vol']+=1
    _,_,stats=project_with_reuse(revised,prior=prior,calendar_sha256=calendar)
    assert stats['reused_rows']==125 and stats['computed_rows']==6
    with pytest.raises(ValueError,match='REUSE_IDENTITY_CONFLICT'):
        project_with_reuse(extended,prior=prior,calendar_sha256='b'*64)
    sidecar[0]['prefix_input_sha256']='0'*64
    with pytest.raises(ValueError,match='REUSE_PREFIX_CONFLICT'):
        project_with_reuse(extended,prior=prior,calendar_sha256=calendar)


def test_real_vendor_write_rejects_incomplete_extension_and_preserves_nulls(tmp_path):
    driver=q._load(Path(q.__file__).parent/'vendor/data_layer_daily_formula_increment_update_v1.py',
                   q.DRIVER_SHA,'confirmed_gap_test_vendor')
    source=bars(30);projected=project_selected(source,list(range(len(source))))
    for name in FIELDS|{'kb_rebuild'}:
        source[name]=[projected[i][0][name] for i in range(len(source))]
    source=source[['trade_date','ts_code','kb_rebuild',*sorted(FIELDS)]]
    types={'string':pa.string(),'bool':pa.bool_(),'double':pa.float64(),'int32':pa.int32()}
    legacy=pa.schema([pa.field('trade_date',pa.int32()),pa.field('ts_code',pa.string()),pa.field('kb_rebuild',pa.bool_())])
    complete=pa.schema(list(legacy)+[pa.field(name,types[typ]) for name,typ in q.SINGLE_GAP_FIELD_TYPES.items()])
    assert not q._single_gap_pair_mode({'selector':legacy,'backtest':legacy})
    assert q._single_gap_pair_mode({'selector':complete,'backtest':complete})
    partial=pa.schema(list(complete)[:-1])
    with pytest.raises(q.QfqGateError,match='SINGLE_GAP_PARTIAL_SCHEMA'):
        q._single_gap_pair_mode({'selector':partial,'backtest':partial})
    declared=legacy.with_metadata({q.META_KEY:json.dumps({'confirmed_gap_enabled':True}).encode()})
    with pytest.raises(q.QfqGateError,match='SINGLE_GAP_SCHEMA_MODE_CONFLICT'):
        q._single_gap_pair_mode({'selector':declared,'backtest':declared})
    with pytest.raises(q.QfqGateError,match='SINGLE_GAP_OUTPUT_WOULD_DROP_FIELDS'):
        q._table(source,legacy,driver,'backtest',confirmed_gap_enabled=True)
    actual=q._table(source,complete,driver,'backtest',confirmed_gap_enabled=True)
    output=tmp_path/'gap.parquet';pq.write_table(actual,output);read=pq.read_table(output)
    assert read['kb_rebuild'][-1].as_py() is None
    assert read['kb_violence_k_type'][-1].as_py() is None
    assert read['kb_brick_trend'][-1].as_py() in ('RED','GREEN')


def test_checkpoint_persists_gap_sidecar_and_refuses_changed_resume(tmp_path):
    driver=q._load(Path(q.__file__).parent/'vendor/data_layer_daily_formula_increment_update_v1.py',
                   q.DRIVER_SHA,'confirmed_gap_checkpoint_vendor')
    source=bars().rename(columns={'vol':'volume'}).assign(ma60=20.0,zge_yellow_line=20.0)
    raw=tmp_path/'source.parquet';pq.write_table(pa.Table.from_pandas(source,preserve_index=False),raw)
    recovered={'002865.SZ':{'artifact':{'path':str(raw),'sha256':q.sha(raw)}}}
    parts=tmp_path/'parts';parts.mkdir()
    identity={'single_yidong_enabled':True,'confirmed_gap_enabled':True,'input_sha256':'a'*64,
              'confirmed_gap_snapshot_file_sha256':'b'*64}
    _,checkpoint=q._symbol_checkpoint('002865.SZ',{},20261030,identity,parts,recovered,driver,False,'c'*64)
    output=pq.read_table(checkpoint)
    receipt=json.loads((parts/'002865.SZ.receipt.json').read_text())
    sidecar=Path(receipt['confirmed_gap_sidecar']['path'])
    table=pq.read_table(sidecar);meta=json.loads(table.schema.metadata[b'v4.a_share.kb_gap_diagnostics.v1'])
    assert table.column_names==['ts_code','trade_date','diagnostics_json','prefix_input_sha256']
    assert len(table)==len(output)==130 and meta['generation_id']=='c'*64
    assert meta['calendar_status']=='CANNOT_CONFIRM' and meta['calendar_sha256'] is None
    assert output['kb_rebuild'][122].as_py() is None and output['kb_rebuild'][123].as_py() is not None
    assert q._symbol_checkpoint('002865.SZ',{},20261030,identity,parts,recovered,driver,False,'c'*64)[1]==checkpoint
    sidecar.write_bytes(b'changed')
    with pytest.raises(q.QfqGateError,match='SOURCE_BINDING_FAILED'):
        q._symbol_checkpoint('002865.SZ',{},20261030,identity,parts,recovered,driver,False,'c'*64)
