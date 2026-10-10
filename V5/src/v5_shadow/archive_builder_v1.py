"""Bind an original research-owner source to one explicit V5 acquisition.

The owner writes the authoritative source. Readonly verification replays its
unchanged normalization with bound IO and recorded wall clocks, then invokes the
unchanged archive builder. Neither an archive hash nor an owner label substitutes
for the complete source byte comparison. This CLI never fetches source data.
"""
import copy
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import importlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
from zoneinfo import ZoneInfo

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from v5_shadow.digests import canonical_bytes, sha256_json, MAX_JSON_BYTES

BASE = Path(__file__).resolve().parents[2]
CAPSULE = BASE / 'vendor/archive_builder_baseline'
DESCRIPTOR = BASE / 'contracts/archive_builder_source_manifest.json'
PIN = '6624676cc21ec1ec729e6b7ad6a52688d467aeda907db5870d26a62ceb920dea'
SCHEMA = 'v5.archive_builder_source_receipt.v1'
SHANGHAI = ZoneInfo('Asia/Shanghai')
BUILDER_PATTERN = (
    r'(?:research/hourly/source/[0-9a-f]{64}'
    r'|research/incoming/[0-9]{8}/[0-9]{4}'
    r'|research_module/runtime_outputs/zsxq_hourly/[0-9]{8}/[0-9]{4}/'
    r'v35_zsxq_hourly_status_[0-9]{8}_[0-9]{4}'
    r'|external_sources/zsxq_hourly/[0-9_]{10,64}/'
    r'(?:builder_source_receipt\.v1|builder_owner_result\.v1))\.json'
)
SAFETY = dict(natural_verified=False, historical_pit_claimed=False,
              production_allowed=False, buy_gate_updated=False, orders_sent=False)
CLOCK_SEQUENCE = [('domains.research_hourly', None),
                  ('domains.research_hourly', None),
                  ('ops.collect_hourly_research_input', 'Asia/Shanghai')]
_OWNER = None


def owner_sources():
    manifest = json.loads(DESCRIPTOR.read_bytes())
    if sha256_json(manifest) != PIN:
        raise ValueError('BUILDER_V1_OWNER_IDENTITY')
    result = {}
    for row in manifest['entries']:
        raw = (CAPSULE / row['relative_path']).read_bytes()
        if (len(raw) != row['bytes'] or hashlib.sha256(raw).hexdigest() != row['sha256']
                or hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest() != row['git_blob_sha']):
            raise ValueError('BUILDER_V1_OWNER_IDENTITY:' + row['relative_path'])
        result[row['relative_path']] = raw
    return result


def builder_identity():
    owner_sources()
    return dict(adapter_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                source_capsule_sha256=PIN)


def load_owner():
    """Only used in isolated children; existing archive dependency pins stay fixed."""
    global _OWNER
    from v5_shadow import archive_reader
    extra = owner_sources()
    sources = archive_reader.sources()
    for name, raw in extra.items():
        if name in sources and sources[name] != raw:
            raise ValueError('BUILDER_V1_OWNER_SOURCE_CONFLICT:' + name)
        sources[name] = raw
    if _OWNER is None:
        names = ('ops.collect_hourly_research_input', 'domains.research_hourly', 'domains.research')
        if any(name in sys.modules for name in names):
            raise ValueError('BUILDER_V1_OWNER_ALREADY_LOADED')
        sys.meta_path.insert(0, archive_reader._Loader(sources))
        _OWNER = tuple(importlib.import_module(name) for name in names)
    return _OWNER


def verify_archive(original, source, source_sha256):
    """Full original-builder comparison; never reconstruct source from an article."""
    expected = load_owner()[2].build_research_archive(
        copy.deepcopy(source), source_input_sha256=source_sha256)
    if original != expected or sha256_json(original) != sha256_json(expected):
        raise ValueError('BUILDER_V1_ARCHIVE_MISMATCH')
    return expected


def _ref(path, raw):
    return dict(path=path, sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))


def _read_ref(read, ref):
    from v5_shadow.archive_article_v2 import read_bound
    observed = []
    def once(name):
        raw = read(name)
        observed.append(raw)
        return raw
    value = read_bound(once, ref)
    return value, observed[0]


def _private_name(root):
    if (not isinstance(root, str) or not root.startswith('/')
            or '\\' in root or str(PurePosixPath(root)) != root or '..' in PurePosixPath(root).parts):
        raise ValueError('BUILDER_V1_CAPTURE_ROOT')
    return root


def _capture_context(read, receipt_ref, status_ref, capture_root):
    from v5_shadow.archive_article_v2 import capture
    receipt, payloads, _ = capture(read, receipt_ref)
    match = re.fullmatch(r'([0-9]{8})_([0-9]{4})00_[0-9]{12}', receipt['run_id'])
    if match is None:
        raise ValueError('BUILDER_V1_DATE_RUN_BINDING')
    day, slot = match[1], match[2]
    prefix = 'external_sources/zsxq_hourly/' + receipt['run_id'] + '/'
    status_name = (f'research_module/runtime_outputs/zsxq_hourly/{day}/{slot}/'
                   f'v35_zsxq_hourly_status_{day}_{slot}.json')
    status, _ = _read_ref(read, status_ref)
    paths = dict(run_dir=prefix[:-1], **{
        key: capture_root + '/' + prefix + name for key, name in (
            ('fetch_result', 'zsxq_recent_topics_fetch_result.json'),
            ('recent_topics', 'zsxq_recent_topics.json'), ('summary', 'zsxq_summary.json'))})
    if (status_ref['path'] != status_name or status.get('status_path') != status_name
            or status.get('schema_version') != 'v3_5.zsxq_hourly_delta.v1'
            or status.get('trade_date') != day or status.get('slot') != slot
            or status.get('latest_run_id') != receipt['run_id']
            or status.get('fetch_ok') is not True or status.get('status') not in ('READY', 'READY_EMPTY')
            or status.get('paths') != paths
            or status.get('acquisition_evidence_v2') != {
                'schema_version': 'v5.zsxq_acquisition_receipt.v3', **receipt_ref}
            or any(status.get(key) is not False for key in ('production_allowed', 'buy_gate_updated', 'orders_sent'))):
        raise ValueError('BUILDER_V1_STATUS_BINDING')
    required = {receipt_ref['path'], status_name, *receipt['files'], *(p['path'] for p in receipt['pages'])}
    return receipt, status, payloads['zsxq_summary.json'], required, day, slot


@contextmanager
def _globals(changes):
    previous = [(module, name, getattr(module, name)) for module, name, _ in changes]
    try:
        for module, name, value in changes:
            setattr(module, name, value)
        yield
    finally:
        for module, name, value in reversed(previous):
            setattr(module, name, value)


def _clock(module, calls, replay, cursor):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            zone = None if tz is None else str(tz)
            if replay is None:
                value = datetime.now(tz)
                offset = value.astimezone().utcoffset() if tz is None else value.utcoffset()
                calls.append(dict(module=module, timezone=zone, value=value.isoformat(),
                                  utc_offset_seconds=int(offset.total_seconds())))
                return value
            index = cursor[0]
            if index >= len(replay) or (replay[index]['module'], replay[index]['timezone']) != (module, zone):
                raise ValueError('BUILDER_V1_CLOCK_TRANSCRIPT')
            cursor[0] += 1
            return datetime.fromisoformat(replay[index]['value'])
    return Clock


def _validate_clocks(receipt, acquisition):
    from v5_shadow.archive_article_v2 import stamp
    started = stamp(receipt['owner_started_at'])
    completed = stamp(receipt['owner_completed_at'])
    available = stamp(receipt['source_available_at'])
    if not (stamp(acquisition['source_payloads_available_at']) <= started <= completed
            <= available <= datetime.now(SHANGHAI)):
        raise ValueError('BUILDER_V1_CLOCK_TRANSCRIPT')
    calls = receipt.get('clock_calls')
    if not isinstance(calls, list) or len(calls) != len(CLOCK_SEQUENCE):
        raise ValueError('BUILDER_V1_CLOCK_TRANSCRIPT')
    previous = started
    for call, expected in zip(calls, CLOCK_SEQUENCE):
        if (not isinstance(call, dict)
                or set(call) != {'module', 'timezone', 'value', 'utc_offset_seconds'}
                or (call['module'], call['timezone']) != expected
                or type(call['utc_offset_seconds']) is not int
                or not -86400 < call['utc_offset_seconds'] < 86400):
            raise ValueError('BUILDER_V1_CLOCK_TRANSCRIPT')
        value = datetime.fromisoformat(call['value'])
        offset = timedelta(seconds=call['utc_offset_seconds'])
        if expected[1] is None:
            if value.utcoffset() is not None:
                raise ValueError('BUILDER_V1_CLOCK_TRANSCRIPT')
            instant = value.replace(tzinfo=timezone(offset))
        else:
            if value.utcoffset() != offset or offset != value.astimezone(SHANGHAI).utcoffset():
                raise ValueError('BUILDER_V1_CLOCK_TRANSCRIPT')
            instant = value
        if not previous <= instant <= completed:
            raise ValueError('BUILDER_V1_CLOCK_TRANSCRIPT')
        previous = instant


def _invoke_owner(root, status_ref, status, summary, day, slot, *, replay=None, source_raw=None, io=None):
    """Limit original owner's discovery to declared bytes; keep normalization intact."""
    collector, hourly, _ = load_owner()
    calls, cursor = [], [0]
    source_name = f'research/incoming/{day}/{slot}.json'
    summary_name = 'external_sources/zsxq_hourly/' + status['latest_run_id'] + '/zsxq_summary.json'
    bound_status = copy.deepcopy(status)
    bound_status['paths']['summary'] = str(root) + '/' + summary_name
    def latest(data_root, business_date, requested_slot):
        if str(data_root) != str(root) or (business_date, requested_slot) != (day, slot):
            raise ValueError('BUILDER_V1_OWNER_IO_BOUNDARY')
        if status['status'] != 'READY':
            return None  # Preserve original READY_EMPTY handling; no older run fallback.
        return path_type(str(root) + '/' + status_ref['path']), copy.deepcopy(bound_status)
    def read_json(path):
        if str(path) != str(root) + '/' + summary_name:
            raise ValueError('BUILDER_V1_OWNER_IO_BOUNDARY')
        return copy.deepcopy(summary)
    if replay is None and io is None:
        raise ValueError('BUILDER_V1_OWNER_IO_BOUNDARY')
    class BoundPath(PurePosixPath):
        def is_file(self):
            if str(self) != str(root) + '/' + summary_name:
                raise ValueError('BUILDER_V1_OWNER_IO_BOUNDARY')
            return True  # Only the already byte-bound summary is visible.
        def read_bytes(self):
            if str(self) != str(root) + '/' + source_name:
                raise ValueError('BUILDER_V1_OWNER_IO_BOUNDARY')
            return source_raw if replay is not None else io.read_bytes(source_name)
    path_type = BoundPath
    def destination(data_root, relative):
        if str(data_root) != str(root) or relative != source_name:
            raise ValueError('BUILDER_V1_OWNER_IO_BOUNDARY')
        return BoundPath(str(root) + '/' + relative)
    def publish_or_compare(path, payload):
        if str(path) != str(root) + '/' + source_name:
            raise ValueError('BUILDER_V1_OWNER_IO_BOUNDARY')
        # Exact pinned owner serialization at the V5 IO boundary. The original
        # owner alone constructs the complete object; its temporary Path writer
        # is replaced by the existing no-follow, no-replace SafeRoot primitive.
        encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode('utf-8')
        if len(encoded) > MAX_JSON_BYTES:
            raise ValueError('BUILDER_V1_INPUT_SIZE')
        if replay is not None:
            if encoded != source_raw:
                raise ValueError('BUILDER_V1_SOURCE_REPLAY_MISMATCH')
        else:
            io.write_bytes(source_name, encoded, require_absent=True)
            if io.read_bytes(source_name) != encoded:
                raise ValueError('BUILDER_V1_SOURCE_READBACK')
        return path
    changes = [(collector, '_latest_zsxq_status', latest), (collector, '_read_json', read_json),
               (collector, 'datetime', _clock('ops.collect_hourly_research_input', calls, replay, cursor)),
               (hourly, 'datetime', _clock('domains.research_hourly', calls, replay, cursor)),
               (collector, 'Path', BoundPath), (collector, 'resolve_owned_path', destination),
               (collector, '_atomic_json', publish_or_compare)]
    with _globals(changes):
        result = collector.build_hourly_research_input(
            data_root=path_type(root), business_date=day, slot=slot)
    if replay is not None and cursor[0] != len(replay):
        raise ValueError('BUILDER_V1_CLOCK_TRANSCRIPT')
    return result, calls


def verify_builder(original, source_ref, owner_ref, receipt_ref, read):
    if not isinstance(source_ref, dict) or not isinstance(owner_ref, dict):
        raise ValueError('ARTICLE_V2_BUILDER_SOURCE_REQUIRED')
    owner, _ = _read_ref(read, owner_ref)
    fields = {'schema_version', 'run_id', 'trade_date', 'slot', 'capture_root', 'capture_receipt',
              'status', 'builder_source', 'source_original', 'owner_result', 'files', 'owner_source_sha256',
              'owner_started_at', 'owner_completed_at', 'source_available_at', 'clock_calls', *SAFETY}
    if (set(owner) != fields or owner.get('schema_version') != SCHEMA or owner.get('owner_source_sha256') != PIN
            or any(owner.get(key) is not value for key, value in SAFETY.items())):
        raise ValueError('BUILDER_V1_OWNER_IDENTITY')
    capture_root = _private_name(owner.get('capture_root'))
    acquisition, status, summary, required, day, slot = _capture_context(
        read, receipt_ref, owner.get('status'), capture_root)
    prefix = 'external_sources/zsxq_hourly/' + acquisition['run_id'] + '/'
    if (owner_ref['path'] != prefix + 'builder_source_receipt.v1.json'
            or owner.get('capture_receipt') != receipt_ref or owner.get('builder_source') != source_ref
            or (owner.get('run_id'), owner.get('trade_date'), owner.get('slot')) != (acquisition['run_id'], day, slot)
            or original.get('archive_date') != day):
        raise ValueError('BUILDER_V1_DATE_RUN_BINDING')
    source, raw = _read_ref(read, source_ref)
    source_original, original_raw = _read_ref(read, owner.get('source_original'))
    result, _ = _read_ref(read, owner.get('owner_result'))
    source_name = f'research/incoming/{day}/{slot}.json'
    digest = hashlib.sha256(raw).hexdigest()
    if (source_ref['path'] != 'research/hourly/source/' + digest + '.json'
            or owner['source_original']['path'] != source_name or raw != original_raw
            or owner['owner_result']['path'] != prefix + 'builder_owner_result.v1.json'
            or result.get('source_path') != source_name or result.get('source_sha256') != digest
            or original.get('source_input_sha256') != digest):
        raise ValueError('BUILDER_V1_SOURCE_SHA')
    if (source.get('trade_date') != day or (result.get('business_date'), result.get('slot')) != (day, slot)
            or source.get('source_manifest', {}).get('hourly_slot') != slot):
        raise ValueError('BUILDER_V1_DATE_RUN_BINDING')
    files = owner.get('files')
    expected = required | {source_name, source_ref['path'], owner['owner_result']['path']}
    if not isinstance(files, dict) or set(files) != expected:
        raise ValueError('BUILDER_V1_FILE_SET')
    for name, ref in files.items():
        _read_ref(read, dict(path=name, **ref))
    for ref in (receipt_ref, owner['status'], source_ref, owner['source_original'], owner['owner_result']):
        if files.get(ref['path']) != {key: ref[key] for key in ('sha256', 'bytes')}:
            raise ValueError('BUILDER_V1_FILE_SET')
    _validate_clocks(owner, acquisition)
    replay_result, _ = _invoke_owner('/v5-bound-owner', owner['status'], status, summary, day, slot,
                                     replay=owner['clock_calls'], source_raw=raw)
    if result != replay_result or canonical_bytes(result) != canonical_bytes(replay_result):
        raise ValueError('BUILDER_V1_SOURCE_REPLAY_MISMATCH')
    verify_archive(original, source, digest)
    return owner


def publish_source(request):
    """Explicit V5 producer boundary around the original source owner; no fetch."""
    from v5_shadow.archive_article_v2 import CAPTURE_PATTERN, stamp
    from v5_shadow.current_us_research import _raw_file
    if not isinstance(request, dict) or set(request) != {'capture_root', 'capture_files', 'receipt', 'status'}:
        raise ValueError('BUILDER_V1_REQUEST_FIELDS')
    root = Path(_private_name(request['capture_root']))
    if any(path.is_symlink() for path in (root, *root.parents)):
        raise ValueError('BUILDER_V1_CAPTURE_ROOT')
    if _raw_file(root, '.v5-archive-acquisition') != b'v5.archive-acquisition.v2\n':
        raise ValueError('BUILDER_V1_CAPTURE_MARKER')
    files = request['capture_files']
    if not isinstance(files, dict) or not files or len(files) > 500:
        raise ValueError('BUILDER_V1_FILE_SET')
    snapshot = {}
    for name, digest in files.items():
        if not re.fullmatch(CAPTURE_PATTERN + '|' + BUILDER_PATTERN, name):
            raise ValueError('BUILDER_V1_FILE_SET')
        raw = _raw_file(root, name)
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError('ARTICLE_V2_CAPTURE_SHA')
        snapshot[name] = raw
        if sum(map(len, snapshot.values())) > MAX_JSON_BYTES:
            raise ValueError('BUILDER_V1_INPUT_SIZE')
    acquisition, status, summary, required, day, slot = _capture_context(
        snapshot.__getitem__, request['receipt'], request['status'], str(root))
    if set(snapshot) != required:
        raise ValueError('BUILDER_V1_FILE_SET')
    started = datetime.now(SHANGHAI).isoformat(timespec='microseconds')
    if (day != stamp(started).strftime('%Y%m%d')
            or stamp(acquisition['source_payloads_available_at']) > stamp(started)):
        raise ValueError('BUILDER_V1_DATE_RUN_BINDING')
    load_owner()
    store = importlib.import_module('infrastructure.data_store').NativeDataStore(root)
    source_name = f'research/incoming/{day}/{slot}.json'
    # All writes use the already pinned original SafeRoot descriptor boundary;
    # no real Path is passed to the owner's temporary-file writer. An exclusive
    # per-slot directory also makes a partial attempt explicit and non-reusable.
    with store._io.parent(f'research/incoming/{day}/{slot}.builder-v1', create=True) as (parent, name):
        os.mkdir(name, mode=0o700, dir_fd=parent)
    with store._io.parent(source_name) as (parent, name):
        try:
            os.stat(name, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise ValueError('BUILDER_V1_SOURCE_ALREADY_EXISTS')
    result, calls = _invoke_owner(root, request['status'], status, summary, day, slot, io=store._io)
    if result.get('source_path') != source_name or result.get('recovery') is not False:
        raise ValueError('BUILDER_V1_SOURCE_REUSED_OR_RECOVERED')
    raw = _raw_file(root, source_name)
    digest = hashlib.sha256(raw).hexdigest()
    if result.get('source_sha256') != digest:
        raise ValueError('BUILDER_V1_SOURCE_SHA')
    source = json.loads(raw)
    original = load_owner()[2].build_research_archive(copy.deepcopy(source), source_input_sha256=digest)
    completed = datetime.now(SHANGHAI).isoformat(timespec='microseconds')
    source_ref = _ref('research/hourly/source/' + digest + '.json', raw)
    original_ref = _ref(source_name, raw)
    prefix = 'external_sources/zsxq_hourly/' + acquisition['run_id'] + '/'
    result_raw = canonical_bytes(result)
    result_ref = _ref(prefix + 'builder_owner_result.v1.json', result_raw)
    additions = {source_name: raw, source_ref['path']: raw, result_ref['path']: result_raw}
    if sum(map(len, snapshot.values())) + sum(map(len, additions.values())) > MAX_JSON_BYTES:
        raise ValueError('BUILDER_V1_INPUT_SIZE')
    for name in (source_ref['path'], result_ref['path'], prefix + 'builder_source_receipt.v1.json'):
        if store._path(name).exists():
            raise ValueError('BUILDER_V1_EXISTING_EVIDENCE')
    for name in (source_ref['path'], result_ref['path']):
        store._io.write_bytes(name, additions[name], require_absent=True)
        if store._io.read_bytes(name) != additions[name]:
            raise ValueError('BUILDER_V1_SOURCE_READBACK')
    snapshot.update(additions)
    receipt = dict(schema_version=SCHEMA, run_id=acquisition['run_id'], trade_date=day, slot=slot,
        capture_root=str(root), capture_receipt=copy.deepcopy(request['receipt']), status=copy.deepcopy(request['status']),
        builder_source=source_ref, source_original=original_ref, owner_result=result_ref,
        files={name: {key: value for key, value in _ref(name, data).items() if key != 'path'}
               for name, data in snapshot.items()}, owner_source_sha256=PIN,
        owner_started_at=started, owner_completed_at=completed,
        source_available_at=datetime.now(SHANGHAI).isoformat(timespec='microseconds'), clock_calls=calls, **SAFETY)
    receipt_raw = canonical_bytes(receipt)
    receipt_ref = _ref(prefix + 'builder_source_receipt.v1.json', receipt_raw)
    snapshot[receipt_ref['path']] = receipt_raw
    if sum(map(len, snapshot.values())) > MAX_JSON_BYTES:
        raise ValueError('BUILDER_V1_INPUT_SIZE')
    # A source receipt is published only after complete readonly owner/builder
    # replay and a second byte check of every actual owner/capture file.
    verify_builder(original, source_ref, receipt_ref, request['receipt'], snapshot.__getitem__)
    for name, data in snapshot.items():
        if name != receipt_ref['path'] and _raw_file(root, name) != data:
            raise ValueError('BUILDER_V1_SOURCE_CHANGED')
    store._io.write_bytes(receipt_ref['path'], receipt_raw, require_absent=True)
    if store._io.read_bytes(receipt_ref['path']) != receipt_raw:
        raise ValueError('BUILDER_V1_SOURCE_READBACK')
    return dict(schema_version='v5.archive_builder_import_source.v1', capture_root=str(root),
        capture_files={name: hashlib.sha256(data).hexdigest() for name, data in snapshot.items()},
        receipt=copy.deepcopy(request['receipt']), builder_source=source_ref, builder_receipt=receipt_ref,
        archive_v1=original, readback='MATCHED', request_sha256=sha256_json(request),
        builder_identity=builder_identity(), **SAFETY)


def run_build(request):
    process = subprocess.run([sys.executable, '-I', '-B', str(Path(__file__).resolve())],
        input=canonical_bytes(request), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
    if len(process.stdout) > MAX_JSON_BYTES:
        raise ValueError('BUILDER_V1_RESPONSE_SIZE')
    try:
        value = json.loads(process.stdout)
    except ValueError as exc:
        raise ValueError('BUILDER_V1_RESPONSE_INVALID') from exc
    if process.returncode or value.get('readback') != 'MATCHED':
        raise ValueError('BUILDER_V1_OWNER_FAILED:' + str(value.get('reason', 'UNKNOWN')))
    if (value.get('request_sha256') != sha256_json(request)
            or value.get('builder_identity') != builder_identity()):
        raise ValueError('BUILDER_V1_RESPONSE_IDENTITY')
    return value


if __name__ == '__main__':
    try:
        raw = sys.stdin.buffer.read(MAX_JSON_BYTES + 1)
        if len(raw) > MAX_JSON_BYTES:
            raise ValueError('BUILDER_V1_REQUEST_SIZE')
        print(canonical_bytes(publish_source(json.loads(raw))).decode())
    except Exception as exc:
        print(json.dumps({'reason': type(exc).__name__ + ':' + str(exc)}))
        raise SystemExit(1)
