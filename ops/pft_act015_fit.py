"""ACT015 stage 2: issuer-held chronological S/B/rank fits and pre-replay prediction seal.

Four main S + inner OOF helpers per two held halves yield exactly 80 successful
model.fit calls. Helpers are research auxiliaries, never official frozen S weights.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from ops.pft_act015_common import *
from ops.pft_s_full_ashare_fit import _fixed_models
from ops.pft_act015_project import worker_init


def training_mask(frame, year, held, *, maturity=False):
    lo, hi = FOLDS[year]
    mask = frame.D.between(lo, hi) & frame.outer.ne(held) & frame.eligible.eq(True)
    if maturity:
        mask &= frame.rank_status.eq('VALID') & frame.target_end.fillna('').between(lo, hi) & frame.rank_target.notna()
    return mask


def sample_rank(frame, role):
    return pd.Series([digest(f'ACT015|{role}|{c}|{d}|{l}') for c, d, l in
                      zip(frame.canonical_security_id, frame.D, frame.get('lane', pd.Series('', index=frame.index)))], index=frame.index)


def capped(frame, count, role, label=None):
    if frame.empty:
        return frame.copy()
    frame = frame.copy()
    frame['_rank_hash'] = sample_rank(frame, role)
    frame = frame.sort_values(['_rank_hash', 'canonical_security_id', 'D'], kind='mergesort')
    if label:
        frame = frame.groupby(label, sort=True).head(count)
    else:
        frame = frame.head(count)
    return frame.reset_index(drop=True)


def merge_cap(previous, found, count, role, label=None):
    if previous is None:
        return capped(found, count, role, label)
    return capped(pd.concat([previous, found], ignore_index=True), count, role, label)


def pools(projection_dir, manifest, year, held):
    """Streaming cap preserves globally smallest hashes without retaining the full pool."""
    s_pool, b_pools, r_pools = None, {}, {}
    counts = Counter()
    for rel in sorted(manifest['outputs_sha256']):
        if not rel.endswith('.parquet'):
            continue
        frame = pd.read_parquet(projection_dir/rel)
        if rel.endswith('_s_train.parquet'):
            found = frame.loc[training_mask(frame, year, held) & frame.S_label.notna()].copy()
            counts['S_available'] += len(found)
            s_pool = merge_cap(s_pool, found, CAPS['S_per_class'], 'S', 'S_label')
        elif rel.endswith('_natural.parquet'):
            train = training_mask(frame, year, held)
            mature = training_mask(frame, year, held, maturity=True)
            in_range = frame.D.between(*FOLDS[year]) & frame.outer.ne(held)
            counts['natural_train_available'] += int(in_range.sum())
            counts['rank_immature_or_unknown'] += int((in_range & ~mature).sum())
            for lane in LANES:
                lane_mask = frame.lane.eq(lane)
                bf = frame.loc[train & lane_mask & frame.label.notna() & frame.formula_mismatch.eq(False)].copy()
                rf = frame.loc[mature & lane_mask].copy()
                counts[lane+'_B_available'] += len(bf)
                counts[lane+'_rank_available'] += len(rf)
                b_pools[lane] = merge_cap(b_pools.get(lane), bf, CAPS['B_per_class'], 'B_'+lane, 'label')
                r_pools[lane] = merge_cap(r_pools.get(lane), rf, CAPS['rank_per_lane'], 'R_'+lane)
        del frame
    if s_pool is None or s_pool.empty:
        raise ValueError('S_TRAIN_EMPTY')
    return s_pool, b_pools, r_pools, dict(counts)


def lr():
    return _fixed_models()['GEMINI_R2_FIXED_LR']


def ranker():
    from sklearn.impute import SimpleImputer
    from sklearn.pipeline import Pipeline
    from sklearn.ensemble import RandomForestRegressor
    return Pipeline([('imputer', SimpleImputer(strategy='median')),
                     ('regressor', RandomForestRegressor(n_estimators=64, max_depth=5,
                         min_samples_leaf=32, random_state=42, n_jobs=-1))])


def s_matrix(frame):
    out = frame[PURE_S].copy()
    out.columns = list(S_FEATURES)
    return out


def probability(model, matrix):
    return model.predict_proba(matrix)[:, list(model.classes_).index(1)]


def s_oof(frame, helpers):
    result = np.full(len(frame), np.nan)
    for inner, model in helpers.items():
        mask = frame.inner.eq(inner).to_numpy()
        if mask.any():
            result[mask] = probability(model, s_matrix(frame.loc[mask]))
    if not np.isfinite(result).all():
        raise ValueError('S_OOF_COVERAGE_INCOMPLETE')
    return result * frame.gate.to_numpy(dtype=float)


def training_identity(frame, label):
    columns = [*IDENTITY, 'outer', 'inner']
    for name in ['lane', 'target_end', 'rank_status', label]:
        if name and name in frame and name not in columns:
            columns.append(name)
    result = frame[columns].copy()
    if result.duplicated([*IDENTITY, *(['lane'] if 'lane' in result else [])]).any():
        raise ValueError('DUPLICATE_TRAINING_IDENTITY')
    return result.sort_values([*IDENTITY, *(['lane'] if 'lane' in result else [])]).reset_index(drop=True)


def read_fit_ledger(path):
    if not path.is_file() or path.is_symlink():
        raise ValueError('UNSAFE_FIT_LEDGER_PATH')
    before = path.stat()
    raw = path.read_bytes()
    after = path.stat()
    stamp = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)
    if stamp(before) != stamp(after):
        raise ValueError('FIT_LEDGER_CHANGED_DURING_READ')
    value = json.loads(raw)
    if not isinstance(value, list) or any(not isinstance(r, dict) for r in value):
        raise ValueError('FIT_LEDGER_MUST_BE_LIST_OF_OBJECTS')
    return value


class FitArchive:
    def __init__(self, stage, year, held, ledger, outputs):
        self.stage, self.year, self.held = stage, year, held
        self.ledger, self.outputs = ledger, outputs
        self.prefix = f'models/{year}_held{held}'
        (stage/self.prefix).mkdir(parents=True, exist_ok=True)

    def fit(self, model, frame, x, label, role, inner=None):
        import joblib
        if frame.empty or not np.isfinite(frame[label].to_numpy(dtype=float)).all():
            raise ValueError('EMPTY_OR_UNKNOWN_FIT_LABEL:' + role)
        if label in ('S_label', 'label'):
            if set(frame[label].astype(int)) != {0, 1}:
                raise ValueError('FIT_REQUIRES_BOTH_CLASSES:' + role)
        lo, hi = FOLDS[self.year]
        if frame.outer.eq(self.held).any() or not frame.D.between(lo, hi).all():
            raise ValueError('OUTER_OR_DATE_TRAIN_LEAKAGE')
        if inner is not None and frame.inner.eq(inner).any():
            raise ValueError('INNER_ISSUER_TRAIN_LEAKAGE')
        if label == 'rank_target' and (not frame.target_end.le(hi).all() or not frame.rank_status.eq('VALID').all()):
            raise ValueError('RANK_OUTCOME_MATURITY_LEAKAGE')
        name = self.prefix+'/'+role
        identities = training_identity(frame, label)
        matrix_hash = digest(pd.util.hash_pandas_object(x, index=False).to_numpy().tobytes().hex())
        # A resume may reuse only an exact successful archive, never a role name alone.
        matches = [r for r in self.ledger if (r['test_year'], r['held_outer'], r['role']) == (self.year, self.held, role)]
        if matches:
            if len(matches) != 1:
                raise ValueError('DUPLICATE_RESUME_FIT_ROLE')
            record = matches[0]
            expected_bytes = identities.to_csv(index=False).encode()
            membership_path = verified_file(self.stage/(name+'_membership.csv'), record['membership_sha256'])
            model_path = verified_file(self.stage/(name+'.joblib'), record['model_sha256'])
            if (record['status'] != 'ARCHIVED_RELOAD_PASS' or record['train_start'] != lo or record['train_end'] != hi
                or record['held_inner'] != inner or record['train_rows'] != len(frame)
                or record['train_issuers'] != frame.canonical_security_id.nunique()
                or record['matrix_sha256'] != matrix_hash or membership_path.read_bytes() != expected_bytes):
                raise ValueError('RESUME_EXACT_TRAINING_IDENTITY_MISMATCH:' + name)
            restored = joblib.load(model_path)
            if list(restored.feature_names_in_) != list(x.columns):
                raise ValueError('RESUME_MODEL_COLUMNS_MISMATCH')
            self.outputs[name+'_membership.csv'] = record['membership_sha256']
            self.outputs[name+'.joblib'] = record['model_sha256']
            print(json.dumps({'stage': 'RESUME_ARCHIVE_REUSED', 'fit_call': record['fit_call'],
                              'test_year': self.year, 'held_outer': self.held, 'role': role,
                              'model_sha256': record['model_sha256']}, sort_keys=True), flush=True)
            return restored
        identities.to_csv(self.stage/(name+'_membership.csv'), index=False)
        identity_hash = old._sha_file(self.stage/(name+'_membership.csv'))
        started = time.monotonic()
        try:
            model.fit(x, frame[label].to_numpy())
        except Exception as exc:
            write_json(self.stage/f'fit_failure_{len(self.ledger)+1:03d}_{role}.json', {'role': role, 'year': self.year, 'held': self.held,
                      'successful_fit_calls_before_failure': len(self.ledger), 'error': str(exc)})
            raise
        # Count only returned successful calls, even if archive checks later fail.
        record = {'fit_call': len(self.ledger)+1, 'test_year': self.year, 'held_outer': self.held,
                  'role': role, 'held_inner': inner, 'train_start': lo, 'train_end': hi,
                  'train_rows': len(frame), 'train_issuers': frame.canonical_security_id.nunique(),
                  'train_class_counts': {str(k): int(v) for k, v in frame[label].value_counts().items()} if label != 'rank_target' else None,
                  'max_target_end': frame.target_end.max() if label == 'rank_target' else None,
                  'membership_sha256': identity_hash, 'matrix_sha256': matrix_hash,
                  'elapsed_seconds': time.monotonic()-started, 'status': 'FIT_RETURNED'}
        self.ledger.append(record)
        write_json(self.stage/'fit_ledger.json', self.ledger)
        if label == 'rank_target':
            # Parallel fitting, deterministic tree reduction for every inference.
            model.set_params(regressor__n_jobs=1)
            record.update(fit_n_jobs=-1, inference_n_jobs=1)
        joblib.dump(model, self.stage/(name+'.joblib'), compress=3)
        restored = joblib.load(self.stage/(name+'.joblib'))
        sample = x.iloc[:min(3, len(x))]
        predict = 'predict' if label == 'rank_target' else 'predict_proba'
        np.testing.assert_allclose(getattr(model, predict)(sample), getattr(restored, predict)(sample), rtol=0, atol=0)
        for suffix in ['_membership.csv', '.joblib']:
            self.outputs[name+suffix] = old._sha_file(self.stage/(name+suffix))
        record.update(status='ARCHIVED_RELOAD_PASS', model_sha256=self.outputs[name+'.joblib'])
        write_json(self.stage/'fit_ledger.json', self.ledger)
        print(json.dumps(record, sort_keys=True), flush=True)
        return model


def fit_fold(stage, projection_dir, manifest, year, held, ledger, outputs):
    sp, bp, rp, counts = pools(projection_dir, manifest, year, held)
    archive = FitArchive(stage, year, held, ledger, outputs)
    main = archive.fit(lr(), sp, s_matrix(sp), 'S_label', 'S_MAIN')
    helpers = {}
    for inner in range(3):
        train = sp.loc[sp.inner.ne(inner)].reset_index(drop=True)
        helpers[inner] = archive.fit(lr(), train, s_matrix(train), 'S_label', f'S_INNER_{inner}', inner)
    models = {}
    for lane in LANES:
        b, r = bp[lane], rp[lane]
        b['S_probability'] = s_oof(b, helpers)
        r['S_probability'] = s_oof(r, helpers)
        # Missing gate is unavailable input, handled by the frozen median recipe.
        models[lane, 'B'] = archive.fit(lr(), b, b[list(FULL_FEATURES)], 'label', lane+'_B')
        models[lane, 'R'] = archive.fit(ranker(), r, r[list(FULL_FEATURES)], 'rank_target', lane+'_RANK_H5')
    return main, helpers, models, counts


def infer_frame(frame, year, held, main, models):
    out = frame.loc[frame.D.str[:4].eq(str(year)) & frame.outer.eq(held)].copy()
    if out.empty:
        return out
    out['S_prob_raw'] = np.nan
    out['S_prob_gated'] = np.nan
    out['B_probability'] = np.nan
    out['rank_score'] = np.nan
    ready = out.eligible.eq(True)
    if ready.any():
        out.loc[ready, 'S_prob_raw'] = probability(main, s_matrix(out.loc[ready]))
    out['S_prob_gated'] = out.S_prob_raw * out.gate
    out['S_probability'] = out.S_prob_gated
    for lane in LANES:
        mask = ready & out.lane.eq(lane)
        if mask.any():
            x = out.loc[mask, list(FULL_FEATURES)]
            out.loc[mask, 'B_probability'] = probability(models[lane, 'B'], x)
            out.loc[mask, 'rank_score'] = models[lane, 'R'].predict(x)
    out['hard_eligible'] = ready & out.S_prob_gated.ge(.5) & out.B_probability.ge(.5) & np.isfinite(out.rank_score)
    out['model_year'] = year
    out['held_outer'] = held
    columns = ['episode_id', *IDENTITY, 'lane', 'outer', 'inner', 'model_year', 'held_outer', 'raw_trigger', 'near_trigger',
               'eligible', 'label', 'stratum', 'reason', 'formula_mismatch', 'gate', 'prior_anchor_date', 'prior_anchor_low',
               'S_prob_raw', 'S_prob_gated', 'B_probability', 'rank_score', 'hard_eligible']
    # Prediction output deliberately excludes every training outcome field.
    return out[columns]


def fit(*, projection_dir, output_dir, resume=False):
    worker_init()
    m = read_manifest(projection_dir, 'projection_manifest.json')
    if m['mode'] != 'FULL' or m['range'] != [START, ASOF] or m.get('2026_outcome_labels_read') is not False:
        raise ValueError('FULL_CAUSAL_PROJECTION_REQUIRED')
    binding = {'projection_manifest_sha256': old._sha_file(projection_dir/'projection_manifest.json'),
               'folds': nullable(FOLDS), 'caps': CAPS, 'source': m['source']}
    if resume:
        stage = output_dir.with_name(output_dir.name+'.partial')
        if output_dir.exists() or not stage.is_dir() or stage.is_symlink():
            raise ValueError('RESUME_REQUIRES_ONLY_PARTIAL_STAGE')
        ledger = read_fit_ledger(stage/'fit_ledger.json') if (stage/'fit_ledger.json').exists() else []
        roles = [(r['test_year'], r['held_outer'], r['role']) for r in ledger]
        if (len(roles) != len(set(roles)) or [r['fit_call'] for r in ledger] != list(range(1, len(ledger)+1))
            or any(r['status'] != 'ARCHIVED_RELOAD_PASS' for r in ledger)):
            raise ValueError('UNSAFE_RESUME_LEDGER')
        if (stage/'resume_identity.json').exists():
            if old._read_json(stage/'resume_identity.json') != nullable(binding):
                raise ValueError('RESUME_PROJECTION_BINDING_MISMATCH')
        elif list((stage/'predictions').glob('*.parquet')):
            # Older interrupted runner had no binding; only pre-prediction archives
            # can be recovered, and each is rebuilt/compared by FitArchive.fit.
            raise ValueError('LEGACY_RESUME_WITH_UNBOUND_PREDICTIONS_FORBIDDEN')
        write_json(stage/'resume_identity.json', nullable(binding))
    else:
        stage = new_stage(output_dir)
        ledger = []
        write_json(stage/'resume_identity.json', nullable(binding))
    (stage/'predictions').mkdir(exist_ok=True)
    outputs, fold_counts, coverage = {}, [], Counter()
    natural_files = [r for r in sorted(m['outputs_sha256']) if r.endswith('_natural.parquet')]
    for year in FOLDS:
        for held in (0, 1):
            main, helpers, models, counts = fit_fold(stage, projection_dir, m, year, held, ledger, outputs)
            fold_counts.append({'test_year': year, 'held_outer': held, **counts})
            for shard, rel in enumerate(natural_files):
                inference_columns = ['episode_id', *IDENTITY, 'lane', 'outer', 'inner', 'eligible',
                    'raw_trigger', 'near_trigger', 'label', 'stratum', 'reason', 'formula_mismatch',
                    'gate', 'prior_anchor_date', 'prior_anchor_low', *NUMERIC]
                frame = pd.read_parquet(projection_dir/rel, columns=inference_columns)
                pred = infer_frame(frame, year, held, main, models)
                expected = int((frame.D.str[:4].eq(str(year)) & frame.outer.eq(held)).sum())
                if len(pred) != expected:
                    raise ValueError('OOS_NATURAL_COVERAGE_MISMATCH')
                coverage[f'{year}_held{held}'] += len(pred)
                if not pred.empty:
                    name = f'predictions/{year}_held{held}_{shard:04d}.parquet'
                    pred.sort_values(['D', 'canonical_security_id', 'lane']).to_parquet(stage/name, index=False, compression='zstd')
                    outputs[name] = old._sha_file(stage/name)
            del main, helpers, models
    if len(ledger) != 80 or any(r['status'] != 'ARCHIVED_RELOAD_PASS' for r in ledger):
        raise ValueError('EXPECTED_80_ARCHIVED_SUCCESSFUL_FITS')
    outputs['fit_ledger.json'] = old._sha_file(stage/'fit_ledger.json')
    write_json(stage/'fold_counts.json', fold_counts)
    outputs['fold_counts.json'] = old._sha_file(stage/'fold_counts.json')
    report = {'schema': 'ACT015_FIT_PREDICTION_V1', 'mode': m['mode'], 'source': m['source'], 'sessions': m['sessions'],
              'projection_manifest_sha256': old._sha_file(projection_dir/'projection_manifest.json'),
              'actual_successful_fit_calls': len(ledger), 'fit_roles': dict(Counter(r['role'].split('_')[0] for r in ledger)),
              'coverage': dict(coverage), 'folds': FOLDS, 'caps': CAPS, 'outputs_sha256': outputs,
              'prediction_outcomes_read': False, '2026_used_in_any_fit': False, 'thresholds': {'S': .5, 'B': .5},
              'rank_target': 'H5 net return_pct + 0.5 * running-close MDD_pct; no B in-sample score input',
              'S_OOF': '3 issuer groups; no held inner issuer in its helper, outer training dates only',
              'code_sha256': {str(p): old._sha_file(p) for p in [Path(__file__), ROOT/'ops/pft_act015_common.py']}}
    # Seal all predictions, weights and membership hashes BEFORE a replay reads execution market.
    write_json(stage/'pre_replay_seal.json', {'schema': 'ACT015_PRE_REPLAY_V1', 'batch': 'ACT-015', 'flags': old.FLAGS,
              'outputs_sha256': outputs, 'fit_calls': 80, 'prediction_outcomes_read': False,
              'projection_manifest_sha256': report['projection_manifest_sha256']})
    outputs['pre_replay_seal.json'] = old._sha_file(stage/'pre_replay_seal.json')
    return finish_manifest(stage, output_dir, 'fit_manifest.json', report)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--projection-dir', type=Path, required=True)
    p.add_argument('--output-dir', type=Path, required=True)
    p.add_argument('--resume', action='store_true', help='Verify and reuse exact archived successful calls in .partial')
    try:
        result = fit(**vars(p.parse_args(argv)))
    except Exception as exc:
        return cli_failure(exc)
    print(json.dumps(result, sort_keys=True)); return 0


if __name__ == '__main__':
    raise SystemExit(main())
