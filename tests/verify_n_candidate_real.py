"""Read back both N candidates without re-running the old signal calculations."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from infrastructure.research_workbench_host import checked_confirmed_gap, checked_single_display_projection
from ops.kb_action_authority import FIELDS as ACTION_FIELDS, project_action
from ops.research_panel_qfq import _source, SINGLE_FEEDBACK_FIELDS

SCORE_CHANGE={'kb_hold_trend_up','kb_hold_trend_up_reason','kb_hold_score','kb_hold_score_min',
              'kb_hold_score_max','kb_hold_score_status'}


def arrow_sha(table):
    table=table.replace_schema_metadata(None).combine_chunks();sink=pa.BufferOutputStream()
    with pa.ipc.new_stream(sink,table.schema) as writer:writer.write_table(table)
    return hashlib.sha256(sink.getvalue().to_pybytes()).hexdigest()


def read(ref):
    return json.loads(_source(ref,owner='N readback').read_text())


def gzip_json(ref):
    return json.loads(gzip.decompress(_source(ref,owner='N view readback').read_bytes()))


def verify(prior_ref,candidate_ref):
    prior=read(prior_ref);candidate=read(candidate_ref);binding=read(candidate['binding'])
    symbol=binding['symbol'];identity=binding['candidate_identity']
    assert candidate['n_rebound_from']==prior_ref
    host=checked_confirmed_gap(binding,identity);display=checked_single_display_projection(binding,identity)
    view=gzip_json(candidate['assets']['kb']);old_view=gzip_json(prior['assets']['kb'])
    assert gzip_json(candidate['assets']['projection'])['formula_result']==gzip_json(prior['assets']['projection'])['formula_result']
    diagnostics=pq.read_table(_source(binding['confirmed_gap']['diagnostics'],owner='N sidecar')).to_pylist()
    old_diagnostics=pq.read_table(_source(prior['confirmed_gap']['diagnostics'],owner='N prior sidecar')).to_pylist()
    n_values=pq.read_table(_source(binding['n_structure']['values'],owner='N values')).to_pylist()
    roles={};tables={}
    for role in ('selector','backtest'):
        old=pq.read_table(_source(prior['outputs'][role],owner='N old role '+role))
        new=pq.read_table(_source(candidate['outputs'][role],owner='N new role '+role))
        unchanged=[name for name in old.column_names if name not in SCORE_CHANGE|ACTION_FIELDS]
        assert old.column_names==new.column_names and arrow_sha(old.select(unchanged))==arrow_sha(new.select(unchanged))
        assert len(new.column_names)==(340 if role=='selector' else 192)
        roles[role]={'rows':len(new),'columns':len(new.column_names),'unchanged_arrow_sha256':arrow_sha(old.select(unchanged)),
                     'display_columns':display[role+'_columns']}
        tables[role]=new
    selector=tables['selector'];score_changed=0
    assert len(selector)==len(diagnostics)==len(old_diagnostics)==len(n_values)==len(view['rows'])==len(old_view['rows'])
    for i,(row,old_row,diag,old_diag,n,bar) in enumerate(zip(view['rows'],old_view['rows'],diagnostics,old_diagnostics,n_values,selector.to_pylist())):
        entries=json.loads(diag['diagnostics_json']);n_object=entries.pop('kb_n_structure')
        assert entries==json.loads(old_diag['diagnostics_json'])==old_row['confirmed_kb_diagnostics']
        assert n_object==json.loads(n['kb_n_structure_json'])==row['confirmed_kb_diagnostics']['kb_n_structure']
        assert row['kb']==old_row['kb'] and row['original']==old_row['original'] and row['yidong']==old_row['yidong']
        assert row['confirmed_kb_fields']==old_row['confirmed_kb_fields']
        assert {k:v for k,v in row['hold_score'].items() if k not in SCORE_CHANGE}=={k:v for k,v in old_row['hold_score'].items() if k not in SCORE_CHANGE}
        assert row['hold_score']['kb_hold_trend_up']==n['kb_hold_trend_up']
        assert row['hold_score']['kb_hold_trend_up_reason']==n['kb_hold_trend_up_reason']
        for field in SCORE_CHANGE:assert row['hold_score'][field]==bar[field]
        changed=any(old_row['hold_score'][name]!=row['hold_score'][name] for name in ('kb_hold_score','kb_hold_score_min','kb_hold_score_max'))
        score_changed+=changed
        if changed:assert row['action']==project_action(bar,rule_sha256=identity['action_contract_sha256'])
        else:assert row['action']==old_row['action']
        assert all(row['action'][name]==bar[name] for name in ACTION_FIELDS)
    assert score_changed==candidate['n_score_changed_rows']
    return {'status':'PASS_N_CANDIDATE_READBACK','symbol':symbol,'candidate':candidate_ref,'generation':candidate['candidate_generation'],
            'rows':len(selector),'roles':roles,'score_changed_rows':score_changed,'last_score':candidate['last_hold_score'],
            'old_signals_and_chart_unchanged':True,'old_24_diagnostics_unchanged':True,'n_diagnostics_rows':len(n_values),
            'calendar_status':'CANNOT_CONFIRM','price_basis_identity_status':'CANNOT_CONFIRM',
            'historical_PIT':False,'RESEARCH_ONLY':True,'production_allowed':False,'buy_gate_updated':False,'orders_sent':False,
            'host':host}


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('prior','prior-sha256','candidate','candidate-sha256','output'):p.add_argument('--'+name,required=True)
    a=p.parse_args()
    result=verify({'path':str(Path(a.prior).resolve(strict=True)),'sha256':a.prior_sha256},
                  {'path':str(Path(a.candidate).resolve(strict=True)),'sha256':a.candidate_sha256})
    with Path(a.output).open('x',encoding='utf-8') as stream:json.dump(result,stream,ensure_ascii=False,sort_keys=True,indent=2);stream.write('\n')
    print(json.dumps(result,ensure_ascii=False))
