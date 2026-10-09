"""Evidence-gated independent research selection from a committed observation.

Deployment, not an HTTP/CLI request, supplies the policy path and its pinned
digest. An approved owner attestation maps source bytes to every required
panel cell. This reader checks those bindings; it is not a provider decoder,
signature service, panel publisher, or the complete original master owner.
"""
import copy
from datetime import datetime, timezone
import hashlib
import math
import os
from pathlib import Path
import re
import sys
import tempfile
import types
import uuid

from . import rebound_observation as observation
from . import rebound_owner as owner
from .composition import no_symlinks
from .contracts import aware, exact_keys, sha, trade_date
from .digests import canonical_bytes, sha256_json
from .module_api import _open_directory, _read_regular
from .source_capsule import checked_path

SCHEMA = 'v5.rebound_admitted_research_selection.v1'
SAFETY = dict(research_only=True, production_allowed=False, buy_gate_updated=False,
              orders_sent=False, natural_verified=False, full_master_owner_verified=False,
              collection_performed=False, panel_published=False)
_TOKEN = object()
_POLICY_FIELDS = ('schema_version', 'policy_id', 'evidence_root', 'owner_identity',
                  'membership_owner_identity', 'observation_implementation_sha256',
                  'admission_implementation_sha256', 'source_capsule_sha256', 'source_contracts',
                  'attestations', 'memberships')
_IDENTITY_FIELDS = ('owner_id', 'owner_source_sha256', 'reviewer_id')


def implementation_sha256():
    """Digest to pin in deployment after code review and Mac acceptance."""
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _code(value):
    if not isinstance(value, str) or not re.fullmatch(r'HK\.\d{5}', value):
        raise ValueError('ADMISSION_CODE')
    return value


def _number(value, *, positive=False):
    if (type(value) not in (int, float) or not math.isfinite(value)
            or (value <= 0 if positive else value < 0)):
        raise ValueError('ADMISSION_CELL_VALUE')
    return value


def _bound(root, relative, expected, limit=64 * 1024**2):
    sha(expected)
    path = checked_path(root, relative)
    directory = _open_directory(path.parent)
    try: fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    finally: os.close(directory)
    try: raw = _read_regular(fd, limit)
    finally: os.close(fd)
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError('ADMISSION_BOUND_FILE_CHANGED')
    return raw


def _json(raw):
    value = owner._json(raw)
    canonical_bytes(value)  # reject NaN/Infinity even in unused metadata
    return value


def _identity(value):
    exact_keys(value, _IDENTITY_FIELDS)
    sha(value['owner_source_sha256'])
    if any(not isinstance(value[k], str) or not value[k].strip() for k in ('owner_id', 'reviewer_id')):
        raise ValueError('ADMISSION_OWNER_IDENTITY')


def _policy(value):
    exact_keys(value, _POLICY_FIELDS)
    if value['schema_version'] != 'v5.rebound_deployment_trust.v1':
        raise ValueError('ADMISSION_TRUST_SCHEMA')
    if not isinstance(value['policy_id'], str) or not value['policy_id'].strip():
        raise ValueError('ADMISSION_POLICY_ID')
    root = no_symlinks(value['evidence_root'])
    if not root.is_dir(): raise ValueError('ADMISSION_EVIDENCE_ROOT')
    _identity(value['owner_identity']); _identity(value['membership_owner_identity'])
    sha(value['observation_implementation_sha256']); sha(value['source_capsule_sha256'])
    sha(value['admission_implementation_sha256'])
    contracts = value['source_contracts']
    if not isinstance(contracts, dict) or not 1 <= len(contracts) <= 32:
        raise ValueError('ADMISSION_SOURCE_CONTRACTS')
    for key, contract in contracts.items():
        if not isinstance(key, str) or not key: raise ValueError('ADMISSION_SOURCE_CONTRACT_ID')
        exact_keys(contract, ('owner_source_sha256', 'decoder_sha256', 'document',
                              'price_basis', 'price_currency', 'price_scale', 'volume_unit',
                              'volume_scale', 'finality_rule', 'field_bindings'))
        sha(contract['owner_source_sha256']); sha(contract['decoder_sha256'])
        exact_keys(contract['document'], ('relative', 'sha256'))
        checked_path(root, contract['document']['relative']); sha(contract['document']['sha256'])
        if (contract['price_basis'] not in ('RAW', 'UNADJUSTED')
                or contract['price_currency'] != 'HKD'
                or contract['volume_unit'] not in ('SHARES', 'LOTS')
                or contract['finality_rule'] != 'DAILY_BARS_CAPTURE_AFTER_NATIVE_CLOSE'):
            raise ValueError('ADMISSION_DAILY_SEMANTICS')
        _number(contract['price_scale'], positive=True); _number(contract['volume_scale'], positive=True)
        fields = contract['field_bindings']
        if not isinstance(fields, dict) or not fields or set(fields) - {'high', 'close', 'trade'}:
            raise ValueError('ADMISSION_NATIVE_FIELD_SCOPE')
        for binding in fields.values():
            exact_keys(binding, ('native_field', 'storage_type', 'storage_locator',
                                 'conversion_basis', 'adjustment_basis'))
            if any(not isinstance(item, str) or not 1 <= len(item.strip()) <= 1024
                   or item.strip().upper() in ('UNKNOWN', 'NOT_PROVEN', 'UNVERIFIED', 'NONE', 'NULL')
                   for item in binding.values()):
                raise ValueError('ADMISSION_NATIVE_FIELD_CONTRACT')
    for field in ('attestations', 'memberships'):
        entries = value[field]
        if not isinstance(entries, dict) or not 1 <= len(entries) <= 1024:
            raise ValueError('ADMISSION_APPROVAL_LIST')
        for key, reference in entries.items():
            if not isinstance(key, str) or not key: raise ValueError('ADMISSION_APPROVAL_ID')
            exact_keys(reference, ('relative', 'sha256'))
            checked_path(root, reference['relative']); sha(reference['sha256'])
    return value


class DeploymentAuthority:
    """Capability created by trusted deployment wiring, never request JSON.

    Python callers controlling deployment pins are trusted administrators.
    A same-process adversary can replace Python functions; this is not a
    cryptographic defense against such an adversary or a compromised owner.
    """
    __slots__ = ('_path', '_digest')

    def __init__(self, path, digest, token=None):
        if token is not _TOKEN: raise ValueError('ADMISSION_DEPLOYMENT_CAPABILITY_REQUIRED')
        self._path, self._digest = path, digest

    def _load(self):
        return _policy(_json(_bound(self._path.parent, self._path.name, self._digest, 4 * 1024**2)))


def load_deployment_authority(policy_path, *, expected_policy_sha256):
    """Call once from original-owner deployment configuration, not request args.

    The expected SHA must live outside the evidence/request writer's control.
    No environment fallback, request-selected policy, self-signing or CLI exists.
    """
    path = no_symlinks(policy_path); sha(expected_policy_sha256)
    capability = DeploymentAuthority(path, expected_policy_sha256, _TOKEN)
    capability._load()
    return capability


def _approved(policy, section, key):
    try: reference = policy[section][key]
    except (KeyError, TypeError) as error: raise ValueError('ADMISSION_EVIDENCE_NOT_DEPLOYMENT_APPROVED') from error
    raw = _bound(Path(policy['evidence_root']), reference['relative'], reference['sha256'])
    return _json(raw), reference['sha256']


def _calendar():
    """Load the unchanged pinned native calendar implementation and bytes."""
    descriptor, sources = observation._capsule()
    prefix = 'vendor/rebound_baseline/contracts/'
    source = observation.BASE / (prefix + 'trading_calendar.py')
    calendar_path = observation.BASE / (prefix + 'market_calendar_2026.json')
    # Python source is pinned by rebound_source_manifest through _sources();
    # observation descriptor binds calendar JSON, not trading_calendar.py.
    raw = sources['contracts/trading_calendar.py']
    calendar_raw = _bound(calendar_path.parent, calendar_path.name, descriptor['bindings'][prefix + calendar_path.name])
    name = '_v5_rebound_admission_calendar_' + uuid.uuid4().hex
    module = types.ModuleType(name); module.__file__ = str(source)
    sys.modules[name] = module
    try:
        exec(compile(raw, str(source), 'exec'), module.__dict__)
        calendar = module.load_market_calendar(calendar_path)
    finally:
        sys.modules.pop(name, None)
    if calendar_path.read_bytes() != calendar_raw:
        raise ValueError('ADMISSION_CALENDAR_CHANGED')
    return module, calendar, hashlib.sha256(calendar_raw).hexdigest()


def _session_close(day, module, calendar, *, full=False):
    trade_date(day)
    state = module.resolve_market_states(calendar, day)['hk_securities']
    if state == module.TradingDayState.FULL_TRADING_DAY:
        field = 'full_day_close'
    elif not full and state == module.TradingDayState.HALF_TRADING_DAY_AM:
        field = 'half_day_close'
    else:
        raise ValueError('ADMISSION_NOT_COMPLETED_SESSION_KIND')
    hhmm = calendar.markets['hk_securities'][field]
    return datetime.strptime(day + hhmm, '%Y%m%d%H%M').replace(tzinfo=observation.HK)


def _windows(artifact, module, calendar, calendar_sha):
    history = artifact['history_sessions']; signal = artifact['request']['signal_date']
    cursor, days60, days5 = signal, [], []
    while len(days60) < 60 or len(days5) < 5:
        cursor = module.previous_session(calendar, cursor, market='hk_securities')
        if len(days60) < 60: days60.append(cursor)
        if module.resolve_market_states(calendar, cursor)['hk_securities'] == module.TradingDayState.FULL_TRADING_DAY and len(days5) < 5:
            days5.append(cursor)
    if (history['prior60'] != sorted(days60) or history['previous5'] != sorted(days5)
            or history['calendar_sha256'] != calendar_sha):
        raise ValueError('ADMISSION_EXACT_CALENDAR_WINDOWS')
    _session_close(signal, module, calendar, full=True)


def _attestation(value, artifact, reference, policy, now):
    exact_keys(value, ('schema_version', 'owner_identity', 'reviewed_at', 'observation_reference',
                      'target_date', 'signal_date', 'research_cutoff', 'panel_sha256',
                      'panel_manifest_sha256', 'calendar_sha256', 'raw_sources', 'codes'))
    if (value['schema_version'] != 'v5.rebound_owner_cell_attestation.v1'
            or value['owner_identity'] != policy['owner_identity']
            or value['observation_reference'] != reference
            or value['target_date'] != artifact['request']['target_date']
            or value['signal_date'] != artifact['request']['signal_date']
            or aware(value['research_cutoff']) != aware(artifact['observed_at'])
            or any(value[key] != artifact['source_identity'][key] for key in
                   ('panel_sha256', 'panel_manifest_sha256', 'calendar_sha256'))
            or not aware(artifact['finished_at']) <= aware(value['reviewed_at']) <= now):
        raise ValueError('ADMISSION_ATTESTATION_BINDING')
    if not isinstance(value['codes'], dict) or len(value['codes']) > 2000:
        raise ValueError('ADMISSION_CODE_SCOPE')
    for code in value['codes']: _code(code)
    sources = value['raw_sources']
    if not isinstance(sources, dict) or not 1 <= len(sources) <= 4096:
        raise ValueError('ADMISSION_RAW_SCOPE')
    total = 0
    for key, source in sources.items():
        if not isinstance(key, str) or not key: raise ValueError('ADMISSION_RAW_ID')
        exact_keys(source, ('relative', 'sha256', 'source_contract_id', 'owner_source_sha256',
                            'decoder_sha256', 'capture_started_at', 'captured_at', 'available_at'))
        contract = policy['source_contracts'].get(source['source_contract_id'])
        if (contract is None or source['owner_source_sha256'] != contract['owner_source_sha256']
                or source['decoder_sha256'] != contract['decoder_sha256']):
            raise ValueError('ADMISSION_RAW_SOURCE_CONTRACT')
        if not aware(source['capture_started_at']) <= aware(source['captured_at']) <= aware(source['available_at']) <= aware(value['research_cutoff']):
            raise ValueError('ADMISSION_RAW_AVAILABILITY')
        total += len(_bound(Path(policy['evidence_root']), source['relative'], source['sha256']))
        if total > 256 * 1024**2: raise ValueError('ADMISSION_RAW_TOTAL_BYTES')
    for contract in policy['source_contracts'].values():
        _bound(Path(policy['evidence_root']), contract['document']['relative'], contract['document']['sha256'], 4 * 1024**2)


def _membership(value, artifact, policy, now):
    exact_keys(value, ('schema_version', 'owner_identity', 'target_date', 'capture_started_at',
                      'captured_at', 'available_at', 'reviewed_at', 'codes', 'codes_sha256', 'raw_source'))
    if (value['schema_version'] != 'v5.rebound_target_membership_attestation.v1'
            or value['owner_identity'] != policy['membership_owner_identity']
            or value['target_date'] != artifact['request']['target_date']):
        raise ValueError('ADMISSION_MEMBERSHIP_BINDING')
    captured = aware(value['captured_at']); cutoff = aware(artifact['observed_at'])
    if (captured.astimezone(observation.HK).strftime('%Y%m%d') != value['target_date']
            or not aware(value['capture_started_at']) <= captured <= aware(value['available_at']) <= cutoff
            or not aware(value['available_at']) <= aware(value['reviewed_at']) <= now):
        raise ValueError('ADMISSION_MEMBERSHIP_AVAILABILITY')
    codes = value['codes']
    if (not isinstance(codes, list) or not 1 <= len(codes) <= 2000
            or any(_code(code) != code for code in codes)
            or codes != sorted(set(codes)) or sha256_json(codes) != value['codes_sha256']):
        raise ValueError('ADMISSION_MEMBERSHIP_CODES')
    exact_keys(value['raw_source'], ('relative', 'sha256'))
    _bound(Path(policy['evidence_root']), value['raw_source']['relative'], value['raw_source']['sha256'])
    return codes


def _panel_cells(artifact):
    """Private SHA-bound input copy; no rewrite or second authority panel."""
    import pandas as pd
    request = artifact['request']
    with tempfile.TemporaryDirectory(prefix='v5-rebound-admission-') as temporary:
        private = Path(temporary).resolve() / 'inputs'
        snapshot = observation.prepare_snapshot(request, private, artifact['observed_at'])
        frame = pd.read_parquet(checked_path(private, request['paths']['panel']),
                                columns=['code_norm', 'trade_date_compact', 'high', 'close', 'trade'])
        owner._verify_private(private, snapshot)
    frame['code_norm'] = frame['code_norm'].astype(str).str.upper()
    frame['trade_date_compact'] = frame['trade_date_compact'].astype(str).str.zfill(8)
    wanted = {*artifact['history_sessions']['prior60'], request['signal_date']}
    rows = {}
    for item in frame.loc[frame['trade_date_compact'].isin(wanted)].to_dict('records'):
        rows.setdefault((item['code_norm'], item['trade_date_compact']), []).append(item)
    return rows


def _proof(code, proof, row, artifact, attestation, policy, panel, module, calendar):
    exact_keys(proof, ('cells',))
    prior = artifact['history_sessions']['prior60']; five = artifact['history_sessions']['previous5']
    signal = artifact['request']['signal_date']
    required = {(day, 'high') for day in prior} | {(signal, 'close')} | {(day, 'trade') for day in [*five, signal]}
    cells = proof['cells']
    if not isinstance(cells, list) or len(cells) != len(required): raise ValueError('ADMISSION_ALL_67_CELLS_REQUIRED')
    found, semantics = {}, {'price': set(), 'volume': set()}
    for cell in cells:
        exact_keys(cell, ('date', 'field', 'value', 'raw_source_id', 'raw_locator'))
        key = (trade_date(cell['date']), cell['field'])
        if key not in required or key in found: raise ValueError('ADMISSION_CELL_SCOPE_OR_DUPLICATE')
        if not isinstance(cell['raw_locator'], str) or not 1 <= len(cell['raw_locator']) <= 512:
            raise ValueError('ADMISSION_RAW_LOCATOR')
        native = _number(cell['value'], positive=cell['field'] != 'trade')
        records = panel.get((code, cell['date']), [])
        if len(records) != 1 or native != _number(records[0][cell['field']], positive=cell['field'] != 'trade'):
            raise ValueError('ADMISSION_CELL_PANEL_MISMATCH')
        try: raw = attestation['raw_sources'][cell['raw_source_id']]
        except (KeyError, TypeError) as error: raise ValueError('ADMISSION_CELL_RAW_SOURCE') from error
        contract = policy['source_contracts'][raw['source_contract_id']]
        if cell['field'] not in contract['field_bindings']:
            raise ValueError('ADMISSION_CELL_DECODING_CONTRACT')
        close = _session_close(cell['date'], module, calendar, full=cell['field'] == 'trade' or cell['date'] == signal)
        if aware(raw['capture_started_at']) < close:
            raise ValueError('ADMISSION_RAW_CAPTURE_BEFORE_SESSION_CLOSE')
        if cell['field'] == 'trade':
            semantics['volume'].add((contract['volume_unit'], contract['volume_scale']))
        else:
            semantics['price'].add((contract['price_basis'], contract['price_currency'], contract['price_scale']))
        found[key] = native
    if len(semantics['price']) != 1 or len(semantics['volume']) != 1:
        raise ValueError('ADMISSION_HISTORY_SCALE_OR_UNIT_MISMATCH')
    # Check identity of core values; original frozen booleans remain the only
    # decision inputs. Do not implement another threshold or threshold epsilon.
    numbers = row['native_numbers']
    import pandas as pd
    mean = float(pd.Series([found[(day, 'trade')] for day in five]).mean())
    expected = dict(close_native=found[(signal, 'close')], current_volume_native=found[(signal, 'trade')],
                    prior60_high_native=max(found[(day, 'high')] for day in prior), previous5_mean_volume_native=mean)
    if mean <= 0 or any(numbers.get(key) != value for key, value in expected.items()):
        raise ValueError('ADMISSION_OBSERVATION_CORE_VALUES')
    return dict(status='OWNER_VERIFIED', scope='ONE_CODE_EXACT_60_PRICE_AND_SIX_VOLUME_SESSIONS',
                price_basis=next(iter(semantics['price']))[0], price_currency='HKD',
                price_scale=next(iter(semantics['price']))[2], volume_unit=next(iter(semantics['volume']))[0],
                volume_scale=next(iter(semantics['volume']))[1], verified_cell_count=len(found),
                finality_basis='DEPLOYMENT_APPROVED_DAILY_CONTRACT_AND_ACTUAL_POST_CLOSE_CAPTURE')


def admit_rebound_observation(observation_root, reference, *, authority, attestation_id, membership_id):
    """Read-only API. The two IDs select entries in deployment's pinned lists.

    Invalid global trust/bindings raise ValueError. Missing or invalid per-code
    proofs remain pending and cannot attest any other code. A valid empty screen
    is READY only when every target member is fully accounted for.
    """
    if type(authority) is not DeploymentAuthority:
        raise ValueError('ADMISSION_DEPLOYMENT_CAPABILITY_REQUIRED')
    started = datetime.now(timezone.utc)
    policy = authority._load()
    implementation = implementation_sha256()
    if policy['admission_implementation_sha256'] != implementation:
        raise ValueError('ADMISSION_DEPLOYED_IMPLEMENTATION_BINDING')
    artifact = observation.read_rebound_observation(observation_root, reference)
    if (artifact['request']['data_kind'] != 'RECORDED_INPUT_CURRENT'
            or artifact['computation_status'] != 'NATIVE_VALUES_OBSERVED'
            or artifact['request']['target_date'] != started.astimezone(observation.HK).strftime('%Y%m%d')
            or aware(artifact['finished_at']) > started):
        raise ValueError('ADMISSION_CURRENT_COMMITTED_OBSERVATION_REQUIRED')
    if (policy['source_capsule_sha256'] != artifact['source_capsule_sha256']
            or policy['observation_implementation_sha256'] != sha256_json(artifact['implementation_identity'])
            or artifact['implementation_identity'] != observation._identity()):
        raise ValueError('ADMISSION_OBSERVATION_IMPLEMENTATION_BINDING')
    dependencies = owner.observe_dependencies(owner.BASE / 'uv.lock')
    if dependencies.get('status') != 'MATCH' or dependencies != artifact['dependencies']:
        raise ValueError('ADMISSION_DEPENDENCY_BINDING')
    module, calendar, calendar_sha = _calendar(); _windows(artifact, module, calendar, calendar_sha)
    attestation, attestation_sha = _approved(policy, 'attestations', attestation_id)
    membership, membership_sha = _approved(policy, 'memberships', membership_id)
    _attestation(attestation, artifact, reference, policy, started)
    members = _membership(membership, artifact, policy, started)
    panel = _panel_cells(artifact)
    by_code = {row['code']: row for row in artifact['rows']}
    groups = dict(strict=[], near=[], excluded=[], pending=[])
    for code in members:
        row = by_code.get(code)
        reasons = []
        if row is None: reasons.append('TARGET_MEMBER_SIGNAL_ROW_MISSING')
        elif row['numeric_input_status'] != 'KNOWN': reasons.extend(['NUMERIC_INPUT_INCOMPLETE', *row['input_gaps']])
        proof = attestation['codes'].get(code)
        if proof is None: reasons.append('OWNER_CODE_EVIDENCE_MISSING')
        evidence = None
        if row is not None and proof is not None and not reasons:
            try: evidence = _proof(code, proof, row, artifact, attestation, policy, panel, module, calendar)
            except (ValueError, KeyError, TypeError, OverflowError) as error:
                reason = str(error)
                reasons.append(reason if re.fullmatch(r'ADMISSION_[A-Z0-9_]+', reason) else 'ADMISSION_CODE_EVIDENCE_INVALID')
        if reasons:
            groups['pending'].append(dict(code=code, reason_codes=sorted(set(reasons))))
            continue
        values = row['native_comparisons']
        # Grouping of the unchanged two booleans is the original strict/near
        # contract. Do not carry the original misleading HKD/VERIFIED labels.
        passed = sum(value is True for value in values.values())
        group = ('excluded', 'near', 'strict')[passed]
        groups[group].append(dict(code=code, name=row['name'], name_source=row['name_source'],
            native_comparisons=copy.deepcopy(values), core_values={key: row['native_numbers'][key] for key in
                ('close_native', 'prior60_high_native', 'current_volume_native', 'previous5_mean_volume_native')},
            evidence=evidence, evidence_admission_status='ADMITTED_INDEPENDENT_RESEARCH_INPUTS', selection_group=group,
            reason_code=('BOTH_ORIGINAL_GATES_FAILED', 'ONE_ORIGINAL_GATE_PASSED', 'BOTH_ORIGINAL_GATES_PASSED')[passed]))
    # Revalidate independently pinned approval/source bytes before returning.
    if authority._load() != policy: raise ValueError('ADMISSION_POLICY_CHANGED')
    if _approved(policy, 'attestations', attestation_id)[1] != attestation_sha or _approved(policy, 'memberships', membership_id)[1] != membership_sha:
        raise ValueError('ADMISSION_APPROVAL_CHANGED')
    _attestation(attestation, artifact, reference, policy, datetime.now(timezone.utc))
    _membership(membership, artifact, policy, datetime.now(timezone.utc))
    observation.read_rebound_observation(observation_root, reference)
    if (implementation_sha256() != implementation or observation._identity() != artifact['implementation_identity']
            or owner.observe_dependencies(owner.BASE / 'uv.lock') != dependencies):
        raise ValueError('ADMISSION_RUNTIME_CHANGED')
    completed = datetime.now(timezone.utc)
    if completed < started or completed.astimezone(observation.HK).strftime('%Y%m%d') != artifact['request']['target_date']:
        raise ValueError('ADMISSION_ACTUAL_CLOCK_CHANGED')
    status = 'PARTIAL' if groups['pending'] else 'READY'
    result = dict(schema_version=SCHEMA, status=status, selection_kind='INDEPENDENT_RESEARCH_TWO_GATE_SELECTION',
        target_date=artifact['request']['target_date'], signal_date=artifact['request']['signal_date'],
        research_cutoff=artifact['observed_at'], evaluated_at=completed.isoformat(),
        source_reference=copy.deepcopy(reference), policy_id=policy['policy_id'], policy_sha256=authority._digest,
        implementation_sha256=implementation,
        attestation_sha256=attestation_sha, membership_sha256=membership_sha,
        membership_captured_at=membership['captured_at'], membership_timing='AS_OF_TARGET_CAPTURE_NOT_PREOPEN_ATTESTATION',
        panel_sha256=artifact['source_identity']['panel_sha256'], calendar_sha256=calendar_sha,
        counts=dict(target_members=len(members), **{key: len(rows) for key, rows in groups.items()}),
        outside_target_membership=sorted(set(by_code) - set(members)), **groups, **SAFETY)
    return dict(result, selection_sha256=sha256_json(result))


def manager_admitted_selection(selection, *, target_date, signal_date, research_cutoff):
    """Validate a selection AFTER the existing ledger's trusted readback.

    The digest detects content changes; it is not an owner signature. Callers
    must not pass request-supplied JSON instead of the ledger-owned artifact.
    No source proof is regenerated, clock backdated, or business state written.
    """
    value = copy.deepcopy(selection)
    groups = ('strict', 'near', 'excluded', 'pending')
    exact_keys(value, ('schema_version', 'status', 'selection_kind', 'target_date',
        'signal_date', 'research_cutoff', 'evaluated_at', 'source_reference', 'policy_id',
        'policy_sha256', 'implementation_sha256', 'attestation_sha256', 'membership_sha256',
        'membership_captured_at', 'membership_timing', 'panel_sha256', 'calendar_sha256',
        'counts', 'outside_target_membership', 'selection_sha256', *groups, *SAFETY))
    if (value['schema_version'] != SCHEMA
            or value['selection_kind'] != 'INDEPENDENT_RESEARCH_TWO_GATE_SELECTION'
            or any(value[key] is not expected for key, expected in SAFETY.items())):
        raise ValueError('ADMISSION_MANAGER_SCHEMA_OR_SAFETY')
    digest = sha(value['selection_sha256'])
    if digest != sha256_json({key: item for key, item in value.items() if key != 'selection_sha256'}):
        raise ValueError('ADMISSION_MANAGER_SELECTION_SHA')
    target = trade_date(target_date); signal = trade_date(signal_date)
    cutoff = aware(research_cutoff); observed = aware(value['research_cutoff'])
    evaluated = aware(value['evaluated_at']); captured = aware(value['membership_captured_at'])
    if (value['target_date'] != target or value['signal_date'] != signal or signal > target
            or any(moment.astimezone(observation.HK).strftime('%Y%m%d') != target
                   for moment in (cutoff, observed, evaluated, captured))):
        raise ValueError('ADMISSION_MANAGER_DATE_MISMATCH')
    if not captured <= observed <= evaluated <= cutoff:
        raise ValueError('ADMISSION_MANAGER_AFTER_CUTOFF')
    if (value['membership_timing'] != 'AS_OF_TARGET_CAPTURE_NOT_PREOPEN_ATTESTATION'
            or not isinstance(value['policy_id'], str) or not value['policy_id'].strip()):
        raise ValueError('ADMISSION_MANAGER_PROVENANCE')
    for key in ('policy_sha256', 'implementation_sha256', 'attestation_sha256',
                'membership_sha256', 'panel_sha256', 'calendar_sha256'):
        sha(value[key])
    reference = value['source_reference']
    exact_keys(reference, ('run_id', 'artifact_sha256', 'manifest_sha256', 'receipt_sha256'))
    if not isinstance(reference['run_id'], str) or not re.fullmatch(r'[0-9a-f]{32}', reference['run_id']):
        raise ValueError('ADMISSION_MANAGER_SOURCE_REFERENCE')
    for key in ('artifact_sha256', 'manifest_sha256', 'receipt_sha256'): sha(reference[key])
    counts = value['counts']; exact_keys(counts, ('target_members', *groups))
    if (any(type(counts[key]) is not int or counts[key] < 0 for key in counts)
            or not 1 <= counts['target_members'] <= 2000):
        raise ValueError('ADMISSION_MANAGER_COUNTS')
    seen = set()
    for group in groups:
        rows = value[group]
        if not isinstance(rows, list) or len(rows) != counts[group]:
            raise ValueError('ADMISSION_MANAGER_COUNTS')
        for row in rows:
            code = _code(row.get('code')) if isinstance(row, dict) else _code(None)
            if code in seen: raise ValueError('ADMISSION_MANAGER_CODE_OVERLAP')
            seen.add(code)
            if group == 'pending':
                exact_keys(row, ('code', 'reason_codes'))
                reasons = row['reason_codes']
                if (not isinstance(reasons, list) or not reasons
                        or any(not isinstance(reason, str) or not reason for reason in reasons)
                        or reasons != sorted(set(reasons))):
                    raise ValueError('ADMISSION_MANAGER_PENDING_REASON')
                continue
            exact_keys(row, ('code', 'name', 'name_source', 'native_comparisons', 'core_values',
                'evidence', 'evidence_admission_status', 'selection_group', 'reason_code'))
            comparisons = row['native_comparisons']
            exact_keys(comparisons, ('close_le_prior60_high_times_0_8', 'current_to_previous5_ge_1_5'))
            if any(type(item) is not bool for item in comparisons.values()):
                raise ValueError('ADMISSION_MANAGER_COMPARISONS')
            passed = sum(comparisons.values())
            if (('excluded', 'near', 'strict')[passed] != group or row['selection_group'] != group
                    or row['evidence_admission_status'] != 'ADMITTED_INDEPENDENT_RESEARCH_INPUTS'
                    or row['reason_code'] != ('BOTH_ORIGINAL_GATES_FAILED', 'ONE_ORIGINAL_GATE_PASSED',
                                              'BOTH_ORIGINAL_GATES_PASSED')[passed]
                    or any(not isinstance(row[key], str) for key in ('name', 'name_source'))):
                raise ValueError('ADMISSION_MANAGER_GROUP')
            numbers = row['core_values']
            exact_keys(numbers, ('close_native', 'prior60_high_native', 'current_volume_native', 'previous5_mean_volume_native'))
            for key, number in numbers.items(): _number(number, positive=key != 'current_volume_native')
            evidence = row['evidence']
            exact_keys(evidence, ('status', 'scope', 'price_basis', 'price_currency', 'price_scale', 'volume_unit',
                                 'volume_scale', 'verified_cell_count', 'finality_basis'))
            if (evidence['status'] != 'OWNER_VERIFIED'
                    or evidence['scope'] != 'ONE_CODE_EXACT_60_PRICE_AND_SIX_VOLUME_SESSIONS'
                    or evidence['price_basis'] not in ('RAW', 'UNADJUSTED') or evidence['price_currency'] != 'HKD'
                    or evidence['volume_unit'] not in ('SHARES', 'LOTS')
                    or type(evidence['verified_cell_count']) is not int or evidence['verified_cell_count'] != 67
                    or evidence['finality_basis'] != 'DEPLOYMENT_APPROVED_DAILY_CONTRACT_AND_ACTUAL_POST_CLOSE_CAPTURE'):
                raise ValueError('ADMISSION_MANAGER_EVIDENCE_SCOPE')
            _number(evidence['price_scale'], positive=True); _number(evidence['volume_scale'], positive=True)
    if len(seen) != counts['target_members'] or sum(counts[group] for group in groups) != counts['target_members']:
        raise ValueError('ADMISSION_MANAGER_TARGET_ACCOUNTING')
    if value['status'] != ('PARTIAL' if counts['pending'] else 'READY'):
        raise ValueError('ADMISSION_MANAGER_STATUS')
    outside = value['outside_target_membership']
    if (not isinstance(outside, list) or any(_code(code) != code for code in outside)
            or outside != sorted(set(outside)) or seen.intersection(outside)):
        raise ValueError('ADMISSION_MANAGER_OUTSIDE_MEMBERSHIP')
    return value
