"""Registered report-only recovery from the immutable 95-fold V194 cache.

The frozen research code universe is a superset of each day's rankable truth.
No fit entry point is called. The original metric/bootstrap kernel is reused.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

from long_training_adapter import SAFETY_FLAGS
from long_training_adapter import (RunnerHeartbeat, canonical_json_sha256, configure_native_thread_budget,
    load_json, require, runtime_snapshot, sha256_file, verify_independent_input_pass)

ROOT = Path('/Users/lexi/Desktop/学习/因子工厂')
LONG = ROOT / 'research/a_share_v194_long_history_20261024'
REGISTRY = ROOT / 'contracts/EXPERIMENT_REGISTRY.jsonl'
FLAGS = SAFETY_FLAGS


def bound_rows(binding: Mapping[str, Any]) -> Iterable[dict[str, str]]:
    """Consume and hash one CSV stream; no second large-file hashing pass."""
    path = Path(binding['path'])
    before = path.stat()
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        def lines():
            for index, raw in enumerate(stream):
                digest.update(raw)
                yield raw.decode('utf-8-sig' if index == 0 else 'utf-8')
        yield from csv.DictReader(lines())
    after = path.stat()
    require((before.st_ino, before.st_size, before.st_mtime_ns) ==
            (after.st_ino, after.st_size, after.st_mtime_ns), 'REPORT_INPUT_STAT_DRIFT:' + str(path))
    require(digest.hexdigest() == binding['sha256'], 'REPORT_INPUT_SHA_DRIFT:' + str(path))


def exclusive_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())


def exclusive_csv(path: Path, rows: list[dict[str, Any]], fields: list[str] | None = None) -> None:
    require(bool(rows) or fields is not None, 'REPORT_CSV_FIELDS_REQUIRED')
    with path.open('x', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields or list(rows[0]), lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)
        stream.flush()
        os.fsync(stream.fileno())


def collect_truth(rows: Iterable[Mapping[str, Any]], dates: list[str], calendar: Mapping[str, Mapping[str, Any]],
                  universe: set[str], selected: Mapping[str, set[str]]) -> tuple[list[dict[str, Any]], dict[str, set[str]], dict[str, Any]]:
    """Keep all positives and selected negatives: the exact report oracle projection.

    Unselected negatives affect neither Hit@50 nor the paired bootstrap. Their
    actual full-day counts are checked against the bound calendar separately.
    Unknown outcomes are never created, filled, or included in this projection.
    """
    wanted = set(dates)
    counts = Counter()
    positives: dict[str, set[str]] = defaultdict(set)
    found_selected: dict[str, set[str]] = defaultdict(set)
    projected = []
    total = 0
    previous_day = None
    seen: set[str] = set()
    for row in rows:
        total += 1
        day, code = row['target_date'], row['code']
        if day not in wanted:
            continue
        if day != previous_day:
            require(previous_day is None or day > previous_day, 'REPORT_TRUTH_DATE_ORDER_DRIFT')
            previous_day, seen = day, set()
        require(code in universe, 'OOF_TRUTH_CODE_OUTSIDE_FROZEN_UNIVERSE')
        require(code not in seen, 'DUPLICATE_OOF_TRUTH_KEY')
        seen.add(code)
        counts[day] += 1
        label_value = float(row['label'])
        require(label_value in (0.0, 1.0), 'REPORT_TRUTH_LABEL_INVALID')
        label = int(label_value)
        if label:
            positives[day].add(code)
        if code in selected.get(day, set()):
            found_selected[day].add(code)
        if label or code in selected.get(day, set()):
            projected.append({'target_date': day, 'code': code, 'label': label})
    audit = []
    for day in dates:
        expected = int(calendar[day]['truth_rankable_research_rows'])
        denominator = int(calendar[day]['truth_positive_denominator'])
        require(counts[day] == expected, 'OOF_TRUTH_RANKABLE_ROW_COUNT_DRIFT:' + day)
        require(expected <= len(universe), 'OOF_TRUTH_EXCEEDS_RESEARCH_UNIVERSE')
        require(denominator == min(100, expected), 'OOF_TOP100_RANKABLE_DENOMINATOR_DRIFT')
        require(len(positives[day]) == denominator, 'OOF_TOP100_DENOMINATOR_DRIFT')
        require(found_selected[day] == selected.get(day, set()), 'SELECTED_KEY_MISSING_TRUTH')
        audit.append({'target_date': day, 'research_universe_code_count': len(universe),
            'rankable_truth_rows': counts[day], 'unknown_or_unrankable_research_codes': len(universe) - counts[day],
            'truth_positive_denominator': denominator, 'selected_keys_with_truth': len(found_selected[day])})
    return projected, positives, {'all_truth_rows_streamed': total, 'daily': audit,
        'oracle_projection': 'ALL_OOF_POSITIVES_PLUS_SELECTED_NEGATIVES; NO_FILLED_UNKNOWN_LABELS',
        'oracle_projection_rows': len(projected)}


def selection_comparison(dates: list[str], positives: Mapping[str, set[str]], raw: Mapping[str, set[str]],
                         baseline: Mapping[str, set[str]], candidate: Mapping[str, set[str]],
                         calendar: Mapping[str, Mapping[str, Any]], fold_for_date: Mapping[str, str],
                         fold_audit: Mapping[str, Mapping[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    daily, truth_flags = [], []
    for day in dates:
        pool = positives[day]
        sets = {'raw_formula255': raw.get(day, set()), 'technical11_l2': baseline.get(day, set()),
                'v194': candidate.get(day, set())}
        require(len(sets['technical11_l2']) <= 50 and len(sets['v194']) <= 50, 'OOF_MODEL_SELECTION_EXCEEDS_TOP50')
        fold_id = fold_for_date[day]
        row = {'target_date': day, 'fold_id': fold_id}
        for name, values in sets.items():
            row[name + '_selected'] = len(values)
            row[name + '_hits'] = len(values & pool)
        row.update(truth_positive_denominator=int(calendar[day]['truth_positive_denominator']),
            technical11_l2_equals_v194=sets['technical11_l2'] == sets['v194'],
            training_source_state_variation_seen=fold_audit[fold_id]['any_source_state_variation_seen'],
            training_all_source_lanes_unknown=fold_audit[fold_id]['all_source_lanes_unknown'])
        for left_name, right_name in (('raw_formula255', 'technical11_l2'), ('raw_formula255', 'v194'),
                                      ('technical11_l2', 'v194')):
            left, right = sets[left_name], sets[right_name]
            prefix = left_name + '_vs_' + right_name
            for suffix, values in (('common', left & right), ('new', right - left), ('lost', left - right)):
                row[prefix + '_' + suffix] = len(values)
                row[prefix + '_' + suffix + '_hits'] = len(values & pool)
        daily.append(row)
        for code in sorted(pool):
            truth_flags.append({'target_date': day, 'code': code,
                **{name + '_selected': int(code in values) for name, values in sets.items()}})
    return daily, truth_flags


def fold_source_audit(splits: list[dict[str, Any]], coverage: Mapping[str, Mapping[str, Any]],
                      candidate_models: Mapping[str, Mapping[str, Any]], fold_results: Mapping[str, Mapping[str, Any]],
                      model: Any) -> dict[str, Any]:
    """Reuse accepted model-row source counts instead of rescanning training rows."""
    result = {}
    for split in splits:
        identifier = split['id']
        dates = split['train_target_dates']
        cutoff = model.decision(min(split['evaluation_target_dates']))
        require(all(model.instant(coverage[day]['label_available_at']) < cutoff for day in dates),
                'SOURCE_AUDIT_TRAIN_LABEL_CUTOFF_DRIFT')
        training_rows = sum(int(coverage[day]['model_source_state_denominator']) for day in dates)
        require(training_rows == int(fold_results[identifier]['training_rows']), 'FROZEN_TRAIN_ROW_COUNT_DRIFT')
        lanes = {}
        for lane in model.SOURCES:
            counts = {state: sum(int(coverage[day]['model_' + lane + '_' + state + '_rows']) for day in dates)
                      for state in model.STATES}
            lanes[lane] = {'row_counts': counts,
                'target_dates_with_state': {state: sum(int(coverage[day]['model_' + lane + '_' + state + '_rows']) > 0
                                                     for day in dates) for state in model.STATES},
                'observed_state_values': sorted(state for state, count in counts.items() if count)}
        candidate_model = candidate_models[identifier]
        coefficients = {feature: float(coefficient) for feature, coefficient in
                        zip(candidate_model['features'], candidate_model['coef']) if feature.startswith('source_')}
        result[identifier] = {'training_target_dates': dates, 'source_states': lanes,
            'any_source_state_variation_seen': any(len(lanes[lane]['observed_state_values']) > 1 for lane in model.SOURCES),
            'all_source_lanes_unknown': all(lanes[lane]['row_counts']['hit'] == 0 and
                lanes[lane]['row_counts']['confirmed_absent'] == 0 for lane in model.SOURCES),
            'candidate_source_feature_coefficients': coefficients,
            'all_source_feature_coefficients_zero_with_tolerance_1e-12': all(abs(x) <= 1e-12 for x in coefficients.values()),
            'derivation': 'Accepted per-date MODEL candidate source counts; bound fold training dates/count and label cutoff parity.'}
    return result


def validate_contract(path: Path, start_event: str) -> dict[str, Any]:
    contract = load_json(path)
    own = Path(__file__).resolve()
    expected = {str(own): sha256_file(own), str(own.with_name('test_long_report_recovery194.py')):
                sha256_file(own.with_name('test_long_report_recovery194.py'))}
    require(contract['code_sha256'] == expected, 'REPORT_HELPER_CODE_BINDING_DRIFT')
    found = None
    with REGISTRY.open(encoding='utf-8') as stream:
        for line in stream:
            event = json.loads(line)
            if event.get('event_sha256') == start_event:
                found = event
                break
    require(found is not None and found.get('event_type') == 'RUN_STARTED' and
            found.get('execution_id') == contract['execution_id'] and found.get('contract_sha256') == sha256_file(path)
            and found.get('code_sha256') == expected, 'REGISTERED_REPORT_START_BINDING_REQUIRED')
    require(all(found.get(key) == value for key, value in FLAGS.items()), 'REPORT_REGISTRY_SAFETY_DRIFT')
    for binding in contract['source_bindings'].values():
        require(sha256_file(binding['path']) == binding['sha256'], 'RECOVERY_BOUND_SOURCE_DRIFT:' + binding['path'])
    for filename, digest in contract['kernel_code_sha256'].items():
        require(sha256_file(filename) == digest, 'FROZEN_KERNEL_DRIFT:' + filename)
    require(contract['extra_oof_fit_count'] == 0, 'REPORT_ONLY_ZERO_OOF_FIT_REQUIRED')
    require(Path(contract['output_directory']).resolve() == (LONG / 'reports/report_recovery_r1').resolve(),
            'RECOVERY_OUTPUT_SCOPE_DRIFT')
    return contract


def recover(contract_path: Path, start_event: str) -> dict[str, Any]:
    contract = validate_contract(contract_path, start_event)
    configure_native_thread_budget(processes=1, threads_per_process=1, total_thread_budget=12)
    import model194 as model
    import report194 as report
    import long_run194 as legacy
    config = load_json(contract['source_bindings']['run_config']['path'])
    input_pass = verify_independent_input_pass(config)
    manifest = load_json(config['input_manifest'])
    cache = Path(contract['cache_directory'])
    frozen = load_json(cache / 'RUN_FREEZE.json')
    require(frozen['identity']['manifest_sha256'] == input_pass['input_manifest_sha256'], 'CACHE_MANIFEST_IDENTITY_DRIFT')
    require(frozen['bootstrap'] == report.BOOTSTRAP, 'FROZEN_BOOTSTRAP_DRIFT')
    require(len(frozen['splits']) == 95 and len(contract['fold_manifests']) == 95, 'EXPECTED_95_FOLDS_REQUIRED')
    out = Path(contract['output_directory'])
    require(not out.exists(), 'RECOVERY_OUTPUT_ALREADY_EXISTS')
    out.mkdir(parents=True)
    heartbeat = RunnerHeartbeat(out / '_runtime', route_id=contract['route_id'], execution_id=contract['execution_id'],
        heartbeat_seconds=15, runtime_budget={'processes': 1, 'threads_per_process': 1, 'total_thread_budget': 12},
        run_stage='report_recovery')
    fit_before = dict(model.FIT_COUNTS)
    original_fit = model.fit_model
    def forbidden_fit(*args, **kwargs):
        raise ValueError('REPORT_RECOVERY_FIT_FORBIDDEN')
    model.fit_model = forbidden_fit
    try:
        with heartbeat:
            calendar_rows = list(bound_rows(manifest['files']['calendar']))
            calendar = {row['target_date']: row for row in calendar_rows}
            require(len(calendar) == len(calendar_rows), 'DUPLICATE_CALENDAR_DATE')
            coverage_rows = list(bound_rows(manifest['files']['coverage']))
            coverage = {row['target_date']: row for row in coverage_rows}
            codes = list(bound_rows({'path': config['frozen_universe']['code_list_path'],
                'sha256': config['frozen_universe']['code_list_sha256']}))
            universe = {row['code'] for row in codes}
            require(len(universe) == len(codes) == config['frozen_universe']['code_count'], 'FROZEN_CODE_LIST_DRIFT')
            predictions = {'baseline': [], 'candidate': []}
            candidate_models, fold_results = {}, {}
            cache_receipt = []
            for split in frozen['splits']:
                identifier = split['id']
                folder = cache / identifier
                binding_path = folder / 'FOLD_MANIFEST.json'
                require(sha256_file(binding_path) == contract['fold_manifests'][identifier], 'FOLD_MANIFEST_DRIFT:' + identifier)
                binding = load_json(binding_path)
                require(binding['identity'] == frozen['identity'], 'FOLD_FROZEN_IDENTITY_DRIFT:' + identifier)
                used_files = ['split.json', 'FOLD_RESULT.json', 'baseline_model.json', 'candidate_model.json',
                              'baseline_top50.json', 'candidate_top50.json']
                for name in used_files:
                    require(sha256_file(folder / name) == binding['files'][name], 'CACHED_REPORT_FILE_DRIFT:' + identifier + ':' + name)
                require(load_json(folder / 'split.json') == split, 'CACHED_SPLIT_DRIFT')
                fold_result = load_json(folder / 'FOLD_RESULT.json')
                require(fold_result['fit_counts']['real_fit_entered'] == fold_result['fit_counts']['real_fit_returned'] == 2,
                        'CACHED_REAL_FIT_COUNT_DRIFT')
                fold_results[identifier] = fold_result
                candidate_models[identifier] = load_json(folder / 'candidate_model.json')
                for arm in predictions:
                    picks = json.loads((folder / (arm + '_top50.json')).read_text())
                    require({row['target_date'] for row in picks} <= set(split['evaluation_target_dates']), 'FOLD_PICK_DATE_DRIFT')
                    predictions[arm].extend(picks)
                cache_receipt.append({'fold_id': identifier, 'manifest_sha256': contract['fold_manifests'][identifier],
                                     'used_files': {name: binding['files'][name] for name in used_files}})
            dates = [day for split in frozen['splits'] for day in split['evaluation_target_dates']]
            require(len(dates) == len(set(dates)) and not set(dates) & model.EXPOSED, 'FROZEN_OOF_DATES_DRIFT')
            selected_sets: dict[str, dict[str, set[str]]] = {}
            for arm, picks in predictions.items():
                require(model.top50(picks) == picks, 'CACHED_TOP50_ORDER_OR_RANK_DRIFT:' + arm)
                groups: dict[str, set[str]] = defaultdict(set)
                for row in picks:
                    require(row['code'] in universe, 'PICK_CODE_OUTSIDE_FROZEN_POOL')
                    groups[row['target_date']].add(row['code'])
                selected_sets[arm] = groups
            selected_union = {day: selected_sets['baseline'].get(day, set()) | selected_sets['candidate'].get(day, set()) for day in dates}
            projected_truth, positives, truth_audit = collect_truth(bound_rows(manifest['files']['truth']),
                dates, calendar, universe, selected_union)
            require(truth_audit['all_truth_rows_streamed'] == manifest['truth_rows'], 'TRUTH_FILE_ROW_COUNT_DRIFT')
            heartbeat.checkpoint('CACHED_FOLDS_AND_RANKABLE_TRUTH_BOUND', cache / 'RUN_FREEZE.json', dict(model.FIT_COUNTS))
            result = report.evaluate(dates, predictions['baseline'], predictions['candidate'], projected_truth, calendar_rows)
            raw: dict[str, set[str]] = defaultdict(set)
            oof_date_set = set(dates)
            for row in bound_rows(manifest['files']['raw_formula_natural']):
                day, code = row['target_date'], row['code']
                if day not in oof_date_set:
                    continue
                require(code in universe and int(float(row['tech_192'])) == 1, 'RAW_FORMULA_BINDING_DRIFT')
                require(code not in raw[day], 'DUPLICATE_RAW_FORMULA_KEY')
                raw[day].add(code)
            audit = fold_source_audit(frozen['splits'], coverage, candidate_models, fold_results, model)
            fold_for_date = {day: split['id'] for split in frozen['splits'] for day in split['evaluation_target_dates']}
            daily, top100 = selection_comparison(dates, positives, raw, selected_sets['baseline'], selected_sets['candidate'],
                                                 calendar, fold_for_date, audit)
            oracle_daily = {row['target_date']: row for row in result['daily']}
            for row in daily:
                oracle = oracle_daily[row['target_date']]
                require((row['technical11_l2_hits'], row['v194_hits'], row['technical11_l2_vs_v194_new_hits'],
                    row['technical11_l2_vs_v194_lost_hits']) == (oracle['baseline_hits'], oracle['candidate_hits'],
                    oracle['new_hits'], oracle['lost_hits']), 'DAILY_ORACLE_PARITY_FAIL')
            daily_all = legacy._daily_model_report_rows(oof_daily=daily, coverage_rows=coverage_rows, calendar_rows=calendar_rows)
            summaries = legacy._selection_totals(daily)
            source_by_year = legacy._source_coverage_by_year(coverage_rows)
            fit_counts = {key: model.FIT_COUNTS[key] - fit_before[key] for key in fit_before}
            require(all(value == 0 for value in fit_counts.values()), 'REPORT_RECOVERY_FIT_COUNT_NOT_ZERO')
            result.update(fit_counts=fit_counts, cached_historical_real_fit_count=190,
                recovery_execution_id=contract['execution_id'], recovery_start_event_sha256=start_event,
                original_failed_execution_id=contract['original_failed_execution_id'], **FLAGS)
            exclusive_csv(out / 'OOF_DAILY_SELECTION_COMPARISON.csv', daily)
            exclusive_csv(out / 'OOF_TOP100_WITH_SELECTIONS.csv', top100)
            exclusive_csv(out / 'LONG_DAILY_MODEL_COUNTS.csv', daily_all)
            exclusive_json(out / 'LONG_FOLD_SOURCE_STATE_AUDIT.json', audit)
            exclusive_json(out / 'LONG_SOURCE_COVERAGE_BY_YEAR.json', source_by_year)
            exclusive_json(out / 'LONG_SELECTION_AUDIT.json', {'summary': summaries, 'daily': daily,
                'formula_route': 'FORMULA255_OFFLINE_RESEARCH_ONLY', 'raw_natural_membership_is_untruncated': True, **FLAGS})
            exclusive_json(out / 'RANKABLE_TRUTH_REPORT_BINDING.json', truth_audit)
            exclusive_json(out / 'CACHED_FOLDS_USED.json', {'cache_directory': str(cache), 'folds': cache_receipt,
                'new_fit_counts': fit_counts, 'historical_real_fit_count': 190, **FLAGS})
            for arm, picks in predictions.items():
                exclusive_json(out / (arm + '_OOF_TOP50.json'), picks)
            # The exact frozen plan and recovered OOF result let the unchanged
            # R3 refit runner consume this new output directory later.
            with (out / 'RUN_FREEZE.json').open('xb') as stream:
                stream.write((cache / 'RUN_FREEZE.json').read_bytes())
                stream.flush()
                os.fsync(stream.fileno())
            exclusive_json(out / 'OOF_RESULT.json', result)
            report.write_report(out, result, {'eligible_dates': frozen['eligible_target_dates'],
                'excluded_exposed_dates': frozen['excluded_target_dates'], 'failed_folds': [],
                'reused_folds': [split['id'] for split in frozen['splits']],
                'empty_candidate_dates': [day for day in dates if int(coverage[day]['candidate_rows']) == 0],
                'original_failed_execution_id': contract['original_failed_execution_id'],
                'recovery_execution_id': contract['execution_id'], 'daily_counts': str(out / 'LONG_DAILY_MODEL_COUNTS.csv')})
            files = {p.name: {'path': str(p), 'sha256': sha256_file(p)} for p in sorted(out.iterdir()) if p.is_file()}
            receipt = {'status': 'REPORT_RECOVERY_COMPLETE_PENDING_INDEPENDENT_REVIEW', 'files': files,
                'execution_id': contract['execution_id'], 'start_event_sha256': start_event,
                'contract': {'path': str(contract_path), 'sha256': sha256_file(contract_path)},
                'kernel_code_sha256': contract['kernel_code_sha256'], 'recovery_code_sha256': contract['code_sha256'],
                'original_failed_execution_id': contract['original_failed_execution_id'],
                'cached_folds': 95, 'cached_historical_real_fit_count': 190, 'extra_oof_fit_counts': fit_counts,
                'summary': summaries, 'metrics_status': result['status'], 'oof_dates': len(dates),
                'maximum_claim': 'DIRECTION_ONLY', 'runtime': runtime_snapshot(), **FLAGS}
            exclusive_json(out / 'AUTHOR_RECEIPT.json', receipt)
            heartbeat.checkpoint('REPORT_RECOVERY_COMPLETE', out / 'AUTHOR_RECEIPT.json', fit_counts)
            return {'status': receipt['status'], 'receipt_path': str(out / 'AUTHOR_RECEIPT.json'),
                'receipt_sha256': sha256_file(out / 'AUTHOR_RECEIPT.json'), 'summary': summaries,
                'metrics_status': result['status'], 'extra_oof_fit_counts': fit_counts, **FLAGS}
    finally:
        model.fit_model = original_fit


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--contract', required=True, type=Path)
    parser.add_argument('--start-event', required=True)
    args = parser.parse_args()
    print(json.dumps(recover(args.contract, args.start_event), ensure_ascii=False, sort_keys=True), flush=True)
