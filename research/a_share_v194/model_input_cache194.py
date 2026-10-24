"""Read-only saved-model input projection; original encoder/fit kernels unchanged."""
from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
import hashlib
import json
from pathlib import Path

EVIDENCE_ROOT = Path('/Users/lexi/Desktop/学习/因子工厂/research/a_share_v194_full_history_20261024')
ORIGINAL_RUNTIME = {
    'long_runner_code_sha256': '996c4017d3c8ad8d0fccfd34ab0c7b2201f2286680e312076ccc4c033878daa4',
    'adapter_code_sha256': 'b0fbcd3649dfbb6421b1b440d848e6c82719a70473f35e591be1e2500b77bc28',
}
PREDICTIVE_SOURCES = {
    'model194.py': '7481058508836682806b7caa94d20f1ff9831b4ec6b2a409577b53e876dca05e',
    'run194.py': '229448913d8d90ae4b35e19565896f5beea2934029e57ba4bea8b09b650a5265',
    'report194.py': '5a48d641538635f4079b62b38441ce03b317bc0d8d2d43645e5de02a538a67eb',
}


def require(value, message):
    if not value:
        raise ValueError(message)


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def stat(path):
    item = Path(path).stat()
    return dict(inode=item.st_ino, size=item.st_size, mtime_ns=item.st_mtime_ns)


def load(path):
    return json.loads(Path(path).read_text())


def bound_json(ref):
    path = Path(ref['path']).resolve()
    require(sha(path) == ref['sha256'], 'CACHE_BOUND_JSON_DRIFT:' + str(path))
    return path, load(path)


def save_new(path, value):
    import os
    with Path(path).open('x') as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())


def input_fields(model):
    return [*model.TECHNICAL, *model.SOURCES, 'target_date', 'signal_date', 'code',
            'decision_at', 'available_at', 'label', 'label_end_at', 'label_available_at']


class Row(Mapping):
    __slots__ = ('owner', 'index')

    def __init__(self, owner, index):
        self.owner, self.index = owner, index

    def __getitem__(self, key):
        column = self.owner.positions[key]
        return self.owner.vocabularies[column][int(self.owner.array[self.index, column])]

    def __iter__(self):
        return iter(self.owner.fields)

    def __len__(self):
        return len(self.owner.fields)


class CacheRows(Sequence):
    def __init__(self, array, vocabularies, fields):
        require(not array.flags.writeable, 'CACHE_ARRAY_MUST_BE_READONLY')
        self.array = array
        self.vocabularies = tuple(tuple(values) for values in vocabularies)
        self.fields = tuple(fields)
        self.positions = {field: i for i, field in enumerate(fields)}
        require(len(self.positions) == len(fields), 'CACHE_FIELD_DUPLICATE')
        require(array.ndim == 2 and array.shape[1] == len(fields), 'CACHE_SHAPE_DRIFT')

    def __len__(self):
        return self.array.shape[0]

    def __getitem__(self, index):
        if isinstance(index, slice):
            return [self[i] for i in range(*index.indices(len(self)))]
        if index < 0:
            index += len(self)
        if not 0 <= index < len(self):
            raise IndexError(index)
        return Row(self, index)


def encode_rows(rows, model, directory):
    """Persist literal original cell tokens; not a replacement X/Y definition."""
    import numpy as np
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    fields = input_fields(model)
    array_path = directory / 'row_codes.npy'
    array = np.lib.format.open_memmap(array_path, mode='w+', dtype='<u4', shape=(len(rows), len(fields)))
    vocabularies, indices = [[] for _ in fields], [{} for _ in fields]
    by_date = {}
    for i, row in enumerate(rows):
        by_date[row['target_date']] = by_date.get(row['target_date'], 0) + 1
        for j, field in enumerate(fields):
            value = row[field]
            require(type(value) is str, 'CACHE_LITERAL_STRING_REQUIRED:' + field)
            if value not in indices[j]:
                require(len(vocabularies[j]) < 2**32, 'CACHE_VOCAB_OVERFLOW')
                indices[j][value] = len(vocabularies[j])
                vocabularies[j].append(value)
            array[i, j] = indices[j][value]
    array.flush()
    del array
    vocab_path = directory / 'vocabularies.json'
    save_new(vocab_path, vocabularies)
    result = dict(fields=fields, rows=len(rows), dtype='<u4', files={}, row_counts_by_target_date=by_date)
    for name, path in [('codes', array_path), ('vocabularies', vocab_path)]:
        path.chmod(0o444)
        result['files'][name] = dict(path=str(path.resolve()), sha256=sha(path), stat=stat(path))
    return result


def open_projection(projection, *, verify_bytes):
    import numpy as np
    for ref in projection['files'].values():
        require(stat(ref['path']) == ref['stat'], 'CACHE_FILE_STAT_DRIFT')
        if verify_bytes:
            require(sha(ref['path']) == ref['sha256'], 'CACHE_FILE_SHA_DRIFT')
    vocabularies = load(projection['files']['vocabularies']['path'])
    array = np.load(projection['files']['codes']['path'], mmap_mode='r', allow_pickle=False)
    require(array.dtype.str == projection['dtype'] and len(array) == projection['rows'], 'CACHE_ARRAY_SCHEMA_DRIFT')
    require(len(vocabularies) == len(projection['fields']), 'CACHE_VOCAB_SHAPE_DRIFT')
    return CacheRows(array, vocabularies, projection['fields'])


def projection_parity(rows, cached, model, config):
    """Every saved string, X value and converted Y must be identical, in order."""
    require(len(rows) == len(cached), 'CACHE_ROW_COUNT_DRIFT')
    digest = hashlib.sha256()
    for original, restored in zip(rows, cached):
        cells = [original[field] for field in cached.fields]
        require(cells == [restored[field] for field in cached.fields], 'CACHE_CELL_VALUE_DRIFT')
        x = []
        for arm in ('baseline', 'candidate'):
            left, right = model.feature_values(original, config, arm), model.feature_values(restored, config, arm)
            require(left == right, 'CACHE_ENCODER_VALUE_DRIFT')
            x.append(left)
        y = int(float(original['label']))
        require(y == int(float(restored['label'])), 'CACHE_LABEL_VALUE_DRIFT')
        digest.update((json.dumps([cells, x, y], ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n').encode())
    return dict(rows=len(rows), every_literal_cell_equal=True, every_X_Y_value_equal=True,
                ordered_cell_X_Y_sha256=digest.hexdigest(), model_fits=0)


def open_bound_cache(ref, *, verify_bytes):
    path, manifest = bound_json(ref)
    require(manifest.get('schema') == 'V194_READONLY_MODEL_INPUT_CACHE_V1', 'CACHE_MANIFEST_SCHEMA_DRIFT')
    require(manifest.get('parity', {}).get('every_literal_cell_equal') is True
            and manifest['parity'].get('every_X_Y_value_equal') is True, 'CACHE_PARITY_UNVERIFIED')
    return open_projection(manifest['projection'], verify_bytes=verify_bytes), manifest


def pressure_snapshot():
    """Wave-boundary swap counters only; existing used swap is not new activity."""
    import re
    import subprocess
    result = {}
    try:
        raw = subprocess.run(['/usr/bin/vm_stat'], capture_output=True, text=True, timeout=10, check=True).stdout
        for field, name in [('Swapins', 'swapins'), ('Swapouts', 'swapouts')]:
            match = re.search(r'^' + field + r':\s+(\d+)\.', raw, re.MULTILINE)
            require(match is not None, 'SWAP_COUNTER_PARSE_UNAVAILABLE')
            result[name] = int(match.group(1))
        result['status'] = 'OBSERVED'
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        result = dict(status='CANNOT_CONFIRM', reason=str(error))
    return result


def verify_compatibility(config, input_pass, canary_receipt):
    """An explicit independent receipt, never an implicit runtime SHA waiver."""
    _, receipt = bound_json(config['runtime_compatibility'])
    require(receipt.get('schema') == 'V194_RUNTIME_CACHE_COMPATIBILITY_V1'
            and receipt.get('status') == 'PASS_RUNTIME_CACHE_EQUIVALENCE', 'CACHE_COMPATIBILITY_NOT_PASS')
    require(receipt.get('maximum_claim') == 'DIRECTION_ONLY' and receipt.get('fit_count_delta') == 0,
            'CACHE_COMPATIBILITY_SCOPE_DRIFT')
    require(receipt['cache_manifest'] == config['input_cache']
            and receipt['original_canary_runtime'] == config['fit_canary_runtime'], 'CACHE_COMPATIBILITY_REF_DRIFT')
    for key in ('input_manifest_path', 'input_manifest_sha256', 'input_review_path', 'input_review_sha256'):
        expected = input_pass['review_receipt_path' if key == 'input_review_path' else
                              'review_receipt_sha256' if key == 'input_review_sha256' else key]
        require(receipt[key] == expected, 'CACHE_COMPATIBILITY_INPUT_DRIFT:' + key)
    root = Path(__file__).resolve().parent
    new_sources = {name: sha(root / name) for name in ('long_run194.py', 'long_training_adapter.py', 'model_input_cache194.py')}
    require(receipt['old_runtime_sources'] == ORIGINAL_RUNTIME, 'CACHE_COMPATIBILITY_OLD_RUNTIME_DRIFT')
    require(receipt['new_runtime_sources'] == new_sources, 'CACHE_COMPATIBILITY_NEW_RUNTIME_DRIFT')
    require(receipt['predictive_sources'] == PREDICTIVE_SOURCES, 'CACHE_COMPATIBILITY_KERNEL_DRIFT')
    require(all(sha(root / name) == value for name, value in PREDICTIVE_SOURCES.items()), 'PREDICTIVE_SOURCE_DRIFT')
    cache_path, cache = bound_json(config['input_cache'])
    require(cache.get('predictive_sources') == PREDICTIVE_SOURCES, 'CACHE_ENCODER_SOURCE_DRIFT')
    require(cache['input_manifest'] == dict(path=input_pass['input_manifest_path'], sha256=input_pass['input_manifest_sha256'])
            and cache['input_review'] == dict(path=input_pass['review_receipt_path'], sha256=input_pass['review_receipt_sha256']),
            'CACHE_INPUT_BINDING_DRIFT')
    require(cache['parity']['every_literal_cell_equal'] and cache['parity']['every_X_Y_value_equal']
            and cache['parity']['rows'] == cache['projection']['rows']
            and cache['first_fold_replay']['saved_models_exact_prediction_parity'] is True
            and cache['first_fold_replay']['train_keys_exact_parity'] is True
            and cache['first_fold_replay']['refits'] == 0, 'CACHE_PARITY_SCOPE_DRIFT')
    require(receipt['cache_zero_fit_parity'] == cache['parity'], 'CACHE_PARITY_RECEIPT_DRIFT')
    require(cache['original_canary_runtime'] == config['fit_canary_runtime'], 'CACHE_CANARY_BINDING_DRIFT')
    require(canary_receipt['runtime_budget']['fit_canary_identity']['long_runner_code_sha256'] == ORIGINAL_RUNTIME['long_runner_code_sha256']
            and canary_receipt['runtime_budget']['fit_canary_identity']['adapter_code_sha256'] == ORIGINAL_RUNTIME['adapter_code_sha256'],
            'CACHE_ORIGINAL_CANARY_CODE_DRIFT')
    output = Path(config['output_dir']).resolve()
    require(receipt['original_freeze'] == cache['original_freeze'] and
            receipt['original_fold_seal'] == cache['original_fold_seal'], 'CACHE_COMPATIBILITY_SEAL_REF_DRIFT')
    require(Path(cache['original_freeze']['path']).resolve() == output / 'RUN_FREEZE.json'
            and Path(cache['original_fold_seal']['path']).resolve() == output / 'fold_01/FOLD_MANIFEST.json',
            'CACHE_COMPATIBILITY_OUTPUT_DRIFT')
    bound_json(cache['original_freeze'])
    seal_path, seal = bound_json(cache['original_fold_seal'])
    for name, value in seal['files'].items():
        require(Path(name).name == name and sha(seal_path.parent / name) == value, 'CACHE_OLD_FOLD_SEAL_DRIFT')
    return receipt


def compatible_canary_identity(actual, expected, compatibility):
    old = dict(actual)
    new = dict(expected)
    for key, filename in [('long_runner_code_sha256', 'long_run194.py'), ('adapter_code_sha256', 'long_training_adapter.py')]:
        require(old.pop(key) == compatibility['old_runtime_sources'][key], 'CACHE_OLD_IDENTITY_DRIFT')
        require(new.pop(key) == compatibility['new_runtime_sources'][filename], 'CACHE_NEW_IDENTITY_DRIFT')
    require(old == new, 'CACHE_NONRUNTIME_IDENTITY_DRIFT')


def build(config, config_sha256):
    from long_training_adapter import configure_native_thread_budget, verify_independent_input_pass
    configure_native_thread_budget(processes=1, threads_per_process=1)
    import run194 as legacy
    import long_run194 as runner
    require(config['schema'] == 'V194_MODEL_CACHE_BUILD_CONFIG_V1', 'CACHE_BUILD_CONFIG_SCHEMA_DRIFT')
    for path, value in config['frozen_source_bindings'].items():
        require(sha(path) == value, 'CACHE_BUILD_SOURCE_DRIFT:' + path)
    run_config = load(bound_json(config['run_config'])[0])
    input_pass = verify_independent_input_pass(run_config)
    parent_freeze_path, parent_freeze = bound_json(config['original_freeze'])
    seal_path, _ = bound_json(config['original_fold_seal'])
    legacy.reuse_fold(seal_path.parent, parent_freeze['identity'])
    original_validator = legacy.m.validate_manifest
    try:
        legacy.m.validate_manifest = lambda manifest, synthetic=False: runner._validate_bounded_research_manifest(
            manifest, synthetic=synthetic, input_pass=input_pass, model_module=legacy.m)
        manifest, tables, rows, model_config, frozen = runner._prepare_bounded_research_plan(run_config, legacy)
    finally:
        legacy.m.validate_manifest = original_validator
    require(frozen == parent_freeze, 'CACHE_ORIGINAL_PLAN_DRIFT')
    directory = Path(config['output_dir']).resolve()
    require(directory.is_relative_to(EVIDENCE_ROOT.resolve() / 'build') and not directory.exists(), 'CACHE_OUTPUT_NOT_NEW_BUILD')
    projection = encode_rows(rows, legacy.m, directory)
    restored = open_projection(projection, verify_bytes=True)
    parity = projection_parity(rows, restored, legacy.m, model_config)
    split = frozen['splits'][0]
    train, evaluation = legacy.m.split_rows(restored, split)
    require([{key: row[key] for key in ('target_date', 'code', 'label_available_at')} for row in train]
            == load(seal_path.parent / 'train_keys.json'), 'CACHE_FIRST_FOLD_TRAIN_KEYS_DRIFT')
    for arm in ('baseline', 'candidate'):
        model = load(seal_path.parent / (arm + '_model.json'))
        scores = legacy.m.predict(model, evaluation, historical_oof=True)
        require(scores == load(seal_path.parent / (arm + '_predictions.json')), 'CACHE_FIRST_FOLD_SAVED_SCORE_DRIFT')
        require(legacy.m.top50(scores) == load(seal_path.parent / (arm + '_top50.json')), 'CACHE_FIRST_FOLD_TOP50_DRIFT')
    require(all(value == 0 for value in legacy.m.FIT_COUNTS.values()), 'CACHE_BUILD_MUST_NOT_FIT')
    result = dict(schema='V194_READONLY_MODEL_INPUT_CACHE_V1', execution_id=config['execution_id'],
        config_sha256=config_sha256, projection=projection, parity=parity,
        input_manifest=dict(path=input_pass['input_manifest_path'], sha256=input_pass['input_manifest_sha256']),
        input_review=dict(path=input_pass['review_receipt_path'], sha256=input_pass['review_receipt_sha256']),
        original_freeze=config['original_freeze'], original_fold_seal=config['original_fold_seal'],
        original_canary_runtime=config['original_canary_runtime'], predictive_sources=PREDICTIVE_SOURCES,
        first_fold_replay=dict(training_rows=len(train), evaluation_rows=len(evaluation),
                               train_keys_exact_parity=True, saved_models_exact_prediction_parity=True, refits=0),
        builder_source_bindings=config['frozen_source_bindings'],
        status='DERIVED_CACHE_PENDING_INDEPENDENT_REVIEW', maximum_claim='DIRECTION_ONLY',
        model_fits=0, research_only=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)
    save_new(directory / 'MANIFEST.json', result)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    parser.add_argument('--config-sha256', required=True)
    args = parser.parse_args()
    require(sha(args.config) == args.config_sha256, 'CACHE_CONFIG_SHA_DRIFT')
    result = build(load(args.config), args.config_sha256)
    print(json.dumps(dict(status=result['status'], rows=result['projection']['rows'], fits=0)))


if __name__ == '__main__':
    main()
