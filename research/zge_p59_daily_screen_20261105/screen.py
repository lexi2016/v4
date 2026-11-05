"""Fixed-SHA Phase59 D05 inference consumer. No feature production or fitting."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import traceback

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = Path('/Users/lexi/Desktop/学习/agents调试/v4_model_daily_screen_20261105')
TRAIN = Path('/Users/lexi/Desktop/学习/agents调试/Z哥方法论/phase59_mac_continue_20261105')
MODEL = TRAIN / 'local_increment_v1/model_t5_local_increment.pkl'
MODEL_SHA = 'ba3553516af05dec467299579dccc7d8c418882dbd4cc89433b4722c2df9dd43'
ORDER = TRAIN / 'cpu_original/models/V193_ALL_A_V3_1/feature_order_v3_1.json'
ORDER_SHA = '6d4e8f60a7854f1895976e1d462975d4645fc0dc01d2b92661d8111b28172325'
RUNTIME_SHA = 'bdc2e24c46a70322b391de8d3aeda9a1bdc26a1d791b36c61ec0106d01013256'
GENERATION = '63986092da44625a69d34f5f98a300c8ba685ea023dbaa007639207caa3ea109'
ASOF = 20261105
FLAGS = dict(RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def require(ok, message):
    if not ok:
        raise ValueError(message)


def dump(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def pinned_runtime():
    path = HERE.parent / 'zge_phase59_mac_continue_20261105/runtime.py'
    require(sha(path) == RUNTIME_SHA, 'RUNTIME_SHA_CONFLICT')
    spec = importlib.util.spec_from_file_location('daily_p59_runtime', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_ref(ref):
    path = Path(ref['path'])
    require(path.is_absolute(), 'ABSOLUTE_INPUT_PATH_REQUIRED')
    require(sha(path) == ref['sha256'], 'INPUT_SHA_CONFLICT:' + str(path))
    return path


def masked_features(features):
    groups = [[c for c in features if c.startswith(p)] for p in ('p54_repr_', 'behav_', 'p53_')]
    require([len(x) for x in groups] == [11, 6, 7], 'FROZEN_MASK_SET_CONFLICT')
    return set(sum(groups, []))


def validate_frames(features, coverage, order):
    """Check all keys/masks mechanically; accept semantic certification upstream."""
    mask = masked_features(order)
    for table, name in ((features, 'FEATURES'), (coverage, 'COVERAGE')):
        require({'ts_code', 'signal_date'} <= set(table), name + '_KEYS_ABSENT')
        require(not table.ts_code.duplicated().any(), name + '_DUPLICATE_CODE')
        require(table.ts_code.astype('string').str.fullmatch(r'\d{6}\.(SH|SZ|BJ)').fillna(False).all(), name + '_NON_A_CODE')
        require(table.signal_date.eq(ASOF).all(), name + '_DATE_CONFLICT')
    require(len(coverage) == 5808, 'EXPECTED_5808_SOURCE_COVERAGE')
    require({'input_status', 'gap_reason'} <= set(coverage), 'COVERAGE_STATUS_ABSENT')
    require(coverage.input_status.isin(['BOUND', 'UNAVAILABLE', 'NO_D05_BAR']).all(), 'COVERAGE_STATUS_CONFLICT')
    unavailable = coverage.input_status.ne('BOUND')
    require(coverage.loc[unavailable, 'gap_reason'].fillna('').str.len().gt(0).all(), 'UNAVAILABLE_WITHOUT_REASON')
    require(set(features.ts_code) <= set(coverage.ts_code), 'FEATURE_OUTSIDE_ACCEPTED_UNIVERSE')
    require([c for c in features if c in order] == order, 'FEATURE_COLUMN_ORDER_CONFLICT')
    require({'target_domain', 'domain_reason'} <= set(features), 'DOMAIN_EVIDENCE_ABSENT')
    # Text/integers cannot accidentally pass the TRUE gate.
    require(all(pd.isna(v) or isinstance(v, (bool, np.bool_)) for v in features.target_domain), 'DOMAIN_MUST_BE_BOOLEAN_OR_NULL')
    require(features.domain_reason.fillna('').astype(str).str.len().gt(0).all(), 'DOMAIN_REASON_ABSENT')
    require(features[list(mask)].isna().all().all(), 'FROZEN_MASK_CONFLICT')
    bound_codes = set(coverage.loc[~unavailable, 'ts_code'])
    require(bound_codes <= set(features.ts_code), 'BOUND_CODE_WITHOUT_FEATURE_ROW')
    bound = features.loc[features.ts_code.isin(bound_codes)].copy()
    unmasked = [c for c in order if c not in mask]
    require(all(pd.api.types.is_numeric_dtype(bound[c]) for c in unmasked), 'NON_NUMERIC_FEATURE')
    require(np.isfinite(bound[unmasked].to_numpy(dtype=float)).all(), 'UNBOUND_UNMASKED_VALUE_ON_BOUND_ROW')
    return bound


def validate_binding(binding, order):
    require(binding['signal_date'] == ASOF and binding['source_generation'] == GENERATION, 'SOURCE_DATE_OR_GENERATION_CONFLICT')
    require(binding['model_sha256'] == MODEL_SHA and binding['feature_order_sha256'] == ORDER_SHA, 'MODEL_OR_ORDER_BINDING_CONFLICT')
    require(binding['top_n'] == 10 and binding['tie_break'] == 'ts_code ascending', 'RANKING_POLICY_CONFLICT')
    require(binding['flags'] == FLAGS, 'RESEARCH_FLAGS_CONFLICT')
    require(binding['controller_accepted'] is True, 'CONTROLLER_ACCEPTANCE_REQUIRED')
    require(bool(binding['domain_definition']) and bool(binding['upstream_execution_id']), 'UPSTREAM_DOMAIN_IDENTITY_ABSENT')
    # This is an explicit controller binding to an independently accepted owner
    # receipt, not a reinterpretation of an upstream verdict string.
    acceptance = read_ref(binding['upstream_acceptance'])
    require(acceptance.suffix == '.json', 'UPSTREAM_ACCEPTANCE_JSON_REQUIRED')
    json.loads(acceptance.read_text())
    statuses = binding['feature_binding']
    mask = masked_features(order)
    require(set(statuses) == set(order), 'FEATURE_BINDING_SET_CONFLICT')
    for field in order:
        expected = 'TRAINING_FROZEN_UNKNOWN' if field in mask else 'SOURCE_BOUND'
        require(statuses[field] == expected, 'FEATURE_BINDING_STATUS_CONFLICT:' + field)
    features = pd.read_parquet(read_ref(binding['features']))
    coverage = pd.read_parquet(read_ref(binding['coverage']))
    features = map_columns(features, binding.get('feature_column_map'))
    coverage = map_columns(coverage, binding.get('coverage_column_map'))
    if binding.get('domain_value_map') is not None:
        value_map = binding['domain_value_map']
        require(all(v is None or isinstance(v, bool) for v in value_map.values()), 'DOMAIN_VALUE_MAP_TYPE_CONFLICT')
        require(features.target_domain.dropna().map(lambda v: str(v) in value_map).all(), 'UNMAPPED_DOMAIN_VALUE')
        features['target_domain'] = features.target_domain.map(lambda v: None if pd.isna(v) else value_map[str(v)])
    bound = validate_frames(features, coverage, order)
    return features, coverage, bound


def map_columns(frame, mapping):
    """Explicit controller-approved rename/projection only; never derive features."""
    if mapping is None:
        return frame
    require(len(set(mapping.values())) == len(mapping), 'AMBIGUOUS_COLUMN_MAP')
    require(set(mapping.values()) <= set(frame), 'COLUMN_MAP_SOURCE_ABSENT')
    return frame[list(mapping.values())].rename(columns={v: k for k, v in mapping.items()})


def predict_and_rank(model, bound, coverage):
    prediction = np.asarray(model.predict(bound), dtype=float) if len(bound) else np.array([], dtype=float)
    require(prediction.shape == (len(bound),) and np.isfinite(prediction).all(), 'INVALID_MODEL_PREDICTION')
    scored = bound[['ts_code', 'target_domain', 'domain_reason']].copy()
    scored['score_uncalibrated'] = prediction
    scored = scored.sort_values(['score_uncalibrated', 'ts_code'], ascending=[False, True], kind='stable')
    scored['score_rank'] = np.arange(1, len(scored) + 1)
    eligible = scored.target_domain.eq(True).fillna(False)
    scored['observation_rank'] = pd.Series(pd.NA, index=scored.index, dtype='Int64')
    scored.loc[eligible, 'observation_rank'] = np.arange(1, int(eligible.sum()) + 1)
    scored['primary_observation'] = scored.observation_rank.le(10).fillna(False)
    result = coverage.merge(scored, on='ts_code', how='left', validate='one_to_one')
    # Canonical nullable dtypes preserve UNKNOWN exactly through Parquet.
    result['target_domain'] = result.target_domain.astype('boolean')
    result['domain_reason'] = result.domain_reason.astype('string')
    result['primary_observation'] = result.primary_observation.fillna(False).astype(bool)
    result['selection_status'] = np.select(
        [result.input_status.ne('BOUND'), result.target_domain.isna(), result.target_domain.eq(False).fillna(False), result.primary_observation],
        ['INPUT_UNAVAILABLE', 'DOMAIN_UNKNOWN', 'OUTSIDE_TARGET_DOMAIN', 'PRIMARY_OBSERVATION'], default='TARGET_DOMAIN_RANKED')
    for col in ('d_plus_1_return_pct', 't5_return_pct'):
        result[col] = np.nan
    result['score_semantics'] = 'UNCALIBRATED_DIRECTION_ONLY_NOT_PROBABILITY'
    result['source_generation'] = GENERATION
    result['model_sha256'] = MODEL_SHA
    return result.sort_values(['score_rank', 'ts_code'], na_position='last', kind='stable').reset_index(drop=True)


def save_and_verify(result, run):
    """Read saved scores/ranks; do not rerun inference to check serialization."""
    ranked_path = run / 'ALL_CODES_RANKED.parquet'
    result.to_parquet(ranked_path, index=False)
    result.to_csv(run / 'ALL_CODES_RANKED.csv', index=False, float_format='%.17g')
    top = result.loc[result.primary_observation].sort_values('observation_rank')
    top.to_csv(run / 'PRIMARY_OBSERVATIONS.csv', index=False, float_format='%.17g')
    restored = pd.read_parquet(ranked_path)
    pd.testing.assert_frame_equal(result, restored)
    csv_top = pd.read_csv(run / 'PRIMARY_OBSERVATIONS.csv', float_precision='round_trip')
    require(csv_top.ts_code.tolist() == top.ts_code.tolist(), 'SAVED_TOP10_IDENTITY_CONFLICT')
    require(csv_top.observation_rank.tolist() == top.observation_rank.tolist(), 'SAVED_TOP10_RANK_CONFLICT')
    all_csv = pd.read_csv(run / 'ALL_CODES_RANKED.csv', float_precision='round_trip')
    require(all_csv.ts_code.tolist() == result.ts_code.tolist(), 'SAVED_FULL_RANKING_CONFLICT')
    require(np.allclose(all_csv.score_uncalibrated.to_numpy(float), result.score_uncalibrated.to_numpy(float), rtol=1e-14, atol=0, equal_nan=True), 'SAVED_SCORE_CONFLICT')
    return top


def add_feature_identity(result, features, binding, order):
    mask = masked_features(order)
    unmasked = [c for c in order if c not in mask]
    meta = features[['ts_code']].copy()
    meta['feature_input_row'] = np.arange(len(features))
    observed = features[unmasked].apply(pd.to_numeric, errors='coerce')
    known = np.isfinite(observed.to_numpy(dtype=float))
    meta['observed_unmasked_feature_count'] = known.sum(axis=1)
    meta['missing_unmasked_features'] = [json.dumps([field for field, ok in zip(unmasked, row) if not ok]) for row in known]
    meta['frozen_unknown_feature_count'] = len(mask)
    result = result.merge(meta, on='ts_code', how='left', validate='one_to_one', sort=False)
    for col in ('feature_input_row', 'observed_unmasked_feature_count', 'frozen_unknown_feature_count'):
        result[col] = result[col].astype('Int64')
    result['feature_row_present'] = result.feature_input_row.notna()
    result['missing_unmasked_features'] = result.missing_unmasked_features.astype('string')
    result['feature_source_path'] = binding['features']['path']
    result['feature_source_sha256'] = binding['features']['sha256']
    result['coverage_source_sha256'] = binding['coverage']['sha256']
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--binding', type=Path, required=True)
    p.add_argument('--binding-sha256', required=True)
    p.add_argument('--execution-id', required=True)
    args = p.parse_args()
    require(args.execution_id.startswith('ZGE_P59_D05_') and args.execution_id.replace('_', '').isalnum(), 'BAD_EXECUTION_ID')
    require(sha(args.binding) == args.binding_sha256, 'CONTROLLER_BINDING_SHA_CONFLICT')
    require(sha(ORDER) == ORDER_SHA and sha(MODEL) == MODEL_SHA, 'PINNED_ARTIFACT_SHA_CONFLICT')
    order = json.loads(ORDER.read_text())
    require(len(order) == len(set(order)) == 87, 'FEATURE_ORDER_LENGTH_CONFLICT')
    binding = json.loads(args.binding.read_text())
    features, coverage, bound = validate_binding(binding, order)
    run = OUT / args.execution_id
    run.mkdir(parents=True, exist_ok=False)
    contract = {'route_id': 'ZGE_PHASE59_DAILY_SCREEN_20261105', 'baseline_id': MODEL_SHA,
                'one_variable': 'Accepted D05 owner projection; fixed model inference only',
                'input': {'dataset_path': binding['features']['path'], 'dataset_sha256': binding['features']['sha256'],
                          'base_model_sha256': MODEL_SHA, 'archive_sha256': binding['upstream_acceptance']['sha256']},
                'signal_date_range': '20261105', 'target_date_range': 'UNMATURED_D_PLUS_1_AND_T5',
                'truth_access': 'NO_FUTURE_OUTCOMES_ACCESSED', 'binding_path': str(args.binding.resolve()),
                'binding_sha256': args.binding_sha256, 'code_sha256': sha(__file__),
                'source_sha256': {name: sha(HERE / name) for name in ('screen.py', 'registry.py')},
                'runtime_sha256': RUNTIME_SHA, 'feature_order_sha256': ORDER_SHA, 'flags': FLAGS}
    dump(run / 'EXECUTION_CONTRACT.json', contract)
    import registry
    try:
        registry.append(args.execution_id, 'RUN_STARTED', run / 'EXECUTION_CONTRACT.json', Path(__file__), run / 'EXECUTION_CONTRACT.json', run)
    except Exception:
        dump(run / 'REGISTRY_START_ERROR.json', {'traceback': traceback.format_exc(), 'retry': 'NOT_ATTEMPTED', 'flags': FLAGS})
        raise
    try:
        runtime = pinned_runtime()
        runtime.install_compat()
        model = runtime.load(MODEL, MODEL_SHA)
        require(list(model.prep_.feat_cols) == order, 'MODEL_PREPROCESSOR_ORDER_CONFLICT')
        from threadpoolctl import threadpool_limits
        # At most 5808 inference rows; measured 18 cores/84% free memory.
        # BLAS cap leaves front-end capacity without spawning worker processes.
        threads = min(8, max(1, (os.cpu_count() or 1) - 2))
        with threadpool_limits(limits=threads):
            result = predict_and_rank(model, bound, coverage)
        result['posterior_status'] = result.ts_code.map(lambda c: 'SAVED_STOCK_POSTERIOR' if c in model.stock_posteriors_ else 'ORIGINAL_GLOBAL_PRIOR_FALLBACK')
        result = add_feature_identity(result, features, binding, order)
        top = save_and_verify(result, run)
        receipt = {'status': 'D05_INFERENCE_COMPLETE_QA_PENDING', 'python': sys.executable,
                   'completed_utc': datetime.now(timezone.utc).isoformat(), 'model_sha256': MODEL_SHA,
                   'feature_order_sha256': ORDER_SHA, 'binding_sha256': args.binding_sha256,
                   'coverage_rows': len(coverage), 'projection_rows': len(features), 'scored_rows': len(bound), 'blas_threads': threads,
                   'target_domain_true': int(bound.target_domain.eq(True).sum()), 'primary_count': len(top),
                   'selection_status_counts': {str(k): int(v) for k, v in result.selection_status.value_counts().items()},
                   'output_sha256': {f.name: sha(f) for f in run.iterdir() if f.suffix in ('.parquet', '.csv')},
                   'saved_readback': 'PASS_WITHOUT_SECOND_INFERENCE', 'source_generation': GENERATION,
                   'feature_masks': 'P54_11_BEHAV_6_P53_7_RETAINED_NULL', 'model_acceptance': 'DIRECTION_ONLY; STRATEGY_ACCEPTANCE_NOT_GRANTED',
                   'd_plus_1_outcome': None, 't5_outcome': None, 'flags': FLAGS}
        dump(run / 'RUN_RECEIPT.json', receipt)
    except Exception:
        dump(run / 'FAILURE.json', {'status': 'FAIL', 'traceback': traceback.format_exc(), 'flags': FLAGS})
        try:
            registry.append(args.execution_id, 'TERMINAL', run / 'EXECUTION_CONTRACT.json', Path(__file__), run / 'FAILURE.json', run, 'CANNOT_CONFIRM')
        except Exception:
            dump(run / 'REGISTRY_TERMINAL_ERROR.json', {'traceback': traceback.format_exc(), 'retry': 'NOT_ATTEMPTED', 'flags': FLAGS})
        raise
    try:
        registry.append(args.execution_id, 'TERMINAL', run / 'EXECUTION_CONTRACT.json', Path(__file__), run / 'RUN_RECEIPT.json', run, 'DIRECTION_ONLY')
    except Exception:
        dump(run / 'REGISTRY_TERMINAL_ERROR.json', {'traceback': traceback.format_exc(), 'retry': 'NOT_ATTEMPTED', 'flags': FLAGS})
        raise
    print(json.dumps(receipt, ensure_ascii=False))


if __name__ == '__main__':
    main()
