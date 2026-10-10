"""Internal-gap extension of the existing HK02 updater, using its owned root.

Install this wrapper at the ORIGINAL writer call site. Normal updates delegate
to the frozen original function under the same publication lock as repairs.
No collector or scheduler is installed. V4 source files are never modified.
"""
from contextlib import contextmanager
import ast
from dataclasses import dataclass
from datetime import datetime, timezone
import fcntl
import hashlib
import os
from pathlib import Path
import re
import struct
import tempfile
import types
import uuid
import sys

from . import rebound_owner as owner_io
from .composition import no_symlinks
from .contracts import aware, exact_keys, sha, trade_date
from .digests import canonical_bytes, sha256_json
from .module_api import _open_directory, _read_at, _read_regular
from .module_artifacts import _directory, _write_once
from .source_capsule import checked_path

OWNER_SHA = '27da90f0e623e45fa1a27af7dcc3b6e5e1ff2320bae1c61bd903ed82050beb89'
SOURCE_CONTRACT = 'tdx_vipdoc_71_day+verified_zero_trade_repairs+native_internal_gap_repair'
RAW_SOURCE_CONTRACT = 'tdx_vipdoc_71_day+verified_zero_trade_repairs+pytdx_internal_gap_repair'
SAFETY = dict(research_only=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)


@dataclass(frozen=True)
class OwnerRepairAuthority:
    """Deployment binding, supplied by the existing owner's integration.

    Approval binds the exact repair request to the existing asset root. This
    authorizes native byte repair, NOT price/volume/membership admission. Do
    not construct this from untrusted job JSON or from an audit's status flag.
    """
    asset_root: Path
    approved_request_sha256: str
    capture_root: Path
    capture_relative: str
    capture_sha256: str


def _read(root, relative, limit=8 * 1024**2):
    path = checked_path(no_symlinks(root), relative)
    parent = _open_directory(path.parent)
    try: fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    finally: os.close(parent)
    try: return _read_regular(fd, limit)
    finally: os.close(fd)


def _same_code(expected, actual):
    """Compare complete immutable code structure, independent of live references.

    marshal's reference flags can change merely by retaining a docstring.
    Compare all 18 public code fields instead, including recursive constants,
    debug/exception tables and exact scalar types/float bits. Mutable or unknown
    constants are not compiler literals and must fail closed.
    """
    def identity(value):
        kind = type(value)
        if kind is types.CodeType:
            fields = ('co_argcount', 'co_posonlyargcount', 'co_kwonlyargcount',
                      'co_nlocals', 'co_stacksize', 'co_flags', 'co_code', 'co_consts',
                      'co_names', 'co_varnames', 'co_filename', 'co_name', 'co_qualname',
                      'co_firstlineno', 'co_linetable', 'co_exceptiontable',
                      'co_freevars', 'co_cellvars')
            return ('code', tuple((name, identity(getattr(value, name))) for name in fields))
        if kind is tuple:
            return ('tuple', tuple(identity(item) for item in value))
        if kind is frozenset:
            return ('frozenset', tuple(sorted(identity(item) for item in value)))
        if kind is slice:
            return ('slice', identity(value.start), identity(value.stop), identity(value.step))
        if kind in (type(None), bool, int, str, bytes):
            return (kind.__name__, value)
        if value is Ellipsis:
            return ('ellipsis',)
        if kind is float:
            return ('float', struct.pack('!d', value))
        if kind is complex:
            return ('complex', struct.pack('!dd', value.real, value.imag))
        raise TypeError('UNSUPPORTED_CODE_CONSTANT')

    try:
        return (type(expected) is types.CodeType and type(actual) is types.CodeType
                and identity(expected) == identity(actual))
    except (TypeError, ValueError, RecursionError):
        return False


def _verify_owner(module):
    path = no_symlinks(module.__file__)
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != OWNER_SHA: raise ValueError('REPAIR_OWNER_SOURCE_IDENTITY')
    compiled = compile(raw, str(path), 'exec', dont_inherit=True)
    tree = ast.parse(raw)
    originals = {c.co_name: c for c in compiled.co_consts if isinstance(c, types.CodeType)}
    # Include helpers: replacing a parser global must not retain owner identity.
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)): continue
        function = getattr(module, node.name, None)
        if (not isinstance(function, types.FunctionType)
                or function.__globals__ is not vars(module)
                or no_symlinks(function.__code__.co_filename) != path):
            raise ValueError('REPAIR_OWNER_FUNCTION_IDENTITY')
        if not _same_code(originals[node.name], function.__code__):
            raise ValueError('REPAIR_OWNER_FUNCTION_MODIFIED')
    for node in tree.body:
        if not isinstance(node, ast.Assign): continue
        try: literal = ast.literal_eval(node.value)
        except (ValueError, TypeError): continue
        for target in node.targets:
            if isinstance(target, ast.Name) and getattr(module, target.id, None) != literal:
                raise ValueError('REPAIR_OWNER_CONSTANT_MODIFIED')
    if (type(module._VIPDOC_DAY_STRUCT) is not struct.Struct
            or module._VIPDOC_DAY_STRUCT.format != '<IfffffII' or module._VIPDOC_DAY_STRUCT.size != 32):
        raise ValueError('REPAIR_OWNER_NATIVE_LAYOUT_MODIFIED')
    # Verify imported Python helpers against the existing frozen dependency
    # capsule as well; checking hk_0_2.py alone misses a replaced hash helper.
    from . import hk_preselection
    sources = hk_preselection._source_bytes()
    for node in tree.body:
        if not isinstance(node, ast.ImportFrom) or node.level != 1: continue
        source_key = 'upstreams/v3_shared_data/shared_data/'+node.module.replace('.', '/')+'.py'
        source = sources[source_key]
        source_functions = {n.name for n in ast.parse(source).body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        for alias in node.names:
            function = getattr(module, alias.asname or alias.name)
            if alias.name not in source_functions: continue
            if not isinstance(function, types.FunctionType): raise ValueError('REPAIR_OWNER_IMPORTED_HELPER_IDENTITY')
            namespace = sys.modules.get(function.__module__)
            if namespace is None or function.__globals__ is not vars(namespace):
                raise ValueError('REPAIR_OWNER_IMPORTED_GLOBALS')
            original = next(c for c in compile(source, function.__code__.co_filename, 'exec',
                            dont_inherit=True).co_consts if isinstance(c, types.CodeType) and c.co_name == alias.name)
            if not _same_code(original, function.__code__):
                raise ValueError('REPAIR_OWNER_IMPORTED_HELPER_MODIFIED')


def _history_window(day):
    """Execute the unchanged original window body with its pinned calendar."""
    sources = owner_io._sources()
    calendar_source = sources['contracts/trading_calendar.py']
    calendar_raw = sources['contracts/market_calendar_2026.json']
    class CalendarBytes:
        def read_bytes(self): return calendar_raw
        def read_text(self, encoding='utf-8'): return calendar_raw.decode(encoding)
    name = '_v5_repair_calendar_'+uuid.uuid4().hex
    module = types.ModuleType(name)
    module.__file__ = str(owner_io.CAPSULE / 'contracts/trading_calendar.py')
    sys.modules[name] = module
    try:
        exec(compile(calendar_source, module.__file__, 'exec'), module.__dict__)
        module.CALENDAR_PATH = CalendarBytes()
        tree = ast.parse(sources['v4/manager_research/workspace_plan.py'])
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                        and node.name == 'rebound_history_sessions')
        # Bind the original import to the private verified calendar namespace;
        # retain every executable date/window statement unchanged.
        function.body = [node for node in function.body if not isinstance(node, ast.ImportFrom)]
        scope = dict(vars(module), date_token=trade_date, hashlib=hashlib)
        wrapper = ast.Module(body=[function], type_ignores=[])
        exec(compile(ast.fix_missing_locations(wrapper), '<pinned-rebound-history>', 'exec'), scope)
        return scope['rebound_history_sessions'](day)
    finally:
        sys.modules.pop(name, None)


def _request(value, through_date):
    raw_input = value.get('schema_version') == 'v5.hk02_pytdx_raw_repair_request.v1'
    exact_keys(value, ('schema_version', 'through_date', 'parent_pointer_sha256',
        'parent_manifest_relative', 'parent_manifest_sha256', 'parent_panel_relative',
        'parent_panel_sha256', 'keys', 'sources' if raw_input else 'native_files'))
    if (value['schema_version'] not in ('v5.hk02_internal_gap_request.v1', 'v5.hk02_pytdx_raw_repair_request.v1')
            or value['through_date'] != trade_date(through_date)):
        raise ValueError('REPAIR_REQUEST_SCHEMA_OR_DATE')
    for key in ('parent_pointer_sha256', 'parent_manifest_sha256', 'parent_panel_sha256'): sha(value[key])
    if not isinstance(value['keys'], list) or not 1 <= len(value['keys']) <= 20000:
        raise ValueError('REPAIR_KEY_BOUND')
    keys = set()
    allowed_dates = set(_history_window(through_date)['prior60'])
    for row in value['keys']:
        exact_keys(row, ('code', 'date'))
        key = (row['code'], trade_date(row['date']))
        if not re.fullmatch(r'HK\.\d{5}', key[0]) or key in keys or key[1] not in allowed_dates:
            raise ValueError('REPAIR_KEY_NOT_INTERNAL_OR_DUPLICATE')
        keys.add(key)
    if raw_input:
        if not isinstance(value['sources'], list) or not 1 <= len(value['sources']) <= 2000:
            raise ValueError('REPAIR_RAW_SOURCE_BOUND')
        for source in value['sources']:
            exact_keys(source, ('relative', 'sha256', 'record_pointer'))
            sha(source['sha256'])
            if not isinstance(source['record_pointer'], str): raise ValueError('REPAIR_RAW_POINTER')
    else:
        files = value['native_files']
        if not isinstance(files, dict) or not 1 <= len(files) <= 2000: raise ValueError('REPAIR_NATIVE_FILE_BOUND')
        expected = {'vipdoc/ds/lday/71#'+code[3:]+'.day' for code, _ in keys}
        if set(files) != expected: raise ValueError('REPAIR_NATIVE_FILE_SCOPE')
        for digest in files.values(): sha(digest)
    for key, suffix in (('parent_manifest_relative', 'manifest.json'),
                        ('parent_panel_relative', 'hkconnect_vipdoc_daily_panel.parquet')):
        if not re.fullmatch(r'panels/[A-Za-z0-9._-]+/'+re.escape(suffix), value[key]):
            raise ValueError('REPAIR_PARENT_PATH')
    return keys


def _capture(authority, request, asset_root):
    if not isinstance(authority, OwnerRepairAuthority): raise ValueError('REPAIR_DEPLOYMENT_AUTHORITY_REQUIRED')
    if no_symlinks(authority.asset_root) != asset_root: raise ValueError('REPAIR_AUTHORITY_ROOT')
    if sha256_json(request) != authority.approved_request_sha256: raise ValueError('REPAIR_UNAPPROVED_REQUEST')
    raw = _read(authority.capture_root, authority.capture_relative)
    if hashlib.sha256(raw).hexdigest() != authority.capture_sha256: raise ValueError('REPAIR_CAPTURE_SHA')
    evidence = owner_io._json(raw)
    raw_input = request['schema_version'] == 'v5.hk02_pytdx_raw_repair_request.v1'
    if raw_input:
        from . import rebound_raw_repair
        bound = (evidence.get('schema_version') == 'v5.hk02_pytdx_capture_binding.v1'
                 and evidence.get('raw_sources_sha256') == sha256_json(request['sources'])
                 and evidence.get('decoder_source_sha256') == rebound_raw_repair.DECODER_SHA)
    else:
        bound = (evidence.get('schema_version') == 'v5.hk02_native_capture_binding.v1'
                 and evidence.get('native_files') == request['native_files']
                 and evidence.get('native_layout') == '<IfffffII')
    if (not bound or evidence.get('repair_keys_sha256') != sha256_json(request['keys'])
            or evidence.get('scale_applied') != 1 or evidence.get('conversion_applied') is not False
            or evidence.get('clock_basis') != 'ACTUAL_CAPTURE_NOT_BAR_LABEL'
            or not aware(evidence['capture_started_at']) <= aware(evidence['capture_finished_at']) <= datetime.now(timezone.utc)):
        raise ValueError('REPAIR_CAPTURE_BINDING')
    # This evidence records actual raw capture, not assumed financial units.
    return evidence


def _parent(module, asset_root, request):
    pointer = _read(asset_root, 'panel_latest.json')
    raw = _read(asset_root, request['parent_manifest_relative'])
    manifest = owner_io._json(raw)
    if (hashlib.sha256(pointer).hexdigest() != request['parent_pointer_sha256']
            or owner_io._json(pointer).get('manifest_relative') != request['parent_manifest_relative']
            or hashlib.sha256(raw).hexdigest() != request['parent_manifest_sha256']
            or manifest.get('panel_relative') != request['parent_panel_relative']
            or manifest.get('panel_sha256') != request['parent_panel_sha256']
            or manifest.get('panel_max_date') != request['through_date']):
        raise ValueError('REPAIR_PARENT_IDENTITY_OR_POINTER_CHANGED')
    # Retain the original owner's real model/name checks; no fabricated assets.
    assets = module.load_frozen_hk_0_2_assets(asset_root)
    if no_symlinks(assets.panel_path) != checked_path(asset_root, request['parent_panel_relative']):
        raise ValueError('REPAIR_PARENT_SELECTION_CHANGED')
    identity = owner_io._file(asset_root, request['parent_panel_relative'])
    if identity['sha256'] != request['parent_panel_sha256']: raise ValueError('REPAIR_PARENT_PANEL_SHA')
    return assets, manifest


def _align_repair_trade_dates(existing, additions):
    """Encode added dates in the parent's storage type without changing old rows.

    The frozen raw/native parsers emit YYYYMMDD strings; real legacy panels
    may store trade_date as an integer. Only exact calendar tokens are accepted.
    This is storage adaptation, not a change to the decoder or market values.
    """
    if 'trade_date' not in existing.columns:
        return additions
    import numbers
    import pandas as pd

    def token(value):
        if isinstance(value, numbers.Integral) and not isinstance(value, (bool,)):
            value = str(int(value))
        if type(value) is not str or re.fullmatch(r'[0-9]{8}', value) is None:
            raise ValueError('REPAIR_DATE_STORAGE_VALUE')
        try:
            datetime.strptime(value, '%Y%m%d')
        except ValueError as error:
            raise ValueError('REPAIR_DATE_STORAGE_CALENDAR') from error
        return value

    dtype = existing['trade_date'].dtype
    integer = pd.api.types.is_integer_dtype(dtype) and not pd.api.types.is_bool_dtype(dtype)
    strings = (pd.api.types.is_object_dtype(dtype) or isinstance(dtype, pd.StringDtype))
    if not integer and not strings:
        raise ValueError('REPAIR_DATE_STORAGE_DTYPE')
    for value, compact in zip(existing['trade_date'], existing['trade_date_compact']):
        if strings and type(value) is not str:
            raise ValueError('REPAIR_DATE_STORAGE_MIXED_PARENT')
        if token(value) != compact or type(compact) is not str:
            raise ValueError('REPAIR_DATE_STORAGE_PARENT_KEY')
    if 'trade_date' not in additions or 'trade_date_compact' not in additions:
        raise ValueError('REPAIR_DATE_STORAGE_MISSING')
    dates = []
    for value, compact in zip(additions['trade_date'], additions['trade_date_compact']):
        day = token(value)
        if type(compact) is not str or day != compact:
            raise ValueError('REPAIR_DATE_STORAGE_ADDED_KEY')
        dates.append(day)
    try:
        encoded = pd.Series([int(day) for day in dates] if integer else dates,
                            index=additions.index, dtype=dtype)
    except (ValueError, TypeError, OverflowError) as error:
        raise ValueError('REPAIR_DATE_STORAGE_RANGE') from error
    if [token(value) for value in encoded] != dates:
        raise ValueError('REPAIR_DATE_STORAGE_LOSS')
    result = additions.copy()
    result['trade_date'] = encoded
    return result


def prepare_internal_gap_repair(module, asset_root, *, tdx_root, request, authority):
    """Build a frame from bound raw bytes with original parsing/enrichment only.

    Existing rows are preserved byte-value-wise. Successor derived fields are
    deliberately not recomputed; this is a missing-row repair, not a rebuild.
    No panel, pointer, model or native source is written by this function.
    """
    _verify_owner(module)
    asset_root = no_symlinks(asset_root); tdx_root = no_symlinks(tdx_root)
    keys = _request(request, request['through_date'])
    capture = _capture(authority, request, asset_root)
    assets, parent_manifest = _parent(module, asset_root, request)
    import pandas as pd
    with tempfile.TemporaryDirectory(prefix='v5-hk02-parent-') as temporary:
        private_panel = Path(temporary) / 'parent.parquet'
        copied = owner_io._file(asset_root, request['parent_panel_relative'], destination=private_panel)
        if copied['sha256'] != request['parent_panel_sha256']: raise ValueError('REPAIR_PARENT_COPY_SHA')
        existing = pd.read_parquet(private_panel)
    required = {'trade_date_compact', 'code_norm', 'open', 'high', 'low', 'close', 'amount', 'trade'}
    if not required.issubset(existing.columns) or existing.empty: raise ValueError('REPAIR_PARENT_COLUMNS')
    dates = existing['trade_date_compact'].astype(str)
    codes = existing['code_norm'].astype(str)
    if dates.max() != request['through_date']: raise ValueError('REPAIR_PARENT_MAX_DATE')
    existing_keys = list(zip(codes, dates))
    if parent_manifest.get('panel_rows') != len(existing): raise ValueError('REPAIR_PARENT_ROW_COUNT')
    if len(set(existing_keys)) != len(existing_keys): raise ValueError('REPAIR_PARENT_DUPLICATES')
    if set(existing_keys) & keys: raise ValueError('REPAIR_EXISTING_KEY_NOT_OVERWRITTEN')
    raw_input = request['schema_version'] == 'v5.hk02_pytdx_raw_repair_request.v1'
    raw_result = None
    if raw_input:
        from . import rebound_raw_repair
        raw_result = rebound_raw_repair.decode_raw_repair(tdx_root, sources=request['sources'],
            keys=request['keys'], through_date=request['through_date'])
        if (aware(raw_result['capture_started_at']) != aware(capture['capture_started_at'])
                or aware(raw_result['capture_finished_at']) != aware(capture['capture_finished_at'])):
            raise ValueError('REPAIR_RAW_CAPTURE_CLOCK_BINDING')
        rows = raw_result['rows']
        all_selected = {(r['code'], r['date']): {k: v for k, v in r.items() if k not in ('code', 'date')}
                        for r in raw_result['row_evidence']}
    else:
        with tempfile.TemporaryDirectory(prefix='v5-hk02-native-repair-') as temporary:
            private = Path(temporary).resolve()
            all_selected = {}
            total = 0
            for relative, expected in sorted(request['native_files'].items()):
                raw = _read(tdx_root, relative)
                total += len(raw)
                if total > 256 * 1024**2: raise ValueError('REPAIR_NATIVE_TOTAL_BYTES')
                if hashlib.sha256(raw).hexdigest() != expected or len(raw) % module._VIPDOC_DAY_STRUCT.size:
                    raise ValueError('REPAIR_NATIVE_SHA_OR_RECORD_LENGTH')
                code = 'HK.' + Path(relative).stem.split('#')[1]
                selected = []
                for offset in range(0, len(raw), module._VIPDOC_DAY_STRUCT.size):
                    record = raw[offset:offset+module._VIPDOC_DAY_STRUCT.size]
                    values = module._VIPDOC_DAY_STRUCT.unpack(record)
                    key = (code, str(values[0]))
                    if key not in keys: continue
                    if key in all_selected: raise ValueError('REPAIR_NATIVE_DUPLICATE_DATE')
                    all_selected[key] = dict(raw_file=relative, raw_file_sha256=expected,
                        record_offset=offset, record_sha256=hashlib.sha256(record).hexdigest())
                    selected.append(record)
                if selected:
                    path = private / Path(relative).name
                    path.write_bytes(b''.join(selected)); path.chmod(0o400)
            if set(all_selected) != keys: raise ValueError('REPAIR_NATIVE_EXACT_KEYS_MISSING')
            earliest = min(day for _, day in keys)
            # Original parser's exclusive lower bound; no business clock is changed.
            from datetime import timedelta
            before = (datetime.strptime(earliest, '%Y%m%d')-timedelta(days=1)).strftime('%Y%m%d')
            rows, _ = module._read_vipdoc_increment(private, after_date=before, through_date=request['through_date'])
    parsed = {(r['code_norm'], r['trade_date_compact']): r for r in rows}
    if len(parsed) != len(rows) or set(parsed) != keys: raise ValueError('REPAIR_ORIGINAL_READER_REJECTED_ROWS')
    import math
    for row in rows:
        if (any(not math.isfinite(row[k]) or row[k] <= 0 for k in ('open', 'high', 'low', 'close'))
                or not row['low'] <= row['open'] <= row['high']):
            raise ValueError('REPAIR_NATIVE_OHLC_INVALID')
    additions = []
    for code, day in sorted(keys):
        # Noncontiguous gaps must see original intervening rows as predecessors.
        prefix = existing.loc[codes.eq(code) & dates.lt(day)].copy()
        prior_additions = [r for r in additions if r['code_norm'] == code and r['trade_date_compact'] < day]
        if prior_additions: prefix = pd.concat([prefix, pd.DataFrame(prior_additions)], ignore_index=True)
        enriched = module._enrich_vipdoc_increment(prefix, pd.DataFrame([parsed[(code, day)]]))
        if len(enriched) != 1: raise ValueError('REPAIR_ORIGINAL_ENRICHMENT_COUNT')
        additions.append(enriched.iloc[0].to_dict())
    addition_frame = _align_repair_trade_dates(existing, pd.DataFrame(additions))
    output = pd.concat([existing, addition_frame], ignore_index=True)
    # Verify the original rows before and after Parquet serialization at publish.
    pd.testing.assert_frame_equal(output.iloc[:len(existing)][existing.columns].reset_index(drop=True),
                                  existing.reset_index(drop=True), check_dtype=False, check_exact=True)
    _parent(module, asset_root, request)
    _verify_owner(module)
    lineage = dict(schema_version='v5.hk02_internal_gap_repair.v1',
        request_sha256=sha256_json(request), parent_panel_relative=request['parent_panel_relative'],
        parent_panel_sha256=request['parent_panel_sha256'], parent_manifest_relative=request['parent_manifest_relative'],
        parent_manifest_sha256=request['parent_manifest_sha256'], parent_pointer_sha256=request['parent_pointer_sha256'],
        original_updater_sha256=OWNER_SHA, input_kind='PYTDX_SOURCE_ROWS' if raw_input else 'VIPDOC_NATIVE',
        native_files=request.get('native_files', {}),
        capture_sha256=authority.capture_sha256, capture_finished_at=capture['capture_finished_at'],
        repaired_keys=request['keys'], row_evidence=[dict(code=k[0], date=k[1], **all_selected[k]) for k in sorted(keys)],
        added_rows=len(additions), existing_rows_preserved=True, successor_derived_fields_recomputed=False,
        scale_applied=1, conversion_applied=False, admission_status='NOT_EVALUATED',
        price_basis='NOT_PROVEN', volume_unit=None, **SAFETY)
    if raw_input:
        lineage.update(raw_files=raw_result['raw_files'], raw_sources=request['sources'],
                       decoder_source_sha256=rebound_raw_repair.DECODER_SHA)
    return dict(frame=output, existing=existing, parent_manifest=parent_manifest, lineage=lineage)


@contextmanager
def _writer_lock(asset_root):
    root = _open_directory(asset_root)
    lock = None
    try:
        lock = os.open('.hk02-updater.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                       0o600, dir_fd=root)
        import stat
        if not stat.S_ISREG(os.fstat(lock).st_mode): raise ValueError('REPAIR_OWNER_LOCK_TYPE')
        try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error: raise ValueError('REPAIR_OWNER_BUSY') from error
        yield root
    finally:
        if lock is not None: os.close(lock)
        os.close(root)


def read_repaired_panel_witness(asset_root, manifest_relative, *, expected_files, cutoff):
    """Explicit consumer branch for this owner's new repair contract.

    Call with privately copied, SHA-bound child/parent panel+manifest and child
    receipt. This proves repair bytes/lineage, never financial semantics.
    """
    root = no_symlinks(asset_root)
    mraw = _read(root, manifest_relative)
    manifest = owner_io._json(mraw)
    if manifest.get('source_contract') not in (SOURCE_CONTRACT, RAW_SOURCE_CONTRACT):
        raise ValueError('REPAIR_READER_SOURCE_CONTRACT')
    raw_input = manifest['source_contract'] == RAW_SOURCE_CONTRACT
    line = manifest['internal_gap_repair']
    day = trade_date(manifest['panel_max_date'])
    panel_relative = manifest['panel_relative']
    receipt_relative = str(Path(manifest_relative).with_name('receipt.json'))
    wanted = {manifest_relative: hashlib.sha256(mraw).hexdigest(),
        panel_relative: manifest['panel_sha256'],
        line['parent_manifest_relative']: line['parent_manifest_sha256'],
        line['parent_panel_relative']: line['parent_panel_sha256']}
    if receipt_relative not in expected_files: raise ValueError('REPAIR_RECEIPT_NOT_BOUND')
    wanted[receipt_relative] = expected_files[receipt_relative]
    for relative, digest in wanted.items():
        sha(digest)
        if expected_files.get(relative) != digest or owner_io._file(root, relative)['sha256'] != digest:
            raise ValueError('REPAIR_READER_INPUT_SHA')
    receipt = owner_io._json(_read(root, receipt_relative))
    parent = owner_io._json(_read(root, line['parent_manifest_relative']))
    if (manifest.get('asset_schema_version') != 'v3_shared_data.hk_0_2_panel_asset.v2'
            or line.get('schema_version') != 'v5.hk02_internal_gap_repair.v1'
            or line.get('original_updater_sha256') != OWNER_SHA
            or line.get('input_kind') != ('PYTDX_SOURCE_ROWS' if raw_input else 'VIPDOC_NATIVE')
            or line.get('admission_status') != 'NOT_EVALUATED'
            or line.get('existing_rows_preserved') is not True
            or line.get('successor_derived_fields_recomputed') is not False
            or line.get('scale_applied') != 1 or line.get('conversion_applied') is not False
            or receipt.get('schema_version') != 'v5.hk02_internal_gap_receipt.v1'
            or receipt.get('status') != 'COMMITTED' or receipt.get('formal_eligibility_verified') is not False
            or receipt.get('manifest_sha256') != wanted[manifest_relative]
            or receipt.get('panel_sha256') != manifest['panel_sha256']
            or receipt.get('request_sha256') != line['request_sha256']
            or parent.get('panel_relative') != line['parent_panel_relative']
            or parent.get('panel_sha256') != line['parent_panel_sha256']
            or parent.get('panel_max_date') != day
            or manifest.get('parent_panel_sha256') != line['parent_panel_sha256']
            or any(doc.get(k) is not v for doc in (manifest, line, receipt) for k, v in SAFETY.items())
            or not aware(line['capture_finished_at']) <= aware(manifest['manifest_prepared_at']) <= aware(receipt['finished_at']) <= aware(cutoff)):
        raise ValueError('REPAIR_READER_LINEAGE')
    expected_dir = day+('-raw-repair-' if raw_input else '-native-repair-')+manifest['panel_sha256'][:12]
    if (manifest_relative != 'panels/'+expected_dir+'/manifest.json'
            or panel_relative != 'panels/'+expected_dir+'/hkconnect_vipdoc_daily_panel.parquet'):
        raise ValueError('REPAIR_READER_PATH_IDENTITY')
    allowed_dates = set(_history_window(day)['prior60'])
    if (type(line['added_rows']) is not int or line['added_rows'] <= 0
            or line['added_rows'] != len(line['repaired_keys'])
            or len({(r['code'], r['date']) for r in line['repaired_keys']}) != line['added_rows']
            or any(trade_date(r['date']) not in allowed_dates for r in line['repaired_keys'])
            or manifest['new_row_count'] != line['added_rows']
            or manifest['panel_rows'] != parent['panel_rows']+line['added_rows']):
        raise ValueError('REPAIR_READER_ROW_COUNTS')
    sha(line['capture_sha256']); sha(line['request_sha256'])
    evidence_keys = set()
    for record in line['row_evidence']:
        key = (record['code'], trade_date(record['date']))
        if not re.fullmatch(r'HK\.\d{5}', key[0]) or key in evidence_keys:
            raise ValueError('REPAIR_READER_ROW_EVIDENCE')
        if raw_input:
            exact_keys(record, ('code', 'date', 'raw_file', 'raw_file_sha256', 'record_pointer',
                                'source_row_index', 'source_row_sha256'))
            if (line['raw_files'].get(record['raw_file']) != record['raw_file_sha256']
                    or type(record['source_row_index']) is not int or record['source_row_index'] < 0
                    or not isinstance(record['record_pointer'], str)
                    or not any(s == dict(relative=record['raw_file'], sha256=record['raw_file_sha256'],
                                         record_pointer=record['record_pointer']) for s in line['raw_sources'])):
                raise ValueError('REPAIR_READER_RAW_ROW_EVIDENCE')
            sha(record['source_row_sha256'])
        else:
            exact_keys(record, ('code', 'date', 'raw_file', 'raw_file_sha256', 'record_offset', 'record_sha256'))
            if (record['raw_file'] != 'vipdoc/ds/lday/71#'+key[0][3:]+'.day'
                    or line['native_files'].get(record['raw_file']) != record['raw_file_sha256']
                    or type(record['record_offset']) is not int or record['record_offset'] < 0
                    or record['record_offset'] % 32):
                raise ValueError('REPAIR_READER_ROW_EVIDENCE')
            sha(record['record_sha256'])
        sha(record['raw_file_sha256'])
        evidence_keys.add(key)
    if evidence_keys != {(r['code'], r['date']) for r in line['repaired_keys']}:
        raise ValueError('REPAIR_READER_ROW_EVIDENCE')
    files = line['raw_files'] if raw_input else line['native_files']
    if set(files) != {record['raw_file'] for record in line['row_evidence']}:
        raise ValueError('REPAIR_READER_NATIVE_FILE_SCOPE')
    if raw_input:
        from . import rebound_raw_repair
        if line['decoder_source_sha256'] != rebound_raw_repair.DECODER_SHA or line['native_files']:
            raise ValueError('REPAIR_READER_RAW_DECODER_BINDING')
    # A self-consistent manifest is not evidence that old values were retained.
    # This read-only path also works inside the observation's private guard.
    import pandas as pd
    parent_frame = pd.read_parquet(checked_path(root, line['parent_panel_relative']))
    child_frame = pd.read_parquet(checked_path(root, panel_relative))
    required = {'code_norm', 'trade_date_compact'}
    if (not required.issubset(parent_frame.columns) or not required.issubset(child_frame.columns)
            or len(parent_frame) != parent['panel_rows'] or len(child_frame) != manifest['panel_rows']
            or not set(parent_frame.columns).issubset(child_frame.columns)):
        raise ValueError('REPAIR_READER_ACTUAL_ROWS')
    parent_keys = list(zip(parent_frame.code_norm.astype(str), parent_frame.trade_date_compact.astype(str)))
    child_keys = list(zip(child_frame.code_norm.astype(str), child_frame.trade_date_compact.astype(str)))
    if (len(set(parent_keys)) != len(parent_keys) or len(set(child_keys)) != len(child_keys)
            or child_keys[:len(parent_keys)] != parent_keys
            or set(child_keys[len(parent_keys):]) != evidence_keys
            or int(child_frame.code_norm.nunique()) != manifest['panel_code_count']):
        raise ValueError('REPAIR_READER_ACTUAL_KEY_DELTA')
    try:
        pd.testing.assert_frame_equal(
            child_frame.iloc[:len(parent_frame)][parent_frame.columns].reset_index(drop=True),
            parent_frame.reset_index(drop=True), check_dtype=False, check_exact=True)
    except AssertionError as error:
        raise ValueError('REPAIR_READER_EXISTING_VALUES_CHANGED') from error
    for relative in (line['parent_panel_relative'], panel_relative):
        if owner_io._file(root, relative)['sha256'] != wanted[relative]:
            raise ValueError('REPAIR_READER_INPUT_CHANGED_DURING_DECODE')
    return dict(owner='V4_SHARED_HK_0_2_PANEL_AUTHORITY_WITH_V5_REPAIR_EXTENSION',
        panel_manifest_path=str(checked_path(root, manifest_relative)), panel_manifest_sha256=wanted[manifest_relative],
        panel_path=str(checked_path(root, panel_relative)), panel_sha256=manifest['panel_sha256'],
        panel_max_date=day, panel_rows=manifest['panel_rows'], panel_code_count=manifest['panel_code_count'],
        panel_available_at=manifest['manifest_prepared_at'], source_contract=manifest['source_contract'],
        price_currency=None, price_basis='UNVERIFIED_NATIVE', session_kind='UNVERIFIED_DAILY_RECORD', amount_unit=None,
        resolution='EXPLICIT_SHA_BOUND_REPAIRED_REVISION', semantics='RAW_REPAIR_BYTES_NOT_FINANCIAL_ATTESTATION')


def update_hk_0_2_panel_from_vipdoc(module, asset_root, *, tdx_root, through_date,
                                  repair=None, authority=None, **normal_options):
    """The original writer's replacement call site, not an extra producer.

    ALL append/repair writers must enter this wrapper for mutual exclusion.
    Existing V4 consumers need the explicit repaired-panel reader installed
    before activating this extension. Deployment is the parent's Mac task.
    """
    _verify_owner(module)
    root = no_symlinks(asset_root)
    with _writer_lock(root) as directory:
        if repair is None:
            return module.update_hk_0_2_panel_from_vipdoc(root, tdx_root=tdx_root,
                                                       through_date=through_date, **normal_options)
        if normal_options: raise ValueError('REPAIR_APPEND_OPTIONS_NOT_APPLICABLE')
        _request(repair, through_date)
        raw_input = repair['schema_version'] == 'v5.hk02_pytdx_raw_repair_request.v1'
        result_status = 'REPAIRED_RAW_ROWS' if raw_input else 'REPAIRED_NATIVE_ROWS'
        _capture(authority, repair, root)
        current_pointer = owner_io._json(_read(root, 'panel_latest.json'))
        current_relative = str(current_pointer.get('manifest_relative', ''))
        current = owner_io._json(_read(root, current_relative))
        if (current.get('source_contract') in (SOURCE_CONTRACT, RAW_SOURCE_CONTRACT)
                and current.get('internal_gap_repair', {}).get('request_sha256') == sha256_json(repair)):
            line = current['internal_gap_repair']
            receipt_relative = str(Path(current_relative).with_name('receipt.json'))
            receipt_raw = _read(root, receipt_relative)
            expected = {current_relative: sha256_json(current), current['panel_relative']: current['panel_sha256'],
                receipt_relative: hashlib.sha256(receipt_raw).hexdigest(),
                line['parent_manifest_relative']: repair['parent_manifest_sha256'],
                line['parent_panel_relative']: repair['parent_panel_sha256']}
            read_repaired_panel_witness(root, current_relative, expected_files=expected,
                                        cutoff=datetime.now(timezone.utc).isoformat())
            # The original loader independently rechecks its panel/model assets.
            if module.load_frozen_hk_0_2_assets(root).panel_manifest != current:
                raise ValueError('REPAIR_OWNER_READBACK_MISMATCH')
            return dict(status=result_status, reused=True, through_date=through_date,
                panel_sha256=current['panel_sha256'], manifest_relative=current_relative,
                manifest_sha256=expected[current_relative], receipt_relative=receipt_relative,
                receipt_sha256=expected[receipt_relative], new_row_count=current['new_row_count'],
                formal_eligibility_verified=False, **SAFETY)
        built = prepare_internal_gap_repair(module, root, tdx_root=tdx_root, request=repair, authority=authority)
        import pandas as pd
        with tempfile.TemporaryDirectory(prefix='.hk02-repair-', dir=root) as temporary:
            staging = Path(temporary) / 'hkconnect_vipdoc_daily_panel.parquet'
            built['frame'].to_parquet(staging, index=False)
            readback = pd.read_parquet(staging)
            pd.testing.assert_frame_equal(readback, built['frame'], check_dtype=False, check_exact=True)
            pd.testing.assert_frame_equal(readback.iloc[:len(built['existing'])][built['existing'].columns].reset_index(drop=True),
                                          built['existing'].reset_index(drop=True), check_dtype=False, check_exact=True)
            digest = module.sha256_file(staging)
            if owner_io._file(Path(temporary), staging.name)['sha256'] != digest:
                raise ValueError('REPAIR_STAGED_PANEL_CHANGED')
            relative = 'panels/'+through_date+('-raw-repair-' if raw_input else '-native-repair-')+digest[:12]
            manifest = dict(asset_schema_version='v3_shared_data.hk_0_2_panel_asset.v2',
                source_contract=RAW_SOURCE_CONTRACT if raw_input else SOURCE_CONTRACT, increment_contract='v5.hk02_internal_gap_repair.v1',
                panel_relative=relative+'/hkconnect_vipdoc_daily_panel.parquet', panel_sha256=digest,
                parent_panel_sha256=repair['parent_panel_sha256'], panel_max_date=through_date,
                panel_rows=len(readback), panel_code_count=int(readback['code_norm'].nunique()),
                manifest_prepared_at=datetime.now(timezone.utc).isoformat(),
                new_row_count=len(repair['keys']), new_dates=sorted({r['date'] for r in repair['keys']}),
                internal_gap_repair=built['lineage'], **SAFETY)
            mraw = canonical_bytes(manifest)
            receipt = dict(schema_version='v5.hk02_internal_gap_receipt.v1', status='COMMITTED',
                request_sha256=sha256_json(repair), panel_sha256=digest,
                manifest_sha256=hashlib.sha256(mraw).hexdigest(),
                finished_at=datetime.now(timezone.utc).isoformat(), formal_eligibility_verified=False, **SAFETY)
            # Recheck original pointer, panel and model before any publication.
            _parent(module, root, repair)
            panels = _directory(directory, 'panels')
            try: revision = _directory(panels, Path(relative).name)
            finally: os.close(panels)
            try:
                # Bounded original files are <512MiB; create-once prevents overwrite.
                try: existing_panel = owner_io._file(root, relative+'/hkconnect_vipdoc_daily_panel.parquet')
                except FileNotFoundError: existing_panel = None
                if existing_panel is not None:
                    if existing_panel['sha256'] != digest: raise ValueError('REPAIR_IMMUTABLE_PANEL_CONFLICT')
                else:
                    _write_once(revision, 'hkconnect_vipdoc_daily_panel.parquet', staging.read_bytes())
                try: previous_raw = _read_at(revision, None, 'manifest.json')
                except FileNotFoundError: previous_raw = None
                if previous_raw is not None:
                    previous = owner_io._json(previous_raw)
                    if previous != dict(manifest, manifest_prepared_at=previous.get('manifest_prepared_at')):
                        raise ValueError('REPAIR_IMMUTABLE_MANIFEST_CONFLICT')
                    manifest, mraw = previous, previous_raw
                    receipt['manifest_sha256'] = hashlib.sha256(mraw).hexdigest()
                _write_once(revision, 'manifest.json', mraw)
                try: previous_receipt_raw = _read_at(revision, None, 'receipt.json')
                except FileNotFoundError: previous_receipt_raw = None
                if previous_receipt_raw is not None:
                    previous = owner_io._json(previous_receipt_raw)
                    if previous != dict(receipt, finished_at=previous.get('finished_at')):
                        raise ValueError('REPAIR_IMMUTABLE_RECEIPT_CONFLICT')
                    receipt = previous
                _write_once(revision, 'receipt.json', canonical_bytes(receipt))
            finally: os.close(revision)
            expected_files = {relative+'/manifest.json': hashlib.sha256(mraw).hexdigest(),
                relative+'/hkconnect_vipdoc_daily_panel.parquet': digest,
                relative+'/receipt.json': sha256_json(receipt),
                repair['parent_manifest_relative']: repair['parent_manifest_sha256'],
                repair['parent_panel_relative']: repair['parent_panel_sha256']}
            read_repaired_panel_witness(root, relative+'/manifest.json', expected_files=expected_files,
                                        cutoff=datetime.now(timezone.utc).isoformat())
            _parent(module, root, repair)
            pointer_raw = canonical_bytes(dict(manifest_relative=relative+'/manifest.json'))
            temporary_pointer = '.panel-latest-'+uuid.uuid4().hex+'.tmp'
            _write_once(directory, temporary_pointer, pointer_raw)
            try:
                # CAS is valid only while all original writers share this lock.
                if hashlib.sha256(_read_at(directory, None, 'panel_latest.json')).hexdigest() != repair['parent_pointer_sha256']:
                    raise ValueError('REPAIR_POINTER_CAS_CONFLICT')
                os.replace(temporary_pointer, 'panel_latest.json', src_dir_fd=directory, dst_dir_fd=directory)
                os.fsync(directory)
            finally:
                try: os.unlink(temporary_pointer, dir_fd=directory)
                except FileNotFoundError: pass
        actual = module.load_frozen_hk_0_2_assets(root)
        if actual.panel_manifest != manifest: raise ValueError('REPAIR_OWNER_READBACK_MISMATCH')
        return dict(status=result_status, reused=False, through_date=through_date, panel_sha256=digest,
            manifest_relative=relative+'/manifest.json', manifest_sha256=receipt['manifest_sha256'],
            receipt_relative=relative+'/receipt.json', receipt_sha256=sha256_json(receipt),
            new_row_count=len(repair['keys']), formal_eligibility_verified=False, **SAFETY)
