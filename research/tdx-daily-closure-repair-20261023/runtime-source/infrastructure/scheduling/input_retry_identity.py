"""Observe fixed owned inputs for retry permission, never for source admission."""
from __future__ import annotations
import hashlib
import importlib.util
import time
import json
import os
import re
from pathlib import Path
from typing import Any

_WORKLOADS = frozenset({'preselection_pools', 'hourly_research', 'research_panel_runtime_evidence', 'research_panel_daily_a'})
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


def observe_input_identity(workload_id: str, business_date: str, target_date: str, slot: str, pending_pool_ids: list[str] | None = None, daily_source_refs: list[str] | None = None) -> dict | None:
    if workload_id not in _WORKLOADS or (workload_id == 'hourly_research' and slot in {'0700', '0800', '1530'}):
        return None
    if workload_id == 'research_panel_daily_a':
        return _observe_daily_identity(business_date, slot, daily_source_refs)
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
        current = observe_input_identity(wait['workload_id'],wait['business_date'],wait['target_date'],wait['slot'],wait.get('pending_pool_ids'), wait.get('daily_source_refs'))
        return current is not None and (current['code_identity'] != wait['code_identity']
            or current['input_identity_sha256'] != wait['input_identity_sha256'])
    except (KeyError, ValueError, TypeError, OSError):
        return False


_DAILY_CODE = ('ops/a_share_daily_sync.py', 'ops/macos_research_panel_daily.py',
    'ops/macos_research_panel_daily_authority.py', 'ops/macos_research_panel_daily_gate.py',
    'ops/macos_research_panel_daily_receipts.py', 'ops/_macos_research_panel_daily_parts/bounded_execution.py',
    'ops/_macos_research_panel_daily_parts/panel_primitives.py', 'ops/_macos_research_panel_daily_parts/cli.py',
    'infrastructure/scheduling/executor_registry_review.py',
    'infrastructure/scheduling/_executor_registry_parts/panel_execution.py',
    'infrastructure/scheduling/input_retry_identity.py')
_DAILY_FLAGS = ('production_allowed', 'buy_gate_updated', 'orders_sent')
_DAY_REFERENCE = re.compile(r'vipdoc/(sh|sz|bj)/lday/\1[0-9]{6}\.day')
# Native source rejection codes from the unchanged synchronizer contract.
# Every row must be recognized before one protocol row can grant a wait.
_DAILY_NATIVE_REASONS = frozenset({
    'EMPTY_RESPONSE', 'PROTOCOL_RESPONSE_MALFORMED', 'TARGET_DATE_MISSING',
    'DUPLICATE_DATE', 'NON_MONOTONIC_DATE', 'CROSS_DAY_CLOSE_RATIO',
    'OUT_OF_SCOPE_AFTER_TARGET_DATE', 'SOURCE_DATE_AFTER_TARGET', 'INVALID_BAR',
    'SOURCE_IDENTITY_CHANGED', 'KNOWN_MALFORMED_AMOUNT_VOLUME_SIGNATURE',
    'HOST_UNAVAILABLE', 'A_SYNC_TIMEOUT',
})


def _daily_config_input_identity(value):
    if not value:
        return {'state': 'UNCONFIGURED'}
    try:
        path = Path(value).expanduser()
        # Match the native owner's absolute, no-symlink input boundary.
        if (not path.is_absolute() or '..' in path.parts or path.resolve() != path
                or any(part.is_symlink() for part in (path, *path.parents))):
            raise ValueError('UNSAFE_CONFIG_INPUT')
        return _read(path.parent, path.name)[0]  # Existing 16 MiB cap; no recursive refs.
    except (OSError, ValueError, RuntimeError):
        return {'state': 'REJECTED_OWNED_PATH'}


def _daily_roots():
    receipt = os.environ.get('V35_RESEARCH_PANEL_A_RECEIPT_ROOT') or os.environ.get('V35_RESEARCH_PANEL_RECEIPT_ROOT')
    tdx = os.environ.get('V35_RESEARCH_PANEL_A_TDX_ROOT')
    if not receipt or not tdx:
        raise ValueError('DAILY_ROOT_MISSING')
    return Path(receipt), Path(tdx)


def _observe_daily_identity(date, slot, refs=None):
    if not re.fullmatch(r'\d{8}', date) or not re.fullmatch(r'\d{4}', slot):
        raise ValueError('INPUT_WAIT_DATE_SLOT_INVALID')
    refs = [] if refs is None else refs
    if (not isinstance(refs, list) or len(refs) > 2 or len(set(refs)) != len(refs)
            or any(not isinstance(ref, str) or not _DAY_REFERENCE.fullmatch(ref) for ref in refs)):
        raise ValueError('DAILY_REFERENCE_INVALID')
    try:
        receipt, tdx = _daily_roots()
    except ValueError:
        return None
    observations = {'receipt_root': str(receipt.resolve()), 'tdx_root': str(tdx.resolve())}
    # Reports, UUIDs, progress and logs are outputs, never retry permission.
    for ref in refs:
        observations[ref] = _read(tdx, ref)[0]
    app = Path(__file__).resolve().parents[2]
    code = {name: _read(app, name)[0] for name in _DAILY_CODE}
    script = os.environ.get('V35_RESEARCH_PANEL_A_SYNC_SCRIPT', '')
    script_path = Path(script)
    code['configured_sync'] = {'path': script, **(_read(script_path.parent, script_path.name)[0] if script else {'state': 'MISSING'})}
    # The child inherits this interpreter's import path. Resolve without importing
    # the SDK or calling any transport; hash only its fixed source components.
    spec = importlib.util.find_spec('pytdx')
    sdk = Path(spec.origin).parent if spec is not None and spec.origin else None
    code['sdk_root'] = str(sdk) if sdk else None
    if sdk is not None:
        for name in ('hq.py', 'base_socket_client.py', 'parser/base.py', 'parser/get_security_bars.py', 'config/hosts.py'):
            code['sdk/' + name] = _read(sdk, name)[0]
    for name in ('V35_A_SYNC_HOST', 'V35_RESEARCH_PANEL_A_SYNC_RUN_BUDGET_SECONDS',
                 'V35_A_SYNC_TRUSTED_CAS_INPUTS', 'V35_RESEARCH_PANEL_A_SYNC_SCRIPT'):
        observations[name] = os.environ.get(name)
    observations['trusted_cas_input_content'] = _daily_config_input_identity(
        os.environ.get('V35_A_SYNC_TRUSTED_CAS_INPUTS'))
    return {'workload_id': 'research_panel_daily_a', 'business_date': date, 'target_date': date,
        'slot': slot, 'code_identity': _hash(code), 'input_identity_sha256': _hash(observations),
        'observations': observations, 'daily_source_refs': refs}


def _daily_stat(root, relative):
    path = _path(root, relative)
    stat = path.stat()
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)


def begin_daily_attempt(date):
    """Cheap pre-child witness. Never read the potentially large source report."""
    witness = {'started_ns': time.time_ns()}
    try:
        root, _ = _daily_roots()
        for key, relative in (('summary', f'a_sync_authority/{date}/summary.json'), ('receipt', f'a-{date}.json')):
            try:
                witness[key] = _daily_stat(root, relative)
            except (OSError, ValueError):
                witness[key] = None
    except ValueError:
        pass
    return witness


def failed_daily_classification(payload, result, date, slot, witness):
    """Only a fresh same-child native zero-accepted protocol failure may wait.

    Classification is never admission. READY/PARTIAL validators remain at the
    caller; invalid/stale/unbound evidence is an explicit terminal UNKNOWN.
    """
    end_ns = time.time_ns()
    if result.get('failure_class') in {'SAFETY', 'UNKNOWN', 'NETWORK', 'EXTERNAL_SOURCE'}:
        return {'failure_class': result['failure_class']}
    if result.get('status') == 'TIMEOUT' or result.get('exception_type') in {'TimeoutExpired', 'TimeoutError', 'ConnectionError', 'ConnectionResetError', 'ConnectionRefusedError'}:
        return {'failure_class': 'NETWORK', 'failure_code': 'A_DAILY_TRANSIENT_NETWORK'}
    rejected = {'failure_class': 'UNKNOWN', 'failure_code': 'A_DAILY_FAILURE_EVIDENCE_UNVERIFIED'}
    try:
        receipt_root, tdx = _daily_roots()
        start_ns = witness['started_ns']
        if (payload.get('schema_version') != 'v3.macos.research_panel_authority_envelope.v1'
                or payload.get('target_date') != date
                or payload.get('requested_lane', payload.get('lane')) != 'A'
                or any(payload.get(k) is not False for k in _DAILY_FLAGS)):
            raise ValueError('ENVELOPE_IDENTITY_OR_SAFETY')
        lane = payload['lanes']['A']
        if not isinstance(lane, dict) or lane.get('status') != 'FAILED' or result.get('exit_code') != 1:
            raise ValueError('CHILD_FAILURE_NOT_BOUND')
        receipt_stat = _daily_stat(receipt_root, f'a-{date}.json')
        context = lane.get('native_failure')
        if not isinstance(context, dict) or context.get('schema_version') != 'v4.a_daily_native_failure.v1':
            raise ValueError('NATIVE_CHILD_CORRELATION_MISSING')
        summary_rel = context.get('summary_relative')
        if (context.get('target_date') != date or summary_rel not in {
                f'a_sync_authority/{date}/summary.json', 'a_sync_authority/summary.json'}):
            raise ValueError('NATIVE_CHILD_CORRELATION_INVALID')
        summary_stat = _daily_stat(receipt_root, summary_rel)
        for key, current in (('summary', summary_stat), ('receipt', receipt_stat)):
            if current == witness.get(key) or not start_ns <= current[3] <= end_ns:
                raise ValueError('STALE_' + key.upper())
        state, receipt = _json(receipt_root, f'a-{date}.json')
        if (receipt is None or receipt.get('schema_version') != 'v3.macos.research_panel_receipt.v1'
                or receipt.get('lane') != 'A' or receipt.get('target_date') != date
                or receipt.get('status') != 'FAILED' or receipt.get('exit_code') != 1
                or receipt.get('runner_called') is not True or receipt.get('receipt_written') is not True
                or receipt.get('exception_type') != 'SnapshotGateError'
                or receipt.get('error') not in {
                    'SnapshotGateError: A sync partial closure has no healthy accepted subset',
                    'A sync authority did not prove exact-date success: status=FAILED,exit_code=2'}
                or any(receipt.get(k) is not False for k in _DAILY_FLAGS)):
            raise ValueError('RECEIPT_IDENTITY_OR_SAFETY')
        if receipt.get('native_failure') != context:
            raise ValueError('CHILD_RECEIPT_CONTEXT_MISMATCH')
        for key in ('status', 'target_date', 'error', *_DAILY_FLAGS):
            if key in lane and lane.get(key) != receipt.get(key):
                raise ValueError('CHILD_RECEIPT_MISMATCH')
        if ('receipt_sha256' in lane or 'receipt_bytes' in lane) and (
                lane.get('receipt_sha256') != state.get('sha256') or lane.get('receipt_bytes') != receipt_stat[2]):
            raise ValueError('RECEIPT_SHA_MISMATCH')
        path = _path(receipt_root, summary_rel)
        # The diagnosed native summary is ~34 MiB. Bound the one postfailure
        # audit to 64 MiB; no scan or summary digest enters the due identity.
        if summary_stat[2] > 64 * 1024 * 1024:
            raise ValueError('NATIVE_SUMMARY_OVERSIZE')
        raw = path.read_bytes()
        summary_sha = hashlib.sha256(raw).hexdigest()
        if summary_sha != context.get('summary_sha256'):
            raise ValueError('NATIVE_CHILD_SUMMARY_SHA_MISMATCH')
        summary = json.loads(raw)
        if not isinstance(summary, dict):
            raise ValueError('NATIVE_SUMMARY_NOT_OBJECT')
        if _daily_stat(receipt_root, summary_rel) != summary_stat:
            raise ValueError('NATIVE_SUMMARY_CHANGED_DURING_AUDIT')
        if summary.get('run_id') != context.get('run_id'):
            raise ValueError('NATIVE_CHILD_RUN_MISMATCH')
        fingerprint = summary.get('target_fingerprint')
        run_id = summary.get('run_id')
        if (not isinstance(fingerprint, str) or not re.fullmatch(r'[0-9a-f]{64}', fingerprint)
                or not isinstance(run_id, str)
                or not re.fullmatch(date + '-' + fingerprint[:16] + r'-[0-9]{19}', run_id)
                or not start_ns <= int(run_id.rsplit('-', 1)[1]) <= summary_stat[3]):
            raise ValueError('NATIVE_RUN_MISMATCH')
        if (summary.get('task_name') != 'tdxpy_daily_vipdoc_sync_v1'
                or summary.get('target_date') != date or summary.get('status') != 'FAILED'
                or summary.get('exit_code') != 2 or summary.get('authority_status') != 'FAILED'
                or any(summary.get(k) is not False for k in (*_DAILY_FLAGS, 'timeout', 'interrupted', 'dry_run'))
                or summary.get('RESEARCH_ONLY') is not True
                or summary.get('accepted_count') != 0 or summary.get('accepted_target_date_file_count') != 0
                or summary.get('pending_count') != 0 or summary.get('coverage_rate') != 0
                or summary.get('rule_id') != 'A-FI-SYNC-001' or summary.get('rule_version') != '1'
                or summary.get('field_rule_id') != 'A-FI-SYNC-001.FIELD_SIGNATURE' or summary.get('field_rule_version') != '1'
                or Path(summary.get('tdx_root', '')).resolve() != tdx.resolve()
                or Path(summary.get('run_dir', '')).resolve() != path.parent.resolve()):
            raise ValueError('NATIVE_IDENTITY_OR_SAFETY')
        rows = summary.get('by_symbol')
        count = summary.get('target_count')
        if (not isinstance(rows, dict) or not isinstance(count, int) or isinstance(count, bool)
                or count <= 0 or count > 10000 or len(rows) != count
                or summary.get('quarantine_count') != count):
            raise ValueError('NATIVE_COUNTS')
        selected = {}
        for symbol, row in rows.items():
            if not isinstance(row, dict) or row.get('run_id') != run_id:
                raise ValueError('NATIVE_ROW_RUN_MISMATCH')
            reason = row.get('reason_code')
            if (reason not in _DAILY_NATIVE_REASONS
                    or row.get('failure_class') in {'UNKNOWN', 'SAFETY'}
                    or any(row.get(flag) is not False for flag in _DAILY_FLAGS if flag in row)):
                raise ValueError('NATIVE_ROW_FAILURE_CONTRACT_UNKNOWN')
            if reason in {'PROTOCOL_RESPONSE_MALFORMED', 'HOST_UNAVAILABLE'} and reason not in selected:
                selected[reason] = (symbol, row)
        if 'PROTOCOL_RESPONSE_MALFORMED' not in selected:
            raise ValueError('NO_PROTOCOL_EVIDENCE')
        refs = []
        for symbol, row in selected.values():
            market = row.get('market')
            prefix = {0: 'sz', 1: 'sh', 2: 'bj'}.get(market)
            relative = f'vipdoc/{prefix}/lday/{prefix}{symbol}.day'
            if (not re.fullmatch(r'[0-9]{6}', symbol) or row.get('symbol') != symbol
                    or not _DAY_REFERENCE.fullmatch(relative)
                    or row.get('classification') != 'QUARANTINED' or row.get('quarantine') is not True
                    or row.get('target_date_ready') is not False or row.get('status') != 'FAILED'
                    or row.get('fetch_status') != 'REBUILD_REQUIRED'
                    or _path(tdx, row.get('path', '')) != tdx / relative):
                raise ValueError('NATIVE_REFERENCE_INVALID')
            observation, _ = _read(tdx, relative)
            expected = row.get('source_sha256_after')
            if (not isinstance(expected, str) or not re.fullmatch(r'[0-9a-f]{64}', expected)
                    or expected != row.get('source_sha256_before') or observation.get('sha256') != expected):
                raise ValueError('NATIVE_REFERENCE_SHA_MISMATCH')
            refs.append(relative)
        identity = _observe_daily_identity(date, slot, sorted(refs))
        return {'failure_class': 'INVALID_INPUT', 'failure_code': 'A_DAILY_PROTOCOL_SOURCE_REJECTED',
            'input_wait': make_input_wait(identity, 'A_DAILY_PROTOCOL_SOURCE_REJECTED'),
            'daily_failure_evidence': {'native_summary_sha256': summary_sha, 'native_run_id': run_id,
                'target_date': date, 'receipt_sha256': state['sha256'], 'audit_count': 1}}
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, UnicodeError) as error:
        return {**rejected, 'daily_failure_evidence_error': str(error)[:180]}



def bind_native_daily_failure(error, reported):
    """Attach only this producer return object's identity, never a latest read.

    The existing native writer uses this exact JSON encoding. The caller checks
    these bytes against the owned report. Concurrent replacements fail closed.
    """
    run_dir = Path(str(reported.get('run_dir') or ''))
    date = str(reported.get('target_date') or '')
    relative = ('a_sync_authority/' + date + '/summary.json'
        if run_dir.name == date else 'a_sync_authority/summary.json')
    context = {'schema_version': 'v4.a_daily_native_failure.v1',
        'target_date': date, 'run_id': reported.get('run_id'), 'summary_relative': relative,
        'summary_sha256': hashlib.sha256(json.dumps(reported, ensure_ascii=False,
            indent=2, default=str).encode('utf-8')).hexdigest()}
    error.result = {'error': type(error).__name__ + ': ' + str(error), 'native_failure': context}
