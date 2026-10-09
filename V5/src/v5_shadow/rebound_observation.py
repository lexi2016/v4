"""Current panel-only native arithmetic, never a verified rebound selection.

The original complete-master owner remains unchanged. This adapter extracts
hash-pinned original arithmetic AST, without constructing a master or witness.
"""
import sys
from pathlib import Path
if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ast
import copy
import hashlib
import importlib
import io
import math
import os
import re
import subprocess
import tempfile
import uuid
from contextlib import redirect_stdout
from datetime import datetime, timezone, timedelta

from v5_shadow import rebound_owner as owner
from v5_shadow.contracts import aware, exact_keys, sha, trade_date
from v5_shadow.composition import no_symlinks
from v5_shadow.digests import canonical_bytes, sha256_json, MAX_JSON_BYTES
from v5_shadow.module_api import _open_directory, _read_at
from v5_shadow.module_artifacts import _directory, _write_once
from v5_shadow.source_capsule import checked_path

BASE = owner.BASE
DESCRIPTOR = BASE / 'contracts/rebound_observation_capsule.json'
PIN = '85c2ea2bdde51373fb511a079def4c3546087390e3abab21a836ec9d58058a57'
SOURCE = 'v4/manager_research/workspace_plan.py'
HK = timezone(timedelta(hours=8))
MARKER = b'v5.rebound-observation-root.v1\n'
SAFETY = dict(owner.SAFETY, eligible_screen=None, formal_status='CANNOT_CONFIRM')
GAPS = ('HISTORY_PRICE_SCALE_CONSISTENCY_NOT_PROVEN', 'HISTORY_VOLUME_SCALE_CONSISTENCY_NOT_PROVEN',
        'PRICE_CURRENCY_NOT_PROVEN', 'AMOUNT_UNIT_NOT_PROVEN', 'PROVIDER_FINALITY_NOT_ATTESTED',
        'TARGET_ELIGIBILITY_NOT_BOUND', 'SECURITY_MASTER_NOT_BOUND_PANEL_OBSERVATION_ONLY')
# Names here are internal capture keys, including original booleans for exact
# differential tests. They are never copied wholesale into the public result.
CAPTURE_KEYS = (
    'code', 'close', 'prev_close', 'day_positive_close_gt_prev_close', 'pct_change',
    'current_volume', 'close_position_0_low_1_high', 'rebound_close_vs_low_pct', 'rebound_ge_3pct',
    'recent_3_session_return_pct', 'recent_5_session_return_pct', 'history_status',
    'history_unknown_reasons', 'prior60_session_count', 'previous5_session_count',
    'previous20_session_count', 'prior60_session_high', 'oversold_cutoff_80pct_prior60_high',
    'previous5_mean_volume', 'volume_ratio_5d', 'previous20_mean_volume_background',
    'volume_ratio_20d_background', 'background20_status', 'oversold_flag',
    'volume_flag_5d_ge_1_5', 'strict_two_gate_oversold_5dvolume', 'near_two_gate_one_missing',
)
NUMBER_MAP = {
    'close_native': 'close', 'previous_close_native': 'prev_close',
    'prior60_high_native': 'prior60_session_high',
    'close_comparison_boundary_native': 'oversold_cutoff_80pct_prior60_high',
    'current_volume_native': 'current_volume', 'previous5_mean_volume_native': 'previous5_mean_volume',
    'current_to_previous5_native_ratio': 'volume_ratio_5d',
    'previous20_mean_volume_native': 'previous20_mean_volume_background',
    'current_to_previous20_native_ratio': 'volume_ratio_20d_background',
    'close_position': 'close_position_0_low_1_high', 'close_vs_low_pct': 'rebound_close_vs_low_pct',
    'change_pct': 'pct_change', 'recent_3_record_native_change_pct': 'recent_3_session_return_pct',
    'recent_5_record_native_change_pct': 'recent_5_session_return_pct',
}
SCALE = dict(scope='ENTIRE_SELECTED_HISTORY', price_scale_consistency='NOT_PROVEN',
    volume_scale_consistency='NOT_PROVEN', price_currency=None, volume_unit=None, amount_unit=None,
    conversion_applied=False)
INTERPRETATION = 'UNVERIFIED_NATIVE_ARITHMETIC_ONLY_NOT_SELECTION'
BACKGROUND_BASIS = 'ORIGINAL_LAST_AVAILABLE_RECORDS_NOT_CALENDAR_WINDOW_VERIFICATION'


def _capsule():
    descriptor = owner._json(DESCRIPTOR.read_bytes())
    if sha256_json(descriptor) != PIN:
        raise ValueError('OBSERVATION_CAPSULE_DESCRIPTOR')
    if descriptor['capture_keys'] != list(CAPTURE_KEYS):
        raise ValueError('OBSERVATION_CAPTURE_CONTRACT')
    for relative, digest in descriptor['bindings'].items():
        if hashlib.sha256(checked_path(BASE, relative).read_bytes()).hexdigest() != digest:
            raise ValueError('OBSERVATION_SOURCE_BINDING:' + relative)
    sources = owner._sources(); raw = sources[SOURCE]
    if hashlib.sha256(raw).hexdigest() != descriptor['source_sha256']:
        raise ValueError('OBSERVATION_ORIGINAL_SOURCE')
    lines = raw.splitlines(keepends=True)
    for span in descriptor['extracted_spans']:
        if hashlib.sha256(b''.join(lines[span['first']-1:span['last']])).hexdigest() != span['sha256']:
            raise ValueError('OBSERVATION_EXTRACTION_SPAN')
    return descriptor, sources


def extract_calculator(original):
    """Compile original statement/expression nodes; no arithmetic translation.

    The fixed source hash and line boundaries reject source drift. New code
    supplies arguments and collects values only; master/name/provenance packing
    from the old screen is excluded, not replaced with fabricated metadata.
    """
    descriptor, sources = _capsule()
    tree = ast.parse(sources[SOURCE], filename=str(owner.CAPSULE / SOURCE))
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'read_rebound_screen')
    outer = next(n for n in function.body if isinstance(n, ast.Try))
    setup = [copy.deepcopy(n) for n in outer.body if 874 <= n.lineno <= 889]
    loop = next(n for n in outer.body if isinstance(n, ast.For) and n.lineno == 893)
    arithmetic = [copy.deepcopy(n) for n in loop.body if 894 <= n.lineno <= 993]
    row_assignment = next(n for n in loop.body if isinstance(n, ast.Assign) and n.lineno == 997)
    keywords = {k.arg: k for k in row_assignment.value.keywords}
    if not set(CAPTURE_KEYS).issubset(keywords):
        raise ValueError('OBSERVATION_CAPTURE_SOURCE_CHANGED')
    capture = copy.deepcopy(row_assignment)
    capture.value.keywords = [copy.deepcopy(keywords[k]) for k in CAPTURE_KEYS]
    background = [copy.deepcopy(n) for n in loop.body if 1046 <= n.lineno <= 1052]
    if descriptor['structural_boundaries'] != dict(setup_count=len(setup), arithmetic_count=len(arithmetic),
                                                  background_count=len(background), original_loop_line=loop.lineno):
        raise ValueError('OBSERVATION_AST_BOUNDARIES')
    extra = ast.parse("""
row['panel_name'] = current.get('name')
row['amount_native'] = amount
row['low_native'] = low
row['high_native'] = high
row['missing_prior60_dates'] = missing_prior60_dates
row['missing_previous5_dates'] = missing_previous5_dates
row['duplicate_prior60_dates'] = sorted(duplicate_prior60_dates)
row['duplicate_previous5_dates'] = sorted(duplicate_previous5_dates)
""").body
    copied_loop = copy.deepcopy(loop)
    copied_loop.body = arithmetic + [capture] + extra + background
    wrapper = ast.parse("""
def calculate(frame, context, history_sessions, panel_gaps):
    day = str(context['market_session'])
    prior60_session_dates = list(history_sessions['prior60'])
    previous5_session_dates = list(history_sessions['previous5'])
    gaps = list(panel_gaps)
    rows = []
""")
    wrapper.body[0].body += setup + [copied_loop] + ast.parse("return dict(rows=rows, gaps=gaps)").body
    ast.fix_missing_locations(wrapper)
    # The namespace comes only from the byte-verified loader, never a request.
    scope = dict(vars(original))
    exec(compile(wrapper, str(owner.CAPSULE / SOURCE), 'exec'), scope)
    return scope['calculate']


def _request(value):
    exact_keys(value, ('schema_version', 'target_date', 'signal_date', 'data_kind', 'input_root', 'paths', 'files'))
    if value['schema_version'] != 'v5.rebound_observation_request.v1':
        raise ValueError('OBSERVATION_REQUEST_SCHEMA')
    if trade_date(value['signal_date']) >= trade_date(value['target_date']):
        raise ValueError('OBSERVATION_SIGNAL_DATE')
    if value['data_kind'] not in ('RECORDED_INPUT_CURRENT', 'SYNTHETIC'):
        raise ValueError('OBSERVATION_DATA_KIND')
    root = no_symlinks(value['input_root'])
    if not root.is_dir():
        raise ValueError('OBSERVATION_INPUT_ROOT')
    for code_root in (BASE, Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve()):
        if root.is_relative_to(code_root) or code_root.is_relative_to(root):
            raise ValueError('OBSERVATION_INPUT_CODE_OVERLAP')
    exact_keys(value['paths'], ('panel_manifest', 'panel'))
    if (not isinstance(value['files'], dict) or not 2 <= len(value['files']) <= 32
            or len(set(value['paths'].values())) != 2):
        raise ValueError('OBSERVATION_INPUT_FILES')
    for relative, digest in value['files'].items():
        checked_path(root, relative); sha(digest)
        if not re.fullmatch(r'assets/hk_0_2/panels/[A-Za-z0-9._-]+/(?:manifest\.json|hkconnect_vipdoc_daily_panel\.parquet)', relative):
            raise ValueError('OBSERVATION_PANEL_ONLY_INPUT')
    if not set(value['paths'].values()).issubset(value['files']):
        raise ValueError('OBSERVATION_ROLE_NOT_BOUND')
    canonical_bytes(value)
    return copy.deepcopy(value)


def _panel_metadata(root, request, observed_at):
    paths = request['paths']; manifest = owner._json(checked_path(root, paths['panel_manifest']).read_bytes())
    if (manifest.get('panel_max_date') != request['signal_date']
            or 'assets/hk_0_2/' + str(manifest.get('panel_relative')) != paths['panel']
            or Path(paths['panel_manifest']).parent != Path(paths['panel']).parent
            or manifest.get('panel_sha256') != request['files'][paths['panel']]):
        raise ValueError('OBSERVATION_PANEL_BINDING')
    if aware(manifest.get('manifest_prepared_at')) > aware(observed_at):
        raise ValueError('OBSERVATION_PANEL_AFTER_CURRENT_OBSERVATION')
    return manifest


def prepare_snapshot(request, destination, observed_at):
    request = _request(request); aware(observed_at)
    source = no_symlinks(request['input_root']); private = no_symlinks(destination)
    if private.exists() or private.is_relative_to(source) or source.is_relative_to(private):
        raise ValueError('OBSERVATION_PRIVATE_ROOT')
    private.mkdir(mode=0o700); entries = {}; total = 0
    for relative, expected in sorted(request['files'].items()):
        identity = owner._file(source, relative, destination=checked_path(private, relative))
        if identity['sha256'] != expected:
            raise ValueError('OBSERVATION_INPUT_SHA:' + relative)
        entries[relative] = identity; total += identity['bytes']
        if total > 1024**3:
            raise ValueError('OBSERVATION_INPUT_SIZE')
    _panel_metadata(private, request, observed_at)
    pointer = 'assets/hk_0_2/panel_latest.json'
    raw = canonical_bytes(dict(manifest_relative=request['paths']['panel_manifest'].removeprefix('assets/hk_0_2/')))
    checked_path(private, pointer).write_bytes(raw)
    entries[pointer] = dict(sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))
    for path in private.rglob('*'):
        if path.is_file(): path.chmod(0o400)
    for path in sorted((p for p in private.rglob('*') if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
        path.chmod(0o500)
    private.chmod(0o500)
    return dict(files=entries, snapshot_sha256=sha256_json(entries), source_file_sha256=request['files'],
        adapter_generated_routing=[pointer], owner_read_lease_verified=False, owner_origin_verified=False,
        status='PRIVATE_COPY_SHA_BOUND', security_master='NOT_BOUND_NOT_SYNTHESIZED')


def project_rows(raw_rows, signal_date, observed_at):
    result = []
    for raw in raw_rows:
        raw = copy.deepcopy(raw)
        complete = raw['history_status'] == 'KNOWN'
        values = (raw['oversold_flag'], raw['volume_flag_5d_ge_1_5'])
        if not complete:
            pattern = 'INCOMPLETE_INPUT'
        else:
            pattern = ('NEITHER_COMPARISON_TRUE', 'ONE_COMPARISON_TRUE', 'BOTH_COMPARISONS_TRUE')[sum(x is True for x in values)]
        # Name is a current reading of a panel label, not a historical master.
        label = raw.get('panel_name')
        name = label.strip() if isinstance(label, str) and label.strip() else raw['code']
        numbers = {target: raw[source] for target, source in NUMBER_MAP.items()}
        numbers.update({key: raw[key] for key in ('amount_native', 'low_native', 'high_native')})
        result.append(dict(code=raw['code'], name=name, name_source='PANEL_LABEL_READ_NOW' if name != raw['code'] else 'SYMBOL_ONLY',
            signal_date=signal_date, observed_at=observed_at, native_numbers=numbers,
            native_comparisons=dict(close_le_prior60_high_times_0_8=values[0], current_to_previous5_ge_1_5=values[1]),
            arithmetic_pattern=pattern, numeric_input_status=raw['history_status'],
            interpretation=INTERPRETATION, background_basis=BACKGROUND_BASIS,
            input_gaps=raw['history_unknown_reasons'].split(';') if raw['history_unknown_reasons'] else [],
            missing_prior60_dates=raw['missing_prior60_dates'], missing_previous5_dates=raw['missing_previous5_dates'],
            duplicate_prior60_dates=raw['duplicate_prior60_dates'], duplicate_previous5_dates=raw['duplicate_previous5_dates'],
            prior60_session_count=raw['prior60_session_count'], previous5_session_count=raw['previous5_session_count'],
            scale_status='NOT_PROVEN_ENTIRE_SELECTED_HISTORY', finality_status='NOT_ATTESTED_BY_PROVIDER',
            eligibility_status='UNVERIFIED'))
    return result


def _identity():
    result = owner._identity()
    result['rebound_observation.py'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    return result


def _worker(envelope):
    request = envelope['request']
    # Worker takes its own clock: stdin cannot select a historical cutoff.
    observed = datetime.now(timezone.utc); observed_text = observed.isoformat()
    if request['data_kind'] == 'RECORDED_INPUT_CURRENT' and request['target_date'] != observed.astimezone(HK).strftime('%Y%m%d'):
        raise ValueError('OBSERVATION_CURRENT_TARGET_REQUIRED')
    if sys.version_info < (3, 14): raise ValueError('OBSERVATION_PYTHON_REQUIRES_3_14')
    descriptor, sources = _capsule(); dependencies = owner.observe_dependencies(BASE / 'uv.lock')
    if dependencies['status'] != 'MATCH':
        raise ValueError('OBSERVATION_DEPENDENCIES:' + ','.join(dependencies['reason_codes']))
    if any(name.split('.')[0] in owner.NAMESPACES for name in sys.modules):
        raise ValueError('OBSERVATION_FRESH_PROCESS_REQUIRED')
    sys.meta_path.insert(0, owner._Loader(sources))
    original = importlib.import_module('v4.manager_research.workspace_plan')
    pd = importlib.import_module('pandas'); importlib.import_module('pyarrow.parquet')
    importlib.import_module('infrastructure.owned_io')
    calculator = extract_calculator(original)
    context = original.plan_context(request['target_date'], now=observed)
    day = request['signal_date']
    if context['market_session'] != day:
        raise ValueError('OBSERVATION_SIGNAL_CALENDAR_MISMATCH')
    history = original.rebound_history_sessions(day)
    dates60, dates5 = history['prior60'], history['previous5']
    if (len(dates60) != 60 or len(set(dates60)) != 60 or len(dates5) != 5 or len(set(dates5)) != 5
            or any(not re.fullmatch(r'\d{8}', str(d)) for d in [*dates60, *dates5]) or not set(dates5).issubset(dates60)):
        raise ValueError('OBSERVATION_HISTORY_CALENDAR_INVALID')
    private = no_symlinks(envelope['private_root']); snapshot = envelope['snapshot']
    owner._verify_private(private, snapshot)
    manifest = _panel_metadata(private, request, observed_text)
    violations = owner._guard(private)
    witness, panel_gaps = original._read_hk02_panel_witness(private, day,
        research_cutoff=observed_text, required_history_date=dates5[-1])
    if witness is None:
        raise ValueError('OBSERVATION_PANEL_WITNESS:' + ','.join(panel_gaps))
    if (witness['panel_sha256'] != request['files'][request['paths']['panel']]
            or witness['panel_manifest_sha256'] != request['files'][request['paths']['panel_manifest']]):
        raise ValueError('OBSERVATION_SELECTED_PANEL_MISMATCH')
    native = original.rebound_native_evidence(manifest, required_session=day, observed_at=datetime.now(timezone.utc))
    # Same original physical-column contract; open/name remain requested even
    # though they do not determine either numerical comparison.
    frame = pd.read_parquet(witness['panel_path'], columns=['trade_date_compact', 'code_norm', 'name',
        'open', 'high', 'low', 'close', 'amount', 'trade', 'pre_close'])
    with redirect_stdout(io.StringIO()): raw = calculator(frame, context, history, panel_gaps)
    if 'rows' not in raw:
        raise ValueError('OBSERVATION_ORIGINAL_INPUT_REJECTED:' + ','.join(raw.get('gaps', [])))
    if violations: raise ValueError('OBSERVATION_BOUNDARY_VIOLATION:' + ','.join(violations))
    owner._verify_private(private, snapshot); _capsule()
    rows = project_rows(raw['rows'], day, observed_text)
    return dict(rows=rows, computation_status='NATIVE_VALUES_OBSERVED',
        observed_at=observed_text, calculation_identity='FROZEN_NUMERIC_BODY_EXTRACT_NOT_COMPLETE_MASTER_OWNER',
        reason_codes=sorted(set(list(GAPS) + raw['gaps'] + native['gaps'])),
        context=context, history_sessions=history, dependencies=dependencies,
        native_evidence=native, source_capsule_sha256=PIN, implementation_identity=_identity(),
        request_sha256=sha256_json(request), snapshot_sha256=snapshot['snapshot_sha256'],
        source_identity=dict(panel_sha256=witness['panel_sha256'], panel_manifest_sha256=witness['panel_manifest_sha256'],
            calendar_sha256=history['calendar_sha256'], original_source_sha256=descriptor['source_sha256']),
        counts=dict(observed_rows=len(rows), numeric_input_complete=sum(r['numeric_input_status']=='KNOWN' for r in rows),
                    numeric_input_incomplete=sum(r['numeric_input_status']!='KNOWN' for r in rows)),
        scale_evidence=copy.deepcopy(SCALE), finality_status='NOT_ATTESTED_BY_PROVIDER', eligibility_status='UNVERIFIED')


def _output(root):
    root = no_symlinks(root); fd = _open_directory(root)
    try:
        if _read_at(fd, None, '.v5-rebound-observation-root') != MARKER:
            raise ValueError('OBSERVATION_OUTPUT_MARKER')
        if root.is_relative_to(BASE) or BASE.is_relative_to(root):
            raise ValueError('OBSERVATION_OUTPUT_CODE_OVERLAP')
        return root, fd
    except Exception:
        os.close(fd); raise


def _validate(value):
    if (value.get('schema_version') != 'v5.rebound_observation.v1' or value.get('source_capsule_sha256') != PIN
            or any(type(value.get(k)) is not type(expected) or value.get(k) != expected for k, expected in SAFETY.items())):
        raise ValueError('OBSERVATION_ARTIFACT_SAFETY')
    request = value['request']
    exact_keys(request, ('schema_version', 'target_date', 'signal_date', 'data_kind', 'input_root', 'paths', 'files'))
    if (request['schema_version'] != 'v5.rebound_observation_request.v1'
            or trade_date(request['signal_date']) >= trade_date(request['target_date'])):
        raise ValueError('OBSERVATION_ARTIFACT_REQUEST_SCHEMA')
    if value['request_sha256'] != sha256_json(request): raise ValueError('OBSERVATION_ARTIFACT_REQUEST')
    if not aware(value['started_at']) <= aware(value['observed_at']) <= aware(value['finished_at']):
        raise ValueError('OBSERVATION_ARTIFACT_CLOCK')
    kind = request['data_kind']
    expected_kind = 'CURRENT_RECORDED_PANEL_OBSERVATION' if kind == 'RECORDED_INPUT_CURRENT' else 'SYNTHETIC_TEST'
    if kind not in ('RECORDED_INPUT_CURRENT', 'SYNTHETIC') or value['execution_kind'] != expected_kind:
        raise ValueError('OBSERVATION_ARTIFACT_KIND')
    snapshot = value['snapshot']
    if snapshot is not None:
        if (snapshot['snapshot_sha256'] != sha256_json(snapshot['files']) or snapshot['source_file_sha256'] != request['files']
                or snapshot['owner_origin_verified'] is not False or snapshot['owner_read_lease_verified'] is not False):
            raise ValueError('OBSERVATION_ARTIFACT_SNAPSHOT')
        if any(snapshot['files'].get(p, {}).get('sha256') != digest for p, digest in request['files'].items()):
            raise ValueError('OBSERVATION_ARTIFACT_INPUT_IDENTITY')
    if value['computation_status'] == 'CANNOT_CONFIRM':
        if value['rows'] is not None or value['counts'] is not None: raise ValueError('OBSERVATION_FAILED_ROWS')
        return
    if kind == 'RECORDED_INPUT_CURRENT' and request['target_date'] != aware(value['observed_at']).astimezone(HK).strftime('%Y%m%d'):
        raise ValueError('OBSERVATION_CURRENT_TARGET_REQUIRED')
    if (value['computation_status'] != 'NATIVE_VALUES_OBSERVED' or snapshot is None
            or value['snapshot_sha256'] != snapshot['snapshot_sha256']
            or value['context']['market_session'] != request['signal_date']
            or value['context']['plan_trade_date'] != request['target_date']
            or value['dependencies']['status'] != 'MATCH' or not set(GAPS).issubset(value['reason_codes'])
            or value['finality_status'] != 'NOT_ATTESTED_BY_PROVIDER' or value['eligibility_status'] != 'UNVERIFIED'
            or canonical_bytes(value['scale_evidence']) != canonical_bytes(SCALE)
            or value['calculation_identity'] != 'FROZEN_NUMERIC_BODY_EXTRACT_NOT_COMPLETE_MASTER_OWNER'
            or aware(value['context']['research_cutoff']) != aware(value['observed_at'])):
        raise ValueError('OBSERVATION_ARTIFACT_CONTRACT')
    descriptor, _ = _capsule()
    calendar_sha = descriptor['bindings']['vendor/rebound_baseline/contracts/market_calendar_2026.json']
    if (value['source_identity'] != dict(panel_sha256=request['files'][request['paths']['panel']],
            panel_manifest_sha256=request['files'][request['paths']['panel_manifest']],
            calendar_sha256=calendar_sha, original_source_sha256=descriptor['source_sha256'])
            or value['history_sessions']['calendar_sha256'] != calendar_sha
            or value['context']['calendar_sha256'] != calendar_sha):
        raise ValueError('OBSERVATION_ARTIFACT_SOURCE_IDENTITY')
    exact_keys(value['implementation_identity'], _identity())
    for digest in value['implementation_identity'].values(): sha(digest)
    codes = set()
    for row in value['rows']:
        exact_keys(row, ('code', 'name', 'name_source', 'signal_date', 'observed_at', 'native_numbers',
            'native_comparisons', 'arithmetic_pattern', 'numeric_input_status', 'interpretation', 'background_basis',
            'input_gaps', 'missing_prior60_dates', 'missing_previous5_dates', 'duplicate_prior60_dates',
            'duplicate_previous5_dates', 'prior60_session_count', 'previous5_session_count',
            'scale_status', 'finality_status', 'eligibility_status'))
        exact_keys(row['native_numbers'], (*NUMBER_MAP, 'amount_native', 'low_native', 'high_native'))
        exact_keys(row['native_comparisons'], ('close_le_prior60_high_times_0_8', 'current_to_previous5_ge_1_5'))
        if any(number is not None and (type(number) not in (int, float) or not math.isfinite(number)) for number in row['native_numbers'].values()):
            raise ValueError('OBSERVATION_NATIVE_NUMBER_TYPE')
        comparisons = list(row['native_comparisons'].values())
        if any(v is not None and type(v) is not bool for v in comparisons):
            raise ValueError('OBSERVATION_COMPARISON_TYPE')
        complete = row['numeric_input_status'] == 'KNOWN'
        expected_pattern = ('NEITHER_COMPARISON_TRUE', 'ONE_COMPARISON_TRUE', 'BOTH_COMPARISONS_TRUE')[sum(v is True for v in comparisons)] if complete else 'INCOMPLETE_INPUT'
        if (row['numeric_input_status'] not in ('KNOWN', 'PARTIAL_UNKNOWN') or (complete and None in comparisons)
                or row['arithmetic_pattern'] != expected_pattern or row['interpretation'] != INTERPRETATION
                or row['background_basis'] != BACKGROUND_BASIS
                or row['name_source'] not in ('PANEL_LABEL_READ_NOW', 'SYMBOL_ONLY')
                or not isinstance(row['name'], str) or not row['name'].strip()
                or not isinstance(row['input_gaps'], list) or any(not isinstance(g, str) for g in row['input_gaps'])
                or any(type(row[k]) is not int or row[k]<0 for k in ('prior60_session_count', 'previous5_session_count'))):
            raise ValueError('OBSERVATION_ARITHMETIC_CONTRACT')
        for key in ('missing_prior60_dates', 'missing_previous5_dates', 'duplicate_prior60_dates', 'duplicate_previous5_dates'):
            if not isinstance(row[key], list): raise ValueError('OBSERVATION_GAP_DATES')
            for date in row[key]: trade_date(date)
        if (row['code'] in codes or not re.fullmatch(r'HK\.\d{5}', row['code'])
                or row['signal_date'] != request['signal_date'] or row['observed_at'] != value['observed_at']
                or row['scale_status'] != 'NOT_PROVEN_ENTIRE_SELECTED_HISTORY'
                or row['finality_status'] != 'NOT_ATTESTED_BY_PROVIDER' or row['eligibility_status'] != 'UNVERIFIED'
                or any(k in row for k in ('strict', 'near', 'classification', 'rank', 'eligible_screen'))):
            raise ValueError('OBSERVATION_ROW_CONTRACT')
        codes.add(row['code'])
    if any(type(n) is not int for n in value['counts'].values()) or value['counts'] != dict(observed_rows=len(codes), numeric_input_complete=sum(r['numeric_input_status']=='KNOWN' for r in value['rows']),
                              numeric_input_incomplete=sum(r['numeric_input_status']!='KNOWN' for r in value['rows'])):
        raise ValueError('OBSERVATION_COUNT_CONTRACT')


def _publish(root, value):
    _validate(value); root, fd = _output(root)
    try:
        runs = _directory(fd, 'runs')
        try: run = _directory(runs, value['run_id'])
        finally: os.close(runs)
        try:
            raw = canonical_bytes(value); ash = hashlib.sha256(raw).hexdigest()
            manifest = dict(schema_version='v5.rebound_observation_manifest.v1', run_id=value['run_id'],
                artifact_sha256=ash, request_sha256=value['request_sha256'], source_capsule_sha256=PIN)
            mraw = canonical_bytes(manifest); msh = hashlib.sha256(mraw).hexdigest()
            receipt = dict(schema_version='v5.rebound_observation_receipt.v1', run_id=value['run_id'],
                artifact_sha256=ash, manifest_sha256=msh, status='COMMITTED', **SAFETY)
            rraw = canonical_bytes(receipt)
            for name, data in (('artifact', raw), ('manifest', mraw), ('receipt', rraw)):
                _write_once(run, name+'.json', data)
            reference = dict(run_id=value['run_id'], artifact_sha256=ash, manifest_sha256=msh,
                             receipt_sha256=hashlib.sha256(rraw).hexdigest())
        finally: os.close(run)
    finally: os.close(fd)
    if read_rebound_observation(root, reference) != value: raise ValueError('OBSERVATION_READBACK_MISMATCH')
    return reference


def read_rebound_observation(root, reference):
    exact_keys(reference, ('run_id', 'artifact_sha256', 'manifest_sha256', 'receipt_sha256'))
    if not re.fullmatch(r'[0-9a-f]{32}', str(reference['run_id'])): raise ValueError('OBSERVATION_RUN_ID')
    for key in ('artifact_sha256', 'manifest_sha256', 'receipt_sha256'): sha(reference[key])
    _, fd = _output(root)
    try:
        runs = os.open('runs', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
        try: run = os.open(reference['run_id'], os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=runs)
        finally: os.close(runs)
        try:
            docs = {}
            for name in ('artifact', 'manifest', 'receipt'):
                raw = _read_at(run, None, name+'.json')
                if hashlib.sha256(raw).hexdigest() != reference[name+'_sha256']: raise ValueError('OBSERVATION_READBACK_SHA:'+name)
                docs[name] = owner._json(raw)
        finally: os.close(run)
    finally: os.close(fd)
    value, manifest, receipt = (docs[k] for k in ('artifact', 'manifest', 'receipt'))
    if (any(d.get('run_id') != reference['run_id'] for d in docs.values())
            or manifest.get('schema_version') != 'v5.rebound_observation_manifest.v1'
            or receipt.get('schema_version') != 'v5.rebound_observation_receipt.v1'
            or any(d.get('artifact_sha256') != reference['artifact_sha256'] for d in (manifest, receipt))
            or receipt.get('manifest_sha256') != reference['manifest_sha256'] or receipt.get('status') != 'COMMITTED'
            or manifest.get('source_capsule_sha256') != PIN or manifest.get('request_sha256') != value['request_sha256']
            or any(type(receipt.get(k)) is not type(expected) or receipt.get(k) != expected for k, expected in SAFETY.items())):
        raise ValueError('OBSERVATION_READBACK_CONTRACT')
    _validate(value)
    return value


def manager_observation(value, *, target_date, market_session, research_cutoff):
    _validate(value); reasons = list(value['reason_codes']); request = value['request']
    if request['data_kind'] != 'RECORDED_INPUT_CURRENT': reasons.append('OBSERVATION_MANAGER_SYNTHETIC_REJECTED')
    if request['target_date'] != target_date or request['signal_date'] != market_session: reasons.append('OBSERVATION_MANAGER_DATE_MISMATCH')
    if aware(value['finished_at']) > aware(research_cutoff): reasons.append('OBSERVATION_MANAGER_AFTER_CUTOFF')
    accepted = not any(r.startswith('OBSERVATION_MANAGER_') for r in reasons)
    return dict(rows=copy.deepcopy(value['rows']) if accepted else None, reason_codes=sorted(set(reasons)),
        computation_status=value['computation_status'],
        source_run_id=value['run_id'], observed_at=value['observed_at'], target_date=request['target_date'],
        signal_date=request['signal_date'], data_kind=request['data_kind'], **SAFETY)


def run_rebound_observation(request, output_root):
    request = _request(request); root, fd = _output(output_root); os.close(fd)
    source = no_symlinks(request['input_root'])
    if root.is_relative_to(source) or source.is_relative_to(root): raise ValueError('OBSERVATION_ROOT_OVERLAP')
    started = datetime.now(timezone.utc).isoformat(); identity = _identity()
    if request['data_kind'] == 'RECORDED_INPUT_CURRENT' and request['target_date'] != aware(started).astimezone(HK).strftime('%Y%m%d'):
        raise ValueError('OBSERVATION_CURRENT_TARGET_REQUIRED')
    value = dict(schema_version='v5.rebound_observation.v1', run_id=uuid.uuid4().hex,
        request=request, request_sha256=sha256_json(request), started_at=started, observed_at=started,
        source_capsule_sha256=PIN, implementation_identity=identity, snapshot=None, rows=None, counts=None,
        computation_status='CANNOT_CONFIRM', reason_codes=list(GAPS),
        execution_kind='CURRENT_RECORDED_PANEL_OBSERVATION' if request['data_kind']=='RECORDED_INPUT_CURRENT' else 'SYNTHETIC_TEST',
        isolation='PRIVATE_COPY_AND_PYTHON_GUARDS_NOT_OS_SANDBOX', **SAFETY)
    try:
        _capsule()
        with tempfile.TemporaryDirectory(prefix='v5-rebound-observation-') as temporary:
            private = Path(temporary).resolve()/'inputs'
            snapshot = prepare_snapshot(request, private, started); value['snapshot'] = snapshot
            observed_at = datetime.now(timezone.utc).isoformat(); value['observed_at'] = observed_at
            envelope = dict(request=request, private_root=str(private), snapshot=snapshot, observed_at=observed_at)
            env = {k: v for k, v in os.environ.items() if not k.startswith(('V4_', 'V5_', 'PYTHON'))}
            response = subprocess.run([sys.executable, '-I', '-B', str(Path(__file__).resolve()), '--worker'],
                input=canonical_bytes(envelope), stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, timeout=180)
            if len(response.stdout)>MAX_JSON_BYTES: raise ValueError('OBSERVATION_RESPONSE_SIZE')
            result = owner._json(response.stdout)
            if response.returncode: raise ValueError(result.get('reason', 'OBSERVATION_WORKER_FAILED'))
            if (result.get('request_sha256') != value['request_sha256'] or result.get('source_capsule_sha256') != PIN
                    or result.get('implementation_identity') != identity or _identity() != identity
                    or result.get('snapshot_sha256') != snapshot['snapshot_sha256']):
                raise ValueError('OBSERVATION_WORKER_IDENTITY')
            owner._verify_private(private, snapshot); value.update(result)
    except (ValueError, OSError, TypeError, KeyError, subprocess.TimeoutExpired) as error:
        value.update(computation_status='CANNOT_CONFIRM', rows=None, counts=None,
                     reason_codes=sorted(set(list(GAPS)+[type(error).__name__+':'+str(error)])))
    value['finished_at'] = datetime.now(timezone.utc).isoformat()
    reference = _publish(root, value)
    return dict(reference=reference, readback=read_rebound_observation(root, reference))


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker', action='store_true'); parser.add_argument('--request', type=Path)
    parser.add_argument('--output-root', type=Path); parser.add_argument('--reference', type=Path)
    args = parser.parse_args()
    if args.worker:
        raw = sys.stdin.buffer.read(MAX_JSON_BYTES+1)
        if len(raw)>MAX_JSON_BYTES: raise ValueError('OBSERVATION_REQUEST_SIZE')
        return _worker(owner._json(raw))
    if args.output_root is None: parser.error('--output-root required')
    if args.reference is not None:
        return read_rebound_observation(args.output_root, owner._json(args.reference.read_bytes()))
    if args.request is None: parser.error('--request required')
    result = run_rebound_observation(owner._json(args.request.read_bytes()), args.output_root)
    return dict(reference=result['reference'], computation_status=result['readback']['computation_status'],
                reason_codes=result['readback']['reason_codes'], **SAFETY)


if __name__ == '__main__':
    try: print(canonical_bytes(main()).decode())
    except Exception as error:
        print(canonical_bytes(dict(status='FAILED', reason=type(error).__name__+':'+str(error))).decode())
        raise SystemExit(1)
