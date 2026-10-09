import hashlib
import importlib.util
import json
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location('r3_verifier', Path(__file__).resolve().parents[1] / 'tools/verify_delivery.py')
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


def fixture(tmp_path):
    package, source = tmp_path / 'package', tmp_path / 'source'
    package.mkdir(); source.mkdir()
    old, new, protected = b'old\n', b'new\n', b'Issue32 stays\n'
    rows = []
    for rel, before, after in [('owned.py', old, new), ('added.py', None, b'added\n')]:
        row = {'profile': 'api', 'path': rel}
        for side, raw in [('before', before), ('after', after)]:
            row[side + '_sha256'] = verifier.sha(raw)
            row[side + '_bytes'] = len(raw) if raw is not None else None
            row[side + '_path'] = f'{side}/api/{rel}' if raw is not None else None
            if raw is not None:
                p = package / row[side + '_path']; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(raw)
        rows.append(row)
    patch = package / 'runtime.patch'; patch.write_bytes(b'synthetic patch identity\n')
    (source / 'owned.py').write_bytes(old); (source / 'protected.py').write_bytes(protected)
    data = {'schema_version': verifier.SCHEMA, 'profiles': {'api': {
        'patch_path': patch.name, 'patch_sha256': verifier.sha(patch.read_bytes())}},
        'files': rows, 'preserve': [{'profiles': ['api'], 'path': 'protected.py', 'sha256': verifier.sha(protected)}]}
    (package / 'source_manifest.json').write_text(json.dumps(data))
    return package, source


def test_exact_before_with_absent_addition_passes_without_writes(tmp_path):
    package, source = fixture(tmp_path)
    before = {p.name: p.read_bytes() for p in source.iterdir()}
    result = verifier.verify(package, profile='api', source_root=source, against='before')
    assert result['status'] == 'PASS' and result['source_writes'] == 0
    assert result['preserved_checked'] == ['protected.py']
    assert {p.name: p.read_bytes() for p in source.iterdir()} == before


@pytest.mark.parametrize('path,value,code', [
    ('owned.py', b'parallel change\n', 'SOURCE_BEFORE_MISMATCH'),
    ('added.py', b'existing unknown namespace\n', 'SOURCE_BEFORE_MISMATCH'),
    ('protected.py', b'old Issue32\n', 'PRESERVED_SOURCE_MISMATCH'),
])
def test_parallel_changed_or_newly_existing_or_protected_bytes_reject(tmp_path, path, value, code):
    package, source = fixture(tmp_path)
    (source / path).write_bytes(value)
    with pytest.raises(ValueError, match=code):
        verifier.verify(package, profile='api', source_root=source, against='before')
    assert (source / path).read_bytes() == value


def test_payload_corruption_and_undeclared_extra_payload_reject(tmp_path):
    package, source = fixture(tmp_path)
    p = package / 'after/api/owned.py'; original = p.read_bytes(); p.write_bytes(b'tampered')
    with pytest.raises(ValueError, match='PAYLOAD_MISMATCH'):
        verifier.verify(package)
    p.write_bytes(original); (package / 'after/api/extra.py').write_bytes(b'extra')
    with pytest.raises(ValueError, match='PAYLOAD_SET_MISMATCH'):
        verifier.verify(package)


def test_symlink_and_unknown_profile_never_pass(tmp_path):
    package, source = fixture(tmp_path)
    original = source / 'owned.py'; original.unlink(); original.symlink_to(source / 'protected.py')
    with pytest.raises(ValueError, match='SYMLINK_REJECTED'):
        verifier.verify(package, profile='api', source_root=source, against='before')
    with pytest.raises(ValueError, match='PROFILE_UNKNOWN'):
        verifier.verify(package, profile='worker')
