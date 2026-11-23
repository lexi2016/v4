"""Prepare ACT-008 B1/B2/B3 from the authoritative paired V4 Reader.

Zero fits. Only case-keyed identities and derived matrices are persisted;
projected source histories remain bounded in memory and are never a panel copy.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))
from ops import pft_s_full_ashare as old
from ops.pft_s_full_ashare_features import FEATURES as S_FEATURES, feature_frame
from ops.pft_act008_b_features import BASE_FEATURES, BRANCH_FEATURES, DIRECT_FIELDS, LANES, b_frame, frozen_s_gate

BATCH = 'ACT-008'
FORMULA_PATH = Path('/Users/lexi/Desktop/学习/agents调试/Z哥方法论/个股学习/b123_four_cases_20261021/futu_source/ACTIVE_MA_USER_20261021.txt')
FORMULA_SHA = '924ab78f0adb0ee0705e41d7824282f40ec275a97da532ffee5b61e29d2925e6'
FLAGS = old.FLAGS


def write_json(path: Path, value: Any) -> None:
    old._atomic_write_text(path, json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)+'\n')


def rank(lane: str, split: str, stratum: str, code: str, day: str) -> str:
    return hashlib.sha256(f'{BATCH}|{lane}|{split}|{stratum}|{code}|{day}'.encode()).hexdigest()


def panel_columns(schema):
    mapping, _ = old._panel_columns(schema)
    actual = old._schema_names(schema)
    aliases = {'kdj_k':'k', 'kdj_d':'d', 'kdj_j':'j', **{n:n.lower() for n in DIRECT_FIELDS if not n.startswith('kdj_')}}
    for semantic, field in aliases.items():
        if field not in actual:
            raise old.PrepareError('B_PANEL_FIELD_MISSING:'+field)
        mapping[semantic] = actual[field]
    return mapping, list(dict.fromkeys(mapping.values()))


def verify_source(source, frozen):
    identity = source['identity']
    basis = identity.get('a_market_basis') or {}
    expected = frozen['scope']['authoritative_v4']
    if (identity.get('generation_id') != expected['generation'] or
        old._day(identity.get('asof_date')) != old._day(expected['asof']) or
        (source.get('backtest') or {}).get('panel_sha256') != expected['backtest_sha256'] or
        basis.get('price_basis') != expected['price_basis'] or basis.get('volume_basis') != expected['volume_basis']):
        raise old.PrepareError('ACT008_PANEL_IDENTITY_OR_BASIS_MISMATCH')


def _scan_one(task):
    import pandas as pd
    canonical, by_code, split, crosswalk = task
    history = old._deduplicate_alias_history(by_code, crosswalk)
    frame = b_frame(pd.DataFrame(history))
    counters = Counter()
    results = []
    for lane in LANES:
        candidates = frame.loc[frame[f'{lane}_label'].notna()]
        best = {}
        for index, row in candidates.iterrows():
            day = str(row.trade_date)
            if (split == 'TRAIN' and day > old.TRAIN_END) or (split == 'OOS' and day < old.OOS_START):
                continue
            stratum = str(row[f'{lane}_stratum'])
            counters[f'{lane}:{stratum}:candidate_rows'] += 1
            item = {'canonical_security_id':canonical, 'D':day, 'split':split, 'lane':lane,
                    'label':int(row[f'{lane}_label']), 'stratum':stratum,
                    'reason':str(row[f'{lane}_reason']),
                    'original':int(row[f'{lane}_original']),
                    'formula_mismatch':bool(row[f'{lane}_formula_mismatch']),
                    'rank_hash':rank(lane,split,stratum,canonical,day)}
            item['episode_id'] = item['rank_hash'][:24]
            if stratum not in best or item['rank_hash'] < best[stratum]['rank_hash']:
                best[stratum] = item
        results.extend(best.values())
        counters[f'{lane}:formula_comparisons'] += int((frame[f'{lane}_recomputed'].notna() & frame[f'{lane}_original'].notna()).sum())
        counters[f'{lane}:formula_mismatches'] += int(frame[f'{lane}_formula_mismatch'].sum())
    return results, dict(counters)


def select(candidates, lane, split, positives, negatives):
    """Frozen order: positive, half-negative original adverse, near miss, remainder."""
    pool = sorted((r for r in candidates if r['lane']==lane and r['split']==split),key=lambda r:r['rank_hash'])
    selected, used = [], set()
    def take(predicate, target):
        count = 0
        for row in pool:
            code = row['canonical_security_id']
            if code in used or not predicate(row):
                continue
            if count >= target:
                break
            selected.append(row.copy()); used.add(code); count += 1
        return count
    actual_pos = take(lambda r:r['label']==1, positives)
    actual_hard = take(lambda r:r['stratum']=='HARD_ORIGINAL_ADVERSE', negatives//2)
    actual_near = take(lambda r:r['stratum']=='NEAR_MISS_ADVERSE', negatives-actual_hard)
    actual_extra = take(lambda r:r['label']==0, negatives-actual_hard-actual_near)
    selected.sort(key=lambda r:r['rank_hash'])
    return selected, {'target_positive':positives,'target_negative':negatives,
                      'actual_positive':actual_pos,'actual_negative':actual_hard+actual_near+actual_extra,
                      'strata':dict(Counter(r['stratum'] for r in selected)),
                      'shortage_positive':positives-actual_pos,
                      'shortage_negative':negatives-actual_hard-actual_near-actual_extra,
                      'precision_scope':'case-control operational weak-label sample; not market prevalence'}


def _selected_one(task):
    """Compute expensive S prefixes once per selected canonical security/D."""
    import pandas as pd
    canonical, by_code, cases, crosswalk = task
    history = old._deduplicate_alias_history(by_code,crosswalk)
    outputs = []
    for day in sorted({case['D'] for case in cases}):
        prefix = [row for row in history if row['trade_date'] <= day]
        if not prefix or prefix[-1]['trade_date'] != day:
            raise old.PrepareError(f'SELECTED_EXACT_D_MISSING:{canonical}:{day}')
        hf = pd.DataFrame(prefix)
        b = b_frame(hf).iloc[-1]
        s = feature_frame(hf).iloc[-1]
        anchor = str(s.get('prior_anchor_date') or '')
        if anchor and anchor >= day:
            raise old.PrepareError('S_ANCHOR_NOT_STRICTLY_BEFORE_D')
        gate, gate_reason = frozen_s_gate(s)
        out = {'canonical_security_id':canonical,'D':day,
               'base':{n:old._csv_value(b[n]) for n in BASE_FEATURES},
               'branches':{f'S_{n}':old._csv_value(s[n]) for n in BRANCH_FEATURES},
               's':{n:old._csv_value(s[n]) for n in S_FEATURES},
               'gate':{'gate':old._csv_value(gate),'gate_reason':gate_reason,'prior_anchor_date':anchor},
               'diagnostics':{n:old._csv_value(b[n]) for n in b.index if n not in BASE_FEATURES and n not in ('trade_date','eligible')}}
        outputs.append(out)
    return outputs


def _map(executor, function, tasks):
    return map(function,tasks) if executor is None else executor.map(function,tasks,chunksize=1)


def _write_rows(path, rows, columns=None):
    columns = columns or list(dict.fromkeys(k for row in rows for k in row))
    old._write_csv(path,list(columns),rows)


def prepare(*, artifact_root: Path, act005_root: Path, data_root: Path, output_dir: Path,
            code_cohort_size: int=384, workers: int=1):
    artifact_root,act005_root,data_root = (p.expanduser().resolve(strict=True) for p in (artifact_root,act005_root,data_root))
    output_dir = output_dir.expanduser().absolute()
    stage = output_dir.with_name(output_dir.name+'.partial')
    if output_dir.exists() or stage.exists() or output_dir.is_symlink() or stage.is_symlink():
        raise old.PrepareError('PREPARE_OUTPUT_ALREADY_EXISTS')
    if output_dir.parent.resolve(strict=True) != artifact_root:
        raise old.PrepareError('PREPARE_OUTPUT_MUST_BE_ARTIFACT_CHILD')
    if not 1 <= workers <= 8:
        raise old.PrepareError('WORKERS_MUST_BE_1_TO_8')
    scope = old._read_json(artifact_root/'scope_frozen.json')
    if scope.get('batch') != BATCH or scope.get('flags') != FLAGS:
        raise old.PrepareError('ACT008_SCOPE_INVALID')
    if old._sha_file(artifact_root/'WRITER_SCOPE.md') != scope.get('experimental_scope_sha256'):
        raise old.PrepareError('WRITER_SCOPE_SHA_MISMATCH')
    if old._sha_file(FORMULA_PATH) != FORMULA_SHA or scope.get('formula_sha256') != FORMULA_SHA:
        raise old.PrepareError('USER_FORMULA_SHA_MISMATCH')
    inputs = old._validate_inputs(act005_root)
    expected = inputs['scope']['authoritative_v4']
    if scope.get('panel_generation')!=expected['generation'] or scope.get('panel_sha256')!=expected['backtest_sha256']:
        raise old.PrepareError('ACT005_ACT008_SOURCE_MISMATCH')
    kb_rows,kb_sha = old._read_csv(act005_root/'external_kb25_observations_frozen.csv')
    if len(kb_rows)!=25 or len({r['case_id'] for r in kb_rows})!=25:
        raise old.PrepareError('KB25_EXACT_IDENTITY_REQUIRED')
    kb_cases = [{'case_id':r['case_id'],'canonical_security_id':inputs['aliases'].get(r['security_id'],r['security_id']),
                 'security_id':r['security_id'],'D':old._day(r['D']),'split':'EXPOSED_KB',
                 'exposure':'EXPOSED_DIAGNOSTIC_ONLY','B_human_gold':'UNKNOWN'} for r in kb_rows]
    kb_reference,kb_reference_sha = old._read_csv(artifact_root/'KB25_original_B_formula_reference.csv')
    if kb_reference_sha != '91e8365337baf54d70a821cd5653a81aab010d2a32f00abc189d7c9bf4da414d':
        raise old.PrepareError('KB25_ORIGINAL_REFERENCE_SHA_MISMATCH')
    from ops import pft_s_first_baseline as baseline
    from ops import research_panel_logical as reader
    executor = ProcessPoolExecutor(max_workers=workers) if workers>1 else None
    counters,all_candidates = Counter(),[]
    try:
        with baseline.bind_current_panels(data_root) as (panel_path,source,recheck):
            verify_source(source,inputs)
            observed,_ = old._key_rows_universe(panel_path,reader,set(inputs['raw_to_canonical']))
            codes_by_canonical={}
            for code in sorted(observed):
                canonical=inputs['raw_to_canonical'][code]
                if canonical not in inputs['excluded_canonical']:
                    codes_by_canonical.setdefault(canonical,[]).append(code)
            schema=reader.parquet.read_schema(panel_path)
            mapping,columns=panel_columns(schema)
            for batch_index,code_batch in enumerate(old._code_cohorts(codes_by_canonical,code_cohort_size)):
                grouped,count = old._read_panel_batch(panel_path,schema,mapping,columns,code_batch,inputs['raw_to_canonical'],reader)
                counters['panel_rows_read']+=count
                tasks=[(c,rows,inputs['canonical_partition'][c],inputs['crosswalk_aliases']) for c,rows in grouped.items() if c not in inputs['excluded_canonical']]
                for found,stats in _map(executor,_scan_one,tasks):
                    all_candidates.extend(found); counters.update(stats)
                print(json.dumps({'stage':'candidate_scan','cohort':batch_index+1,'candidate_stocks_strata':len(all_candidates),'rows_read':counters['panel_rows_read']}),file=sys.stderr,flush=True)
            selections,counts={},{}
            for lane in LANES:
                for split,p,n in [('TRAIN',120,240),('OOS',60,120)]:
                    key=f'{lane}_{split.lower()}'
                    selections[key],counts[key]=select(all_candidates,lane,split,p,n)
            all_cases=[r for rows in selections.values() for r in rows]+kb_cases
            by_canonical={}
            for item in all_cases: by_canonical.setdefault(item['canonical_security_id'],[]).append(item)
            selected_codes={c:[raw for raw,canonical in inputs['raw_to_canonical'].items() if canonical==c] for c in by_canonical}
            if any(not codes for codes in selected_codes.values()):
                raise old.PrepareError('SELECTED_CANONICAL_ALIAS_MISSING')
            selected={}
            for code_batch in old._code_cohorts(selected_codes,code_cohort_size):
                grouped,count=old._read_panel_batch(panel_path,schema,mapping,columns,code_batch,inputs['raw_to_canonical'],reader)
                counters['selected_panel_rows_read']+=count
                tasks=[(c,grouped[c],by_canonical[c],inputs['crosswalk_aliases']) for c in grouped]
                for found in _map(executor,_selected_one,tasks):
                    for row in found: selected[(row['canonical_security_id'],row['D'])]=row
            recheck()
    finally:
        if executor: executor.shutdown(wait=True)
    if any(counters[f'{lane}:formula_mismatches'] for lane in LANES):
        # Keep findings explicit; a selected mismatch cannot enter a fit.
        selected_mismatches=[r for rows in selections.values() for r in rows if r['formula_mismatch']]
        if selected_mismatches:
            raise old.PrepareError(f'SELECTED_FORMULA_MISMATCH:{len(selected_mismatches)}')
    refs={r['case_id']:r for r in kb_reference}
    if set(refs)!={r['case_id'] for r in kb_cases}:
        raise old.PrepareError('KB25_REFERENCE_CASE_ID_MISMATCH')
    for case in kb_cases:
        ref=refs[case['case_id']]
        if old._day(ref['D'])!=case['D'] or ref['security_id']!=case['security_id']:
            raise old.PrepareError('KB25_REFERENCE_IDENTITY_MISMATCH')
        diag=selected[(case['canonical_security_id'],case['D'])]['diagnostics']
        for lane,column in [('B1','original_B1'),('B2','original_B2_F03'),('B3','original_B3')]:
            if float(diag[f'{lane}_original'])!=float(ref[column]):
                raise old.PrepareError(f'KB25_ORIGINAL_FLAG_MISMATCH:{case["case_id"]}:{lane}')
    stage.mkdir()
    for key,rows in selections.items():
        identities=[{k:r[k] for k in ('episode_id','canonical_security_id','D','lane','split')} for r in rows]
        _write_rows(stage/f'{key}_identity.csv',identities,['episode_id','canonical_security_id','D','lane','split'])
        labels=[{**i,**{k:r[k] for k in ('label','reason','stratum','original','rank_hash')}} for i,r in zip(identities,rows)]
        _write_rows(stage/f'{key}_labels.csv',labels,['episode_id','canonical_security_id','D','lane','split','label','reason','stratum','original','rank_hash'])
        _write_case_matrices(stage,key,rows,selected)
    _write_rows(stage/'kb_identity.csv',kb_cases)
    _write_case_matrices(stage,'kb',kb_cases,selected)
    input_hashes={**inputs['input_sha256'],'scope_frozen.json':old._sha_file(artifact_root/'scope_frozen.json'),
                  'WRITER_SCOPE.md':old._sha_file(artifact_root/'WRITER_SCOPE.md'),
                  'S_FROZEN_V1_inference.json':old._sha_file(artifact_root/'S_FROZEN_V1_inference.json'),
                  'external_kb25_observations_frozen.csv':kb_sha,'original_formula':FORMULA_SHA}
    input_hashes['KB25_original_B_formula_reference.csv']=kb_reference_sha
    manifest={'schema':'pft_act008_b_prepared.v1','batch':BATCH,'source':source,'flags':FLAGS,
              'act005_root':str(act005_root),'artifact_root':str(artifact_root),
              'base_features':list(BASE_FEATURES),'branch_features':[f'S_{n}' for n in BRANCH_FEATURES],
              's_features':list(S_FEATURES),'input_sha256':input_hashes,'sampling':counts,'counters':dict(counters),
              'reader':{'range':[old.START_DATE,old.ASOF_DATE],'columns':mapping,'workers':workers,'code_cohort_size':code_cohort_size},
              'label_contract':'ACT008 operational D-only weak labels; independent B human gold UNKNOWN',
              'actual_fit_counts':{'S_helper':0,'B':0},
              'outputs_sha256':{p.name:old._sha_file(p) for p in stage.iterdir() if p.is_file()},
              'code_sha256':{p.name:old._sha_file(p) for p in (Path(__file__),APP_ROOT/'ops/pft_act008_b_features.py')}}
    write_json(stage/'manifest.json',manifest)
    stage.replace(output_dir)
    return {'status':'PREPARED','output_dir':str(output_dir),'sampling':counts,'fit_counts':manifest['actual_fit_counts']}


def _write_case_matrices(stage,key,rows,selected):
    values=[selected[(r['canonical_security_id'],r['D'])] for r in rows]
    _write_rows(stage/f'{key}_base.csv',[r['base'] for r in values],BASE_FEATURES)
    _write_rows(stage/f'{key}_branches.csv',[r['branches'] for r in values],[f'S_{n}' for n in BRANCH_FEATURES])
    _write_rows(stage/f'{key}_s.csv',[r['s'] for r in values],S_FEATURES)
    _write_rows(stage/f'{key}_gates.csv',[r['gate'] for r in values],['gate','gate_reason','prior_anchor_date'])
    _write_rows(stage/f'{key}_diagnostics.csv',[r['diagnostics'] for r in values])


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['prepare'])
    for name in ('artifact-root','act005-root','data-root','output-dir'): parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--code-cohort-size',type=int,default=384)
    parser.add_argument('--workers',type=int,default=1,help='Controller selects 1..8 from current resource measurements')
    args=parser.parse_args(argv)
    try:
        result=prepare(artifact_root=args.artifact_root,act005_root=args.act005_root,data_root=args.data_root,output_dir=args.output_dir,code_cohort_size=args.code_cohort_size,workers=args.workers)
    except Exception as exc:
        print(json.dumps({'status':'FAILED','error':str(exc)}),file=sys.stderr);return 2
    print(json.dumps(result,sort_keys=True));return 0

if __name__=='__main__': raise SystemExit(main())
