"""Read back one paired, frozen two-stock gap candidate without recalculation."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from infrastructure.research_workbench_host import checked_confirmed_gap, checked_single_display_projection
from ops.kb_confirmed_gap import FIELD_TYPES, INPUTS, prefix_hashes, project_selected
from ops.research_panel_qfq import _source


def arrow_sha(table):
    table=table.replace_schema_metadata(None).combine_chunks();sink=pa.BufferOutputStream()
    with pa.ipc.new_stream(sink,table.schema) as writer:writer.write_table(table)
    return hashlib.sha256(sink.getvalue().to_pybytes()).hexdigest()


def read_json(ref):
    return json.loads(_source(ref,owner='gap acceptance source').read_text())


def read_gzip(ref):
    return json.loads(gzip.decompress(_source(ref,owner='gap acceptance asset').read_bytes()))


def verify(previous_ref, candidate_ref):
    previous=read_json(previous_ref);candidate=read_json(candidate_ref)
    binding=read_json(candidate['binding']);identity=binding['candidate_identity'];symbol=binding['symbol']
    assert candidate['confirmed_gap_rebound_from']==previous_ref
    assert candidate['candidate_generation']==binding['candidate_generation']
    host=checked_confirmed_gap(binding,identity);display=checked_single_display_projection(binding,identity)
    new_view=read_gzip(candidate['assets']['kb']);old_view=read_gzip(previous['assets']['kb'])
    new_chart=read_gzip(candidate['assets']['projection']);old_chart=read_gzip(previous['assets']['projection'])
    assert new_chart['formula_result']==old_chart['formula_result']
    sidecar=pq.read_table(_source(binding['confirmed_gap']['diagnostics'],owner='gap acceptance sidecar')).to_pylist()
    expected_diagnostics=pq.read_table(_source(binding['confirmed_gap']['source_diagnostics'],owner='gap source sidecar')).to_pylist()
    original_diag={(x['ts_code'],str(x['trade_date'])):json.loads(x['diagnostics_json']) for x in expected_diagnostics}
    roles={};rebuild_counts={};warmup_preserved=0
    for role in ('selector','backtest'):
        old=pq.read_table(_source(previous['outputs'][role],owner='prior role '+role))
        new=pq.read_table(_source(candidate['outputs'][role],owner='candidate role '+role))
        names=[name for name in old.column_names if name!='kb_rebuild']
        assert arrow_sha(old.select(names))==arrow_sha(new.select(names))
        assert new.column_names==old.column_names+list(FIELD_TYPES)
        assert len(new.column_names)==(340 if role=='selector' else 192)
        assert old['kb_brick_consecutive'].equals(new['kb_brick_consecutive'])
        roles[role]={'rows':len(new),'columns':len(new.column_names),'old_except_rebuild_arrow_sha256':arrow_sha(old.select(names)),
                     'display_columns':display[role+'_columns'],'brick_count_unchanged':True}
    selector=pq.read_table(_source(candidate['outputs']['selector'],owner='candidate selector'))
    frame=selector.select([('volume' if n=='vol' else n) for n in INPUTS]).to_pandas().rename(columns={'volume':'vol'})
    fingerprints=prefix_hashes(frame)
    assert len(sidecar)==len(new_view['rows'])==len(old_view['rows'])==len(selector)
    for i,(entry,row,old_row) in enumerate(zip(sidecar,new_view['rows'],old_view['rows'])):
        key=(symbol,str(row['trade_date']));diag=json.loads(entry['diagnostics_json'])
        assert entry['ts_code']==symbol and entry['trade_date']==key[1] and entry['prefix_input_sha256']==fingerprints[i]
        assert diag==original_diag[key]==row['confirmed_kb_diagnostics']
        assert row['kb']['kb_rebuild']==selector['kb_rebuild'][i].as_py()
        assert {k:v for k,v in row['kb'].items() if k!='kb_rebuild'}=={k:v for k,v in old_row['kb'].items() if k!='kb_rebuild'}
        assert row['confirmed_kb_fields']=={name:selector[name][i].as_py() for name in FIELD_TYPES}
        assert row['action']==old_row['action'] and row['original']==old_row['original']
        raw_count=selector['kb_brick_consecutive'][i].as_py()
        if raw_count is not None and diag['kb_brick_count_reason']=='BRICK_RUN_ORIGIN_IN_WARMUP':warmup_preserved+=1
        value=row['kb']['kb_rebuild'];keycount='unknown' if value is None else 'true' if value else 'false'
        rebuild_counts[keycount]=rebuild_counts.get(keycount,0)+1
    # Check only representative boundaries and one real hit against the same
    # current helper; the historical 57-field computation is not rerun.
    sample={0,12,13,19,122,123,len(frame)-1}
    sample.add(next(i for i,row in enumerate(new_view['rows']) if row['kb']['kb_rebuild'] is True))
    if symbol=='002865.SZ':sample.add(next(i for i,row in enumerate(new_view['rows']) if row['trade_date']==20251212))
    calculated=project_selected(frame,sorted(sample))
    for i,(values,diag) in calculated.items():
        row=new_view['rows'][i]
        assert values=={**row['confirmed_kb_fields'],'kb_rebuild':row['kb']['kb_rebuild']}
        assert diag==row['confirmed_kb_diagnostics']
    return {'symbol':symbol,'candidate':candidate_ref,'candidate_generation':candidate['candidate_generation'],
            'prior':previous_ref,'roles':roles,'rebuild_counts':rebuild_counts,'brick_warmup_existing_values_preserved':warmup_preserved,
            'diagnostic_rows_exact':len(sidecar),'diagnostic_field_count':24,'new_fields':sorted(FIELD_TYPES),
            'real_helper_sample_dates':[str(new_view['rows'][i]['trade_date']) for i in sorted(sample)],
            'original_chart_formula_rows_unchanged':True,'original_action_and_buy_sell_unchanged':True,
            'host_check':host,'calendar_status':'CANNOT_CONFIRM','status':'PASS_CANDIDATE_READBACK'}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--prior',type=Path,required=True);p.add_argument('--prior-sha256',required=True)
    p.add_argument('--candidate',type=Path,required=True);p.add_argument('--candidate-sha256',required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();result=verify({'path':str(a.prior.resolve(strict=True)),'sha256':a.prior_sha256},
        {'path':str(a.candidate.resolve(strict=True)),'sha256':a.candidate_sha256})
    with a.output.open('x',encoding='utf-8') as stream:json.dump(result,stream,ensure_ascii=False,sort_keys=True,indent=2);stream.write('\n')
    print(json.dumps(result,ensure_ascii=False))
