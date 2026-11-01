"""Bounded tests for opt-in A-share widening in the existing QFQ owner."""
from datetime import date, timedelta
import json
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ops import research_panel_qfq as q
from ops.kb_hold_score import score_history


def test_full_contract_adds_107_nullable_fields_and_rejects_partial_schema():
    path=Path(q.__file__).resolve().parents[1]/'contracts/a_share_kb_full_research_v1.json'
    spec=q.full_research_contract({'path':str(path),'sha256':q.sha(path)})
    original=pa.schema([pa.field('trade_date',pa.string()),pa.field('ts_code',pa.string())])
    full=q.full_research_schema(original,spec)
    assert len(full)==len(original)+107
    assert all(full.field(f.name)==f for f in original)
    assert all(full.field(n).nullable for n in set(full.names)-set(original.names))
    declared=q._full_research_schema_declaration(original,spec,q.sha(path))
    pair={'selector':declared,'backtest':declared}
    assert q._single_feedback_pair_mode(pair) and q._single_action_pair_mode(pair)
    assert q._single_yidong_pair_mode(pair) and q._single_gap_pair_mode(pair) and q._single_n_pair_mode(pair)
    with pytest.raises(q.QfqGateError,match='FULL_RESEARCH_PARTIAL_SCHEMA'):
        q.full_research_schema(original.append(pa.field('kb_hold_score',pa.int8())),spec)
    bad=original.append(pa.field('kb_hold_score',pa.string()))
    with pytest.raises(q.QfqGateError,match='FULL_RESEARCH_PARTIAL_SCHEMA'):
        q.full_research_schema(bad,spec)
    with pytest.raises(q.QfqGateError,match='SOURCE_BINDING_FAILED'):
        q.full_research_contract({'path':str(path),'sha256':'f'*64})


def test_full_candidate_journals_and_pointer_files_must_be_isolated(tmp_path):
    pointers={'selector':tmp_path/'pointers/selector.txt','backtest':tmp_path/'pointers/backtest.txt'}
    assert q._validate_full_research_isolation(tmp_path,tmp_path/'data',tmp_path/'runs',pointers)==tmp_path.resolve()
    with pytest.raises(q.QfqGateError,match='FULL_RESEARCH_ISOLATION_PATH_ESCAPE'):
        q._validate_full_research_isolation(tmp_path,tmp_path/'data',tmp_path/'runs',dict(pointers,selector=tmp_path.parent/'selector.txt'))
    with pytest.raises(q.QfqGateError,match='FULL_RESEARCH_ISOLATION_OVERLAPS_ACTIVE_STATE'):
        q._validate_full_research_isolation(Path.home(),tmp_path/'data',tmp_path/'runs',pointers)


def test_full_entry_requires_reuse_and_cannot_publish(tmp_path):
    contract=Path(q.__file__).resolve().parents[1]/'contracts/a_share_kb_full_research_v1.json'
    ref={'path':str(contract),'sha256':q.sha(contract)}
    args=dict(driver_path=tmp_path/'driver',formula_path=tmp_path/'formula',tdx_root=tmp_path/'tdx',
        data_root=tmp_path/'data',pointers={'selector':tmp_path/'selector','backtest':tmp_path/'backtest'},
        contract_csv=tmp_path/'csv',return_root=tmp_path/'runs',target=20261030,
        full_research_contract_ref=ref,full_research_isolation_root=tmp_path)
    with pytest.raises(q.QfqGateError,match='FULL_RESEARCH_REUSE_REFERENCE_REQUIRED'):
        q.run_daily_rebuild(**args)
    with pytest.raises(q.QfqGateError,match='FULL_RESEARCH_ISOLATED_CANDIDATE_ONLY'):
        q.run_daily_rebuild(**args,publish=True)
    assert not (tmp_path/'data').exists()


def test_bulk_j_uses_both_source_gates_without_replacing_unknowns():
    rows=[]
    for i in range(12):
        close=10+i*.1
        rows.append(dict(trade_date=20261001+i,open=close-.1,high=close+.2,low=close-.2,
                         close=close,volume=100.,kb_b1_j=None))
    raw=score_history(rows)
    for row,score in zip(rows,raw):row['kb_b1_j']=score['kb_hold_j']
    known=q._bulk_feedback_projection('000063.SZ',rows)
    assert known[-1]['kb_hold_j_not_dead']==raw[-1]['kb_hold_j_not_dead']
    missing=[dict(row) for row in rows];missing[-1]['kb_b1_j']=None
    result=q._bulk_feedback_projection('000063.SZ',missing)
    assert result[-1]['kb_hold_j_not_dead'] is None
    assert result[-1]['kb_hold_j_not_dead_reason']=='BOUND_KB_J_UNAVAILABLE'
    assert result[-1]['kb_hold_score'] is None
    mismatch=[dict(row) for row in rows];mismatch[-1]['kb_b1_j']+=1
    with pytest.raises(ValueError,match='BOUND_KB_J_MISMATCH'):
        q._bulk_feedback_projection('000063.SZ',mismatch)
    invalid=[dict(row) for row in rows]
    invalid[0].update(high=-1.,low=-3.,close=-2.)
    result=q._bulk_feedback_projection('000063.SZ',invalid)
    assert result[-1]['kb_hold_j_not_dead'] is None
    assert result[-1]['kb_hold_j_not_dead_reason']=='INVALID_HLC_PREFIX'
    assert invalid[-1]['kb_b1_j'] is not None


def test_bulk_gap_stricter_input_is_unknown_without_mutating_57_signal(tmp_path):
    from ops import kb_confirmed_gap as gap
    rows=[]
    for i in range(26):
        close=-2. if i<5 else 10.
        rows.append(dict(ts_code='000063.SZ',trade_date=20261001+i,open=close,high=close+1.,low=close-1.,
                         close=close,vol=100.,pre_close=close,pct_chg=0.,kb_double_gun=False,
                         kb_violence_k=False,kb_yidong_vol_ratio_5=None))
    frame=pd.DataFrame(rows);proxy,masked=q._bulk_gap_strict_input_frame(frame)
    assert frame.loc[23,'kb_double_gun'] is False or frame.loc[23,'kb_double_gun']==False
    assert proxy.loc[23,'kb_double_gun'] is None and proxy.loc[23,'kb_violence_k'] is None
    assert masked['kb_double_gun']>0 and masked['kb_violence_k']>0
    with pytest.raises(ValueError,match='CONFIRMED_GAP_EXISTING_SIGNAL_INPUT_CONFLICT'):
        gap.project_selected(frame,[23])
    projected=gap.project_selected(proxy,[23])
    assert projected[23][0]['kb_violence_k_type'] is None
    assert projected[23][1]['kb_violence_k_components_status']=='INVALID_OR_UNBOUND_INPUT'
    contract=Path(q.__file__).resolve().parents[1]/'contracts/a_share_kb_full_research_v1.json'
    identity={'research_scope':'ADMITTED_A_SHARE','full_research_contract_sha256':q.sha(contract),
              'input_sha256':'a'*64,'confirmed_gap_snapshot_file_sha256':'b'*64}
    result,side=q._single_gap_daily('000063.SZ',frame,identity,tmp_path,'c'*64,'d'*64)
    assert result['kb_violence_k'].tolist()==frame['kb_violence_k'].tolist()
    saved=pq.read_table(side['path']);meta=json.loads(saved.schema.metadata[b'v4.a_share.kb_gap_diagnostics.v1'])
    assert saved['prefix_input_sha256'].to_pylist()==gap.prefix_hashes(frame)
    assert meta['prefix_hash_basis']=='ORIGINAL_UNMASKED_57_LABELS'
    assert meta['stricter_component_input_unavailable']==masked
    # A contradiction with valid inputs remains a hard failure.
    good=frame.copy();good[['open','high','low','close','pre_close']]=[10.,11.,9.,10.,10.]
    good.loc[23,'kb_double_gun']=True
    valid,_=q._bulk_gap_strict_input_frame(good)
    with pytest.raises(ValueError,match='CONFIRMED_GAP_DOUBLE_GUN_SOURCE_CONFLICT'):
        gap.project_selected(valid,[23])


def test_arrow_readback_checks_all_old_columns_null_nan_and_float_bits(tmp_path):
    old_path=tmp_path/'old.parquet';candidate=tmp_path/'candidate.parquet'
    dictionary=pa.array(['a','b','a']).dictionary_encode().cast(pa.dictionary(pa.int8(),pa.string()))
    old=pa.table({'ts_code':['000001.SZ']*3,'value':pa.array([None,float('nan'),-0.0],type=pa.float64()),
                  'category':dictionary})
    pq.write_table(old,old_path)
    def write(table):
        with pq.ParquetWriter(candidate,table.schema) as writer:
            writer.write_table(table,row_group_size=3)
            writer.write_table(table.slice(0,1),row_group_size=1)
    write(old.append_column('kb_b1',pa.array([None,True,False])))
    plan=[{'kind':'old','bucket':0,'rows':3},{'kind':'new','code':'920201.BJ','rows':1}]
    proof=q._verify_original_arrow_readback({0:old_path},candidate,plan,old.schema)
    assert proof['rows']==3 and proof['columns']==3
    changed=old.set_column(1,old.schema.field('value'),pa.array([None,float('nan'),0.0],type=pa.float64()))
    write(changed.append_column('kb_b1',pa.array([None,True,False])))
    with pytest.raises(q.QfqGateError,match='FULL_RESEARCH_READBACK_OLD_VALUE_CONFLICT:0:value'):
        q._verify_original_arrow_readback({0:old_path},candidate,plan,old.schema)


def test_widened_scope_persists_score_action_gap_and_n_for_admitted_a_only(tmp_path):
    symbol='000001.SZ';bars=[]
    for i in range(130):
        close=round(20+i*.01,2);previous=20 if not i else bars[-1]['close']
        bars.append(dict(ts_code=symbol,trade_date=int((date(2025,1,1)+timedelta(days=i)).strftime('%Y%m%d')),
            open=close-.1,high=close+.2,low=close-.2,close=close,volume=1000.,pre_close=previous,
            pct_chg=round((close/previous-1)*100,2),ma60=20.,zge_yellow_line=20.,
            kb_double_gun=False if i>=23 else None,kb_violence_k=False if i>=20 else None,
            kb_b1=False,kb_b2=False,kb_b3=False,kb_white_cross_down=False,kb_bull_rope_status='牵牛',
            kb_macd_veto=False,kb_brick_action='持有',kb_brick_flip_green=False,user_v1_sell_signal_daily=0))
    for row,score in zip(bars,score_history(bars)):row['kb_b1_j']=score['kb_hold_j']
    frame=pd.DataFrame(bars)
    assert q._single_feedback_daily(symbol,frame) is frame
    assert not q.research_code_in_scope('00700.HK','ADMITTED_A_SHARE')
    source=tmp_path/'source.parquet';pq.write_table(pa.Table.from_pandas(frame,preserve_index=False),source)
    recovered={symbol:{'artifact':{'path':str(source),'sha256':q.sha(source)}}};parts=tmp_path/'parts';parts.mkdir()
    contract=Path(q.__file__).resolve().parents[1]/'contracts/a_share_kb_full_research_v1.json'
    identity={'research_scope':'ADMITTED_A_SHARE','full_research_contract_sha256':q.sha(contract),
      'single_feedback_enabled':True,'single_action_enabled':True,'single_yidong_enabled':True,
      'confirmed_gap_enabled':True,'n_structure_enabled':True,'input_sha256':'a'*64,
      'confirmed_gap_snapshot_file_sha256':'b'*64,**q._n_sha256s()}
    _,result=q._symbol_checkpoint(symbol,{},20261030,identity,parts,recovered,None,True,'c'*64)
    table=pq.read_table(result);receipt=json.loads((parts/(symbol+'.receipt.json')).read_text())
    all_fields=q.SINGLE_FEEDBACK_FIELDS|q.SINGLE_ACTION_FIELDS|q.SINGLE_YIDONG_FIELDS|q.SINGLE_GAP_FIELDS
    assert len(all_fields)==50 and all_fields.issubset(table.column_names)
    assert table['kb_hold_score_min'][-1].as_py() is not None
    assert table['kb_action_rule_sha256'][-1].as_py()==q.action_rule_sha256()
    assert table['kb_yidong_rule_sha256'][-1].as_py()==q.yidong_rule_sha256()
    side=pq.read_table(receipt['confirmed_gap_sidecar']['path'])
    assert len(side)==len(table)==130 and len(json.loads(side['diagnostics_json'][-1].as_py()))==25
    assert receipt['n_structure_checkpoint']['sha256']==q.sha(receipt['n_structure_checkpoint']['path'])
    assert q._symbol_checkpoint(symbol,{},20261030,identity,parts,recovered,None,True,'c'*64)[1]==result
    with pytest.raises(q.QfqGateError,match='FULL_RESEARCH_CONTRACT_IDENTITY_CONFLICT'):
        q._symbol_checkpoint(symbol,{},20261030,{**identity,'full_research_contract_sha256':'f'*64},parts,recovered,None,True,'c'*64)


def test_full_seed_uses_original_pair_and_retains_foreign_arrow_values(tmp_path,monkeypatch):
    symbol='000001.SZ';rows=[]
    for i in range(130):
        close=round(20+i*.01,2);previous=20 if not i else rows[-1]['close']
        rows.append(dict(ts_code=symbol,trade_date=int((date(2025,1,1)+timedelta(days=i)).strftime('%Y%m%d')),
            open=close-.1,high=close+.2,low=close-.2,close=close,vol=1000.,pre_close=previous,
            pct_chg=round((close/previous-1)*100,2),ma60=20.,zge_yellow_line=20.,user_v1_sell_signal_daily=0))
    source=pd.DataFrame(rows)
    def append(frame):
        result=frame.copy()
        for name in q.KB_FIELDS:result[name]=None
        for row,score in zip(result.index,score_history(result.rename(columns={'vol':'volume'}).to_dict('records'))):
            result.at[row,'kb_b1_j']=score['kb_hold_j']
        for field,value in {'kb_b1':False,'kb_b2':False,'kb_b3':False,'kb_white_cross_down':False,
            'kb_bull_rope_status':'牵牛','kb_macd_veto':False,'kb_brick_action':'持有','kb_brick_flip_green':False}.items():result[field]=value
        result['kb_double_gun']=[False if i>=23 else None for i in range(len(result))]
        result['kb_violence_k']=[False if i>=20 else None for i in range(len(result))]
        return result
    monkeypatch.setattr(q,'append_kb_signals',append)
    selector=pa.Table.from_pandas(source.rename(columns={'vol':'volume'}),preserve_index=False)
    backtest=pa.Table.from_pandas(source,preserve_index=False)
    spools={};bucket=q._bucket(symbol)
    for role,table in [('selector',selector),('backtest',backtest)]:
        path=tmp_path/(role+'.parquet');pq.write_table(table,path);spools[role]={bucket:path}
    parts=tmp_path/'parts';parts.mkdir();run=tmp_path/'run';run.mkdir()
    contract=Path(q.__file__).resolve().parents[1]/'contracts/a_share_kb_full_research_v1.json'
    identity={'research_scope':'ADMITTED_A_SHARE','full_research_contract_sha256':q.sha(contract),
      'single_feedback_enabled':True,'single_action_enabled':True,'single_yidong_enabled':True,
      'confirmed_gap_enabled':True,'n_structure_enabled':True,'input_sha256':'a'*64,
      'confirmed_gap_snapshot_file_sha256':'b'*64,**q._n_sha256s()}
    snapshot={'symbols':{symbol:{'history_start_date':int(source.trade_date.iloc[0])}}}
    seeded=q._kb_seed_checkpoints(spools,snapshot,20261030,identity,{'selector':'1'*64,'backtest':'2'*64},parts,
                                  None,None,None,1,'thread',run,'c'*64)
    assert seeded==[symbol]
    with monkeypatch.context() as resume:
        resume.setattr(q,'append_kb_signals',lambda frame: (_ for _ in ()).throw(AssertionError('recomputed on resume')))
        assert q._kb_seed_checkpoints(spools,snapshot,20261030,identity,{'selector':'1'*64,'backtest':'2'*64},parts,
                                      None,None,None,1,'thread',run,'c'*64)==[symbol]
    extra=selector.slice(0,1).set_column(selector.schema.get_field_index('ts_code'),selector.schema.field('ts_code'),
                                         pa.array(['00700.HK'],type=selector.schema.field('ts_code').type))
    old=pa.concat_tables([selector.slice(0,2),extra]);spec=q.full_research_contract({'path':str(contract),'sha256':q.sha(contract)})
    schema=q.full_research_schema(old.schema,spec);out=q._kb_overlay_retained(old,schema,parts,full_research=True)
    assert out['ts_code'].to_pylist()==[symbol,symbol,'00700.HK']
    for field in old.schema:
        assert out[field.name].equals(old[field.name])
    assert out['kb_hold_score_min'][1].as_py() is not None
    for field in q.KB_FIELDS|q.SINGLE_FEEDBACK_FIELDS|q.SINGLE_ACTION_FIELDS|q.SINGLE_YIDONG_FIELDS|q.SINGLE_GAP_FIELDS:
        assert out[field][-1].as_py() is None
    name='ma60';field=selector.schema.field(name)
    nan_side=selector.set_column(selector.schema.get_field_index(name),field,pa.array([float('nan')]+[20.]*(len(selector)-1),type=field.type))
    null_side=backtest.set_column(backtest.schema.get_field_index(name),backtest.schema.field(name),pa.array([None]+[20.]*(len(backtest)-1),type=field.type))
    nan_path=tmp_path/'nan.parquet';null_path=tmp_path/'null.parquet';pq.write_table(nan_side,nan_path);pq.write_table(null_side,null_path)
    with pytest.raises(q.QfqGateError,match='KB_ROLE_A_INPUT_TYPE_OR_NULL_MISMATCH:000001.SZ:ma60'):
        q._kb_seed_checkpoints({'selector':{bucket:nan_path},'backtest':{bucket:null_path}},snapshot,20261030,identity,
            {'selector':'1'*64,'backtest':'2'*64},parts,None,None,None,1,'thread',run,'c'*64)
    changed=backtest.set_column(backtest.schema.get_field_index('ma60'),'ma60',pa.array([21.]*len(backtest)))
    bad=tmp_path/'changed.parquet';pq.write_table(changed,bad)
    with pytest.raises(q.QfqGateError,match='KB_ROLE_A_INPUT_MISMATCH:000001.SZ:ma60'):
        q._kb_seed_checkpoints({'selector':spools['selector'],'backtest':{bucket:bad}},snapshot,20261030,identity,
            {'selector':'1'*64,'backtest':'2'*64},parts,None,None,None,1,'thread',run,'c'*64)


def test_overlay_uses_date_values_for_string_checkpoint_without_changing_role_types(tmp_path):
    contract=Path(q.__file__).resolve().parents[1]/'contracts/a_share_kb_full_research_v1.json'
    spec=q.full_research_contract({'path':str(contract),'sha256':q.sha(contract)})
    parts=tmp_path/'parts';parts.mkdir()
    first=pa.table({'ts_code':['002865.SZ']*2,'trade_date':['20261029','20261030'],'close':[1.,2.]})
    schema=q.full_research_schema(first.schema,spec)
    new_fields=set(schema.names)-set(first.column_names)
    columns={'trade_date':pa.array(['20261029','20261030'],type=pa.string())}
    for name in sorted(new_fields):
        typ=schema.field(name).type
        columns[name]=pa.array([3,4],type=typ) if name=='kb_hold_score_min' else pa.nulls(2,type=typ)
    pq.write_table(pa.table(columns),parts/'002865.SZ.parquet')
    for dates in (pa.array(['20261029','20261030'],type=pa.string()),
                  pa.array([20261029,20261030],type=pa.int32())):
        old=first.set_column(first.schema.get_field_index('trade_date'),'trade_date',dates)
        role_schema=q.full_research_schema(old.schema,spec)
        result=q._kb_overlay_retained(old,role_schema,parts,full_research=True)
        assert result['kb_hold_score_min'].to_pylist()==[3,4]
        assert result.schema.field('trade_date')==old.schema.field('trade_date')
        assert all(result[field.name].equals(old[field.name]) for field in old.schema)


def test_overlay_rejects_invalid_or_duplicate_checkpoint_dates(tmp_path):
    contract=Path(q.__file__).resolve().parents[1]/'contracts/a_share_kb_full_research_v1.json'
    spec=q.full_research_contract({'path':str(contract),'sha256':q.sha(contract)})
    old=pa.table({'ts_code':['002865.SZ']*2,'trade_date':[20261029,20261030]})
    schema=q.full_research_schema(old.schema,spec);parts=tmp_path/'parts';parts.mkdir()
    fields=set(schema.names)-set(old.column_names)
    for dates in (['20261029','bad'],['20261030','20261030']):
        data={'trade_date':pa.array(dates,type=pa.string())}
        data.update({name:pa.nulls(2,type=schema.field(name).type) for name in fields})
        pq.write_table(pa.table(data),parts/'002865.SZ.parquet')
        with pytest.raises(q.QfqGateError,match='KB_CHECKPOINT_.*(?:DATE|KEYS)'):
            q._kb_overlay_retained(old,schema,parts,full_research=True)
