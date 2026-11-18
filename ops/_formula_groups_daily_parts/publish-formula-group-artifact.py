"""Commit an approved two-formula date under the existing A_LONG owner lock."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import runpy
import stat
import tempfile

from urllib.parse import urlsplit

common = runpy.run_path(Path(__file__).with_name('prepare-formula-group-artifact.py'))
FLAGS, FORMULA_SHA256 = common['FLAGS'], common['FORMULA_SHA256']
prepare, require = common['prepare'], common['require']


def canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n').encode()


def path_sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def absolute(path):
    require(path.is_absolute() and path.resolve() == path, 'FORMULA_PUBLICATION_PATH_INVALID')
    return path


def atomic(path, raw):
    absolute(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix='.formula-groups.')
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        parent = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
    finally:
        Path(temp).unlink(missing_ok=True)


def immutable(day, folder, value):
    raw = canonical(value)
    digest = hashlib.sha256(raw).hexdigest()
    path = absolute(day / folder / f'{digest}.json')
    if path.exists():
        require(path.read_bytes() == raw, 'FORMULA_IMMUTABLE_PATH_CONFLICT')
    else:
        atomic(path, raw)
    return {'path': str(path), 'sha256': digest}


def publish(args):
    url = urlsplit(args.origin)
    require(url.scheme == 'http' and url.hostname == '127.0.0.1' and not (url.path or url.query or url.fragment),
            'FORMULA_PUBLICATION_ORIGIN_INVALID')
    binding_path = absolute(args.binding)
    raw_binding = binding_path.read_bytes()
    require(hashlib.sha256(raw_binding).hexdigest() == args.binding_sha256, 'FORMULA_HOST_BINDING_SHA_DRIFT')
    binding = json.loads(raw_binding)
    require(binding.get('schema') == 'V4_MAC_WORKBENCH_BINDING_V1'
            and isinstance(binding.get('candidate_group_overrides'), dict)
            and binding.get('candidate_group_formula_sha256') == FORMULA_SHA256
            and all(binding.get(key) is value for key, value in FLAGS.items()), 'FORMULA_HOST_BINDING_INVALID')
    root = absolute(Path(binding['formula_groups_root']))

    lock_path = absolute(args.owner_lock)
    inherited_fd = getattr(args, 'owner_fd', None)
    fd = (os.dup(inherited_fd) if inherited_fd is not None
          else os.open(lock_path, os.O_RDONLY | os.O_NOFOLLOW))
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        held = os.fstat(fd)
        current = os.stat(lock_path, follow_symlinks=False)
        require(stat.S_ISREG(held.st_mode) and (held.st_dev, held.st_ino) == (current.st_dev, current.st_ino),
                'FORMULA_OWNER_LOCK_DRIFT')
        require(binding_path.read_bytes() == raw_binding, 'FORMULA_HOST_BINDING_SHA_DRIFT')
        result = prepare(args.batch, args.origin)
        day = absolute(root / result['source_date'])
        latest = absolute(day / 'latest.json')
        before = path_sha(latest) if latest.exists() else 'ABSENT'
        stage_sha = hashlib.sha256(canonical(result)).hexdigest()
        if latest.exists():
            previous = json.loads(latest.read_bytes())
            previous_artifact = previous.get('artifact', {})
            if previous_artifact.get('sha256') == stage_sha:
                require(previous.get('schema') == 'V4_WORKBENCH_MODULE_COMMIT_V1'
                        and previous.get('module') == 'formula_groups' and previous.get('date') == day.name
                        and all(previous.get(key) is value for key, value in FLAGS.items()),
                        'FORMULA_CURRENT_POINTER_INVALID')
                path = absolute(Path(previous_artifact['path']))
                receipt_ref = previous['receipt']
                receipt_path = absolute(Path(receipt_ref['path']))
                require(path.is_relative_to(day) and path_sha(path) == stage_sha
                        and receipt_path.is_relative_to(day) and path_sha(receipt_path) == receipt_ref['sha256'],
                        'FORMULA_CURRENT_ARTIFACT_DRIFT')
                prior_receipt = json.loads(receipt_path.read_bytes())
                require(prior_receipt.get('status') == 'COMMITTED' and prior_receipt.get('artifact') == previous_artifact,
                        'FORMULA_CURRENT_RECEIPT_INVALID')
                return dict(status='ALREADY_COMMITTED', current_sha256=before, pointer=str(latest))
        require(before == args.expected_current, 'FORMULA_CURRENT_POINTER_MOVED')
        artifact = immutable(day, 'artifacts', result)
        receipt = immutable(day, 'receipts', dict(status='COMMITTED', artifact=artifact,
                            source_date=result['source_date'], generation=result['generation'],
                            numeric_manifest=result['numeric_manifest'], previous_pointer_sha256=before, **FLAGS))
        pointer = dict(schema='V4_WORKBENCH_MODULE_COMMIT_V1', module='formula_groups',
                       date=result['source_date'], artifact=artifact, receipt=receipt, **FLAGS)
        require((path_sha(latest) if latest.exists() else 'ABSENT') == before, 'FORMULA_CURRENT_POINTER_MOVED')
        atomic(latest, canonical(pointer))
        return dict(status='COMMITTED', current_sha256=path_sha(latest), pointer=str(latest), artifact=artifact, receipt=receipt)
    finally:
        os.close(fd)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch', type=Path, required=True)
    parser.add_argument('--binding', type=Path, required=True)
    parser.add_argument('--binding-sha256', required=True)
    parser.add_argument('--owner-lock', type=Path, required=True)
    parser.add_argument('--owner-fd', type=int)
    parser.add_argument('--expected-current', default='ABSENT')
    parser.add_argument('--origin', default='http://127.0.0.1:8873')
    print(json.dumps(publish(parser.parse_args()), ensure_ascii=False))
