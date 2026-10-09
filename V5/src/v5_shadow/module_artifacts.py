"""Immutable per-module output snapshots and atomic, compare-and-swap activation.

Only V5-marked roots are admitted. Old generations/objects are never deleted.
This publishes already-built records, and never runs collectors or algorithms.
"""
from contextlib import contextmanager
import fcntl
import hashlib
import os
import re
import stat
from uuid import uuid4

from .contracts import sha
from .digests import canonical_bytes
from .module_api import (_config, _generation_head, _load_generation, _read_at,
                         _read_object, _parse_record, _validate_record, response_key)

MAX_GENERATION_BYTES = 64 * 1024 * 1024


@contextmanager
def _locked(config):
    config, root = _config(config)
    lock = None
    try:
        lock = os.open('.publication.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                       0o600, dir_fd=root)
        if not stat.S_ISREG(os.fstat(lock).st_mode):
            raise ValueError('MODULE_PUBLICATION_LOCK')
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield config, root
    finally:
        if lock is not None:
            os.close(lock)
        os.close(root)


def _directory(root, name):
    try:
        os.mkdir(name, mode=0o700, dir_fd=root)
        os.fsync(root)
    except FileExistsError:
        pass
    return os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root)


def _write_once(directory, name, raw):
    temporary = '.' + name + '.' + uuid4().hex + '.tmp'
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                 0o600, dir_fd=directory)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, name, src_dir_fd=directory, dst_dir_fd=directory,
                    follow_symlinks=False)
        except FileExistsError:
            if _read_at(directory, None, name) != raw:
                raise ValueError('MODULE_IMMUTABLE_COLLISION')
        os.fsync(directory)
    finally:
        try:
            os.unlink(temporary, dir_fd=directory)
            os.fsync(directory)
        except FileNotFoundError:
            pass


def _write_immutable(root, folder, digest, raw):
    directory = _directory(root, folder)
    try:
        _write_once(directory, digest + '.json', raw)
    finally:
        os.close(directory)


def _validate_ref(config, key, record):
    _validate_record(config, record, record['path'], record['query'])
    if response_key(config['module_id'], record['path'], record['query']) != key:
        raise ValueError('MODULE_RESPONSE_KEY')


def _load_records(config, root, generation):
    refs = {}
    total = 0
    if generation is not None:
        refs = dict(_load_generation(root, config, generation)['records'])
        for key, digest in refs.items():
            record, raw = _read_object(root, digest, config)
            _validate_ref(config, key, record)
            total += len(raw)
            if total > MAX_GENERATION_BYTES:
                raise ValueError('MODULE_GENERATION_SIZE')
        return refs
    try:
        directory = os.open('responses', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root)
    except FileNotFoundError:
        return refs
    try:
        names = os.listdir(directory)
    finally:
        os.close(directory)
    if len(names) > 10000:
        raise ValueError('MODULE_GENERATION_RECORDS')
    for name in sorted(names):
        if not re.fullmatch(r'[0-9a-f]{64}\.json', name):
            raise ValueError('MODULE_LEGACY_RECORD_NAME')
        raw = _read_at(root, 'responses', name)
        total += len(raw)
        if total > MAX_GENERATION_BYTES:
            raise ValueError('MODULE_GENERATION_SIZE')
        record = _parse_record(raw, config)
        _validate_ref(config, name[:-5], record)
        digest = hashlib.sha256(raw).hexdigest()
        _write_immutable(root, 'objects', digest, raw)
        refs[name[:-5]] = digest
    return refs


def _activate(config, root, generation):
    # Verify every referenced object before exposing the generation.
    _load_records(config, root, generation)
    value = dict(schema_version='v5.module_active.v1', module_id=config['module_id'],
                 release_id=config['release_id'], generation_sha256=generation)
    # Sticky migration state makes an absent active pointer fail closed. If
    # the first activation is interrupted, explicit activate_generation with
    # the known complete generation can repair it; publish cannot guess.
    mode = canonical_bytes(dict(schema_version='v5.generation_mode.v1',
                                module_id=config['module_id'], release_id=config['release_id']))
    _write_once(root, '.v5-generation-mode', mode)
    temporary = '.active.' + uuid4().hex + '.tmp'
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=root)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(canonical_bytes(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, 'active.json', src_dir_fd=root, dst_dir_fd=root)
        os.fsync(root)
    finally:
        try:
            os.unlink(temporary, dir_fd=root)
        except FileNotFoundError:
            pass
    return value


def _compare(root, config, expected, *, explicit_recovery=False):
    if expected is not None:
        sha(expected)
    try:
        current = _generation_head(root, config, publication_locked=True)
    except ValueError as error:
        if not (explicit_recovery and expected is None and str(error) == 'MODULE_ACTIVE_MISSING'):
            raise
        current = None
    if current != expected:
        raise ValueError('GENERATION_CONFLICT')
    return current


def publish_generation(config, records, *, expected_generation):
    if not isinstance(records, list) or not 1 <= len(records) <= 10000:
        raise ValueError('MODULE_PUBLICATION_RECORDS')
    # Apply the same parser budget as the serving API before changing storage.
    canonical_bytes(records)
    with _locked(config) as (config, root):
        previous = _compare(root, config, expected_generation)
        changes = {}
        for record in records:
            if not isinstance(record, dict):
                raise ValueError('MODULE_RECORD_IDENTITY')
            _validate_record(config, record, record.get('path'), record.get('query'))
            key = response_key(config['module_id'], record['path'], record['query'])
            if key in changes:
                raise ValueError('MODULE_DUPLICATE_RESPONSE')
            raw = canonical_bytes(record)
            _parse_record(raw, config)
            changes[key] = (hashlib.sha256(raw).hexdigest(), raw)
        refs = _load_records(config, root, previous)
        for key, (digest, raw) in changes.items():
            _write_immutable(root, 'objects', digest, raw)
            refs[key] = digest
        if len(refs) > 10000:
            raise ValueError('MODULE_GENERATION_RECORDS')
        manifest = dict(schema_version='v5.module_generation.v1', module_id=config['module_id'],
                        release_id=config['release_id'], records=refs)
        raw = canonical_bytes(manifest)
        generation = hashlib.sha256(raw).hexdigest()
        _write_immutable(root, 'generations', generation, raw)
        result = _activate(config, root, generation)
        return {**result, 'previous_generation': previous, 'changed': generation != previous}


def activate_generation(config, generation, *, expected_generation):
    sha(generation)
    with _locked(config) as (config, root):
        previous = _compare(root, config, expected_generation, explicit_recovery=True)
        result = _activate(config, root, generation)
        return {**result, 'previous_generation': previous, 'changed': generation != previous}
