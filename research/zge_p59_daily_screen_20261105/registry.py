"""Task-local wrapper around the existing locked official registry adapter.

Keep the exact four historical exceptions. Do not modify the shared validator
or assume other active tasks have stopped appending to the registry.
"""
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import sys

from screen import HERE, FLAGS, dump, require, sha

LEGACY_MODULE_SHA = '530dd93d982112fae71c37fe56c43bda478e78399830ec94a3f8a4f4e3ca7ca2'


def append(execution_id, event_type, contract_path, code_path, artifact, output_dir, decision='RUNNING'):
    require(event_type in ('RUN_STARTED', 'TERMINAL'), 'EVENT_TYPE_OUT_OF_SCOPE')
    path = HERE.parent / 'zge_phase59_mac_continue_20261105/registry.py'
    require(sha(path) == LEGACY_MODULE_SHA, 'REGISTRY_ADAPTER_WRAPPER_SOURCE_CHANGED')
    spec = importlib.util.spec_from_file_location('daily_p59_registry_reference', path)
    legacy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(legacy)
    contract = json.loads(Path(contract_path).read_text())
    adapter = legacy.OfficialRegistryAdapter()
    with adapter._locked():
        raw_before = adapter.registry_path.read_bytes()
        import hashlib
        require(len(raw_before) >= legacy.BASE_SIZE and hashlib.sha256(raw_before[:legacy.BASE_SIZE]).hexdigest() == legacy.BASE_SHA, 'REGISTRY_BASELINE_CHANGED')
        old = [json.loads(line) for line in raw_before[:legacy.BASE_SIZE].decode().splitlines()]
        for line, expected in legacy.LEGACY_EXCEPTIONS.items():
            require(old[line - 1].get('event_sha256') == expected and old[line - 1].get('event_type') == 'EVIDENCE_BOUND', 'EXACT_LEGACY_EXCEPTION_CHANGED')
        official = adapter.validator.OFFICIAL
        original_rule = official._execution_reuse_allowed
        official._execution_reuse_allowed = lambda e: original_rule(e) or e.get('event_sha256') in legacy.LEGACY_EXCEPTIONS.values()
        try:
            raw, events = adapter._read_validated()
            require(raw == raw_before, 'REGISTRY_READ_CHANGED_INSIDE_LOCK')
            prior = [e for e in events if e.get('execution_id') == execution_id]
            if event_type == 'RUN_STARTED':
                require(not prior, 'EXECUTION_ALREADY_EXISTS')
            else:
                require(sum(e.get('event_type') == 'RUN_STARTED' for e in prior) == 1 and not any(e.get('event_type') == 'TERMINAL' for e in prior), 'EXECUTION_LIFECYCLE_CONFLICT')
            template = next(e for e in reversed(events) if e.get('event_type') == 'RUN_STARTED')
            event = {k: v for k, v in template.items() if k not in ('previous_event_sha256', 'event_sha256', 'artifact_sha256')}
            event.update(schema_version='1.0', route_id=contract['route_id'], experiment_id=contract['route_id'],
                         execution_id=execution_id, track_id='A_SHARE_PHASE59_CONTINUE_RESEARCH',
                         registry_event_id=f'{execution_id}_D05_{event_type}', stage='D05_INFERENCE', event_type=event_type,
                         registration_mode='LIVE_EXECUTION', occurred_at=datetime.now(timezone.utc).isoformat(), occurred_at_reason='LIVE_EXECUTION_UTC',
                         contract_path=str(contract_path), contract_sha256=sha(contract_path), input_sha256=contract['input']['dataset_sha256'],
                         code_sha256=sha(code_path), config_sha256=sha(contract_path), baseline_id=contract['baseline_id'], one_variable=contract['one_variable'],
                         signal_date_range=contract['signal_date_range'], target_date_range=contract['target_date_range'], truth_access=contract['truth_access'],
                         sealed_status='NOT_SEALED_EXPOSED_HISTORY', runtime={'python': sys.executable}, device='CPU',
                         artifact_path=str(artifact), artifact_paths=[str(artifact)], artifact_sha256=sha(artifact), checkpoint_ref=None,
                         deterministic_metrics={'truth_positive_denominator': None, 'selection_slots': None, 'artifact_summary_path': str(artifact)},
                         decision=decision, stop_reason='NONE' if decision != 'CANNOT_CONFIRM' else 'SEE_TASK_FAILURE_ARTIFACT', evidence_level='DIRECTION_ONLY',
                         input_identity={**contract['input'], 'binding_sha256': contract['binding_sha256'],
                                         'null_reasons': {'deterministic_metrics.truth_positive_denominator': 'UNMATURED_NO_TRUTH', 'deterministic_metrics.selection_slots': 'NO_TRUTH_METRIC_IN_THIS_EVENT'}},
                         research_only=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)
            adapter._append_unlocked(raw, events, event)
            after, checked = adapter._read_validated()
            require(after.startswith(raw) and len(checked) == len(events) + 1, 'REGISTRY_APPEND_IDENTITY_CONFLICT')
            receipt = {'execution_id': execution_id, 'event_type': event_type, 'last_event_sha256': checked[-1]['event_sha256'],
                       'registry_path': str(adapter.registry_path), 'registry_sha256': hashlib.sha256(after).hexdigest(),
                       'old_prefix_byte_identity': 'PASS', 'new_event_chain_and_lifecycle': 'PASS',
                       'compatibility_validation': 'PASS_ONLY_WITH_EXACT_FOUR_HISTORICAL_EXCEPTIONS',
                       'global_validation': 'FAIL_PREEXISTING_SEMANTIC_DEBT', 'legacy_exact_event_sha_exceptions': legacy.LEGACY_EXCEPTIONS, 'flags': FLAGS}
        finally:
            official._execution_reuse_allowed = original_rule
    dump(Path(output_dir) / f'REGISTRY_{event_type}.json', receipt)
    return receipt
