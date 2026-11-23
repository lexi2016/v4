"""ACT032 research-only training and a separately locked 2026 scoring phase."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
from importlib.metadata import version
from itertools import product
import json
from pathlib import Path
import re
import warnings

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import ExtraTreesClassifier, GradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.preprocessing import RobustScaler
from threadpoolctl import threadpool_limits

from ops.pft_act030_eval import EVENT, NEG, PENDING, POS, SCORES, SUBTYPES, indexed, metrics, need, sha, validate_scores
from ops.pft_act030_features import FEATURES, FLAGS

DEV, VAL, TEST = 'DEV_CV_2020_2024', 'OOT_VAL_2025', 'OOT_TEST_2026'
ROLES = (DEV, VAL, TEST)
EXPECTED = {DEV: (171, 38, 42, 9), VAL: (36, 7, 8, 1), TEST: (33, 7, 11, 3)}
FAMILIES = ('L2_LR', 'RF', 'ExtraTrees', 'LightGBM', 'GBDT')
ADV_TIERS = ('<1亿', '1-3亿', '≥3亿')
CORE = (POS, NEG)
EXAM = (*CORE, EVENT)
SEED = 20261123
A_FLOOR, A_PRECISION, EVENT_THRESHOLD = .70, .85, .60
S_THRESHOLD = .50
PRICE_BASIS = ('D_LOCAL_QFQ', 'ARCHIVE_QFQ_BSE_FALLBACK')


def now():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, data, *, exclusive=False):
    if exclusive:
        with path.open('x', encoding='utf-8') as file:
            json.dump(data, file, ensure_ascii=False, indent=2, allow_nan=False)
            file.write('\n')
        return
    staging = path.with_suffix(path.suffix + '.tmp')
    with staging.open('x', encoding='utf-8') as file:
        json.dump(data, file, ensure_ascii=False, indent=2, allow_nan=False)
        file.write('\n')
    staging.replace(path)


def csv_bool(value):
    word = str(value).lower()
    need(word in ('true', 'false', '1', '0'), 'BAD_FEATURE_GATE_FIELD')
    return word in ('true', '1')


def read_features(path, roles):
    frame = pd.read_csv(path, dtype={'episode_id': str, 'security_id': str, 'D': str})
    metadata = ('episode_id', 'security_id', 'board', 'D', 'adv20_cny', 'price_basis', 'h0_ok', 'g1_w_gt_y')
    need(set(frame.columns) == set(metadata + FEATURES), 'FEATURE_SCHEMA_DRIFT')
    frame = frame.sort_values('episode_id').set_index('episode_id', drop=False)
    need(len(frame) == sum(EXPECTED[r][0] for r in roles) and frame.index.is_unique
         and frame.security_id.nunique() == len(frame), 'FEATURE_COHORT_OR_SECURITY_DRIFT')
    need(frame.D.str.fullmatch(r'20(2[0-6])-\d{2}-\d{2}').all(), 'FEATURE_DATE_DRIFT')
    years = frame.D.str[:4].astype(int)
    actual_sizes = {DEV: int(years.le(2024).sum()), VAL: int(years.eq(2025).sum()), TEST: int(years.eq(2026).sum())}
    need(actual_sizes == {r: EXPECTED[r][0] if r in roles else 0 for r in ROLES}, 'FEATURE_ROLE_DRIFT')
    need(not np.isinf(frame[list(FEATURES)].to_numpy(dtype=float)).any(), 'INFINITE_FEATURE')
    need(np.isfinite(frame.adv20_cny).all() and frame.adv20_cny.ge(0).all(), 'FEATURE_ADV_INVALID')
    need(set(frame.price_basis) <= set(PRICE_BASIS), 'FEATURE_BASIS_DRIFT')
    fallback = frame.price_basis == PRICE_BASIS[1]
    need(frame.loc[fallback, 'board'].eq('BSE').all(), 'BSE_FALLBACK_BOARD_DRIFT')
    for flag in ('h0_ok', 'g1_w_gt_y'):
        frame[flag] = frame[flag].map(csv_bool)
    return frame


def read_labels(path, features, roles):
    data = json.loads(path.read_text(encoding='utf-8'))
    rows = indexed(data)
    years = features.D.str[:4].astype(int)
    role_ids = {DEV: set(years.index[years.le(2024)]), VAL: set(years.index[years.eq(2025)]),
                TEST: set(years.index[years.eq(2026)])}
    need(set(rows) == set.union(*(role_ids[role] for role in roles)), 'LABEL_EXPECTED_ID_PARTITION_DRIFT')
    for role in roles:
        counts = Counter()
        for eid in sorted(role_ids[role]):
            row = rows[eid]
            base = features.loc[eid]
            for name in ('security_id', 'board', 'D'):
                need(row[name] == base[name], 'LABEL_FEATURE_IDENTITY_DRIFT')
            need(int(row['year']) == int(years.loc[eid]) and row['split_role'] == role, 'LABEL_ROLE_DRIFT')
            amount = float(base['adv20_cny'])
            need(np.isclose(float(row['adv20_cny']), amount, rtol=1e-8, atol=.01), 'LABEL_ADV_DRIFT')
            tier = ADV_TIERS[0 if amount < 1e8 else 1 if amount < 3e8 else 2]
            need(row['adv20_tier'] == tier, 'LABEL_ADV_BUCKET_DRIFT')
            label = row['consensus_status']
            if label in (*EXAM, PENDING):
                need(row['is_unanimous'] is True and row['gold_status_chat'] == row['gold_status_gem'] == label,
                     'LABEL_UNANIMITY_DRIFT')
            counts[label] += 1
        actual = (len(role_ids[role]), counts[POS], counts[NEG], counts[EVENT])
        need(actual == EXPECTED[role], f'FROZEN_LABEL_COUNTER_DRIFT_{role}_{actual}')
    return rows


def grid():
    candidates = []
    def add(family, settings):
        for params in settings:
            candidates.append((family, len(candidates) + 1, params))
    add('L2_LR', (dict(C=c) for c in (.05, .1, .3, 1.0)))
    tree_configs = [dict(n_estimators=n, max_depth=depth, min_samples_leaf=leaf, max_features=feat)
                    for n, depth, leaf, feat in product((100, 200), (2, 3), (8, 12, 16), (.4, .6, 'sqrt'))]
    for family in ('RF', 'ExtraTrees'):
        add(family, tree_configs)
    # Fractional grid pairs leaves/shape, observation subsampling and penalties.
    add('LightGBM', (
        dict(n_estimators=n, max_depth=depth, num_leaves=leaves, learning_rate=lr, min_child_samples=child,
             reg_alpha=alpha, reg_lambda=penalty, subsample=sample, colsample_bytree=features)
        for n, (depth, leaves), lr, (child, alpha, penalty, sample, features) in product(
            (30, 50, 80), ((2, 4), (3, 6), (3, 8)), (.03, .05),
            ((10, .5, 2.0, .7, .8), (15, 1.0, 5.0, .8, .7), (20, 2.0, 10.0, .8, .8)))))
    add('GBDT', (dict(n_estimators=n, max_depth=depth, min_samples_leaf=leaf, learning_rate=lr, subsample=.8,
                      max_features=.7) for n, depth, leaf, lr in product((30, 50, 80), (2, 3), (8, 12, 16),
                                                                        (.03, .05))))
    return candidates


def estimator(family, params):
    if family == 'L2_LR':
        return LogisticRegression(solver='lbfgs', max_iter=1000, random_state=SEED, **params)
    if family == 'RF':
        return RandomForestClassifier(n_jobs=1, random_state=SEED, **params)
    if family == 'ExtraTrees':
        return ExtraTreesClassifier(n_jobs=1, random_state=SEED, **params)
    if family == 'GBDT':
        return GradientBoostingClassifier(random_state=SEED, **params)
    if family == 'LightGBM':
        from lightgbm import LGBMClassifier
        return LGBMClassifier(n_jobs=1, random_state=SEED, subsample_freq=1, verbosity=-1, deterministic=True,
                              force_col_wise=True, **params)
    raise ValueError('UNKNOWN_MODEL_FAMILY')


def probabilities(model, transformed):
    need(np.array_equal(model.classes_, [0, 1]), 'BINARY_ESTIMATOR_CLASS_DRIFT')
    # Recent LightGBM assigns default feature names even to fitted ndarrays.
    with warnings.catch_warnings():
        warnings.filterwarnings('ignore', message='X does not have valid feature names.*')
        result = model.predict_proba(transformed)[:, 1]
    need(np.isfinite(result).all() and np.all((result >= 0) & (result <= 1)), 'INVALID_MODEL_PROBABILITY')
    return result


def design_matrix(features, ids):
    return features.loc[ids, list(FEATURES)].to_numpy(dtype=float)


def preprocessing(train):
    need(train.shape[1] == len(FEATURES) and np.isfinite(train).any(axis=0).all(),
         'ALL_MISSING_FEATURE_IN_TRAIN_FOLD')
    median = np.nanmedian(train, axis=0)
    imputed = np.where(np.isnan(train), median, train)
    low, high = np.quantile(imputed, [.01, .99], axis=0)
    scaler = RobustScaler().fit(np.clip(imputed, low, high))
    return dict(median=median, low=low, high=high, scaler=scaler)


def transform(prep, matrix):
    filled = np.where(np.isnan(matrix), prep['median'], matrix)
    return prep['scaler'].transform(np.clip(filled, prep['low'], prep['high']))


def planned_folds(dev_ids, labels):
    core = [eid for eid in dev_ids if labels[eid]['consensus_status'] in CORE]
    status = np.array([labels[eid]['consensus_status'] for eid in core])
    groups = [labels[eid]['security_id'] for eid in core]
    subtypes = [labels[eid]['consensus_subtype'] if labels[eid]['consensus_subtype'] in SUBTYPES else 'UNRESOLVED'
                for eid in core]
    tiers = [labels[eid]['adv20_tier'] for eid in core]
    strata = [f'{label}|{subtype if label == POS else "NA"}|{tier}'
              for label, subtype, tier in zip(status, subtypes, tiers)]
    counts = Counter(strata)
    pos_subtypes = Counter(t for label, t in zip(status, subtypes) if label == POS)

    def fold_cost(folds):
        missing = sum(set(status[test]) != set(CORE) for _, test in folds)
        missing += sum(len(set(ADV_TIERS) - {tiers[i] for i in test}) for _, test in folds)
        subtype_missing = sum(t not in {subtypes[i] for i in test if status[i] == POS}
                              for _, test in folds for t in SUBTYPES if pos_subtypes[t] >= 5)
        balance = sum((int(sum(status[test] == POS)) - len(core) * (status == POS).mean() / 5)**2
                      + (int(sum(status[test] == NEG)) - len(core) * (status == NEG).mean() / 5)**2
                      for _, test in folds)
        return missing, subtype_missing, float(balance)

    best = None
    # Deterministic design-only search balances rare strata without using features or fit outcomes.
    with warnings.catch_warnings():
        warnings.filterwarnings('ignore', message='The least populated class in y has only.*')
        for seed in range(SEED, SEED + 256):
            splitter = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=seed)
            folds = list(splitter.split(np.zeros(len(core)), strata, groups))
            cost = (*fold_cost(folds), seed)
            if best is None or cost < best[0]:
                best = cost, folds
    need(best and best[0][0] == 0, 'FOLD_CORE_CLASS_OR_ADV_MISSING')
    assignment = {core[i]: fold for fold, (_, test) in enumerate(best[1], 1) for i in test}
    audits = {}
    for eid in dev_ids:
        if eid not in assignment:
            audits.setdefault(labels[eid]['consensus_status'], []).append(eid)
    for bucket in audits.values():
        for i, eid in enumerate(bucket):
            assignment[eid] = 1 + i % 5
    need(set(assignment) == set(dev_ids) and len(assignment) == len(dev_ids), 'OOF_PARTITION_DRIFT')
    receipt = dict(seed=best[0][-1], strata_counts=dict(sorted(counts.items())),
                   pos_subtype_counts=dict(sorted(pos_subtypes.items())),
                   rare_strata={k: n for k, n in counts.items() if n < 5}, fold_assignment=assignment, folds=[])
    for fold in range(1, 6):
        training = [eid for eid in core if assignment[eid] != fold]
        holdout = [eid for eid in dev_ids if assignment[eid] == fold]
        need(not ({labels[x]['security_id'] for x in training} & {labels[x]['security_id'] for x in holdout}),
             'SECURITY_OVERLAP_FOLD')
        hold_core = [eid for eid in holdout if labels[eid]['consensus_status'] in CORE]
        receipt['folds'].append(dict(fold=fold, train_n=len(training), held_n=len(holdout),
                                     core_status=dict(Counter(labels[eid]['consensus_status'] for eid in hold_core)),
                                     core_adv=dict(Counter(labels[eid]['adv20_tier'] for eid in hold_core)),
                                     pos_subtype=dict(Counter(labels[eid]['consensus_subtype'] for eid in hold_core
                                                              if labels[eid]['consensus_status'] == POS))))
    return core, assignment, receipt


def binary_matrix(features, train_ids, held_ids, labels, positives):
    raw_train = design_matrix(features, train_ids)
    prep = preprocessing(raw_train)
    outcome = np.array([int(labels[eid]['consensus_status'] in positives) for eid in train_ids])
    need(set(outcome) == {0, 1}, 'TRAINING_REQUIRES_TWO_CLASSES')
    return prep, transform(prep, raw_train), outcome, transform(prep, design_matrix(features, held_ids))


def cv_task(config, matrices):
    family, number, params = config
    scores, calls, fit_ok = [], 0, 0
    try:
        for x, y, held_x in matrices:
            model = estimator(family, params)
            calls += 1
            model.fit(x, y)
            fit_ok += 1
            scores.append(probabilities(model, held_x))
    except Exception as exc:
        return dict(family=family, config_id=number, params=params, calls=calls, successful=fit_ok,
                    error=f'{type(exc).__name__}: {exc}')
    return dict(family=family, config_id=number, params=params, calls=calls, successful=fit_ok, scores=scores)


def actual_fit(model, x, y, ledger, *, stage, family, config_id=None):
    item = dict(stage=stage, family=family, config_id=config_id, calls=1, successful=0)
    try:
        model.fit(x, y)
        item['successful'] = 1
    except Exception as exc:
        item['error'] = f'{type(exc).__name__}: {exc}'
        raise
    finally:
        ledger(item)
    return model


def gates(features):
    return (features.h0_ok & features.g1_w_gt_y).to_dict()


def s_view(ids, labels, probabilities_by_id, score_key='score'):
    return [dict(episode_id=eid, unanimous_gold_v1=labels[eid]['consensus_status'], **{score_key: probabilities_by_id[eid]})
            for eid in ids]


def ranking_key(candidate):
    overall = candidate['oof_metrics']
    # Mean fold F1 is the objective. All tie-breaks use the same DEV held-out scores.
    return (-candidate['fold_f1_mean'], overall['fpr'], -overall['auc'], overall['brier'], candidate['config_id'])


def logit(p):
    clipped = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(clipped / (1 - clipped)).reshape(-1, 1)


def calibrate_probabilities(calibrator, method, native):
    if method == 'identity_nonpositive_platt_slope':
        return native
    need(method == 'platt_logit', 'UNKNOWN_CALIBRATION_METHOD')
    return probabilities(calibrator, logit(native))


def choose_a(gated_prob, y, audit_gated_prob):
    options = sorted({A_FLOOR, *(float(x) for x in gated_prob if x >= A_FLOOR)})
    candidates = []
    for threshold in options:
        hits = gated_prob >= threshold
        total, tp = int(hits.sum()), int(y[hits].sum())
        if total and tp / total >= A_PRECISION:
            # Pending status influences validation threshold only, never binary fit.
            pending_hits = int(np.sum(audit_gated_prob >= threshold))
            candidates.append((pending_hits, -tp, total - tp, threshold, total))
    if not candidates:
        return dict(threshold=None, qualified=False, val_n=len(y), val_a_n=0, val_a_tp=0,
                    val_pending_n=len(audit_gated_prob), val_pending_a_n=0, val_a_precision=None)
    pending, neg_tp, _, threshold, total = min(candidates)
    return dict(threshold=threshold, qualified=True, val_n=len(y), val_a_n=total, val_a_tp=-neg_tp,
                val_pending_n=len(audit_gated_prob), val_pending_a_n=pending, val_a_precision=-neg_tp/total)


def pending_audit(row):
    return PENDING in (row['gold_status_chat'], row['gold_status_gem'])


def fit_phase(args):
    run = args.run_dir
    need(run.is_dir() and not (run / 'fit_plan.json').exists(), 'FIT_RUN_ALREADY_STARTED_OR_PATH_MISSING')
    paths = {'features': args.features, 'selection_labels': args.selection_labels, 'code': Path(__file__)}
    hashes = {key: sha(path) for key, path in paths.items()}
    holdout_hashes = dict(test_features=args.test_features_sha, test_labels=args.test_labels_sha)
    need(all(re.fullmatch(r'[0-9a-f]{64}', digest) for digest in holdout_hashes.values()), 'BAD_HOLDOUT_FROZEN_SHA')
    features = read_features(args.features, (DEV, VAL))
    labels = read_labels(args.selection_labels, features, (DEV, VAL))
    dev_ids = sorted(eid for eid, row in labels.items() if row['split_role'] == DEV)
    val_ids = sorted(eid for eid, row in labels.items() if row['split_role'] == VAL)
    dev_core, assignment, fold_receipt = planned_folds(dev_ids, labels)
    val_core = [eid for eid in val_ids if labels[eid]['consensus_status'] in CORE]
    val_pending = [eid for eid in val_ids if pending_audit(labels[eid])]
    val_pos = np.array([int(labels[eid]['consensus_status'] == POS) for eid in val_core])
    sv2_gate = gates(features)
    cfg = grid()
    versions = {p: version(p) for p in ('scikit-learn', 'numpy', 'pandas', 'joblib', 'lightgbm')}
    grid_counts = dict(Counter(f for f, _, _ in cfg))
    need(set(grid_counts) == set(FAMILIES), 'GRID_MISSING_MODEL_FAMILY')
    write_json(run / 'fit_plan.json', dict(created_utc=now(), hashes=hashes, holdout_hashes=holdout_hashes, roles=[DEV, VAL],
                                          features=list(FEATURES), fold_plan=fold_receipt,
                                          grid=cfg, grid_counts=grid_counts, versions=versions,
                                          workers=args.workers, estimator_threads=1,
                                          selection='DEV native gated mean fold F1 @0.50, then FPR/AUC/Brier/grid order',
                                          calibration='2025 core-only L2 sigmoid on clipped logits; identity if fitted slope <=0; no isotonic',
                                          threshold_a='2025 calibrated gated, precision >=85%, score >=0.70',
                                          **FLAGS), exclusive=True)
    # Preprocessing is fitted once per fold and reused without crossing fold boundaries.
    matrices, held_ids = [], []
    for fold in range(1, 6):
        train = [eid for eid in dev_core if assignment[eid] != fold]
        held = [eid for eid in dev_ids if assignment[eid] == fold]
        _, xx, y, hx = binary_matrix(features, train, held, labels, (POS,))
        matrices.append((xx, y, hx))
        held_ids.append(held)
    dev_summary = []
    oof_winners = {}
    winners = {}
    counter = Counter()
    success = Counter()
    failed = 0
    with (run / 'fit_ledger.jsonl').open('x', encoding='utf-8') as fit_log:
        def ledger(item):
            key = item['stage']
            counter[key] += item['calls']
            success[key] += item['successful']
            fit_log.write(json.dumps(item, ensure_ascii=False, allow_nan=False) + '\n')
            fit_log.flush()
        with joblib.parallel_config(backend='loky', inner_max_num_threads=1):
            worker = joblib.Parallel(n_jobs=args.workers, return_as='generator_unordered', pre_dispatch='2*n_jobs')
            for result in worker(joblib.delayed(cv_task)(c, matrices) for c in cfg):
                scores = result.pop('scores', None)
                ledger({'stage': 's_dev_cv', **result})
                if scores is None:
                    failed += 1
                    continue
                oof = {eid: float(p) for ids, array in zip(held_ids, scores)
                       for eid, p in zip(ids, array, strict=True)}
                gated = {eid: p if sv2_gate[eid] else 0.0 for eid, p in oof.items()}
                measures = metrics(s_view(dev_core, labels, gated), 'score', ks=(20, 50))
                fold_f1 = [metrics(s_view([x for x in dev_core if assignment[x] == fold], labels, gated),
                                   'score', ks=())['f1'] for fold in range(1, 6)]
                candidate = dict(family=result['family'], config_id=result['config_id'], params=result['params'],
                                 fold_f1=fold_f1, fold_f1_mean=float(np.mean(fold_f1)),
                                 fold_f1_std=float(np.std(fold_f1)), oof_metrics=measures)
                dev_summary.append(candidate)
                family = candidate['family']
                if family not in winners or ranking_key(candidate) < ranking_key(winners[family]):
                    winners[family] = candidate
                    oof_winners[family] = oof
        need(not failed and set(winners) == set(FAMILIES), 'INCOMPLETE_GRID_SEE_FIT_LEDGER')
        dev_summary.sort(key=lambda x: x['config_id'])
        winner = min(winners.values(), key=ranking_key)['family']
        write_json(run / 'grid_results.json', dict(all_candidates=dev_summary, winners=winners, winner=winner,
                                                   source='DEV exclusively', completed_utc=now()))
        core_prep, full_x, full_y, val_predict_x = binary_matrix(features, dev_core, val_ids, labels, (POS,))
        val_positions = {eid: i for i, eid in enumerate(val_ids)}
        core_pos = [val_positions[eid] for eid in val_core]
        pending_pos = [val_positions[eid] for eid in val_pending]
        val_gate = np.array([sv2_gate[eid] for eid in val_ids])
        models = {}
        with threadpool_limits(limits=1):
            for family in FAMILIES:
                best = winners[family]
                model = actual_fit(estimator(family, best['params']), full_x, full_y, ledger, stage='s_dev_refit',
                                   family=family, config_id=best['config_id'])
                native = probabilities(model, val_predict_x)
                calibrator = actual_fit(LogisticRegression(C=1, solver='lbfgs', max_iter=1000),
                                        logit(native[core_pos]), val_pos, ledger, stage='s_2025_platt', family=family)
                slope, intercept = float(calibrator.coef_[0, 0]), float(calibrator.intercept_[0])
                method = 'platt_logit' if slope > 0 else 'identity_nonpositive_platt_slope'
                calibrated = calibrate_probabilities(calibrator, method, native)
                gated = np.where(val_gate, calibrated, 0.0)
                calibration = dict(method=method, slope=slope, intercept=intercept, fit_n=int(len(val_pos)),
                                   fit_pos=int(val_pos.sum()), fit_neg=int(len(val_pos) - val_pos.sum()))
                models[family] = dict(model=model, calibrator=calibrator, calibration=calibration,
                                      grade_a=choose_a(gated[core_pos], val_pos, gated[pending_pos]))
            # Separate, fixed H0-independent E model. Hard-negative S labels are a weak E proxy.
            event_ids = [eid for eid in dev_ids if labels[eid]['consensus_status'] in EXAM]
            event_oof = {}
            for fold, held in enumerate(held_ids, 1):
                event_train = [eid for eid in event_ids if assignment[eid] != fold]
                prep, x, y, hx = binary_matrix(features, event_train, held, labels, (POS, EVENT))
                model = actual_fit(estimator('L2_LR', {'C': .10}), x, y, ledger, stage='e_dev_cv', family='E_LR')
                event_oof.update(zip(held, map(float, probabilities(model, hx)), strict=True))
            event_prep, x, y, _ = binary_matrix(features, event_ids, val_ids, labels, (POS, EVENT))
            event_model = actual_fit(estimator('L2_LR', {'C': .10}), x, y, ledger,
                                     stage='e_dev_refit', family='E_LR')
    need(sum(counter.values()) == len(cfg)*5 + (len(FAMILIES)*2) + 6 and counter == success, 'FIT_LEDGER_MISMATCH')
    saved = dict(schema='PFT_ACT032_RESEARCH_WEIGHTS_V1', feature_order=FEATURES, core_prep=core_prep,
                 models=models, winner=winner, oof_winners=oof_winners, event_oof=event_oof,
                 event_prep=event_prep, event_model=event_model, fold_assignment=assignment)
    weights_dir = run / 'weights'
    weights_dir.mkdir(mode=0o700, exist_ok=True)
    bundle = weights_dir / 'sv2_research_weights.joblib'
    with bundle.open('xb') as file:
        joblib.dump(saved, file, compress=3)
    lock = dict(schema='PFT_ACT032_SELECTION_LOCK_V1', completed_utc=now(), hashes=hashes, holdout_hashes=holdout_hashes,
                fit_plan_sha=sha(run / 'fit_plan.json'), fit_ledger_sha=sha(run / 'fit_ledger.jsonl'),
                weights_sha=sha(bundle), grid_sha=sha(run / 'grid_results.json'), winner=winner,
                families={f: {**winners[f], 'grade_a': models[f]['grade_a'],
                              'calibration': models[f]['calibration']} for f in FAMILIES},
                model_fit=sum(counter.values()), model_fit_success=sum(success.values()), fit_stages=counter,
                preprocessing_fits=dict(s_dev_cv=5, s_dev_refit=1, e_dev_cv=5, e_dev_refit=1),
                model_fits_by_family={f: grid_counts[f]*5+2 for f in FAMILIES} | {'E_LR': 6},
                test_labels_read=0, test_features_read=0, test_predictions=0, versions=versions, **FLAGS)
    write_json(run / 'selection_lock.json', lock, exclusive=True)
    print(json.dumps(dict(model_fit=lock['model_fit'], winner=winner, selection_lock_sha=sha(run/'selection_lock.json'))))


def baseline_scores(path, ids):
    with path.open(newline='', encoding='utf-8-sig') as file:
        reader = csv.DictReader(file)
        need(set(reader.fieldnames or ()) == {'episode_id', 'gate_reason', *SCORES}, 'BASELINE_FILE_SCHEMA_DRIFT')
        baseline = indexed(reader)
    need(set(baseline) == set(ids), 'BASELINE_EPISODES_DRIFT')
    validate_scores(baseline.values(), (('raw_S_lr', 'gated_S_lr'), ('raw_S_rf', 'gated_S_rf')))
    return baseline


def audit_rate(rows, event):
    hits = sum(event(row) for row in rows)
    return dict(n=len(rows), hits=int(hits), rate=hits / len(rows) if rows else None)


def assess(rows, score_field, grade_field):
    binary = [r for r in rows if r['unanimous_gold_v1'] in CORE]
    hard_neg = [r for r in binary if r['unanimous_gold_v1'] == NEG]
    large_neg = [r for r in hard_neg if r['adv20_cny'] >= 3e8]
    events = [r for r in rows if r['unanimous_gold_v1'] == EVENT]
    pending = [r for r in rows if r['unanimous_gold_v1'] == PENDING]
    pending_any = [r for r in rows if r['pending_any']]
    high = lambda r: r[score_field] >= S_THRESHOLD
    at_a = lambda r: r[grade_field]
    unanimous = sorted(binary + events, key=lambda r: (-r[score_field], r['episode_id']))
    retrieval = {}
    for k in (20, 50):
        if len(unanimous) < k:
            retrieval[str(k)] = None
        else:
            top = unanimous[:k]
            hits = sum(r['unanimous_gold_v1'] == POS for r in top)
            retrieval[str(k)] = dict(k=k, hits=hits, precision=hits / k,
                                     event_hits=sum(r['unanimous_gold_v1'] == EVENT for r in top))
    return dict(core=metrics(binary, score_field, ks=(20, 50)), unanimous_retrieval=retrieval,
                hard_neg=audit_rate(hard_neg, high), large_hard_neg=audit_rate(large_neg, high),
                hard_neg_v04_either=audit_rate([r for r in hard_neg if 'V04' in (r['chat_v'], r['gem_v'])], high),
                pending_a=audit_rate(pending, at_a), pending_any_a=audit_rate(pending_any, at_a),
                pending_any_gray=audit_rate(pending_any, lambda r: .25 <= r[score_field] <= .65),
                event_s_block=audit_rate(events, lambda r: not high(r)),
                event_s_zero=audit_rate(events, lambda r: r[score_field] == 0.0))


def score_phase(args):
    run = args.run_dir
    lock_path = run / 'selection_lock.json'
    need(lock_path.is_file() and not (run/'score_attempt.json').exists() and not args.predictions.exists(),
         'SCORE_ALREADY_STARTED_OUTPUT_EXISTS_OR_LOCK_MISSING')
    lock = json.loads(lock_path.read_text(encoding='utf-8'))
    need(lock.get('schema') == 'PFT_ACT032_SELECTION_LOCK_V1' and lock['test_labels_read'] == 0
         and lock['test_features_read'] == 0 and lock['test_predictions'] == 0, 'INVALID_SELECTION_LOCK')
    paths = {'features': args.features, 'selection_labels': args.selection_labels, 'code': Path(__file__)}
    need({key: sha(path) for key, path in paths.items()} == lock['hashes'], 'LOCKED_SELECTION_INPUT_DRIFT')
    bundle = run/'weights'/'sv2_research_weights.joblib'
    for path, expected in ((bundle, lock['weights_sha']), (run/'fit_plan.json', lock['fit_plan_sha']),
                           (run/'fit_ledger.jsonl', lock['fit_ledger_sha']), (run/'grid_results.json', lock['grid_sha'])):
        need(sha(path) == expected, 'LOCKED_ARTIFACT_DRIFT')
    plan = json.loads((run/'fit_plan.json').read_text(encoding='utf-8'))
    selection = json.loads((run/'grid_results.json').read_text(encoding='utf-8'))
    need(plan['holdout_hashes'] == lock['holdout_hashes'] and selection['winner'] == lock['winner'],
         'LOCKED_WINNER_OR_HOLDOUT_DIGEST_DRIFT')
    versions = {package: version(package) for package in lock['versions']}
    need(versions == lock['versions'], 'LOCKED_PYTHON_ENVIRONMENT_DRIFT')
    write_json(run / 'score_attempt.json', dict(started_utc=now(), lock_sha=sha(lock_path), model_fit=0), exclusive=True)
    need(sha(args.test_features) == lock['holdout_hashes']['test_features'], 'LOCKED_TEST_FEATURE_INPUT_DRIFT')
    selection_features = read_features(args.features, (DEV, VAL))
    holdout_features = read_features(args.test_features, (TEST,))
    features = pd.concat([selection_features, holdout_features], verify_integrity=True).sort_index()
    need(features.security_id.nunique() == 240, 'CROSS_PERIOD_SECURITY_OVERLAP')
    need(int(features.price_basis.eq(PRICE_BASIS[1]).sum()) == 26, 'BSE_FALLBACK_COUNT_DRIFT')
    labels = read_labels(args.selection_labels, selection_features, (DEV, VAL))
    baseline = baseline_scores(args.baseline, features.index)
    saved = joblib.load(bundle)
    need(saved['schema'] == 'PFT_ACT032_RESEARCH_WEIGHTS_V1' and saved['feature_order'] == FEATURES
         and saved['winner'] == lock['winner'] and set(saved['models']) == set(FAMILIES), 'WEIGHT_SCHEMA_DRIFT')
    dev_ids = sorted(eid for eid, row in labels.items() if row['split_role'] == DEV)
    later_ids = sorted(set(features.index) - set(dev_ids))
    need(set(saved['fold_assignment']) == set(dev_ids), 'LOCKED_DEV_FOLD_ID_DRIFT')
    later_raw = design_matrix(features, later_ids)
    later_s = transform(saved['core_prep'], later_raw)
    later_e = transform(saved['event_prep'], later_raw)
    s_raw, s_ungated = {}, {}
    e_probs = dict(saved['event_oof'])
    with threadpool_limits(limits=1):
        e_probs.update(zip(later_ids, map(float, probabilities(saved['event_model'], later_e)), strict=True))
        for family, components in saved['models'].items():
            need(components['grade_a'] == lock['families'][family]['grade_a']
                 and components['calibration'] == lock['families'][family]['calibration'], 'LOCKED_CALIBRATION_DRIFT')
            later_native = probabilities(components['model'], later_s)
            later_calibrated = calibrate_probabilities(components['calibrator'],
                                                        components['calibration']['method'], later_native)
            front = saved['oof_winners'][family]
            need(set(front) == set(dev_ids), 'LOCKED_OOF_DRIFT')
            s_raw[family] = {**front, **dict(zip(later_ids, map(float, later_native), strict=True))}
            s_ungated[family] = {**front, **dict(zip(later_ids, map(float, later_calibrated), strict=True))}
    # Test labels cannot influence scores: all frozen models have finished prediction here.
    need(sha(args.test_labels) == lock['holdout_hashes']['test_labels'], 'LOCKED_TEST_LABEL_INPUT_DRIFT')
    labels.update(read_labels(args.test_labels, holdout_features, (TEST,)))
    rows = []
    for eid, feature in features.iterrows():
        label = labels[eid]
        role = label['split_role']
        source = baseline[eid]
        gold = label['consensus_status']
        row = dict(episode_id=eid, security_id=feature.security_id, D=feature.D, board=feature.board,
                   adv20_cny=float(feature.adv20_cny), adv20_tier=label['adv20_tier'], split_role=role,
                   oof_fold=saved['fold_assignment'].get(eid, ''), price_basis=feature.price_basis,
                   score_basis='DEV_NATIVE_OOF' if role == DEV else 'DEV_REFIT_2025_CALIBRATION',
                   h0_ok=bool(feature.h0_ok), g1_w_gt_y=bool(feature.g1_w_gt_y),
                   consensus_status=gold, unanimous_gold_v1=gold if gold in (*EXAM, PENDING) else '',
                   consensus_subtype=label['consensus_subtype'], pending_any=pending_audit(label),
                   chat_v=label['chat_v'], gem_v=label['gem_v'], baseline_gate_reason=source['gate_reason'],
                   e_probability=e_probs[eid], e_recall_gate=e_probs[eid] >= EVENT_THRESHOLD,
                   sv2_overall_winner=saved['winner'])
        for score in SCORES:
            row[score] = float(source[score])
            row[score+'_a_proxy'] = row[score] >= A_FLOOR
        for family, components in saved['models'].items():
            prefix = 'sv2_' + family
            val_threshold = components['grade_a']['threshold']
            ungated = s_ungated[family][eid]
            gated = ungated if feature.h0_ok and feature.g1_w_gt_y else 0.0
            # DEV native OOF scores cannot use a later-calibrated probability threshold.
            a_threshold = A_FLOOR if role == DEV else val_threshold
            at_a = a_threshold is not None and gated >= a_threshold
            row[prefix+'_native'] = s_raw[family][eid]
            row[prefix+'_ungated'] = ungated
            row[prefix+'_score'] = gated
            row[prefix+'_a'] = at_a
            row[prefix+'_grade'] = 'UNKNOWN' if not feature.h0_ok else 'A' if at_a else 'B' if gated >= S_THRESHOLD else 'C'
        rows.append(row)
    exam_summary = {}
    cohort = {role: [row for row in rows if row['split_role'] == role] for role in ROLES}
    cohort['FULL_UNANIMOUS_126'] = rows
    for group, subset in cohort.items():
        events = [r for r in subset if r['unanimous_gold_v1'] == EVENT]
        exam_summary[group] = dict(rows_total=len(subset),
                                   unanimous_exam_n=sum(r['unanimous_gold_v1'] in EXAM for r in subset),
                                   counts=dict(Counter(r['consensus_status'] for r in subset)),
                                   bse_archive_fallback_n=sum(r['price_basis'] == PRICE_BASIS[1] for r in subset),
                                   e_event_recall=audit_rate(events, lambda r: r['e_recall_gate']),
                                   e_event_recall_s_zero=audit_rate(
                                       events, lambda r: r['e_recall_gate'] and not (r['h0_ok'] and r['g1_w_gt_y'])),
                                   model_scores={**{c: assess(subset, c, c+'_a_proxy') for c in SCORES},
                                                 **{f: assess(subset, 'sv2_'+f+'_score', 'sv2_'+f+'_a') for f in FAMILIES}})
    with args.predictions.open('x', newline='', encoding='utf-8') as file:
        columns = [c for c in rows[0] if c != 'unanimous_gold_v1']
        writer = csv.DictWriter(file, fieldnames=columns, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)
    summary = dict(schema='PFT_ACT032_REPORT_DATA_V1', model_fit=lock['model_fit'], score_stage_model_fit=0,
                   selection_lock_sha=sha(lock_path), baseline_sha=sha(args.baseline),
                   predictions_sha=sha(args.predictions), predictions_n=len(rows),
                   winner=lock['winner'], eligible_counts=EXPECTED, thresholds=dict(core=S_THRESHOLD, event=EVENT_THRESHOLD,
                   baseline_a_proxy=A_FLOOR, dev_native_a_proxy=A_FLOOR,
                   oot_a={f: lock['families'][f]['grade_a'] for f in FAMILIES}),
                   exams=exam_summary, **FLAGS)
    write_json(run / 'assessment.json', summary, exclusive=True)
    print(json.dumps(dict(model_fit=summary['model_fit'], winner=summary['winner'], prediction_rows=len(rows),
                          assessment_sha=sha(run/'assessment.json'))))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='phase', required=True)
    fit = commands.add_parser('fit')
    score = commands.add_parser('score')
    for command in (fit, score):
        for name in ('features', 'selection-labels', 'run-dir'):
            command.add_argument('--' + name, type=Path, required=True)
    fit.add_argument('--test-features-sha', required=True)
    fit.add_argument('--test-labels-sha', required=True)
    fit.add_argument('--workers', type=int, required=True)
    for name in ('test-features', 'test-labels', 'baseline', 'predictions'):
        score.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    if args.phase == 'fit':
        need(args.workers > 0, 'INVALID_WORKER_BUDGET')
        fit_phase(args)
    else:
        score_phase(args)


if __name__ == '__main__':
    main()
