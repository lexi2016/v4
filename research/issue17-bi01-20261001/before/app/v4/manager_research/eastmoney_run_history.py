"""Bounded history for the EXISTING announcement owner and its original stores.

No provider, clock, master or eligibility replacement. Named immutable products
are commit points. Index observations preserve original MaterialStore metadata
before its latest-key pointer moves; GET never creates or repairs evidence.
"""
from __future__ import annotations
from copy import deepcopy
import json
import re
from typing import Any, Mapping
from .contracts import canonical_json
from .workspace_projection import FLAGS, date_token, digest, timestamp

PROTOCOL = 'EASTMONEY_RUN_AFTER_TERMINAL_JOURNAL_V1'
OBS_SCHEMA = 'v4.manager_research.eastmoney_index_observation.v1'
MAX_RUNS = 1024
MAX_PRODUCT_BYTES = 8 * 1024 * 1024
MAX_HISTORY_BYTES = 64 * 1024 * 1024
_RUN = re.compile(r'^[0-9a-f]{32}\.json$')
_ERRORS = (ValueError, RuntimeError, OSError, KeyError, TypeError, ImportError)


def _observation_path(ref: Mapping[str, Any]) -> str:
    return 'observations/eastmoney_hk/' + digest([
        ref.get('source_key'), ref.get('blob_sha256'), ref.get('retrieved_at')]) + '.json'


class _ObservedIndex:
    """Read a persisted original index observation, never fabricate one from ref."""
    def __init__(self, store: Any, ref: Mapping[str, Any]):
        self.store = store
        self.ref = ref
        self._io = store._io
        self._blob_relative = store._blob_relative

    def stat_source(self, source_key: str) -> dict | None:
        try:
            raw = self._io.read_bytes(_observation_path(self.ref), max_bytes=32768)
        except FileNotFoundError:
            return self.store.stat_source(source_key)  # Legacy: exact live index only.
        value = json.loads(raw)
        index = value.get('index') if isinstance(value, dict) else None
        if (not isinstance(index, dict) or value.get('schema_version') != OBS_SCHEMA
                or value.get('index_sha256') != digest(index)
                or index.get('source_key') != source_key):
            raise ValueError('EASTMONEY_HK_INDEX_OBSERVATION_INVALID')
        return index


def read_retained_response(store: Any, ref: Mapping[str, Any]) -> bytes:
    from .announcement_source import read_eastmoney_response
    return read_eastmoney_response(_ObservedIndex(store, ref), ref)


def product_refs(product: Mapping[str, Any]):
    for query in product['queries']:
        if isinstance(query.get('listing_ref'), dict):
            yield query['listing_ref']
    for doc in product['documents']:
        yield doc['row']['listing_ref']
        yield from doc['content_refs']
        yield doc['pdf_ref']


def retain_index_observations(store: Any, products: list[dict]) -> list[str]:
    """Writer only: copy exact valid index records; missing old clocks stay missing."""
    from .announcement_source import read_eastmoney_response, safe_reason
    gaps = []; seen = set()
    for product in products:
        for ref in product_refs(product):
            path = _observation_path(ref)
            if path in seen:
                continue
            seen.add(path)
            persisting=False
            try:
                # Existing observations must validate, not be overwritten/repaired.
                try:
                    store._io.read_bytes(path, max_bytes=32768)
                except FileNotFoundError:
                    read_eastmoney_response(store, ref)
                    index = store.stat_source(ref['source_key'])
                    if (not isinstance(index, dict) or index.get('sha256') != ref['blob_sha256']
                            or index.get('url') != ref['request']['url']
                            or index.get('retrieved_at') != ref['retrieved_at']):
                        raise ValueError('EASTMONEY_HK_INDEX_CHANGED_BEFORE_RETENTION')
                    value = dict(schema_version=OBS_SCHEMA, index=index, index_sha256=digest(index))
                    persisting=True
                    store._io.write_bytes(path, canonical_json(value), require_absent=True)
                    persisting=False
                index=_ObservedIndex(store,ref).stat_source(ref['source_key'])
                if not index or any(index.get(k)!=v for k,v in dict(sha256=ref['blob_sha256'],
                        url=ref['request']['url'],retrieved_at=ref['retrieved_at']).items()):
                    raise ValueError('EASTMONEY_HK_INDEX_OBSERVATION_BINDING_INVALID')
            except _ERRORS as exc:
                if persisting:
                    raise ValueError('EASTMONEY_HK_INDEX_RETENTION_WRITE_FAILED') from exc
                gaps.append(safe_reason(exc, 'EASTMONEY_HK_INDEX_RETENTION_FAILED'))
    return sorted(set(gaps))


def committed_products(service: Any, date: str) -> tuple[list[dict], list[dict], list[str]]:
    """Read committed named runs, including legacy runs with original journal proof.

    A latest pointer alone cannot rescue a missing/corrupt named new-protocol
    product. One bad run never removes another valid run.
    """
    from . import workspace_announcements as ann
    from .workspace import validate_attempt
    from .workspace_read_control import checkpoint
    date = date_token(date)
    root = f'workspace_announcements/{date}/eastmoney_hk'
    attempts = f'workspace_announcement_runs/{date}/eastmoney_hk'
    rows = []; rejected = []; gaps = []
    names = service.store._io.files(root)
    names = [name for name in names if _RUN.fullmatch(name)]
    if len(names) > MAX_RUNS:
        raise ValueError('EASTMONEY_HK_HISTORY_RUN_BUDGET')
    total = 0; latest = None; legacy_attempts = None
    try:
        latest = service.store._read(service.store.root/root/'latest.json')
    except _ERRORS as exc:
        gaps.append(ann.safe_reason(exc, 'EASTMONEY_HK_LATEST_INVALID'))
    # Legacy latest-only products remain readable, but never for the new protocol.
    if (isinstance(latest, dict) and not latest.get('commit_protocol')
            and _RUN.fullmatch(str(latest.get('run_id')) + '.json')
            and latest['run_id'] + '.json' not in names):
        names.append('latest.json')
    if (isinstance(latest, dict) and latest.get('commit_protocol')
            and str(latest.get('run_id'))+'.json' not in names):
        gaps.append('EASTMONEY_HK_LATEST_RUN_NOT_COMMITTED')
    for name in sorted(names):
        checkpoint()
        try:
            raw = service.store._io.read_bytes(root+'/'+name, max_bytes=MAX_PRODUCT_BYTES)
            total += len(raw)
            if total > MAX_HISTORY_BYTES:
                raise ValueError('EASTMONEY_HK_HISTORY_BYTE_BUDGET')
            product = ann._validate_eastmoney_product(json.loads(raw), date)
            if name != 'latest.json' and name != product['run_id']+'.json':
                raise ValueError('EASTMONEY_HK_RUN_FILENAME_MISMATCH')
            if product.get('commit_protocol') is not None:
                if product['commit_protocol'] != PROTOCOL:
                    raise ValueError('EASTMONEY_HK_COMMIT_PROTOCOL_INVALID')
                attempt_id = product.get('attempt_run_id')
                if not re.fullmatch(r'[0-9a-f]{32}', str(attempt_id)):
                    raise ValueError('EASTMONEY_HK_COMMIT_ATTEMPT_INVALID')
                proof = service.store._read(service.store.root/attempts/(attempt_id+'.json'))
                proof = validate_attempt(proof, date)
                if (proof.get('owner') != ann.OWNER or proof.get('source_scope') != ann.EASTMONEY_SCOPE
                        or proof.get('state') not in {'PARTIAL','SUCCEEDED','SUCCEEDED_EMPTY'}
                        or proof.get('product_sha256') != product['sha256']
                        or proof.get('product_run_id') != product['run_id']
                        or proof.get('last_success_at') != product['generated_at']):
                    raise ValueError('EASTMONEY_HK_RUN_NOT_COMMITTED')
            elif not (isinstance(latest, dict) and latest.get('sha256') == product['sha256']):
                if legacy_attempts is None:
                    attempt_names = service.store._io.files(attempts)
                    if len(attempt_names) > MAX_RUNS + 1:
                        raise ValueError('EASTMONEY_HK_HISTORY_ATTEMPT_BUDGET')
                    legacy_attempts = []
                    for n in attempt_names:
                        if not _RUN.fullmatch(n):
                            continue
                        try:
                            proof = validate_attempt(service.store._read(service.store.root/attempts/n), date)
                            if proof.get('source_scope') == ann.EASTMONEY_SCOPE:
                                legacy_attempts.append(proof)
                        except _ERRORS:
                            continue
                if not any(p.get('owner') == ann.OWNER
                        and p.get('state') in {'PARTIAL','SUCCEEDED','SUCCEEDED_EMPTY'}
                        and p.get('last_success_at') == product['generated_at']
                        and p.get('input_identity') == product['scope_identity'] for p in legacy_attempts):
                    raise ValueError('EASTMONEY_HK_LEGACY_COMMIT_EVIDENCE_MISSING')
            rows.append(product)
        except _ERRORS as exc:
            reason = ann.safe_reason(exc, 'EASTMONEY_HK_RUN_READBACK_FAILED')
            gaps.append(reason)
            rejected.append(dict(capture_trade_date=date, product_ref=root+'/'+name,
                source='EASTMONEY_HK', reason=reason))
            if total > MAX_HISTORY_BYTES:
                break
    return sorted(rows, key=lambda p:(timestamp(p['generated_at']), p['run_id'])), rejected, sorted(set(gaps))


def next_sweep(products: list[dict], names: Mapping, witness: Mapping, size: int) -> tuple[list[str], dict]:
    """Advance only from committed batches of this exact master/window universe."""
    universe = sorted(names); identity = digest([witness, universe]); start = 0; cycle = 1
    prior = None
    for product in products:
        sweep = product.get('sweep')
        if not isinstance(sweep, dict) or sweep.get('universe_identity') != identity:
            continue
        a, b, c = sweep.get('start_index'), sweep.get('next_index'), sweep.get('cycle')
        if (type(a) is not int or type(b) is not int or type(c) is not int
                or c < 1 or not 0 <= a < b <= len(universe)
                or product['scope'] != universe[a:b]):
            raise ValueError('EASTMONEY_HK_SWEEP_IDENTITY_INVALID')
        prior = sweep
    if prior:
        start = prior['next_index']; cycle = prior['cycle']
        if start == len(universe):
            start = 0; cycle += 1
    end = min(start + size, len(universe))
    return universe[start:end], dict(universe_identity=identity, cycle=cycle,
        start_index=start, next_index=end, master_issuer_count=len(universe),
        scheduled_issuer_count=end,
        visited_issuer_count=(prior.get('visited_issuer_count',0) if prior and start else 0),
        all_issuers_visited=False,
        visit_semantics='RETAINED_LIST_RESPONSE_COUNT_NOT_DIRECTORY_EXHAUSTION',
        successful_query_count=(prior.get('successful_query_count',0) if prior and start else 0),
        failed_query_count=(prior.get('failed_query_count',0) if prior and start else 0))


def read_history(service: Any, date: str, context: Mapping) -> dict:
    from . import workspace_announcements as ann
    from .workspace import validate_attempt
    rows, rejected, gaps = committed_products(service, date)
    from .workspace_read_control import checkpoint
    captures = []; documents = []; seen = {}; successful = 0; latest_sweep = None
    failed_issuers=[];pending_count=0
    for product in rows:
        checkpoint()
        try:
            # Exclude future capture before revalidation of source/master state.
            if timestamp(product['generated_at']) > timestamp(context['research_cutoff']):
                raise ValueError('EASTMONEY_HK_CAPTURE_AFTER_CONSUMER_CUTOFF')
            ann._check_eastmoney_sources(service, product)
            docs, missing = ann._project_eastmoney_hk(product, context, rejection_audit=rejected)
            gaps.extend([*product.get('gaps',[]), *missing])
            cap = dict(source='EASTMONEY_HK', source_scope=product['source_scope'],
                target_trade_date=date, run_id=product['run_id'], sha256=product['sha256'],
                generated_at=product['generated_at'], query_cutoff=product['context']['research_cutoff'],
                queried_issuers=product['scope'], document_count=len(product['documents']),
                product_ref=f'workspace_announcements/{date}/eastmoney_hk/'+product['run_id']+'.json',
                source_status=product['status'], readback_status='VERIFIED', exhaustive=False,
                capture_budget=product['capture_budget'], hkex_first_publication_verified=False, **FLAGS)
            captures.append(cap)
            if product.get('sweep'):
                latest_sweep = product['sweep']
            successful += sum(q.get('status')=='OBSERVED' for q in product['queries'])
            failed_issuers.extend(dict(code=q.get('code'),reason=q.get('reason'),run_id=product['run_id'])
                for q in product['queries'] if q.get('status')!='OBSERVED')
            pending_count+=len(product['pending_documents'])
            for doc in docs:
                identity = (doc['symbol'], doc['art_code'], doc['body_sha256'])
                if identity not in seen:
                    seen[identity]=len(documents)
                    documents.append(dict(document=doc, capture=cap, occurrences=[deepcopy(cap)]))
                else:
                    documents[seen[identity]]['occurrences'].append(deepcopy(cap))
        except _ERRORS as exc:
            reason = ann.safe_reason(exc, 'EASTMONEY_HK_SOURCE_READBACK_FAILED')
            gaps.append(reason)
            rejected.append(dict(capture_trade_date=date, run_id=product['run_id'], reason=reason,
                                 source='EASTMONEY_HK'))
    attempt = None
    try:
        attempt = service.store._read(service.store.root/'workspace_announcement_runs'/date/'eastmoney_hk/latest.json')
        if attempt is not None:
            attempt = validate_attempt(attempt, date)
            if attempt.get('source_scope') != ann.EASTMONEY_SCOPE:
                raise ValueError('EASTMONEY_HK_ATTEMPT_SCOPE_INVALID')
            if timestamp(attempt['started_at']) > timestamp(context['research_cutoff']):
                attempt = None
            elif attempt.get('state') in {'FAILED','RUNNING'}:
                gaps.extend(attempt.get('failure_reasons',[]))
    except _ERRORS as exc:
        gaps.append(ann.safe_reason(exc, 'EASTMONEY_HK_ATTEMPT_READBACK_FAILED'))
    return dict(captures=captures, documents=documents, rejections=rejected, gaps=sorted(set(gaps)),
        attempt=attempt, coverage=dict(committed_run_count=len(captures), unique_document_count=len(documents),
        successful_query_count=successful,failed_issuers=failed_issuers,pending_document_count=pending_count,
        sweep=deepcopy(latest_sweep), directory_exhaustion='UNVERIFIED',
        all_announcements_captured=False, run_limit=MAX_RUNS, history_byte_limit=MAX_HISTORY_BYTES))
