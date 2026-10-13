"""Immutable capture publication and strict date/cutoff-bound native projection.

The complete raw catalogue remains in the core product. Derived consumption
excludes marked source-window outsiders; it never promotes mirror timing to PIT.
"""
from __future__ import annotations
import json
from pathlib import Path
from infrastructure.owned_io import SafeRoot
from ..contracts import digest
from .validation import before,time_value
from .capture_store import OWNER,encoded,sha
from .capture import resolve_publication_window,_catalog_page,_body_page


def _read(io, relative, expected):
    raw=io.read_bytes(relative)
    if sha(raw)!=expected:raise ValueError('CAPTURE_BOUND_SHA_MISMATCH')
    value=json.loads(raw)
    if not isinstance(value,dict):raise ValueError('CAPTURE_BOUND_OBJECT_INVALID')
    return value


def _source_ref(io, ref, cutoff):
    raw=io.read_bytes(ref['artifact_ref'])
    if sha(raw)!=ref['sha256'] or not before(ref['available_at'],cutoff):raise ValueError('CAPTURE_RAW_SHA_OR_CUTOFF_INVALID')
    if ref.get('owner')!='EASTMONEY_MIRROR':raise ValueError('CAPTURE_SOURCE_OWNER_INVALID')
    return raw


def validate_product(config, ref, context):
    io=SafeRoot(config.capture_root);product=_read(io,ref['artifact_ref'],ref['sha256'])
    if (product.get('schema_version')!='mwb.capture.window.v1' or product.get('owner')!=OWNER
            or product.get('source_scope')!='EASTMONEY_ONLY' or product.get('source')!='EASTMONEY_HK'
            or product.get('target_trade_date')!=context.target_date or product.get('market')!='HK_CONNECT'
            or any(product.get(k) is not False for k in ('production_allowed','buy_gate_updated','orders_sent'))):
        raise ValueError('CAPTURE_PRODUCT_OWNER_DATE_OR_SAFETY_INVALID')
    window=product['window'];expected=resolve_publication_window(context)
    if (window['target_trade_date']!=context.target_date or window['publication_window_mode']!=expected['publication_window_mode']
            or window['publication_window_start']!=expected['publication_window_start']
            or window['calendar_sha256']!=expected['calendar_sha256']
            or not before(window['research_cutoff'],context.cutoff)
            or window['publication_dates']!=[d for d in expected['publication_dates'] if d<=time_value(window['research_cutoff']).date().isoformat()]):
        raise ValueError('CAPTURE_PRODUCT_PUBLICATION_WINDOW_INVALID')
    # Directory pages keep exact-date, total and terminal evidence, including gaps.
    catalogues=product['catalogues']
    if [c['publication_date'] for c in catalogues]!=window['publication_dates']:raise ValueError('CAPTURE_CATALOGUE_DATES_INVALID')
    for catalogue in catalogues:
        for receipt in catalogue['page_receipts']:
            capsule={k:v for k,v in receipt.items() if k!='receipt_sha256'};capsule['from_cache']=False
            if sha(encoded(capsule))!=receipt['receipt_sha256']:raise ValueError('CAPTURE_PAGE_RECEIPT_SHA_INVALID')
            raw=io.read_bytes(receipt['artifact_ref'])
            if sha(raw)!=receipt['sha256'] or not before(receipt['available_at'],context.cutoff):raise ValueError('CAPTURE_PAGE_RAW_OR_TIME_INVALID')
            page=receipt['request']['url'].split('page_index=')[-1]
            _catalog_page(raw,catalogue['publication_date'],int(page),catalogue['total_hits'])
    if len(product['rows'])!=product['observed_count'] or product['rows']!=product['source_variants']:
        raise ValueError('CAPTURE_SOURCE_COUNTS_INVALID')
    seen=set()
    for article in product['rows']:
        key=(article['publication_date'],article['art_code'])
        if key in seen or article['owner']!='EASTMONEY_MIRROR':raise ValueError('CAPTURE_ARTICLE_OWNER_OR_DUPLICATE_INVALID')
        seen.add(key)
        original=_read(io,article['body_artifact_ref'],article['source_sha256'])
        if original!={k:v for k,v in article.items() if k not in {'body_artifact_ref','source_sha256'}}:
            raise ValueError('CAPTURE_BODY_ARTIFACT_IDENTITY_INVALID')
        for page in article['pages']:
            raw=_source_ref(io,page['source_ref'],context.cutoff)
            detail,_=_body_page(raw,article,page['page_number'],article['content_page_count'])
            if detail['notice_content']!=page['text'] or sha(page['text'].encode())!=page['text_sha256']:
                raise ValueError('CAPTURE_BODY_PAGE_TEXT_INVALID')
        if article['body_complete']:
            pages=article['pages'];text='\n\n'.join(p['text'] for p in pages)
            if (len(pages)!=article['content_page_count'] or [p['page_number'] for p in pages]!=list(range(1,len(pages)+1))
                    or text!=article['body_text'] or sha(text.encode())!=article['body_text_sha256']
                    or not before(article['available_at'],context.cutoff)):
                raise ValueError('CAPTURE_COMPLETE_BODY_INVALID')
    return product


def article_identity(article):
    return digest(dict(publication=article['publication_date'],article=article['art_code'],
        listing_sha=sha(encoded(article['raw_row'])),owner=article['owner'],body_sha=article['body_text_sha256'],
        complete=article['body_complete'],window=article['window_consumption_status'],
        pages=[{k:p['source_ref'][k] for k in ('sha256','artifact_ref','owner','source_url')} for p in article['pages']],gaps=article['gaps']))


def factual_identity(product):
    # Observation request time/run changes alone are not a new article material.
    return digest([article_identity(a) for a in product['rows']])


def publish(config, product, context, job_id):
    ref=product['saved_ref'];validated=validate_product(config,ref,context)
    available=max((r['available_at'] for r in validated['evidence_refs']),default=context.cutoff)
    material_refs={}
    try:
        previous_pin=resolve(config,context);previous_manifest,previous=read_binding(config,previous_pin,context)
        prior={article_identity(a):a for a in previous['rows'] if a['body_complete']}
        for article in validated['rows']:
            identity=article_identity(article)
            if article['body_complete'] and identity in prior:
                old_ref=previous_manifest.get('article_material_refs',{}).get(identity,previous_manifest['product_ref'])
                material_refs[identity]=old_ref
    except (OSError,ValueError,KeyError,TypeError):pass
    value=dict(schema='mwb.capture.binding.v1' ,owner=OWNER,target_date=context.target_date,capture_job_id=job_id,
        product_ref=ref,article_material_refs=material_refs,available_at=available,material_sha256=factual_identity(validated),window=validated['window'])
    raw=encoded(value);identity=sha(raw);relative=f'capture_bindings/{context.target_date}/{identity}.json'
    io=SafeRoot(Path(config.state_root)/'manager_workbench')
    try:io.write_bytes(relative,raw,require_absent=True)
    except FileExistsError:
        if io.read_bytes(relative)!=raw:raise ValueError('CAPTURE_BINDING_IMMUTABLE_CONFLICT')
    if io.read_bytes(relative)!=raw:raise ValueError('CAPTURE_BINDING_READBACK_FAILED')
    return dict(capture_binding_relative=relative,capture_binding_sha256=identity,material_sha256=value['material_sha256'],available_at=available)


def read_binding(config, pin, context):
    io=SafeRoot(Path(config.state_root)/'manager_workbench')
    manifest=_read(io,pin['capture_binding_relative'],pin['capture_binding_sha256'])
    if (manifest.get('schema')!='mwb.capture.binding.v1' or manifest.get('owner')!=OWNER
            or manifest.get('target_date')!=context.target_date or not before(manifest['available_at'],context.cutoff)):
        raise ValueError('CAPTURE_BINDING_DATE_OR_CUTOFF_INVALID')
    product=validate_product(config,manifest['product_ref'],context)
    if factual_identity(product)!=manifest['material_sha256']:raise ValueError('CAPTURE_MATERIAL_IDENTITY_INVALID')
    # Keep prior successful article material identities stable when only another
    # article/catalogue observation was added. Raw current product stays intact.
    if manifest.get('article_material_refs'):
        # Scope validation reuse to this read and the complete immutable ref.
        # Each unique product still passes raw SHA, time and window validation.
        validated={encoded(manifest['product_ref']):product};indexes={};rows=[]
        for article in product['rows']:
            identity=article_identity(article);old_ref=manifest['article_material_refs'].get(identity)
            if old_ref:
                key=encoded(old_ref)
                if key not in validated:validated[key]=validate_product(config,old_ref,context)
                if key not in indexes:
                    index={}
                    for prior in validated[key]['rows']:
                        if prior['body_complete']:index.setdefault(article_identity(prior),[]).append(prior)
                    indexes[key]=index
                matches=indexes[key].get(identity,[])
                if len(matches)!=1:raise ValueError('CAPTURE_PRIOR_MATERIAL_IDENTITY_INVALID')
                rows.append(matches[0])
            else:rows.append(article)
        product={**product,'rows':rows}
    return manifest,product


def resolve(config,context):
    root=Path(config.state_root)/'manager_workbench';candidates=[];failures=[]
    for path in sorted((root/'capture_bindings'/context.target_date).glob('*.json')):
        if path.is_symlink():continue
        pin=dict(capture_binding_relative=path.relative_to(root).as_posix(),capture_binding_sha256=path.stem)
        try:
            manifest,product=read_binding(config,pin,context)
            candidates.append((time_value(manifest['available_at']),pin))
        except (OSError,ValueError,KeyError,TypeError) as exc:failures.append(str(exc))
    if not candidates:raise ValueError('NEW_CAPTURE_OWNER_UNAVAILABLE_BEFORE_CUTOFF'+(':'+','.join(sorted(set(failures))) if failures else ''))
    return max(candidates,key=lambda x:(x[0],x[1]['capture_binding_sha256']))[1]
