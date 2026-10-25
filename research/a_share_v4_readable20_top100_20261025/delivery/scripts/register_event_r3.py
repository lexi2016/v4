"""Append a frozen-scope event through the existing official registry adapter."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path('/Users/lexi/Desktop/学习/因子工厂')
ADAPTER_PATH = ROOT / 'workspace/hkconnect_price_semantics_v2_20260919/zero_label_parity/registry_adapter.py'
TASK_ROOT = Path(__file__).resolve().parents[1]
RECEIPTS = TASK_ROOT / 'receipts'
FLAGS = {
    'research_only': True,
    'production_allowed': False,
    'buy_gate_updated': False,
    'orders_sent': False,
}


def sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha_file(path: Path) -> str:
    return sha_bytes(path.read_bytes())


def counts(events: list[dict]) -> dict:
    return {
        'routes': len({e['route_id'] for e in events}),
        'events': len(events),
        'executions': len({e['execution_id'] for e in events}),
        'corrections': sum(e['event_type'] == 'CORRECTION' for e in events),
    }


def get_adapter():
    sys.path.insert(0, str(ADAPTER_PATH.parent))
    spec = importlib.util.spec_from_file_location('readable20_official_registry_adapter', ADAPTER_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module.OfficialRegistryAdapter()


def append_event(contract_path: Path, execution_id: str, stage: str, event_type: str,
                 truth_access: str, decision: str, evidence_level: str,
                 artifact_paths: list[Path], metrics: dict | None = None,
                 stop_reason: str = 'NONE') -> dict:
    contract = json.loads(contract_path.read_text())
    assert contract['route_id'] == 'A_SHARE_V4_READABLE20_TOP100_20261025'
    adapter = get_adapter()
    event = {
        'schema_version': '1.0',
        'registry_event_id': f'{execution_id}_{stage}',
        'registration_mode': 'LIVE_EXECUTION',
        'route_id': contract['route_id'],
        'experiment_id': contract['route_id'],
        'execution_id': execution_id,
        'track_id': 'A_SHARE_V4_READABLE20_TOP100_DESCRIPTIVE',
        'stage': stage,
        'event_type': event_type,
        'occurred_at': datetime.now(timezone.utc).isoformat(),
        'contract_path': str(contract_path),
        'input_sha256': contract.get('input_sha256'),
        'input_sha256_reason': contract.get('input_sha256_reason'),
        'code_sha256': contract.get('code_sha256'),
        'code_sha256_reason': contract.get('code_sha256_reason'),
        'config_sha256': contract.get('config_sha256'),
        'config_sha256_reason': contract.get('config_sha256_reason'),
        'baseline_id': contract['baseline_id'],
        'one_variable': contract['one_variable'],
        'signal_date_range': contract['signal_date_range'],
        'target_date_range': contract['target_date_range'],
        'truth_access': truth_access,
        'sealed_status': contract['sealed_status'],
        'runtime': {'python': sys.executable},
        'device': 'MAC_LOCAL_CPU',
        'artifact_paths': [str(contract_path), *[str(p) for p in artifact_paths]],
        'checkpoint_ref': str(artifact_paths[-1]) if event_type == 'CHECKPOINT' and artifact_paths else None,
        'deterministic_metrics': {
            'truth_positive_denominator': None,
            'selection_slots': None,
            **(metrics or {}),
        },
        'decision': decision,
        'stop_reason': stop_reason,
        'evidence_level': evidence_level,
        **FLAGS,
    }
    with adapter._locked():
        raw_before, events_before = adapter._read_validated()
        same = [e for e in events_before if e['execution_id'] == execution_id]
        if event_type == 'RUN_STARTED':
            if same:
                raise RuntimeError(f'EXECUTION_ALREADY_EXISTS:{execution_id}')
        else:
            if not any(e['event_type'] == 'RUN_STARTED' for e in same):
                raise RuntimeError(f'RUN_STARTED_MISSING:{execution_id}')
            if any(e['event_type'] in {'TERMINAL', 'CORRECTION'} for e in same):
                raise RuntimeError(f'EXECUTION_ALREADY_TERMINAL:{execution_id}')
        adapter._append_unlocked(raw_before, events_before, event)
        raw_after, events_after = adapter._read_validated()
        saved = events_after[-1]
        if saved['execution_id'] != execution_id or saved['stage'] != stage or saved['event_type'] != event_type:
            raise RuntimeError('APPENDED_EVENT_READBACK_MISMATCH')
        scope_events = [e for e in events_after if e['route_id'] == contract['route_id']]
        receipt = {
            'schema': 'READABLE20_REGISTRY_RECEIPT_V1',
            'route_id': contract['route_id'],
            'execution_id': execution_id,
            'stage': stage,
            'event_type': event_type,
            'event_sha256': saved['event_sha256'],
            'registry_path': str(adapter.registry_path),
            'registry_prefix_sha256': sha_bytes(raw_before),
            'registry_sha256': sha_bytes(raw_after),
            'global_counts': counts(events_after),
            'scope_counts': counts(scope_events),
            'global_unregistered_route_count': None,
            'global_contract_only_count': None,
            'count_gap_reason': 'GLOBAL_ROUTE_AND_CONTRACT_INVENTORY_NOT_IN_THIS_SCOPE',
            'scope_unregistered_route_count': 0,
            'scope_contract_only_count': 0,
            'external_persistence': 'CANNOT_CONFIRM',
            'decision': decision,
            **FLAGS,
        }
        RECEIPTS.mkdir(parents=True, exist_ok=True)
        receipt_path = RECEIPTS / f'{execution_id}_{stage}.json'
        receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n')
        with receipt_path.open('rb') as f:
            os.fsync(f.fileno())
        receipt['projection_sync_note'] = 'CURRENT_EVENT_AND_CURRENT_BATCH_SNAPSHOT_ONLY; earlierLunaeventsnotclaimedpreviouslysynced'
        for name in ['CURRENT_STATE.md', 'HK_OHLCV_RESEARCH_STATE.md', 'PROGRESS.md']:
            with (ROOT / name).open('a') as f:
                f.write('\n<!-- A_SHARE_V4_READABLE20_TOP100_20261025 -->\n' + json.dumps(receipt, ensure_ascii=False, separators=(',', ':')) + '\n')
                f.flush(); os.fsync(f.fileno())
        out = ROOT / 'research/a_share_v4_readable20_top100_20261025'
        (out / 'INDEX.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n')
        return receipt


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--contract', type=Path, required=True)
    parser.add_argument('--execution-id', required=True)
    parser.add_argument('--stage', required=True)
    parser.add_argument('--event-type', choices=['RUN_STARTED', 'CHECKPOINT', 'TERMINAL'], required=True)
    parser.add_argument('--truth-access', required=True)
    parser.add_argument('--decision', required=True)
    parser.add_argument('--evidence-level', required=True)
    parser.add_argument('--artifact', action='append', default=[], type=Path)
    parser.add_argument('--metrics-json', default='{}')
    parser.add_argument('--stop-reason', default='NONE')
    args = parser.parse_args()
    result = append_event(
        args.contract, args.execution_id, args.stage, args.event_type,
        args.truth_access, args.decision, args.evidence_level,
        args.artifact, json.loads(args.metrics_json), args.stop_reason,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
