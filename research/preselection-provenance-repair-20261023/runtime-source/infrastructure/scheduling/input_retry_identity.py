"""Observe fixed owned inputs for retry permission, never for source admission."""
from __future__ import annotations
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

_WORKLOADS = frozenset({'preselection_pools', 'hourly_research', 'research_panel_runtime_evidence'})
_CODE_PATHS = ('ops/materialize_shared_v192_preselection.py', 'ops/materialize_scheduled_preselection.py',
    'infrastructure/scheduling/executor_registry_preselection.py', 'ops/run_hourly_research.py',
    'infrastructure/scheduling/executor_registry_research.py', 'infrastructure/scheduling/dispatcher.py',
    'ops/run_v35_macos_scheduler_due.py', 'infrastructure/scheduling/input_retry_identity.py',
    'infrastructure/scheduling/_executor_registry_parts/preselection.py',
    'infrastructure/scheduling/_executor_registry_parts/research_materials.py',
    'ops/_run_v35_macos_scheduler_parts/schedule_selection.py')
_LIMIT = 16 * 1024 * 1024


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def _path(root: Path, value: str) -> Path:
    path = Path(value)
    if '..' in path.parts:
        raise ValueError('UNSAFE_PATH')
    if not path.is_absolute():
        path = root / path
    path.resolve().relative_to(root.resolve())
    return path


def _read(root: Path, relative: str) -> tuple[dict, bytes | None]:
    try:
        path = _path(root, relative)
        if not path.exists():
            return {'state': 'MISSING'}, None
        if not path.is_file() or path.stat().st_size > _LIMIT:
            return {'state': 'UNREADABLE_OR_OVERSIZE'}, None
        raw = path.read_bytes()
        return {'state': 'PRESENT', 'sha256': hashlib.sha256(raw).hexdigest()}, raw
    except (OSError, ValueError, RuntimeError):
        return {'state': 'REJECTED_OWNED_PATH'}, None


def _json(root: Path, relative: str):
    observation, raw = _read(root, relative)
    if raw is None:
        return observation, None
    try:
        value = json.loads(raw.decode('utf-8-sig'))
        if not isinstance(value, dict):
            raise ValueError('not object')
        return observation, value
    except (ValueError, UnicodeError):
        return {**observation, 'state': 'INVALID_JSON'}, None


def _source_content(value):
    """Only attempt-generated header fields are excluded; event/PIT times remain."""
    result = dict(value)
    manifest = result.get('source_manifest')
    if isinstance(manifest, dict):
        result['source_manifest'] = {k: v for k, v in manifest.items()
            if k not in {'generated_at', 'published_at', 'version'}}
    return result


def _dependency_content(value):
    if isinstance(value, dict):
        return {k: _dependency_content(v) for k, v in value.items() if k not in {
            'generated_at', 'created_at', 'finished_at', 'started_at', 'updated_at',
            'attempt', 'elapsed_seconds', 'duration_seconds', 'runner_called',
            'receipt_written', 'argv', 'error', 'exception_type'}}
    if isinstance(value, list):
        return [_dependency_content(v) for v in value]
    return value


def _dependency(root, relative):
    state, value = _json(root, relative)
    return {'state': 'PRESENT', 'semantic_sha256': _hash(_dependency_content(value))} if value is not None else state


def observe_input_identity(workload_id: str, business_date: str, target_date: str, slot: str, pending_pool_ids: list[str] | None = None) -> dict | None:
    if workload_id not in _WORKLOADS or (workload_id == 'hourly_research' and slot in {'0700', '0800', '1530'}):
        return None
    if workload_id == 'hourly_research':
        target_date = business_date  # hourly archives own the business date
    if not re.fullmatch(r'\d{8}', business_date) or not re.fullmatch(r'\d{8}', target_date) or not re.fullmatch(r'\d{4}', slot):
        raise ValueError('INPUT_WAIT_DATE_SLOT_INVALID')
    observations: dict[str, Any] = {}
    def configured(name):
        value = os.environ.get(name)
        observations[name] = {'root': str(Path(value).resolve()) if value else None}
        return Path(value) if value else None
    if workload_id in {'preselection_pools', 'research_panel_runtime_evidence'}:
        shared = configured('V35_SHARED_DATA_ROOT')
        if shared is not None:
            state, registry = _json(shared, 'latest.json')
            if registry is None and state.get('state') == 'MISSING':
                registry = {'entries': {}}
            if registry is None:
                observations['exact_registry'] = state
            else:
                entries = registry.get('entries')
                if not isinstance(entries, dict):
                    observations['exact_registry'] = {'state': 'INVALID_ENTRIES'}
                else:
                    roles = {'a_d1_premarket_pool': 'A_SHARE_V192_PREMARKET_POOL_V3', 'hkconnect_d1_top100': 'HK_CONNECT_D1_TOP100_0_2'}
                    for pool_id, role in roles.items():
                        if pending_pool_ids is not None and pool_id not in pending_pool_ids:
                            continue
                        entry = entries.get(target_date + '/' + role)
                        # Ignore unrelated entries and mutable registry timestamps.
                        if not isinstance(entry, dict):
                            observations[role] = {'state': 'MISSING'}
                            continue
                        identity = {k: entry.get(k) for k in ('run_id','status','artifact_relative','artifact_sha256',
                            'manifest_relative','manifest_sha256','receipt_relative','receipt_sha256')}
                        observations[role] = identity
                        for kind in ('artifact', 'manifest', 'receipt'):
                            relative = entry.get(kind + '_relative')
                            observations[role + '/' + kind] = (_read(shared, relative)[0]
                                if isinstance(relative, str) else {'state': 'INVALID_REFERENCE'})
        selector = (configured('V35_SELECTOR_DATA_ROOT')
            if pending_pool_ids is None or 'a_d1_premarket_pool' in pending_pool_ids else None)
        if selector is not None:
            state, raw = _read(selector, 'data_layer_interface_current/CURRENT_SELECTOR_READY_PANEL.txt')
            observations['selector_pointer'] = state
            if raw is not None:
                try:
                    panel = _path(selector, raw.decode('utf-8-sig').strip())
                    observations['selector_availability'] = {'path': str(panel), 'state': 'PRESENT' if panel.is_file() else 'MISSING'}
                    # The panel is immutable; never scan or hash millions of rows per tick.
                    for name in ('manifest.json', 'receipt.json', panel.stem + '.manifest.json'):
                        observations['selector/' + name] = _read(selector, str(panel.parent / name))[0]
                except (ValueError, UnicodeError, OSError, RuntimeError):
                    observations['selector_availability'] = {'state': 'REJECTED_OWNED_PATH'}
    else:
        data = configured('V35_DATA_ROOT')
        if data is not None:
            incoming = data / 'research/incoming' / business_date
            relative = f'research/incoming/{business_date}/{slot}.json'
            state, source = _json(data, relative)
            observations['canonical_source'] = ({'state':'PRESENT', 'content_sha256':_hash(_source_content(source))} if source is not None else state)
            # Content dedupe prevents retries from manufacturing progress via a new recovery filename/version.
            recoveries = set()
            try:
                _path(data, str(incoming))
                paths = sorted(incoming.glob(slot + '.recovery-*.json'))
                if len(paths) > 128:
                    raise ValueError('TOO_MANY_RECOVERIES')
                for path in paths:
                    st, payload = _json(data, str(path))
                    recoveries.add(_hash(_source_content(payload)) if payload is not None else _hash(st))
                observations['recovery_content'] = sorted(recoveries)
            except (OSError, ValueError, RuntimeError):
                observations['recovery_content'] = {'state': 'REJECTED_OWNED_PATH'}
            receipt = f'research_module/runtime_outputs/zsxq_hourly/{business_date}/{slot}/v35_zsxq_hourly_status_{business_date}_{slot}.json'
            state, status = _json(data, receipt)
            observations['zsxq_receipt'] = state
            if status is not None:
                paths = status.get('paths')
                if isinstance(paths, dict):
                    for key in ('fetch_result', 'recent_topics', 'summary'):
                        value = paths.get(key)
                        try:
                            path = _path(data, value) if isinstance(value,str) else None
                            if path is None or not path.resolve().is_relative_to((data/'external_sources/zsxq_hourly').resolve()):
                                raise ValueError('UNOWNED_SOURCE_REFERENCE')
                            observations['zsxq/' + key] = _read(data, str(path))[0]
                        except (OSError, ValueError, RuntimeError):
                            observations['zsxq/' + key] = {'state':'REJECTED_OWNED_PATH'}
    if workload_id == 'research_panel_runtime_evidence':
        data = configured('V35_DATA_ROOT')
        if data is not None:
            producer = Path(os.environ.get('V35_RESEARCH_PANEL_RECEIPT_ROOT') or
                str(data.parent / 'research_panel_daily/receipts'))
            observations['daily_producer_root'] = str(producer.resolve())
            for lane in ('a', 'hk'):
                observations['producer/' + lane] = _dependency(producer, lane + '-' + business_date + '.json')
            for role, env, default in (
                ('close_review', 'V35_CLOSE_REVIEW_PATH', f'close_reviews/{business_date}.json'),
                ('close_review_receipt', 'V35_CLOSE_REVIEW_RECEIPT', f'receipts/close_reviews/{business_date}.json')):
                observations[role] = _dependency(data, os.environ.get(env) or default)
            selector_value = os.environ.get('V35_SELECTOR_DATA_ROOT')
            if selector_value:
                selector = Path(selector_value)
                observations['backtest_pointer'] = _read(selector, os.environ.get('V35_BACKTEST_POINTER') or
                    'backtest_panel_interface_current/CURRENT_BACKTEST_BASE_PANEL.txt')[0]
    app = Path(__file__).resolve().parents[2]
    code = {name: _read(app,name)[0] for name in _CODE_PATHS}
    return {'workload_id': workload_id, 'business_date': business_date, 'target_date': target_date,
        'slot': slot, 'code_identity': _hash(code), 'input_identity_sha256': _hash(observations),
        'observations': observations, 'pending_pool_ids': pending_pool_ids}


def make_input_wait(identity: dict, failure_code: str) -> dict:
    return {'schema_version':'v4.input_retry_wait.v1', **identity,
        'failure_code': failure_code, 'wait_for_input_change': True}


def input_wait_changed(wait: dict) -> bool:
    try:
        current = observe_input_identity(wait['workload_id'],wait['business_date'],wait['target_date'],wait['slot'],wait.get('pending_pool_ids'))
        return current is not None and (current['code_identity'] != wait['code_identity']
            or current['input_identity_sha256'] != wait['input_identity_sha256'])
    except (KeyError, ValueError, TypeError, OSError):
        return False
