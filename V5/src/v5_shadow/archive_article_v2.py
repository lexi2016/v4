"""New-capture archive extension; original store/validator and issuer logic remain owners.

No network or classification. The CLI publishes only to an explicit marked private
root. Every v2 read rechecks page bytes, exact topic/body, original summary identity,
and acquisition clocks before the frozen archive store can return its payload.
"""
import copy
from datetime import datetime
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import sys
import subprocess
from zoneinfo import ZoneInfo

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from v5_shadow.digests import canonical_bytes, sha256_json, MAX_JSON_BYTES
from v5_shadow.archive_builder_v1 import BUILDER_PATTERN, verify_builder

SCHEMA = 'v5.research_archive.v2'
SHANGHAI = ZoneInfo('Asia/Shanghai')
CAPTURE_PATTERN = r'external_sources/zsxq_hourly/[0-9_]{10,64}/(?:zsxq_recent_topics_fetch_result|zsxq_recent_topics|zsxq_summary|acquisition_receipt\.v3|pages/[0-9]{4})\.json'
INPUT_PATTERN = r'acquisition/[0-9a-f]{64}\.json'


def stamp(value):
    if not isinstance(value, str):
        raise ValueError('ARTICLE_V2_TIME_MISSING')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.utcoffset() is None:
        raise ValueError('ARTICLE_V2_TIME_NAIVE')
    return parsed


def read_bound(read, ref):
    if not isinstance(ref, dict) or set(ref) != {'path', 'sha256', 'bytes'}:
        raise ValueError('ARTICLE_V2_FILE_BINDING')
    if not re.fullmatch(CAPTURE_PATTERN + '|' + INPUT_PATTERN + '|' + BUILDER_PATTERN, ref['path']):
        raise ValueError('ARTICLE_V2_FILE_PATH')
    raw = read(ref['path'])
    if (type(ref['bytes']) is not int or len(raw) != ref['bytes']
            or hashlib.sha256(raw).hexdigest() != ref['sha256']):
        raise ValueError('ARTICLE_V2_FILE_SHA')
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError('ARTICLE_V2_OBJECT_REQUIRED')
    return value


def capture(read, receipt_ref):
    receipt = read_bound(read, receipt_ref)
    manifest = json.loads((Path(__file__).resolve().parents[2] /
                          'producers/archive-acquisition-v2/manifest.json').read_bytes())
    if (receipt.get('schema_version') != 'v5.zsxq_acquisition_receipt.v3'
            or receipt.get('producer_sha256') != manifest['after_sha256']
            or receipt.get('response_representation') != 'CLI_STDOUT_TEXT_UTF8_AFTER_BOM_REMOVAL'
            or receipt.get('historical_pit_claimed') is not False
            or receipt.get('production_allowed') is not False
            or receipt.get('buy_gate_updated') is not False
            or receipt.get('orders_sent') is not False):
        raise ValueError('ARTICLE_V2_NEW_PRODUCER_REQUIRED')
    prefix = 'external_sources/zsxq_hourly/' + str(receipt.get('run_id')) + '/'
    if receipt_ref['path'] != prefix + 'acquisition_receipt.v3.json':
        raise ValueError('ARTICLE_V2_RUN_BINDING')
    started = stamp(receipt['acquisition_started_at'])
    ended = stamp(receipt['retrieval_completed_at'])
    available = stamp(receipt['source_payloads_available_at'])
    if not started <= ended <= available <= datetime.now(SHANGHAI):
        raise ValueError('ARTICLE_V2_CLOCK_ORDER')
    names = ['zsxq_recent_topics_fetch_result.json', 'zsxq_recent_topics.json', 'zsxq_summary.json']
    if set(receipt['files']) != {prefix + name for name in names}:
        raise ValueError('ARTICLE_V2_PAYLOAD_SET')
    payloads = {name: read_bound(read, dict(path=prefix + name, **receipt['files'][prefix + name])) for name in names}
    pages = receipt.get('pages')
    if not isinstance(pages, list) or not pages or len(pages) > 400:
        raise ValueError('ARTICLE_V2_PAGE_EVIDENCE_MISSING')
    observations = []
    previous = started
    for index, page in enumerate(pages):
        if set(page) != {'path', 'sha256', 'bytes', 'group_id', 'retrieved_at'}:
            raise ValueError('ARTICLE_V2_PAGE_FIELDS')
        if page['path'] != prefix + f'pages/{index:04d}.json':
            raise ValueError('ARTICLE_V2_PAGE_SEQUENCE')
        if not isinstance(page['group_id'], str) or not re.fullmatch(r'[0-9]{1,64}', page['group_id']):
            raise ValueError('ARTICLE_V2_GROUP_ID')
        at = stamp(page['retrieved_at'])
        if not previous <= at <= ended:
            raise ValueError('ARTICLE_V2_PAGE_CLOCK')
        previous = at
        content = read_bound(read, {key: page[key] for key in ('path', 'sha256', 'bytes')})
        rows = content.get('topics_brief') or content.get('topics') or []
        if not isinstance(rows, list):
            raise ValueError('ARTICLE_V2_PAGE_ROWS')
        for raw in rows:
            if not isinstance(raw, dict):
                continue
            explicit_groups = [raw['group_id']] if 'group_id' in raw else []
            if 'group' in raw:
                if not isinstance(raw['group'], dict):
                    raise ValueError('ARTICLE_V2_RESPONSE_GROUP_INVALID')
                if 'group_id' in raw['group']:
                    explicit_groups.append(raw['group']['group_id'])
            if any(isinstance(group, bool) or not isinstance(group, (str, int))
                   or str(group) != page['group_id'] for group in explicit_groups):
                raise ValueError('ARTICLE_V2_RESPONSE_GROUP_MISMATCH')
            topic = str(raw.get('topic_id') or raw.get('id') or '')
            if not re.fullmatch(r'[0-9]{17}', topic):
                continue
            body = raw.get('content') or raw.get('text') or raw.get('plain_text')
            if not isinstance(body, str) or not body.strip():
                continue  # attachment-only rows cannot acquire an invented body
            observations.append(dict(topic_id=topic, group_id=page['group_id'], raw=raw,
                body=body, raw_sha256=sha256_json(raw), page=page,
                published_at=raw.get('create_time'), retrieved_at=page['retrieved_at']))
    return receipt, payloads, observations


def collector_code(value):
    # Exact normalization from the pinned original _zsxq_rows collector.
    text = str(value or '').strip().upper()
    digits = ''.join(character for character in text if character.isdigit())
    return digits[-6:] if len(digits) >= 6 else digits


def collector_name(value):
    return re.sub(r'[（(].*?[）)]', '', str(value or '')).replace(' ', '').strip()


def enrich(original, receipt_ref, input_ref, read, generated_at, *, builder_source=None, builder_receipt=None):
    receipt, payloads, observations = capture(read, receipt_ref)
    available_at = receipt['source_payloads_available_at']
    available = stamp(available_at)
    if (original['archive_date'] != available.astimezone(SHANGHAI).strftime('%Y%m%d')
            or not receipt['run_id'].startswith(original['archive_date'] + '_')):
        raise ValueError('ARTICLE_V2_NEW_CAPTURE_DATE_REQUIRED')
    if not available <= stamp(generated_at) <= datetime.now(SHANGHAI):
        raise ValueError('ARTICLE_V2_IMPORT_CLOCK')
    recent = payloads['zsxq_recent_topics.json'].get('topics_brief')
    summary = payloads['zsxq_summary.json'].get('effective_topics')
    if (not isinstance(recent, list) or not isinstance(summary, list)
            or any(not isinstance(r, dict) or not isinstance(r.get('group'), dict) for r in recent)
            or any(not isinstance(r, dict) for r in summary)):
        raise ValueError('ARTICLE_V2_ORIGINAL_SUMMARY_REQUIRED')
    result = copy.deepcopy(original)
    result.update(schema_version=SCHEMA, acquisition_receipt=copy.deepcopy(receipt_ref),
                  archive_input_v1=copy.deepcopy(input_ref), source_generated_at=generated_at)
    run = re.fullmatch(r'([0-9]{8})_([0-9]{4})00_[0-9]{12}', receipt['run_id'])
    if run is None:
        raise ValueError('ARTICLE_V2_RUN_FORMAT')
    source_path = (f'research_module/runtime_outputs/zsxq_hourly/{run[1]}/{run[2]}/'
                   f'v35_zsxq_hourly_status_{run[1]}_{run[2]}.json')
    for article in result['articles']:
        if article.get('source_path_sha256') != hashlib.sha256(source_path.encode()).hexdigest():
            raise ValueError('ARTICLE_V2_SOURCE_PATH_BINDING')
        if article.get('source_type') != 'zsxq' or article.get('source_name') != '知识星球':
            raise ValueError('ARTICLE_V2_SOURCE_IDENTITY')
        # Original collector's stable topic URL; no title-only/fuzzy/body substitution.
        match = re.fullmatch(r'https://wx\.zsxq\.com/dweb2/index/topic_detail/([0-9]{17})', article.get('url', ''))
        if not match:
            raise ValueError('ARTICLE_V2_TOPIC_URL_REQUIRED')
        topic_id = match.group(1)
        candidates = [o for o in observations if o['topic_id'] == topic_id
                      and stamp(o['published_at']).replace(microsecond=0) == stamp(article['published_at'])]
        # Repeated pages or duplicate topic IDs fail closed until an exact page selection
        # contract exists. Do not select a convenient body from a collision.
        if len(candidates) != 1:
            raise ValueError('ARTICLE_V2_TOPIC_BINDING_NOT_UNIQUE')
        observation = candidates[0]
        selected = [r for r in recent if str(r.get('topic_id') or r.get('id')) == topic_id
                    and r.get('group', {}).get('group_id') == observation['group_id']]
        expected = {**observation['raw'], 'group': selected[0]['group']} if len(selected) == 1 else None
        if len(selected) != 1 or selected[0] != expected:
            raise ValueError('ARTICLE_V2_RECENT_RAW_MISMATCH')
        analyzed = [r for r in summary if str(r.get('topic_id')) == topic_id
                    and r.get('title') == article['source_title']
                    and stamp(r.get('create_time')) == stamp(observation['published_at'])]
        if len(analyzed) != 1:
            raise ValueError('ARTICLE_V2_SUMMARY_BINDING_NOT_UNIQUE')
        topic = analyzed[0]
        companies = topic.get('companies')
        if isinstance(companies, dict): companies = [companies]
        if not isinstance(companies, list): companies = []
        # Exact original company identity plus raw prose anchoring. Original native
        # issuer/proposition parser still decides whether any US relation is usable.
        company = [c for c in companies if isinstance(c, dict)
                   and collector_code(c.get('code')) == article['stock_code']
                   and collector_name(c.get('name')) == article['stock_name']]
        body = observation['body']
        evidence = article.get('evidence_sentence')
        if (len(company) != 1 or not article['stock_name'] or article['stock_name'] not in body
                or not isinstance(evidence, str) or not evidence.strip() or evidence not in body):
            raise ValueError('ARTICLE_V2_ISSUER_BODY_BINDING')
        themes = topic.get('themes') or []
        theme = ' / '.join(str(t.get('theme') or '').strip() for t in themes
                           if isinstance(t, dict) and str(t.get('theme') or '').strip())
        if article['theme'] != theme:
            raise ValueError('ARTICLE_V2_ORIGINAL_THEME_MISMATCH')
        retrieved_at = observation['retrieved_at']
        if not stamp(observation['published_at']) <= stamp(retrieved_at) <= available:
            raise ValueError('ARTICLE_V2_ARTICLE_CLOCK')
        # Original collector/builder truncate to seconds. Verify that conversion
        # above, but preserve full source precision for all v2 PIT consumers.
        article.update(published_at=observation['published_at'],
            body_text=body, retrieved_at=retrieved_at, available_at=available_at,
            collected_at=retrieved_at, first_seen_at=retrieved_at,
            acquisition_v2=dict(topic_id=topic_id, group_id=observation['group_id'],
                page_sha256=observation['page']['sha256'], raw_topic_sha256=observation['raw_sha256'],
                body_sha256=hashlib.sha256(body.encode()).hexdigest(),
                summary_topic_sha256=sha256_json(topic), issuer_identity_status='ORIGINAL_CONSUMER_MUST_VERIFY'))
    # The existing article/body/PIT gates above retain their original rejection
    # reasons. Complete owner-source and original-builder verification still
    # precedes every write and runs again on each independent v2 read.
    owner = verify_builder(original, builder_source, builder_receipt, receipt_ref, read)
    if stamp(owner['source_available_at']) > stamp(generated_at):
        raise ValueError('ARTICLE_V2_IMPORT_CLOCK')
    result.update(builder_source=copy.deepcopy(builder_source),
                  builder_receipt=copy.deepcopy(builder_receipt))
    # Preserve original pool/algorithm; only the article evidence is admitted here.
    return result


def install_validator(read):
    """Install an explicit version dispatcher before the original store imports it."""
    contract = importlib.import_module('contracts.research')
    original_validate = contract.validate_research_archive
    def validate(payload):
        if payload.get('schema_version') != SCHEMA:
            return original_validate(payload)
        original = read_bound(read, payload.get('archive_input_v1'))
        if original.get('schema_version') != 'v3_5.research_archive.v1':
            raise ValueError('ARTICLE_V2_ORIGINAL_V1_REQUIRED')
        day = original_validate(original)
        expected = enrich(original, payload.get('acquisition_receipt'), payload['archive_input_v1'],
                          read, payload.get('source_generated_at'),
                          builder_source=payload.get('builder_source'),
                          builder_receipt=payload.get('builder_receipt'))
        if payload != expected or canonical_bytes(payload) != canonical_bytes(expected):
            raise ValueError('ARTICLE_V2_ARTICLE_OR_PAYLOAD_CHANGED')
        return day
    contract.validate_research_archive = validate
    return original_validate


def publish(request):
    """Called only in its own CLI process; no module cache shared with manager."""
    from v5_shadow import archive_reader
    from v5_shadow.current_us_research import _raw_file
    if not isinstance(request, dict) or not {'builder_source', 'builder_receipt'} <= set(request):
        raise ValueError('ARTICLE_V2_BUILDER_SOURCE_REQUIRED')
    if set(request) != {'capture_root', 'capture_files', 'receipt', 'archive_v1', 'output_root',
                        'builder_source', 'builder_receipt'}:
        raise ValueError('ARTICLE_V2_REQUEST_FIELDS')
    source = Path(request['capture_root'])
    output = Path(request['output_root'])
    for root in (source, output):
        if not root.is_absolute() or '..' in root.parts or any(p.is_symlink() for p in (root, *root.parents)):
            raise ValueError('ARTICLE_V2_PRIVATE_ROOT')
    if source == output or source in output.parents or output in source.parents:
        raise ValueError('ARTICLE_V2_ROOT_OVERLAP')
    if _raw_file(output, '.v5-archive-article-v2') != b'v5.archive-article.v2\n':
        raise ValueError('ARTICLE_V2_OUTPUT_MARKER')
    if set(os.listdir(output)) != {'.v5-archive-article-v2'}:
        raise ValueError('ARTICLE_V2_OUTPUT_NOT_FRESH')
    files = request['capture_files']
    if not isinstance(files, dict) or not files or len(files) > 500:
        raise ValueError('ARTICLE_V2_FILE_BOUND')
    snapshot = {}
    for relative, digest in files.items():
        if not re.fullmatch(CAPTURE_PATTERN + '|' + BUILDER_PATTERN, relative):
            raise ValueError('ARTICLE_V2_CAPTURE_PATH')
        raw = _raw_file(source, relative)
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError('ARTICLE_V2_CAPTURE_SHA')
        snapshot[relative] = raw
        if sum(map(len, snapshot.values())) > MAX_JSON_BYTES:
            raise ValueError('ARTICLE_V2_TOTAL_CAPTURE_SIZE')
    original = request['archive_v1']
    input_raw = canonical_bytes(original)
    input_ref = dict(path='acquisition/' + hashlib.sha256(input_raw).hexdigest() + '.json',
                     sha256=hashlib.sha256(input_raw).hexdigest(), bytes=len(input_raw))
    snapshot[input_ref['path']] = input_raw
    read = snapshot.__getitem__
    sys.meta_path.insert(0, archive_reader._Loader(archive_reader.sources()))
    original_validate = install_validator(read)
    original_validate(original)
    payload = enrich(original, request['receipt'], input_ref, read,
                     datetime.now(SHANGHAI).isoformat(timespec='microseconds'),
                     builder_source=request['builder_source'], builder_receipt=request['builder_receipt'])
    # Validation is complete before any writes. Original owner enforces conflicting
    # archive re-import rejection; private evidence files must also be immutable.
    store = importlib.import_module('infrastructure.research_store').ResearchArchiveStore(output)
    relative = store._relative(payload['archive_date'])
    if store._path(relative).exists() or relative in store._manifest():
        raise ValueError('ARTICLE_V2_EXISTING_DATE_NOT_REWRITTEN')
    for name, raw in snapshot.items():
        path = store._path(name)
        if path.exists():
            if store._io.read_bytes(name) != raw:
                raise ValueError('ARTICLE_V2_EXISTING_EVIDENCE_CONFLICT')
        else:
            store._io.write_bytes(name, raw)
        if store._io.read_bytes(name) != raw:
            raise ValueError('ARTICLE_V2_EVIDENCE_READBACK')
    result = store.publish(payload, mode='REPLAY')
    if canonical_bytes(store.read_exact(payload['archive_date'])) != canonical_bytes(payload):
        raise ValueError('ARTICLE_V2_ORIGINAL_STORE_READBACK')
    bound = {name: hashlib.sha256(raw).hexdigest() for name, raw in snapshot.items()}
    for name in ('manifest.json', result['payload_path'], result['receipt_path']):
        bound[name] = hashlib.sha256(store._io.read_bytes(name)).hexdigest()
    binding = dict(root=str(output), files=bound)
    independent = archive_reader.read_private(output, binding)
    if canonical_bytes(independent['records'].get(payload['archive_date'] + '/', {}).get('payload')) != canonical_bytes(payload):
        raise ValueError('ARTICLE_V2_INDEPENDENT_STORE_READBACK')
    return dict(schema_version='v5.archive_article_import.v2', archive_binding=binding,
                request_sha256=sha256_json(request), article_v2_source_sha256=archive_reader.article_v2_identity(),
                original_store=result, readback='MATCHED', natural_verified=False, historical_pit_claimed=False,
                production_allowed=False, buy_gate_updated=False, orders_sent=False)


def run_import(request):
    process = subprocess.run([sys.executable, '-I', '-B', str(Path(__file__).resolve())],
        input=canonical_bytes(request), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
    if len(process.stdout) > MAX_JSON_BYTES:
        raise ValueError('ARTICLE_V2_RESPONSE_SIZE')
    try:
        value = json.loads(process.stdout)
    except ValueError as exc:
        raise ValueError('ARTICLE_V2_RESPONSE_INVALID') from exc
    if process.returncode or value.get('readback') != 'MATCHED':
        raise ValueError('ARTICLE_V2_IMPORT_FAILED:' + str(value.get('reason', 'UNKNOWN')))
    from v5_shadow.archive_reader import article_v2_identity
    if (value.get('request_sha256') != sha256_json(request)
            or value.get('article_v2_source_sha256') != article_v2_identity()):
        raise ValueError('ARTICLE_V2_RESPONSE_IDENTITY')
    return value


if __name__ == '__main__':
    try:
        raw = sys.stdin.buffer.read(MAX_JSON_BYTES + 1)
        if len(raw) > MAX_JSON_BYTES: raise ValueError('ARTICLE_V2_REQUEST_SIZE')
        print(canonical_bytes(publish(json.loads(raw))).decode())
    except Exception as exc:
        print(json.dumps({'reason': type(exc).__name__ + ':' + str(exc)}))
        raise SystemExit(1)
