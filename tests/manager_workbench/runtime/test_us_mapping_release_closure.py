"""Frozen r3 scheduler composition checks; all outputs require an isolated root.

Run with the candidate app first on sys.path. This file never activates a role,
captures data, or accesses labels. Native source readback and frozen-checkpoint
execution are deliberately separate so newly read bytes cannot replace US23.
"""
from copy import deepcopy
from collections import Counter
from datetime import datetime
import hashlib
import importlib
import json
import os
from pathlib import Path
import socket
import subprocess
import time

import pytest

HERE = Path(__file__).resolve().parents[3]
PROFILE = HERE / 'docs/handoffs/us_mapping_scheduler_integration_20261025/COHORT.json'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def evidence_root():
    root = Path(os.environ['US_MAPPING_CLOSURE_ARTIFACT_ROOT']).resolve()
    assert root.name == 'runtime-integration-r1' and root.is_dir()
    return root


def dump(name, value):
    (evidence_root() / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def frozen_input():
    path = Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/state/manager_workbench/manager_workbench/input_snapshots/e2c9ecd0dcedd303f6fabd6f199c9bf805dbc51c36f620c18dd9930386a5b16b.json')
    assert sha(path) == path.stem
    return path, json.loads(path.read_bytes())


def isolated_config(tmp_path):
    from v4.manager_workbench.config import load_config
    path = Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/us-mapping-natural-scheduler-20261021-r4/us-industry-observed-scheduler-20261021-r2.json')
    # Preserve read-only owner roots; disable every capture capability locally.
    return load_config(path).model_copy(update=dict(state_root=tmp_path, workers=1,
        capture_enabled=False, capture_root=None, capture_lease_root=None,
        capture_lease_token=None, dynamic_source_bindings=False))


@pytest.fixture
def no_external(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('NETWORK_MODEL_OR_SUBPROCESS_FORBIDDEN')
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(subprocess, 'Popen', forbidden)


def test_candidate_imports_own_complete_closure():
    profile = json.loads(PROFILE.read_bytes())
    app = Path(profile['candidate_release']) / 'app'
    names = ['v4.manager_workbench.supervisor', 'v4.manager_workbench.inputs.native',
        'v4.manager_workbench.inputs.strict_us_selection', 'v4.manager_workbench.engines.core',
        'v4.manager_workbench.engines.us_mapping', 'v4.manager_workbench.engines.us_mapping_consumption',
        'v4.manager_workbench.engines.strict_us_selection', 'v4.manager_workbench.engines.us_mapping_policy',
        'v4.manager_workbench.contracts', 'v4.manager_workbench.service', 'v4.manager_workbench.scheduler',
        'upstreams.v3_shared_data.shared_data.hk_history_resolution',
        'upstreams.v3_shared_data.shared_data.hk_panel_audit']
    loaded = {}
    for name in names:
        module = importlib.import_module(name)
        path = Path(module.__file__).resolve()
        assert path.is_relative_to(app), (name, path)
        relative = path.relative_to(app).as_posix()
        if relative in profile['expected_overlays']:
            assert sha(path) == profile['expected_overlays'][relative]['source_sha256']
        loaded[name] = dict(path=str(path), sha256=sha(path))
    dump('candidate-imports.json', loaded)


def test_real_native_owner_readback_separate_from_frozen_execution(tmp_path, no_external):
    from v4.manager_workbench.contracts import RunContext, Lane
    from v4.manager_workbench.inputs.native import NativeAdapters
    path, original = frozen_input()
    cfg = isolated_config(tmp_path)
    adapter = NativeAdapters(cfg)
    context = RunContext.model_validate(original['context'])
    loaded = adapter.load(Lane.US_MAPPING, adapter.prepare_context(context)).model_dump(mode='json')
    old = original['batches'][0]
    def payloads(batch):
        return [r.get('us_factor_payload', {}).get('strict_selection_payload') for r in batch['records']
            if isinstance(r.get('us_factor_payload'), dict)]
    def legacy_comparable_records(batch):
        records = deepcopy(batch['records'])
        for row in records:
            factor = row.get('us_factor_payload')
            if isinstance(factor, dict):
                factor.pop('strict_selection_payload', None)
                factor.pop('single_day_mapping_payload', None)
            # Exact three source-fact projections newly carried by modern
            # Native; this normalization is comparison-only, never engine input.
            for relation in row.get('relations', []):
                for key in ('current_validity', 'direction', 'primary_theme'):
                    relation.pop(key, None)
        return records
    from v4.manager_workbench.contracts import digest
    def differences(left, right, prefix=''):
        if isinstance(left, dict) and isinstance(right, dict):
            result = []
            for key in sorted(left.keys() | right.keys()):
                if key not in left or key not in right:
                    result.append(dict(path=prefix+'.'+key, before_sha256=digest(left.get(key)), after_sha256=digest(right.get(key))))
                elif left[key] != right[key]:
                    result.extend(differences(left[key], right[key], prefix+'.'+key))
            return result
        if isinstance(left, list) and isinstance(right, list) and len(left) == len(right):
            return [item for index,(a,b) in enumerate(zip(left,right)) if a != b
                for item in differences(a,b,prefix+f'[{index}]')]
        return [dict(path=prefix, before_sha256=digest(left), after_sha256=digest(right))]
    report = dict(state='READ_ONLY_NATIVE_SOURCE_COMPARISON', frozen_input_path=str(path), frozen_input_sha256=sha(path),
        source_cutoff=context.scope_refs.get('source_cutoff'), execution_cutoff=context.cutoff,
        old_batch_sha256=old['input_sha256'], native_batch_sha256=loaded['input_sha256'],
        frozen_record_count=len(old['records']), native_record_count=len(loaded['records']),
        record_bytes_equal=old['records'] == loaded['records'], evidence_refs_equal=old['evidence_refs'] == loaded['evidence_refs'],
        legacy_comparable_records_equal=legacy_comparable_records(old) == legacy_comparable_records(loaded),
        comparison_only_projection_fields=['relations.current_validity','relations.direction','relations.primary_theme',
            'us_factor_payload.strict_selection_payload','us_factor_payload.single_day_mapping_payload'],
        frozen_selection_payloads_sha256=digest(payloads(old)), native_selection_payloads_sha256=digest(payloads(loaded)),
        first_record_differences=differences(old['records'][0], loaded['records'][0]),
        engine_calls=0, replacement_of_frozen_input=False)
    dump('native-owner-readback.json', report)
    assert len(loaded['records']) == len(old['records'])
    assert old['evidence_refs'] == loaded['evidence_refs']
    assert legacy_comparable_records(old) == legacy_comparable_records(loaded)
    assert sha(path) == path.stem


def test_real_hook_handoff_native_us23_engine_and_isolated_saved_focus(tmp_path, monkeypatch, no_external):
    from v4.manager_workbench import engines
    from v4.manager_workbench.binding import CalendarAdapter, StageFeed
    from v4.manager_workbench.inputs.native import NativeAdapters
    from v4.manager_workbench.inputs import source_bindings
    from v4.manager_workbench.contracts import Lane
    from v4.manager_workbench.engines import core
    from v4.manager_workbench.engines.strict_us_selection import engine_identity
    from v4.manager_workbench.scheduler import _handoff_identity
    from v4.manager_workbench.contracts import digest
    from v4.manager_workbench.supervisor import WorkbenchHook
    path, original = frozen_input()
    context = original['context']
    cfg = isolated_config(tmp_path).model_copy(update=dict(dynamic_source_bindings=True))
    pins, gaps = context['scope_refs']['owner_bindings'], context['scope_refs']['owner_binding_gaps']
    resolutions = []
    def exact_saved_owners(config, ctx):
        resolutions.append(ctx.cutoff)
        return deepcopy(pins), deepcopy(gaps)
    monkeypatch.setattr(source_bindings, 'resolve_bindings', exact_saved_owners)
    adapter = NativeAdapters(cfg)
    moment = datetime.fromisoformat(context['cutoff'])
    hook = WorkbenchHook(cfg, clock=lambda:moment, binding=dict(adapters=adapter,
        engines=engines, executor=object(), calendar=CalendarAdapter(), stage_feed=StageFeed(adapter)))
    service = hook.service
    identity = _handoff_identity(pins['us_mapping'], '20261026')
    legacy_identity = {k:v for k,v in identity.items() if not k.startswith('selection_')}
    old_job_id = 'd725567793324cfea5617018e989a4da'
    service.store.set_cursor('us_close_'+digest(legacy_identity), dict(input_key=digest(legacy_identity), state='CONSUMED'))
    service.store.save_checkpoint(old_job_id, 'lane_US_MAPPING', dict(selection=None, legacy_zero_checkpoint=True))
    real_work = service._work
    def with_old_lane_checkpoint(job):
        # Resume only the old lane cache; no LOAD_INPUTS checkpoint exists, so
        # the actual loader must read Native, then reject the unversioned lane.
        job.context.scope_refs['resume_from_job'] = old_job_id
        return real_work(job)
    monkeypatch.setattr(service, '_work', with_old_lane_checkpoint)
    scope = dict(merge_phase_lanes=True, us_close_handoff=True, us_session_date='20261023',
        us_close_handoff_key=digest(identity), owner_artifact_sha256=identity['artifact_sha256'],
        owner_receipt_sha256=identity['receipt_sha256'], owner_manifest_sha256=identity['manifest_sha256'],
        source_cutoff=identity['capture_cutoff'], owner_bindings=deepcopy(pins), owner_binding_gaps=deepcopy(gaps),
        resume_from_job=old_job_id)
    expected_context = service.context('20261026', __import__('v4.manager_workbench.contracts',fromlist=['Phase']).Phase.NEXT_DAY,
        trigger='SCHEDULED', cutoff=moment, lanes=[Lane.US_MAPPING], scope_refs=scope)
    native_frozen = adapter.load(Lane.US_MAPPING, expected_context)
    dump('native-engine-input-freeze.json', dict(input_sha256=native_frozen.input_sha256,
        record_count=len(native_frozen.records), records_sha256=digest(native_frozen.records),
        evidence_refs_sha256=digest([r.model_dump(mode='json') for r in native_frozen.evidence_refs]),
        source_cutoff=expected_context.scope_refs['source_cutoff'], cutoff=expected_context.cutoff,
        owner_quote_sha256=pins['us_mapping']['quote_sha256'], engine_calls=0))
    native_loads = []
    real_load = adapter.load
    def observed_load(lane, ctx):
        loaded = real_load(lane, ctx)
        if lane == Lane.US_MAPPING:
            dump('native-engine-input-observed.json', dict(input_sha256=loaded.input_sha256,
                expected_sha256=native_frozen.input_sha256, records_sha256=digest(loaded.records),
                evidence_refs_sha256=digest([r.model_dump(mode='json') for r in loaded.evidence_refs])))
            assert loaded.input_sha256 == native_frozen.input_sha256
            assert loaded.records == native_frozen.records and loaded.evidence_refs == native_frozen.evidence_refs
            native_loads.append(loaded.input_sha256)
        return loaded
    monkeypatch.setattr(adapter, 'load', observed_load)
    calls = []
    real_engine = core.run_us_mapping
    def observed_engine(ctx, batch):
        assert batch['input_sha256'] == native_frozen.input_sha256
        calls.append(dict(input_sha256=batch['input_sha256'], target_date=ctx['target_date'],
            source_cutoff=ctx['scope_refs'].get('source_cutoff'), cutoff=ctx['cutoff']))
        dump('actual-engine-calls.json', calls)
        return real_engine(ctx, batch)
    monkeypatch.setattr(core, 'run_us_mapping', observed_engine)
    try:
        result = hook.once()
        assert result['state'] == 'NOT_APPLICABLE' and len(result['jobs']) == 1
        submitted = result['jobs'][0]
        job = service.jobs.get(submitted['job_id'])
        deadline = time.monotonic() + 30
        while job.state.value in {'QUEUED', 'RUNNING'} and time.monotonic() < deadline:
            time.sleep(.02)
            job = service.jobs.get(job.job_id)
        assert job.state.value in {'SUCCEEDED', 'PARTIAL'}, job.model_dump(mode='json')
        saved = service.store.get_plan('20261026', 'NEXT_DAY')
        assert saved is not None and len(calls) == 1
        lane = next(l for l in saved.lanes if l.lane == Lane.US_MAPPING)
        selection = lane.selection.model_dump(mode='json')
        expected = json.loads((evidence_root().parent / 'cleanup/canonical-selection-after.json').read_bytes())
        assert selection['engine_identity'] == engine_identity()
        before, after = deepcopy(expected), deepcopy(selection)
        before.pop('engine_identity'); after.pop('engine_identity')
        same_selection = after == before
        assert selection['focus']['counts']['selected'] == 10
        assert selection['counts']['selected'] == 0
        assert saved.context.scope_refs['source_cutoff'] == context['scope_refs']['source_cutoff']
        assert saved.context.cutoff == context['cutoff']
        assert saved.changes['us_selection_engine_identity'] == engine_identity()
        identity = _handoff_identity(pins['us_mapping'], '20261026')
        legacy_identity = {k:v for k,v in identity.items() if not k.startswith('selection_')}
        assert digest(identity) != digest(legacy_identity)
        assert submitted['input_key'] == digest(identity)
        old_snapshot = path.parent.parent / 'snapshots/d725567793324cfea5617018e989a4da.json'
        assert sha(old_snapshot) == 'c69fa636d513af59f248474addf25784fa613e4a1495bd5d70af1c14f6adf3bf'
        old_symbols = {r['symbol'] for r in json.loads(old_snapshot.read_bytes())['stocks']}
        strict = {r['symbol']:r['decision'] for r in selection['strict_decisions']}
        fates = {s:strict.get(s, 'NOT_CANDIDATE') for s in sorted(old_symbols)}
        fate_counts = dict(Counter(fates.values()))
        assert len(fates) == 701
        dump('all-legacy-stock-fates.json', fates)
        dump('scheduler-frozen-us23-readback.json', dict(state='REPROCESSED_REAL_NATIVE_US23_ENGINEERING_ONLY',
            hook_class=hook.__class__.__module__, native_class=adapter.__class__.__module__, service_class=service.__class__.__module__,
            source_input_path=str(path), source_input_sha256=sha(path), isolated_state_root=str(service.store.root),
            saved_run_id=saved.run_id, job_id=job.job_id, job_state=job.state.value,
            saved_product_sha256=saved.product_sha256, source_cutoff=saved.context.scope_refs['source_cutoff'], cutoff=saved.context.cutoff,
            engine_calls=calls, focus_counts=selection['focus']['counts'],
            focus_selected=[r for r in selection['focus']['decisions'] if r['decision']=='SELECTED'],
            legacy_stock_fates=fate_counts, strict_counts=selection['counts'],
            canonical_selection_equal_except_engine_identity=same_selection, canonical_selection_sha256=digest(selection),
            native_load_calls=native_loads, native_frozen_batch_sha256=native_frozen.input_sha256,
            old_cache_rejected=True, new_handoff_key=digest(identity), legacy_handoff_key=digest(legacy_identity),
            selection_engine_identity=engine_identity(), actual_owner_resolution_count=len(resolutions),
            natural_verification='NOT_RUN', RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False))
        assert native_loads == [native_frozen.input_sha256]
        assert selection['focus']['counts']['selected'] == 10
        assert sha(path) == path.stem
    finally:
        hook.stop()
