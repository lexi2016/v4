"""Independent SYNTHETIC R8 bug probe; never a positive production test.

Usage: PYTHONPATH=<isolated-copy>/V5/src python -B this_file.py <isolated-copy>
Not run by the static reviewer. The real context intentionally has no permit:
the R8 bug must reject the real strict store before assembler/store methods.
"""
import importlib.util
import sys
import tempfile
from pathlib import Path

source = Path(sys.argv[1]).resolve()
from v5_shadow.a_preselection import _FrozenLoader, _source_bytes
assert not any(name in sys.modules for name in ('domains', 'infrastructure', 'contracts', 'upstreams'))
sys.meta_path.insert(0, _FrozenLoader(_source_bytes()))
from infrastructure.scope_gate import StoreGateContext
from infrastructure.preselection_pool_store import PreselectionPoolStore
from v5_shadow.a_preselection_daily import build_m05_daily

spec = importlib.util.spec_from_file_location('m05_original_fixture_helpers', source / 'V5/tests/test_a_preselection.py')
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)

with tempfile.TemporaryDirectory(prefix='m05-r8-bug-only-') as raw:
    base = Path(raw).resolve()
    output = base / 'output'
    output.mkdir()
    (output / '.v5-shadow-root').write_text('v5.shadow-root.v1\n')
    authority = base / 'inputs'
    authority.mkdir()
    lane = fixture.make_lane(authority / 'fupan')
    control = base / 'control'
    control.mkdir()
    v4 = base / 'synthetic-v4-boundary'
    v4.mkdir()
    context = StoreGateContext(control_dir=control, expected_permit_sha256='0' * 64,
        expected_owner_id='M05_R8_SYNTHETIC_BUG_ONLY', expected_release_sha256='0' * 64,
        expected_root=output)
    store = PreselectionPoolStore(output, write_gate_context=context, require_write_gate_context=True)
    assert store._require_write_gate_context is True
    assert store._write_gate_context is context
    assert not hasattr(store, 'require_write_gate_context')
    request = dict(target_date='20261008', signal_date='20260930', data_kind='SYNTHETIC', lanes=[lane])
    def unreachable_runner(_request):
        raise AssertionError('Unexpected assembler entry: this reproduction requires unchanged R8')
    try:
        build_m05_daily(request, run_a_preselection=unreachable_runner, store=store,
            source_root=str(authority), private_root=str(output), code_root=str(source),
            v4_root=str(v4), write_gate_context=context)
    except ValueError as error:
        assert str(error) == 'M05_STORE_STRICT_GATE_REQUIRED', repr(error)
        assert sorted(p.name for p in output.iterdir()) == ['.v5-shadow-root']
        print('BUG_REPRODUCED: real strict store falsely rejected before assembler and writer; no output write')
    else:
        raise AssertionError('Expected unchanged R8 false rejection')
