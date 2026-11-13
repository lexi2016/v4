"""Dated, SHA-pinned history deltas for the original daily label owner."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

from ops.research_storage_retention import fsync_dir

DELTA_SCHEMA = 'v4.a_share.history_checkpoint_delta.v1'
HEAD_SCHEMA = 'v4.a_share.history_checkpoint_head.v1'
_UNCHECKED = object()


class HistoryCheckpointError(ValueError):
    """The history checkpoint could not be verified or committed."""


def _bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
                      allow_nan=False).encode() + b'\n'


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _date(value):
    day = str(value)
    if not re.fullmatch(r'[0-9]{8}', day):
        raise HistoryCheckpointError('HISTORY_CHECKPOINT_DATE_INVALID:' + day)
    return day


def _path(path):
    path = Path(path)
    if not path.is_absolute() or path.resolve() != path:
        raise HistoryCheckpointError('HISTORY_CHECKPOINT_PATH_INVALID:' + str(path))
    return path


def _exists(path):
    return path.exists() or path.is_symlink()


def _stamp(stat):
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def _assert_dependencies(dependencies):
    for name, expected in dependencies.items():
        try:
            current = _stamp(_path(name).stat())
        except OSError as error:
            raise HistoryCheckpointError('HISTORY_CHECKPOINT_DEPENDENCY_MOVED:' + name) from error
        if current != expected:
            raise HistoryCheckpointError('HISTORY_CHECKPOINT_DEPENDENCY_MOVED:' + name)


def _read_bytes(path, expected_sha=None, dependencies=None):
    path = _path(path)
    try:
        with path.open('rb') as stream:
            stamp = _stamp(os.fstat(stream.fileno()))
            raw = stream.read()
            if stamp != _stamp(os.fstat(stream.fileno())) or stamp != _stamp(path.stat()):
                raise HistoryCheckpointError('HISTORY_CHECKPOINT_DEPENDENCY_MOVED:' + str(path))
    except OSError as error:
        raise HistoryCheckpointError('HISTORY_CHECKPOINT_UNREADABLE:' + str(path)) from error
    sha = _sha(raw)
    if expected_sha is not None and expected_sha != sha:
        raise HistoryCheckpointError('HISTORY_CHECKPOINT_SHA_DRIFT:' + str(path))
    if dependencies is not None:
        dependencies[str(path)] = stamp
    return dict(path=str(path), sha256=sha), raw


def _read(path, expected_sha=None, dependencies=None):
    ref, raw = _read_bytes(path, expected_sha, dependencies)
    try:
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise HistoryCheckpointError('HISTORY_CHECKPOINT_OBJECT_REQUIRED:' + str(path))
        return ref, value
    except (UnicodeError, json.JSONDecodeError) as error:
        raise HistoryCheckpointError('HISTORY_CHECKPOINT_UNREADABLE:' + str(path)) from error


def _validate_ref(ref):
    if not isinstance(ref, dict) or set(ref) != {'path', 'sha256'} or not isinstance(ref['path'], str) or not isinstance(ref['sha256'], str) or not re.fullmatch(r'[a-f0-9]{64}', ref['sha256']):
        raise HistoryCheckpointError('HISTORY_CHECKPOINT_REFERENCE_INVALID')


def _read_ref(ref, dependencies=None):
    _validate_ref(ref)
    return _read(ref['path'], ref['sha256'], dependencies)[1]


def _asof(cache):
    try:
        return _date(cache['source_identity']['asof'])
    except (KeyError, TypeError) as error:
        raise HistoryCheckpointError('HISTORY_CHECKPOINT_ASOF_MISSING') from error


def _check_dates(evaluations, day):
    if not isinstance(evaluations, dict) or any(_date(date) > day for date in evaluations):
        raise HistoryCheckpointError('HISTORY_CHECKPOINT_FUTURE_LABEL')


def _apply_chain(ref, value, dependencies):
    """Read each immutable link once, then replay in date order."""
    patches = []
    seen = set()
    newer_day = None
    while True:
        _validate_ref(ref)
        if ref['path'] in seen:
            raise HistoryCheckpointError('HISTORY_CHECKPOINT_REFERENCE_CYCLE')
        seen.add(ref['path'])
        if value is None:
            value = _read_ref(ref, dependencies)
        schema = value.get('storage_schema')
        if schema is None:
            if not isinstance(value.get('evaluations'), dict):
                raise HistoryCheckpointError('HISTORY_CHECKPOINT_EVALUATIONS_REQUIRED')
            day = _asof(value)
            if newer_day is not None and day > newer_day:
                raise HistoryCheckpointError('HISTORY_CHECKPOINT_FUTURE_BASE')
            _check_dates(value['evaluations'], day)
            break
        if schema != DELTA_SCHEMA:
            raise HistoryCheckpointError('HISTORY_CHECKPOINT_SCHEMA_INVALID')
        name = Path(ref['path']).name
        if name != 'delta-' + ref['sha256'] + '.json':
            raise HistoryCheckpointError('HISTORY_CHECKPOINT_DELTA_NAME_CONFLICT')
        day = _date(value['asof'])
        if _asof(value['metadata']) != day or (newer_day is not None and day > newer_day):
            raise HistoryCheckpointError('HISTORY_CHECKPOINT_DELTA_DATE_CONFLICT')
        _check_dates(value['upserts'], day)
        patches.append(value)
        newer_day = day
        ref = value['base']
        if ref is None:
            value = {'evaluations': {}}
            break
        value = None
    evaluations = value['evaluations']
    for patch in reversed(patches):
        meta = patch['metadata']
        if patch['base'] is not None and (meta.get('rule_sha256') != value.get('rule_sha256') or meta.get('rules_signature') != value.get('rules_signature')):
            raise HistoryCheckpointError('HISTORY_CHECKPOINT_DELTA_RULE_CONFLICT')
        removed = patch['removed']
        if not isinstance(removed, list) or any(date not in evaluations or date in patch['upserts'] for date in removed) or len(removed) != len(set(removed)):
            raise HistoryCheckpointError('HISTORY_CHECKPOINT_REMOVAL_CONFLICT')
        for date in removed:
            del evaluations[date]
        evaluations.update(patch['upserts'])
        value = {**meta, 'evaluations': evaluations}
        if patch['derive_coverage_dates'] and value['coverage'].get('evaluated_count') != len(evaluations):
            raise HistoryCheckpointError('HISTORY_CHECKPOINT_COVERAGE_CONFLICT')
    if patches and patches[0]['derive_coverage_dates']:
        value['coverage']['evaluated_dates'] = sorted(map(int, evaluations))
    return value


def _load_checkpoint(ref, value, dependencies=None):
    try:
        return _apply_chain(ref, value, dependencies)
    except (KeyError, TypeError, AttributeError) as error:
        raise HistoryCheckpointError('HISTORY_CHECKPOINT_MALFORMED_CHAIN') from error


def load_checkpoint_ref(ref, *, dependencies=None):
    return _load_checkpoint(ref, None, dependencies)


def _head(path, asof):
    directory = path.parent
    if _exists(directory):
        _path(directory)
    heads = ((p.name[5:-5], p) for p in directory.glob('head-*.json'))
    heads = [(_date(day), p) for day, p in heads]
    latest = max(((day, p) for day, p in heads if asof is None or day <= asof), default=None)
    if latest is None:
        return None, None, None, None
    day, head = latest
    _, value = _read(head)
    if value.get('storage_schema') != HEAD_SCHEMA or value.get('asof') != day:
        raise HistoryCheckpointError('HISTORY_CHECKPOINT_HEAD_CONFLICT:' + str(head))
    ref = value.get('delta')
    _validate_ref(ref)
    if ref['path'] != str(directory / ('delta-' + ref['sha256'] + '.json')):
        raise HistoryCheckpointError('HISTORY_CHECKPOINT_HEAD_REFERENCE_CONFLICT:' + str(head))
    return day, ref, value.get('legacy_stamp'), value.get('legacy_asof')


def _legacy_stamp(path):
    try:
        stamp = _path(path).stat()
    except FileNotFoundError:
        return None
    return [stamp.st_dev, stamp.st_ino, stamp.st_size, stamp.st_mtime_ns]


def _check_legacy_stamp(path, recorded):
    current = _legacy_stamp(path)
    if current is not None and current != recorded:
        raise HistoryCheckpointError('HISTORY_CHECKPOINT_LEGACY_REPLACED:' + str(path))
    return current


def _visible_checkpoint(path, asof):
    day, ref, recorded_stamp, legacy_day = _head(path, asof)
    stamp = _check_legacy_stamp(path, recorded_stamp) if ref is not None else _legacy_stamp(path)
    if stamp is not None and (ref is None or legacy_day is None or legacy_day > day):
        dependencies = {}
        legacy_ref, value = _read(path, dependencies=dependencies)
        verified_day = _asof(value)
        if legacy_day is not None and verified_day != legacy_day:
            raise HistoryCheckpointError('HISTORY_CHECKPOINT_LEGACY_ASOF_CONFLICT')
        legacy_day = verified_day
        if (asof is None or legacy_day <= asof) and (day is None or legacy_day > day):
            return legacy_day, legacy_ref, value, dependencies, stamp, legacy_day
    return day, ref, None, {}, stamp, legacy_day


def read_checkpoint_state(path, *, asof=None, dependencies=None):
    """Return the latest eligible pinned reference and assembled cache."""
    path = _path(path)
    asof = _date(asof) if asof is not None else None
    day, ref, value, reads, _, _ = _visible_checkpoint(path, asof)
    if ref is None:
        return None, None
    if dependencies is not None:
        dependencies.update(reads)
    cache = _load_checkpoint(ref, value, dependencies)
    if _asof(cache) != day:
        raise HistoryCheckpointError('HISTORY_CHECKPOINT_HEAD_ASOF_CONFLICT')
    return ref, cache


def read_checkpoint(path, *, asof=None):
    return read_checkpoint_state(path, asof=asof)[1]


def checkpoint_reference(path, *, asof=None):
    return read_checkpoint_state(path, asof=asof)[0]


def _publish(path, raw):
    fd, pending = tempfile.mkstemp(prefix='.' + path.name + '.', suffix='.pending', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(pending, path)
        fsync_dir(path.parent)
    finally:
        if os.path.exists(pending):
            os.unlink(pending)


def _retain_legacy_seed(base_ref, directory, observe, dependencies):
    # The owner used to replace checkpoint.json on every write. Anchor the old
    # inode without rewriting it so even an older owner replacing it is safe.
    source = Path(base_ref['path'])
    seed = directory / ('seed-' + base_ref['sha256'] + '.json')
    if not _exists(seed):
        if observe is not None:
            observe(seed, 0, False)
        try:
            os.link(_path(source), seed)
        except OSError as error:
            raise HistoryCheckpointError('HISTORY_CHECKPOINT_SEED_LINK_FAILED:' + str(source)) from error
        try:
            _read_bytes(seed, base_ref['sha256'], dependencies)
        except HistoryCheckpointError:
            seed.unlink()
            raise
        fsync_dir(directory)
        if observe is not None:
            observe(seed, 0, True)
    else:
        _read_bytes(seed, base_ref['sha256'], dependencies)
    dependencies.pop(str(source), None)
    return dict(path=str(seed), sha256=base_ref['sha256'])


def write_checkpoint(path, cache, *, base_ref=None, base_cache=None, base_dependencies=None,
                     expected_ref=_UNCHECKED, retain_base=False, observe=None):
    """Publish only changed label dates. Leave every previous ref readable."""
    path = _path(path)
    day = _asof(cache)
    evaluations = cache['evaluations']
    _check_dates(evaluations, day)
    dependencies = dict(base_dependencies or {})
    if base_ref is not None:
        _validate_ref(base_ref)
        if base_cache is None or base_ref['path'] not in dependencies:
            verified_cache = load_checkpoint_ref(base_ref, dependencies=dependencies)
            if base_cache is not None and base_cache != verified_cache:
                raise HistoryCheckpointError('HISTORY_CHECKPOINT_BASE_VALUE_CONFLICT')
            base_cache = verified_cache
        if _asof(base_cache) > day:
            raise HistoryCheckpointError('HISTORY_CHECKPOINT_FUTURE_BASE')
        if (cache.get('rule_sha256'), cache.get('rules_signature')) != (base_cache.get('rule_sha256'), base_cache.get('rules_signature')):
            raise HistoryCheckpointError('HISTORY_CHECKPOINT_BASE_RULE_CONFLICT')
    else:
        base_cache = {'evaluations': {}}
    previous = base_cache['evaluations']
    upserts = {date: value for date, value in evaluations.items() if value != previous.get(date)}
    removed = sorted(previous.keys() - evaluations.keys())
    if not (previous.keys() & evaluations.keys()):
        # No surviving history should depend on a retired source after invalidation.
        base_ref, removed = None, []
        dependencies.clear()
    metadata = {key: value for key, value in cache.items() if key != 'evaluations'}
    coverage = cache.get('coverage', {})
    derive_dates = coverage.get('evaluated_dates') == sorted(map(int, evaluations)) and coverage.get('evaluated_count') == len(evaluations)
    if derive_dates:
        metadata['coverage'] = {key: value for key, value in coverage.items() if key != 'evaluated_dates'}
    directory = path.parent
    descriptor = None
    try:
        directory.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(directory, os.O_RDONLY)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        _, visible, _, _, legacy_stamp, legacy_day = _visible_checkpoint(path, day)
        if retain_base and base_ref is not None and expected_ref is not _UNCHECKED and visible != expected_ref:
            # A successful concurrent publication may be an idempotent retry.
            # The retained immutable name is deterministic; do not create a
            # hardlink to a potentially replaced path in this case.
            base_ref = dict(path=str(directory / ('seed-' + base_ref['sha256'] + '.json')), sha256=base_ref['sha256'])
        elif retain_base and base_ref is not None:
            _assert_dependencies(dependencies)
            base_ref = _retain_legacy_seed(base_ref, directory, observe, dependencies)
        payload = dict(storage_schema=DELTA_SCHEMA, asof=day, base=base_ref, upserts=upserts,
                       removed=removed, metadata=metadata, derive_coverage_dates=derive_dates)
        raw = _bytes(payload)
        sha = _sha(raw)
        delta = directory / ('delta-' + sha + '.json')
        head = directory / ('head-' + day + '.json')
        ref = dict(path=str(delta), sha256=sha)
        if visible == ref:
            load_checkpoint_ref(ref)
            return ref
        if expected_ref is not _UNCHECKED and visible != expected_ref:
            raise HistoryCheckpointError('HISTORY_CHECKPOINT_CAS_MOVED:' + str(path))
        if base_ref == visible and base_ref is not None and not upserts and not removed and cache == base_cache and Path(base_ref['path']).name.startswith('delta-'):
            _assert_dependencies(dependencies)
            return base_ref
        if _exists(delta):
            _read(ref['path'], ref['sha256'], dependencies)
        else:
            if observe is not None:
                observe(delta, len(raw), False)
            _publish(delta, raw)
            dependencies[str(delta)] = _stamp(delta.stat())
            if observe is not None:
                observe(delta, len(raw), True)
        head_value = dict(storage_schema=HEAD_SCHEMA, asof=day, delta=ref)
        if legacy_stamp is not None:
            head_value['legacy_stamp'] = legacy_stamp
            head_value['legacy_asof'] = legacy_day
        _check_legacy_stamp(path, legacy_stamp)
        head_raw = _bytes(head_value)
        if observe is not None:
            observe(head, len(head_raw), False)
        _assert_dependencies(dependencies)
        _check_legacy_stamp(path, legacy_stamp)
        _publish(head, head_raw)
        if observe is not None:
            observe(head, len(head_raw), True)
        return ref
    except OSError as error:
        raise HistoryCheckpointError('HISTORY_CHECKPOINT_WRITE_FAILED:' + str(path)) from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
