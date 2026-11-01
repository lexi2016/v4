"""Read back the isolated EDAN candidate without recomputing its old labels."""
import argparse
from decimal import Decimal
import gzip
import json
import math
from pathlib import Path

import pyarrow.parquet as pq
from infrastructure.research_workbench_host import checked_confirmed_gap, checked_single_display_projection
from ops.junda_feedback_candidate import same
from ops.kb_action_authority import project_action
from ops.kb_n_structure import _bar, _next_digest, _EMPTY_DIGEST
from ops.research_panel_qfq import _source, sha, FLAGS

def obj(ref):return json.loads(_source(ref,owner='EDAN acceptance reference').read_text())
def ungzip(ref):return json.loads(gzip.decompress(_source(ref,owner='EDAN acceptance asset').read_bytes()))
def clean(value):return None if isinstance(value,float) and not math.isfinite(value) else value

def verify(candidate_ref, frozen_ref):
    candidate=obj(candidate_ref);binding=obj(candidate['binding']);identity=binding['candidate_identity']
    frozen=obj(frozen_ref);assert candidate['symbol']==binding['symbol']=='300206.SZ'
    assert candidate['candidate_pool_member'] is binding['candidate_pool_member'] is False
    assert candidate['candidate_generation']==binding['candidate_generation']
    host=checked_confirmed_gap(binding,identity);display=checked_single_display_projection(binding,identity)
    view=ungzip(candidate['assets']['kb']);projection=ungzip(candidate['assets']['projection'])
    assert len(view['fields'])==57 and len(view['rows'])==candidate['rows']==3767
    result=projection['formula_result'];assert (result['field_count'],result['drawing_count'],len(result['rows']))==(51,22,3767)
    tables={};old_equal={}
    for role in ('selector','backtest'):
        source=frozen['roles'][role];p=Path(source['panel']);s=p.stat()
        assert (s.st_size,s.st_mtime_ns,s.st_ino)==(source['size_bytes'],source['mtime_ns'],source['inode'])
        original=pq.read_table(p,filters=[('ts_code','=','300206.SZ')])
        current=pq.read_table(_source(candidate['outputs'][role],owner='EDAN final '+role))
        assert len(original)==len(current)==3767 and len(current.column_names)==(340 if role=='selector' else 192)
        for name in original.column_names:
            assert same(original[name],current[name]),(role,name)
        tables[role]=current;old_equal[role]=len(original.column_names)
    sel,back=tables['selector'],tables['backtest']
    dates=[str(x) for x in sel['trade_date'].to_pylist()]
    assert dates==sorted(set(dates)) and dates[0]=='20110421' and dates[-1]=='20261030'
    assert [str(x) for x in back['trade_date'].to_pylist()]==dates
    n_values=pq.read_table(_source(binding['n_structure']['values'],owner='N values')).to_pylist()
    diagnostics=pq.read_table(_source(binding['confirmed_gap']['diagnostics'],owner='diagnostics')).to_pylist()
    bars=sel.to_pylist();digest=_EMPTY_DIGEST
    for date,bar,n,diag,row,chart in zip(dates,bars,n_values,diagnostics,view['rows'],result['rows']):
        assert str(bar['trade_date'])==str(n['trade_date'])==str(diag['trade_date'])==date
        assert int(date)==row['trade_date']==chart['trade_date'] and n['ts_code']==diag['ts_code']=='300206.SZ'
        digest=_next_digest(digest,_bar('300206.SZ',bar))
        structure=json.loads(n['kb_n_structure_json']);assert digest==n['prefix_input_sha256']==structure['prefix_input_sha256']
        assert structure==json.loads(diag['diagnostics_json'])['kb_n_structure']==row['confirmed_kb_diagnostics']['kb_n_structure']
        assert structure['first_breakout_at'] is None
        for group in ('kb','original','hold_score','supplemental','action','yidong','confirmed_kb_fields'):
            for name,value in row[group].items():assert clean(bar[name])==value,(date,group,name)
        assert row['action']==project_action(bar,rule_sha256=identity['action_contract_sha256'])
        for name in ('open','high','low','close'):
            assert Decimal(str(bar[name]))==Decimal(chart['ohlcv'][name]),(date,name)
        assert Decimal(str(bar['volume']))==Decimal(chart['ohlcv']['vol'])
    assert digest==obj(binding['n_structure']['checkpoint'])['prefix_sha256']
    latest=view['rows'][-1];score=latest['hold_score']
    assert [score['kb_hold_score'],score['kb_hold_score_min'],score['kb_hold_score_max']]==[4,4,4]
    assert score['kb_hold_trend_up'] is False and all(latest['supplemental'][x] is None for x in ('kb_s1','kb_s2','kb_s3'))
    assert latest['action']['kb_action_with_position']=='放飞' and latest['action']['kb_action_no_position']=='等回调'
    assert ungzip(candidate['assets']['history'])['source_candidate']['sha256']==identity['source_candidate_sha256']
    company=ungzip(candidate['assets']['company']);assert company['source_candidate']['sha256']==identity['source_candidate_sha256']
    assert company['f10']['captured_at']==display['captured_at'] and len(company['f10']['concepts'])==display['kb_concept_count']==8
    return {'status':'PASS_ISOLATED_EDAN_CANDIDATE_READBACK','candidate':candidate_ref,'generation':candidate['candidate_generation'],
            'rows':len(dates),'first_date':dates[0],'last_date':dates[-1],
            'columns':{'selector':340,'backtest':192},'display_columns':{'selector':317,'backtest':186},
            'old_columns_exact':old_equal,'n_prefix_last_sha256':digest,'n_daily_rows':len(n_values),
            'original_chart_fields':51,'original_chart_drawings':22,'score':[4,4,4],
            'calendar_reuse':'CANNOT_CONFIRM','historical_PIT':False,'confirmed_gap':host,**FLAGS}

if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('candidate','candidate-sha256','frozen','frozen-sha256','output'):p.add_argument('--'+name,required=True)
    a=p.parse_args();ref=lambda path,digest:{'path':str(Path(path).resolve(strict=True)),'sha256':digest}
    result=verify(ref(a.candidate,a.candidate_sha256),ref(a.frozen,a.frozen_sha256))
    with Path(a.output).open('x',encoding='utf-8') as stream:json.dump(result,stream,ensure_ascii=False,sort_keys=True,indent=2);stream.write('\n')
    print(json.dumps({'status':result['status'],'output':a.output,'sha256':sha(a.output)},ensure_ascii=False))
