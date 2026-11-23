"""ACT-010 natural held-out scan and saved-model inference; no fitting or outcomes.

Only projected V4 reads, immutable signal-keyed derived shards, and a pre-outcome
seal. CANARY is explicit whenever the reserved universe is restricted.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
from pathlib import Path
import sys

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))
import numpy as np
import pandas as pd
from ops import pft_s_full_ashare as old
from ops.pft_act008_b import panel_columns, verify_source, write_json
from ops.pft_act008_b_features import BASE_FEATURES, BRANCH_FEATURES, FULL_FEATURES, LANES, b_frame, frozen_s_gate
from ops.pft_s_full_ashare_features import FEATURES as S_FEATURES, feature_frame

START, ASOF = '20260101', '20261120'
PRIMARY = 'GEMINI_R2_FIXED_LR'
IDENTITY = ['canonical_security_id', 'D']
CANDIDATE_COLUMNS = ['episode_id', *IDENTITY, 'lane', 'raw_trigger', 'near_trigger', 'original',
                     'recomputed', 'label', 'reason', 'stratum', 'eligible', 'formula_mismatch',
                     'S_prob_raw', 'S_prob_gated', 'gate', 'gate_reason', 'prior_anchor_date',
                     'S_model_source', 'BASELINE_B_prob', 'FULL_B_prob']
FEATURE_COLUMNS = [*IDENTITY, *BASE_FEATURES, 'S_probability',
                   *(f'S_{n}' for n in BRANCH_FEATURES), *(f'pure_s_{n}' for n in S_FEATURES)]


def natural_masks(h, b):
    """Membership uses observed materialized raw or D-only near, never weak truth."""
    o, hi, lo, c, v = (pd.to_numeric(h[n], errors='coerce') for n in ('open','high','low','close','vol'))
    observed = pd.concat([o,hi,lo,c,v], axis=1).notna().all(axis=1)
    observed &= pd.concat([o,hi,lo,c,v], axis=1).gt(0).all(axis=1)
    observed &= hi.ge(pd.concat([o,c,lo],axis=1).max(axis=1)) & lo.le(pd.concat([o,c,hi],axis=1).min(axis=1))
    observed &= pd.to_numeric(h.tradeable_basic, errors='coerce').eq(1)
    w, y, j = (pd.to_numeric(h[n], errors='coerce') for n in ('zge_white_line','zge_yellow_line','kdj_j'))
    wy_known = w.notna() & y.notna()
    near = {
        'B1': wy_known & j.notna() & w.gt(y) & j.le(28),
        'B2': wy_known & j.rolling(3).count().eq(3) & b.ret1_pct.notna() & b.volume_ratio5.notna()
              & w.gt(y) & j.rolling(3).min().le(24) & b.ret1_pct.ge(2.5) & b.volume_ratio5.ge(1.05),
        'B3': wy_known & j.shift(2).notna() & b.previous_ret_pct.notna() & b.previous_volume_ratio5.notna()
              & w.gt(y) & j.shift(2).lt(30) & b.previous_ret_pct.ge(2) & b.previous_volume_ratio5.ge(1.05),
    }
    return {lane: (observed & b[f'{lane}_original'].eq(1), near[lane] & b.eligible) for lane in LANES}


def scan_security(task):
    canonical, by_code, crosswalk = task
    history = old._deduplicate_alias_history(by_code, crosswalk)
    if not history:
        return [], [], {'canonical_security_id':canonical, 'history_rows':0, 'signal_rows':0}
    h = pd.DataFrame(history)
    b, s = b_frame(h), feature_frame(h)
    masks = natural_masks(h, b)
    candidates, feature_indices = [], set()
    for lane in LANES:
        raw, near = masks[lane]
        chosen = (raw | near) & b.trade_date.between(START, ASOF)
        for i in np.flatnonzero(chosen.to_numpy()):
            row = b.iloc[i]; sr = s.iloc[i]; day = str(row.trade_date)
            anchor = str(sr.get('prior_anchor_date') or '')
            if anchor and anchor >= day:
                raise ValueError('S_ANCHOR_NOT_STRICTLY_BEFORE_D')
            gate, reason = frozen_s_gate(sr)
            candidates.append({'episode_id':hashlib.sha256(f'ACT-010|{canonical}|{day}|{lane}'.encode()).hexdigest()[:24],
                'canonical_security_id':canonical, 'D':day, 'lane':lane,
                'raw_trigger':bool(raw.iloc[i]), 'near_trigger':bool(near.iloc[i]),
                'original':row[f'{lane}_original'], 'recomputed':row[f'{lane}_recomputed'],
                'label':row[f'{lane}_label'], 'reason':row[f'{lane}_reason'], 'stratum':row[f'{lane}_stratum'],
                'eligible':bool(row.eligible), 'formula_mismatch':bool(row[f'{lane}_formula_mismatch']),
                'gate':gate, 'gate_reason':reason, 'prior_anchor_date':anchor,
                'S_model_source':'SAVED_ACT005_FULL_LR'})
            feature_indices.add(i)
    vectors = []
    for i in sorted(feature_indices):
        vectors.append({'canonical_security_id':canonical,'D':str(b.iloc[i].trade_date),
                        **{n:b.iloc[i][n] for n in BASE_FEATURES},
                        **{f'S_{n}':s.iloc[i][n] for n in BRANCH_FEATURES},
                        **{f'pure_s_{n}':s.iloc[i][n] for n in S_FEATURES}})
    return candidates, vectors, {'canonical_security_id':canonical,'history_rows':len(h), 'signal_rows':len(candidates),
                                **{f'{lane}_signals':sum(r['lane']==lane for r in candidates) for lane in LANES}}


def verified_file(path, sha):
    if not sha or not path.is_file() or path.is_symlink() or old._sha_file(path) != sha:
        raise ValueError('INPUT_SHA_MISMATCH:'+str(path))
    return path


def frozen_models(act005, act008):
    """Lock six primary B pipelines and full S, plus train identities and config."""
    import joblib
    lock_path = act008/'fit_v1/prediction_lock.json'
    lock = old._read_json(lock_path)
    config_path = act008/'S_FROZEN_V1_inference.json'
    config = old._read_json(config_path)
    if lock.get('batch') != 'ACT-008' or lock.get('flags') != old.FLAGS or lock.get('threshold') != .5:
        raise ValueError('ACT008_LOCK_IDENTITY_MISMATCH')
    if config.get('feature_columns') != list(S_FEATURES) or config.get('G2_remove') != 'G2_CLOSE_YELLOW_GE_35':
        raise ValueError('S_CONFIG_MISMATCH')
    hashes = {str(lock_path):old._sha_file(lock_path), str(config_path):old._sha_file(config_path)}
    saved = config['weights'][PRIMARY]
    if saved['sha256'] != lock['S_primary_saved_model_sha256']:
        raise ValueError('S_MODEL_LOCK_MISMATCH')
    path = verified_file(Path(saved['file']),saved['sha256']);hashes[str(path)] = saved['sha256']
    models = {'S':joblib.load(path)}
    if list(models['S'].feature_names_in_) != list(S_FEATURES):
        raise ValueError('S_MODEL_COLUMNS_MISMATCH')
    for lane in LANES:
        for arm, cols in [('BASELINE_B',BASE_FEATURES),('FULL_B',FULL_FEATURES)]:
            name = f'{lane}__{arm}__{PRIMARY}.joblib'
            path = verified_file(act008/'fit_v1'/name,lock['B_model_sha256'][name])
            hashes[str(path)] = lock['B_model_sha256'][name]
            models[lane,arm] = joblib.load(path)
            if list(models[lane,arm].feature_names_in_) != list(cols):
                raise ValueError('B_MODEL_COLUMNS_MISMATCH:'+name)
    p = verified_file(act005/'prepared/train_manifest.csv',config['train_manifest_sha256'])
    hashes[str(p)] = config['train_manifest_sha256']
    train = {r['canonical_security_id'] for r in old._read_csv(p)[0]}
    for lane in LANES:
        name = f'{lane}_train_identity.csv'
        p = verified_file(act008/'prepared'/name,lock['prepared_inputs_sha256'][name])
        hashes[str(p)] = lock['prepared_inputs_sha256'][name]
        train.update(r['canonical_security_id'] for r in old._read_csv(p)[0])
    return models, hashes, train


def infer(candidates, vectors, models):
    f = pd.DataFrame(vectors)
    c = pd.DataFrame(candidates)
    if f.empty:
        return pd.DataFrame(columns=CANDIDATE_COLUMNS), pd.DataFrame(columns=FEATURE_COLUMNS)
    if f.duplicated(IDENTITY).any() or c.episode_id.duplicated().any():
        raise ValueError('DUPLICATE_SIGNAL_IDENTITY')
    # Only model-ready rows are scored; raw short-history signals remain visible.
    keyed = c.drop_duplicates(IDENTITY).set_index(IDENTITY)
    ordered = keyed.reindex(pd.MultiIndex.from_frame(f[IDENTITY]))
    ready = ordered.eligible.to_numpy(dtype=bool)
    f['S_probability'] = np.nan
    raw = np.full(len(f),np.nan)
    if ready.any():
        sx = f.loc[ready,[f'pure_s_{n}' for n in S_FEATURES]].copy();sx.columns = list(S_FEATURES)
        raw[ready] = models['S'].predict_proba(sx)[:,list(models['S'].classes_).index(1)]
    gated = raw * ordered.gate.to_numpy(dtype=float)
    f['S_probability'] = gated
    probabilities = pd.DataFrame({**{n:f[n] for n in IDENTITY},'S_prob_raw':raw,'S_prob_gated':gated})
    c = c.merge(probabilities,on=IDENTITY,validate='many_to_one')
    for arm,cols in [('BASELINE_B',BASE_FEATURES),('FULL_B',FULL_FEATURES)]:
        c[arm+'_prob'] = np.nan
        feature_lookup = f.set_index(IDENTITY)
        for lane in LANES:
            mask = c.lane.eq(lane) & c.eligible
            if not mask.any(): continue
            x = feature_lookup.reindex(pd.MultiIndex.from_frame(c.loc[mask,IDENTITY])).loc[:,list(cols)]
            c.loc[mask,arm+'_prob'] = models[lane,arm].predict_proba(x)[:,list(models[lane,arm].classes_).index(1)]
    return c.loc[:,CANDIDATE_COLUMNS], f.loc[:,FEATURE_COLUMNS]


def scan(*,act005_root,act008_root,data_root,output_dir,workers=1,batch_size=384,canary_codes=None):
    from ops import pft_s_first_baseline as baseline
    from ops import research_panel_logical as reader
    if not 1 <= workers <= 12 or not 1 <= batch_size <= 384:
        raise ValueError('BOUNDED_RESOURCES_REQUIRED')
    if output_dir.exists() or output_dir.with_name(output_dir.name+'.partial').exists():
        raise ValueError('OUTPUT_EXISTS')
    frozen = old._validate_inputs(act005_root)
    reserved = sorted(c for c,p in frozen['canonical_partition'].items() if p=='OOS' and c not in frozen['excluded_canonical'])
    if len(reserved) != 1348:
        raise ValueError('RESERVED_UNIVERSE_COUNT_DRIFT:'+str(len(reserved)))
    models, hashes, training = frozen_models(act005_root,act008_root)
    training = {frozen['aliases'].get(c,c) for c in training}
    if set(reserved) & training:
        raise ValueError('CANONICAL_S_OR_B_TRAIN_OVERLAP')
    mode = 'CANARY' if canary_codes else 'NATURAL_FULL'
    selected = sorted(set(canary_codes or reserved))
    if not set(selected).issubset(reserved): raise ValueError('CANARY_OUTSIDE_RESERVED_UNIVERSE')
    codes = {c:[] for c in selected}
    for raw, canonical in frozen['aliases'].items():
        if canonical in codes: codes[canonical].append(raw)
    if any(not a for a in codes.values()):raise ValueError('UNMAPPED_CANONICAL')
    stage = output_dir.with_name(output_dir.name+'.partial'); (stage/'shards').mkdir(parents=True)
    universe, shard_files, counts = [], {}, Counter()
    with baseline.bind_current_panels(data_root) as (panel_path,source,recheck):
        verify_source(source,frozen)
        schema = reader.parquet.read_schema(panel_path); mapping,columns = panel_columns(schema)
        with ProcessPoolExecutor(max_workers=workers) if workers>1 else _Inline() as executor:
            for n,batch in enumerate(old._code_cohorts(codes,batch_size)):
                grouped,rows_read = old._read_panel_batch(panel_path,schema,mapping,columns,batch,frozen['aliases'],reader)
                canonicals = sorted({frozen['aliases'][raw] for raw in batch})
                tasks = [(c,grouped.get(c,{}),frozen['crosswalk_aliases']) for c in canonicals]
                results = list(executor.map(scan_security,tasks))
                candidates = [r for rs,_,_ in results for r in rs]
                vectors = [r for _,rs,_ in results for r in rs]
                universe.extend(r for _,_,r in results)
                c,f = infer(candidates,vectors,models)
                for suffix,frame in [('candidates',c),('features',f)]:
                    name = f'shards/{n:04d}_{suffix}.parquet';frame.to_parquet(stage/name,index=False)
                    shard_files[name] = old._sha_file(stage/name)
                counts['rows_read'] += rows_read; counts['signals'] += len(c);counts['unique_code_D'] += len(f)
                for lane in LANES:
                    sub = c[c.lane.eq(lane)]
                    counts[f'{lane}:signals'] += len(sub)
                    counts[f'{lane}:raw'] += int(sub.raw_trigger.sum())
                    counts[f'{lane}:near'] += int(sub.near_trigger.sum())
                    counts[f'{lane}:UNKNOWN'] += int(sub.label.isna().sum())
                    counts[f'{lane}:mismatch'] += int(sub.formula_mismatch.sum())
                write_json(stage/'scan_progress.json',{'mode':mode,'completed_shards':n+1,'completed_codes':len(universe),
                                                     'total_codes':len(selected),'counts':dict(counts),'flags':old.FLAGS})
                print(json.dumps({'shard':n,'codes':len(universe),'signals':counts['signals']},sort_keys=True),flush=True)
        recheck()
    for path,sha in hashes.items():verified_file(Path(path),sha)
    pd.DataFrame(universe).sort_values('canonical_security_id').to_csv(stage/'universe.csv',index=False)
    shard_files['universe.csv'] = old._sha_file(stage/'universe.csv')
    code_paths = [Path(__file__), APP_ROOT/'ops/pft_act008_b_features.py', APP_ROOT/'ops/pft_s_full_ashare_features.py']
    manifest = {'batch':'ACT-010','mode':mode,'flags':old.FLAGS,'source':source,'range':[START,ASOF],
                'history_start':old.START_DATE,'reserved_count':len(reserved),'scanned_count':len(selected),
                'zero_trigger_codes':sum(r['signal_rows']==0 for r in universe),'train_overlap':0,
                'source_input_sha256':frozen['input_sha256'],'models_and_training_sha256':hashes,
                'code_sha256':{str(p):old._sha_file(p) for p in code_paths},'outputs_sha256':shard_files,
                'counters':dict(counts),'features':FEATURE_COLUMNS,'candidate_columns':CANDIDATE_COLUMNS,
                'fits_this_round':{'B':0,'S':0},'inherited_B_fits':12,'outcomes_read':False}
    write_json(stage/'scan_manifest.json',manifest)
    write_json(stage/'pre_outcome_seal.json',{'schema':'ACT010_PRE_OUTCOME_V1','mode':mode,'flags':old.FLAGS,
               'manifest_sha256':old._sha_file(stage/'scan_manifest.json'),'outputs_sha256':shard_files,
               'models_and_training_sha256':hashes,'outcomes_read':False})
    stage.rename(output_dir)
    return {'status':'SEALED','mode':mode,'output_dir':str(output_dir),'signals':counts['signals'],
            'seal_sha256':old._sha_file(output_dir/'pre_outcome_seal.json')}


class _Inline:
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def map(self,fn,tasks):return map(fn,tasks)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    for name in ['act005-root','act008-root','data-root','output-dir']:p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--workers',type=int,default=1);p.add_argument('--batch-size',type=int,default=384)
    p.add_argument('--canary-codes',help='Comma-separated canonical codes; always marks output CANARY')
    a = p.parse_args(argv);a.canary_codes = a.canary_codes.split(',') if a.canary_codes else None
    try:result = scan(**vars(a))
    except Exception as exc:
        print(json.dumps({'status':'FAILED','error':str(exc)}),file=sys.stderr);return 2
    print(json.dumps(result,sort_keys=True));return 0

if __name__=='__main__':raise SystemExit(main())
