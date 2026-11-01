import copy

import pytest
import json
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from ops.kb_hold_score import apply_n_score, score_history
from ops import research_panel_qfq as q


def test_n_replaces_only_trend_and_dependent_score_tristate():
    source=[{'ts_code':'002865.SZ','trade_date':20260100+i,'open':19+i/10,'high':21+i/10,
             'low':18+i/10,'close':20+i/10,'volume':100} for i in range(1,31)]
    old=score_history(source);original=copy.deepcopy(old)
    rule='a'*64;helper='b'*64
    def rows(trend,reason):
        return [{'ts_code':'002865.SZ','trade_date':r['trade_date'],'kb_hold_trend_up':trend,
                 'kb_hold_trend_up_reason':reason,'kb_n_structure':{'state':'TREND_UP' if trend is True else reason,
                 'rule_sha256':rule,'helper_sha256':helper}} for r in source]
    allowed={'kb_hold_trend_up','kb_hold_trend_up_reason','kb_hold_score','kb_hold_score_min','kb_hold_score_max','kb_hold_score_status'}
    false=apply_n_score('002865.SZ',source,old,rows(False,'STRUCTURE_NOT_RISING'),rule_sha256=rule,helper_sha256=helper)
    true=apply_n_score('002865.SZ',source,old,rows(True,None),rule_sha256=rule,helper_sha256=helper)
    unknown=apply_n_score('002865.SZ',source,old,rows(None,'AMBIGUOUS_SAME_BAR_PIVOT'),rule_sha256=rule,helper_sha256=helper)
    assert old==original
    assert {k:v for k,v in false[-1].items() if k not in allowed}=={k:v for k,v in old[-1].items() if k not in allowed}
    assert (false[-1]['kb_hold_score'],false[-1]['kb_hold_score_min'],false[-1]['kb_hold_score_max'])==(4,4,4)
    assert (true[-1]['kb_hold_score'],true[-1]['kb_hold_score_min'],true[-1]['kb_hold_score_max'])==(5,5,5)
    assert (unknown[-1]['kb_hold_score'],unknown[-1]['kb_hold_score_min'],unknown[-1]['kb_hold_score_max'])==(None,4,5)
    bad=rows(True,None);bad[-1]['kb_n_structure']['helper_sha256']='c'*64
    with pytest.raises(ValueError,match='HOLD_N_ROW_IDENTITY_CONFLICT'):
        apply_n_score('002865.SZ',source,old,bad,rule_sha256=rule,helper_sha256=helper)


def test_n_is_explicitly_paired_and_requires_the_existing_score_and_gap_schema():
    fields=[pa.field('trade_date',pa.int32()),pa.field('ts_code',pa.string()),pa.field('kb_rebuild',pa.bool_())]
    for name in sorted(q.SINGLE_FEEDBACK_FIELDS):
        typ=(pa.string() if name.endswith('_reason') or name=='kb_hold_score_status' else
             pa.int8() if name in {'kb_hold_score','kb_hold_score_min','kb_hold_score_max'} else
             pa.float64() if name in {'kb_hold_bbi','kb_hold_k','kb_hold_d'} else pa.bool_())
        fields.append(pa.field(name,typ))
    types={'string':pa.string(),'bool':pa.bool_(),'double':pa.float64(),'int32':pa.int32()}
    fields += [pa.field(name,types[kind]) for name,kind in q.SINGLE_GAP_FIELD_TYPES.items()]
    legacy=pa.schema(fields)
    enabled=legacy.with_metadata({q.META_KEY:json.dumps({'n_structure_enabled':True}).encode()})
    assert q._single_n_pair_mode({'selector':legacy,'backtest':legacy}) is False
    assert q._single_n_pair_mode({'selector':enabled,'backtest':enabled}) is True
    with pytest.raises(q.QfqGateError,match='SINGLE_N_ROLE_MODE_MISMATCH'):
        q._single_n_pair_mode({'selector':enabled,'backtest':legacy})
    no_gap=pa.schema(fields[:1],metadata={q.META_KEY:json.dumps({'n_structure_enabled':True}).encode()})
    with pytest.raises(q.QfqGateError,match='SINGLE_N_REQUIRES_FEEDBACK_AND_GAP'):
        q._single_n_pair_mode({'selector':no_gap,'backtest':no_gap})


def test_daily_owner_persists_n_checkpoint_and_score_in_existing_gap_sidecar(tmp_path):
    symbol='002865.SZ';bars=[]
    for i in range(130):
        close=round(20+i*.01,2)
        previous=20 if not i else bars[-1]['close']
        bars.append(dict(ts_code=symbol,trade_date=int((date(2025,1,1)+timedelta(days=i)).strftime('%Y%m%d')),
            open=close-.1,high=close+.2,low=close-.2,close=close,volume=1000.,pre_close=previous,
            pct_chg=round((close/previous-1)*100,2),ma60=20.,zge_yellow_line=20.,
            kb_double_gun=False if i>=23 else None,kb_violence_k=False if i>=20 else None))
    for row,score in zip(bars,score_history(bars)):row['kb_b1_j']=score['kb_hold_j']
    source=tmp_path/'source.parquet';pq.write_table(pa.Table.from_pylist(bars),source)
    recovered={symbol:{'artifact':{'path':str(source),'sha256':q.sha(source)}}}
    parts=tmp_path/'parts';parts.mkdir()
    identity={'single_feedback_enabled':True,'single_yidong_enabled':True,'confirmed_gap_enabled':True,
              'n_structure_enabled':True,'input_sha256':'a'*64,'confirmed_gap_snapshot_file_sha256':'b'*64,**q._n_sha256s()}
    _,result=q._symbol_checkpoint(symbol,{},20261030,identity,parts,recovered,None,True,'c'*64)
    output=pq.read_table(result);receipt=json.loads((parts/(symbol+'.receipt.json')).read_text())
    sidecar=pq.read_table(receipt['confirmed_gap_sidecar']['path']);meta=json.loads(sidecar.schema.metadata[b'v4.a_share.kb_gap_diagnostics.v1'])
    checkpoint=json.loads(Path(receipt['n_structure_checkpoint']['path']).read_text())
    assert len(sidecar)==len(output)==130 and len(meta['diagnostic_keys'])==25
    assert meta['n_structure_contract_sha256']==identity['n_structure_contract_sha256']
    assert checkpoint['identity']['generation_id']=='c'*64 and checkpoint['identity']['price_basis_sha256'] is None
    diag=json.loads(sidecar['diagnostics_json'][-1].as_py())['kb_n_structure']
    assert output['kb_hold_trend_up'][-1].as_py() is None
    assert output['kb_hold_trend_up_reason'][-1].as_py()==diag['state']=='INSUFFICIENT_CONFIRMED_SWINGS'
    assert q._symbol_checkpoint(symbol,{},20261030,identity,parts,recovered,None,True,'c'*64)[1]==result
    Path(receipt['n_structure_checkpoint']['path']).write_text('{}')
    with pytest.raises(q.QfqGateError,match='SOURCE_BINDING_FAILED'):
        q._symbol_checkpoint(symbol,{},20261030,identity,parts,recovered,None,True,'c'*64)


def test_final_generation_gate_separates_base_identity_from_bound_extensions(tmp_path,monkeypatch):
    snapshot=tmp_path/'snapshot.json';snapshot.write_text('{"same":true}')
    base={'input_sha256':'a'*64}
    monkeypatch.setattr(q,'load_snapshot',lambda *args:{})
    monkeypatch.setattr(q,'generation_identity',lambda *args:dict(base))
    root=Path(q.__file__).resolve().parents[1]
    identity={**base,**q._n_sha256s(),'confirmed_gap_enabled':True,'n_structure_enabled':True,
              'confirmed_gap_contract_sha256':q.gap_rule_sha256(),'confirmed_gap_helper_sha256':q.gap_helper_sha256s(),
              'confirmed_gap_snapshot_file_sha256':q.sha(snapshot),
              'confirmed_gap_rebuild_contract_sha256':q.sha(root/'contracts/a_share_kb_rebuild_brick_v1.json'),
              'confirmed_gap_components_contract_sha256':q.sha(root/'contracts/a_share_kb_signal_components_v1.json')}
    args=(snapshot,20261030,None,Path('driver'),Path('formula'),Path('csv'),base,identity,True,True,None)
    q._revalidate_build_identity(*args)
    snapshot.write_text('{ "same": true }')
    with pytest.raises(q.QfqGateError,match='SINGLE_GAP_INPUT_CHANGED_DURING_BUILD'):
        q._revalidate_build_identity(*args)
    snapshot.write_text('{"same":true}')
    identity['n_structure_helper_sha256']='f'*64
    with pytest.raises(q.QfqGateError,match='SINGLE_N_INPUT_CHANGED_DURING_BUILD'):
        q._revalidate_build_identity(*args)
